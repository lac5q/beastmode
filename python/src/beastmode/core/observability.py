"""Framework-neutral trace metadata for Beastmode runs.

The helpers return OpenTelemetry-shaped dictionaries but do not import or
require an observability SDK.  Callers may hand the result to OpenTelemetry,
LangSmith, a logger, or nowhere at all.  No gate decision is derived from a
trace callback or tracing backend.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile
from itertools import islice
from typing import Any, Callable, Iterable, Mapping

from .provenance import check_provenance


MAX_PUBLIC_TEXT_CHARS = 16_384
MAX_TRACE_ITEMS = 128
MAX_CHILD_META_BYTES = 256 * 1024
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"),
    re.compile(r"/(?:home|Users)/[^/\s]+"),
    re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+"),
    re.compile(
        r"(?i)\b(?:password|passwd|secret|token|api[-_]?key|authorization|"
        r"database[-_]?url|access[-_]?token)\b\s*[:=]\s*[^\s,;]+"
    ),
)
_SECRET_KEY_NAMES = {
    "authorization",
    "credential",
    "credentials",
    "database_url",
    "private_key",
    "token",
}
_SECRET_KEY_SUFFIXES = (
    "apikey",
    "api_key",
    "credential",
    "password",
    "passwd",
    "privatekey",
    "private_key",
    "secret",
    "token",
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
        sanitized = {}
        for key, item in islice(value.items(), MAX_TRACE_ITEMS):
            raw_key = str(key)
            safe_key = redact_text(raw_key, limit=limit)
            sanitized[safe_key] = (
                "[REDACTED]"
                if _is_secret_key(raw_key) or safe_key == "[REDACTED]"
                else redact_value(item, limit=limit, depth=depth + 1)
            )
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [
            redact_value(item, limit=limit, depth=depth + 1)
            for item in islice(value, MAX_TRACE_ITEMS)
        ]
    if isinstance(value, str):
        return redact_text(value, limit=limit)
    if isinstance(value, bytes):
        return redact_text(value.decode(errors="replace"), limit=limit)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(value, limit=limit)


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
        "attributes": redact_value({
            "goal_id": state.get("goal_id") or state.get("thread_id"),
            "phase": state.get("phase"),
            "seat": meta.get("seat") or state.get("seat") or "executor",
            "autonomy": state.get("autonomy"),
            "requested_model": requested,
            "actual_model": actual,
        }),
        "tags": redact_value(sorted(tag_set)),
    }


def child_span_from_meta(
    meta_path: Path,
    *,
    attestations: Path | None = None,
    parent_span_id: str | None = None,
    goal_id: str | None = None,
) -> dict[str, Any]:
    """Synthesize a child span from one canonical child metadata file."""
    path = Path(meta_path)
    payload = _read_regular_file(path)
    try:
        meta = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("child metadata must be valid bounded JSON") from exc
    if not isinstance(meta, Mapping):
        raise ValueError("child metadata must be a JSON object")
    child_id = redact_text(meta.get("id") or path.parent.name)
    usage = _metadata_mapping(meta, "usage")
    files_changed = _metadata_sequence(meta, "files_changed")
    commands_run = _metadata_sequence(meta, "commands_run")
    # The canonical checker is intentionally retained, but it receives the
    # already-opened bytes in a private directory.  It never reopens the
    # attacker-controlled pathname after the no-follow open above.
    with tempfile.TemporaryDirectory(prefix="beastmode-meta-check-") as check_root:
        safe_path = Path(check_root) / "meta.json"
        safe_path.write_bytes(payload)
        result = check_provenance(
            Path(check_root), expect=[child_id], attestations=attestations
        )
    tags = [] if result.verdict == "ok" else [result.verdict]
    return {
        "name": "beastmode.child",
        "kind": "internal",
        "parent_span_id": redact_text(parent_span_id or ""),
        "attributes": {
            "child_id": child_id,
            "goal_id": redact_text(goal_id or ""),
            "requested_model": redact_text(meta.get("requested_model")),
            "actual_model": redact_text(meta.get("actual_model")),
            "stop_reason": redact_text(meta.get("stop_reason")),
            "usage": redact_value(dict(usage)),
            "files_changed": redact_value(list(files_changed)),
            "commands_run": redact_value(list(commands_run)),
        },
        "tags": tags,
        "status": {
            "code": "ok" if result.verdict == "ok" else "error",
            "description": redact_text("; ".join(result.messages)),
        },
    }


def emit_trace(
    record: Mapping[str, Any],
    callback: Callable[[Mapping[str, Any]], Any] | None = None,
) -> Mapping[str, Any]:
    """Best-effort callback hook; tracing failures never affect the caller."""
    safe_record = redact_value(dict(record))
    if callback is None:
        return safe_record
    try:
        callback(safe_record)
    except Exception:
        pass
    return safe_record


def _is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    compact = normalized.replace("_", "")
    parts = set(normalized.split("_"))
    compact_markers = (
        "apikey",
        "authorization",
        "credential",
        "password",
        "passwd",
        "privatekey",
        "secret",
        "token",
    )
    return (
        normalized in _SECRET_KEY_NAMES
        or bool(parts.intersection({"authorization", "credential", "credentials", "passwd", "password", "secret"}))
        or any(normalized.endswith(f"_{suffix}") for suffix in _SECRET_KEY_SUFFIXES)
        or compact in _SECRET_KEY_SUFFIXES
        or any(compact.startswith(marker) or compact.endswith(marker) for marker in compact_markers)
    )


def _read_regular_file(path: Path) -> bytes:
    """Read one bounded regular file through an inode-stable no-follow fd."""
    if path.name in {"", ".", ".."}:
        raise ValueError("child metadata must name a regular file")
    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(path.parent, directory_flags)
    except OSError as exc:
        raise ValueError("child metadata parent must be a regular, non-symlink directory") from exc
    try:
        file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        file_flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path.name, file_flags, dir_fd=directory_fd)
        except OSError as exc:
            raise ValueError("child metadata must be a regular, non-symlink file") from exc
    finally:
        os.close(directory_fd)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("child metadata must be a regular, non-symlink file")
        if metadata.st_size > MAX_CHILD_META_BYTES:
            raise ValueError(f"child metadata exceeds {MAX_CHILD_META_BYTES} bytes")
        chunks = bytearray()
        while len(chunks) <= MAX_CHILD_META_BYTES:
            chunk = os.read(fd, min(8192, MAX_CHILD_META_BYTES + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        if len(chunks) > MAX_CHILD_META_BYTES:
            raise ValueError(f"child metadata exceeds {MAX_CHILD_META_BYTES} bytes")
        return bytes(chunks)
    finally:
        os.close(fd)


def _metadata_mapping(meta: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = meta.get(field)
    if not isinstance(value, Mapping):
        raise ValueError(f"child metadata {field} must be a JSON object")
    return value


def _metadata_sequence(meta: Mapping[str, Any], field: str) -> list[Any]:
    value = meta.get(field)
    if not isinstance(value, list):
        raise ValueError(f"child metadata {field} must be a JSON array")
    return value
