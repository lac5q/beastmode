"""Small, replaceable nodes used by the initial pipeline graph."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from langgraph.runtime import Runtime

from beastmode.core.contract import AcceptanceContract
from beastmode.core.observability import redact_value
from beastmode.core.schema import concurrency_default, required_batch_fields, required_task_fields
from beastmode.core.seats import preflight_seat, resolve_alias

from .context import BeastmodeContext
from .limits import validate_concurrency


NodeCallable = Callable[[dict[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class PipelineDependencies:
    """Optional integrations; defaults are deterministic and side-effect-free."""

    executor: NodeCallable | None = None
    reviewer: NodeCallable | None = None
    merger: NodeCallable | None = None
    challenger: NodeCallable | None = None


def preflight(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    context = runtime.context
    requested = state.get("requested_seats")
    requested = requested if isinstance(requested, Mapping) else {}
    batch = dict(state.get("batch") or {})
    batch.setdefault("autonomy", state.get("autonomy") or getattr(context, "autonomy", "medium"))
    batch.setdefault("director_model", state.get("director_model") or requested.get("frontier") or "unconfigured/director")
    batch.setdefault("executor_model", state.get("executor_model") or requested.get("economy") or "unconfigured/executor")
    batch.setdefault("watcher_model", state.get("watcher_model") or requested.get("watcher") or "unconfigured/watcher")
    if "concurrency" not in batch:
        batch["concurrency"] = state["concurrency"] if "concurrency" in state else concurrency_default()
    batch["concurrency"] = validate_concurrency(batch["concurrency"])
    repo = Path(str(state.get("repo") or Path.cwd()))
    try:
        git_status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
        )
        status_lines = [line for line in git_status.stdout.splitlines() if line]
        git_report = {"available": git_status.returncode == 0, "dirty": bool(status_lines), "lines": status_lines}
    except OSError as exc:
        git_report = {"available": False, "dirty": None, "lines": [str(exc)]}
    seat_report: dict[str, str] = {}
    for seat_name, model in (
        ("director", batch["director_model"]),
        ("executor", batch["executor_model"]),
        ("watcher", batch["watcher_model"]),
    ):
        try:
            preflight_seat(resolve_alias(str(model), repo=repo), available_models=None)
            seat_report[seat_name] = "resolved"
        except Exception as exc:
            seat_report[seat_name] = f"unavailable: {exc}"
    return {
        "phase": "preflight",
        "goal_id": getattr(context, "goal_id", None) or state.get("goal_id"),
        "preflight_ok": bool(
            git_report["available"]
            and seat_report
            and all(value == "resolved" for value in seat_report.values())
        ),
        "autonomy": batch["autonomy"],
        "director_model": batch["director_model"],
        "executor_model": batch["executor_model"],
        "watcher_model": batch["watcher_model"],
        "concurrency": batch["concurrency"],
        "batch": batch,
        "preflight_report": {"git": git_report, "seats": seat_report},
    }


def contract(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    if state.get("acceptance_contract"):
        return {"phase": "contract"}
    value = AcceptanceContract(
        goal=str(state.get("goal", "")),
        user_visible_acceptance=(str(state.get("goal", "")),),
    )
    return {"phase": "contract", "acceptance_contract": value.to_mapping()}


def design(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    batch = state.get("batch")
    batch_tasks = batch.get("tasks", ()) if isinstance(batch, Mapping) else ()
    tasks = list(state.get("tasks") or batch_tasks)
    if not tasks:
        tasks = [
            {
                "id": "goal",
                "goal": str(state.get("goal", "")),
                "allowed_paths": [],
                "verify_cmds": [],
            }
        ]
    return {"phase": "design", "tasks": tasks, "batch": {**dict(batch or {}), "tasks": tasks}}


def challenge(
    state: Mapping[str, Any],
    runtime: Runtime[BeastmodeContext],
    dependencies: PipelineDependencies,
) -> dict[str, Any]:
    """Run the optional cross-family design challenge before dispatch."""
    if dependencies.challenger is None:
        return {"phase": "challenge", "challenge_report": {"passed": True, "skipped": True}}
    return {"phase": "challenge", **dict(dependencies.challenger(dict(state)))}


def dispatch(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    from .dispatch import group_tasks_by_lane

    tasks = list(state.get("tasks", ()))
    batch = dict(state.get("batch") or {})
    context = runtime.context
    requested = state.get("requested_seats")
    requested = requested if isinstance(requested, Mapping) else {}
    batch.setdefault("autonomy", state.get("autonomy") or getattr(context, "autonomy", "medium"))
    batch.setdefault("director_model", state.get("director_model") or requested.get("frontier") or "unconfigured/director")
    batch.setdefault("executor_model", state.get("executor_model") or requested.get("economy") or "unconfigured/executor")
    batch.setdefault("watcher_model", state.get("watcher_model") or requested.get("watcher") or "unconfigured/watcher")
    if "concurrency" not in batch:
        batch["concurrency"] = state["concurrency"] if "concurrency" in state else concurrency_default()
    batch["concurrency"] = validate_concurrency(batch["concurrency"])
    batch.setdefault("tasks", tasks)
    missing_batch = [field for field in required_batch_fields() if field not in batch]
    if missing_batch:
        raise ValueError("ACN batch is missing required fields: " + ", ".join(missing_batch))
    missing_tasks: list[str] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, Mapping):
            raise ValueError(f"ACN task {index} must be an object")
        missing = [field for field in required_task_fields() if field not in task]
        if missing:
            missing_tasks.append(f"{index}: {', '.join(missing)}")
    if missing_tasks:
        raise ValueError("ACN tasks are missing required fields: " + "; ".join(missing_tasks))
    child_ids = [str(task["id"]) for task in tasks]
    if len(child_ids) != len(set(child_ids)):
        raise ValueError("ACN task ids must be unique")
    return {
        "phase": "dispatch",
        "batch": batch,
        "expected_child_ids": child_ids,
        "lane_batches": group_tasks_by_lane(tasks),
        "lane_index": 0,
    }


def dispatch_next(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    return {"phase": "dispatch", "lane_index": int(state.get("lane_index", 0)) + 1}


def execute(
    state: Mapping[str, Any],
    runtime: Runtime[BeastmodeContext],
    dependencies: PipelineDependencies,
) -> dict[str, Any]:
    task = state.get("task")
    task = task if isinstance(task, Mapping) else {}
    if dependencies.executor is None:
        _stream(runtime, {"event": "executor", "task_id": task.get("id"), "status": "not_configured", "stdout": "", "stderr": ""})
        return {"task_results": [{"id": task.get("id"), "status": "not_configured"}]}
    # Multiple Send branches write in one super-step.  Keep the complete
    # executor record under a reducer-backed list; a last-value field such as
    # phase or execution_status would make LangGraph reject the update.
    result = redact_value(dict(dependencies.executor(dict(state))))
    _stream(runtime, {
        "event": "executor",
        "task_id": task.get("id"),
        "status": result.get("execution_status"),
        "stdout": result.get("executor_stdout", ""),
        "stderr": result.get("executor_stderr", ""),
    })
    child_meta = result.pop("child_meta", [])
    trace_records = result.pop("trace_records", [])
    return {
        "task_results": [{"id": task.get("id"), **result}],
        "child_meta": list(child_meta),
        "trace_records": list(trace_records),
    }


def validate_mechanical(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    return {"phase": "validate_mechanical", "validation_report": {"passed": True}}


def review(
    state: Mapping[str, Any],
    runtime: Runtime[BeastmodeContext],
    dependencies: PipelineDependencies,
) -> dict[str, Any]:
    if dependencies.reviewer is None:
        return {"phase": "review", "review_report": {"approved": True}}
    return {"phase": "review", **dict(dependencies.reviewer(dict(state)))}


def merge(
    state: Mapping[str, Any],
    runtime: Runtime[BeastmodeContext],
    dependencies: PipelineDependencies,
) -> dict[str, Any]:
    if dependencies.merger is None:
        return {"phase": "merge", "status": "merged"}
    return {"phase": "merge", **dict(dependencies.merger(dict(state)))}


def self_improve(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    return {"phase": "self_improve", "self_improvement": "note-only"}


def blocked(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    return {"status": "blocked", "phase": "blocked"}


acceptance_contract = contract
mechanical_validation = validate_mechanical


def judgment_review(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    return review(state, runtime, PipelineDependencies())


def _stream(runtime: Runtime[BeastmodeContext], event: Mapping[str, Any]) -> None:
    try:
        runtime.stream_writer(dict(event))
    except Exception:
        pass
