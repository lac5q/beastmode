"""Safe-by-default subprocess execution for ACN child work."""

from __future__ import annotations

import os
import json
import re
import shlex
import shutil
import subprocess
import selectors
import signal
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from ..worktree import isolated_worktree
from ..observability import MAX_PUBLIC_TEXT_CHARS, child_span_from_meta, redact_text


DEFAULT_EXECUTOR_TIMEOUT = 300.0


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
    timeout: float | None = DEFAULT_EXECUTOR_TIMEOUT
    extra_env: Mapping[str, str] = field(default_factory=dict)

    def __call__(self, state: Mapping[str, object]) -> dict[str, object]:
        worktree = state.get("worktree") or state.get("run_dir")
        if not isinstance(worktree, (str, Path)):
            raise ValueError("subprocess executor needs a child worktree path")
        env = _safe_environment(self.extra_env or {})
        completed = _run_bounded(self.command, cwd=Path(worktree), env=env, timeout=self.timeout)
        stdout = _redact_explicit_env(completed.stdout, self.extra_env)
        stderr = _redact_explicit_env(completed.stderr, self.extra_env)
        return {
            "execution_status": "ok" if completed.returncode == 0 and not completed.timed_out else "failed",
            "executor_returncode": 124 if completed.timed_out else completed.returncode,
            "executor_stdout": stdout,
            "executor_stderr": stderr,
            "executor_output_truncated": completed.truncated,
            "commands_run": [_safe_command_label(self.command)],
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
    timeout: float | None = DEFAULT_EXECUTOR_TIMEOUT
    extra_env: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not _filesystem_sandbox_available():
            raise RuntimeError(
                "worktree executor requires bubblewrap on Linux; install bwrap "
                "or provide a different trusted executor implementation"
            )

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
                    "    commit|push|send-pack|receive-pack|update-ref|update-index|"
                    "config|reset|checkout|switch|merge|rebase|clean|tag|branch)\n"
                    "      printf 'blocked_git command\\n' >> \"${BEASTMODE_EXECUTOR_EVENTS:-/dev/null}\"\n"
                    "      echo 'beastmode: worker git write command is blocked' >&2\n"
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
                        "TMPDIR": str(child_run_dir / "tmp"),
                        "GIT_CONFIG_NOSYSTEM": "1",
                        "GIT_TERMINAL_PROMPT": "0",
                        "GIT_ASKPASS": "/bin/false",
                        "SSH_ASKPASS": "/bin/false",
                        "GIT_ALLOW_PROTOCOL": "",
                    },
                    path_prefix=(shim_root,),
                )
                child_command = _filesystem_sandbox_command(
                    self.command,
                    repo=Path(self.repo).resolve(),
                    worktree=worktree,
                    run_dir=run_dir,
                    scratch=child_run_dir / "tmp",
                )
                completed = _run_bounded(child_command, cwd=worktree, env=env, timeout=self.timeout)
                stdout = _redact_explicit_env(completed.stdout, self.extra_env or {})
                stderr = _redact_explicit_env(completed.stderr, self.extra_env or {})
                result = {
                    "execution_status": "ok" if completed.returncode == 0 and not completed.timed_out else "failed",
                    "executor_returncode": 124 if completed.timed_out else completed.returncode,
                    "executor_stdout": stdout,
                    "executor_stderr": stderr,
                    "executor_output_truncated": completed.truncated,
                    "executor_worktree": str(worktree),
                    "child_run_dir": str(child_run_dir),
                    "commands_run": [_safe_command_label(self.command)],
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


@dataclass(frozen=True)
class _BoundedCompleted:
    returncode: int
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool


def _run_bounded(
    command: Iterable[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float | None,
) -> _BoundedCompleted:
    """Run argv with bounded pipes, timeout, and process-group cleanup."""
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    deadline = None if timeout is None else time.monotonic() + max(timeout, 0.0)
    timed_out = False
    while selector.get_map():
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        if remaining == 0.0 and process.poll() is None:
            timed_out = True
            _kill_process_group(process)
            remaining = 1.0
        events = selector.select(remaining)
        if not events:
            if process.poll() is None:
                timed_out = True
                _kill_process_group(process)
            continue
        for key, _ in events:
            chunk = os.read(key.fileobj.fileno(), 8192)
            if not chunk:
                selector.unregister(key.fileobj)
                key.fileobj.close()
                continue
            name = key.data
            available = MAX_PUBLIC_TEXT_CHARS - len(buffers[name])
            if available > 0:
                buffers[name].extend(chunk[:available])
            if len(chunk) > max(available, 0):
                truncated[name] = True
    returncode = process.wait()
    if timed_out:
        returncode = 124
    stdout = redact_text(bytes(buffers["stdout"]).decode(errors="replace"))
    stderr = redact_text(bytes(buffers["stderr"]).decode(errors="replace"))
    return _BoundedCompleted(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        truncated=truncated["stdout"] or truncated["stderr"],
        timed_out=timed_out,
    )


def _kill_process_group(process: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    process.kill()


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
    extra_values = dict(extra)
    # A child must not replace the shim-first PATH with a caller-selected one.
    extra_values.pop("PATH", None)
    base.update(extra_values)
    if prefix:
        base["PATH"] = prefix + os.pathsep + base.get("PATH", "")
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


def _redact_explicit_env(text: str, values: Mapping[str, str]) -> str:
    """Remove caller-supplied credential values even when printed without a key."""
    redacted = text
    for key, value in values.items():
        if not re.search(r"(?i)(?:password|passwd|secret|token|api.?key|authorization|credential)", str(key)):
            continue
        secret = str(value)
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redact_text(redacted)


def _safe_command_label(command: Iterable[str]) -> str:
    """Record the executable without persisting potentially secret arguments."""
    parts = list(command)
    executable = Path(parts[0]).name if parts else "unknown"
    return f"{redact_text(executable, limit=256)} [arguments omitted]"


def _filesystem_sandbox_available() -> bool:
    return sys.platform.startswith("linux") and shutil.which("bwrap") is not None


def _filesystem_sandbox_command(
    command: Iterable[str],
    *,
    repo: Path,
    worktree: Path,
    run_dir: Path,
    scratch: Path,
) -> tuple[str, ...]:
    """Make the shared checkout/Git database read-only to the worker process."""
    bwrap = shutil.which("bwrap")
    if bwrap is None or not sys.platform.startswith("linux"):
        raise RuntimeError("required Linux bubblewrap filesystem sandbox is unavailable")
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    common = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    common_dir = Path(common)
    if not common_dir.is_absolute():
        common_dir = (repo / common_dir).resolve()
    config_path = common_dir / "config"
    args = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/",
        "/",
        "--dev-bind",
        "/dev",
        "/dev",
        "--proc",
        "/proc",
        "--bind",
        str(worktree),
        str(worktree),
        "--bind",
        str(run_dir),
        str(run_dir),
    ]
    if config_path.is_file():
        # Remove remotes and credential helpers even for an absolute git
        # executable; local read operations still work without this config.
        args.extend(("--ro-bind", "/dev/null", str(config_path)))
    args.extend(("--chdir", str(worktree), "--"))
    args.extend(str(part) for part in command)
    return tuple(args)


def _text_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)
