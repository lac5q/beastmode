from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

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
    real_git = subprocess.run(
        ["sh", "-c", "command -v git"], check=True, capture_output=True, text=True
    ).stdout.strip()
    command = (
        sys.executable,
        "-c",
        (
            "import json, os, pathlib, subprocess; "
            "pathlib.Path('child.txt').write_text('child\\n'); "
            "subprocess.run(['git','add','child.txt'], check=False); "
            "subprocess.run(['git','commit','-m','blocked'], check=False); "
            "subprocess.run(['git','push'], check=False); "
            f"print('absolute_git_rc', subprocess.run([{real_git!r},'config','worker.bypass','yes'], check=False).returncode); "
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
    assert "absolute_git_rc 0" not in result["executor_stdout"]
    assert subprocess.run(
        ["git", "-C", str(repo), "config", "--get", "worker.bypass"],
        check=False,
        capture_output=True,
        text=True,
    ).returncode != 0
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


def test_subprocess_executor_redacts_generic_explicit_env_secret(tmp_path: Path) -> None:
    secret = "ordinary-value-with-no-token-prefix"
    executor = SubprocessExecutor(
        command=(sys.executable, "-c", "import os; print(os.environ['SERVICE_PASSWORD'])"),
        extra_env={"SERVICE_PASSWORD": secret},
    )
    result = executor({"worktree": tmp_path})
    assert secret not in result["executor_stdout"]
    assert "[REDACTED]" in result["executor_stdout"]


def test_subprocess_executor_ignores_caller_path_override(tmp_path: Path) -> None:
    executor = SubprocessExecutor(
        command=(sys.executable, "-c", "import os; print(os.environ['PATH'])"),
        extra_env={"PATH": "/attacker/bin"},
    )
    result = executor({"worktree": tmp_path})
    assert "/attacker/bin" not in result["executor_stdout"]


@pytest.mark.skipif(os.name != "posix", reason="process-group semantics are POSIX-specific")
def test_timeout_kills_descendant_processes(tmp_path: Path) -> None:
    marker = tmp_path / "descendant-survived"
    child = (
        "import pathlib,time; time.sleep(.25); "
        f"pathlib.Path({str(marker)!r}).write_text('bad')"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(5)"
    )
    result = SubprocessExecutor(
        command=(sys.executable, "-c", parent),
        timeout=0.05,
    )({"worktree": tmp_path})
    assert result["executor_returncode"] == 124
    time.sleep(0.35)
    assert not marker.exists()
