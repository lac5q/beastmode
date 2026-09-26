"""Unit tests for the isolated decision-model API benchmark runner."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import benchmark_api  # noqa: E402


class FakeResponse:
    def __init__(self, payload: object, status: int = 200):
        self.payload = payload
        self.status = status
        self.closed = False

    def read(self) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        if isinstance(self.payload, str):
            return self.payload.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        self.closed = True


def _case(case_id: str = "case-1", category: str = "routing", gold: str = "allow") -> dict[str, object]:
    return {
        "id": case_id,
        "category": category,
        "state": {"kind": "test", "value": 1},
        "question": "Which option should be selected?",
        "options": ["allow", "deny"],
        "gold": gold,
        "rationale": "The fixture is intentionally small.",
    }


def _jev_response(model: str = "jev-test", *, usage: dict[str, object] | None = None) -> dict[str, object]:
    response: dict[str, object] = {
        "model": model,
        "answer": {"choice": "allow", "probs": {"allow": 0.9}, "confidence": 0.9},
    }
    if usage is not None:
        response["usage"] = usage
    return response


class BenchmarkApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, responses: list[object], *, provider: str = "jev", repeats: int = 1) -> tuple[dict[str, object], list[object]]:
        output = self.root / "run.jsonl"
        requests: list[object] = []

        def opener(request: object, **_: object) -> FakeResponse:
            requests.append(request)
            payload = responses.pop(0)
            return payload if isinstance(payload, FakeResponse) else FakeResponse(payload)

        env = {"TYPESAFE_API_KEY": "unit-test-key", "OPENROUTER_API_KEY": "unit-test-key"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            benchmark_api.urllib.request, "urlopen", side_effect=opener
        ):
            result = benchmark_api.run_benchmark([_case()], output, provider, "jev-test", repeats)
        return result, requests

    def test_missing_usage_stays_null_and_is_incomplete(self) -> None:
        result, _ = self._run([_jev_response(), _jev_response(usage=None)])
        row = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
        self.assertIsNone(row["prompt_tokens"])
        self.assertIsNone(row["completion_tokens"])
        self.assertIsNone(row["cost_usd"])
        summary = result["summary"]
        self.assertFalse(summary["tokens"]["prompt_tokens"]["complete"])
        self.assertIsNone(summary["tokens"]["prompt_tokens"]["sum"])
        self.assertTrue(summary["accuracy"]["repeats"]["accuracy"] == 1.0)

    def test_jev_criteria_contains_each_option_with_null_value(self) -> None:
        payload = benchmark_api.build_payload("jev", _case(), "jev-test")
        self.assertEqual(payload["questions"]["decision"]["criteria"], {"allow": None, "deny": None})

    def test_openrouter_invalid_json_is_invalid_and_raw_is_retained(self) -> None:
        valid = {
            "model": "or-test",
            "choices": [{"message": {"content": '{"choice":"allow"}'}}],
        }
        invalid = {
            "model": "or-test",
            "choices": [{"message": {"content": "this is not JSON"}}],
        }
        output = self.root / "openrouter.jsonl"
        responses = [valid, invalid]

        def opener(_: object, **__: object) -> FakeResponse:
            return FakeResponse(responses.pop(0))

        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-key"}, clear=True), mock.patch.object(
            benchmark_api.urllib.request, "urlopen", side_effect=opener
        ):
            result = benchmark_api.run_benchmark([_case()], output, "openrouter", "or-test", 1)

        row = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(row["valid"])
        self.assertFalse(row["correct"])
        self.assertEqual(row["error"], "invalid_json")
        self.assertEqual(row["raw"]["choices"][0]["message"]["content"], "this is not JSON")
        self.assertEqual(result["summary"]["counts"]["invalid"], 1)

    def test_wrong_model_cannot_be_valid_or_correct(self) -> None:
        result, _ = self._run([_jev_response(), _jev_response("different-model")])
        row = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
        self.assertFalse(row["model_match"])
        self.assertFalse(row["valid"])
        self.assertFalse(row["correct"])
        self.assertEqual(result["summary"]["counts"]["model_mismatches"], 1)
        self.assertEqual(result["summary"]["accuracy"]["repeats"]["denominator"], 1)
        self.assertEqual(result["summary"]["accuracy"]["repeats"]["correct"], 0)

    def test_http_error_is_recorded_with_status_and_counted(self) -> None:
        result, _ = self._run([_jev_response(), FakeResponse({"error": "server"}, status=500)])
        row = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
        self.assertEqual(row["http_status"], 500)
        self.assertFalse(row["valid"])
        self.assertFalse(row["correct"])
        self.assertEqual(row["error"], "http_error")
        self.assertEqual(result["summary"]["counts"]["invalid"], 1)

    def test_summary_denominators_unique_cases_and_each_pass(self) -> None:
        rows = [
            {"id": "a", "category": "one", "repeat": 1, "correct": True, "valid": True, "model_match": True, "latency_ms": 2},
            {"id": "b", "category": "one", "repeat": 1, "correct": False, "valid": True, "model_match": True, "latency_ms": 4},
            {"id": "a", "category": "one", "repeat": 2, "correct": False, "valid": True, "model_match": True, "latency_ms": 8},
            {"id": "b", "category": "one", "repeat": 2, "correct": True, "valid": True, "model_match": True, "latency_ms": 16},
        ]
        summary = benchmark_api.summarize_records(rows, provider="openrouter", model="or-test")
        self.assertEqual(summary["accuracy"]["unique_cases"]["denominator"], 2)
        self.assertEqual(summary["accuracy"]["unique_cases"]["correct"], 1)
        self.assertEqual(summary["accuracy"]["repeats"]["denominator"], 4)
        self.assertEqual(summary["accuracy"]["repeats"]["correct"], 2)
        self.assertEqual(summary["per_pass"]["1"]["accuracy"]["denominator"], 2)
        self.assertEqual(summary["per_pass"]["2"]["accuracy"]["denominator"], 2)
        self.assertEqual(summary["per_category"]["one"]["latency_ms"]["median_ms"], 6.0)
        self.assertEqual(summary["per_category"]["one"]["latency_ms"]["p95_ms"], 16.0)

    def test_auth_stop_saves_warmup_and_summary_without_leaking_headers(self) -> None:
        output = self.root / "stopped.jsonl"

        def opener(request: object, **__: object) -> FakeResponse:
            self.assertNotIn("unit-test-key", str(request))
            return FakeResponse({"error": "unauthorized"}, status=401)

        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "unit-test-key"}, clear=True), mock.patch.object(
            benchmark_api.urllib.request, "urlopen", side_effect=opener
        ):
            with self.assertRaises(benchmark_api.ProviderHalt):
                benchmark_api.run_benchmark([_case()], output, "jev", "jev-test", 1)

        warmup = json.loads((self.root / "stopped.warmup.json").read_text(encoding="utf-8"))
        self.assertEqual(warmup["http_status"], 401)
        self.assertEqual(warmup["error"], "http_error")
        summary = json.loads((self.root / "stopped.summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["run"]["status"], "stopped")
        self.assertEqual(summary["counts"]["records"], 0)
        self.assertTrue(summary["warmup"]["present"])

    def test_validation_rejects_duplicate_ids_and_invalid_gold(self) -> None:
        with self.assertRaises(benchmark_api.ConfigurationError):
            benchmark_api.validate_cases([_case("same"), _case("same")])
        invalid = _case()
        invalid["gold"] = "other"
        with self.assertRaises(benchmark_api.ConfigurationError):
            benchmark_api.validate_cases([invalid])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
