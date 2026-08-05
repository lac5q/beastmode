from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "langgraph-runner"


def _trusted_helpers(tmp_path: Path) -> tuple[Path, Path, Path]:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    attestor = trusted / "attest"
    attestor.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        "p=json.load(sys.stdin)\n"
        "print(json.dumps({'id':p['id'],'requested_model':p['requested_model'],"
        "'actual_model':p['requested_model'],'source':'test-parent-journal'}))\n",
        encoding="utf-8",
    )
    validator = trusted / "validate"
    validator.write_text(
        "#!/usr/bin/env python3\nimport json,sys\njson.load(sys.stdin)\n"
        "print(json.dumps({'validation_report':{'passed':True,'source':'test-validator'}}))\n",
        encoding="utf-8",
    )
    reviewer = trusted / "review"
    reviewer.write_text(
        "#!/usr/bin/env python3\nimport json,sys\njson.load(sys.stdin)\n"
        "print(json.dumps({'review_report':{'approved':True,'source':'test-reviewer'}}))\n",
        encoding="utf-8",
    )
    for path in (attestor, validator, reviewer):
        path.chmod(0o700)
    return attestor, validator, reviewer


def _helper_args(tmp_path: Path) -> list[str]:
    attestor, validator, reviewer = _trusted_helpers(tmp_path)
    return [
        "--allow-worker-network",
        "--attestor-command",
        str(attestor),
        "--validator-command",
        str(validator),
        "--reviewer-command",
        str(reviewer),
    ]


def test_runner_requires_an_explicit_child_driver(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(RUNNER), "missing-driver", "--database", str(tmp_path / "db.sqlite")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--executor-command" in result.stderr


def test_runner_executes_a_real_goal_in_a_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True)
    child_code = (
        "import json, os; from pathlib import Path; "
        "p=Path(os.environ['BEASTMODE_META_DIR']); p.mkdir(parents=True, exist_ok=True); "
        "model=os.environ['BEASTMODE_REQUESTED_MODEL']; "
        "(p/'meta.json').write_text(json.dumps({'id':os.environ['BEASTMODE_TASK_ID'],"
        "'requested_model':model,'actual_model':model,'stop_reason':'end_turn','usage':{},"
        "'files_changed':[],'commands_run':[],'verify':{'passed':True}}))"
    )
    command = f"{sys.executable} -c {json.dumps(child_code)}"
    argv = [
            sys.executable,
            str(RUNNER),
            "real-goal",
            "--autonomy",
            "high",
            "--database",
            str(tmp_path / "db.sqlite"),
            "--run-dir",
            str(tmp_path / "run"),
            "--worktree-root",
            str(tmp_path / "worktrees"),
            "--repo",
            str(repo),
            "--executor-command",
            command,
        ]
    argv.extend(_helper_args(tmp_path))
    result = subprocess.run(
        argv,
        cwd=repo,
        env={**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "merged"
    traces = payload["trace_records"]
    child_trace = next(record for record in traces if record["name"] == "beastmode.child")
    node_trace = next(record for record in traces if record["name"] == "beastmode.node")
    assert child_trace["attributes"]["goal_id"] == "real-goal"
    assert node_trace["attributes"]["goal_id"] == "real-goal"


def test_runner_default_run_dir_does_not_use_goal_as_a_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True)
    child_code = (
        "import json, os; from pathlib import Path; "
        "p=Path(os.environ['BEASTMODE_META_DIR']); p.mkdir(parents=True, exist_ok=True); "
        "model=os.environ['BEASTMODE_REQUESTED_MODEL']; "
        "(p/'meta.json').write_text(json.dumps({'id':os.environ['BEASTMODE_TASK_ID'],"
        "'requested_model':model,'actual_model':model,'stop_reason':'end_turn','usage':{},"
        "'files_changed':[],'commands_run':[],'verify':{'passed':True}}))"
    )
    argv = [
            sys.executable,
            str(RUNNER),
            "../private goal",
            "--autonomy",
            "high",
            "--database",
            str(tmp_path / "db.sqlite"),
            "--repo",
            str(repo),
            "--worktree-root",
            str(tmp_path / "worktrees"),
            "--executor-command",
            f"{sys.executable} -c {json.dumps(child_code)}",
        ]
    argv.extend(_helper_args(tmp_path))
    result = subprocess.run(
        argv,
        cwd=repo,
        env={**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (tmp_path / "private goal").exists()
    assert not (repo.parent / "private goal").exists()


def test_runner_rejects_parent_helper_from_target_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    helper = repo / "attest"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o700)
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "unsafe-helper",
            "--repo",
            str(repo),
            "--executor-command",
            "/bin/true",
            "--attestor-command",
            str(helper),
            "--validator-command",
            str(helper),
            "--reviewer-command",
            str(helper),
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "outside the target repository" in result.stderr


def test_trusted_helper_output_is_bounded_while_running(tmp_path: Path) -> None:
    helper = tmp_path / "large-helper"
    helper.write_text(
        "#!/usr/bin/env python3\nimport sys\nsys.stdin.buffer.read()\n"
        "sys.stdout.write('x' * (1024 * 1024 + 1))\n",
        encoding="utf-8",
    )
    helper.chmod(0o700)
    namespace = runpy.run_path(str(RUNNER))
    trusted = namespace["_trusted_helper"](
        str(helper), repo=tmp_path / "different-repo", label="test"
    )
    callback = namespace["_json_callback"](trusted, required_key=None)
    import pytest

    with pytest.raises(ValueError, match="output exceeds"):
        callback({"bounded": True})


def test_trusted_helper_execution_is_bound_to_verified_file_identity(tmp_path: Path) -> None:
    helper = tmp_path / "identity-helper"
    helper.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\nsys.stdin.buffer.read()\n"
        "print(json.dumps({'marker':'verified'}))\n",
        encoding="utf-8",
    )
    helper.chmod(0o700)
    namespace = runpy.run_path(str(RUNNER))
    trusted = namespace["_trusted_helper"](
        str(helper), repo=tmp_path / "different-repo", label="test"
    )
    helper.unlink()
    helper.write_text(
        "#!/usr/bin/env python3\nprint('{\"marker\":\"replacement\"}')\n",
        encoding="utf-8",
    )
    helper.chmod(0o700)

    result = namespace["_json_callback"](trusted, required_key=None)({"run": True})
    assert result == {"marker": "verified"}
