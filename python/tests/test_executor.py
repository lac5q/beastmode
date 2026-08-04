from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from beastmode.core.executors import SubprocessExecutor, WorktreeSubprocessExecutor
from beastmode.core.provenance import check_provenance


ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "seed")
    return repo


def test_worktree_executor_isolates_changes_and_blocks_commit_push(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    command = (
        sys.executable,
        "-c",
        (
            "import json, os, pathlib, subprocess; "
            "pathlib.Path('child.txt').write_text('child\\n'); "
            "subprocess.run(['git','add','child.txt'], check=False); "
            "subprocess.run(['git','commit','-m','blocked'], check=False); "
            "subprocess.run(['git','push'], check=False); "
            "pathlib.Path(os.environ['BEASTMODE_META_DIR'], 'meta.json').write_text(json.dumps({"
            "'id':os.environ['BEASTMODE_TASK_ID'],"
            "'requested_model':os.environ['BEASTMODE_REQUESTED_MODEL'],"
            "'actual_model':os.environ['BEASTMODE_REQUESTED_MODEL'],"
            "'stop_reason':'end_turn','usage':{},'files_changed':['child.txt'],"
            "'commands_run':['git add'], 'verify':{'passed':True}}))"
        ),
    )
    result = WorktreeSubprocessExecutor(repo=repo, command=command)(
        {
            "run_dir": run_dir,
            "executor_model": "minimax/MiniMax-M3",
            "task": {"id": "child-a", "goal": "write a file"},
        }
    )
    assert result["execution_status"] == "ok"
    assert json.loads((run_dir / "child-a" / "meta.json").read_text())["id"] == "child-a"
    assert (run_dir / "executor-events.log").read_text().count("blocked_git") == 2
    assert subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""
    assert check_provenance(run_dir, repo=ROOT, expect=["child-a"]).exit_code == 0


def test_killed_child_without_meta_is_unverifiable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    result = WorktreeSubprocessExecutor(
        repo=repo,
        command=(sys.executable, "-c", "import time; time.sleep(1)"),
        timeout=0.01,
    )({"run_dir": run_dir, "task": {"id": "killed", "goal": "sleep"}})
    assert result["execution_status"] == "failed"
    assert check_provenance(run_dir, repo=ROOT, expect=["killed"]).verdict == "unverifiable"


def test_task_id_cannot_escape_run_or_worktree_root(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    executor = WorktreeSubprocessExecutor(
        repo=repo,
        command=(sys.executable, "-c", "print('should not run')"),
    )
    import pytest

    with pytest.raises(ValueError, match="task id"):
        executor({"run_dir": run_dir, "task": {"id": "../outside", "goal": "escape"}})
    assert not outside.exists()


def test_subprocess_executor_bounds_and_redacts_output(tmp_path: Path) -> None:
    token = "ghp_" + "a" * 24
    executor = SubprocessExecutor(
        command=(sys.executable, "-c", f"print({token!r}); print('x' * 20000)"),
    )
    result = executor({"worktree": tmp_path})
    assert result["execution_status"] == "ok"
    assert token not in result["executor_stdout"]
    assert len(result["executor_stdout"]) <= 16_384 + len("…[TRUNCATED]")
    assert result["executor_output_truncated"] is True
