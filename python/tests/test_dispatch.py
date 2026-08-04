from __future__ import annotations

from beastmode.langgraph.dispatch import group_tasks_by_lane


def test_lane_grouping_keeps_same_lane_tasks_together() -> None:
    tasks = [
        {"id": "a", "lane": "economy"},
        {"id": "b", "lane": "frontier"},
        {"id": "c", "lane": "economy"},
    ]
    assert [[task["id"] for task in batch] for batch in group_tasks_by_lane(tasks)] == [
        ["a", "c"],
        ["b"],
    ]
