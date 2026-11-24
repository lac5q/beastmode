#!/usr/bin/env python3
"""Run the frozen 32-case Choice contract against a caller-provided real encoder.

This runner intentionally reports schema/transport results only. It never reads
gold labels and never reports task accuracy. It does not read API keys; the
endpoint must be reachable without a key or be configured by the caller outside
this script.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "1"

from clm.embedder import Embedder
from clm.engine import Engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default=os.environ.get("CLM_EMB_URL"), help="real /v1/embeddings URL")
    parser.add_argument("--model", default="qwen3-8b")
    parser.add_argument("--cases", type=Path, required=True, help="frozen 32-case Choice JSON fixture")
    parser.add_argument("--checkpoint", type=Path, default=Path(__file__).with_name("CLM_v0.1-8B.pt"))
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("--endpoint or CLM_EMB_URL is required; no endpoint call is made without it")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if len(cases) != 32:
        parser.error(f"expected exactly 32 frozen cases, found {len(cases)}")

    embedder = Embedder(url=args.endpoint, model=args.model, api_key=None, timeout=300.0)
    engine = Engine(embedder=embedder, checkpoint=str(args.checkpoint), device="cpu", action_cache="0")
    results = []
    for case in cases:
        options = list(case["options"])
        question = {
            "type": "choice",
            "instructions": case["question"],
            "criteria": {option: None for option in options},
        }
        started = time.perf_counter()
        response = engine.answer(case["state"], {"decision": question})
        elapsed_ms = (time.perf_counter() - started) * 1000
        answer = response["answers"]["decision"]
        probabilities = answer["probabilities"]
        if answer["type"] != "choice" or list(probabilities) != options:
            raise AssertionError(f"schema mismatch for {case['id']}")
        if abs(sum(float(value) for value in probabilities.values()) - 1.0) > 1e-5:
            raise AssertionError(f"probability sum mismatch for {case['id']}")
        results.append(
            {
                "id": case["id"],
                "type": answer["type"],
                "choice": answer["choice"],
                "probability_keys": options,
                "probability_sum": sum(float(value) for value in probabilities.values()),
                "input_tokens": response["usage"]["input_tokens"],
                "elapsed_ms": elapsed_ms,
            }
        )
    print(
        json.dumps(
            {
                "status": "pass",
                "cases": len(results),
                "semantic_status": "real encoder endpoint supplied by caller; this runner reports contract only",
                "accuracy_reported": False,
                "gold_labels_read": False,
                "api_key_read": False,
                "results": results,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
