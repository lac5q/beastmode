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
    result = WorktreeSubprocessExecutor(repo=repo, command=command, allow_network=True)(
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
    assert check_provenance(run_dir, repo=ROOT, expect=["child-a"]).verdict == "unverifiable"


def test_parent_attestor_writes_external_evidence_after_child_exit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    child_dir = run_dir / "attested"
    expected_attestation = tmp_path / ".run.attestations" / "attested.json"
    command = (
        sys.executable,
        "-c",
        (
            "import json,os,pathlib; root=pathlib.Path(os.environ['BEASTMODE_META_DIR']); "
            "root.joinpath('finished').write_text('yes'); "
            f"external=pathlib.Path({str(expected_attestation)!r}); "
            "print('forged' if external.parent.exists() else 'attestation-hidden'); "
            "root.joinpath('meta.json').write_text(json.dumps({"
            "'id':os.environ['BEASTMODE_TASK_ID'],"
            "'requested_model':os.environ['BEASTMODE_REQUESTED_MODEL'],"
            "'actual_model':os.environ['BEASTMODE_REQUESTED_MODEL'],"
            "'stop_reason':'end_turn','usage':{},'files_changed':[],"
            "'commands_run':[],'verify':{'passed':True}}))"
        ),
    )
    observed = []

    def attest(request: dict[str, object]) -> dict[str, object]:
        observed.append(dict(request))
        assert (child_dir / "finished").read_text() == "yes"
        return {
            "id": request["id"],
            "requested_model": request["requested_model"],
            "actual_model": "minimax/MiniMax-M3",
            "source": "trusted-provider-journal",
        }

    executor = WorktreeSubprocessExecutor(
        repo=repo,
        command=command,
        allow_network=True,
        model_attestor=attest,
    )
    assert executor.attestation_directory_for(run_dir) == expected_attestation.parent
    result = executor(
        {
            "run_dir": run_dir,
            "executor_model": "minimax/MiniMax-M3",
            "task": {"id": "attested", "goal": "prove model"},
        }
    )
    attestation_path = Path(result["model_attestation_path"])
    assert observed and observed[0]["id"] == "attested"
    assert result["execution_status"] == "ok"
    assert result["model_attestation_status"] == "ok"
    assert result["executor_stdout"].strip() == "attestation-hidden"
    assert attestation_path == expected_attestation
    assert not attestation_path.is_relative_to(run_dir)
    assert json.loads(attestation_path.read_text()) == {
        "id": "attested",
        "requested_model": "minimax/MiniMax-M3",
        "actual_model": "minimax/MiniMax-M3",
        "source": "trusted-provider-journal",
    }
    assert check_provenance(
        run_dir,
        repo=ROOT,
        expect=["attested"],
        attestations=attestation_path,
    ).verdict == "ok"
    assert result["trace_records"][0]["status"]["code"] == "ok"


def test_parent_attestation_does_not_trust_worker_actual_model(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    command = (
        sys.executable,
        "-c",
        (
            "import json,os,pathlib; "
            "pathlib.Path(os.environ['BEASTMODE_META_DIR'],'meta.json').write_text(json.dumps({"
            "'id':os.environ['BEASTMODE_TASK_ID'],"
            "'requested_model':os.environ['BEASTMODE_REQUESTED_MODEL'],"
            "'actual_model':'attacker/forged-model','stop_reason':'end_turn',"
            "'usage':{},'files_changed':[],'commands_run':[],"
            "'verify':{'passed':True}}))"
        ),
    )

    def attest(request: dict[str, object]) -> dict[str, object]:
        return {
            "id": request["id"],
            "requested_model": request["requested_model"],
            "actual_model": "minimax/MiniMax-M3",
            "source": "trusted-provider-journal",
        }

    result = WorktreeSubprocessExecutor(
        repo=repo,
        command=command,
        allow_network=True,
        model_attestor=attest,
    )(
        {
            "run_dir": run_dir,
            "executor_model": "minimax/MiniMax-M3",
            "task": {"id": "forged", "goal": "forge actual model"},
        }
    )
    assert result["model_attestation_status"] == "ok"
    assert result["trace_records"][0]["status"]["code"] == "error"
    assert check_provenance(
        run_dir,
        repo=ROOT,
        expect=["forged"],
        attestations=Path(result["model_attestation_path"]),
    ).verdict == "unverifiable"


def test_malformed_parent_attestation_fails_execution_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"

    def wrong_child(request: dict[str, object]) -> dict[str, object]:
        return {
            "id": "different-child",
            "requested_model": request["requested_model"],
            "actual_model": "minimax/MiniMax-M3",
            "source": "trusted-provider-journal",
        }

    result = WorktreeSubprocessExecutor(
        repo=repo,
        command=(sys.executable, "-c", "print('worker succeeded')"),
        allow_network=True,
        model_attestor=wrong_child,
    )({"run_dir": run_dir, "task": {"id": "expected-child", "goal": "bind evidence"}})
    assert result["execution_status"] == "failed"
    assert result["model_attestation_status"] == "failed"
    assert result["model_attestation_path"] is None
    assert "expected child id" in result["model_attestation_error"]


def test_killed_child_without_meta_is_unverifiable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    result = WorktreeSubprocessExecutor(
        repo=repo,
        command=(sys.executable, "-c", "import time; time.sleep(1)"),
        timeout=0.01,
        allow_network=True,
    )({"run_dir": run_dir, "task": {"id": "killed", "goal": "sleep"}})
    assert result["execution_status"] == "failed"
    assert check_provenance(run_dir, repo=ROOT, expect=["killed"]).verdict == "unverifiable"


def test_worktree_executor_removes_stale_metadata_before_launch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    stale_dir = run_dir / "same-child"
    stale_attestation = tmp_path / ".run.attestations" / "same-child.json"
    stale_attestation.parent.mkdir()
    stale_attestation.write_text(
        json.dumps(
            {
                "id": "same-child",
                "requested_model": "minimax/MiniMax-M3",
                "actual_model": "minimax/MiniMax-M3",
                "source": "stale-parent-record",
            }
        ),
        encoding="utf-8",
    )
    stale_dir.mkdir(parents=True)
    (stale_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "same-child",
                "requested_model": "minimax/MiniMax-M3",
                "actual_model": "minimax/MiniMax-M3",
                "stop_reason": "end_turn",
                "usage": {},
                "files_changed": [],
                "commands_run": [],
                "verify": {"passed": True},
            }
        ),
        encoding="utf-8",
    )
    result = WorktreeSubprocessExecutor(
        repo=repo,
        command=(sys.executable, "-c", "print('no fresh metadata')"),
        allow_network=True,
    )({"run_dir": run_dir, "task": {"id": "same-child", "goal": "retry"}})
    assert result["execution_status"] == "ok"
    assert not (stale_dir / "meta.json").exists()
    assert not stale_attestation.exists()
    assert result["trace_records"] == []
    assert check_provenance(run_dir, repo=ROOT, expect=["same-child"]).verdict == "unverifiable"


