"""Framework-neutral trace metadata for Beastmode runs.

The helpers return OpenTelemetry-shaped dictionaries but do not import or
require an observability SDK.  Callers may hand the result to OpenTelemetry,
LangSmith, a logger, or nowhere at all.  No gate decision is derived from a
trace callback or tracing backend.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .provenance import check_provenance


def trace_metadata(
    state: Mapping[str, Any],
    meta: Mapping[str, Any] | None = None,
    *,
    tags: Iterable[str] = (),
) -> dict[str, Any]:
    """Build stable OTel-style attributes without contacting a vendor."""
    meta = meta or {}
    requested = meta.get("requested_model") or state.get("executor_model")
    actual = meta.get("actual_model")
    verdict = meta.get("provenance_verdict") or state.get("provenance_verdict")
    tag_set = {str(tag) for tag in tags}
    if verdict and verdict != "ok":
        tag_set.add(str(verdict))
    if requested and actual and requested != actual:
        tag_set.add("drift")
    if actual in (None, "") and "actual_model" in meta and requested:
        tag_set.add("unverifiable")
    return {
        "name": "beastmode.node",
        "kind": "internal",
        "attributes": {
            "goal_id": state.get("goal_id") or state.get("thread_id"),
            "phase": state.get("phase"),
            "seat": meta.get("seat") or state.get("seat") or "executor",
            "autonomy": state.get("autonomy"),
            "requested_model": requested,
            "actual_model": actual,
        },
        "tags": sorted(tag_set),
    }


def child_span_from_meta(
    meta_path: Path,
    *,
    parent_span_id: str | None = None,
    goal_id: str | None = None,
) -> dict[str, Any]:
    """Synthesize a child span from one canonical child metadata file."""
    path = Path(meta_path)
    with path.open(encoding="utf-8") as handle:
        meta = json.load(handle)
    if not isinstance(meta, Mapping):
        raise ValueError(f"child metadata must be an object: {path}")
    child_id = str(meta.get("id") or path.parent.name)
    result = check_provenance(path.parent, expect=[child_id])
    tags = [] if result.verdict == "ok" else [result.verdict]
    return {
        "name": "beastmode.child",
        "kind": "internal",
        "parent_span_id": parent_span_id,
        "attributes": {
            "child_id": child_id,
            "goal_id": goal_id,
            "requested_model": meta.get("requested_model"),
            "actual_model": meta.get("actual_model"),
            "stop_reason": meta.get("stop_reason"),
            "usage": dict(meta.get("usage") or {}),
            "files_changed": list(meta.get("files_changed") or []),
            "commands_run": list(meta.get("commands_run") or []),
        },
        "tags": tags,
        "status": {
            "code": "ok" if result.verdict == "ok" else "error",
            "description": "; ".join(result.messages),
        },
    }


def emit_trace(
    record: Mapping[str, Any],
    callback: Callable[[Mapping[str, Any]], Any] | None = None,
) -> Mapping[str, Any]:
    """Best-effort callback hook; tracing failures never affect the caller."""
    if callback is None:
        return record
    try:
        callback(record)
    except Exception:
        pass
    return record
