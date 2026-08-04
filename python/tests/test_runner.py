from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "langgraph-runner"


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
    result = subprocess.run(
        [
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
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
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
    result = subprocess.run(
        [
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
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "private goal").exists()
    assert not (repo.parent / "private goal").exists()
