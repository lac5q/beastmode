"""Small, replaceable nodes used by the initial pipeline graph."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from langgraph.runtime import Runtime

from beastmode.core.contract import AcceptanceContract
from beastmode.core.executors import SubprocessExecutor
from beastmode.core.observability import redact_text, redact_value
from beastmode.core.schema import concurrency_default, required_batch_fields, required_task_fields
from beastmode.core.seats import preflight_seat, resolve_alias

from .context import BeastmodeContext
from .gates import _is_approved
from .limits import MAX_TASKS, validate_concurrency, validate_executor_result, validate_tasks


NodeCallable = Callable[[dict[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class PipelineDependencies:
    """Optional integrations; defaults are deterministic and side-effect-free."""

    executor: NodeCallable | None = None
    validator: NodeCallable | None = None
    reviewer: NodeCallable | None = None
    merger: NodeCallable | None = None
    challenger: NodeCallable | None = None


def preflight(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    context = runtime.context
    trusted_run_dir = getattr(context, "run_dir", None)
    requested = state.get("requested_seats")
    requested = requested if isinstance(requested, Mapping) else {}
    batch_source = state.get("batch")
    batch_source = batch_source if isinstance(batch_source, Mapping) else {}
    batch = {
        field: batch_source[field]
        for field in required_batch_fields()
        if field in batch_source
    }
    batch.setdefault("autonomy", state.get("autonomy") or getattr(context, "autonomy", "medium"))
    batch.setdefault("director_model", state.get("director_model") or requested.get("frontier") or "unconfigured/director")
    batch.setdefault("executor_model", state.get("executor_model") or requested.get("economy") or "unconfigured/executor")
    batch.setdefault("watcher_model", state.get("watcher_model") or requested.get("watcher") or "unconfigured/watcher")
    if "concurrency" not in batch:
        batch["concurrency"] = state["concurrency"] if "concurrency" in state else concurrency_default()
    batch["concurrency"] = validate_concurrency(batch["concurrency"])
    repo = Path(str(state.get("repo") or Path.cwd()))
    try:
        git_status = SubprocessExecutor(
            command=(
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "diff.external=",
                "-c",
                "core.pager=cat",
                "-C",
                str(repo),
                "status",
                "--porcelain=v1",
            ),
            timeout=5.0,
            extra_env={
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_TERMINAL_PROMPT": "0",
            },
        )({"worktree": repo})
        status_lines = [line for line in str(git_status["executor_stdout"]).splitlines() if line]
        git_report = {
            "available": git_status["executor_returncode"] == 0,
            "dirty": bool(status_lines),
            "change_count": len(status_lines),
            "output_truncated": bool(git_status["executor_output_truncated"]),
        }
    except (OSError, ValueError) as exc:
        git_report = {"available": False, "dirty": None, "error": redact_text(exc)}
    seat_report: dict[str, str] = {}
    for seat_name, model in (
        ("director", batch["director_model"]),
        ("executor", batch["executor_model"]),
        ("watcher", batch["watcher_model"]),
    ):
        if str(model).startswith("unconfigured/"):
            seat_report[seat_name] = "not_requested"
            continue
        try:
            preflight_seat(resolve_alias(str(model), repo=repo), available_models=None)
            seat_report[seat_name] = "resolved"
        except Exception as exc:
            seat_report[seat_name] = f"unavailable: {redact_text(exc)}"
    return {
        "phase": "preflight",
        "goal_id": getattr(context, "goal_id", None) or state.get("goal_id"),
        "preflight_ok": bool(
            git_report["available"]
            and trusted_run_dir is not None
            and seat_report
            and all(value in {"resolved", "not_requested"} for value in seat_report.values())
        ),
        "autonomy": batch["autonomy"],
        "director_model": batch["director_model"],
        "executor_model": batch["executor_model"],
        "watcher_model": batch["watcher_model"],
        "concurrency": batch["concurrency"],
        "run_dir": str(Path(trusted_run_dir).resolve())
        if trusted_run_dir is not None
        else "",
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
    tasks = validate_tasks(tasks)
    return {"phase": "design", "tasks": tasks, "batch": {**dict(batch or {}), "tasks": tasks}}


def challenge(
    state: Mapping[str, Any],
    runtime: Runtime[BeastmodeContext],
    dependencies: PipelineDependencies,
) -> dict[str, Any]:
    """Run the optional cross-family design challenge before dispatch."""
    if dependencies.challenger is None:
        return {"phase": "challenge", "challenge_report": {"passed": True, "skipped": True}}
    update = redact_value(validate_executor_result(dependencies.challenger(dict(state))))
    return {"phase": "challenge", **update}


def dispatch(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    from .dispatch import group_tasks_by_lane

    tasks = validate_tasks(state.get("tasks", ()))
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
    trusted_run_dir = getattr(context, "run_dir", None)
    if trusted_run_dir is None:
        raise ValueError("pipeline dispatch requires a trusted runtime run_dir")
    return {
        "phase": "dispatch",
        "run_dir": str(Path(trusted_run_dir).resolve()),
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
    result = redact_value(validate_executor_result(dependencies.executor(dict(state))))
    _stream(runtime, {
        "event": "executor",
        "task_id": task.get("id"),
        "status": result.get("execution_status"),
        "stdout": result.get("executor_stdout", ""),
        "stderr": result.get("executor_stderr", ""),
    })
    child_meta = result.pop("child_meta", [])
    trace_records = result.pop("trace_records", [])
    if not isinstance(child_meta, list) or not isinstance(trace_records, list):
        raise ValueError("executor child_meta and trace_records must be lists")
    return {
        "task_results": [{**result, "id": task.get("id")}],
        "child_meta": list(child_meta),
        "trace_records": list(trace_records),
    }


def validate_mechanical(
    state: Mapping[str, Any],
    runtime: Runtime[BeastmodeContext],
    dependencies: PipelineDependencies | None = None,
) -> dict[str, Any]:
    expected = [str(task["id"]) for task in validate_tasks(state.get("tasks", ()))]
    results = list(state.get("task_results") or ())
    by_id: dict[str, Mapping[str, Any]] = {}
    retried: set[str] = set()
    failures: list[str] = []
    if len(results) > MAX_TASKS * 3:
        failures.append("executor result history exceeds the bounded retry allowance")
    for result in results:
        if not isinstance(result, Mapping):
            failures.append("executor returned a non-object result")
            continue
        result_id = str(result.get("id") or "")
        if result_id in by_id:
            retried.add(result_id)
        by_id[result_id] = result
    for task_id in expected:
        result = by_id.get(task_id)
        if result is None:
            failures.append(f"missing result for task {redact_text(task_id)}")
        elif result.get("execution_status") != "ok":
            failures.append(
                f"task {redact_text(task_id)} status is {redact_text(result.get('execution_status'))}"
            )
    unexpected = sorted(set(by_id).difference(expected))
    if unexpected:
        failures.append("unexpected task results: " + ", ".join(redact_text(item) for item in unexpected))
    trusted_report: dict[str, Any]
    if dependencies is None or dependencies.validator is None:
        trusted_report = {
            "passed": False,
            "failures": ["trusted mechanical validator is not configured"],
        }
    else:
        update = redact_value(validate_executor_result(dependencies.validator(dict(state))))
        supplied = update.get("validation_report")
        if not isinstance(supplied, Mapping):
            raise ValueError("trusted mechanical validator must return validation_report")
        trusted_report = dict(supplied)
        if trusted_report.get("passed") is not True:
            failures.append("trusted mechanical validation did not pass")
    if trusted_report.get("passed") is not True and not failures:
        failures.append("trusted mechanical validation did not pass")
    return {
        "phase": "validate_mechanical",
        "validation_report": {
            "passed": not failures,
            "expected": len(expected),
            "observed": len(results),
            "retried": sorted(redact_text(task_id) for task_id in retried),
            "failures": failures,
            "trusted": trusted_report,
        },
    }


def review(
    state: Mapping[str, Any],
    runtime: Runtime[BeastmodeContext],
    dependencies: PipelineDependencies,
) -> dict[str, Any]:
    if dependencies.reviewer is None:
        return {
            "phase": "review",
            "review_report": {
                "approved": False,
                "reason": "explicit trusted reviewer is not configured",
            },
        }
    update = redact_value(validate_executor_result(dependencies.reviewer(dict(state))))
    report = update.get("review_report")
    if not isinstance(report, Mapping) or report.get("approved") is not True:
        return {
            "phase": "review",
            "review_report": dict(report) if isinstance(report, Mapping) else {
                "approved": False,
                "reason": "trusted reviewer returned no review_report",
            },
        }
    return {"phase": "review", **update}


def merge(
    state: Mapping[str, Any],
    runtime: Runtime[BeastmodeContext],
) -> dict[str, Any]:
    """Mark a graph run ready; only the trusted runtime wrapper may merge."""
    validation = state.get("validation_report")
    review_report = state.get("review_report")
    merge_decision = state.get("merge_decision")
    if (
        state.get("preflight_ok") is not True
        or not isinstance(validation, Mapping)
        or validation.get("passed") is not True
        or state.get("provenance_verdict") != "ok"
        or not isinstance(review_report, Mapping)
        or review_report.get("approved") is not True
        or not _is_approved(merge_decision)
    ):
        raise PermissionError("merge requires successful preflight, validation, provenance, review, and gate approval")
    return {"phase": "merge", "status": "ready_to_merge"}


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
        runtime.stream_writer(redact_value(dict(event)))
    except Exception:
        pass