def test_worktree_executor_rejects_malformed_metadata_without_crashing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    command = (
        sys.executable,
        "-c",
        (
            "import json,os,pathlib; "
            "pathlib.Path(os.environ['BEASTMODE_META_DIR'],'meta.json').write_text("
            "json.dumps({'id':os.environ['BEASTMODE_TASK_ID'],"
            "'requested_model':os.environ['BEASTMODE_REQUESTED_MODEL'],"
            "'actual_model':os.environ['BEASTMODE_REQUESTED_MODEL'],"
            "'stop_reason':'end_turn','usage':'bad','files_changed':[],"
            "'commands_run':[],'verify':{'passed':True}}))"
        ),
    )
    result = WorktreeSubprocessExecutor(repo=repo, command=command, allow_network=True)(
        {"run_dir": run_dir, "task": {"id": "bad-meta", "goal": "write malformed meta"}}
    )
    assert result["execution_status"] == "ok"
    assert result["trace_records"] == []


def test_worktree_executor_cannot_read_unmounted_host_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    sentinel = tmp_path / "host-secret.txt"
    sentinel.write_text("must-not-be-readable", encoding="utf-8")
    command = (
        sys.executable,
        "-c",
        (
            "import pathlib; p=pathlib.Path(" + repr(str(sentinel)) + "); "
            "print('exposed' if p.exists() and p.read_text() else 'blocked')"
        ),
    )
    result = WorktreeSubprocessExecutor(repo=repo, command=command, allow_network=True)(
        {"run_dir": run_dir, "task": {"id": "sandbox", "goal": "probe host"}}
    )
    assert result["execution_status"] == "ok"
    assert result["executor_stdout"].strip() == "blocked"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux namespaces required")
