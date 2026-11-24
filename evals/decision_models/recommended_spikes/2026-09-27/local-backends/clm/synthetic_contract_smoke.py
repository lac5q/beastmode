#!/usr/bin/env python3
"""Bounded CLM head/schema smoke with explicitly fake, nonsemantic embeddings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

# The pinned CLM source currently calls torch.load without an explicit flag.
# Force the safe loader before any source import can load a checkpoint.
os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "1"

import numpy as np

from clm.engine import Engine, ModelNotFound


class FakeNonsemanticEmbedder:
    """Deterministic vectors for plumbing checks; these have no language meaning."""

    hidden = 4096

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> tuple[np.ndarray, int]:
        self.calls.append(list(texts))
        vectors: list[np.ndarray] = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
            rng = np.random.default_rng(seed)
            vector = rng.standard_normal(self.hidden, dtype=np.float32)
            vectors.append(vector / (np.linalg.norm(vector) + 1e-12))
        return np.stack(vectors), sum(max(1, len(text.split())) for text in texts)


def _assert_distribution(answer: dict[str, Any], keys: list[str]) -> None:
    assert answer["type"] == "choice"
    assert answer["choice"] in keys
    probabilities = answer["probabilities"]
    assert list(probabilities) == keys
    assert all(np.isfinite(float(value)) and 0 <= float(value) <= 1 for value in probabilities.values())
    assert abs(sum(float(value) for value in probabilities.values()) - 1.0) < 1e-6


def _validate_answers(answers: dict[str, dict[str, Any]]) -> None:
    noul = answers["safe"]
    assert noul["type"] == "noul"
    assert np.isfinite(float(noul["noul"])) and 0 <= float(noul["noul"]) <= 1

    _assert_distribution(answers["route"], ["billing", "technical", "other"])

    score = answers["severity"]
    assert score["type"] == "score"
    assert 0 <= float(score["score"]) <= 2
    assert list(score["probabilities"]) == ["0", "1", "2"]
    assert abs(sum(float(value) for value in score["probabilities"].values()) - 1.0) < 1e-6
    assert all(np.isfinite(float(value)) for value in score["probabilities"].values())


def run(checkpoint: Path) -> dict[str, Any]:
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")
    import torch

    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)

    fake = FakeNonsemanticEmbedder()
    engine = Engine(embedder=fake, checkpoint=str(checkpoint), device="cpu", action_cache="1MiB")
    head = engine.heads["clm-latest"].ensure()

    rng = np.random.default_rng(20260927)
    states = rng.standard_normal((3, 4096), dtype=np.float32)
    actions = rng.standard_normal((5, 4096), dtype=np.float32)
    projected_states, projected_actions = head.project(states, actions)
    assert projected_states.shape == (3, 512)
    assert projected_actions.shape == (5, 512)
    norm_error = max(
        float(np.max(np.abs(np.linalg.norm(projected_states, axis=1) - 1))),
        float(np.max(np.abs(np.linalg.norm(projected_actions, axis=1) - 1))),
    )
    assert np.isfinite(projected_states).all() and np.isfinite(projected_actions).all()
    assert norm_error < 1e-5

    questions = {
        "safe": {"type": "noul", "instructions": "Is the synthetic state safe?"},
        "route": {
            "type": "choice",
            "instructions": "Which synthetic queue?",
            "criteria": {"billing": "Billing queue", "technical": "Technical queue", "other": "Other queue"},
        },
        "severity": {
            "type": "score",
            "instructions": "How severe?",
            "criteria": ["low", "medium", "high"],
        },
    }
    state = {"fixture": "deterministic synthetic embedding", "n": 1}
    first = engine.answer(state, questions)
    calls_after_first = len(fake.calls)
    second = engine.answer(state, questions)
    _validate_answers(first["answers"])
    _validate_answers(second["answers"])
    assert first["answers"] == second["answers"]
    assert calls_after_first == 2
    assert len(fake.calls) == calls_after_first
    assert second["usage"]["input_tokens"] == 0

    invalid: list[dict[str, str]] = []

    def expect(label: str, action) -> None:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - receipt records exact contract failures.
            invalid.append({"case": label, "error_type": type(exc).__name__, "message": str(exc)})
        else:
            raise AssertionError(f"invalid input was accepted: {label}")

    expect("empty_questions", lambda: engine.answer("state", {}))
    expect("unknown_type", lambda: engine.answer("state", {"x": {"type": "unknown", "instructions": "x"}}))
    expect("empty_choice", lambda: engine.answer("state", {"x": {"type": "choice", "instructions": "x", "criteria": {}}}))
    expect("one_level_score", lambda: engine.answer("state", {"x": {"type": "score", "instructions": "x", "criteria": ["one"]}}))
    expect("bad_temperature", lambda: engine.answer("state", questions, temperature=0))
    expect("unknown_model", lambda: engine.answer("state", questions, model="unknown"))

    assert {item["case"] for item in invalid} == {
        "empty_questions", "unknown_type", "empty_choice", "one_level_score", "bad_temperature", "unknown_model"
    }
    return {
        "status": "pass",
        "semantic_status": "FAKE NONSEMANTIC: deterministic synthetic embeddings; no task accuracy claim",
        "advertised_model_inference": False,
        "checkpoint": str(checkpoint),
        "torch_force_weights_only_load": os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"],
        "torch_version": torch.__version__,
        "projection": {
            "state_shape": list(projected_states.shape),
            "action_shape": list(projected_actions.shape),
            "state_action_norm_max_error": norm_error,
            "finite": True,
            "head_generation": head.generation,
            "projection_dim": head.proj_dim,
            "scale": head.scale,
            "n_params": head.n_params,
        },
        "schema": {"types": ["noul", "choice", "score"], "validated": True},
        "cache": {
            "embedding_calls_first_request": calls_after_first,
            "embedding_calls_after_identical_request": len(fake.calls),
            "identical_request_reused_vectors": True,
            "second_request_input_tokens": second["usage"]["input_tokens"],
            "arena": engine.arena.stats() if engine.arena else None,
        },
        "invalid_inputs": invalid,
        "first_answers": first["answers"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=Path(__file__).with_name("CLM_v0.1-8B.pt"))
    args = parser.parse_args()
    if not args.checkpoint.is_file():
        parser.error(f"checkpoint not found: {args.checkpoint}")
    print(json.dumps(run(args.checkpoint.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
