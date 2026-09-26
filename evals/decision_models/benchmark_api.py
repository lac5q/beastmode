"""Small, serial HTTP benchmark runner for decision-model API comparisons.

The module deliberately uses only the Python standard library.  It is kept
outside the Beastmode package because this is an isolated evaluation harness,
not a runtime routing feature.

The public helpers are useful to the local adapters as well as the command
line runner:

``parse_record(raw, provider, model, case, ...)``
    Turn one provider response into the common result record shape.

``summarize(output_path, ...)``
    Read a JSONL result file, write its sibling ``.summary.json`` file, and
    return the summary dictionary.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence


PROVIDER_ENDPOINTS = {
    "jev": "https://api.typesafe.ai/v1/systemone",
    "simplejev": "https://simple-jev-demo-api.featherless.ai/v1/systemone",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}

PROVIDER_KEY_ENV = {
    "jev": "TYPESAFE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "simplejev": None,
}

_REQUIRED_CASE_FIELDS = (
    "id",
    "category",
    "state",
    "question",
    "options",
    "gold",
    "rationale",
)
_STOP_STATUSES = frozenset({401, 403, 429})
_SIMPLEJEV_MIN_INTERVAL_SECONDS = 0.6
_JEV_ESTIMATED_PROMPT_RATE_USD_PER_MILLION = 0.042
_HTTP_TIMEOUT_SECONDS = 120.0


class BenchmarkError(Exception):
    """Base class for expected benchmark setup and provider failures."""


class ConfigurationError(BenchmarkError):
    """Raised when the cases or command-line configuration is invalid."""


class ProviderHalt(BenchmarkError):
    """Raised after a recorded authentication or rate-limit response."""

    def __init__(self, status: int):
        self.status = status
        # Keep this message deliberately free of exception text, response
        # bodies, headers, URLs containing credentials, or key material.
        super().__init__(f"provider stopped after HTTP status {status}")


def _utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def cases_sha256(cases: Sequence[Mapping[str, Any]]) -> str:
    """Return the stable hash of the validated, canonical case list."""

    return hashlib.sha256(_canonical_json(cases).encode("utf-8")).hexdigest()


# A descriptive alias makes call sites that use ``sha256_cases`` easy to read.
sha256_cases = cases_sha256


def validate_cases(cases: Any) -> list[dict[str, Any]]:
    """Validate and copy a case list before any provider request is made."""

    if not isinstance(cases, list) or not cases:
        raise ConfigurationError("cases must be a non-empty JSON list")

    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(cases):
        if not isinstance(value, Mapping):
            raise ConfigurationError(f"case {index} must be a JSON object")
        missing = [field for field in _REQUIRED_CASE_FIELDS if field not in value]
        if missing:
            raise ConfigurationError(f"case {index} missing required fields: {', '.join(missing)}")

        case = dict(value)
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id:
            raise ConfigurationError(f"case {index} id must be a non-empty string")
        if case_id in seen_ids:
            raise ConfigurationError(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)

        for text_field in ("category", "question", "rationale"):
            if not isinstance(case[text_field], str):
                raise ConfigurationError(f"case {case_id} field {text_field} must be a string")

        options = case["options"]
        if not isinstance(options, list) or not options:
            raise ConfigurationError(f"case {case_id} options must be a non-empty list")
        if any(not isinstance(option, str) for option in options):
            raise ConfigurationError(f"case {case_id} options must contain strings")
        if len(set(options)) != len(options):
            raise ConfigurationError(f"case {case_id} options must be unique")
        if not isinstance(case["gold"], str) or case["gold"] not in options:
            raise ConfigurationError(f"case {case_id} gold must be one of options")

        # This catches unserializable state and non-finite values before a
        # request is attempted, while allowing arbitrary JSON state shape.
        try:
            _canonical_json(case)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"case {case_id} is not valid JSON") from exc
        validated.append(case)
    return validated


def load_cases(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Load and validate the frozen cases JSON file."""

    case_path = Path(path)
    try:
        cases = json.loads(case_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"could not read cases file: {case_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"cases file is not valid JSON: {case_path}") from exc
    return validate_cases(cases)


def _require_provider(provider: str) -> None:
    if provider not in PROVIDER_ENDPOINTS:
        allowed = ", ".join(PROVIDER_ENDPOINTS)
        raise ConfigurationError(f"provider must be one of: {allowed}")


def _jev_payload(case: Mapping[str, Any], model: str) -> dict[str, Any]:
    return {
        "state": case["state"],
        "model": model,
        "questions": {
            "decision": {
                "type": "choice",
                "instructions": case["question"],
                "criteria": {option: None for option in case["options"]},
            }
        },
    }


def _openrouter_prompt(case: Mapping[str, Any]) -> str:
    instruction = (
        'Return exactly JSON {"choice":"<one of the options>"}; '
        "do not include any other keys or prose."
    )
    prompt_object = {
        "state": case["state"],
        "question": case["question"],
        "options": case["options"],
        "instruction": instruction,
    }
    return _canonical_json(prompt_object)


def _openrouter_payload(case: Mapping[str, Any], model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": _openrouter_prompt(case)}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 256,
        "reasoning": {"effort": "none"},
    }


def build_payload(provider: str, case: Mapping[str, Any], model: str) -> dict[str, Any]:
    """Build the exact provider request body, without transport headers."""

    _require_provider(provider)
    if provider in ("jev", "simplejev"):
        return _jev_payload(case, model)
    return _openrouter_payload(case, model)


def _optional_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


def _mapping_value(mapping: Any, *keys: str) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _usage_value(usage: Any, *keys: str) -> int | float | None:
    if not isinstance(usage, Mapping):
        return None
    for key in keys:
        if key in usage:
            return _optional_number(usage[key])
    return None


def _reported_cost(raw: Any, usage: Any) -> tuple[int | float | None, str | None]:
    for source, mapping in (("usage", usage), ("response", raw)):
        if not isinstance(mapping, Mapping):
            continue
        for key in ("cost_usd", "cost"):
            if key in mapping:
                value = _optional_number(mapping[key])
                if value is not None:
                    return value, "provider_reported"
    return None, None


def _decode_json_text(text: str) -> tuple[Any, bool]:
    try:
        return json.loads(text), True
    except (json.JSONDecodeError, TypeError):
        return text, False


def _as_raw_value(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8", errors="replace")
    if isinstance(raw, str):
        return _decode_json_text(raw)[0]
    return raw


def _jev_answer(raw: Mapping[str, Any]) -> Mapping[str, Any] | None:
    candidate: Any = raw.get("answer")
    if candidate is None:
        candidate = raw.get("answers")
    if isinstance(candidate, Mapping):
        if "choice" in candidate:
            return candidate
        for key in ("decision", "answer"):
            nested = candidate.get(key)
            if isinstance(nested, Mapping):
                return nested
        for nested in candidate.values():
            if isinstance(nested, Mapping) and "choice" in nested:
                return nested
    elif isinstance(candidate, list):
        for nested in candidate:
            if isinstance(nested, Mapping) and "choice" in nested:
                return nested
    return None


def parse_record(
    raw: Any,
    provider: str,
    model: str,
    case: Mapping[str, Any],
    payload: Mapping[str, Any] | None = None,
    latency_ms: float | None = None,
    *,
    http_status: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Normalize one response into the common JSONL record shape.

    ``valid`` requires a parseable allowed choice and an exact requested /
    observed model match.  A model mismatch therefore cannot accidentally
    contribute a correct answer to a benchmark summary.
    """

    _require_provider(provider)
    raw_was_invalid_json = isinstance(raw, (str, bytes, bytearray))
    raw_value = _as_raw_value(raw)
    if raw_was_invalid_json and isinstance(raw_value, str):
        raw_was_invalid_json = True
    else:
        raw_was_invalid_json = False
    response = raw_value if isinstance(raw_value, Mapping) else None

    actual_model = response.get("model") if response is not None else None
    model_match = isinstance(actual_model, str) and actual_model == model
    choice: Any = None
    probabilities: Any = None
    confidence: Any = None
    prompt_tokens: int | float | None = None
    completion_tokens: int | float | None = None
    cost_usd: int | float | None = None
    cost_source: str | None = None
    parse_error: str | None = error

    usage = response.get("usage") if response is not None else None
    if provider in ("jev", "simplejev"):
        if response is None:
            parse_error = parse_error or "invalid_response"
        else:
            answer = _jev_answer(response)
            if answer is None:
                parse_error = parse_error or "invalid_response"
            else:
                choice = answer.get("choice")
                probabilities = _mapping_value(answer, "probs", "probabilities")
                if probabilities is None:
                    probabilities = _mapping_value(response, "probs", "probabilities")
                confidence = _mapping_value(answer, "confidence")
                if confidence is None:
                    confidence = _mapping_value(response, "confidence")
            prompt_tokens = _usage_value(usage, "input_tokens", "prompt_tokens")
            completion_tokens = _usage_value(usage, "output_tokens", "completion_tokens")
    else:
        if response is None:
            parse_error = parse_error or ("invalid_json" if raw_was_invalid_json else "invalid_response")
        else:
            choices = response.get("choices")
            message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], Mapping) else None
            content = message.get("content") if isinstance(message, Mapping) else None
            if isinstance(content, str):
                parsed_content, parsed_ok = _decode_json_text(content)
                if parsed_ok and isinstance(parsed_content, Mapping):
                    choice = parsed_content.get("choice")
                else:
                    parse_error = parse_error or "invalid_json"
            elif isinstance(content, Mapping):
                choice = content.get("choice")
            else:
                parse_error = parse_error or "invalid_response"
            prompt_tokens = _usage_value(usage, "prompt_tokens", "input_tokens")
            completion_tokens = _usage_value(usage, "completion_tokens", "output_tokens")

    cost_usd, cost_source = _reported_cost(response, usage)
    if response is None:
        parse_error = parse_error or "invalid_response"
    elif not model_match:
        parse_error = parse_error or ("missing_model" if actual_model is None else "model_mismatch")
    elif choice not in case.get("options", []):
        parse_error = parse_error or "invalid_choice"

    valid = parse_error is None and model_match and choice in case.get("options", [])
    correct = bool(valid and choice == case.get("gold"))
    return {
        "id": case.get("id"),
        "category": case.get("category"),
        "provider": provider,
        "model": model,
        "actual_model": actual_model,
        "model_match": model_match,
        "choice": choice,
        "gold": case.get("gold"),
        "correct": correct,
        "valid": valid,
        "latency_ms": latency_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": cost_usd,
        "cost_source": cost_source,
        "probabilities": probabilities,
        "confidence": confidence,
        "http_status": http_status,
        "error": parse_error,
        "raw": raw_value,
        "payload": dict(payload) if isinstance(payload, Mapping) else payload,
    }


def _http_post(endpoint: str, payload: Mapping[str, Any], api_key: str | None, provider: str) -> dict[str, Any]:
    """Perform one request and return a sanitized exchange envelope."""

    body = _canonical_json(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if provider == "simplejev":
        headers["User-Agent"] = "beastmode-decision-spike/1.0 (+https://github.com/lac5q/beastmode)"
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    started = time.perf_counter()
    try:
        response = urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS)
        try:
            response_body = response.read()
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        raw_text = bytes(response_body).decode("utf-8", errors="replace") if isinstance(response_body, (bytes, bytearray)) else str(response_body)
        raw, _ = _decode_json_text(raw_text)
        status_value = int(status) if status is not None else None
        return {
            "raw": raw,
            "http_status": status_value,
            "transport_error": (
                "http_error"
                if status_value is not None and (status_value < 200 or status_value >= 300)
                else None
            ),
            "latency_ms": (time.perf_counter() - started) * 1000.0,
        }
    except urllib.error.HTTPError as exc:
        # HTTPError.read() is response data, not the exception string.  Keep
        # the exception itself out of records, especially for 401/403 bodies.
        try:
            response_body = exc.read()
        except Exception:
            response_body = b""
        raw_text = bytes(response_body).decode("utf-8", errors="replace") if isinstance(response_body, (bytes, bytearray)) else str(response_body)
        raw, _ = _decode_json_text(raw_text)
        return {
            "raw": raw if raw_text else None,
            "http_status": int(exc.code),
            "transport_error": "http_error",
            "latency_ms": (time.perf_counter() - started) * 1000.0,
        }
    except (urllib.error.URLError, TimeoutError, OSError):
        return {
            "raw": None,
            "http_status": None,
            "transport_error": "network_error",
            "latency_ms": (time.perf_counter() - started) * 1000.0,
        }


def _api_key(provider: str) -> str | None:
    env_name = PROVIDER_KEY_ENV[provider]
    if env_name is None:
        return None
    value = os.environ.get(env_name)
    if not value:
        raise ConfigurationError(f"missing API key environment variable {env_name}")
    return value


def _space_simplejev(last_start: float | None) -> float:
    """Sleep as needed so request *starts* are 0.6s apart."""

    if last_start is None:
        return time.monotonic()
    now = time.monotonic()
    remaining = _SIMPLEJEV_MIN_INTERVAL_SECONDS - (now - last_start)
    if remaining > 0:
        time.sleep(remaining)
    return time.monotonic()


def _request_case(
    case: Mapping[str, Any],
    provider: str,
    model: str,
    api_key: str | None,
    *,
    last_start: float | None,
    measure: bool,
) -> tuple[dict[str, Any], float]:
    if provider == "simplejev":
        last_start = _space_simplejev(last_start)
    else:
        last_start = time.monotonic()

    payload = build_payload(provider, case, model)
    exchange = _http_post(PROVIDER_ENDPOINTS[provider], payload, api_key, provider)
    transport_error = exchange["transport_error"]
    record_error = transport_error
    record = parse_record(
        exchange["raw"],
        provider,
        model,
        case,
        payload,
        exchange["latency_ms"] if measure else None,
        http_status=exchange["http_status"],
        error=record_error,
    )
    if transport_error is not None:
        record["valid"] = False
        record["correct"] = False
        record["model_match"] = False
    return record, last_start


def _sibling_json_path(path: str | os.PathLike[str], label: str) -> Path:
    output = Path(path)
    stem = output.name[:-len(output.suffix)] if output.suffix else output.name
    return output.with_name(f"{stem}.{label}.json")


def metadata_path_for(output: str | os.PathLike[str]) -> Path:
    return _sibling_json_path(output, "meta")


def warmup_path_for(output: str | os.PathLike[str]) -> Path:
    return _sibling_json_path(output, "warmup")


def summary_path_for(output: str | os.PathLike[str]) -> Path:
    return _sibling_json_path(output, "summary")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()


def run_benchmark(
    cases: Sequence[Mapping[str, Any]],
    output: str | os.PathLike[str],
    provider: str,
    model: str,
    repeats: int = 2,
) -> dict[str, Any]:
    """Run a validated case list serially and write JSONL plus sidecars."""

    _require_provider(provider)
    validated_cases = validate_cases(list(cases))
    if not isinstance(model, str) or not model:
        raise ConfigurationError("model must be a non-empty string")
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
        raise ConfigurationError("repeats must be a positive integer")

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = metadata_path_for(output_path)
    warmup_path = warmup_path_for(output_path)
    cases_hash = cases_sha256(validated_cases)
    started_at = _utc_now()
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "started_at_utc": started_at,
        "provider": provider,
        "model": model,
        "endpoint": PROVIDER_ENDPOINTS[provider],
        "api_key_env": PROVIDER_KEY_ENV[provider],
        "cases_sha256": cases_hash,
        "case_count": len(validated_cases),
        "repeats": repeats,
        "expected_records": len(validated_cases) * repeats,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "runner": "evals/decision_models/benchmark_api.py",
        "simplejev_min_start_interval_seconds": _SIMPLEJEV_MIN_INTERVAL_SECONDS if provider == "simplejev" else None,
    }
    _write_json(metadata_path, metadata)
    # Ensure an empty output exists even if the warm-up is halted by auth or a
    # rate limit.  The summary then explicitly reflects zero measured rows.
    output_path.write_text("", encoding="utf-8")

    api_key: str | None = None
    stopped: ProviderHalt | None = None
    failed: Exception | None = None
    rows_written = 0
    last_start: float | None = None

    try:
        api_key = _api_key(provider)
        warmup, last_start = _request_case(
            validated_cases[0], provider, model, api_key, last_start=last_start, measure=False
        )
        warmup["warmup"] = True
        warmup["repeat"] = None
        _write_json(warmup_path, warmup)
        if warmup.get("http_status") in _STOP_STATUSES:
            raise ProviderHalt(int(warmup["http_status"]))

        with output_path.open("w", encoding="utf-8") as handle:
            for repeat in range(1, repeats + 1):
                for case in validated_cases:
                    row, last_start = _request_case(
                        case, provider, model, api_key, last_start=last_start, measure=True
                    )
                    row["repeat"] = repeat
                    handle.write(_canonical_json(row) + "\n")
                    handle.flush()
                    rows_written += 1
                    if row.get("http_status") in _STOP_STATUSES:
                        raise ProviderHalt(int(row["http_status"]))
    except ProviderHalt as exc:
        stopped = exc
    except Exception as exc:
        # Persist a failure receipt while avoiding exception text that could
        # accidentally contain request details or credentials.
        failed = exc
    finally:
        metadata["finished_at_utc"] = _utc_now()
        metadata["status"] = "stopped" if stopped is not None else ("failed" if failed is not None else "completed")
        metadata["records_written"] = rows_written
        if stopped is not None:
            metadata["stop_http_status"] = stopped.status
            metadata["stop_reason"] = "authentication_or_rate_limit"
        elif failed is not None:
            metadata["failure_type"] = type(failed).__name__
        _write_json(metadata_path, metadata)
        summary = summarize(output_path, metadata_path=metadata_path, warmup_path=warmup_path)

    if stopped is not None:
        raise stopped
    if failed is not None:
        raise failed
    return {
        "output_path": output_path,
        "metadata_path": metadata_path,
        "warmup_path": warmup_path,
        "summary_path": summary_path_for(output_path),
        "records_written": rows_written,
        "cases_sha256": cases_hash,
        "summary": summary,
    }


def _nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int((percentile * len(ordered)) + 0.999999999999))
    return ordered[min(rank, len(ordered)) - 1]


def _latency_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [
        float(row["latency_ms"])
        for row in rows
        if isinstance(row.get("latency_ms"), (int, float)) and not isinstance(row.get("latency_ms"), bool)
    ]
    return {
        "measured": len(values),
        "total": len(rows),
        "complete": len(values) == len(rows),
        "median_ms": statistics.median(values) if values else None,
        "p95_ms": _nearest_rank(values, 0.95),
    }


def _accuracy_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    denominator = len(rows)
    correct = sum(1 for row in rows if row.get("correct") is True and row.get("model_match", True) is not False)
    valid = sum(1 for row in rows if row.get("valid") is True and row.get("model_match", True) is not False)
    model_matches = sum(1 for row in rows if row.get("model_match") is True)
    return {
        "correct": correct,
        "denominator": denominator,
        "accuracy": (correct / denominator) if denominator else None,
        "valid": valid,
        "invalid": denominator - valid,
        "valid_accuracy": (correct / valid) if valid else None,
        "model_matches": model_matches,
    }


def _sum_stats(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    values = [
        row[key]
        for row in rows
        if isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool)
    ]
    return {
        "sum": sum(values) if values else None,
        "measured": len(values),
        "total": len(rows),
        "complete": len(values) == len(rows),
    }


def _metric_bundle(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "accuracy": _accuracy_stats(rows),
        "latency_ms": _latency_stats(rows),
    }


def _first_pass_per_case(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    selected: dict[Any, Mapping[str, Any]] = {}
    for row in rows:
        key = row.get("id")
        if key not in selected:
            selected[key] = row
            continue
        previous = selected[key]
        previous_repeat = previous.get("repeat")
        current_repeat = row.get("repeat")
        if isinstance(current_repeat, int) and (not isinstance(previous_repeat, int) or current_repeat < previous_repeat):
            selected[key] = row
    return list(selected.values())


def summarize_records(
    rows: Sequence[Mapping[str, Any]],
    *,
    provider: str | None = None,
    model: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    warmup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build summary data from common result rows without writing a file."""

    rows = [dict(row) for row in rows]
    if provider is None and metadata is not None:
        provider = metadata.get("provider")
    if model is None and metadata is not None:
        model = metadata.get("model")

    repeats = sorted({row.get("repeat") for row in rows if isinstance(row.get("repeat"), int)})
    unique_rows = _first_pass_per_case(rows)
    by_pass: dict[str, list[Mapping[str, Any]]] = {}
    for repeat in repeats:
        by_pass[str(repeat)] = [row for row in rows if row.get("repeat") == repeat]

    by_category: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        category = row.get("category")
        category_key = category if isinstance(category, str) else "<unknown>"
        by_category.setdefault(category_key, []).append(row)

    prompt_stats = _sum_stats(rows, "prompt_tokens")
    completion_stats = _sum_stats(rows, "completion_tokens")
    cost_stats = _sum_stats(rows, "cost_usd")
    if provider == "jev":
        prompt_sum = prompt_stats["sum"]
        estimate = (prompt_sum * _JEV_ESTIMATED_PROMPT_RATE_USD_PER_MILLION / 1_000_000) if prompt_sum is not None else None
        cost_estimate = {
            "applicable": True,
            "rate_usd_per_million_prompt_tokens": _JEV_ESTIMATED_PROMPT_RATE_USD_PER_MILLION,
            "prompt_tokens": prompt_sum,
            "estimated_cost_usd": estimate,
            "complete": prompt_stats["complete"],
        }
    else:
        cost_estimate = {
            "applicable": False,
            "rate_usd_per_million_prompt_tokens": None,
            "prompt_tokens": None,
            "estimated_cost_usd": None,
            "complete": False,
        }

    summary: dict[str, Any] = {
        "schema_version": 1,
        "provider": provider,
        "model": model,
        "counts": {
            "records": len(rows),
            "unique_cases": len(unique_rows),
            "repeats": repeats,
            "valid": sum(1 for row in rows if row.get("valid") is True),
            "invalid": sum(1 for row in rows if row.get("valid") is not True),
            "model_mismatches": sum(1 for row in rows if row.get("model_match") is False),
        },
        "accuracy": {
            "unique_cases": _accuracy_stats(unique_rows),
            "repeats": _accuracy_stats(rows),
        },
        "latency_ms": _latency_stats(rows),
        "per_pass": {repeat: _metric_bundle(pass_rows) for repeat, pass_rows in by_pass.items()},
        "per_category": {
            category: _metric_bundle(category_rows) for category, category_rows in sorted(by_category.items())
        },
        "tokens": {
            "prompt_tokens": prompt_stats,
            "completion_tokens": completion_stats,
        },
        "cost": {
            "sum_usd": cost_stats["sum"],
            "measured": cost_stats["measured"],
            "total": cost_stats["total"],
            "complete": cost_stats["complete"],
            "source_counts": {
                source: sum(1 for row in rows if row.get("cost_source") == source)
                for source in sorted({row.get("cost_source") for row in rows if row.get("cost_source") is not None})
            },
        },
        # Provider-reported cost_usd remains separate from this Jev estimate.
        "cost_estimate": cost_estimate,
        "warmup": {
            "included_in_metrics": False,
            "present": warmup is not None,
            "record": dict(warmup) if warmup is not None else None,
        },
    }
    return summary


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BenchmarkError(f"invalid JSONL record at line {line_number}: {path}") from exc
                if not isinstance(value, Mapping):
                    raise BenchmarkError(f"JSONL record at line {line_number} is not an object: {path}")
                rows.append(dict(value))
    except OSError as exc:
        raise BenchmarkError(f"could not read result file: {path}") from exc
    return rows


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"could not read JSON sidecar: {path}") from exc
    if not isinstance(value, Mapping):
        raise BenchmarkError(f"JSON sidecar must contain an object: {path}")
    return dict(value)


def summarize(
    output: str | os.PathLike[str] | Sequence[Mapping[str, Any]],
    *,
    metadata_path: str | os.PathLike[str] | None = None,
    warmup_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Write ``<output stem>.summary.json`` and return the summary object."""

    # ``benchmark_local.py`` imports this helper for in-memory rows.  Keep
    # that integration callable without making the local runner write API
    # sidecars or reinterpret its legacy row schema.
    if not isinstance(output, (str, bytes, os.PathLike)):
        rows = list(output)
        if rows and any("status" in row for row in rows):
            statuses: dict[str, int] = {}
            latencies: list[float] = []
            judged = 0
            correct = 0
            for row in rows:
                status = str(row.get("status", "unknown"))
                statuses[status] = statuses.get(status, 0) + 1
                usage = row.get("usage")
                if isinstance(usage, Mapping) and isinstance(usage.get("latency_ms"), (int, float)):
                    latencies.append(float(usage["latency_ms"]))
                if row.get("correct") is not None:
                    judged += 1
                    correct += int(bool(row.get("correct")))
            ordered = sorted(latencies)
            percentile = lambda q: ordered[max(0, min(len(ordered) - 1, int(q * len(ordered) + 0.999999999) - 1))] if ordered else None
            return {
                "rows": len(rows),
                "statuses": statuses,
                "judged": judged,
                "correct": correct,
                "accuracy": (correct / judged) if judged else None,
                "latency_ms": {"p50": percentile(0.50), "p95": percentile(0.95)},
                "local_cost": None,
            }
        return summarize_records(rows)

    output_path = Path(output)
    metadata = _read_optional_json(Path(metadata_path) if metadata_path is not None else metadata_path_for(output_path))
    warmup = _read_optional_json(Path(warmup_path) if warmup_path is not None else warmup_path_for(output_path))
    rows = _read_jsonl(output_path)
    summary = summarize_records(
        rows,
        provider=metadata.get("provider") if metadata else None,
        model=metadata.get("model") if metadata else None,
        metadata=metadata,
        warmup=warmup,
    )
    if metadata is not None:
        summary["run"] = {
            "status": metadata.get("status"),
            "cases_sha256": metadata.get("cases_sha256"),
            "expected_records": metadata.get("expected_records"),
            "records_written": metadata.get("records_written"),
            "complete": (
                metadata.get("status") == "completed"
                and metadata.get("records_written") == metadata.get("expected_records")
            ),
            "started_at_utc": metadata.get("started_at_utc"),
            "finished_at_utc": metadata.get("finished_at_utc"),
            "stop_http_status": metadata.get("stop_http_status"),
        }
    _write_json(summary_path_for(output_path), summary)
    return summary


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="frozen cases JSON list")
    parser.add_argument("--output", required=True, help="JSONL result path")
    parser.add_argument("--provider", choices=tuple(PROVIDER_ENDPOINTS), required=True)
    parser.add_argument("--model", required=True, help="explicit provider model identifier")
    parser.add_argument("--repeats", type=_positive_int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cases = load_cases(args.cases)
        result = run_benchmark(cases, args.output, args.provider, args.model, args.repeats)
    except ProviderHalt as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (BenchmarkError, OSError) as exc:
        # Expected messages are already sanitized.  Never print provider
        # exception objects, request headers, or API key values.
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"wrote {result['records_written']} records to {result['output_path']} "
        f"and summary to {result['summary_path']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through CLI use
    raise SystemExit(main())
