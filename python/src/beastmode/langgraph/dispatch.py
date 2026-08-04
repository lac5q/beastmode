"""ACN task fan-out helpers for LangGraph ``Send`` routing."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from langgraph.types import Send


def group_tasks_by_lane(tasks: Iterable[Mapping[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group tasks by lane while preserving first-seen lane/task order."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        item = dict(task)
        lane = str(item.get("lane", "default"))
        grouped.setdefault(lane, []).append(item)
    return list(grouped.values())


def first_lane_sends(state: Mapping[str, Any]):
    """Return one ``Send`` per task in the first lane, or validate if empty."""
    batches = state.get("lane_batches") or []
    if not batches:
        return "validate_mechanical"
    return _sends_for_batch(batches[0], state)


def next_lane_sends(state: Mapping[str, Any]):
    """Advance to the next sequential lane after all current children join."""
    batches = state.get("lane_batches") or []
    index = int(state.get("lane_index", 0)) + 1
    if index >= len(batches):
        return "validate_mechanical"
    return _sends_for_batch(batches[index], state)


def _sends_for_batch(batch: Iterable[Mapping[str, Any]], state: Mapping[str, Any]):
    return [
        Send(
            "execute",
            {
                "goal": state.get("goal", ""),
                "goal_id": state.get("goal_id"),
                "run_dir": state.get("run_dir"),
                "expected_child_ids": state.get("expected_child_ids", []),
                "task": dict(task),
            },
        )
        for task in batch
    ]
