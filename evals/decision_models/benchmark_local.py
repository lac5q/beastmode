#!/usr/bin/env python3
"""Run the pinned Decider prompt against a local llama.cpp completion server.

This module deliberately reads the *pre-sampling* token log-probabilities.  A
grammar is not used: llama.cpp can expose a grammar-masked distribution after
rejection sampling, which would make the reported probabilities unsuitable for
comparison.  The server therefore receives one ordinary completion request and
the adapter normalizes only the option-letter logits itself.

The input cases file is a JSON list.  A case may put ``state``, ``question`` and
``options`` at its top level or under an ``input`` object.  Other fields (for
example ``gold`` and ``rationale``) are never included in the prompt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:18089"
DEFAULT_TEMPERATURE = 1.935
DEFAULT_REPEATS = 2
COMPLETION_REQUEST = {
    "n_predict": 1,
    "temperature": 0,
    "n_probs": 512,
    "post_sampling_probs": False,
    "cache_prompt": False,
    "return_tokens": True,
    "seed": 0,
}
RECEIPT_FIELDS = ("repo", "revision", "file", "sha256", "bytes")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class BenchmarkError(RuntimeError):
    """An input, server, or response error that should be surfaced to callers."""


class ResponseParseError(BenchmarkError):
    """The server response cannot be trusted as a raw-logit result."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_value(value: Any) -> str:
    """Render structured state/options without Python repr or lossy coercion."""

    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def case_parts(case: Mapping[str, Any], index: int = 0) -> tuple[str, str, list[str], Any, str]:
    """Return id, state, options and expected answer without exposing extra fields."""

    source = case.get("input") if isinstance(case.get("input"), Mapping) else case
    if not isinstance(source, Mapping):
        raise BenchmarkError(f"case {index} input must be an object")

    case_id = case.get("id", case.get("case_id", str(index)))
    if case_id is None:
        case_id = str(index)
    case_id = str(case_id)

    if "state" not in source:
        raise BenchmarkError(f"case {case_id} is missing state")
    if "question" not in source:
        raise BenchmarkError(f"case {case_id} is missing question")
    if "options" not in source:
        raise BenchmarkError(f"case {case_id} is missing options")

    options_raw = source["options"]
    if not isinstance(options_raw, Sequence) or isinstance(options_raw, (str, bytes, bytearray)):
        raise BenchmarkError(f"case {case_id} options must be a list")
    if not options_raw:
        raise BenchmarkError(f"case {case_id} must have at least one option")
    if len(options_raw) > 26:
        raise BenchmarkError(f"case {case_id} has {len(options_raw)} options; A-Z supports at most 26")

    options: list[str] = []
    for option_index, option in enumerate(options_raw):
        if isinstance(option, Mapping):
            if "text" not in option:
                raise BenchmarkError(f"case {case_id} option {option_index} is missing text")
            option = option["text"]
        options.append(_json_value(option))

    expected = case.get("gold", case.get("expected", case.get("answer")))
    if expected is None and isinstance(source, Mapping):
        expected = source.get("gold", source.get("expected", source.get("answer")))
    return case_id, _json_value(source["state"]), options, expected, str(source["question"])


def build_prompt(case: Mapping[str, Any], index: int = 0) -> str:
    """Build the exact state-first Decider prompt required by the protocol."""

    _case_id, state, options, _expected, question = case_parts(case, index)
    labels = [chr(ord("A") + i) for i in range(len(options))]
    option_block = "".join(f"\n({label}) {option}" for label, option in zip(labels, options))
    return f"Context:\n{state}\n\nQuestion: {question}\nOptions:{option_block}\nAnswer: ("


def option_labels(option_count: int) -> list[str]:
    if option_count < 1 or option_count > 26:
        raise BenchmarkError(f"option count must be between 1 and 26, got {option_count}")
    return [chr(ord("A") + i) for i in range(option_count)]


