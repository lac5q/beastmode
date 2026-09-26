#!/usr/bin/env python3
"""Verify and aggregate frozen typed-decision benchmark result archives."""

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

NAMES = ("jev", "openrouter", "simplejev-identified", "decider08", "decider4")
PROVIDERS = {
    "jev": "jev",
    "openrouter": "openrouter",
    "simplejev-identified": "simplejev",
    "decider08": "local",
    "decider4": "local",
}
EXPECTED_API_MODELS = {
    "jev": "jev-1.13.0",
    "openrouter": "openai/gpt-5.4-nano",
    "simplejev-identified": "featherless-ai/Qwen3.5-4B-classifier",
}
LOCAL_TEMPERATURES = {"decider08": 1.03, "decider4": 1.935}
JEV_RATE = 0.042
REQUIRED_FIELDS = (
    "id", "category", "gold", "choice", "valid", "correct",
    "model_match", "prompt_tokens", "completion_tokens", "latency_ms",
)
OPENROUTER_INSTRUCTION = (
    'Return exactly JSON {"choice":"<one of the options>"}; '
    "do not include any other keys or prose."
)


def fail(message: str) -> None:
    raise ValueError(message)


def finite_nonnegative(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{label} must be a finite non-negative number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        fail(f"{label} must be a finite non-negative number")
    return number


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{label} must be finite numeric")
    number = float(value)
    if not math.isfinite(number):
        fail(f"{label} must be finite numeric")
    return number


def close(a: Any, b: Any, tolerance: float = 1e-9) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read cases {path}: {exc}")
    if not isinstance(value, list) or len(value) != 30:
        fail("cases must be a JSON list of exactly 30 cases")
    cases: list[dict[str, Any]] = []
    ids: set[str] = set()
    categories: dict[str, int] = {}
    for index, case in enumerate(value):
        if not isinstance(case, dict):
            fail(f"case {index} is not an object")
        missing = [key for key in ("id", "category", "state", "question", "options", "gold", "rationale") if key not in case]
        if missing:
            fail(f"case {index} missing fields: {', '.join(missing)}")
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            fail(f"case {index} has a missing or duplicate id")
        ids.add(case_id)
        if not isinstance(case["category"], str) or not isinstance(case["state"], str) or not isinstance(case["question"], str):
            fail(f"case {case_id} has invalid text fields")
        options = case["options"]
        if not isinstance(options, list) or len(options) not in (3, 4) or not all(isinstance(x, str) for x in options):
            fail(f"case {case_id} options must be three or four strings")
        if case["gold"] not in options:
            fail(f"case {case_id} gold is not an option")
        categories[case["category"]] = categories.get(case["category"], 0) + 1
        cases.append(case)
    if set(categories) != {"routing", "retry", "evidence", "tools", "ads"} or set(categories.values()) != {6}:
        fail(f"cases must contain six cases in each required category: {categories}")
    return cases, hashlib.sha256(raw).hexdigest()


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    fail(f"blank result line {line_number}: {path}")
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    fail(f"invalid JSON at {path}:{line_number}: {exc}")
                if not isinstance(value, dict):
                    fail(f"result at {path}:{line_number} is not an object")
                rows.append(value)
    except (OSError, EOFError) as exc:
        fail(f"cannot read gzip result {path}: {exc}")
    return rows


def forbid_gold_rationale(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"gold", "rationale"}:
                fail(f"{path} contains forbidden key {key!r}")
            forbid_gold_rationale(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            forbid_gold_rationale(child, f"{path}[{index}]")


def local_prompt(case: dict[str, Any]) -> str:
    options = "".join(f"\n({chr(65 + i)}) {option}" for i, option in enumerate(case["options"]))
    return f"Context:\n{case['state']}\n\nQuestion: {case['question']}\nOptions:{options}\nAnswer: ("


def validate_payload(name: str, row: dict[str, Any], case: dict[str, Any]) -> None:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        fail(f"{name}/{row['id']} payload is missing or not an object")
    forbid_gold_rationale(payload)
    options = case["options"]
    if name in ("jev", "simplejev-identified"):
        if payload.get("state") != case["state"]:
            fail(f"{name}/{row['id']} Jev state differs from cases")
        questions = payload.get("questions")
        if not isinstance(questions, dict) or set(questions) != {"decision"}:
            fail(f"{name}/{row['id']} Jev questions shape differs")
        decision = questions["decision"]
        if not isinstance(decision, dict):
            fail(f"{name}/{row['id']} Jev decision is not an object")
        if decision.get("instructions") != case["question"]:
            fail(f"{name}/{row['id']} Jev instructions differ from cases")
        criteria = decision.get("criteria")
        if criteria != {option: None for option in options}:
            fail(f"{name}/{row['id']} Jev criteria differ from options")
    elif name == "openrouter":
        messages = payload.get("messages")
        if not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict):
            fail(f"{name}/{row['id']} OpenRouter messages shape differs")
        content = messages[0].get("content")
        if messages[0].get("role") != "user" or not isinstance(content, str):
            fail(f"{name}/{row['id']} OpenRouter user message is invalid")
        try:
            prompt_object = json.loads(content)
        except json.JSONDecodeError as exc:
            fail(f"{name}/{row['id']} OpenRouter content is not JSON: {exc}")
        if not isinstance(prompt_object, dict):
            fail(f"{name}/{row['id']} OpenRouter content JSON is not an object")
        forbid_gold_rationale(prompt_object, f"{name}/{row['id']}.prompt")
        if prompt_object.get("state") != case["state"] or prompt_object.get("question") != case["question"]:
            fail(f"{name}/{row['id']} OpenRouter state/question differs from cases")
        if prompt_object.get("options") != options:
            fail(f"{name}/{row['id']} OpenRouter options differ from cases")
        if prompt_object.get("instruction") != OPENROUTER_INSTRUCTION:
            fail(f"{name}/{row['id']} OpenRouter instruction differs")
    else:
        if payload.get("prompt") != local_prompt(case):
            fail(f"{name}/{row['id']} local prompt differs from protocol")
        requested = row.get("requested")
        if isinstance(requested, dict) and "temperature" in requested:
            if not close(requested["temperature"], LOCAL_TEMPERATURES[name]):
                fail(f"{name}/{row['id']} release temperature differs")


def validate_probabilities(row: dict[str, Any], options: list[str], label: str, *, jev_rounding: bool = False) -> None:
    probabilities = row.get("probabilities")
    if probabilities is None:
        return
    if not isinstance(probabilities, dict) or set(probabilities) != set(options):
        fail(f"{label} probabilities must use exactly semantic option names")
    values = [finite_nonnegative(probabilities[option], f"{label} probability") for option in options]
    tolerance = 0.005 * len(options) + 1e-9 if jev_rounding else 1e-6
    if abs(sum(values) - 1.0) > tolerance:
        fail(f"{label} probabilities do not sum to one")


def validate_local_raw(name: str, row: dict[str, Any], case: dict[str, Any]) -> None:
    raw = row.get("raw")
    if not isinstance(raw, dict) or raw.get("truncated") is not False:
        fail(f"{name}/{row['id']} raw.truncated must be false")
    timings = raw.get("timings")
    if not isinstance(timings, dict) or timings.get("cache_n") != 0:
        fail(f"{name}/{row['id']} raw.timings.cache_n must be zero")
    prompt_raw = timings.get("prompt_n")
    completion_raw = timings.get("predicted_n")
    if prompt_raw is None or completion_raw is None:
        fail(f"{name}/{row['id']} raw timings lack measured token counts")
    finite_nonnegative(prompt_raw, "raw prompt tokens")
    finite_nonnegative(completion_raw, "raw completion tokens")
    if not close(row["prompt_tokens"], prompt_raw) or not close(row["completion_tokens"], completion_raw):
        fail(f"{name}/{row['id']} row tokens disagree with raw timings")
    receipt = row.get("provenance", {}).get("model_receipt") if isinstance(row.get("provenance"), dict) else None
    observed = row.get("observed") if isinstance(row.get("observed"), dict) else None
    expected_file = receipt.get("file") if isinstance(receipt, dict) else None
    raw_model = raw.get("model")
    props_model = observed.get("loaded_model_file") if isinstance(observed, dict) else None
    if not isinstance(expected_file, str) or not isinstance(raw_model, str) or not isinstance(props_model, str):
        fail(f"{name}/{row['id']} local model provenance is incomplete")
    if Path(raw_model).name != Path(expected_file).name or Path(props_model).name != Path(expected_file).name:
        fail(f"{name}/{row['id']} local model provenance disagrees with receipt file")
    completions = raw.get("completion_probabilities")
    if not isinstance(completions, list) or not completions or not isinstance(completions[0], dict):
        completions = raw.get("probs")
    if not isinstance(completions, list) or not completions or not isinstance(completions[0], dict):
        fail(f"{name}/{row['id']} raw probabilities are missing")
    top = completions[0].get("top_logprobs")
    if isinstance(top, dict):
        top = [{"token": key, "logprob": value} for key, value in top.items()]
    if not isinstance(top, list):
        fail(f"{name}/{row['id']} raw top_logprobs are missing")
    labels = [chr(65 + i) for i in range(len(case["options"]))]
    logs: dict[str, float] = {}
    for entry in top:
        if not isinstance(entry, dict) or entry.get("token") not in labels:
            continue
        token = entry["token"]
        if token in logs:
            fail(f"{name}/{row['id']} duplicate raw option token {token}")
        logs[token] = finite_number(entry.get("logprob"), "raw option logprob")
    if set(logs) != set(labels):
        fail(f"{name}/{row['id']} raw top_logprobs do not contain every option letter")
    temperature = LOCAL_TEMPERATURES[name]
    scaled = {label: logs[label] / temperature for label in labels}
    maximum = max(scaled.values())
    weights = {label: math.exp(value - maximum) for label, value in scaled.items()}
    total = sum(weights.values())
    probabilities = {label: weights[label] / total for label in labels}
    row_probabilities = row.get("probabilities")
    if not isinstance(row_probabilities, dict) or set(row_probabilities) != set(case["options"]):
        fail(f"{name}/{row['id']} local probabilities must use semantic option names")
    for label, option in zip(labels, case["options"]):
        if not close(row_probabilities[option], probabilities[label], 1e-8):
            fail(f"{name}/{row['id']} probabilities disagree with raw logits")
    winner = max(labels, key=lambda label: probabilities[label])
    if row["choice"] != case["options"][labels.index(winner)]:
        fail(f"{name}/{row['id']} choice is not the raw probability argmax")
    if "choice_label" in row and row["choice_label"] != winner:
        fail(f"{name}/{row['id']} choice_label disagrees with raw probability argmax")


def validate_rows(name: str, path: Path, cases: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not path.is_file():
        fail(f"missing required result file: {path}")
    rows = load_rows(path)
    if len(rows) != 60:
        fail(f"{name} must contain exactly 60 rows, found {len(rows)}")
    expected_provider = PROVIDERS[name]
    seen: set[tuple[str, int]] = set()
    for index, row in enumerate(rows):
        missing = [field for field in REQUIRED_FIELDS if field not in row]
        if missing:
            fail(f"{name} row {index} missing fields: {', '.join(missing)}")
        case_id = row["id"]
        if case_id not in cases:
            fail(f"{name} row {index} has unknown case id {case_id!r}")
        case = cases[case_id]
        repeat = row.get("repeat")
        if isinstance(repeat, bool) or repeat not in (1, 2):
            fail(f"{name}/{case_id} repeat must be 1 or 2")
        key = (case_id, repeat)
        if key in seen:
            fail(f"{name} contains duplicate row {key}")
        seen.add(key)
        if row["category"] != case["category"] or row["gold"] != case["gold"]:
            fail(f"{name}/{case_id} category or gold differs from frozen cases")
        if row.get("provider") != expected_provider:
            fail(f"{name}/{case_id} provider differs from expected {expected_provider}")
        if name in EXPECTED_API_MODELS:
            expected_model = EXPECTED_API_MODELS[name]
            if row.get("model") != expected_model or row.get("actual_model") != expected_model:
                fail(f"{name}/{case_id} actual/requested model differs from {expected_model}")
        if not isinstance(row["valid"], bool) or row["valid"] is not True:
            fail(f"{name}/{case_id} valid must be true")
        if not isinstance(row["model_match"], bool) or row["model_match"] is not True:
            fail(f"{name}/{case_id} model_match must be true")
        if not isinstance(row["correct"], bool):
            fail(f"{name}/{case_id} correct must be boolean")
        expected_correct = bool(row["valid"] and row["model_match"] and row["choice"] == row["gold"])
        if row["correct"] != expected_correct:
            fail(f"{name}/{case_id} correct formula is inconsistent")
        if row["choice"] not in case["options"]:
            fail(f"{name}/{case_id} choice is not an option")
        finite_nonnegative(row["prompt_tokens"], f"{name}/{case_id} prompt_tokens")
        finite_nonnegative(row["completion_tokens"], f"{name}/{case_id} completion_tokens")
        finite_nonnegative(row["latency_ms"], f"{name}/{case_id} latency_ms")
        cost = row.get("cost_usd")
        if name == "openrouter":
            finite_nonnegative(cost, f"{name}/{case_id} cost_usd")
        elif cost is not None:
            fail(f"{name}/{case_id} non-OpenRouter cost must be null")
        validate_payload(name, row, case)
        validate_probabilities(row, case["options"], f"{name}/{case_id}", jev_rounding=name == "jev")
        if name in LOCAL_TEMPERATURES:
            validate_local_raw(name, row, case)
        else:
            raw = row.get("raw")
            if not isinstance(raw, dict):
                fail(f"{name}/{case_id} raw response is missing")
            if raw.get("model") != EXPECTED_API_MODELS[name]:
                fail(f"{name}/{case_id} raw model differs from expected model")
            usage = raw.get("usage")
            if isinstance(usage, dict):
                pairs = (
                    ("prompt_tokens", ("input_tokens", "prompt_tokens")),
                    ("completion_tokens", ("output_tokens", "completion_tokens")),
                )
                for field, keys in pairs:
                    raw_value = next((usage[key] for key in keys if key in usage), None)
                    if raw_value is not None and not close(row[field], raw_value):
                        fail(f"{name}/{case_id} row {field} disagrees with raw usage")
    expected = {(case_id, repeat) for case_id in cases for repeat in (1, 2)}
    if seen != expected:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        fail(f"{name} cartesian rows differ; missing={missing}, extra={extra}")
    return rows


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if quantile == 0.5:
        return float(statistics.median(ordered))
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return float(ordered[index])


def accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    correct = sum(1 for row in rows if row["correct"])
    return {
        "correct": correct,
        "total": total,
        "accuracy": float(correct / total) if total else 0.0,
        "valid": sum(1 for row in rows if row["valid"]),
        "model_matches": sum(1 for row in rows if row["model_match"]),
    }


def latency_stats(rows: list[dict[str, Any]]) -> dict[str, float]:
    values = [float(row["latency_ms"]) for row in rows]
    return {
        "mean": float(statistics.mean(values)),
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
    }


def token_stats(rows: list[dict[str, Any]]) -> dict[str, float]:
    prompt = [float(row["prompt_tokens"]) for row in rows]
    completion = [float(row["completion_tokens"]) for row in rows]
    total = [a + b for a, b in zip(prompt, completion)]
    return {
        "prompt_total": float(sum(prompt)),
        "prompt_mean": float(statistics.mean(prompt)),
        "completion_total": float(sum(completion)),
        "completion_mean": float(statistics.mean(completion)),
        "total_total": float(sum(total)),
        "total_mean": float(statistics.mean(total)),
    }


def pmax_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = 0
    covered = 0
    wrong = 0
    for row in rows:
        probabilities = row.get("probabilities")
        if not isinstance(probabilities, dict) or not probabilities:
            continue
        available += 1
        pmax = max(float(value) for value in probabilities.values())
        if pmax >= 0.9:
            covered += 1
            if not row["correct"]:
                wrong += 1
    return {
        "threshold": 0.9,
        "probability_rows": available,
        "covered": covered,
        "coverage": float(covered / len(rows)) if rows else 0.0,
        "wrong_decisions": wrong,
        "note": "descriptive; not calibrated",
    }


def model_report(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    categories = sorted({row["category"] for row in rows})
    prompt_total = sum(float(row["prompt_tokens"]) for row in rows)
    provider_cost = (
        float(sum(float(row["cost_usd"]) for row in rows))
        if name == "openrouter" else None
    )
    jev_estimate = prompt_total * JEV_RATE / 1_000_000 if name == "jev" else None
    return {
        "provider": PROVIDERS[name],
        "models": sorted({row.get("model") for row in rows if isinstance(row.get("model"), str)}),
        "records": len(rows),
        "accuracy": {
            "overall": accuracy(rows),
            "first_pass": accuracy([row for row in rows if row["repeat"] == 1]),
            "second_pass": accuracy([row for row in rows if row["repeat"] == 2]),
            "per_category": {
                category: accuracy([row for row in rows if row["category"] == category])
                for category in categories
            },
        },
        "latency_ms": latency_stats(rows),
        "per_pass_latency_ms": {
            "first_pass": latency_stats([row for row in rows if row["repeat"] == 1]),
            "second_pass": latency_stats([row for row in rows if row["repeat"] == 2]),
        },
        "tokens": token_stats(rows),
        "pmax_ge_0_9": pmax_stats(rows),
        "cost": {
            "provider_reported_usd": provider_cost,
            "jev_estimated_input_usd": jev_estimate,
            "local_assumed_usd": None,
        },
    }


def aggregate(cases_path: Path, cases_digest: str, result_digests: dict[str, str], reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    jev_cost = reports["jev"]["cost"]["jev_estimated_input_usd"]
    nano_cost = reports["openrouter"]["cost"]["provider_reported_usd"]
    calls = float(reports["jev"]["records"])
    for name in ("decider08", "decider4"):
        mean_ms = reports[name]["latency_ms"]["mean"]
        def breakeven(cost: Any) -> float | None:
            if cost is None or mean_ms <= 0:
                return None
            return float((float(cost) / calls) * 3_600_000.0 / mean_ms)
        reports[name]["local_economics"] = {
            "mean_wall_ms": float(mean_ms),
            "assumed_hourly_rate_usd": None,
            "cost_per_call_usd": None,
            "utilization": 1.0,
            "break_even_hourly_usd_vs_jev": breakeven(jev_cost),
            "break_even_hourly_usd_vs_nano": breakeven(nano_cost),
        }
    return {
        "schema_version": 1,
        "dataset": {
            "cases_path": str(cases_path),
            "case_count": 30,
            "repeats": [1, 2],
            "rawfile_sha256": {
                "cases": cases_digest,
                "results": result_digests,
            },
        },
        "models": reports,
        "economics_reference": {
            "jev_estimated_input_usd": jev_cost,
            "nano_provider_reported_usd": nano_cost,
            "utilization_assumption": 1.0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("evals/decision_models/results/2026-09-26"))
    parser.add_argument("--cases", type=Path, default=Path("evals/decision_models/cases.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        cases, cases_digest = load_cases(args.cases)
        case_map = {case["id"]: case for case in cases}
        rows_by_model: dict[str, list[dict[str, Any]]] = {}
        digests: dict[str, str] = {}
        for name in NAMES:
            path = args.results / f"{name}.jsonl.gz"
            rows_by_model[name] = validate_rows(name, path, case_map)
            digests[name] = sha256_file(path)
        reports = {name: model_report(name, rows) for name, rows in rows_by_model.items()}
        report = aggregate(args.cases, cases_digest, digests, reports)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"analyze_results: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
