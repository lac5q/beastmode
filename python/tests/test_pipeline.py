from __future__ import annotations

from pathlib import Path
import json
import threading
import time

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from beastmode.langgraph.context import BeastmodeContext
from beastmode.langgraph.graphs.pipeline import build_pipeline
from beastmode.langgraph.nodes import PipelineDependencies


ROOT = Path(__file__).resolve().parents[2]
MATCH_RUN = ROOT / "tests" / "fixtures" / "acn-meta" / "match"


def _config() -> dict:
    return {"configurable": {"thread_id": "pipeline-test"}}


def test_medium_pipeline_resumes_through_both_gates() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    context = BeastmodeContext(autonomy="medium", run_dir=MATCH_RUN)
    first = graph.invoke(
        {
            "goal": "test",
            "run_dir": str(MATCH_RUN),
            "tasks": [{"id": "a", "goal": "test", "allowed_paths": [], "verify_cmds": []}],
        },
        config=_config(),
        context=context,
    )
    assert "__interrupt__" in first
    resumed = graph.invoke(Command(resume="approved"), config=_config(), context=context)
    assert "__interrupt__" in resumed
    completed = graph.invoke(Command(resume="approved"), config=_config(), context=context)
    assert completed["status"] == "merged"
    assert completed["provenance_verdict"] == "ok"


def test_gate_rejects_unapproved_resume_value() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "rejected-resume"}}
    context = BeastmodeContext(autonomy="medium", run_dir=MATCH_RUN)
    paused = graph.invoke(
        {
            "goal": "reject",
            "run_dir": str(MATCH_RUN),
            "tasks": [{"id": "a", "goal": "reject", "allowed_paths": [], "verify_cmds": []}],
        },
        config=config,
        context=context,
    )
    assert "__interrupt__" in paused
    with pytest.raises(PermissionError, match="requires an explicit approved decision"):
        graph.invoke(Command(resume="rejected"), config=config, context=context)


def test_pipeline_rejects_excessive_concurrency() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    with pytest.raises(ValueError, match="cannot exceed"):
        graph.invoke(
            {
                "goal": "bounded",
                "concurrency": 33,
                "tasks": [{"id": "a", "goal": "bounded", "allowed_paths": [], "verify_cmds": []}],
            },
            config={"configurable": {"thread_id": "bounded-concurrency"}},
            context=BeastmodeContext(autonomy="high"),
        )


def test_high_pipeline_does_not_interrupt() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    result = graph.invoke(
        {
            "goal": "test",
            "run_dir": str(MATCH_RUN),
            "tasks": [{"id": "a", "goal": "test", "allowed_paths": [], "verify_cmds": []}],
        },
        config=_config(),
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert "__interrupt__" not in result
    assert result["status"] == "merged"


def test_low_pipeline_stops_at_every_phase_boundary() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    context = BeastmodeContext(autonomy="low", run_dir=MATCH_RUN)
    config = {"configurable": {"thread_id": "low-pipeline"}}
    result = graph.invoke(
        {
            "goal": "test",
            "run_dir": str(MATCH_RUN),
            "tasks": [{"id": "a", "goal": "test", "allowed_paths": [], "verify_cmds": []}],
        },
        config=config,
        context=context,
    )
    interruptions = 0
    while "__interrupt__" in result:
        interruptions += 1
        result = graph.invoke(Command(resume="approved"), config=config, context=context)
    assert interruptions >= 8
    assert result["status"] == "merged"


def test_dispatch_rejects_missing_schema_task_field() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    with pytest.raises(ValueError, match="missing required fields"):
        graph.invoke(
            {
                "goal": "invalid",
                "run_dir": str(MATCH_RUN),
                "tasks": [{"id": "a", "allowed_paths": [], "verify_cmds": []}],
            },
            config={"configurable": {"thread_id": "invalid-task"}},
            context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
        )


def test_dispatch_rejects_duplicate_task_ids() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    with pytest.raises(ValueError, match="unique"):
        graph.invoke(
            {
                "goal": "duplicate",
                "tasks": [
                    {"id": "same", "goal": "a", "allowed_paths": [], "verify_cmds": []},
                    {"id": "same", "goal": "b", "allowed_paths": [], "verify_cmds": []},
                ],
            },
            config={"configurable": {"thread_id": "duplicate-task"}},
            context=BeastmodeContext(autonomy="high"),
        )


def test_gate_nodes_are_not_overrideable() -> None:
    with pytest.raises(ValueError, match="load-bearing gate"):
        build_pipeline(overrides={"gate_provenance": lambda state, runtime: {}})


def test_non_gate_override_replaces_the_default_node() -> None:
    def custom_review(state, runtime):
        return {"phase": "review", "review_report": {"source": "custom"}}

    graph = build_pipeline(
        overrides={"review": custom_review},
        checkpointer=InMemorySaver(),
    )
    result = graph.invoke(
        {
            "goal": "override",
            "run_dir": str(MATCH_RUN),
            "tasks": [{"id": "a", "goal": "override", "allowed_paths": [], "verify_cmds": []}],
        },
        config={"configurable": {"thread_id": "override-test"}},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert result["review_report"] == {"source": "custom"}


def test_three_children_fan_out_and_rejoin_by_lane(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    active = 0
    peak = 0
    lock = threading.Lock()

    def executor(state):
        nonlocal active, peak
        task = state["task"]
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.08)
        child_dir = run_dir / str(task["id"])
        child_dir.mkdir(parents=True)
        (child_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": task["id"],
                    "requested_model": "minimax/MiniMax-M3",
                    "actual_model": "minimax/MiniMax-M3",
                    "stop_reason": "end_turn",
                    "usage": {},
                    "files_changed": [],
                    "commands_run": [],
                    "verify": {},
                }
            ),
            encoding="utf-8",
        )
        with lock:
            active -= 1
        return {"execution_status": "ok"}

    graph = build_pipeline(
        dependencies=PipelineDependencies(executor=executor),
        checkpointer=InMemorySaver(),
    )
    tasks = [
        {"id": "a", "lane": "economy", "goal": "a", "allowed_paths": [], "verify_cmds": []},
        {"id": "b", "lane": "economy", "goal": "b", "allowed_paths": [], "verify_cmds": []},
        {"id": "c", "lane": "economy", "goal": "c", "allowed_paths": [], "verify_cmds": []},
    ]
    result = graph.invoke(
        {"goal": "fanout", "run_dir": str(run_dir), "tasks": tasks},
        config={"configurable": {"thread_id": "fanout-test"}, "max_concurrency": 3},
        context=BeastmodeContext(autonomy="high", run_dir=run_dir),
    )
    assert result["status"] == "merged"
    assert peak >= 2


def test_custom_stream_contains_phase_and_executor_progress() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    events = list(
        graph.stream(
            {
                "goal": "stream",
                "run_dir": str(MATCH_RUN),
                "tasks": [{"id": "a", "goal": "stream", "allowed_paths": [], "verify_cmds": []}],
            },
            config={"configurable": {"thread_id": "stream-test"}},
            context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
            stream_mode="custom",
        )
    )
    assert any(event.get("event") == "phase" for event in events)
    assert any(event.get("event") == "executor" for event in events)
