from __future__ import annotations

from pathlib import Path
import asyncio
import os
import stat

import pytest
from langgraph.types import Command

from beastmode.langgraph.context import BeastmodeContext
from beastmode.langgraph.graphs.pipeline import build_pipeline
from beastmode.langgraph.runtime import (
    arun_pipeline,
    checkpoint_history,
    durability_for,
    replay_from_checkpoint,
    run_pipeline,
    sqlite_checkpointer,
)
from beastmode.langgraph.nodes import PipelineDependencies


ROOT = Path(__file__).resolve().parents[2]
MATCH_RUN = ROOT / "tests" / "fixtures" / "acn-meta" / "match"


def _ok_executor(state):
    return {"execution_status": "ok"}


OK_DEPENDENCIES = PipelineDependencies(executor=_ok_executor)


def test_durability_policy_is_gate_aware() -> None:
    assert durability_for("medium") == "sync"
    assert durability_for("low") == "sync"
    assert durability_for("high") == "exit"


def test_sqlite_checkpoint_survives_reopen_and_resumes(tmp_path: Path) -> None:
    database = tmp_path / "run.sqlite"
    config = {"configurable": {"thread_id": "restartable-goal"}}
    initial = {
        "goal": "restartable",
        "run_dir": str(MATCH_RUN),
        "tasks": [{"id": "a", "goal": "restartable", "allowed_paths": [], "verify_cmds": []}],
    }
    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=saver)
        paused = graph.invoke(
            initial,
            config=config,
            context=BeastmodeContext(autonomy="medium", run_dir=MATCH_RUN),
        )
        assert "__interrupt__" in paused

    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=saver)
        paused_again = graph.invoke(
            Command(resume="approved"),
            config=config,
            context=BeastmodeContext(autonomy="medium", run_dir=MATCH_RUN),
        )
        assert "__interrupt__" in paused_again
        completed = graph.invoke(
            Command(resume="approved"),
            config=config,
            context=BeastmodeContext(autonomy="medium", run_dir=MATCH_RUN),
        )
    assert completed["status"] == "merged"


def test_sqlite_checkpoint_storage_is_private(tmp_path: Path) -> None:
    database = tmp_path / "private" / "run.sqlite"
    with sqlite_checkpointer(database):
        pass
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700


def test_async_runtime_uses_async_sqlite_saver(tmp_path: Path) -> None:
    result = asyncio.run(
        arun_pipeline(
            {
                "goal": "async-goal",
                "run_dir": str(MATCH_RUN),
                "tasks": [{"id": "a", "goal": "async-goal", "allowed_paths": [], "verify_cmds": []}],
            },
            goal_id="async-goal",
            autonomy="high",
            database=tmp_path / "async.sqlite",
            run_dir=MATCH_RUN,
            dependencies=OK_DEPENDENCIES,
        )
    )
    assert result["status"] == "merged"


def test_checkpoint_history_can_replay_a_selected_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "history.sqlite"
    config = {"configurable": {"thread_id": "history-goal"}}
    initial = {
        "goal": "history",
        "run_dir": str(MATCH_RUN),
        "tasks": [{"id": "a", "goal": "history", "allowed_paths": [], "verify_cmds": []}],
    }
    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=saver)
        paused = graph.invoke(
            initial,
            config=config,
            context=BeastmodeContext(autonomy="medium", run_dir=MATCH_RUN),
        )
        assert "__interrupt__" in paused
    history = checkpoint_history(database=database, goal_id="history-goal")
    checkpoint = next(
        snapshot.config["configurable"]["checkpoint_id"]
        for snapshot in history
        if snapshot.values.get("phase") == "validate_mechanical"
    )
    replayed = replay_from_checkpoint(
        database=database,
        goal_id="history-goal",
        checkpoint_id=checkpoint,
        autonomy="medium",
        run_dir=MATCH_RUN,
        dependencies=OK_DEPENDENCIES,
    )
    assert "__interrupt__" in replayed


def test_checkpoint_replay_can_fork_a_new_goal_thread(tmp_path: Path) -> None:
    database = tmp_path / "fork.sqlite"
    config = {"configurable": {"thread_id": "original-goal"}}
    initial = {
        "goal": "original",
        "run_dir": str(MATCH_RUN),
        "tasks": [{"id": "a", "goal": "original", "allowed_paths": [], "verify_cmds": []}],
    }
    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=OK_DEPENDENCIES, checkpointer=saver)
        graph.invoke(initial, config=config, context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN))
    history = checkpoint_history(database=database, goal_id="original-goal")
    checkpoint = next(
        snapshot.config["configurable"]["checkpoint_id"]
        for snapshot in history
        if snapshot.values.get("phase") == "design"
    )
    forked = replay_from_checkpoint(
        database=database,
        goal_id="original-goal",
        new_goal_id="forked-goal",
        checkpoint_id=checkpoint,
        autonomy="high",
        run_dir=MATCH_RUN,
        dependencies=OK_DEPENDENCIES,
    )
    assert forked["status"] == "merged"
    assert checkpoint_history(database=database, goal_id="original-goal")
    assert checkpoint_history(database=database, goal_id="forked-goal")


def test_initial_command_cannot_jump_to_merge(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="goto"):
        run_pipeline(
            Command(goto="merge"),
            goal_id="goto-blocked",
            autonomy="high",
            database=tmp_path / "goto.sqlite",
            run_dir=MATCH_RUN,
            dependencies=OK_DEPENDENCIES,
        )
    assert not (tmp_path / "goto.sqlite").exists()


def test_sqlite_rejects_symlinked_parent(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(private, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        with sqlite_checkpointer(alias / "run.sqlite"):
            pass


def test_sqlite_rejects_shared_checkpoint_directory(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)
    with pytest.raises(PermissionError, match="owner-only"):
        with sqlite_checkpointer(shared / "run.sqlite"):
            pass


def test_sqlite_rejects_hard_linked_checkpoint_file(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    original = private / "original.sqlite"
    original.touch(mode=0o600)
    linked = private / "linked.sqlite"
    os.link(original, linked)
    with pytest.raises(ValueError, match="hard links"):
        with sqlite_checkpointer(linked):
            pass
