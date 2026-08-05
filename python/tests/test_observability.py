from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest

from beastmode.core.observability import (
    child_span_from_meta,
    emit_trace,
    redact_text,
    redact_value,
    trace_metadata,
)
from beastmode.langgraph.context import BeastmodeContext
from beastmode.langgraph.gates import gate_provenance


ROOT = Path(__file__).resolve().parents[2]
MATCH_META = ROOT / "tests" / "fixtures" / "acn-meta" / "match" / "a.json"
ATTESTATIONS = ROOT / "tests" / "fixtures" / "acn-attestations.json"
ATTESTATION_KEY = bytes(32)
ATTESTATION_RUN_ID = "fixture-run"


def test_trace_metadata_marks_drift_without_deciding_a_gate() -> None:
    record = trace_metadata(
        {"goal_id": "goal-1", "phase": "review", "autonomy": "high"},
        {"requested_model": "minimax/MiniMax-M3", "actual_model": "openai/gpt"},
        tags=("child",),
    )
    assert record["attributes"]["goal_id"] == "goal-1"
    assert set(record["tags"]) == {"child", "drift"}
    observed = []
    assert emit_trace(record, observed.append) == record
    assert observed == [record]


def test_child_span_reconstructs_provenance_from_meta() -> None:
    span = child_span_from_meta(
        MATCH_META,
        attestations=ATTESTATIONS,
        attestation_key=ATTESTATION_KEY,
        attestation_run_id=ATTESTATION_RUN_ID,
        parent_span_id="parent",
        goal_id="goal-1",
    )
    assert span["parent_span_id"] == "parent"
    assert span["attributes"]["child_id"] == "a"
    assert span["attributes"]["goal_id"] == "goal-1"
    assert span["status"]["code"] == "ok"
    assert span["tags"] == []


def test_child_span_tokens_reconcile_with_acn_report() -> None:
    span = child_span_from_meta(
        MATCH_META,
        attestations=ATTESTATIONS,
        attestation_key=ATTESTATION_KEY,
        attestation_run_id=ATTESTATION_RUN_ID,
        parent_span_id="parent",
        goal_id="goal-1",
    )
    report = subprocess.run(
        [
            str(ROOT / "scripts" / "acn-report"),
            str(MATCH_META.parent),
            "--attestations",
            str(ATTESTATIONS),
            "--trust-attestations",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "BEASTMODE_ATTESTATION_KEY": ATTESTATION_KEY.hex(),
            "BEASTMODE_ATTESTATION_RUN_ID": ATTESTATION_RUN_ID,
        },
    ).stdout
    match = re.search(r"tokens:\s+in=(\d+) out=(\d+)", report)
    assert match is not None
    usage = span["attributes"]["usage"]
    assert (usage["input_tokens"], usage["output_tokens"]) == tuple(
        int(value) for value in match.groups()
    )


@pytest.mark.parametrize(
    "environment",
    [
        {"LANGSMITH_TRACING": "false"},
        {
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_ENDPOINT": "https://unreachable.invalid",
        },
        {
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_ENDPOINT": "http://127.0.0.1:9",
            "LANGSMITH_TRACING_SAMPLING_RATE": "0",
        },
    ],
)
def test_tracing_configuration_cannot_change_gate_verdict(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
) -> None:
    for key in (
        "LANGSMITH_TRACING",
        "LANGSMITH_ENDPOINT",
        "LANGSMITH_TRACING_SAMPLING_RATE",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    state = {
        "phase": "validate_mechanical",
        "preflight_ok": True,
        "validation_report": {"passed": True},
        "expected_child_ids": ["a"],
        "tasks": [
            {
                "id": "a",
                "goal": "trace parity",
                "allowed_paths": [],
                "verify_cmds": [],
            }
        ],
    }
    runtime = SimpleNamespace(
        context=BeastmodeContext(
            autonomy="high",
            run_dir=MATCH_META.parent,
            attestations=ATTESTATIONS,
            attestation_key=ATTESTATION_KEY,
            attestation_run_id=ATTESTATION_RUN_ID,
        )
    )
    update = gate_provenance(state, runtime)
    assert update["provenance_verdict"] == "ok"
    assert update["provenance_exit_code"] == 0
    assert update["gate_decision"] == "approved"


def test_child_span_rejects_oversized_metadata(tmp_path: Path) -> None:
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"id": "a", "padding": "x" * (256 * 1024)}))
    with pytest.raises(ValueError, match="exceeds"):
        child_span_from_meta(meta)


def test_trace_and_child_fields_are_redacted(tmp_path: Path) -> None:
    token = "ghp_" + "z" * 24
    record = trace_metadata({"goal_id": token, "phase": "review"})
    assert token not in json.dumps(record)


@pytest.mark.parametrize(
    "token",
    (
        "github_" + "pat_" + "a" * 24,
        "sk-" + "proj-" + "a" * 24,
        "sk-" + "ant-" + "a" * 24,
    ),
)
def test_runtime_redaction_covers_public_release_credential_families(token: str) -> None:
    assert token not in redact_text(f"worker output: {token}")
    assert token not in json.dumps(redact_value({"stdout": token}))


def test_structured_trace_secret_values_are_redacted_by_key() -> None:
    secret = "ordinary-secret-value"
    record = emit_trace(
        {
            "attributes": {
                "authorization": f"Bearer {secret}",
                "nested": {
                    "client_secret": secret,
                    "accessToken": secret,
                    "safe": "visible",
                },
            }
        }
    )
    encoded = json.dumps(record)
    assert secret not in encoded
    assert record["attributes"]["authorization"] == "[REDACTED]"
    assert record["attributes"]["nested"]["client_secret"] == "[REDACTED]"
    assert record["attributes"]["nested"]["accessToken"] == "[REDACTED]"
    assert record["attributes"]["nested"]["safe"] == "visible"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("usage", "not-an-object"),
        ("files_changed", {"not": "an-array"}),
        ("commands_run", 7),
    ],
)
def test_child_span_rejects_malformed_structured_metadata(
    tmp_path: Path, field: str, value: object
) -> None:
    body = {
        "id": "child-a",
        "requested_model": "minimax/MiniMax-M3",
        "actual_model": "minimax/MiniMax-M3",
        "stop_reason": "end_turn",
        "usage": {},
        "files_changed": [],
        "commands_run": [],
        "verify": {"passed": True},
    }
    body[field] = value
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        child_span_from_meta(meta)


def test_child_span_rejects_symlinked_metadata(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}")
    link = tmp_path / "meta.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="non-symlink"):
        child_span_from_meta(link)


def test_child_span_reads_opened_inode_when_path_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    safe = {
        "id": "safe-child",
        "requested_model": "minimax/MiniMax-M3",
        "actual_model": "minimax/MiniMax-M3",
        "stop_reason": "end_turn",
        "usage": {},
        "files_changed": [],
        "commands_run": [],
        "verify": {"passed": True},
    }
    attacker = {**safe, "id": "attacker-controlled"}
    meta = tmp_path / "meta.json"
    replacement = tmp_path / "replacement.json"
    meta.write_text(json.dumps(safe), encoding="utf-8")
    replacement.write_text(json.dumps(attacker), encoding="utf-8")

    real_read = os.read
    swapped = False

    def swap_after_open(fd: int, size: int) -> bytes:
        nonlocal swapped
        if not swapped:
            swapped = True
            meta.unlink()
            meta.symlink_to(replacement)
        return real_read(fd, size)

    monkeypatch.setattr(os, "read", swap_after_open)
    span = child_span_from_meta(meta)
    assert swapped is True
    assert span["attributes"]["child_id"] == "safe-child"