def load_cases(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"invalid cases JSON: {path}: {exc}") from exc
    if not isinstance(value, list):
        raise BenchmarkError("cases file must contain a JSON list")
    cases: list[dict[str, Any]] = []
    for index, case in enumerate(value):
        if not isinstance(case, dict):
            raise BenchmarkError(f"case {index} must be a JSON object")
        # Validate the fields now, before touching the server, so a malformed
        # frozen case set cannot produce a partial benchmark.
        case_parts(case, index)
        cases.append(case)
    return cases, sha256_bytes(raw)


def _canonical_cases_sha256(cases: Sequence[Mapping[str, Any]]) -> str:
    """Match benchmark_api's canonical case hash when that harness is present."""

    try:
        module = importlib.import_module("benchmark_api")
    except ImportError:
        module = None
    fn = getattr(module, "cases_sha256", None) if module is not None else None
    if callable(fn):
        value = fn(cases)
        if isinstance(value, str) and SHA256_RE.fullmatch(value):
            return value
    return sha256_bytes(json_bytes(list(cases)))


def load_model_receipt(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"invalid model receipt {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BenchmarkError("model receipt must be a JSON object")
    missing = [field for field in RECEIPT_FIELDS if field not in value]
    if missing:
        raise BenchmarkError(f"model receipt missing fields: {', '.join(missing)}")
    if not all(isinstance(value[field], str) and value[field] for field in ("repo", "revision", "file")):
        raise BenchmarkError("model receipt repo, revision, and file must be non-empty strings")
    if not isinstance(value["bytes"], int) or isinstance(value["bytes"], bool) or value["bytes"] < 0:
        raise BenchmarkError("model receipt bytes must be a non-negative integer")
    if not isinstance(value["sha256"], str) or not SHA256_RE.fullmatch(value["sha256"]):
        raise BenchmarkError("model receipt sha256 must be a 64-character hexadecimal digest")
    return value


def _url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def request_json(
    base_url: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    *,
    timeout: float = 300.0,
) -> tuple[Any, float]:
    """Make one JSON request and return decoded JSON plus wall-clock seconds."""

    body = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = Request(_url(base_url, path), data=body, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read()
            status = getattr(response, "status", 200)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise BenchmarkError(f"HTTP {exc.code} {path}: {detail[:1000]}") from exc
    except URLError as exc:
        raise BenchmarkError(f"request failed {path}: {exc.reason}") from exc
    except OSError as exc:
        raise BenchmarkError(f"request failed {path}: {exc}") from exc
    elapsed = time.perf_counter() - started
    if status < 200 or status >= 300:
        raise BenchmarkError(f"HTTP {status} {path}")
    try:
        return json.loads(response_body.decode("utf-8")), elapsed
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"non-JSON response from {path}: {exc}") from exc


def inspect_props(base_url: str, *, timeout: float = 300.0) -> dict[str, Any]:
    """Inspect server props, retaining an explicit unverified state on failure."""

    try:
        props, _elapsed = request_json(base_url, "/props", timeout=timeout)
    except BenchmarkError as exc:
        return {
            "props": None,
            "props_error": str(exc),
            "loaded_model_file": None,
            "default_generation_model": None,
            "loaded_model_source": None,
            "model_alias": None,
            "loaded_model_status": "unverified",
        }
    if not isinstance(props, dict):
        return {
            "props": props,
            "props_error": "GET /props did not return a JSON object",
            "loaded_model_file": None,
            "default_generation_model": None,
            "loaded_model_source": None,
            "model_alias": None,
            "loaded_model_status": "unverified",
        }
    defaults = props.get("default_generation_settings")
    default_model = defaults.get("model") if isinstance(defaults, dict) else None
    model_path = props.get("model_path")
    model_alias = props.get("model_alias")
    if isinstance(model_path, str) and model_path:
        observed = model_path
        observed_source = "model_path"
    elif isinstance(default_model, str) and default_model:
        observed = default_model
        observed_source = "default_generation_settings.model"
    else:
        observed = None
        observed_source = None
    if not isinstance(model_alias, str) or not model_alias:
        model_alias = None
    return {
        "props": props,
        "props_error": None,
        "loaded_model_file": observed,
        "default_generation_model": default_model if isinstance(default_model, str) else None,
        "loaded_model_source": observed_source,
        "model_alias": model_alias,
        "loaded_model_status": "reported" if observed else "unverified",
    }


def completion_payload(prompt: str) -> dict[str, Any]:
    payload = {"prompt": prompt}
    payload.update(COMPLETION_REQUEST)
    return payload


def _top_logprobs(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    completions = response.get("completion_probabilities")
    if isinstance(completions, list) and completions:
        first = completions[0]
        if isinstance(first, Mapping):
            top = first.get("top_logprobs")
            if isinstance(top, list):
                return [entry for entry in top if isinstance(entry, Mapping)]
            if isinstance(top, Mapping):
                return [{"token": token, "logprob": value} for token, value in top.items()]

    # A small compatibility fallback for server builds that expose the same
    # native object under ``probs`` rather than ``completion_probabilities``.
    probs = response.get("probs")
    if isinstance(probs, list) and probs:
        first = probs[0]
        if isinstance(first, Mapping):
            top = first.get("top_logprobs")
            if isinstance(top, list):
                return [entry for entry in top if isinstance(entry, Mapping)]
            if isinstance(top, Mapping):
                return [{"token": token, "logprob": value} for token, value in top.items()]
    raise ResponseParseError("response has no pre-sampling top_logprobs")


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResponseParseError(f"{field} is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ResponseParseError(f"{field} is non-finite")
    return number


def parse_raw_probabilities(
    response: Mapping[str, Any],
    labels: Sequence[str],
    release_temperature: float,
) -> dict[str, Any]:
    """Parse and renormalize only exact candidate letter tokens.

    Missing labels and non-finite log-probabilities are hard errors.  In
    particular, this function never fills an absent option with zero.
    """

    temperature = _finite_number(release_temperature, "release temperature")
    if temperature <= 0:
        raise ResponseParseError("release temperature must be greater than zero")
    if not labels:
        raise ResponseParseError("no option labels supplied")

    entries = _top_logprobs(response)
    logprobs: dict[str, float] = {}
    for entry in entries:
        token = entry.get("token")
        # Deliberately require exact token text.  A leading-space token or a
        # token id without its decoded text cannot safely be equated to A/B/...
        if not isinstance(token, str) or token not in labels:
            continue
        if token in logprobs:
            raise ResponseParseError(f"duplicate top-logprob token {token!r}")
        logprobs[token] = _finite_number(entry.get("logprob"), f"logprob[{token}]")

    missing = [label for label in labels if label not in logprobs]
    if missing:
        raise ResponseParseError("missing option token(s): " + ", ".join(missing))

    scaled = {label: logprobs[label] / temperature for label in labels}
    maximum = max(scaled.values())
    weights = {label: math.exp(value - maximum) for label, value in scaled.items()}
    total = sum(weights.values())
    if not math.isfinite(total) or total <= 0:
        raise ResponseParseError("restricted softmax total is non-finite or non-positive")
    probabilities = {label: weights[label] / total for label in labels}
    if any(not math.isfinite(value) for value in probabilities.values()):
        raise ResponseParseError("restricted softmax produced a non-finite probability")
    choice = max(labels, key=lambda label: probabilities[label])
    return {
        "choice": choice,
        "logprobs": logprobs,
        "probabilities": probabilities,
        "labels": list(labels),
        "temperature": temperature,
    }


def _first_value(objects: Iterable[Mapping[str, Any]], keys: Sequence[str]) -> Any:
    for obj in objects:
        for key in keys:
            if key in obj and obj[key] is not None:
                return obj[key]
    return None


def extract_usage(response: Mapping[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    timings = response.get("timings") if isinstance(response.get("timings"), Mapping) else {}
    sources = [timings, response]
    tokens_predicted = _first_value(sources, ("predicted_n", "tokens_predicted", "completion_tokens"))
    if tokens_predicted is None and isinstance(response.get("tokens"), list):
        tokens_predicted = len(response["tokens"])
    tokens_evaluated = _first_value(sources, ("prompt_n", "tokens_evaluated", "tokens_prompt"))
    prompt_n = _first_value(sources, ("prompt_n", "tokens_evaluated", "tokens_prompt"))
    return {
        "tokens_predicted": tokens_predicted,
        "tokens_evaluated": tokens_evaluated,
        "prompt_n": prompt_n,
        "latency_ms": elapsed_seconds * 1000.0,
        "backend_timings": dict(timings) if isinstance(timings, Mapping) else timings,
    }


def _expected_label(expected: Any, options: Sequence[str]) -> str | None:
    if expected is None:
        return None
    if isinstance(expected, str):
        value = expected.strip().upper()
        if len(value) == 1 and "A" <= value <= "Z" and ord(value) - ord("A") < len(options):
            return value
        if expected in options:
            return chr(ord("A") + options.index(expected))
    if isinstance(expected, int) and not isinstance(expected, bool) and 0 <= expected < len(options):
        return chr(ord("A") + expected)
    return None


def _server_observed(response: Mapping[str, Any], props_info: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model": response.get("model"),
        "loaded_model_file": props_info.get("loaded_model_file"),
        "default_generation_model": props_info.get("default_generation_model"),
        "loaded_model_source": props_info.get("loaded_model_source"),
        "model_alias": props_info.get("model_alias"),
        "loaded_model_status": props_info.get("loaded_model_status", "unverified"),
    }


def _basename(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value).name


def _model_provenance(
    response_model: Any,
    props_info: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> tuple[bool | None, dict[str, Any]]:
    """Require both server observations to name the receipt's file.

    A missing observation is UNKNOWN and therefore invalid for benchmark
    claims.  An alias alone is not accepted as file provenance.
    """

    expected = _basename(receipt.get("file"))
    response_file = _basename(response_model)
    props_file = _basename(props_info.get("loaded_model_file"))
    details = {
        "receipt_file": expected,
        "response_model_file": response_file,
        "props_model_file": props_file,
        "model_alias": props_info.get("model_alias"),
    }
    if not expected or not response_file or not props_file:
        return None, details
    return response_file == expected and props_file == expected, details


def run_one(
    case: Mapping[str, Any],
    *,
    index: int,
    base_url: str,
    model_id: str,
    release_temperature: float,
    receipt: Mapping[str, Any],
    props_info: Mapping[str, Any],
    cases_sha256: str,
    pass_index: int,
    repeat_index: int,
    timeout: float = 300.0,
) -> dict[str, Any]:
    case_id, _state, options, expected, _question = case_parts(case, index)
    prompt = build_prompt(case, index)
    labels = option_labels(len(options))
    payload = completion_payload(prompt)
    row: dict[str, Any] = {
        "record_type": "decision",
        "case_id": case_id,
        "pass": pass_index,
        "repeat": repeat_index,
        "prompt": prompt,
        "requested": {
            "base_url": base_url,
            "model_id": model_id,
            "temperature": release_temperature,
            "endpoint": "/completion",
            "completion": payload,
        },
        "provenance": {
            "cases_sha256": cases_sha256,
            "model_receipt": dict(receipt),
            "server_props": props_info.get("props"),
            "server_props_error": props_info.get("props_error"),
        },
        "observed": {
            "model": None,
            "loaded_model_file": props_info.get("loaded_model_file"),
            "default_generation_model": props_info.get("default_generation_model"),
            "loaded_model_source": props_info.get("loaded_model_source"),
            "model_alias": props_info.get("model_alias"),
            "loaded_model_status": props_info.get("loaded_model_status", "unverified"),
        },
        "raw": None,
        "usage": None,
        "status": "error",
        "choice": None,
        "choice_label": None,
        "valid": False,
        "model_match": None,
        "actual_model": None,
        "category": case.get("category"),
        "id": case_id,
        "provider": "local",
        "model": model_id,
        "gold": expected,
        "prompt_tokens": None,
        "completion_tokens": None,
        "latency_ms": None,
        "cost_usd": None,
        "cost_source": None,
        "confidence": None,
        "probabilities": None,
        "expected": expected,
        "correct": None,
        "error": None,
        "local_cost": None,
        "payload": payload,
    }
    try:
        response, elapsed = request_json(base_url, "/completion", payload, timeout=timeout)
        if not isinstance(response, Mapping):
            raise ResponseParseError("completion response must be a JSON object")
        response_dict = dict(response)
        row["raw"] = response_dict
        row["usage"] = extract_usage(response_dict, elapsed)
        row["observed"] = _server_observed(response_dict, props_info)
        row["actual_model"] = response_dict.get("model")
        model_match, model_details = _model_provenance(response_dict.get("model"), props_info, receipt)
        row["model_match"] = model_match
        row["provenance"]["model_observation"] = model_details
        row["prompt_tokens"] = row["usage"].get("tokens_evaluated")
        row["completion_tokens"] = row["usage"].get("tokens_predicted")
        row["latency_ms"] = row["usage"].get("latency_ms")
        parsed = parse_raw_probabilities(response_dict, labels, release_temperature)
        row["status"] = "ok"
        selected_index = labels.index(parsed["choice"])
        row["choice_label"] = parsed["choice"]
        row["choice"] = options[selected_index]
        row["valid"] = model_match is True
        row["letter_probabilities"] = parsed["probabilities"]
        row["probabilities"] = {
            options[index]: parsed["probabilities"][label]
            for index, label in enumerate(labels)
        }
        row["logprobs"] = parsed["logprobs"]
        expected_label = _expected_label(expected, options)
        row["correct"] = bool(row["valid"] and expected_label is not None and expected_label == parsed["choice"])
        if model_match is None:
            row["status"] = "invalid"
            row["error"] = {
                "type": "model_provenance_unverified",
                "message": "response model and props model file are both required to match receipt.file",
            }
        elif model_match is False:
            row["status"] = "invalid"
            row["error"] = {
                "type": "model_mismatch",
                "message": "response model and props model file do not both match receipt.file",
            }
    except BenchmarkError as exc:
        row["error"] = {"type": type(exc).__name__, "message": str(exc)}
        # A response with unusable/missing logits is an invalid model result;
        # transport/HTTP failures remain infrastructure errors.
        row["status"] = "invalid" if isinstance(exc, ResponseParseError) else "error"
        if row["raw"] is not None and row["usage"] is None:
            row["usage"] = {"latency_ms": None}
    return row


def _warmup(cases: Sequence[Mapping[str, Any]], base_url: str, timeout: float) -> tuple[Any, float] | None:
    if not cases:
        return None
    prompt = build_prompt(cases[0], 0)
    response, elapsed = request_json(base_url, "/completion", completion_payload(prompt), timeout=timeout)
    return response, elapsed


def _local_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    latencies: list[float] = []
    judged = 0
    correct = 0
    for row in rows:
        status = str(row.get("status", "unknown"))
        statuses[status] = statuses.get(status, 0) + 1
        usage = row.get("usage")
        if isinstance(usage, Mapping) and isinstance(usage.get("latency_ms"), (int, float)):
            value = float(usage["latency_ms"])
            if math.isfinite(value):
                latencies.append(value)
        if row.get("correct") is not None:
            judged += 1
            correct += int(bool(row.get("correct")))

    def percentile(values: Sequence[float], q: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
        return ordered[index]

    return {
        "rows": len(rows),
        "statuses": statuses,
        "judged": judged,
        "correct": correct,
        "accuracy": (correct / judged) if judged else None,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
        "local_cost": None,
    }


def summarize(rows: Sequence[Mapping[str, Any]], *, model: str | None = None) -> dict[str, Any]:
    """Use the sibling API harness' in-memory summary when available."""

    for module_name in ("benchmark_api", "evals.decision_models.benchmark_api"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        fn = getattr(module, "summarize_records", None)
        if callable(fn):
            try:
                value = fn(rows, provider="local", model=model)
            except TypeError:
                value = fn(list(rows))
            if isinstance(value, Mapping):
                return dict(value)
    return _local_summary(rows)


def run_benchmark(
    *,
    cases_path: Path,
    output_path: Path,
    base_url: str = DEFAULT_BASE_URL,
    model_id: str,
    model_receipt_path: Path,
    release_temperature: float = DEFAULT_TEMPERATURE,
    repeats: int = DEFAULT_REPEATS,
    timeout: float = 300.0,
) -> dict[str, Any]:
    if repeats < 1:
        raise BenchmarkError("repeats must be at least one")
    cases, raw_cases_sha256 = load_cases(cases_path)
    cases_sha256 = _canonical_cases_sha256(cases)
    receipt = load_model_receipt(model_receipt_path)
    props_info = inspect_props(base_url, timeout=timeout)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    # Warmup is intentionally excluded from rows and all reported timings, but
    # retain its raw exchange beside the JSONL for auditability.
    warmup_path = output_path.with_name(f"{output_path.stem}.warmup.json")
    warmup_response, warmup_elapsed = _warmup(cases, base_url, timeout) or (None, None)
    warmup_record = {
        "warmup": True,
        "included_in_metrics": False,
        "payload": completion_payload(build_prompt(cases[0], 0)) if cases else None,
        "raw": warmup_response,
        "latency_ms": warmup_elapsed * 1000.0 if isinstance(warmup_elapsed, (int, float)) else None,
    }
    warmup_path.write_text(
        json.dumps(warmup_record, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with output_path.open("w", encoding="utf-8") as output:
        for pass_index in range(1, repeats + 1):
            for index, case in enumerate(cases):
                row = run_one(
                    case,
                    index=index,
                    base_url=base_url,
                    model_id=model_id,
                    release_temperature=release_temperature,
                    receipt=receipt,
                    props_info=props_info,
                    cases_sha256=cases_sha256,
                    pass_index=pass_index,
                    repeat_index=pass_index,
                    timeout=timeout,
                )
                rows.append(row)
                output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                output.flush()
    return {
        "summary": summarize(rows, model=model_id),
        "rows": rows,
        "metadata": {
            "cases_sha256": cases_sha256,
            "cases_file_sha256": raw_cases_sha256,
            "case_count": len(cases),
            "repeats": repeats,
            "base_url": base_url,
            "model_id": model_id,
            "model_receipt": receipt,
            "server_props": props_info.get("props"),
            "server_props_error": props_info.get("props_error"),
            "loaded_model_file": props_info.get("loaded_model_file"),
            "default_generation_model": props_info.get("default_generation_model"),
            "loaded_model_source": props_info.get("loaded_model_source"),
            "model_alias": props_info.get("model_alias"),
            "loaded_model_status": props_info.get("loaded_model_status"),
            "warmup_path": str(warmup_path),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="frozen JSON case list")
    parser.add_argument("--output", type=Path, required=True, help="per-row JSONL output")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model-id", required=True, help="requested model identifier for provenance")
    parser.add_argument("--model-receipt", type=Path, required=True)
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="release temperature used only to rescale raw option logprobs (default: %(default)s)",
    )
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_benchmark(
            cases_path=args.cases,
            output_path=args.output,
            base_url=args.base_url,
            model_id=args.model_id,
            model_receipt_path=args.model_receipt,
            release_temperature=args.temperature,
            repeats=args.repeats,
            timeout=args.timeout,
        )
    except BenchmarkError as exc:
        print(f"benchmark_local: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
