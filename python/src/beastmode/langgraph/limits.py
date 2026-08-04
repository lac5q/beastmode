"""Boundaries for caller-controlled LangGraph work."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


MAX_CONCURRENCY = 32
MAX_TASKS = 128
MAX_TASK_BYTES = 64 * 1024
MAX_TASK_BATCH_BYTES = 1024 * 1024
MAX_TASK_LIST_ITEMS = 128
MAX_TASK_TEXT_CHARS = 16_384
MAX_EXECUTOR_RESULT_BYTES = 256 * 1024
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def validate_concurrency(value: object) -> int:
    """Return a safe positive concurrency value or reject the request."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("concurrency must be a positive integer")
    if value > MAX_CONCURRENCY:
        raise ValueError(f"concurrency cannot exceed {MAX_CONCURRENCY}")
    return value


def validate_tasks(value: object) -> list[dict[str, Any]]:
    """Return a JSON-safe, bounded task batch suitable for Send fan-out."""
    if not isinstance(value, (list, tuple)):
        raise ValueError("tasks must be a list")
    if len(value) > MAX_TASKS:
        raise ValueError(f"task count cannot exceed {MAX_TASKS}")
    tasks: list[dict[str, Any]] = []
    total_bytes = 0
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise ValueError(f"ACN task {index} must be an object")
        task = dict(raw)
        task_id = task.get("id")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError(f"ACN task {index} has an invalid id")
        goal = task.get("goal")
        if not isinstance(goal, str) or len(goal) > MAX_TASK_TEXT_CHARS:
            raise ValueError(
                f"ACN task {index} goal must be a string no longer than {MAX_TASK_TEXT_CHARS} characters"
            )
        for field in ("allowed_paths", "verify_cmds"):
            _validate_string_list(task.get(field), field=field, index=index)
        try:
            encoded = json.dumps(task, ensure_ascii=False, separators=(",", ":")).encode()
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError(f"ACN task {index} must contain bounded JSON values") from exc
        if len(encoded) > MAX_TASK_BYTES:
            raise ValueError(f"ACN task {index} exceeds {MAX_TASK_BYTES} bytes")
        total_bytes += len(encoded)
        if total_bytes > MAX_TASK_BATCH_BYTES:
            raise ValueError(f"task batch exceeds {MAX_TASK_BATCH_BYTES} bytes")
        tasks.append(task)
    return tasks


def validate_executor_result(value: object) -> dict[str, Any]:
    """Reject executor updates that could make reducer-backed state unbounded."""
    if not isinstance(value, Mapping):
        raise ValueError("executor result must be an object")
    result = dict(value)
    try:
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("executor result must contain bounded JSON values") from exc
    if len(encoded) > MAX_EXECUTOR_RESULT_BYTES:
        raise ValueError(f"executor result exceeds {MAX_EXECUTOR_RESULT_BYTES} bytes")
    return result


def _validate_string_list(value: object, *, field: str, index: int) -> None:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"ACN task {index} field {field} must be a list")
    if len(value) > MAX_TASK_LIST_ITEMS:
        raise ValueError(
            f"ACN task {index} field {field} cannot exceed {MAX_TASK_LIST_ITEMS} items"
        )
    for item in value:
        if not isinstance(item, str) or len(item) > MAX_TASK_TEXT_CHARS:
            raise ValueError(
                f"ACN task {index} field {field} contains an invalid string"
            )