def test_worktree_executor_unshares_network_and_pid_namespaces_by_default(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    host_namespaces = {
        name: os.readlink(f"/proc/self/ns/{name}") for name in ("net", "pid")
    }
    command = (
        sys.executable,
        "-c",
        (
            "import json,os; print(json.dumps({n:os.readlink('/proc/self/ns/'+n) "
            "for n in ('net','pid')}))"
        ),
    )
    result = WorktreeSubprocessExecutor(repo=repo, command=command)(
        {"run_dir": run_dir, "task": {"id": "namespaces", "goal": "probe namespaces"}}
    )
    if result["execution_status"] == "failed":
        # Restricted hosts that cannot create a network namespace must stop
        # before the worker command rather than silently sharing host network.
        assert result["executor_stdout"] == ""
        assert "bwrap" in result["executor_stderr"]
    else:
        child_namespaces = json.loads(result["executor_stdout"])
        assert child_namespaces["net"] != host_namespaces["net"]
        assert child_namespaces["pid"] != host_namespaces["pid"]

    compatible = WorktreeSubprocessExecutor(
        repo=repo, command=command, allow_network=True
    )({"run_dir": run_dir, "task": {"id": "shared-net", "goal": "explicit network opt-in"}})
    assert compatible["execution_status"] == "ok"
    compatible_namespaces = json.loads(compatible["executor_stdout"])
    assert compatible_namespaces["net"] == host_namespaces["net"]
    assert compatible_namespaces["pid"] != host_namespaces["pid"]


def test_worktree_executor_fails_closed_on_disk_budget(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run_dir = tmp_path / "run"
    result = WorktreeSubprocessExecutor(
        repo=repo,
        command=(
            sys.executable,
            "-c",
            "import pathlib,time; pathlib.Path('large.bin').write_bytes(b'x'*200_000); time.sleep(.2)",
        ),
        max_disk_bytes=64 * 1024,
        allow_network=True,
    )({"run_dir": run_dir, "task": {"id": "disk", "goal": "exhaust disk"}})
    assert result["execution_status"] == "failed"
    assert result["executor_resource_exhausted"] is True
    assert not (run_dir / "disk").exists()


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


@pytest.mark.skipif(os.name != "posix", reason="process-tree semantics are POSIX-specific")
def test_timeout_kills_descendant_that_escapes_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "detached-descendant-survived"
    child = (
        "import pathlib,time; time.sleep(.3); "
        f"pathlib.Path({str(marker)!r}).write_text('bad')"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}], start_new_session=True); "
        "time.sleep(5)"
    )
    started = time.monotonic()
    result = SubprocessExecutor(
        command=(sys.executable, "-c", parent),
        timeout=0.05,
    )({"worktree": tmp_path})
    elapsed = time.monotonic() - started
    assert result["executor_returncode"] == 124
    assert elapsed < 2.0
    time.sleep(0.4)
    assert not marker.exists()
