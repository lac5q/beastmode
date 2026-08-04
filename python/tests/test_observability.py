from __future__ import annotations

import json
from pathlib import Path

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
