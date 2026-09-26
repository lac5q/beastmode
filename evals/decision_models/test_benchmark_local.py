from __future__ import annotations

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import TestCase, mock

try:
    from .benchmark_local import (
        BenchmarkError,
        ResponseParseError,
        build_prompt,
        completion_payload,
        extract_usage,
        load_model_receipt,
        parse_raw_probabilities,
        run_benchmark,
    )
except ImportError:  # direct ``python test_benchmark_local.py`` / pytest path import
    from benchmark_local import (  # type: ignore[no-redef]
        BenchmarkError,
        ResponseParseError,
        build_prompt,
        completion_payload,
        extract_usage,
        load_model_receipt,
        parse_raw_probabilities,
        run_benchmark,
    )


class BenchmarkLocalTests(TestCase):
    def test_prompt_is_exact_and_excludes_gold_and_rationale(self) -> None:
        case = {
            "id": "prompt-1",
            "state": "A request needs verification.",
            "question": "What should happen?",
            "options": ["verify", "escalate", "stop"],
            "gold": "B",
            "rationale": "Never expose this to the model.",
        }
        self.assertEqual(
            build_prompt(case),
            "Context:\nA request needs verification.\n\nQuestion: What should happen?\n"
            "Options:\n(A) verify\n(B) escalate\n(C) stop\nAnswer: (",
        )
        self.assertNotIn("gold", build_prompt(case).lower())
        self.assertNotIn("rationale", build_prompt(case).lower())
        self.assertNotIn("Never expose", build_prompt(case))

    def test_completion_payload_has_native_raw_logit_contract(self) -> None:
        payload = completion_payload("prompt")
        self.assertEqual(
            payload,
            {
                "prompt": "prompt",
                "n_predict": 1,
                "temperature": 0,
                "n_probs": 512,
                "post_sampling_probs": False,
                "cache_prompt": False,
                "return_tokens": True,
                "seed": 0,
            },
        )
        self.assertNotIn("grammar", payload)

    def test_all_labels_are_scaled_and_choice_is_local_argmax(self) -> None:
        response = {
            "completion_probabilities": [
                {
                    "top_logprobs": [
                        {"token": "A", "id": 1, "logprob": -1.0},
                        {"token": "B", "id": 2, "logprob": -2.0},
                        {"token": "C", "id": 3, "logprob": -3.0},
                    ]
                }
            ],
            "content": "C",
        }
        parsed = parse_raw_probabilities(response, ["A", "B", "C"], 2.0)
        self.assertEqual(parsed["choice"], "A")
        self.assertAlmostEqual(sum(parsed["probabilities"].values()), 1.0)
        expected_a = 1.0 / (1.0 + math.exp(-0.5) + math.exp(-1.0))
        self.assertAlmostEqual(parsed["probabilities"]["A"], expected_a)
        # Choice must come from normalized logits, independently of generated content.
        self.assertNotEqual(parsed["choice"], response["content"])

    def test_missing_label_is_invalid_trust_boundary(self) -> None:
        response = {
            "completion_probabilities": [
                {"top_logprobs": [{"token": "A", "logprob": -1.0}, {"token": "B", "logprob": -2.0}]}
            ]
        }
        with self.assertRaisesRegex(ResponseParseError, "missing option token.*C"):
            parse_raw_probabilities(response, ["A", "B", "C"], 1.935)

    def test_nonfinite_logprob_is_rejected(self) -> None:
        response = {
            "completion_probabilities": [
                {
                    "top_logprobs": [
                        {"token": "A", "logprob": float("nan")},
                        {"token": "B", "logprob": -1.0},
                    ]
                }
            ]
        }
        with self.assertRaisesRegex(ResponseParseError, "non-finite"):
            parse_raw_probabilities(response, ["A", "B"], 1.935)

    def test_leading_space_token_does_not_get_silently_equated(self) -> None:
        response = {
            "completion_probabilities": [
                {
                    "top_logprobs": [
                        {"token": " A", "logprob": -1.0},
                        {"token": "B", "logprob": -2.0},
                    ]
                }
            ]
        }
        with self.assertRaisesRegex(ResponseParseError, "missing option token.*A"):
            parse_raw_probabilities(response, ["A", "B"], 1.935)

    def test_receipt_requires_exact_provenance_fields(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text(
                json.dumps(
                    {
                        "repo": "Mapika/decider-4b",
                        "revision": "7ab294cbdf6be6ac17fc818c10cdead744393d92",
                        "file": "model.gguf",
                        "sha256": "a" * 64,
                        "bytes": 42,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_model_receipt(path)["bytes"], 42)
            path.write_text(json.dumps({"repo": "missing"}), encoding="utf-8")
            with self.assertRaises(BenchmarkError):
                load_model_receipt(path)

    def test_usage_prefers_llama_timings_and_counts_transport_tokens(self) -> None:
        usage = extract_usage(
            {
                "tokens": [123],
                "timings": {"predicted_n": 1, "prompt_n": 27, "prompt_ms": 2.0},
            },
            0.125,
        )
        self.assertEqual(usage["tokens_predicted"], 1)
        self.assertEqual(usage["tokens_evaluated"], 27)
        self.assertEqual(usage["prompt_n"], 27)
        self.assertAlmostEqual(usage["latency_ms"], 125.0)


class _FakeServer:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[tuple[str, dict[str, Any] | None]] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/props":
                    self.send_error(404)
                    return
                body = json.dumps(
                    {
                        "model_path": "/models/model.gguf",
                        "model_alias": "server-alias",
                        "default_generation_settings": {"model": "/models/model.gguf"},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length).decode())
                owner.requests.append((self.path, payload))
                body = json.dumps(owner.response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "_FakeServer":
        self.thread.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


class BenchmarkIntegrationTests(TestCase):
    def test_benchmark_warmup_then_two_serial_passes_and_flushes_rows(self) -> None:
        response = {
            "model": "/models/model.gguf",
            "completion_probabilities": [
                {
                    "top_logprobs": [
                        {"token": "A", "id": 1, "logprob": -0.1},
                        {"token": "B", "id": 2, "logprob": -1.0},
                    ]
                }
            ],
            "tokens": [1],
            "timings": {"predicted_n": 1, "prompt_n": 12},
        }
        with TemporaryDirectory() as directory, _FakeServer(response) as server:
            root = Path(directory)
            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    [
                        {
                            "id": "one",
                            "state": "state",
                            "question": "question",
                            "options": ["first", "second"],
                            "category": "smoke",
                            "gold": "first",
                            "rationale": "private rationale",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            receipt_path = root / "receipt.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "repo": "Mapika/decider-4b",
                        "revision": "rev",
                        "file": "model.gguf",
                        "sha256": "b" * 64,
                        "bytes": 10,
                    }
                ),
                encoding="utf-8",
            )
            output_path = root / "results.jsonl"
            result = run_benchmark(
                cases_path=cases_path,
                output_path=output_path,
                base_url=server.base_url,
                model_id="decider-4b-v2",
                model_receipt_path=receipt_path,
                release_temperature=1.935,
                repeats=2,
            )
            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(server.requests), 3)  # one warmup + two measured rows
            self.assertEqual([item[0] for item in server.requests], ["/completion"] * 3)
            for _path, payload in server.requests:
                assert payload is not None
                self.assertEqual(payload["n_predict"], 1)
                self.assertEqual(payload["n_probs"], 512)
                self.assertFalse(payload["post_sampling_probs"])
                self.assertFalse(payload["cache_prompt"])
                self.assertNotIn("grammar", payload)
                self.assertTrue(payload["prompt"].endswith("Answer: ("))
                self.assertNotIn("private rationale", payload["prompt"])
            self.assertEqual(result["summary"]["accuracy"]["repeats"]["correct"], 2)
            self.assertEqual(rows[0]["observed"]["loaded_model_file"], "/models/model.gguf")
            self.assertEqual(rows[0]["provenance"]["model_receipt"]["file"], "model.gguf")
            self.assertIsNone(rows[0]["local_cost"])


if __name__ == "__main__":
    import unittest

    unittest.main()
