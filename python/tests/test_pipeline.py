from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace
import threading
import time

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import InvalidUpdateError
from langgraph.types import Command

from beastmode.langgraph.context import BeastmodeContext
from beastmode.langgraph.graphs.pipeline import build_pipeline
import beastmode.langgraph.gates as gates_module
from beastmode.langgraph.gates import _autonomy, gate_provenance
from beastmode.core.provenance import check_provenance as canonical_check_provenance
from beastmode.langgraph.nodes import PipelineDependencies, preflight, validate_mechanical


ROOT = Path(__file__).resolve().parents[2]
MATCH_RUN = ROOT / "tests" / "fixtures" / "acn-meta" / "match"
ATTESTATIONS = ROOT / "tests" / "fixtures" / "acn-attestations.json"


def _ok_executor(state):
    return {"execution_status": "ok"}


def _ok_validator(state):
    return {"validation_report": {"passed": True, "source": "trusted-test-validator"}}


def _ok_reviewer(state):
    return {"review_report": {"approved": True, "source": "trusted-test-reviewer"}}


OK_DEPENDENCIES = PipelineDependencies(
    executor=_ok_executor,
    validator=_ok_validator,
    reviewer=_ok_reviewer,
)


def _config() -> dict:
    return {"configurable": {"thread_id": "pipeline-test"}}


