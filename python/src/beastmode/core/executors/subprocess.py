"""Safe-by-default subprocess execution for ACN child work."""

from __future__ import annotations

import os
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import selectors
import secrets
import signal
import stat
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

from ..worktree import (
    isolated_worktree,
    parent_git_command,
    parent_git_environment,
    trusted_git_path,
)
from ..observability import MAX_PUBLIC_TEXT_CHARS, child_span_from_meta, redact_text
from ..provenance import sign_attestation


DEFAULT_EXECUTOR_TIMEOUT = 300.0
DEFAULT_MAX_WORKER_DISK_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_WORKER_FILES = 100_000
DEFAULT_MAX_WORKER_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_WORKER_PROCESSES = 256
DEFAULT_MAX_WORKER_CPU_SECONDS = 300
DEFAULT_MAX_AGGREGATE_WORKERS = 4
_RESOURCE_POLL_SECONDS = 0.05
_TERMINATION_GRACE_SECONDS = 1.0
_WORKER_SLOTS = threading.BoundedSemaphore(DEFAULT_MAX_AGGREGATE_WORKERS)


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
    allow_network: bool = False
    max_disk_bytes: int = DEFAULT_MAX_WORKER_DISK_BYTES
    max_files: int = DEFAULT_MAX_WORKER_FILES
    max_memory_bytes: int = DEFAULT_MAX_WORKER_MEMORY_BYTES
    max_processes: int = DEFAULT_MAX_WORKER_PROCESSES
    max_cpu_seconds: int = DEFAULT_MAX_WORKER_CPU_SECONDS
    model_attestor: (
        Callable[[Mapping[str, object]], Mapping[str, object] | None] | None
    ) = None
    attestation_dir: Path | None = None
    attestation_key: bytes = field(
        default_factory=lambda: secrets.token_bytes(32), repr=False, compare=False
    )
    attestation_run_id: str = field(default_factory=lambda: secrets.token_hex(16))

    def __post_init__(self) -> None:
        if not _filesystem_sandbox_available():
            raise RuntimeError(
                "worktree executor requires bubblewrap on Linux; install bwrap "
                "or provide a different trusted executor implementation"
            )
        if any(
            limit <= 0
            for limit in (
                self.max_disk_bytes,
                self.max_files,
                self.max_memory_bytes,
                self.max_processes,
                self.max_cpu_seconds,
            )
        ):
            raise ValueError("worker resource limits must be positive")
        if shutil.which("prlimit", path=_safe_system_path()) is None:
            raise RuntimeError("worktree executor requires prlimit resource enforcement")

    def attestation_directory_for(self, run_dir: Path) -> Path:
        """Return the parent-owned path callers pass to runtime attestations."""
        return _trusted_attestation_directory(
            Path(run_dir).expanduser().resolve(), configured=self.attestation_dir
        )

    def __call__(self, state: Mapping[str, object]) -> dict[str, object]:
        task = state.get("task")
        task = task if isinstance(task, Mapping) else {}
        task_id = _safe_task_id(task.get("id") or "child")
        run_dir_value = state.get("run_dir")
        if not isinstance(run_dir_value, (str, Path)):
            raise ValueError("worktree subprocess executor needs a run_dir")
        run_dir = _trusted_parent_directory(Path(run_dir_value), label="run_dir")
        child_run_dir = _reset_disposable_directory(run_dir, task_id)
        attestation_dir = self.attestation_directory_for(run_dir)
        attestation_path = attestation_dir / f"{task_id}.json"
        _remove_disposable_path(attestation_path, attestation_dir)
        scratch = child_run_dir / "tmp"
        scratch.mkdir(mode=0o700)
        child_home = child_run_dir / "home"
        child_home.mkdir(mode=0o700)
        worktree_root = _trusted_parent_directory(
            Path(self.worktree_root or run_dir.parent / ".worktrees"),
            label="worktree_root",
        )
        worktree = worktree_root / f"{task_id}-{uuid.uuid4().hex[:10]}"
        events_path = run_dir / "executor-events.log"
        _prepare_regular_file(events_path)
        requested_model = str(
            task.get("requested_model")
            or state.get("executor_model")
            or "unconfigured/executor"
        )
        real_git = trusted_git_path()

        slot_timeout = self.timeout if self.timeout is not None else DEFAULT_EXECUTOR_TIMEOUT
        if not _WORKER_SLOTS.acquire(timeout=max(float(slot_timeout), 0.0)):
            raise RuntimeError("aggregate worker concurrency budget is exhausted")
        try:
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
                        f"exec {shlex.quote(str(real_git))} \"$@\"\n",
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
                            "HOME": str(child_home),
                            "TMPDIR": str(scratch),
                            "GIT_CONFIG_NOSYSTEM": "1",
                            "GIT_CONFIG_GLOBAL": "/dev/null",
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
                        child_run_dir=child_run_dir,
                        events_path=events_path,
                        trusted_ro_paths=(Path(shim_root),),
                        allow_network=self.allow_network,
                    )
                    effective_disk_budget = _effective_disk_budget(
                        (worktree, run_dir), self.max_disk_bytes
                    )
                    completed = _run_bounded(
                        _with_resource_limits(
                            child_command,
                            max_file_bytes=effective_disk_budget,
                            max_memory_bytes=self.max_memory_bytes,
                            max_processes=self.max_processes,
                            max_cpu_seconds=self.max_cpu_seconds,
                        ),
                        cwd=worktree,
                        env=env,
                        timeout=self.timeout,
                        disk_roots=(worktree, run_dir),
                        max_disk_bytes=effective_disk_budget,
                        max_files=self.max_files,
                    )
                    changed_paths = _worktree_changed_paths(worktree)
                    unauthorized_paths = _unauthorized_paths(
                        changed_paths, task.get("allowed_paths", ())
                    )
                    stdout = _redact_explicit_env(completed.stdout, self.extra_env or {})
                    stderr = _redact_explicit_env(completed.stderr, self.extra_env or {})
                    attestation_status = "unconfigured"
                    attestation_error = ""
                    if self.model_attestor is not None:
                        try:
                            attestation = self.model_attestor(
                                {
                                    "id": task_id,
                                    "requested_model": requested_model,
                                    "returncode": completed.returncode,
                                    "timed_out": completed.timed_out,
                                    "resource_exhausted": completed.resource_exhausted,
                                }
                            )
                            record = _validate_parent_attestation(
                                attestation,
                                child_id=task_id,
                                requested_model=requested_model,
                            )
                            record["run_id"] = self.attestation_run_id
                            record["result_digest"] = _result_digest(
                                child_run_dir / "meta.json"
                            )
                            record["signature"] = sign_attestation(
                                record, self.attestation_key
                            )
                            _write_parent_attestation(attestation_path, record)
                            attestation_status = "ok"
                        except Exception as exc:
                            attestation_status = "failed"
                            attestation_error = _redact_explicit_env(
                                redact_text(exc, limit=512), self.extra_env or {}
                            )
                    result = {
                        "execution_status": (
                            "ok"
                            if completed.returncode == 0
                            and not completed.timed_out
                            and not completed.resource_exhausted
                            and not unauthorized_paths
                            and attestation_status != "failed"
                            else "failed"
                        ),
                        "executor_returncode": (
                            125
                            if completed.resource_exhausted
                            else 124
                            if completed.timed_out
                            else 126
                            if unauthorized_paths
                            else completed.returncode
                        ),
                        "executor_stdout": stdout,
                        "executor_stderr": stderr,
                        "executor_output_truncated": completed.truncated,
                        "executor_resource_exhausted": completed.resource_exhausted,
                        "files_changed": list(changed_paths),
                        "unauthorized_paths": list(unauthorized_paths),
                        "path_authorization_error": (
                            "worker changed paths outside task.allowed_paths"
                            if unauthorized_paths
                            else ""
                        ),
                        "executor_worktree": str(worktree),
                        "child_run_dir": str(child_run_dir),
                        "model_attestation_status": attestation_status,
                        "model_attestation_error": attestation_error,
                        "model_attestation_path": (
                            str(attestation_path) if attestation_status == "ok" else None
                        ),
                        "model_attestation_dir": str(attestation_dir),
                        "model_attestation_run_id": self.attestation_run_id,
                        "commands_run": [_safe_command_label(self.command)],
                        "trace_records": [],
                    }
                    if completed.resource_exhausted:
                        _remove_disposable_path(child_run_dir, run_dir)
                    else:
                        meta_path = child_run_dir / "meta.json"
                        if meta_path.exists() or meta_path.is_symlink():
                            try:
                                result["trace_records"] = [
                                    child_span_from_meta(
                                        meta_path,
                                        attestations=(
                                            attestation_path
                                            if attestation_status == "ok"
                                            else None
                                        ),
                                        attestation_key=self.attestation_key,
                                        attestation_run_id=self.attestation_run_id,
                                        goal_id=str(
                                            state.get("goal_id") or state.get("thread_id") or ""
                                        )
                                        or None,
                                    )
                                ]
                            except (OSError, ValueError, json.JSONDecodeError):
                                result["trace_records"] = []
                    return result
        finally:
            _remove_disposable_path(worktree, worktree_root)
            _WORKER_SLOTS.release()


