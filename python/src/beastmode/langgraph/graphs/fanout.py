"""Composable ACN fan-out without the full Beastmode pipeline."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Callable, Mapping, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from beastmode.core.observability import redact_value

from ..dispatch import group_tasks_by_lane
from ..limits import validate_executor_result, validate_tasks


Executor = Callable[[dict[str, Any]], Mapping[str, Any]]


class FanoutState(TypedDict, total=False):
    """Small state vocabulary for the fan-out-only template."""

    goal: str
    goal_id: str
    run_dir: str
    tasks: list[dict[str, Any]]
    lane_batches: list[list[dict[str, Any]]]
    lane_index: int
    task: dict[str, Any]
    task_results: Annotated[list[dict[str, Any]], operator.add]
    execution_report: dict[str, Any]
    status: str


def _prepare(state: Mapping[str, Any]) -> dict[str, Any]:
    tasks = validate_tasks(state.get("tasks", ()))
    return {
        "tasks": tasks,
        "lane_batches": group_tasks_by_lane(tasks),
        "lane_index": 0,
    }


def _lane_route(state: Mapping[str, Any]):
    batches = state.get("lane_batches") or []
    index = int(state.get("lane_index", 0))
    if index >= len(batches):
        return "validate"
    return [
        Send(
            "execute",
            {
                "goal": state.get("goal", ""),
                "goal_id": state.get("goal_id"),
                "run_dir": state.get("run_dir"),
                "task": dict(task),
            },
        )
        for task in batches[index]
    ]


def _advance(state: Mapping[str, Any]) -> dict[str, int]:
    return {"lane_index": int(state.get("lane_index", 0)) + 1}


def _validate(state: Mapping[str, Any]) -> dict[str, Any]:
    expected = [str(task["id"]) for task in validate_tasks(state.get("tasks", ()))]
    results = list(state.get("task_results") or ())
    by_id = {
        str(result.get("id")): result
        for result in results
        if isinstance(result, Mapping) and result.get("id")
    }
    failures = [
        task_id
        for task_id in expected
        if task_id not in by_id or by_id[task_id].get("execution_status") != "ok"
    ]
    unexpected = sorted(set(by_id).difference(expected))
    complete = not failures and not unexpected and len(by_id) == len(expected)
    return {
        "execution_report": {
            "complete": complete,
            "trusted": False,
            "expected": expected,
            "observed": sorted(by_id),
            "failed": failures,
            "unexpected": unexpected,
        },
        "status": "executed" if complete else "failed",
    }


def build_fanout(
    executor: Executor,
    *,
    state_schema: type = FanoutState,
):
    """Compile a lane-grouped ``Send`` fan-out with an untrusted execution join.

    Completion proves only that every executor returned ``execution_status=ok``.
    It never emits Beastmode's protected ``validated`` state; callers must add
    independent mechanical validation and provenance gates.
    """

    def execute(state: Mapping[str, Any]) -> dict[str, Any]:
        task = state.get("task")
        task = task if isinstance(task, Mapping) else {}
        result = dict(redact_value(validate_executor_result(executor(dict(state)))))
        return {"task_results": [{**result, "id": str(task.get("id") or "")}]}

    graph = StateGraph(state_schema)
    graph.add_node("prepare", _prepare)
    graph.add_node("execute", execute)
    graph.add_node("advance", _advance)
    graph.add_node("validate", _validate, defer=True)
    graph.add_edge(START, "prepare")
    graph.add_conditional_edges("prepare", _lane_route, {"validate": "validate"})
    graph.add_edge("execute", "advance")
    graph.add_conditional_edges("advance", _lane_route, {"validate": "validate"})
    graph.add_edge("validate", END)
    return graph.compile(name="beastmode-acn-fanout")


__all__ = ["FanoutState", "build_fanout"]
