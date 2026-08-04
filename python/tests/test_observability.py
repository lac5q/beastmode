from __future__ import annotations

import json
from pathlib import Path

import pytest

from beastmode.core.observability import child_span_from_meta, emit_trace, trace_metadata


ROOT = Path(__file__).resolve().parents[2]
MATCH_META = ROOT / "tests" / "fixtures" / "acn-meta" / "match" / "a.json"


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
    span = child_span_from_meta(MATCH_META, parent_span_id="parent", goal_id="goal-1")
    assert span["parent_span_id"] == "parent"
    assert span["attributes"]["child_id"] == "a"
    assert span["attributes"]["goal_id"] == "goal-1"
    assert span["status"]["code"] == "ok"
    assert span["tags"] == []


def test_child_span_rejects_oversized_metadata(tmp_path: Path) -> None:
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"id": "a", "padding": "x" * (256 * 1024)}))
    with pytest.raises(ValueError, match="exceeds"):
        child_span_from_meta(meta)


def test_trace_and_child_fields_are_redacted(tmp_path: Path) -> None:
    token = "ghp_" + "z" * 24
    record = trace_metadata({"goal_id": token, "phase": "review"})
    assert token not in json.dumps(record)


def test_child_span_rejects_symlinked_metadata(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}")
    link = tmp_path / "meta.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="non-symlink"):
        child_span_from_meta(link)