@pytest.fixture(autouse=True)
def _trusted_provenance_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep pipeline-control tests independent of provider attestation fixtures."""
    monkeypatch.setattr(
        gates_module,
        "check_provenance",
        lambda target, expect, attestations=None: SimpleNamespace(
            verdict="ok", messages=(), exit_code=0
        ),
    )


def test_medium_pipeline_resumes_through_both_gates() -> None:
    graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=InMemorySaver())
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
    assert completed["status"] == "ready_to_merge"
    assert completed["provenance_verdict"] == "ok"


def test_gate_rejects_unapproved_resume_value() -> None:
    graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=InMemorySaver())
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
    graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=InMemorySaver())
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
    graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=InMemorySaver())
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
    assert result["status"] == "ready_to_merge"


def test_low_pipeline_stops_at_every_phase_boundary() -> None:
    graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=InMemorySaver())
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
    assert result["status"] == "ready_to_merge"


def test_dispatch_rejects_missing_schema_task_field() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    with pytest.raises(ValueError, match="task 0 goal"):
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
            context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
        )


def test_preflight_disables_repository_executable_git_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    marker = tmp_path / "fsmonitor-ran"
    monitor = tmp_path / "monitor.sh"
    monitor.write_text(
        f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8"
    )
    monitor.chmod(0o755)
    subprocess.run(
        ["git", "config", "core.fsmonitor", str(monitor)], cwd=repo, check=True
    )
    report = preflight(
        {"repo": str(repo)},
        SimpleNamespace(
            context=BeastmodeContext(autonomy="high", run_dir=tmp_path / "run")
        ),
    )
    assert report["preflight_ok"] is True
    assert not marker.exists()


def test_mechanical_validation_uses_latest_bounded_retry_result() -> None:
    update = validate_mechanical(
        {
            "tasks": [{"id": "a", "goal": "retry", "allowed_paths": [], "verify_cmds": []}],
            "task_results": [
                {"id": "a", "execution_status": "failed"},
                {"id": "a", "execution_status": "ok"},
            ],
        },
        SimpleNamespace(),
        OK_DEPENDENCIES,
    )
    assert update["validation_report"]["passed"] is True
    assert update["validation_report"]["retried"] == ["a"]


def test_gate_nodes_are_not_overrideable() -> None:
    with pytest.raises(ValueError, match="load-bearing control"):
        build_pipeline(overrides={"gate_provenance": lambda state, runtime: {}})
    with pytest.raises(ValueError, match="load-bearing control"):
        build_pipeline(overrides={"validate_mechanical": lambda state, runtime: {"validation_report": {"passed": True}}})
    with pytest.raises(ValueError, match="load-bearing control"):
        build_pipeline(overrides={"review": lambda state, runtime: {"review_report": {"approved": True}}})
    with pytest.raises(ValueError, match="load-bearing control"):
        build_pipeline(overrides={"merge": lambda state, runtime: {"status": "merged"}})


def test_non_gate_override_replaces_the_default_node() -> None:
    def custom_challenge(state, runtime):
        return {"phase": "challenge", "challenge_report": {"source": "custom"}}

    graph = build_pipeline(
        dependencies=OK_DEPENDENCIES,
        overrides={"challenge": custom_challenge},
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
    assert result["challenge_report"] == {"source": "custom"}
    assert result["status"] == "ready_to_merge"


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
        dependencies=PipelineDependencies(
            executor=executor,
            validator=_ok_validator,
            reviewer=_ok_reviewer,
        ),
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
    assert result["status"] == "ready_to_merge"
    assert peak >= 2


def test_custom_stream_contains_phase_and_executor_progress() -> None:
    graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=InMemorySaver())
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


def test_default_executor_fails_closed() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    result = graph.invoke(
        {
            "goal": "no executor",
            "tasks": [{"id": "a", "goal": "no executor", "allowed_paths": [], "verify_cmds": []}],
        },
        config={"configurable": {"thread_id": "no-executor"}},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert result["status"] == "blocked"
    assert result["validation_report"]["passed"] is False


def test_preflight_failure_routes_directly_to_blocked(tmp_path: Path) -> None:
    graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=InMemorySaver())
    result = graph.invoke(
        {
            "goal": "bad repo",
            "repo": str(tmp_path / "missing"),
            "tasks": [{"id": "a", "goal": "bad repo", "allowed_paths": [], "verify_cmds": []}],
        },
        config={"configurable": {"thread_id": "bad-repo"}},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert result["preflight_ok"] is False
    assert result["status"] == "blocked"


def test_reviewer_rejection_blocks_merge() -> None:
    dependencies = PipelineDependencies(
        executor=_ok_executor,
        validator=_ok_validator,
        reviewer=lambda state: {"review_report": {"approved": False}},
    )
    graph = build_pipeline(dependencies=dependencies, checkpointer=InMemorySaver())
    result = graph.invoke(
        {
            "goal": "reject review",
            "tasks": [{"id": "a", "goal": "reject review", "allowed_paths": [], "verify_cmds": []}],
        },
        config={"configurable": {"thread_id": "review-reject"}},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert result["review_report"]["approved"] is False
    assert result["status"] == "blocked"


def test_task_count_is_bounded() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    tasks = [
        {"id": f"t-{index}", "goal": "bounded", "allowed_paths": [], "verify_cmds": []}
        for index in range(129)
    ]
    with pytest.raises(ValueError, match="task count"):
        graph.invoke(
            {"goal": "bounded", "tasks": tasks},
            config={"configurable": {"thread_id": "task-bound"}},
            context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
        )


def test_state_cannot_raise_autonomy_without_runtime_context() -> None:
    runtime = SimpleNamespace(context=SimpleNamespace())
    assert _autonomy(runtime, {"autonomy": "high"}) == "medium"


def test_executor_stream_redacts_caller_controlled_values() -> None:
    token = "ghp_" + "q" * 24
    dependencies = PipelineDependencies(
        executor=lambda state: {"execution_status": "ok", "executor_stdout": token},
        validator=_ok_validator,
        reviewer=_ok_reviewer,
    )
    graph = build_pipeline(dependencies=dependencies, checkpointer=InMemorySaver())
    events = list(
        graph.stream(
            {
                "goal": "redact stream",
                "tasks": [{"id": "a", "goal": "redact stream", "allowed_paths": [], "verify_cmds": []}],
            },
            config={"configurable": {"thread_id": "stream-redaction"}},
            context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
            stream_mode="custom",
        )
    )
    assert token not in json.dumps(events)


def test_provenance_uses_context_run_dir_not_state_value(tmp_path: Path) -> None:
    graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=InMemorySaver())
    result = graph.invoke(
        {
            "goal": "bound provenance",
            "run_dir": str(tmp_path / "caller-selected"),
            "expected_child_ids": [],
            "tasks": [{"id": "a", "goal": "bound provenance", "allowed_paths": [], "verify_cmds": []}],
        },
        config={"configurable": {"thread_id": "bound-provenance"}},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert result["provenance_verdict"] == "ok"
    assert result["status"] == "ready_to_merge"


def test_direct_graph_command_cannot_jump_to_merge() -> None:
    graph = build_pipeline(checkpointer=InMemorySaver())
    with pytest.raises(PermissionError, match="merge requires"):
        graph.invoke(
            Command(goto="merge"),
            config={"configurable": {"thread_id": "direct-goto-merge"}},
            context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
        )


def test_missing_trusted_validator_blocks_before_provenance() -> None:
    graph = build_pipeline(
        dependencies=PipelineDependencies(executor=_ok_executor, reviewer=_ok_reviewer),
        checkpointer=InMemorySaver(),
    )
    result = graph.invoke(
        {
            "goal": "validate explicitly",
            "tasks": [{"id": "a", "goal": "validate", "allowed_paths": [], "verify_cmds": []}],
        },
        config={"configurable": {"thread_id": "missing-validator"}},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert result["status"] == "blocked"
    assert result["validation_report"]["trusted"]["passed"] is False


def test_missing_reviewer_does_not_auto_approve() -> None:
    graph = build_pipeline(
        dependencies=PipelineDependencies(executor=_ok_executor, validator=_ok_validator),
        checkpointer=InMemorySaver(),
    )
    result = graph.invoke(
        {
            "goal": "review explicitly",
            "tasks": [{"id": "a", "goal": "review", "allowed_paths": [], "verify_cmds": []}],
        },
        config={"configurable": {"thread_id": "missing-reviewer"}},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert result["status"] == "blocked"
    assert result["review_report"]["approved"] is False


def test_dispatch_replaces_state_run_dir_with_trusted_context(tmp_path: Path) -> None:
    observed: list[str] = []

    def executor(state):
        observed.append(state["run_dir"])
        return {"execution_status": "ok"}

    def challenger(state):
        observed.append(state["run_dir"])
        return {"challenge_report": {"passed": True}}

    graph = build_pipeline(
        dependencies=PipelineDependencies(
            executor=executor,
            validator=_ok_validator,
            reviewer=_ok_reviewer,
            challenger=challenger,
        ),
        checkpointer=InMemorySaver(),
    )
    graph.invoke(
        {
            "goal": "bind run directory",
            "run_dir": str(tmp_path / "attacker-selected"),
            "tasks": [{"id": "a", "goal": "bind", "allowed_paths": [], "verify_cmds": []}],
        },
        config={"configurable": {"thread_id": "trusted-run-dir"}},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert observed == [str(MATCH_RUN.resolve()), str(MATCH_RUN.resolve())]


def test_direct_graph_never_invokes_merger_side_effect() -> None:
    calls: list[str] = []
    dependencies = PipelineDependencies(
        executor=_ok_executor,
        validator=_ok_validator,
        reviewer=_ok_reviewer,
        merger=lambda state: calls.append("merged") or {},
    )
    graph = build_pipeline(dependencies=dependencies, checkpointer=InMemorySaver())
    result = graph.invoke(
        {
            "goal": "no direct side effect",
            "tasks": [{"id": "a", "goal": "no merge", "allowed_paths": [], "verify_cmds": []}],
        },
        config={"configurable": {"thread_id": "no-direct-merger"}},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert result["status"] == "ready_to_merge"
    assert calls == []

    with pytest.raises(InvalidUpdateError):
        graph.invoke(
            Command(
                goto="merge",
                update={
                    "preflight_ok": True,
                    "validation_report": {"passed": True},
                    "provenance_verdict": "ok",
                    "review_report": {"approved": True},
                    "merge_decision": "approved",
                },
            ),
            config={"configurable": {"thread_id": "forged-direct-merger"}},
            context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
        )
    assert calls == []


def test_provenance_uses_only_external_context_attestations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gates_module, "check_provenance", canonical_check_provenance
    )
    state = {
        "phase": "validate_mechanical",
        "preflight_ok": True,
        "validation_report": {"passed": True},
        "attestations": str(ATTESTATIONS),
        "tasks": [
            {"id": "a", "goal": "attest", "allowed_paths": [], "verify_cmds": []}
        ],
    }

    missing = gate_provenance(
        state,
        SimpleNamespace(
            context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN)
        ),
    )
    assert missing["provenance_verdict"] == "unverifiable"

    in_tree = gate_provenance(
        state,
        SimpleNamespace(
            context=BeastmodeContext(
                autonomy="high",
                run_dir=MATCH_RUN,
                attestations=MATCH_RUN / "a.json",
            )
        ),
    )
    assert in_tree["provenance_verdict"] == "unverifiable"

    valid = gate_provenance(
        state,
        SimpleNamespace(
            context=BeastmodeContext(
                autonomy="high",
                run_dir=MATCH_RUN,
                attestations=ATTESTATIONS,
            )
        ),
    )
    assert valid["provenance_verdict"] == "ok"