@dataclass(frozen=True)
class _BoundedCompleted:
    returncode: int
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool
    resource_exhausted: bool
    output_exhausted: bool


def _run_bounded(
    command: Iterable[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float | None,
    disk_roots: Iterable[Path] = (),
    max_disk_bytes: int | None = None,
    max_files: int | None = None,
    input_data: bytes | None = None,
    max_stdout_bytes: int = MAX_PUBLIC_TEXT_CHARS,
    max_stderr_bytes: int = MAX_PUBLIC_TEXT_CHARS,
    terminate_on_output_limit: bool = False,
    pass_fds: Iterable[int] = (),
) -> _BoundedCompleted:
    """Run argv with bounded pipes, timeout, and process-group cleanup."""
    if max_stdout_bytes <= 0 or max_stderr_bytes <= 0:
        raise ValueError("subprocess output limits must be positive")
    input_file = None
    try:
        if input_data is not None:
            input_file = tempfile.TemporaryFile()
            input_file.write(input_data)
            input_file.seek(0)
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdin=input_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
            pass_fds=tuple(pass_fds) if os.name == "posix" else (),
        )
    finally:
        if input_file is not None:
            input_file.close()
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    deadline = None if timeout is None else time.monotonic() + max(timeout, 0.0)
    timed_out = False
    resource_exhausted = False
    output_exhausted = False
    termination_deadline: float | None = None
    known_descendants: dict[int, int] = {}
    while selector.get_map() or process.poll() is None:
        now = time.monotonic()
        _remember_descendants(process.pid, known_descendants)
        if termination_deadline is None and deadline is not None and now >= deadline:
            timed_out = True
            _terminate_process_tree(process, known_descendants)
            termination_deadline = now + _TERMINATION_GRACE_SECONDS
        if termination_deadline is None and _disk_budget_exceeded(
            disk_roots, max_disk_bytes=max_disk_bytes, max_files=max_files
        ):
            resource_exhausted = True
            _terminate_process_tree(process, known_descendants)
            termination_deadline = now + _TERMINATION_GRACE_SECONDS
        if termination_deadline is not None and now >= termination_deadline:
            break
        if not selector.get_map() and process.poll() is not None:
            break
        waits = [_RESOURCE_POLL_SECONDS]
        if deadline is not None:
            waits.append(max(0.0, deadline - now))
        if termination_deadline is not None:
            waits.append(max(0.0, termination_deadline - now))
        events = selector.select(min(waits))
        if not events:
            continue
        for key, _ in events:
            chunk = os.read(key.fileobj.fileno(), 8192)
            if not chunk:
                selector.unregister(key.fileobj)
                key.fileobj.close()
                continue
            name = key.data
            limit = max_stdout_bytes if name == "stdout" else max_stderr_bytes
            available = limit - len(buffers[name])
            if available > 0:
                buffers[name].extend(chunk[:available])
            if len(chunk) > max(available, 0):
                truncated[name] = True
                output_exhausted = True
                if terminate_on_output_limit and termination_deadline is None:
                    _terminate_process_tree(process, known_descendants)
                    termination_deadline = time.monotonic() + _TERMINATION_GRACE_SECONDS
    _close_selector(selector)
    try:
        returncode = process.wait(timeout=_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process, known_descendants)
        try:
            returncode = process.wait(timeout=_TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            returncode = 124
    if timed_out:
        returncode = 124
    elif resource_exhausted:
        returncode = 125
    stdout = redact_text(
        bytes(buffers["stdout"]).decode(errors="replace"), limit=max_stdout_bytes
    )
    stderr = redact_text(
        bytes(buffers["stderr"]).decode(errors="replace"), limit=max_stderr_bytes
    )
    return _BoundedCompleted(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        truncated=truncated["stdout"] or truncated["stderr"],
        timed_out=timed_out,
        resource_exhausted=resource_exhausted,
        output_exhausted=output_exhausted,
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


def _terminate_process_tree(
    process: subprocess.Popen, known_descendants: dict[int, int]
) -> None:
    """Stop and kill descendants even when they created a new session."""
    for _ in range(3):
        _remember_descendants(process.pid, known_descendants)
        for pid, started in tuple(known_descendants.items()):
            _signal_same_process(pid, started, signal.SIGSTOP)
    _kill_process_group(process)
    for pid, started in tuple(known_descendants.items()):
        _signal_same_process(pid, started, signal.SIGKILL)


def _remember_descendants(parent_pid: int, known: dict[int, int]) -> None:
    if not sys.platform.startswith("linux"):
        return
    pending = [parent_pid]
    seen = set(pending)
    while pending:
        pid = pending.pop()
        try:
            children_text = Path(f"/proc/{pid}/task/{pid}/children").read_text()
        except OSError:
            continue
        for item in children_text.split():
            try:
                child_pid = int(item)
            except ValueError:
                continue
            if child_pid in seen:
                continue
            seen.add(child_pid)
            started = _process_start_time(child_pid)
            if started is not None:
                known[child_pid] = started
                pending.append(child_pid)


def _process_start_time(pid: int) -> int | None:
    try:
        body = Path(f"/proc/{pid}/stat").read_text()
        return int(body.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _signal_same_process(pid: int, started: int, signum: signal.Signals) -> None:
    if _process_start_time(pid) != started:
        return
    try:
        os.kill(pid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _close_selector(selector: selectors.BaseSelector) -> None:
    for key in list(selector.get_map().values()):
        try:
            selector.unregister(key.fileobj)
        except (KeyError, ValueError):
            pass
        try:
            key.fileobj.close()
        except OSError:
            pass
    selector.close()


def _safe_environment(
    extra: Mapping[str, str] | Iterable[tuple[str, str]],
    *,
    path_prefix: Iterable[Path] = (),
) -> dict[str, str]:
    """Keep credentials out of child env unless a caller explicitly opts in."""
    base = {
        key: value
        for key, value in os.environ.items()
        if key in {"LANG", "LC_ALL", "LC_CTYPE"}
        or key.startswith("LC_")
    }
    base["PATH"] = _safe_system_path()
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


def _validated_git_common_dir(repo: Path, raw_common_dir: str) -> Path:
    """Return a Git admin path that stays inside the trusted repository."""
    repo_root = Path(repo).resolve(strict=True)
    git_root = repo_root / ".git"
    if git_root.is_symlink() or not git_root.is_dir():
        raise RuntimeError("trusted repository must have a real .git directory")
    git_root = git_root.resolve(strict=True)
    if raw_common_dir.strip() == "":
        raise RuntimeError("git returned an empty common directory")
    candidate = Path(raw_common_dir)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    # Normalize lexical '..' segments before comparing with the resolved path;
    # a symlink component must not turn a repository-looking path into a host
    # path outside the approved Git admin root.
    candidate = Path(os.path.abspath(str(candidate)))
    resolved = candidate.resolve(strict=True)
    if candidate != resolved:
        raise RuntimeError("git common directory contains a symlink component")
    try:
        resolved.relative_to(git_root)
    except ValueError as exc:
        raise RuntimeError("git common directory escapes the trusted repository") from exc
    if not resolved.is_dir():
        raise RuntimeError("git common directory is not a directory")
    return resolved


def _filesystem_sandbox_command(
    command: Iterable[str],
    *,
    repo: Path,
    worktree: Path,
    child_run_dir: Path,
    events_path: Path,
    trusted_ro_paths: Iterable[Path] = (),
    allow_network: bool = False,
) -> tuple[str, ...]:
    """Expose only the worker checkout, artifacts, and trusted runtime roots."""
    bwrap = shutil.which("bwrap")
    if bwrap is None or not sys.platform.startswith("linux"):
        raise RuntimeError("required Linux bubblewrap filesystem sandbox is unavailable")
    command_parts, runtime_paths = _sandbox_runtime_paths(command, worktree)
    common = subprocess.run(
        parent_git_command(repo, "rev-parse", "--git-common-dir"),
        check=True,
        capture_output=True,
        text=True,
        env=parent_git_environment(),
        timeout=5,
    ).stdout.strip()
    common_dir = _validated_git_common_dir(repo, common)
    config_path = common_dir / "config"
    args = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
    ]
    if allow_network:
        args.append("--share-net")
    args.extend(
        [
        "--tmpfs",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        ]
    )
    created_dirs: set[Path] = {Path("/")}
    _append_system_mounts(args, created_dirs)
    readonly_paths = [common_dir, *runtime_paths, *map(Path, trusted_ro_paths)]
    for source in _unique_paths(readonly_paths):
        _append_bind(args, source, source, readonly=True, created_dirs=created_dirs)
    _append_bind(args, worktree, worktree, readonly=False, created_dirs=created_dirs)
    git_pointer = worktree / ".git"
    if git_pointer.exists() or git_pointer.is_symlink():
        _append_bind(
            args,
            git_pointer,
            git_pointer,
            readonly=True,
            created_dirs=created_dirs,
        )
    _append_bind(
        args,
        child_run_dir,
        child_run_dir,
        readonly=False,
        created_dirs=created_dirs,
    )
    _append_bind(
        args,
        events_path,
        events_path,
        readonly=False,
        created_dirs=created_dirs,
    )
    if config_path.is_file():
        # Remove remotes and credential helpers even for an absolute git
        # executable; local read operations still work without this config.
        args.extend(("--ro-bind", "/dev/null", str(config_path)))
    args.extend(("--chdir", str(worktree), "--"))
    args.extend(command_parts)
    return tuple(args)


def _safe_system_path() -> str:
    candidates = (
        "/usr/local/sbin",
        "/usr/local/bin",
        "/usr/sbin",
        "/usr/bin",
        "/sbin",
        "/bin",
    )
    return os.pathsep.join(path for path in candidates if Path(path).is_dir())


def _sandbox_runtime_paths(
    command: Iterable[str], worktree: Path
) -> tuple[list[str], tuple[Path, ...]]:
    parts = [str(part) for part in command]
    if not parts:
        raise ValueError("worker command cannot be empty")
    executable = Path(parts[0])
    if not executable.is_absolute() and len(executable.parts) == 1:
        resolved = shutil.which(parts[0], path=_safe_system_path())
        if resolved is None:
            current = shutil.which(parts[0])
            if current is None:
                raise RuntimeError(f"worker executable is unavailable: {parts[0]}")
            executable = Path(current)
        else:
            executable = Path(resolved)
        parts[0] = str(executable)
    elif not executable.is_absolute():
        candidate = (worktree / executable).resolve()
        if not candidate.is_relative_to(worktree.resolve()):
            raise RuntimeError("worker executable cannot escape its worktree")
        return parts, ()

    # Paths supplied by a virtualenv can contain lexical ``..`` components
    # (for example ``python/../.venv/bin/python``).  Bubblewrap only exposes
    # the explicitly mounted runtime roots, so an otherwise equivalent path
    # can fail while resolving an unmounted intermediate directory.  Collapse
    # those components without resolving the virtualenv's interpreter symlink;
    # retaining that symlink is what gives Python the intended ``sys.prefix``.
    executable = Path(os.path.abspath(executable))
    parts[0] = str(executable)
    resolved_executable = executable.resolve()
    system_roots = tuple(
        path.resolve()
        for path in map(Path, ("/usr", "/bin", "/sbin", "/lib", "/lib64"))
        if path.exists()
    )
    if any(resolved_executable.is_relative_to(root) for root in system_roots):
        return parts, ()
    runtime_roots = _unique_paths(
        (
            Path(sys.prefix).resolve(),
            Path(sys.base_prefix).resolve(),
            # Some managed runtimes make the venv interpreter point through a
            # version-selection symlink beside ``sys.base_prefix``.  Mount only
            # that runtime-generation directory so the symlink resolves; this
            # is not a mount of the surrounding home or agent configuration.
            Path(sys.base_prefix).resolve().parent,
        )
    )
    if any(
        executable.is_relative_to(root) or resolved_executable.is_relative_to(root)
        for root in runtime_roots
    ):
        return parts, tuple(runtime_roots)
    if executable.is_relative_to(worktree.resolve()):
        return parts, ()
    raise RuntimeError(
        "worker executable must be in the isolated worktree, a system path, "
        "or the current trusted Python runtime"
    )


def _append_system_mounts(args: list[str], created_dirs: set[Path]) -> None:
    usr = Path("/usr")
    if usr.is_dir():
        _append_bind(args, usr, usr, readonly=True, created_dirs=created_dirs)
    for alias in map(Path, ("/bin", "/sbin", "/lib", "/lib64")):
        if not alias.exists() and not alias.is_symlink():
            continue
        if alias.is_symlink():
            _ensure_parent_dirs(args, alias, created_dirs)
            args.extend(("--symlink", os.readlink(alias), str(alias)))
        elif alias != usr:
            _append_bind(args, alias, alias, readonly=True, created_dirs=created_dirs)
    for source in map(
        Path,
        (
            "/etc/ca-certificates",
            "/etc/ssl",
            "/etc/hosts",
            "/etc/ld.so.cache",
            "/etc/localtime",
            "/etc/nsswitch.conf",
            "/etc/protocols",
            "/etc/resolv.conf",
            "/etc/services",
        ),
    ):
        if source.exists():
            _append_bind(args, source, source, readonly=True, created_dirs=created_dirs)


def _append_bind(
    args: list[str],
    source: Path,
    target: Path,
    *,
    readonly: bool,
    created_dirs: set[Path],
) -> None:
    source = source.resolve()
    _ensure_parent_dirs(args, target, created_dirs)
    args.extend(("--ro-bind" if readonly else "--bind", str(source), str(target)))


def _ensure_parent_dirs(args: list[str], target: Path, created_dirs: set[Path]) -> None:
    missing = []
    parent = target.parent
    while parent != Path("/") and parent not in created_dirs:
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        args.extend(("--dir", str(directory)))
        created_dirs.add(directory)


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    unique = []
    seen = set()
    for path in paths:
        resolved = Path(path).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _reset_disposable_directory(parent: Path, name: str) -> Path:
    destination = parent / name
    _remove_disposable_path(destination, parent)
    destination.mkdir(mode=0o700)
    return destination


def _trusted_parent_directory(path: Path, *, label: str) -> Path:
    """Create an owner-only parent directory without following symlink components."""
    candidate = Path(path).expanduser().absolute()
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not contain symlink components")
    candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not contain symlink components")
    if not candidate.is_dir():
        raise ValueError(f"{label} must be a directory")
    metadata = candidate.stat()
    if metadata.st_uid not in {0, os.geteuid()}:
        raise ValueError(f"{label} must be owned by root or the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        candidate.chmod(0o700)
        if stat.S_IMODE(candidate.stat().st_mode) & 0o077:
            raise ValueError(f"{label} must be owner-only")
    return candidate.resolve(strict=True)


def _trusted_attestation_directory(
    run_dir: Path, *, configured: Path | None
) -> Path:
    directory = (
        Path(configured).expanduser().resolve()
        if configured is not None
        else run_dir.parent / f".{run_dir.name}.attestations"
    )
    run_dir = run_dir.resolve()
    if directory == run_dir or run_dir in directory.parents:
        raise ValueError("attestation_dir must be outside the worker-writable run_dir")
    if directory.is_symlink():
        raise ValueError("attestation_dir must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("attestation_dir must be a regular directory")
    metadata = directory.stat()
    if metadata.st_uid not in {0, os.geteuid()}:
        raise ValueError("attestation_dir must be owned by root or the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        try:
            directory.chmod(0o700)
        except OSError as exc:
            raise ValueError("attestation_dir must be owner-only") from exc
        if stat.S_IMODE(directory.stat().st_mode) & 0o077:
            raise ValueError("attestation_dir must be owner-only")
    return directory.resolve()


def _worktree_changed_paths(worktree: Path) -> tuple[str, ...]:
    """Return parent-observed tracked and untracked changes without renames."""
    commands = (
        ("diff", "--no-ext-diff", "--no-renames", "--name-only", "-z", "HEAD", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z", "--"),
        ("ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--"),
    )
    changed: set[str] = set()
    for args in commands:
        output = subprocess.run(
            parent_git_command(worktree, *args),
            check=True,
            capture_output=True,
            env=parent_git_environment(),
            timeout=10,
        ).stdout
        for raw in output.split(b"\0"):
            if raw:
                changed.add(raw.decode("utf-8", errors="surrogateescape"))
    return tuple(sorted(changed))


def _unauthorized_paths(
    changed_paths: Iterable[str], allowed_paths: object
) -> tuple[str, ...]:
    """Fail closed when a worker writes outside its task path contract."""
    if not isinstance(allowed_paths, (list, tuple)):
        allowed: tuple[str, ...] = ()
    else:
        normalized: list[str] = []
        for raw in allowed_paths:
            if not isinstance(raw, str) or not raw or "\x00" in raw:
                raise ValueError("task allowed_paths contains an invalid path")
            path = raw.replace("\\", "/").rstrip("/") or "."
            parts = tuple(part for part in path.split("/") if part not in ("", "."))
            if path.startswith("/") or ".." in parts:
                raise ValueError("task allowed_paths must stay inside the worktree")
            normalized.append("/".join(parts) or ".")
        allowed = tuple(dict.fromkeys(normalized))
    denied = []
    for path in changed_paths:
        if not any(
            prefix == "." or path == prefix or path.startswith(prefix + "/")
            for prefix in allowed
        ):
            denied.append(path)
    return tuple(sorted(denied))


def _validate_parent_attestation(
    value: Mapping[str, object] | None,
    *,
    child_id: str,
    requested_model: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("model_attestor must return an attestation object")
    record = {
        field: _attestation_text(value.get(field), field)
        for field in ("id", "requested_model", "actual_model", "source")
    }
    if record["id"] != child_id:
        raise ValueError("model attestation does not bind the expected child id")
    if record["requested_model"] != requested_model:
        raise ValueError("model attestation does not bind the requested model")
    return record


def _attestation_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f"model attestation {field} must be a nonempty bounded string")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*", value):
        raise ValueError(f"model attestation {field} contains unsafe characters")
    return value


def _result_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("model attestation requires regular child metadata")
    if path.stat().st_size > 256 * 1024:
        raise ValueError("model attestation child metadata exceeds 262144 bytes")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_parent_attestation(path: Path, record: Mapping[str, str]) -> None:
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(record), handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _prepare_regular_file(path: Path) -> None:
    """Create one parent-owned file without following an inherited symlink."""
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ValueError("executor events path must be a regular, non-symlink file") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("executor events path must be a regular, non-symlink file")
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)


def _remove_disposable_path(path: Path, parent: Path) -> None:
    """Remove one exact child without following a worker-created symlink."""
    path = Path(path)
    parent = Path(parent).resolve()
    if path.parent.resolve() != parent or path.name in {"", ".", ".."}:
        raise ValueError("refusing to remove a path outside its disposable root")
    try:
        path.lstat()
    except FileNotFoundError:
        return
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
        return
    shutil.rmtree(path)


def _disk_budget_exceeded(
    roots: Iterable[Path], *, max_disk_bytes: int | None, max_files: int | None
) -> bool:
    if max_disk_bytes is None and max_files is None:
        return False
    total_bytes = 0
    total_files = 0
    pending = [Path(root) for root in roots]
    seen_roots: set[Path] = set()
    while pending:
        current = pending.pop()
        try:
            identity = current.resolve()
        except OSError:
            return True
        if identity in seen_roots:
            continue
        seen_roots.add(identity)
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    total_files += 1
                    if max_files is not None and total_files > max_files:
                        return True
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError:
                        return True
                    total_bytes += metadata.st_size
                    if max_disk_bytes is not None and total_bytes > max_disk_bytes:
                        return True
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
        except FileNotFoundError:
            continue
        except OSError:
            return True
    return False


def _effective_disk_budget(roots: Iterable[Path], configured: int) -> int:
    """Leave most free space unavailable so one worker cannot fill the volume."""
    free_space = []
    for root in roots:
        try:
            free_space.append(shutil.disk_usage(root).free)
        except OSError:
            continue
    if not free_space:
        return configured
    return max(1, min(configured, min(free_space) // 10))


def _current_user_task_count() -> int:
    """Count kernel tasks charged to the current UID for RLIMIT_NPROC headroom.

    Bubblewrap creates its user namespace after ``prlimit`` has applied the
    process ceiling.  Linux rejects that namespace creation with ``EAGAIN``
    when the ceiling is below the caller's already-running task count.  Count
    threads, rather than only ``/proc/<pid>`` entries, because the kernel's
    process limit charges each task.
    """
    if not sys.platform.startswith("linux"):
        return 0
    uid = os.getuid()
    total = 0
    proc = Path("/proc")
    try:
        entries = tuple(proc.iterdir())
    except OSError as exc:
        raise RuntimeError("cannot inspect /proc for worker process limits") from exc
    for entry in entries:
        if not entry.name.isdigit():
            continue
        real_uid: int | None = None
        threads = 1
        try:
            for line in (entry / "status").read_text(encoding="utf-8").splitlines():
                if line.startswith("Uid:"):
                    real_uid = int(line.split()[1])
                elif line.startswith("Threads:"):
                    threads = int(line.split()[1])
        except (OSError, ValueError, IndexError):
            # Processes can exit between iterdir() and reading status.
            continue
        if real_uid == uid:
            total += max(threads, 1)
    return total


def _nproc_limit_for_bwrap(max_processes: int) -> int:
    """Return a host-UID ceiling that leaves ``max_processes`` for the worker."""
    current_tasks = _current_user_task_count()
    # prlimit itself and Bubblewrap's setup need trusted launcher slots.  They
    # are not part of the untrusted worker's process budget.
    requested = current_tasks + max_processes + 2
    try:
        import resource as _resource

        hard_limit = _resource.getrlimit(_resource.RLIMIT_NPROC)[1]
        infinity = _resource.RLIM_INFINITY
    except (ImportError, OSError):
        hard_limit = -1
        infinity = -1
    if hard_limit not in {-1, infinity} and requested > hard_limit:
        raise RuntimeError(
            "worker process limit leaves no room for Bubblewrap namespace setup"
        )
    return requested


def _with_resource_limits(
    command: Iterable[str],
    *,
    max_file_bytes: int,
    max_memory_bytes: int,
    max_processes: int,
    max_cpu_seconds: int,
) -> tuple[str, ...]:
    """Apply mandatory kernel resource ceilings before entering Bubblewrap."""
    parts = tuple(str(part) for part in command)
    prlimit = shutil.which("prlimit", path=_safe_system_path())
    if prlimit is None:
        raise RuntimeError("required prlimit resource enforcement is unavailable")
    nproc_limit = _nproc_limit_for_bwrap(max_processes)
    return (
        prlimit,
        f"--fsize={max_file_bytes}:{max_file_bytes}",
        f"--as={max_memory_bytes}:{max_memory_bytes}",
        f"--nproc={nproc_limit}:{nproc_limit}",
        f"--cpu={max_cpu_seconds}:{max_cpu_seconds}",
        "--",
        *parts,
    )


def _text_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)
