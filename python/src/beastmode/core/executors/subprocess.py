"""Safe-by-default subprocess execution for ACN child work."""

from __future__ import annotations

import os
import json
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from ..worktree import isolated_worktree
from ..observability import child_span_from_meta


@dataclass(frozen=True)
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    commands_run: tuple[str, ...]


@dataclass(frozen=True)
class SubprocessExecutor:
    """Run an argv command in a supplied child worktree with a reduced env."""

    command: tuple[str, ...]
    timeout: float | None = None
    extra_env: Mapping[str, str] = field(default_factory=dict)

    def __call__(self, state: Mapping[str, object]) -> dict[str, object]:
        worktree = state.get("worktree") or state.get("run_dir")
        if not isinstance(worktree, (str, Path)):
            raise ValueError("subprocess executor needs a child worktree path")
        env = _safe_environment(self.extra_env or {})
        completed = subprocess.run(
            list(self.command),
            cwd=Path(worktree),
            env=env,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        return {
            "execution_status": "ok" if completed.returncode == 0 else "failed",
            "executor_returncode": completed.returncode,
            "executor_stdout": completed.stdout,
            "executor_stderr": completed.stderr,
            "commands_run": [" ".join(self.command)],
        }


@dataclass(frozen=True)
class WorktreeSubprocessExecutor:
    """Run each ACN child in a disposable git worktree.

    The child command is responsible for writing ``$BEASTMODE_META_DIR/meta.json``
    using the canonical ACN shape.  This executor intentionally does not
    synthesize provenance on behalf of a killed or silent child; the expected
    child-id check must catch that absence.  A small ``git`` shim blocks worker
    commits and pushes while delegating read-only git commands to the real
    executable.
    """

    repo: Path
    command: tuple[str, ...]
    worktree_root: Path | None = None
    timeout: float | None = None
    extra_env: Mapping[str, str] | None = None

    def __call__(self, state: Mapping[str, object]) -> dict[str, object]:
        task = state.get("task")
        task = task if isinstance(task, Mapping) else {}
        task_id = _safe_task_id(task.get("id") or "child")
        run_dir_value = state.get("run_dir")
        if not isinstance(run_dir_value, (str, Path)):
            raise ValueError("worktree subprocess executor needs a run_dir")
        run_dir = Path(run_dir_value).resolve()
        child_run_dir = run_dir / task_id
        child_run_dir.mkdir(parents=True, exist_ok=True)
        worktree_root = Path(self.worktree_root or run_dir.parent / ".worktrees").resolve()
        worktree_root.mkdir(parents=True, exist_ok=True)
        worktree = worktree_root / f"{task_id}-{uuid.uuid4().hex[:10]}"
        events_path = run_dir / "executor-events.log"
        requested_model = str(
            task.get("requested_model")
            or state.get("executor_model")
            or "unconfigured/executor"
        )
        real_git = shutil.which("git")
        if real_git is None:
            raise RuntimeError("worktree subprocess executor requires git in PATH")

        with isolated_worktree(Path(self.repo), worktree):
            with tempfile.TemporaryDirectory(prefix="beastmode-git-shim-") as shim_root:
                shim = Path(shim_root) / "git"
                shim.write_text(
                    "#!/bin/sh\n"
                    "for arg do\n"
                    "  case \"$arg\" in\n"
                    "    commit|push)\n"
                    "      printf 'blocked_git %s\\n' \"$*\" >> \"${BEASTMODE_EXECUTOR_EVENTS:-/dev/null}\"\n"
                    "      echo 'beastmode: worker git commit/push is blocked' >&2\n"
                    "      exit 126\n"
                    "      ;;\n"
                    "  esac\n"
                    "done\n"
                    f"exec {shlex.quote(real_git)} \"$@\"\n",
                    encoding="utf-8",
                )
                shim.chmod(0o755)
                env = _safe_environment(
                    {
                        **dict(self.extra_env or {}),
                        "BEASTMODE_META_DIR": str(child_run_dir),
                        "BEASTMODE_RUN_DIR": str(run_dir),
                        "BEASTMODE_TASK_ID": task_id,
                        "BEASTMODE_TASK_GOAL": str(task.get("goal", "")),
                        "BEASTMODE_REQUESTED_MODEL": requested_model,
                        "BEASTMODE_EXECUTOR_EVENTS": str(events_path),
                    },
                    path_prefix=(shim_root,),
                )
                try:
                    completed = subprocess.run(
                        list(self.command),
                        cwd=worktree,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout,
                        check=False,
                    )
                    result = {
                        "execution_status": "ok" if completed.returncode == 0 else "failed",
                        "executor_returncode": completed.returncode,
                        "executor_stdout": completed.stdout,
                        "executor_stderr": completed.stderr,
                        "executor_worktree": str(worktree),
                        "child_run_dir": str(child_run_dir),
                        "commands_run": [" ".join(self.command)],
                    }
                    meta_path = child_run_dir / "meta.json"
                    if meta_path.is_file():
                        try:
                            result["trace_records"] = [
                                child_span_from_meta(
                                    meta_path,
                                    goal_id=str(state.get("goal_id") or state.get("thread_id") or "") or None,
                                )
                            ]
                        except (OSError, ValueError, json.JSONDecodeError):
                            result["trace_records"] = []
                    return result
                except subprocess.TimeoutExpired as exc:
                    return {
                        "execution_status": "failed",
                        "executor_returncode": 124,
                        "executor_stdout": _text_output(exc.stdout),
                        "executor_stderr": _text_output(exc.stderr),
                        "child_run_dir": str(child_run_dir),
                        "commands_run": [" ".join(self.command)],
                    }


def _safe_environment(
    extra: Mapping[str, str] | Iterable[tuple[str, str]],
    *,
    path_prefix: Iterable[Path] = (),
) -> dict[str, str]:
    """Keep credentials out of child env unless a caller explicitly opts in."""
    base = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR"}
        or key.startswith("LC_")
    }
    prefix = os.pathsep.join(str(path) for path in path_prefix)
    if prefix:
        base["PATH"] = prefix + os.pathsep + base.get("PATH", "")
    base.update(dict(extra))
    return base


def _safe_task_id(value: object) -> str:
    """Keep child ids to one portable filesystem path component."""
    task_id = str(value)
    if not task_id or len(task_id) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
        raise ValueError(
            "task id must be 1-128 characters of letters, digits, dot, underscore, or hyphen"
        )
    if task_id in {".", ".."}:
        raise ValueError("task id cannot be a dot path")
    return task_id


def _text_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)
