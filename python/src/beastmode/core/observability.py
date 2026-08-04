"""Framework-neutral trace metadata for Beastmode runs.

The helpers return OpenTelemetry-shaped dictionaries but do not import or
require an observability SDK.  Callers may hand the result to OpenTelemetry,
LangSmith, a logger, or nowhere at all.  No gate decision is derived from a
trace callback or tracing backend.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping

from .provenance import check_provenance


MAX_PUBLIC_TEXT_CHARS = 16_384
MAX_TRACE_ITEMS = 128
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"),
    re.compile(r"/(?:home|Users)/[^/\s]+"),
    re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+"),
)


def redact_text(value: object, *, limit: int = MAX_PUBLIC_TEXT_CHARS) -> str:
    """Bound and redact text before it enters traces, reports, or graph state."""
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > limit:
        return text[:limit] + "…[TRUNCATED]"
    return text


def redact_value(value: Any, *, limit: int = MAX_PUBLIC_TEXT_CHARS, depth: int = 0) -> Any:
    """Recursively sanitize bounded trace/state values without changing scalars."""
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(key): redact_value(item, limit=limit, depth=depth + 1)
            for key, item in list(value.items())[:MAX_TRACE_ITEMS]
        }
    if isinstance(value, (list, tuple, set)):
        return [
            redact_value(item, limit=limit, depth=depth + 1)
            for item in list(value)[:MAX_TRACE_ITEMS]
        ]
    if isinstance(value, str):
        return redact_text(value, limit=limit)
    return value


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
            "usage": redact_value(dict(meta.get("usage") or {})),
            "files_changed": redact_value(list(meta.get("files_changed") or [])),
            "commands_run": redact_value(list(meta.get("commands_run") or [])),
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
