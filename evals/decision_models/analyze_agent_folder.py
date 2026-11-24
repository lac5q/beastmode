#!/usr/bin/env python3
"""Analyzer for the 2026-09-27 agent-folder decision corpus.

This is an offline, fail-closed verifier. A complete arm may contain recorded
model failures; those rows remain in its denominator. An unavailable arm has no
rows and explicit stopped/unavailable metadata, while a nonempty partial arm is
incomplete and never rankable.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

ARMS = ("jev", "openrouter", "simplejev-identified")
PROVIDERS = {"jev": "jev", "openrouter": "openrouter", "simplejev-identified": "simplejev"}
EXPECTED_MODELS = {
    "jev": "jev-1.13.0",
    "openrouter": "openai/gpt-5.4-nano",
    "simplejev-identified": "featherless-ai/Qwen3.5-4B-classifier",
}
CATEGORIES = ("next_worker", "relevance", "done", "risky")
REPEATS = (1, 2)
JEV_INPUT_RATE = 0.042
OPENROUTER_INSTRUCTION = (
    'Return exactly JSON {"choice":"<one of the options>"}; '
    "do not include any other keys or prose."
)
COMMON_FIELDS = (
    "id", "category", "gold", "choice", "valid", "correct",
    "model_match", "prompt_tokens", "completion_tokens", "latency_ms",
)


def fail(message: str) -> None:
    raise ValueError(message)


def number(value: Any, label: str, *, nonnegative: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{label} is not numeric")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        fail(f"{label} is not finite and non-negative")
    return result


def optional_number(value: Any, label: str) -> float | None:
    return None if value is None else number(value, label)


def close(a: Any, b: Any, tolerance: float = 1e-9) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"invalid JSON file {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"JSON file {path} must contain an object")
    return value


def load_cases(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read cases {path}: {exc}")
    if not isinstance(value, list) or len(value) != 32:
        fail("the new corpus must contain exactly 32 cases")
    cases: dict[str, dict[str, Any]] = {}
    counts = {category: 0 for category in CATEGORIES}
    for index, case in enumerate(value):
        if not isinstance(case, dict):
            fail(f"case {index} is not an object")
        required = ("id", "category", "state", "question", "options", "gold", "rationale")
        if any(key not in case for key in required):
            fail(f"case {index} is missing required fixture fields")
        case_id = case["id"]
        category = case["category"]
        options = case["options"]
        if not isinstance(case_id, str) or not case_id or case_id in cases:
            fail(f"case {index} has a missing or duplicate id")
        if category not in CATEGORIES:
            fail(f"case {case_id} has unknown category {category!r}")
        if not isinstance(case["state"], str) or not isinstance(case["question"], str):
            fail(f"case {case_id} state/question must be strings")
        if not isinstance(options, list) or len(options) not in (3, 4) or not all(isinstance(x, str) for x in options):
            fail(f"case {case_id} options must be three or four strings")
        if case["gold"] not in options:
            fail(f"case {case_id} gold is not an option")
        if not isinstance(case["rationale"], str):
            fail(f"case {case_id} rationale must be a string")
        cases[case_id] = case
        counts[category] += 1
    if any(counts[category] != 8 for category in CATEGORIES):
        fail(f"expected eight cases per category, got {counts}")
    return cases, hashlib.sha256(raw).hexdigest()


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    fail(f"blank result line {line_number}: {path}")
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    fail(f"malformed result JSON at {path}:{line_number}: {exc}")
                if not isinstance(value, dict):
                    fail(f"result at {path}:{line_number} is not an object")
                rows.append(value)
    except (OSError, EOFError) as exc:
        fail(f"cannot read result archive {path}: {exc}")
    return rows


def forbid_gold_rationale(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"gold", "rationale"}:
                fail(f"{path} contains forbidden key {key!r}")
            forbid_gold_rationale(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            forbid_gold_rationale(child, f"{path}[{index}]")


def validate_payload(arm: str, row: dict[str, Any], case: dict[str, Any]) -> str | None:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        fail(f"{arm}/{row['id']} payload is not an object")
    forbid_gold_rationale(payload, f"{arm}/{row['id']}.payload")
    options = case["options"]
    requested = row["model"]
    if arm in ("jev", "simplejev-identified"):
        if payload.get("state") != case["state"] or payload.get("model") != requested:
            fail(f"{arm}/{row['id']} state/model payload differs from fixture")
        questions = payload.get("questions")
        if not isinstance(questions, dict) or set(questions) != {"decision"}:
            fail(f"{arm}/{row['id']} Jev questions shape is invalid")
        decision = questions["decision"]
        if not isinstance(decision, dict):
            fail(f"{arm}/{row['id']} Jev decision is not an object")
        if decision.get("type") != "choice":
            fail(f"{arm}/{row['id']} Jev decision type is not choice")
        if decision.get("instructions") != case["question"]:
            fail(f"{arm}/{row['id']} Jev instructions differ from fixture")
        if decision.get("criteria") != {option: None for option in options}:
            fail(f"{arm}/{row['id']} Jev criteria differ from fixture options")
    else:
        if payload.get("model") != requested:
            fail(f"{arm}/{row['id']} OpenRouter requested model differs")
        messages = payload.get("messages")
        if not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict):
            fail(f"{arm}/{row['id']} OpenRouter messages are invalid")
        message = messages[0]
        if message.get("role") != "user" or not isinstance(message.get("content"), str):
            fail(f"{arm}/{row['id']} OpenRouter user content is invalid")
        try:
            prompt = json.loads(message["content"])
        except json.JSONDecodeError as exc:
            fail(f"{arm}/{row['id']} OpenRouter prompt JSON is malformed: {exc}")
        if not isinstance(prompt, dict):
            fail(f"{arm}/{row['id']} OpenRouter prompt is not an object")
        forbid_gold_rationale(prompt, f"{arm}/{row['id']}.prompt")
        if prompt.get("state") != case["state"] or prompt.get("question") != case["question"]:
            fail(f"{arm}/{row['id']} OpenRouter state/question differs from fixture")
        if prompt.get("options") != options or prompt.get("instruction") != OPENROUTER_INSTRUCTION:
            fail(f"{arm}/{row['id']} OpenRouter options/instruction differs")
    return requested


def find_choice(value: Any) -> Any:
    if isinstance(value, dict):
        if "choice" in value:
            return value["choice"]
        for child in value.values():
            found = find_choice(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_choice(child)
            if found is not None:
                return found
    return None


def raw_answer(arm: str, raw: Any) -> tuple[Any, str]:
    if not isinstance(raw, dict):
        return None, "unparsed_failure"
    if "error" in raw and "choices" not in raw and "answers" not in raw and "answer" not in raw:
        return None, "provider_error"
    if arm in ("jev", "simplejev-identified"):
        choice = find_choice(raw.get("answers", raw.get("answer")))
        return (choice, "ok") if choice is not None else (None, "invalid_answer")
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None, "invalid_answer"
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, dict):
        parsed = content
    elif isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None, "invalid_answer"
    else:
        return None, "invalid_answer"
    if not isinstance(parsed, dict) or set(parsed) - {"choice"}:
        return None, "invalid_answer"
    choice = parsed.get("choice")
    return (choice, "ok") if choice is not None else (None, "invalid_answer")


def validate_probabilities(arm: str, row: dict[str, Any], case: dict[str, Any]) -> None:
    probabilities = row.get("probabilities")
    if probabilities is None:
        return
    options = case["options"]
    if not isinstance(probabilities, dict) or set(probabilities) != set(options):
        fail(f"{arm}/{row['id']} probabilities do not use semantic option names")
    values = [number(probabilities[option], f"{arm}/{row['id']} probability") for option in options]
    if any(value > 1.0 for value in values):
        fail(f"{arm}/{row['id']} probability is greater than one")
    tolerance = 0.005 * len(options) + 1e-9 if arm == "jev" else 1e-6
    if abs(sum(values) - 1.0) > tolerance:
        fail(f"{arm}/{row['id']} probabilities do not sum to one")


def usage_value(usage: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in usage:
            return usage[name]
    return None


def jev_decision(raw: dict[str, Any]) -> dict[str, Any] | None:
    candidate = raw.get("answers", raw.get("answer"))
    if isinstance(candidate, dict):
        if "choice" in candidate:
            return candidate
        for child in candidate.values():
            if isinstance(child, dict):
                found = jev_decision({"answer": child})
                if found is not None:
                    return found
    elif isinstance(candidate, list):
        for child in candidate:
            if isinstance(child, dict):
                found = jev_decision({"answer": child})
                if found is not None:
                    return found
    return None


def bounded(value: Any, label: str) -> float:
    result = number(value, label)
    if result > 1.0:
        fail(f"{label} is greater than one")
    return result


def validate_raw_and_usage(
    arm: str, row: dict[str, Any], case: dict[str, Any]
) -> tuple[set[str], str | None, Any, str]:
    if "raw" not in row:
        fail(f"{arm}/{row['id']} raw response is missing")
    raw = row["raw"]
    if raw is not None and not isinstance(raw, dict):
        fail(f"{arm}/{row['id']} malformed raw response")
    if raw is None and not row.get("error"):
        fail(f"{arm}/{row['id']} missing response has no failure receipt")
    observed: set[str] = set()
    raw_model: str | None = None
    usage: dict[str, Any] | None = None
    if isinstance(raw, dict):
        raw_model = raw.get("model")
        if raw_model is not None:
            if not isinstance(raw_model, str):
                fail(f"{arm}/{row['id']} raw model id is malformed")
            observed.add(raw_model)
        actual = row.get("actual_model")
        if actual is not None:
            if not isinstance(actual, str):
                fail(f"{arm}/{row['id']} actual model id is malformed")
            if raw_model is not None and actual != raw_model:
                fail(f"{arm}/{row['id']} actual_model differs from raw model")
            observed.add(actual)
        raw_usage = raw.get("usage")
        if raw_usage is not None and not isinstance(raw_usage, dict):
            fail(f"{arm}/{row['id']} raw usage is malformed")
        usage = raw_usage
        if isinstance(usage, dict):
            pairs = (
                ("prompt_tokens", ("input_tokens", "prompt_tokens")),
                ("completion_tokens", ("output_tokens", "completion_tokens")),
            )
            for field, names in pairs:
                raw_value = usage_value(usage, names)
                row_value = row.get(field)
                if raw_value is None and row_value is not None:
                    fail(f"{arm}/{row['id']} row {field} has no matching raw usage")
                if raw_value is not None:
                    number(raw_value, f"{arm}/{row['id']} raw {field}")
                    if row_value is None or not close(row_value, raw_value):
                        fail(f"{arm}/{row['id']} row {field} disagrees with raw usage")
            raw_cost = usage.get("cost_usd", usage.get("cost"))
            row_cost = row.get("cost_usd")
            if arm == "openrouter":
                if raw_cost is not None:
                    number(raw_cost, f"{arm}/{row['id']} raw cost", nonnegative=True)
                    if row_cost is None or not close(row_cost, raw_cost):
                        fail(f"{arm}/{row['id']} row cost disagrees with raw cost")
                elif row_cost is not None:
                    fail(f"{arm}/{row['id']} row cost has no matching raw cost")
            elif row_cost is not None:
                fail(f"{arm}/{row['id']} non-Nano cost must be null")
        elif row["valid"] or row.get("prompt_tokens") is not None or row.get("completion_tokens") is not None or row.get("cost_usd") is not None:
            fail(f"{arm}/{row['id']} normalized usage/cost has no raw usage receipt")
    elif row["valid"] or row.get("prompt_tokens") is not None or row.get("completion_tokens") is not None or row.get("cost_usd") is not None:
        fail(f"{arm}/{row['id']} valid row has malformed raw response")
    choice, state = raw_answer(arm, raw)
    if state == "ok" and choice != row["choice"]:
        fail(f"{arm}/{row['id']} row choice disagrees with raw answer")
    if row["valid"]:
        if state != "ok" or choice not in case["options"]:
            fail(f"{arm}/{row['id']} valid row has no semantic raw choice")
    elif row["choice"] is not None and state == "ok" and choice != row["choice"]:
        fail(f"{arm}/{row['id']} invalid row choice disagrees with raw answer")
    validate_probabilities(arm, row, case)

    if arm in ("jev", "simplejev-identified") and isinstance(raw, dict):
        decision = jev_decision(raw)
        raw_probabilities = None
        raw_confidence = None
        if decision is not None:
            raw_probabilities = decision.get("probabilities", decision.get("probs"))
            raw_confidence = decision.get("confidence")
        if raw_probabilities is None:
            raw_probabilities = raw.get("probabilities", raw.get("probs"))
        if raw_confidence is None:
            raw_confidence = raw.get("confidence")
        if raw_probabilities is not None:
            if not isinstance(raw_probabilities, dict) or set(raw_probabilities) != set(case["options"]):
                fail(f"{arm}/{row['id']} raw probabilities do not use semantic option names")
            raw_values = [number(raw_probabilities[option], f"{arm}/{row['id']} raw probability") for option in case["options"]]
            if any(value > 1.0 for value in raw_values):
                fail(f"{arm}/{row['id']} raw probability is greater than one")
            if row.get("probabilities") is None or any(
                not close(row["probabilities"][option], raw_probabilities[option])
                for option in case["options"]
            ):
                fail(f"{arm}/{row['id']} normalized probabilities disagree with raw answer")
        elif row.get("probabilities") is not None:
            fail(f"{arm}/{row['id']} normalized probabilities have no raw answer receipt")
        if raw_confidence is not None:
            confidence = bounded(raw_confidence, f"{arm}/{row['id']} raw confidence")
            if row.get("confidence") is None or not close(row["confidence"], confidence):
                fail(f"{arm}/{row['id']} normalized confidence disagrees with raw answer")
        elif row.get("confidence") is not None:
            fail(f"{arm}/{row['id']} normalized confidence has no raw answer receipt")
    elif row.get("probabilities") is not None or row.get("confidence") is not None:
        fail(f"{arm}/{row['id']} normalized probabilities/confidence are unsupported by raw answer")
    return observed, raw_model, choice, state


def validate_row(arm: str, row: dict[str, Any], cases: dict[str, dict[str, Any]], seen: set[tuple[str, int]]) -> set[str]:
    missing = [field for field in COMMON_FIELDS if field not in row]
    if missing:
        fail(f"{arm} row is missing fields: {', '.join(missing)}")
    case_id = row["id"]
    if case_id not in cases:
        fail(f"{arm} has unknown case id {case_id!r}")
    case = cases[case_id]
    repeat = row.get("repeat", row.get("pass"))
    if isinstance(repeat, bool) or repeat not in REPEATS:
        fail(f"{arm}/{case_id} repeat must be 1 or 2")
    key = (case_id, repeat)
    if key in seen:
        fail(f"{arm} contains duplicate row {key}")
    seen.add(key)
    if row["category"] != case["category"] or row["gold"] != case["gold"]:
        fail(f"{arm}/{case_id} category/gold differs from fixture")
    if row.get("provider") != PROVIDERS[arm]:
        fail(f"{arm}/{case_id} provider differs from expected")
    expected_model = EXPECTED_MODELS[arm]
    if row["model"] != expected_model:
        fail(f"{arm}/{case_id} requested model differs from pinned {expected_model}")
    if not isinstance(row["valid"], bool) or not isinstance(row["model_match"], bool):
        fail(f"{arm}/{case_id} valid/model_match must be booleans")
    if not isinstance(row["correct"], bool):
        fail(f"{arm}/{case_id} correct must be boolean")
    if row["valid"] and row["choice"] not in case["options"]:
        fail(f"{arm}/{case_id} valid choice is not semantic")
    optional_number(row["prompt_tokens"], f"{arm}/{case_id} prompt_tokens")
    optional_number(row["completion_tokens"], f"{arm}/{case_id} completion_tokens")
    number(row["latency_ms"], f"{arm}/{case_id} latency_ms")
    if row.get("confidence") is not None:
        bounded(row["confidence"], f"{arm}/{case_id} confidence")
    if row.get("cost_usd") is not None:
        number(row["cost_usd"], f"{arm}/{case_id} cost_usd")
    requested = validate_payload(arm, row, case)
    observed, raw_model, raw_choice, raw_state = validate_raw_and_usage(arm, row, case)
    actual = row.get("actual_model")
    if raw_model is not None:
        if actual != raw_model:
            fail(f"{arm}/{case_id} actual_model differs from raw model")
    elif actual is not None:
        fail(f"{arm}/{case_id} actual_model has no raw model receipt")
    derived_match = raw_model == expected_model
    if row["model_match"] != derived_match:
        fail(f"{arm}/{case_id} model_match disagrees with raw model identity")
    expected_valid = bool(derived_match and raw_state == "ok" and raw_choice in case["options"])
    if row["valid"] != expected_valid:
        fail(f"{arm}/{case_id} valid disagrees with raw answer/model identity")
    if raw_state != "ok" and row["choice"] is not None:
        fail(f"{arm}/{case_id} failed raw answer has a fabricated choice")
    if raw_state == "ok" and raw_choice != row["choice"]:
        fail(f"{arm}/{case_id} row choice disagrees with raw answer")
    expected_correct = bool(row["valid"] and row["model_match"] and row["choice"] == row["gold"])
    if row["correct"] != expected_correct:
        fail(f"{arm}/{case_id} correct formula disagrees")
    return {requested, *observed}


def metadata_for(results: Path, arm: str) -> tuple[dict[str, Any], Path | None]:
    for suffix in (".metadata.json", ".meta.json", ".status.json"):
        path = results / f"{arm}{suffix}"
        if path.is_file():
            return read_json(path), path
    return {}, None


def archive_for(results: Path, arm: str) -> Path | None:
    for suffix in (".jsonl.gz", ".jsonl"):
        path = results / f"{arm}{suffix}"
        if path.is_file():
            return path
    return None


def metadata_model(metadata: dict[str, Any]) -> str | None:
    for key in ("requested_model", "model", "model_id", "pinned_model"):
        if key in metadata and metadata[key] is not None and not isinstance(metadata[key], str):
            fail(f"metadata {key} is not a string")
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    request = metadata.get("request")
    if isinstance(request, dict):
        for key in ("model", "model_id", "requested_model"):
            if key in request and request[key] is not None and not isinstance(request[key], str):
                fail(f"metadata request.{key} is not a string")
            value = request.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def metadata_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = ("status", "model", "requested_model", "records_written", "expected_records", "stop_reason", "error")
    return {key: metadata[key] for key in keys if key in metadata}


def arm_status(metadata: dict[str, Any], archive: Path | None, rows: list[dict[str, Any]], expected: set[tuple[str, int]], seen: set[tuple[str, int]]) -> tuple[str, str]:
    status = str(metadata.get("status", "")).lower()
    unavailable_statuses = {"stopped", "unavailable", "not_run", "skipped", "cancelled", "failed"}
    if not rows:
        if status == "completed":
            fail("metadata says completed but arm has no rows")
        return "unavailable", metadata.get("stop_reason") or ("no result archive" if archive is None else "empty result archive")
    if status in unavailable_statuses:
        return "incomplete", f"metadata status {status} with nonempty rows"
    if status in {"running", "started"}:
        return "incomplete", f"metadata status {status}"
    return ("complete", "full Cartesian coverage") if seen == expected else ("incomplete", "partial Cartesian coverage")


def p95(values: list[float]) -> float:
    return float(sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)])


def latency_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["latency_ms"]) for row in rows]
    complete = len(values) == len(rows)
    return {
        "count": len(values), "complete": complete,
        "mean": float(statistics.mean(values)) if values else None,
        "p50": float(statistics.median(values)) if values else None,
        "p95": p95(values) if values else None,
    }


def token_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = [float(row["prompt_tokens"]) for row in rows if row["prompt_tokens"] is not None]
    completions = [float(row["completion_tokens"]) for row in rows if row["completion_tokens"] is not None]
    totals = [
        float(row["prompt_tokens"]) + float(row["completion_tokens"])
        for row in rows if row["prompt_tokens"] is not None and row["completion_tokens"] is not None
    ]
    return {
        "prompt_total": float(sum(prompts)) if prompts else None,
        "prompt_mean": float(statistics.mean(prompts)) if prompts else None,
        "completion_total": float(sum(completions)) if completions else None,
        "completion_mean": float(statistics.mean(completions)) if completions else None,
        "total_total": float(sum(totals)) if totals else None,
        "total_mean": float(statistics.mean(totals)) if totals else None,
        "complete": len(prompts) == len(rows) and len(completions) == len(rows),
    }


def accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    valid_rows = [row for row in rows if row["valid"] and row["model_match"]]
    correct = sum(1 for row in rows if row["correct"])
    valid_correct = sum(1 for row in valid_rows if row["correct"])
    return {
        "total": total, "correct": correct,
        "accuracy": float(correct / total) if total else None,
        "valid_model_rows": len(valid_rows),
        "valid_accuracy": float(valid_correct / len(valid_rows)) if valid_rows else None,
        "invalid": sum(1 for row in rows if not row["valid"]),
        "model_mismatches": sum(1 for row in rows if not row["model_match"]),
    }


def probability_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = 0
    covered = 0
    wrong = 0
    for row in rows:
        probabilities = row.get("probabilities")
        if not isinstance(probabilities, dict) or not probabilities:
            continue
        available += 1
        if max(float(value) for value in probabilities.values()) >= 0.9:
            covered += 1
            wrong += int(not row["correct"])
    return {
        "threshold": 0.9, "probability_rows": available, "covered": covered,
        "coverage": float(covered / len(rows)) if rows else None,
        "wrong_decisions": wrong, "note": "descriptive; not fitted calibration",
    }


def confidence_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [bounded(row["confidence"], "confidence") for row in rows if row.get("confidence") is not None]
    return {
        "count": len(values),
        "mean": float(statistics.mean(values)) if values else None,
        "p50": float(statistics.median(values)) if values else None,
        "p95": p95(values) if values else None,
        "note": "original model confidence; separate from pmax",
    }


def dangerous_errors(rows: list[dict[str, Any]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for row in rows:
        choice, gold, category = row.get("choice"), row["gold"], row["category"]
        kind = None
        if category == "next_worker" and gold == "wait" and choice in {"research", "write", "verify"}:
            kind = "next_worker_action_when_wait"
        elif category == "relevance" and gold == "keep" and choice == "drop":
            kind = "relevance_drop_when_keep"
        elif category == "done" and gold != "met" and choice == "met":
            kind = "done_met_when_not_met"
        elif category == "risky" and gold != "read_only" and choice == "read_only":
            kind = "risky_read_only_when_not_read_only"
        if kind:
            records.append({"id": row["id"], "repeat": row.get("repeat", row.get("pass")), "kind": kind})
    by_kind: dict[str, int] = {}
    for record in records:
        by_kind[record["kind"]] = by_kind.get(record["kind"], 0) + 1
    return {"total": len(records), "by_kind": by_kind, "records": records}


def bundle(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return {
        "accuracy": accuracy(rows),
        "latency_ms": latency_stats(rows),
        "tokens": token_stats(rows),
    }


def arm_report(arm: str, rows: list[dict[str, Any]], status: str, status_note: str, metadata: dict[str, Any], archive: Path | None, cases: dict[str, dict[str, Any]], seen: set[tuple[str, int]]) -> dict[str, Any]:
    expected = {(case_id, repeat) for case_id in cases for repeat in REPEATS}
    requested_models = sorted({row["model"] for row in rows})
    pinned = metadata_model(metadata)
    expected_model = EXPECTED_MODELS[arm]
    if pinned is not None and pinned != expected_model:
        fail(f"{arm} metadata pinned model differs from {expected_model}")
    if pinned is not None and requested_models and requested_models != [pinned]:
        fail(f"{arm} metadata pinned model differs from rows")
    observed = sorted({
        value for row in rows
        for value in ([row.get("actual_model")] if isinstance(row.get("actual_model"), str) else [])
    })
    categories = {
        category: [row for row in rows if row["category"] == category]
        for category in CATEGORIES
    }
    passes = {
        f"pass_{repeat}": [row for row in rows if row.get("repeat", row.get("pass")) == repeat]
        for repeat in REPEATS
    }
    prompt_values = [row["prompt_tokens"] for row in rows if row["prompt_tokens"] is not None]
    cost_values = [row.get("cost_usd") for row in rows]
    observed_cost_values = [value for value in cost_values if value is not None]
    prompt_complete = len(prompt_values) == len(rows)
    nano_complete = arm == "openrouter" and len(observed_cost_values) == len(rows)
    jev_estimate = (
        float(sum(float(value) for value in prompt_values) * JEV_INPUT_RATE / 1_000_000)
        if arm == "jev" and prompt_values else None
    )
    nano_known_subtotal = (
        float(sum(float(value) for value in observed_cost_values))
        if arm == "openrouter" and observed_cost_values else None
    )
    nano_cost = nano_known_subtotal if nano_complete else None
    if not rows:
        metrics = {"accuracy": None, "latency_ms": None, "tokens": None}
    else:
        metrics = bundle(rows)
    return {
        "provider": PROVIDERS[arm],
        "status": status,
        "status_note": status_note,
        "rankable": status == "complete",
        "coverage": {
            "observed": len(rows), "expected": len(expected),
            "fraction": float(len(seen) / len(expected)) if expected else 0.0,
            "missing": sorted(expected - seen),
        },
        "archive": str(archive) if archive else None,
        "rawfile_sha256": digest(archive) if archive else None,
        "metadata": metadata_summary(metadata),
        "requested_model": pinned or (requested_models[0] if len(requested_models) == 1 else expected_model),
        "observed_model_ids": observed,
        "backend_identity": "unverified",
        "accuracy": {
            "overall": metrics["accuracy"],
            "per_pass": {key: bundle(value)["accuracy"] if value else None for key, value in passes.items()},
            "per_category": {key: bundle(value)["accuracy"] if value else None for key, value in categories.items()},
        },
        "latency_ms": metrics["latency_ms"],
        "per_pass_latency_ms": {key: bundle(value)["latency_ms"] if value else None for key, value in passes.items()},
        "tokens": metrics["tokens"],
        "per_pass_tokens": {key: bundle(value)["tokens"] if value else None for key, value in passes.items()},
        "per_category": {key: bundle(value) for key, value in categories.items()},
        "confidence": confidence_stats(rows) if rows else None,
        "pmax_ge_0_9": probability_stats(rows) if rows else None,
        "dangerous_errors": dangerous_errors(rows) if rows else None,
        "cost": {
            "provider_reported_usd": nano_cost if arm == "openrouter" else None,
            "provider_reported_known_subtotal_usd": nano_known_subtotal if arm == "openrouter" else None,
            "provider_cost_complete": nano_complete if arm == "openrouter" else False,
            "jev_estimated_input_usd": jev_estimate if arm == "jev" else None,
            "jev_input_tokens_complete": prompt_complete if arm == "jev" else None,
            "demo_cost_usd": None,
            "note": "missing cost is unknown, never treated as zero",
        },
    }


def arm_inputs(results: Path, arm: str, cases: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata, metadata_path = metadata_for(results, arm)
    if "provider" in metadata and metadata["provider"] != PROVIDERS[arm]:
        fail(f"{arm} metadata provider differs from expected {PROVIDERS[arm]}")
    pinned = metadata_model(metadata)
    if pinned is not None and pinned != EXPECTED_MODELS[arm]:
        fail(f"{arm} metadata pinned model differs from {EXPECTED_MODELS[arm]}")
    archive = archive_for(results, arm)
    rows = read_rows(archive) if archive else []
    canonical = json.dumps(list(cases.values()), ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    expected_metadata = {
        "case_count": len(cases), "repeats": len(REPEATS),
        "expected_records": len(cases) * len(REPEATS),
        "cases_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "records_written": len(rows),
    }
    for key, value in expected_metadata.items():
        if key in metadata and metadata[key] != value:
            fail(f"{arm} metadata {key} disagrees with frozen inputs or receipts")
    expected = {(case_id, repeat) for case_id in cases for repeat in REPEATS}
    seen: set[tuple[str, int]] = set()
    requested: set[str] = set()
    observed: set[str] = set()
    for row in rows:
        ids = validate_row(arm, row, cases, seen)
        requested |= {value for value in ids if value}
        raw = row.get("raw")
        if isinstance(raw, dict) and isinstance(raw.get("model"), str):
            observed.add(raw["model"])
    if len(requested) > 1:
        fail(f"{arm} has requested model drift: {sorted(requested)}")
    status, note = arm_status(metadata, archive, rows, expected, seen)
    report = arm_report(arm, rows, status, note, metadata, archive, cases, seen)
    report["metadata_path"] = str(metadata_path) if metadata_path else None
    report["observed_model_ids"] = sorted(set(report["observed_model_ids"]) | observed)
    return report, {"archive": archive, "metadata": metadata, "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        cases, cases_sha = load_cases(args.cases)
        reports: dict[str, dict[str, Any]] = {}
        rawfiles: dict[str, Any] = {}
        metadata_files: dict[str, Any] = {}
        for arm in ARMS:
            report, source = arm_inputs(args.results, arm, cases)
            reports[arm] = report
            archive = source["archive"]
            rawfiles[arm] = {
                "path": str(archive) if archive else None,
                "sha256": digest(archive) if archive else None,
            }
            metadata_files[arm] = report["metadata_path"]
        output = {
            "schema_version": 1,
            "dataset": {
                "cases_path": str(args.cases),
                "case_count": len(cases),
                "categories": {category: 8 for category in CATEGORIES},
                "repeats": list(REPEATS),
                "cases_rawfile_sha256": cases_sha,
                "rawfile_sha256": rawfiles,
                "metadata_files": metadata_files,
            },
            "models": reports,
            "notes": {
                "fixture_assumptions": [
                    "32 frozen cases: eight each for next_worker, relevance, done, and risky.",
                    "Two repeats are expected per case; incomplete nonempty arms are not rankable.",
                    "Requested models use the protocol pins; observed backend identity remains unverified.",
                ],
                "validation_commands": [
                    "python evals/decision_models/analyze_agent_folder.py --cases PATH --results DIR --output PATH",
                ],
                "danger_thresholds_promoted": False,
                "ranking": "No ranking or threshold promotion is computed.",
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"analyze_agent_folder: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
