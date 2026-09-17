"""Native goal lifecycle for Beastmode (schema/goal-lifecycle.json).

One stdlib module owns every durable goal record: identity, state machine,
events, approvals, supervision, cancellation, reconciliation and the
revision-bound acceptance record. `scripts/bm-goal` and `bm goal <verb>` are
thin CLI wrappers over `main()`.

Layout (outside the target repository):

  $XDG_STATE_HOME/beastmode/goals/<goal_id>/goal.json      atomic snapshot
  $XDG_STATE_HOME/beastmode/goals/<goal_id>/events.jsonl   append-only history
  $XDG_STATE_HOME/beastmode/goals/<goal_id>/attempts/a<n>/ attempt.json,
                                                            harness.log, run/,
                                                            result.json
  $XDG_STATE_HOME/beastmode/locks/<repo-digest>.lock       one goal per repo

Every state change is refused unless schema/goal-lifecycle.json lists the
transition; nothing here ever equates completion with merge.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

LIB_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = LIB_DIR.parent
ROOT = SCRIPTS_DIR.parent

sys.path.insert(0, str(LIB_DIR))
import acn_meta  # noqa: E402



def _locate_contract() -> Path:
    """schema/goal-lifecycle.json from the repo root, or beside an installed bm."""
    for candidate in (ROOT, SCRIPTS_DIR):
        path = candidate / "schema" / "goal-lifecycle.json"
        if path.is_file():
            return path
    return ROOT / "schema" / "goal-lifecycle.json"


CONTRACT_PATH = _locate_contract()

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_BREAKER = 3
EXIT_AWAITING = 4
EXIT_CANCELLED = 5
EXIT_UNSUPPORTED = 6
EXIT_CONFLICT = 7

STATE_EXIT = {
    "succeeded": EXIT_OK,
    "awaiting_approval": EXIT_AWAITING,
    "cancelled": EXIT_CANCELLED,
    "failed": EXIT_FAILED,
    "blocked": EXIT_FAILED,
    "queued": EXIT_FAILED,
    "paused": EXIT_FAILED,
    "running": EXIT_FAILED,
}

GOAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ATTEMPT_ID_RE = re.compile(r"^a[1-9][0-9]{0,5}$")
DECISION_ID_RE = re.compile(r"^d[1-9][0-9]{0,5}$")
MAX_LOG_TAIL = 2_000
MAX_CONTROL_BYTES = 64 * 1024
MAX_GOAL_TEXT = 8_000
HEARTBEAT_SECONDS = 2.0
DEFAULT_STALL_SECONDS = 1_800
DEFAULT_GRACE_SECONDS = 10.0
NOTIFY_RETRIES = 3

# Flags `scripts/bm` consumes with a value. They are split away from the goal
# text so the supervisor can record the harness/autonomy it launched with.
BM_VALUE_FLAGS = {
    "--harness", "--on", "--frontier", "--economy", "--watcher", "--graph",
    "--executor-command", "--attestor-command", "--validator-command",
    "--reviewer-command", "--worktree-root", "--autonomy", "--interview",
    "--thinking",
}
BM_BOOL_FLAGS = {"--gsd", "--claude-subscription", "--allow-worker-network"}


class LifecycleError(Exception):
    def __init__(self, message: str, exit_code: int = EXIT_USAGE):
        super().__init__(message)
        self.exit_code = exit_code


def _contract() -> dict[str, Any]:
    with CONTRACT_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or "transitions" not in data:
        raise LifecycleError(f"invalid lifecycle contract: {CONTRACT_PATH}")
    return data


CONTRACT = _contract()
STATES: tuple[str, ...] = tuple(CONTRACT["states"])
TRANSITIONS: dict[str, tuple[str, ...]] = {
    key: tuple(value) for key, value in CONTRACT["transitions"].items()
}
TERMINAL_STATES: frozenset[str] = frozenset(CONTRACT["terminal_states"])
RETRYABLE_OUTCOMES: frozenset[str] = frozenset(CONTRACT["retryable_outcomes"])
CAPABILITIES: dict[str, dict[str, Any]] = dict(CONTRACT["capabilities"])
CONTRACT_VERSION: str = str(CONTRACT["version"])


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def safe(value: object, *, limit: int = 256) -> str:
    return acn_meta.safe_report_text(value, limit=limit)


def state_root() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".local" / "state"
    return base / "beastmode"


def harness_binary() -> Path:
    """`scripts/bm`, or BM_GOAL_HARNESS_BIN (absolute, owner-executable) for tests."""
    override = os.environ.get("BM_GOAL_HARNESS_BIN")
    if not override:
        return SCRIPTS_DIR / "bm"
    path = Path(override)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise LifecycleError(f"BM_GOAL_HARNESS_BIN must be an absolute executable file (got: {safe(override)})")
    return path


def _secure_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def atomic_write_text(path: Path, body: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    _fsync_dir(path.parent)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def read_json(path: Path, *, limit: int = 4 * 1024 * 1024) -> Any:
    if path.is_symlink():
        raise LifecycleError(f"refusing symlinked record: {safe(path)}")
    size = path.stat().st_size
    if size > limit:
        raise LifecycleError(f"record exceeds {limit} bytes: {safe(path)}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_control_json(path: Path) -> dict[str, Any] | None:
    """Read a worker-writable control file with bounded trust."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        body = read_json(path, limit=MAX_CONTROL_BYTES)
    except (OSError, ValueError, LifecycleError):
        return None
    return body if isinstance(body, dict) else None


def validate_goal_id(goal_id: str) -> str:
    if not isinstance(goal_id, str) or not GOAL_ID_RE.fullmatch(goal_id):
        raise LifecycleError(f"invalid goal id: {safe(goal_id)}")
    return goal_id


def new_goal_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"g{stamp}-{secrets.token_hex(3)}"


def contract_digest(goal: str, *, harness: str, autonomy: str, seats: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {
            "goal": " ".join(goal.split()),
            "harness": harness,
            "autonomy": autonomy,
            "seats": {key: seats.get(key) for key in sorted(seats)},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def git_head(worktree: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = proc.stdout.strip()
    return revision if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", revision) else None


def git_dirty(worktree: Path) -> bool | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return bool(proc.stdout.strip())


def revision_stamp(worktree: Path) -> dict[str, Any]:
    return {"head": git_head(worktree), "dirty": git_dirty(worktree), "recorded_at": now_iso()}


def process_alive(pid: int | None, host: str | None) -> bool | None:
    """True/False when the pid is local and decidable; None when unknowable."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if host and host != socket.gethostname():
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_group_alive(pgid: int | None) -> bool | None:
    if not isinstance(pgid, int) or pgid <= 0:
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _last_event_seq(path: Path) -> int:
    """Highest seq in an append-only events file, reading only its tail."""
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    if size == 0:
        return 0
    with path.open("rb") as handle:
        handle.seek(max(0, size - MAX_CONTROL_BYTES))
        tail = handle.read().decode("utf-8", "replace")
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            seq = json.loads(line).get("seq")
        except (ValueError, AttributeError):
            continue
        if isinstance(seq, int):
            return seq
    return 0


class GoalStore:
    def __init__(self, root: Path | None = None):
        self.base = root or state_root()
        self.goals = self.base / "goals"
        self.locks = self.base / "locks"

    # -- paths ---------------------------------------------------------------

    def goal_dir(self, goal_id: str) -> Path:
        return self.goals / validate_goal_id(goal_id)

    def attempt_dir(self, goal_id: str, attempt_id: str) -> Path:
        if not ATTEMPT_ID_RE.fullmatch(attempt_id):
            raise LifecycleError(f"invalid attempt id: {safe(attempt_id)}")
        return self.goal_dir(goal_id) / "attempts" / attempt_id

    def repo_lock_path(self, repo: Path) -> Path:
        digest = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:24]
        return self.locks / f"{digest}.lock"

    # -- records -------------------------------------------------------------

    def exists(self, goal_id: str) -> bool:
        return (self.goal_dir(goal_id) / "goal.json").is_file()

    def load(self, goal_id: str) -> dict[str, Any]:
        path = self.goal_dir(goal_id) / "goal.json"
        if not path.is_file():
            raise LifecycleError(f"unknown goal: {safe(goal_id)}", EXIT_USAGE)
        goal = read_json(path)
        if not isinstance(goal, dict) or goal.get("goal_id") != goal_id:
            raise LifecycleError(f"corrupt goal record: {safe(path)}", EXIT_CONFLICT)
        return goal

    def save(self, goal: Mapping[str, Any]) -> None:
        goal_dir = self.goal_dir(str(goal["goal_id"]))
        _secure_mkdir(goal_dir)
        atomic_write_json(goal_dir / "goal.json", goal)

    def create(self, goal: dict[str, Any]) -> dict[str, Any]:
        goal_dir = self.goal_dir(str(goal["goal_id"]))
        if goal_dir.exists():
            raise LifecycleError(f"goal already exists: {safe(goal['goal_id'])}", EXIT_CONFLICT)
        _secure_mkdir(self.goals)
        _secure_mkdir(goal_dir)
        _secure_mkdir(goal_dir / "attempts")
        goal["last_event_seq"] = 0
        self.save(goal)
        self.record_event(goal, "created", to_state=goal["state"], actor=goal.get("created_by"))
        return goal

    def list_ids(self) -> list[str]:
        if not self.goals.is_dir():
            return []
        ids = []
        for entry in sorted(self.goals.iterdir()):
            if entry.is_dir() and GOAL_ID_RE.fullmatch(entry.name) and (entry / "goal.json").is_file():
                ids.append(entry.name)
        return ids

    def list_goals(self) -> list[dict[str, Any]]:
        goals = []
        for goal_id in self.list_ids():
            try:
                goals.append(self.load(goal_id))
            except LifecycleError as exc:
                goals.append({"goal_id": goal_id, "state": "corrupt", "reason": str(exc)})
        goals.sort(key=lambda g: str(g.get("updated_at") or ""), reverse=True)
        return goals

    # -- events --------------------------------------------------------------

    def events_path(self, goal_id: str) -> Path:
        return self.goal_dir(goal_id) / "events.jsonl"

    def record_event(
        self,
        goal: dict[str, Any],
        event_type: str,
        *,
        from_state: str | None = None,
        to_state: str | None = None,
        reason: str | None = None,
        actor: str | None = None,
        attempt_id: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "seq": 0,
            "ts": now_iso(),
            "type": event_type,
            "goal_id": goal["goal_id"],
            "attempt_id": attempt_id or goal.get("current_attempt"),
            "from": from_state,
            "to": to_state,
            "reason": reason,
            "actor": actor or default_actor(),
            "data": dict(data or {}),
        }
        path = self.events_path(goal["goal_id"])
        # The file, not the caller's snapshot, is the sequence authority: an
        # operator's `cancel` and the supervisor append from different
        # processes, so the next seq is read under an exclusive lock.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            seq = _last_event_seq(path) + 1
            event["seq"] = seq
            line = json.dumps(event, sort_keys=True, default=str) + "\n"
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        goal["last_event_seq"] = seq
        goal["updated_at"] = event["ts"]
        self.save(goal)
        return event

    def events(self, goal_id: str) -> list[dict[str, Any]]:
        path = self.events_path(goal_id)
        if not path.is_file():
            return []
        events = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    body = json.loads(line)
                except ValueError:
                    events.append({"seq": None, "type": "corrupt_event", "raw": safe(line)})
                    continue
                if isinstance(body, dict):
                    events.append(body)
        return events

    # -- transitions ---------------------------------------------------------

    def transition(
        self,
        goal: dict[str, Any],
        to_state: str,
        *,
        reason: str | None = None,
        outcome: str | None = None,
        actor: str | None = None,
        attempt_id: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        from_state = str(goal.get("state"))
        if to_state not in STATES:
            raise LifecycleError(f"unknown state: {safe(to_state)}", EXIT_CONFLICT)
        if to_state not in TRANSITIONS.get(from_state, ()):
            raise LifecycleError(
                f"illegal transition {from_state} -> {to_state} for goal {goal['goal_id']}",
                EXIT_CONFLICT,
            )
        goal["state"] = to_state
        goal["reason"] = reason
        if outcome is not None or to_state in ("running", "queued"):
            goal["outcome"] = outcome
        self.record_event(
            goal,
            "transition",
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            actor=actor,
            attempt_id=attempt_id,
            data=dict(data or {}, outcome=outcome) if outcome else data,
        )
        return goal


def default_actor() -> str:
    return os.environ.get("BM_ACTOR") or os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------


class FileLock:
    """flock-backed exclusive lock whose owner metadata survives for inspection."""

    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def acquire(self, owner: Mapping[str, Any]) -> bool:
        _secure_mkdir(self.path.parent)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps(dict(owner), sort_keys=True, default=str).encode("utf-8"))
        os.fsync(fd)
        self.fd = fd
        return True

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            os.ftruncate(self.fd, 0)
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None

    def holder(self) -> dict[str, Any] | None:
        """Return the recorded owner when the lock is currently held."""
        if not self.path.is_file():
            return None
        fd = os.open(self.path, os.O_RDWR)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raw = os.read(fd, MAX_CONTROL_BYTES)
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except ValueError:
                    body = {}
                return body if isinstance(body, dict) else {}
            fcntl.flock(fd, fcntl.LOCK_UN)
            return None
        finally:
            os.close(fd)


# ---------------------------------------------------------------------------
# Run argument parsing
# ---------------------------------------------------------------------------


def split_bm_args(argv: Sequence[str]) -> tuple[list[str], dict[str, str], str]:
    """Separate bm passthrough flags from goal text; mirror scripts/bm's grammar."""
    passthrough: list[str] = []
    values: dict[str, str] = {}
    goal_parts: list[str] = []
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--":
            goal_parts.extend(args)
            break
        if arg in BM_VALUE_FLAGS:
            if not args:
                raise LifecycleError(f"{arg} needs a value")
            value = args.pop(0)
            values[arg] = value
            passthrough.extend([arg, value])
        elif arg.startswith("--") and "=" in arg and arg.split("=", 1)[0] in BM_VALUE_FLAGS:
            flag, value = arg.split("=", 1)
            values[flag] = value
            passthrough.extend([flag, value])
        elif arg in BM_BOOL_FLAGS:
            passthrough.append(arg)
        elif arg.startswith("-"):
            raise LifecycleError(f"unknown arg: {safe(arg)}")
        else:
            goal_parts.append(arg)
    goal = " ".join(part for part in goal_parts if part).strip()
    return passthrough, values, goal


def _parse_run_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bm goal run", add_help=True, allow_abbrev=False)
    parser.add_argument("--goal-id", default=None)
    parser.add_argument("--repo", default=None, help="target worktree (default: cwd)")
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--stall-seconds", type=float, default=DEFAULT_STALL_SECONDS)
    parser.add_argument("--verify-cmd", action="append", default=[])
    parser.add_argument("--expect", default=None, help="expected child ids (a,b or batch.json)")
    parser.add_argument("--attestations", default=None, help="parent-owned trusted attestations")
    parser.add_argument("--allow-empty-children", action="store_true")
    parser.add_argument("--notify-cmd", default=None, help="command run with the completion record on stdin")
    parser.add_argument("--queue-only", action="store_true", help="create the record without starting")
    parser.add_argument("--from-template", default=None, help="copy goal text, seats, budget and acceptance from an existing goal")
    parser.add_argument("--occurrence", default=None, help="with --from-template: suffix for the fresh goal id (dedup key)")
    parser.add_argument("--json", action="store_true")
    known, rest = parser.parse_known_args(list(argv))
    known.bm_args = rest
    return known


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


class Supervisor:
    """Own one attempt of one goal from spawn to recorded outcome."""

    def __init__(self, store: GoalStore, goal: dict[str, Any], *, bm_path: Path | None = None):
        self.store = store
        self.goal = goal
        self.bm_path = bm_path or harness_binary()
        self.cancel_requested = False
        self.kill_reason: str | None = None
        self.child: subprocess.Popen[bytes] | None = None
        self._stop = threading.Event()

    # -- helpers -------------------------------------------------------------

    @property
    def goal_id(self) -> str:
        return str(self.goal["goal_id"])

    @property
    def worktree(self) -> Path:
        return Path(self.goal["worktree"])

    @property
    def harness(self) -> str:
        return str(self.goal["harness"])

    def _cancel_flag(self) -> Path:
        return self.store.goal_dir(self.goal_id) / "control" / "cancel.json"

    def _next_attempt_id(self) -> str:
        return f"a{len(self.goal.get('attempts') or []) + 1}"

    def _terminate_child(self, reason: str, grace: float = DEFAULT_GRACE_SECONDS) -> None:
        self.kill_reason = self.kill_reason or reason
        child = self.child
        if child is None or child.poll() is not None:
            return
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + grace
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _on_signal(self, signum: int, _frame: Any) -> None:
        self.cancel_requested = True
        self._terminate_child(f"signal {signum}")

    # -- attempt -------------------------------------------------------------

    def run_attempt(self, *, resume_mode: str | None = None, decisions: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
        goal = self.goal
        attempt_id = self._next_attempt_id()
        attempt_dir = self.store.attempt_dir(self.goal_id, attempt_id)
        run_dir = attempt_dir / "run"
        _secure_mkdir(run_dir)
        # Workers write receipts and control files here; the parent never
        # treats their contents as trusted evidence on their own.
        run_dir.chmod(0o700)
        _secure_mkdir(run_dir / "control")
        if decisions:
            atomic_write_json(run_dir / "control" / "decisions.json", {"decisions": list(decisions)})
        log_path = attempt_dir / "harness.log"
        started = now_iso()
        attempt = {
            "attempt_id": attempt_id,
            "goal_id": self.goal_id,
            "started_at": started,
            "finished_at": None,
            "supervisor_pid": os.getpid(),
            "pid": None,
            "pgid": None,
            "host": socket.gethostname(),
            "heartbeat_at": started,
            "exit_code": None,
            "outcome": None,
            "resume_mode": resume_mode,
            "run_dir": str(run_dir),
            "log": str(log_path),
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "start_revision": revision_stamp(self.worktree),
        }
        atomic_write_json(attempt_dir / "attempt.json", attempt)
        goal.setdefault("attempts", []).append(attempt_id)
        goal["current_attempt"] = attempt_id
        goal["supervisor"] = {"pid": os.getpid(), "host": attempt["host"], "started_at": started}
        self.store.transition(
            goal,
            "running",
            reason="attempt started" if resume_mode is None else f"resumed ({resume_mode})",
            actor=default_actor(),
            attempt_id=attempt_id,
            data={"resume_mode": resume_mode},
        )

        # The attestation key is parent-held evidence; a harness that sees it
        # could sign its own provenance.
        env = {k: v for k, v in os.environ.items() if k not in ("BEASTMODE_ATTESTATION_KEY", "BEASTMODE_ATTESTATION_RUN_ID")}
        env.update(
            {
                "BM_GOAL_ID": self.goal_id,
                "BM_ATTEMPT_ID": attempt_id,
                "BM_RUN_DIR": str(run_dir),
                "BM_LIFECYCLE_SUMMARY": str(attempt_dir / "harness-summary.json"),
                "BM_LANGGRAPH_DB": str(self.store.goal_dir(self.goal_id) / "langgraph.sqlite"),
            }
        )
        if resume_mode == "checkpoint" and decisions:
            env["BM_RESUME"] = json.dumps(_langgraph_resume_value(decisions[-1]))
        argv = [str(self.bm_path), *goal.get("bm_args", []), "--", str(goal["goal"])]

        previous = {
            sig: signal.signal(sig, self._on_signal) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
        }
        outcome_hint: str | None = None
        exit_code: int | None = None
        try:
            with log_path.open("ab") as log:
                try:
                    self.child = subprocess.Popen(
                        argv,
                        cwd=str(self.worktree),
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                except OSError as exc:
                    outcome_hint = "infrastructure_failed"
                    log.write(f"bm goal: cannot start harness: {exc}\n".encode("utf-8"))
                if self.child is not None:
                    attempt["pid"] = self.child.pid
                    attempt["pgid"] = self.child.pid
                    atomic_write_json(attempt_dir / "attempt.json", attempt)
                    self.store.record_event(goal, "harness_started", attempt_id=attempt_id, data={"pid": self.child.pid})
                    exit_code = self._wait(attempt, attempt_dir, run_dir, log_path)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)

        attempt["exit_code"] = exit_code
        attempt["finished_at"] = now_iso()
        attempt["usage"] = _usage_from_run_dir(run_dir)
        atomic_write_json(attempt_dir / "attempt.json", attempt)
        goal.setdefault("budget", {}).setdefault("used", {})
        used = goal["budget"]["used"]
        used["attempts"] = len(goal["attempts"])
        used["tokens"] = int(used.get("tokens") or 0) + attempt["usage"]["input_tokens"] + attempt["usage"]["output_tokens"]
        used["seconds"] = round(float(used.get("seconds") or 0) + _elapsed(attempt), 3)

        outcome, detail = self._classify(attempt, run_dir, attempt_dir, exit_code, outcome_hint)
        attempt["outcome"] = outcome
        atomic_write_json(attempt_dir / "attempt.json", attempt)
        self._apply_outcome(attempt, outcome, detail)
        goal["supervisor"] = None
        self.store.save(goal)
        return attempt

    def _wait(self, attempt: dict[str, Any], attempt_dir: Path, run_dir: Path, log_path: Path) -> int | None:
        assert self.child is not None
        budget = self.goal.get("budget") or {}
        max_seconds = budget.get("max_seconds")
        stall_seconds = budget.get("stall_seconds") or DEFAULT_STALL_SECONDS
        started = time.monotonic()
        last_activity = started
        last_signature: tuple[int, float] | None = None
        while True:
            code = self.child.poll()
            if code is not None:
                return code
            time.sleep(min(HEARTBEAT_SECONDS, 0.25))
            now = time.monotonic()
            signature = _activity_signature(log_path, run_dir)
            if signature != last_signature:
                last_signature = signature
                last_activity = now
            if self._cancel_flag().is_file():
                self.cancel_requested = True
                self._terminate_child("cancel requested")
            elif max_seconds and now - started > float(max_seconds):
                self._terminate_child("budget_exhausted")
            elif stall_seconds and now - last_activity > float(stall_seconds):
                self._terminate_child("stalled")
            attempt["heartbeat_at"] = now_iso()
            try:
                atomic_write_json(attempt_dir / "attempt.json", attempt)
            except OSError:
                pass

    # -- classification ------------------------------------------------------

    def _classify(
        self,
        attempt: dict[str, Any],
        run_dir: Path,
        attempt_dir: Path,
        exit_code: int | None,
        hint: str | None,
    ) -> tuple[str, dict[str, Any]]:
        if hint:
            return hint, {"reason": "harness could not be started"}
        if self.cancel_requested:
            alive = process_group_alive(attempt.get("pgid"))
            cleanup = "confirmed" if alive is False else "uncertain"
            return "cancelled", {"reason": self.kill_reason or "cancelled", "cleanup": cleanup}
        if self.kill_reason in ("budget_exhausted", "stalled"):
            return self.kill_reason, {"reason": self.kill_reason}
        summary = read_control_json(attempt_dir / "harness-summary.json") if self.harness == "langgraph" else None
        gate = self._pending_gate(run_dir, attempt, summary)
        if gate is not None:
            return "awaiting_approval", {"gate": gate}
        if exit_code is None:
            return "infrastructure_failed", {"reason": "harness exit status unknown"}
        if exit_code in (126, 127):
            return "infrastructure_failed", {"reason": f"harness exit {exit_code}"}
        if exit_code == EXIT_BREAKER:
            return "harness_failed", {"reason": "bm breaker refused the run", "exit_code": exit_code}
        if exit_code != 0:
            return "harness_failed", {"reason": f"harness exit {exit_code}", "exit_code": exit_code}
        return self._accept(attempt, run_dir, attempt_dir, summary)

    def _pending_gate(
        self, run_dir: Path, attempt: Mapping[str, Any], summary: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        if summary and summary.get("interrupt"):
            interrupt = summary["interrupt"]
            first = interrupt[0] if isinstance(interrupt, list) and interrupt else interrupt
            payload = first if isinstance(first, Mapping) else {"value": first}
            return {
                "gate": safe(payload.get("gate") or "langgraph"),
                "phase": safe(payload.get("phase") or ""),
                "question": safe(payload.get("question") or f"approve {safe(payload.get('gate') or 'gate')} gate", limit=1024),
                "options": ["approved", "rejected"],
                "source": "langgraph_interrupt",
            }
        gate_path = run_dir / "control" / "gate.json"
        body = read_control_json(gate_path)
        if body is None:
            return None
        try:
            if gate_path.stat().st_mtime < _parse_iso(attempt["started_at"]) - 1:
                return None
        except (OSError, ValueError):
            return None
        options = body.get("options")
        return {
            "gate": safe(body.get("gate") or "gate"),
            "phase": safe(body.get("phase") or ""),
            "question": safe(body.get("question") or "approve to continue", limit=1024),
            "options": [safe(item) for item in options[:8]] if isinstance(options, list) else ["approved", "rejected"],
            "recommended": safe(body.get("recommended") or ""),
            "source": "control/gate.json",
        }

    def _accept(
        self,
        attempt: dict[str, Any],
        run_dir: Path,
        attempt_dir: Path,
        summary: Mapping[str, Any] | None,
    ) -> tuple[str, dict[str, Any]]:
        goal = self.goal
        revision = revision_stamp(self.worktree)
        acceptance = goal.get("acceptance") or {}
        validation = _run_verify_commands(acceptance.get("verify_cmds") or [], self.worktree)
        provenance = _provenance(run_dir, acceptance, summary)
        review = _review(run_dir, goal, attempt, revision, provenance, summary)
        record = {
            "version": CONTRACT_VERSION,
            "goal_id": self.goal_id,
            "attempt_id": attempt["attempt_id"],
            "contract_digest": goal["contract_digest"],
            "revision": revision,
            "validation": validation,
            "provenance": provenance,
            "review": review,
            "recorded_at": now_iso(),
        }
        if not validation["passed"]:
            record["outcome"] = "validation_failed"
        elif provenance["verdict"] != "ok":
            record["outcome"] = "provenance_failed"
        elif not review["approved"]:
            record["outcome"] = "review_missing"
        else:
            record["outcome"] = "succeeded"
        atomic_write_json(attempt_dir / "result.json", record)
        return record["outcome"], {"result": str(attempt_dir / "result.json"), "record": record}

    def _apply_outcome(self, attempt: Mapping[str, Any], outcome: str, detail: Mapping[str, Any]) -> None:
        goal = self.goal
        attempt_id = str(attempt["attempt_id"])
        actor = "supervisor"
        if outcome == "succeeded":
            goal["completion"] = detail["record"]
            self.store.transition(goal, "succeeded", reason="acceptance record written", outcome=outcome, actor=actor, attempt_id=attempt_id, data={"result": detail["result"]})
        elif outcome == "awaiting_approval":
            decision_id = f"d{len(goal.get('decisions') or []) + 1}"
            pending = dict(detail["gate"])
            pending.update(
                {
                    "id": decision_id,
                    "attempt_id": attempt_id,
                    "revision": revision_stamp(self.worktree),
                    "contract_digest": goal["contract_digest"],
                    "requested_at": now_iso(),
                }
            )
            goal["pending_decision"] = pending
            self.store.transition(goal, "awaiting_approval", reason=pending["question"], outcome=outcome, actor=actor, attempt_id=attempt_id, data={"decision": decision_id, "gate": pending["gate"]})
        elif outcome == "cancelled":
            self.store.transition(goal, "cancelled", reason=str(detail.get("reason")), outcome=outcome, actor=actor, attempt_id=attempt_id, data={"cleanup": detail.get("cleanup")})
        elif outcome in ("review_missing", "budget_exhausted"):
            self.store.transition(goal, "blocked", reason=_outcome_reason(outcome, detail), outcome=outcome, actor=actor, attempt_id=attempt_id, data=_detail_data(detail))
        else:
            self.store.transition(goal, "failed", reason=_outcome_reason(outcome, detail), outcome=outcome, actor=actor, attempt_id=attempt_id, data=_detail_data(detail))
        _notify(self.store, goal, attempt, outcome)


def _detail_data(detail: Mapping[str, Any]) -> dict[str, Any]:
    data = {key: value for key, value in detail.items() if key != "record"}
    record = detail.get("record")
    if isinstance(record, Mapping):
        data["validation_passed"] = record["validation"]["passed"]
        data["provenance_verdict"] = record["provenance"]["verdict"]
        data["review_approved"] = record["review"]["approved"]
    return data


def _outcome_reason(outcome: str, detail: Mapping[str, Any]) -> str:
    record = detail.get("record")
    if isinstance(record, Mapping):
        if outcome == "validation_failed":
            failures = [f for f in record["validation"]["commands"] if f.get("exit_code") != 0]
            return f"{len(failures)} verify command(s) failed at {record['revision'].get('head')}"
        if outcome == "provenance_failed":
            return "; ".join(record["provenance"].get("messages") or [record["provenance"]["verdict"]])[:1024]
        if outcome == "review_missing":
            return str(record["review"].get("reason") or "no bound watcher review")
    return str(detail.get("reason") or outcome)


def _elapsed(attempt: Mapping[str, Any]) -> float:
    try:
        return max(0.0, _parse_iso(str(attempt["finished_at"])) - _parse_iso(str(attempt["started_at"])))
    except (KeyError, ValueError, TypeError):
        return 0.0


def _parse_iso(value: str) -> float:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


def _activity_signature(log_path: Path, run_dir: Path) -> tuple[int, float]:
    size = 0
    newest = 0.0
    try:
        size = log_path.stat().st_size
    except OSError:
        pass
    try:
        for dirpath, _dirs, files in os.walk(run_dir):
            for name in files:
                try:
                    newest = max(newest, os.stat(os.path.join(dirpath, name)).st_mtime)
                except OSError:
                    continue
    except OSError:
        pass
    return size, newest


def _usage_from_run_dir(run_dir: Path) -> dict[str, int]:
    totals = {"input_tokens": 0, "output_tokens": 0}
    try:
        rows = acn_meta.load_rows(run_dir)
    except (OSError, ValueError, acn_meta.MetadataLimitError):
        return totals
    for row in rows:
        for key, raw in (("input_tokens", row.input_tokens), ("output_tokens", row.output_tokens)):
            try:
                totals[key] += int(raw)
            except (TypeError, ValueError):
                continue
    return totals


def _langgraph_resume_value(decision: Mapping[str, Any]) -> Any:
    return "approved" if decision.get("approved") is True else {"approved": False}


def _run_verify_commands(commands: Sequence[str], worktree: Path) -> dict[str, Any]:
    results = []
    passed = True
    for command in commands:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            results.append({"command": command, "exit_code": None, "error": f"unparseable: {exc}"})
            passed = False
            continue
        if not argv:
            continue
        try:
            proc = subprocess.run(
                argv,
                cwd=str(worktree),
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            entry = {
                "command": command,
                "exit_code": proc.returncode,
                "stdout_tail": safe(proc.stdout[-2000:], limit=2048),
                "stderr_tail": safe(proc.stderr[-2000:], limit=2048),
            }
            passed = passed and proc.returncode == 0
        except (OSError, subprocess.SubprocessError) as exc:
            entry = {"command": command, "exit_code": None, "error": safe(exc)}
            passed = False
        results.append(entry)
    return {"passed": passed, "commands": results, "count": len(results)}


def _provenance(run_dir: Path, acceptance: Mapping[str, Any], summary: Mapping[str, Any] | None) -> dict[str, Any]:
    if summary is not None:
        verdict = summary.get("provenance_verdict")
        verdict = verdict if verdict in ("ok", "drift", "unverifiable") else "unverifiable"
        return {
            "verdict": verdict,
            "source": "langgraph_runner",
            "messages": [safe(m, limit=1024) for m in (summary.get("provenance_messages") or [])[:32]],
            "ok_children": [safe(c) for c in (summary.get("ok_children") or [])[:acn_meta.MAX_META_FILES]],
        }
    attestations = acceptance.get("attestations")
    key = run_id = None
    if attestations:
        try:
            key, run_id = acn_meta.attestation_credentials_from_environment()
        except acn_meta.MetadataLimitError as exc:
            return {"verdict": "unverifiable", "source": "acn_meta", "messages": [f"UNVERIFIABLE: {safe(exc)}"], "ok_children": []}
    expect = acceptance.get("expect")
    try:
        expected = acn_meta.expected_ids(expect) if expect else None
    except (OSError, ValueError) as exc:
        return {"verdict": "unverifiable", "source": "acn_meta", "messages": [f"UNVERIFIABLE: --expect: {safe(exc)}"], "ok_children": []}
    result = acn_meta.check(
        run_dir,
        allow_empty=bool(acceptance.get("allow_empty_children")),
        strict=True,
        expect=expected,
        attestations=Path(attestations) if attestations else None,
        attestation_key=key,
        attestation_run_id=run_id,
    )
    if result.exit_code == 0:
        verdict = "ok"
    elif any(row.status == acn_meta.DRIFT for row in result.rows):
        verdict = "drift"
    else:
        verdict = "unverifiable"
    return {
        "verdict": verdict,
        "source": "acn_meta",
        "exit_code": result.exit_code,
        "messages": [safe(m, limit=1024) for m in result.messages],
        "ok_children": [row.raw_id for row in result.rows if row.status == acn_meta.OK],
        "child_count": len(result.rows),
    }


def _review(
    run_dir: Path,
    goal: Mapping[str, Any],
    attempt: Mapping[str, Any],
    revision: Mapping[str, Any],
    provenance: Mapping[str, Any],
    summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if summary is not None:
        report = summary.get("review_report")
        approved = isinstance(report, Mapping) and report.get("approved") is True
        return {
            "approved": bool(approved),
            "source": "langgraph_runner",
            "reason": None if approved else safe((report or {}).get("reason") if isinstance(report, Mapping) else "no trusted review report"),
        }
    body = read_control_json(run_dir / "control" / "review.json")
    if body is None:
        return {"approved": False, "source": "control/review.json", "reason": "no watcher review recorded; no watcher, no validated"}
    head = revision.get("head")
    checks = {
        "goal_id": body.get("goal_id") == goal["goal_id"],
        "attempt_id": body.get("attempt_id") == attempt["attempt_id"],
        "revision": bool(head) and body.get("revision") == head,
        "approved": body.get("approved") is True,
        "reviewer_proven": str(body.get("reviewer_id") or "") in set(provenance.get("ok_children") or []),
    }
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "approved": not failed,
        "source": "control/review.json",
        "reviewer_id": safe(body.get("reviewer_id") or ""),
        "summary": safe(body.get("summary") or "", limit=1024),
        "reason": None if not failed else f"review not bound: {', '.join(failed)}",
    }


def _notify(store: GoalStore, goal: dict[str, Any], attempt: Mapping[str, Any], outcome: str) -> None:
    """Best-effort, deduplicated notification hook; the durable record stays the source of truth.

    One notification per (attempt, outcome). Delivery is retried a bounded number
    of times and both delivery and failure are recorded as events, so an operator
    can see that a notification never arrived. A notification can never approve.
    """
    command = (goal.get("notify") or {}).get("command")
    if not command:
        return
    notification_id = f"{goal['goal_id']}:{attempt['attempt_id']}:{outcome}"
    sent = goal.setdefault("notifications", [])
    if notification_id in sent:
        return
    payload = json.dumps(
        {
            "notification_id": notification_id,
            "goal_id": goal["goal_id"],
            "attempt_id": attempt["attempt_id"],
            "state": goal["state"],
            "outcome": outcome,
            "reason": goal.get("reason"),
            "goal": goal["goal"],
            "event_seq": goal.get("last_event_seq"),
        },
        sort_keys=True,
        default=str,
    )
    last_error = None
    for _ in range(NOTIFY_RETRIES):
        try:
            completed = subprocess.run(shlex.split(str(command)), input=payload, text=True, timeout=60, check=False, capture_output=True)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            last_error = safe(exc, limit=512)
            continue
        if completed.returncode == 0:
            sent.append(notification_id)
            store.record_event(goal, "notified", attempt_id=attempt["attempt_id"], data={"notification_id": notification_id})
            return
        last_error = f"exit {completed.returncode}: {safe(completed.stderr, limit=512)}"
    store.record_event(
        goal,
        "notification_failed",
        attempt_id=attempt["attempt_id"],
        reason=last_error,
        data={"notification_id": notification_id, "retries": NOTIFY_RETRIES},
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _capability(harness: str, name: str) -> Any:
    caps = CAPABILITIES.get(harness)
    if caps is None:
        raise LifecycleError(f"unknown harness for lifecycle: {safe(harness)}", EXIT_USAGE)
    return caps.get(name)


def _run_supervised(store: GoalStore, goal: dict[str, Any], *, resume_mode: str | None, decisions: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    goal_lock = FileLock(store.goal_dir(goal["goal_id"]) / "supervisor.lock")
    owner = {"goal_id": goal["goal_id"], "pid": os.getpid(), "host": socket.gethostname(), "since": now_iso()}
    if not goal_lock.acquire(owner):
        raise LifecycleError(f"another supervisor owns goal {goal['goal_id']}", EXIT_CONFLICT)
    repo_lock = FileLock(store.repo_lock_path(Path(goal["worktree"])))
    try:
        if not repo_lock.acquire(owner):
            holder = repo_lock.holder() or {}
            raise LifecycleError(
                f"repository {goal['worktree']} is locked by goal {safe(holder.get('goal_id'))} (pid {safe(holder.get('pid'))})",
                EXIT_CONFLICT,
            )
        try:
            return Supervisor(store, goal).run_attempt(resume_mode=resume_mode, decisions=decisions)
        finally:
            repo_lock.release()
    finally:
        goal_lock.release()


def cmd_run(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    args = _parse_run_args(argv)
    if args.from_template:
        return _run_occurrence(store, args, out)
    bm_args, values, goal_text = split_bm_args(args.bm_args)
    if not goal_text:
        raise LifecycleError("bm goal run needs a goal")
    if len(goal_text) > MAX_GOAL_TEXT:
        raise LifecycleError(f"goal text exceeds {MAX_GOAL_TEXT} characters")
    harness = values.get("--harness", "pi")
    autonomy = values.get("--autonomy", "medium")
    if harness not in CAPABILITIES:
        raise LifecycleError(f"--harness must be one of {', '.join(sorted(CAPABILITIES))} (got: {safe(harness)})")
    if autonomy not in ("low", "medium", "high"):
        raise LifecycleError(f"--autonomy must be low|medium|high (got: {safe(autonomy)})")
    if values.get("--on") not in (None, "auto", "local"):
        raise LifecycleError("bm goal run supervises local processes only; remote dispatch has no verifiable cancellation", EXIT_UNSUPPORTED)
    if args.max_attempts < 1 or args.max_attempts > 20:
        raise LifecycleError("--max-attempts must be between 1 and 20")
    worktree = Path(args.repo or os.getcwd()).resolve()
    if git_head(worktree) is None:
        raise LifecycleError(f"{worktree} is not a git worktree with a HEAD commit")
    if args.attestations:
        attestation_path = Path(args.attestations).expanduser().resolve()
        if worktree in attestation_path.parents or attestation_path == worktree:
            raise LifecycleError("--attestations must live outside the target worktree", EXIT_BREAKER)
    seats = {"frontier": values.get("--frontier"), "economy": values.get("--economy", "luna-max"), "watcher": values.get("--watcher")}
    goal_id = validate_goal_id(args.goal_id) if args.goal_id else new_goal_id()
    goal = {
        "version": CONTRACT_VERSION,
        "goal_id": goal_id,
        "goal": goal_text,
        "contract_digest": contract_digest(goal_text, harness=harness, autonomy=autonomy, seats=seats),
        "repo": str(worktree),
        "worktree": str(worktree),
        "harness": harness,
        "autonomy": autonomy,
        "seats": seats,
        "bm_args": bm_args,
        "capabilities": CAPABILITIES[harness],
        "state": "queued",
        "outcome": None,
        "reason": "queued",
        "created_at": now_iso(),
        "created_by": default_actor(),
        "updated_at": None,
        "base_revision": revision_stamp(worktree),
        "current_attempt": None,
        "attempts": [],
        "budget": {
            "max_attempts": args.max_attempts,
            "max_seconds": args.max_seconds,
            "max_tokens": args.max_tokens,
            "stall_seconds": args.stall_seconds,
            "used": {"attempts": 0, "seconds": 0, "tokens": 0},
        },
        "acceptance": {
            "verify_cmds": list(args.verify_cmd),
            "expect": args.expect,
            "attestations": str(Path(args.attestations).expanduser().resolve()) if args.attestations else None,
            "allow_empty_children": bool(args.allow_empty_children),
        },
        "notify": {"command": args.notify_cmd} if args.notify_cmd else {},
        "pending_decision": None,
        "decisions": [],
        "completion": None,
        "supervisor": None,
    }
    store.create(goal)
    if args.queue_only:
        out(_render(goal, args.json, f"queued {goal_id}"))
        return EXIT_OK
    _run_supervised(store, goal, resume_mode=None)
    goal = store.load(goal_id)
    out(_render(goal, args.json, _summary_line(goal)))
    return STATE_EXIT.get(str(goal["state"]), EXIT_FAILED)


def _run_occurrence(store: GoalStore, args: argparse.Namespace, out: Callable[[str], None]) -> int:
    """A recurring schedule creates a fresh goal per intended occurrence.

    The template goal is never executed itself; `<template>-<occurrence>` is the
    deduplication key (a repeated trigger for the same occurrence exits 7) and
    the repository lock turns overlapping occurrences into an explicit reject.
    """
    if args.bm_args:
        raise LifecycleError("--from-template takes no goal text or bm flags; edit the template goal instead")
    if not args.occurrence:
        raise LifecycleError("--from-template needs --occurrence <token>")
    template = store.load(args.from_template)
    goal_id = validate_goal_id(f"{template['goal_id']}-{args.occurrence}")
    if store.exists(goal_id):
        raise LifecycleError(f"occurrence {goal_id} already exists; not starting a duplicate", EXIT_CONFLICT)
    worktree = Path(template["worktree"])
    if git_head(worktree) is None:
        raise LifecycleError(f"{worktree} is not a git worktree with a HEAD commit")
    goal = {
        key: copy.deepcopy(template[key])
        for key in ("version", "goal", "contract_digest", "repo", "worktree", "harness", "autonomy", "seats", "bm_args", "capabilities", "budget", "acceptance", "notify")
    }
    goal["budget"]["used"] = {"attempts": 0, "seconds": 0, "tokens": 0}
    goal.update(
        {
            "goal_id": goal_id,
            "template": template["goal_id"],
            "occurrence": args.occurrence,
            "state": "queued",
            "outcome": None,
            "reason": "queued",
            "created_at": now_iso(),
            "created_by": default_actor(),
            "updated_at": None,
            "base_revision": revision_stamp(worktree),
            "current_attempt": None,
            "attempts": [],
            "pending_decision": None,
            "decisions": [],
            "completion": None,
            "supervisor": None,
        }
    )
    store.create(goal)
    store.record_event(template, "occurrence_created", data={"goal_id": goal_id, "occurrence": args.occurrence})
    if args.queue_only:
        out(_render(goal, args.json, f"queued {goal_id}"))
        return EXIT_OK
    _run_supervised(store, goal, resume_mode=None)
    goal = store.load(goal_id)
    out(_render(goal, args.json, _summary_line(goal)))
    return STATE_EXIT.get(str(goal["state"]), EXIT_FAILED)


def cmd_runs(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    parser = argparse.ArgumentParser(prog="bm goal runs", allow_abbrev=False)
    parser.add_argument("--state", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    goals = [g for g in store.list_goals() if not args.state or g.get("state") == args.state]
    for goal in goals:
        if goal.get("state") == "running":
            goal["liveness"] = _liveness(store, goal)
    if args.json:
        out(json.dumps([_public(g) for g in goals], indent=2, sort_keys=True, default=str))
        return EXIT_OK
    if not goals:
        out("no goals recorded")
        return EXIT_OK
    out(f"{'GOAL':<24} {'STATE':<18} {'ATTEMPT':<8} {'HARNESS':<10} {'UPDATED':<28} GOAL TEXT")
    for goal in goals:
        text = safe(goal.get("goal") or "", limit=60)
        state = str(goal.get("state"))
        if goal.get("liveness") and goal["liveness"].get("alive") is False:
            state = f"{state} (supervisor lost)"
        out(f"{goal['goal_id']:<24} {state:<18} {str(goal.get('current_attempt') or '-'):<8} {str(goal.get('harness') or '-'):<10} {str(goal.get('updated_at') or '-'):<28} {text}")
    return EXIT_OK


def cmd_inspect(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    parser = argparse.ArgumentParser(prog="bm goal inspect", allow_abbrev=False)
    parser.add_argument("goal_id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    goal = store.load(args.goal_id)
    goal["events"] = store.events(args.goal_id)
    goal["attempt_records"] = [_load_attempt(store, args.goal_id, a) for a in goal.get("attempts") or []]
    goal["liveness"] = _liveness(store, goal)
    events_ahead = goal["events"][-1]["seq"] if goal["events"] else 0
    goal["consistency"] = {"events_ahead_of_record": bool(events_ahead and events_ahead != goal.get("last_event_seq"))}
    if args.json:
        out(json.dumps(_public(goal), indent=2, sort_keys=True, default=str))
        return EXIT_OK
    lines = [
        f"goal:      {goal['goal_id']}",
        f"text:      {safe(goal['goal'], limit=512)}",
        f"state:     {goal['state']}" + (f" ({goal.get('outcome')})" if goal.get("outcome") else ""),
        f"reason:    {safe(goal.get('reason') or '', limit=1024)}",
        f"harness:   {goal['harness']}  autonomy: {goal['autonomy']}  seats: {json.dumps(goal.get('seats'), sort_keys=True)}",
        f"worktree:  {goal['worktree']}",
        f"base rev:  {(goal.get('base_revision') or {}).get('head')}",
        f"attempts:  {len(goal.get('attempts') or [])}/{(goal.get('budget') or {}).get('max_attempts')}  current: {goal.get('current_attempt') or '-'}",
        f"budget:    {json.dumps((goal.get('budget') or {}).get('used'), sort_keys=True)}",
        f"liveness:  {json.dumps(goal['liveness'], sort_keys=True)}",
        f"resume:    {goal['capabilities'].get('resume')}",
    ]
    pending = goal.get("pending_decision")
    if pending:
        lines.append(f"pending:   {pending['id']} [{pending.get('gate')}] {pending.get('question')} options={pending.get('options')} bound to {pending.get('attempt_id')}@{(pending.get('revision') or {}).get('head')}")
    completion = goal.get("completion")
    if completion:
        lines.append(f"complete:  attempt {completion['attempt_id']} at {completion['revision'].get('head')} validation={completion['validation']['passed']} provenance={completion['provenance']['verdict']} review={completion['review']['approved']}")
    for record in goal["attempt_records"]:
        lines.append(
            f"  {record.get('attempt_id')}: {record.get('outcome') or 'in progress'} exit={record.get('exit_code')} started={record.get('started_at')} finished={record.get('finished_at') or '-'} resume={record.get('resume_mode') or '-'} usage={json.dumps(record.get('usage'))}"
        )
    lines.append("events:")
    for event in goal["events"][-25:]:
        arrow = f"{event.get('from')} -> {event.get('to')}" if event.get("to") else ""
        lines.append(f"  #{event.get('seq')} {event.get('ts')} {event.get('type')} {arrow} {safe(event.get('reason') or '', limit=200)}")
    out("\n".join(lines))
    return EXIT_OK


def cmd_logs(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    parser = argparse.ArgumentParser(prog="bm goal logs", allow_abbrev=False)
    parser.add_argument("goal_id")
    parser.add_argument("--attempt", default=None)
    parser.add_argument("--tail", type=int, default=200)
    args = parser.parse_args(list(argv))
    goal = store.load(args.goal_id)
    attempt_id = args.attempt or goal.get("current_attempt")
    if not attempt_id:
        out("no attempt has run yet")
        return EXIT_OK
    log = store.attempt_dir(args.goal_id, attempt_id) / "harness.log"
    if not log.is_file():
        out(f"no log for attempt {attempt_id}")
        return EXIT_OK
    tail = max(1, min(args.tail, MAX_LOG_TAIL))
    with log.open("rb") as handle:
        lines = handle.read().splitlines()[-tail:]
    out("\n".join(safe(line.decode("utf-8", "replace"), limit=4096) for line in lines))
    return EXIT_OK


def cmd_approve(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    parser = argparse.ArgumentParser(prog="bm goal approve", allow_abbrev=False)
    parser.add_argument("goal_id")
    parser.add_argument("--decision", default=None)
    parser.add_argument("--answer", action="append", default=[])
    parser.add_argument("--actor", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    goal = store.load(args.goal_id)
    pending = _require_pending(goal, args.decision)
    answers = {}
    for item in args.answer:
        if "=" not in item:
            raise LifecycleError("--answer must be KEY=VALUE")
        key, value = item.split("=", 1)
        answers[safe(key, limit=64)] = safe(value, limit=1024)
    decision = _record_decision(store, goal, pending, approved=True, actor=args.actor, answers=answers)
    out(_render(goal, args.json, f"approved {decision['id']} for {goal['goal_id']} (bound to {decision['attempt_id']}@{(decision.get('revision') or {}).get('head')}); run `bm goal resume {goal['goal_id']}`"))
    return EXIT_OK


def cmd_reject(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    parser = argparse.ArgumentParser(prog="bm goal reject", allow_abbrev=False)
    parser.add_argument("goal_id")
    parser.add_argument("--decision", default=None)
    parser.add_argument("--reason", default="rejected by operator")
    parser.add_argument("--actor", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    goal = store.load(args.goal_id)
    pending = _require_pending(goal, args.decision)
    decision = _record_decision(store, goal, pending, approved=False, actor=args.actor, answers={"reason": safe(args.reason, limit=1024)})
    store.transition(goal, "failed", reason=safe(args.reason, limit=1024), outcome="rejected", actor=args.actor, data={"decision": decision["id"]})
    out(_render(goal, args.json, f"rejected {decision['id']}; goal {goal['goal_id']} is failed (rejected)"))
    return EXIT_OK


def cmd_pause(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    parser = argparse.ArgumentParser(prog="bm goal pause", allow_abbrev=False)
    parser.add_argument("goal_id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    goal = store.load(args.goal_id)
    if goal["state"] == "running":
        if not _capability(goal["harness"], "pause_running"):
            raise LifecycleError(
                f"harness {goal['harness']} cannot pause a running attempt; use `bm goal cancel` or wait for its next gate",
                EXIT_UNSUPPORTED,
            )
    store.transition(goal, "paused", reason="paused by operator")
    out(_render(goal, args.json, f"paused {goal['goal_id']}"))
    return EXIT_OK


def cmd_resume(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    parser = argparse.ArgumentParser(prog="bm goal resume", allow_abbrev=False)
    parser.add_argument("goal_id")
    parser.add_argument("--restart", action="store_true", help="start a new attempt for a failed/blocked goal")
    parser.add_argument("--acknowledge-partial-effects", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    goal = store.load(args.goal_id)
    state = str(goal["state"])
    if state == "paused":
        store.transition(goal, "queued", reason="unpaused by operator")
        _run_supervised(store, goal, resume_mode=None)
    elif state == "awaiting_approval":
        decision = _latest_decision(goal)
        pending = goal.get("pending_decision")
        if decision is None or pending is None or decision.get("id") != pending.get("id") or decision.get("approved") is not True:
            raise LifecycleError(
                f"goal {goal['goal_id']} has no approved decision; run `bm goal approve {goal['goal_id']}` first",
                EXIT_CONFLICT,
            )
        _check_decision_binding(store, goal, decision)
        mode = str(_capability(goal["harness"], "resume"))
        goal["pending_decision"] = None
        _run_supervised(store, goal, resume_mode=mode, decisions=[d for d in goal["decisions"] if d.get("approved")])
    elif state in ("failed", "blocked"):
        if not args.restart:
            raise LifecycleError(
                f"goal {goal['goal_id']} is {state} ({goal.get('outcome')}); a new attempt is a restart, not a resume. Re-run with --restart",
                EXIT_CONFLICT,
            )
        _check_budget(goal)
        if goal.get("outcome") not in RETRYABLE_OUTCOMES and not args.acknowledge_partial_effects:
            raise LifecycleError(
                f"outcome {goal.get('outcome')} is not retryable automatically; the worktree may hold partial effects. Re-run with --acknowledge-partial-effects",
                EXIT_CONFLICT,
            )
        _run_supervised(store, goal, resume_mode="restart")
    else:
        raise LifecycleError(f"goal {goal['goal_id']} is {state}; nothing to resume", EXIT_CONFLICT)
    goal = store.load(args.goal_id)
    out(_render(goal, args.json, _summary_line(goal)))
    return STATE_EXIT.get(str(goal["state"]), EXIT_FAILED)


def cmd_cancel(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    parser = argparse.ArgumentParser(prog="bm goal cancel", allow_abbrev=False)
    parser.add_argument("goal_id")
    parser.add_argument("--grace-seconds", type=float, default=DEFAULT_GRACE_SECONDS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    goal = store.load(args.goal_id)
    state = str(goal["state"])
    if state in TERMINAL_STATES:
        raise LifecycleError(f"goal {goal['goal_id']} is already {state}", EXIT_CONFLICT)
    if state != "running":
        store.transition(goal, "cancelled", reason="cancelled by operator", outcome="cancelled", data={"cleanup": "confirmed"})
        out(_render(goal, args.json, f"cancelled {goal['goal_id']}"))
        return EXIT_OK
    control = store.goal_dir(goal["goal_id"]) / "control"
    _secure_mkdir(control)
    atomic_write_json(control / "cancel.json", {"requested_at": now_iso(), "actor": default_actor()})
    store.record_event(goal, "cancel_requested", reason="cancel requested by operator")
    attempt = _load_attempt(store, goal["goal_id"], str(goal.get("current_attempt")))
    pgid = attempt.get("pgid")
    alive = process_group_alive(pgid if isinstance(pgid, int) else None)
    if alive:
        try:
            os.killpg(int(pgid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + max(0.0, args.grace_seconds) + 5.0
    while time.monotonic() < deadline:
        goal = store.load(args.goal_id)
        if goal["state"] != "running":
            break
        time.sleep(0.2)
    if goal["state"] == "running":
        # The supervisor did not record the cancellation itself (it may be
        # gone). Record it here with the honest cleanup verdict.
        if alive and process_group_alive(int(pgid)):
            try:
                os.killpg(int(pgid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            time.sleep(0.2)
        cleanup = "confirmed" if process_group_alive(pgid if isinstance(pgid, int) else None) is False else "uncertain"
        store.transition(goal, "cancelled", reason="cancelled by operator (supervisor did not acknowledge)", outcome="cancelled", data={"cleanup": cleanup})
    out(_render(goal, args.json, f"cancelled {goal['goal_id']} (cleanup: {_last_cleanup(store, goal)})"))
    return EXIT_OK


def cmd_reconcile(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    parser = argparse.ArgumentParser(prog="bm goal reconcile", allow_abbrev=False)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    findings = []
    for goal in store.list_goals():
        if goal.get("state") != "running":
            continue
        liveness = _liveness(store, goal)
        if liveness.get("alive") is not False:
            continue
        attempt_id = str(goal.get("current_attempt"))
        attempt = _load_attempt(store, goal["goal_id"], attempt_id)
        run_dir = Path(attempt.get("run_dir") or store.attempt_dir(goal["goal_id"], attempt_id) / "run")
        receipts = len(acn_meta.find_meta_files(run_dir)) if run_dir.is_dir() else 0
        # An unsupervised harness keeps mutating the worktree with nobody to
        # record it; stop it, then say honestly whether that worked.
        pgid = attempt.get("pgid")
        harness_alive = process_group_alive(pgid if isinstance(pgid, int) else None)
        cleanup = "confirmed"
        if harness_alive:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(int(pgid), sig)
                except (ProcessLookupError, PermissionError):
                    break
                time.sleep(0.5)
                if not process_group_alive(int(pgid)):
                    break
            cleanup = "confirmed" if process_group_alive(int(pgid)) is False else "uncertain"
        elif harness_alive is None:
            cleanup = "uncertain"
        effects = {
            "receipts": receipts,
            "harness_was_running": harness_alive,
            "cleanup": cleanup,
            "revision_before": (attempt.get("start_revision") or {}).get("head"),
            "revision_now": git_head(Path(goal["worktree"])),
            "worktree_dirty": git_dirty(Path(goal["worktree"])),
        }
        attempt["outcome"] = "supervisor_lost"
        attempt["finished_at"] = attempt.get("finished_at") or now_iso()
        atomic_write_json(store.attempt_dir(goal["goal_id"], attempt_id) / "attempt.json", attempt)
        goal["supervisor"] = None
        store.transition(
            goal,
            "failed",
            reason="supervisor process is gone; effects recorded for review",
            outcome="supervisor_lost",
            actor="reconcile",
            attempt_id=attempt_id,
            data={"effects": effects, "liveness": liveness, "cleanup": cleanup},
        )
        findings.append({"goal_id": goal["goal_id"], "attempt_id": attempt_id, "effects": effects})
    if args.json:
        out(json.dumps(findings, indent=2, sort_keys=True, default=str))
    elif findings:
        for finding in findings:
            out(f"{finding['goal_id']}: attempt {finding['attempt_id']} marked supervisor_lost; effects={json.dumps(finding['effects'], sort_keys=True)}")
    else:
        out("nothing to reconcile")
    return EXIT_OK


def _cron_interval(every_seconds: int) -> str:
    """Five-field cron schedule for a recurring interval (rounded to cron's grid)."""
    minutes = max(1, every_seconds // 60)
    if minutes < 60:
        return f"*/{minutes} * * * *"
    hours = minutes // 60
    if hours < 24:
        return f"0 */{hours} * * *"
    days = max(1, hours // 24)
    return f"0 0 */{min(days, 28)} * *"


def cmd_schedule(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    """Export an OS-scheduler entry; Beastmode owns no scheduler daemon.

    `--at` resumes this goal once. `--every` treats this goal as a template and
    starts a fresh `<goal>-<UTC minute>` occurrence each trigger. Policies are
    fixed and recorded: triggers are UTC, overlap is rejected by the repository
    lock (exit 7), a repeated trigger for the same occurrence is a no-op duplicate
    (exit 7), and missed triggers are skipped (cron) or coalesced (launchd).
    """
    parser = argparse.ArgumentParser(prog="bm goal schedule", allow_abbrev=False)
    parser.add_argument("goal_id")
    parser.add_argument("--at", default=None, help="ISO-8601 UTC time for a single run")
    parser.add_argument("--every", type=int, default=None, help="interval in seconds for a recurring run")
    parser.add_argument("--export", choices=("cron", "launchd", "json"), default="json")
    args = parser.parse_args(list(argv))
    goal = store.load(args.goal_id)
    if goal["state"] not in ("queued", "paused"):
        raise LifecycleError(f"only queued or paused goals can be scheduled (goal is {goal['state']})", EXIT_CONFLICT)
    if bool(args.at) == bool(args.every):
        raise LifecycleError("choose exactly one of --at or --every")
    if args.every is not None and args.every < 60:
        raise LifecycleError("--every must be at least 60 seconds")
    when = None
    if args.at:
        try:
            when = datetime.fromisoformat(args.at.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError as exc:
            raise LifecycleError(f"--at must be ISO-8601: {exc}") from exc
    bm_goal = str(SCRIPTS_DIR / "bm-goal")
    if when:
        argv_out = [bm_goal, "resume", goal["goal_id"]]
        command = " ".join(shlex.quote(part) for part in argv_out)
    else:
        argv_out = [bm_goal, "run", "--from-template", goal["goal_id"], "--occurrence"]
        command = " ".join(shlex.quote(part) for part in argv_out) + ' "$(date -u +%Y%m%dT%H%M)"'
    schedule = {
        "goal_id": goal["goal_id"],
        "mode": "one_shot_resume" if when else "recurring_template",
        "command": command,
        "at": when.isoformat() if when else None,
        "at_local": when.astimezone().isoformat() if when else None,
        "every_seconds": args.every,
        "timezone": "UTC",
        "overlap_policy": "reject (repository lock, exit 7)",
        "duplicate_policy": "reject (goal id per occurrence, exit 7)",
        "missed_trigger_policy": {"cron": "skip", "launchd": "coalesce on wake"},
        "note": "the scheduler only invokes bm-goal, so every approval, provenance and review gate still applies",
    }
    goal["schedule"] = schedule
    store.record_event(goal, "scheduled", reason="schedule exported", data=schedule)
    env_prefix = f"XDG_STATE_HOME={shlex.quote(str(store.base.parent))}"
    if args.export == "cron":
        out("CRON_TZ=UTC")
        if when:
            out(f"{when.minute} {when.hour} {when.day} {when.month} * {env_prefix} {command}")
        else:
            out(f"{_cron_interval(args.every)} {env_prefix} {command}")
    elif args.export == "launchd":
        label = f"ai.beastmode.goal.{goal['goal_id']}"
        plist = {
            "Label": label,
            "ProgramArguments": argv_out if when else ["/bin/sh", "-c", command],
            "EnvironmentVariables": {"XDG_STATE_HOME": str(store.base.parent)},
        }
        if when:
            local = when.astimezone()
            plist["StartCalendarInterval"] = {"Minute": local.minute, "Hour": local.hour, "Day": local.day, "Month": local.month}
            plist["Comment"] = f"launchd calendar intervals are host-local; {when.isoformat()} rendered for {local.tzname()}"
        else:
            plist["StartInterval"] = args.every
        out(json.dumps(plist, indent=2, sort_keys=True))
    else:
        out(json.dumps(schedule, indent=2, sort_keys=True))
    return EXIT_OK


def cmd_capabilities(_store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    parser = argparse.ArgumentParser(prog="bm goal capabilities", allow_abbrev=False)
    parser.parse_args(list(argv))
    out(json.dumps({"version": CONTRACT_VERSION, "capabilities": CAPABILITIES, "exit_codes": CONTRACT["exit_codes"], "states": STATES, "transitions": TRANSITIONS}, indent=2, sort_keys=True))
    return EXIT_OK


def cmd_harvest(store: GoalStore, argv: Sequence[str], out: Callable[[str], None]) -> int:
    """Learning harvest: propose skill/config changes from durable records, for review only.

    Reads terminal goals and writes a Markdown proposal. It never edits skills,
    prompts, budgets or goals; an operator applies (or discards) the proposal.
    """
    parser = argparse.ArgumentParser(prog="bm goal harvest", allow_abbrev=False)
    parser.add_argument("--since", default=None, help="ISO-8601 UTC; only goals updated at/after this time")
    parser.add_argument("--out", default=None, help="write the proposal here (default: stdout)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError as exc:
            raise LifecycleError(f"--since must be ISO-8601: {exc}") from exc
    goals = [g for g in store.list_goals() if g.get("state") in TERMINAL_STATES | {"failed", "blocked"}]
    if since is not None:
        goals = [g for g in goals
                 if (updated := _parse_iso_lenient(g.get("updated_at"))) is not None and updated >= since]
    report = _harvest(goals)
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str) if args.json else _render_harvest(report)
    if args.out:
        target = Path(args.out)
        if target.exists() and not target.is_file():
            raise LifecycleError(f"--out must be a regular file path: {safe(str(target))}")
        atomic_write_text(target, rendered + ("\n" if not rendered.endswith("\n") else ""))
        out(f"harvest proposal written to {target} ({report['goals_examined']} goals; review before applying)")
    else:
        out(rendered)
    return EXIT_OK


def _parse_iso_lenient(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _harvest(goals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    outcomes: dict[str, int] = {}
    by_harness: dict[str, dict[str, int]] = {}
    proposals: list[dict[str, Any]] = []
    seen: set[str] = set()

    def propose(kind: str, target: str, text: str, evidence: str) -> None:
        key = f"{kind}:{target}:{text}"
        if key in seen:
            return
        seen.add(key)
        proposals.append({"kind": kind, "target": target, "proposal": safe(text, limit=400), "evidence": safe(evidence, limit=200)})

    for goal in goals:
        outcome = str(goal.get("outcome") or goal.get("state") or "unknown")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        harness = str(goal.get("harness") or "unknown")
        by_harness.setdefault(harness, {})
        by_harness[harness][outcome] = by_harness[harness].get(outcome, 0) + 1
        gid = str(goal.get("goal_id"))
        budget = goal.get("budget") or {}
        used = budget.get("used") or {}
        if outcome == "budget_exhausted":
            propose("config", "budget", f"attempt/time budget exhausted for {harness}; review --max-attempts/--max-seconds defaults or split the goal", gid)
        if outcome in ("provenance_failed", "model_drift"):
            propose("skill", "model routing", f"{harness} produced a provenance {outcome}; pin executor models or add an attestor for this seat", gid)
        if outcome == "review_missing":
            propose("skill", "watcher prompt", f"{harness} finished without a revision-bound watcher review; strengthen the lifecycle prompt's review.json instruction", gid)
        if outcome == "validation_failed":
            propose("skill", "verify-cmd", f"verification failed for {harness}; consider running the verify commands earlier in the phase prompt", gid)
        if outcome == "stalled":
            propose("config", "stall-seconds", f"{harness} stalled past the heartbeat budget; review --stall-seconds or the harness liveness output", gid)
        if int(used.get("attempts") or 0) > 1 and outcome == "succeeded":
            propose("skill", "gates", f"{gid} needed {used.get('attempts')} attempts to succeed; capture the recorded decisions as defaults", gid)
    return {
        "generated_at": now_iso(),
        "goals_examined": len(goals),
        "outcomes": outcomes,
        "by_harness": by_harness,
        "proposals": proposals,
        "applies_changes": False,
    }


def _render_harvest(report: Mapping[str, Any]) -> str:
    lines = [
        "# Beastmode learning harvest (proposal — review before applying)",
        "",
        f"Generated {report['generated_at']} from {report['goals_examined']} terminal/blocked goal record(s).",
        "This file is advisory: nothing here has been applied to skills, prompts or budgets.",
        "",
        "## Outcomes",
        "",
    ]
    for outcome, count in sorted(report["outcomes"].items()):
        lines.append(f"- {outcome}: {count}")
    lines += ["", "## By harness", ""]
    for harness, counts in sorted(report["by_harness"].items()):
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        lines.append(f"- {harness}: {summary}")
    lines += ["", "## Proposed changes", ""]
    if not report["proposals"]:
        lines.append("- none: no recurring failure pattern in the examined records")
    for item in report["proposals"]:
        lines.append(f"- [{item['kind']}] {item['target']}: {item['proposal']} (evidence: {item['evidence']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command helpers
# ---------------------------------------------------------------------------


def _require_pending(goal: Mapping[str, Any], decision_id: str | None) -> dict[str, Any]:
    if goal.get("state") != "awaiting_approval" or not isinstance(goal.get("pending_decision"), Mapping):
        raise LifecycleError(f"goal {goal['goal_id']} is {goal.get('state')}; nothing awaits approval", EXIT_CONFLICT)
    pending = dict(goal["pending_decision"])
    if decision_id is not None and decision_id != pending.get("id"):
        raise LifecycleError(f"pending decision is {pending.get('id')}, not {safe(decision_id)}", EXIT_CONFLICT)
    return pending


def _record_decision(
    store: GoalStore,
    goal: dict[str, Any],
    pending: Mapping[str, Any],
    *,
    approved: bool,
    actor: str | None,
    answers: Mapping[str, str],
) -> dict[str, Any]:
    if any(d.get("id") == pending.get("id") for d in goal.get("decisions") or []):
        raise LifecycleError(f"decision {pending.get('id')} was already recorded", EXIT_CONFLICT)
    decision = {
        "id": pending["id"],
        "gate": pending.get("gate"),
        "question": pending.get("question"),
        "approved": approved,
        "answers": dict(answers),
        "actor": actor or default_actor(),
        "decided_at": now_iso(),
        "attempt_id": pending.get("attempt_id"),
        "revision": pending.get("revision"),
        "contract_digest": pending.get("contract_digest"),
    }
    goal.setdefault("decisions", []).append(decision)
    store.record_event(goal, "decision", reason="approved" if approved else "rejected", actor=decision["actor"], data={"decision": decision["id"], "approved": approved})
    return decision


def _latest_decision(goal: Mapping[str, Any]) -> dict[str, Any] | None:
    decisions = goal.get("decisions") or []
    return dict(decisions[-1]) if decisions else None


def _check_decision_binding(store: GoalStore, goal: dict[str, Any], decision: Mapping[str, Any]) -> None:
    problems = []
    if decision.get("contract_digest") != goal.get("contract_digest"):
        problems.append("contract digest changed")
    if decision.get("attempt_id") != goal.get("current_attempt"):
        problems.append("attempt changed")
    bound = (decision.get("revision") or {}).get("head")
    head = git_head(Path(goal["worktree"]))
    if bound and head != bound:
        problems.append(f"worktree moved from {bound} to {head}")
    if problems:
        store.record_event(goal, "approval_stale", reason="; ".join(problems), data={"decision": decision.get("id")})
        raise LifecycleError(
            f"approval {decision.get('id')} is stale ({'; '.join(problems)}); inspect the goal and approve again after the harness re-raises its gate",
            EXIT_CONFLICT,
        )


def _check_budget(goal: Mapping[str, Any]) -> None:
    budget = goal.get("budget") or {}
    used = budget.get("used") or {}
    if len(goal.get("attempts") or []) >= int(budget.get("max_attempts") or 1):
        raise LifecycleError(
            f"attempt budget exhausted ({len(goal.get('attempts') or [])}/{budget.get('max_attempts')}); the goal stays {goal['state']}",
            EXIT_CONFLICT,
        )
    max_tokens = budget.get("max_tokens")
    if max_tokens and int(used.get("tokens") or 0) >= int(max_tokens):
        raise LifecycleError("token budget exhausted", EXIT_CONFLICT)
    max_seconds = budget.get("max_seconds")
    if max_seconds and float(used.get("seconds") or 0) >= float(max_seconds):
        raise LifecycleError("time budget exhausted", EXIT_CONFLICT)


def _load_attempt(store: GoalStore, goal_id: str, attempt_id: str) -> dict[str, Any]:
    path = store.attempt_dir(goal_id, attempt_id) / "attempt.json"
    try:
        body = read_json(path)
    except (OSError, ValueError, LifecycleError):
        return {"attempt_id": attempt_id, "corrupt": True}
    if not isinstance(body, dict):
        return {"attempt_id": attempt_id, "corrupt": True}
    try:
        result = read_json(store.attempt_dir(goal_id, attempt_id) / "result.json")
    except (OSError, ValueError, LifecycleError):
        result = None
    if isinstance(result, dict):
        body["acceptance"] = result
    return body


def _liveness(store: GoalStore, goal: Mapping[str, Any]) -> dict[str, Any]:
    supervisor = goal.get("supervisor") or {}
    attempt_id = goal.get("current_attempt")
    attempt = _load_attempt(store, goal["goal_id"], str(attempt_id)) if attempt_id else {}
    lock = FileLock(store.goal_dir(goal["goal_id"]) / "supervisor.lock")
    holder = lock.holder()
    alive: bool | None
    if goal.get("state") != "running":
        alive = None
    elif holder is not None:
        alive = True
    else:
        alive = process_alive(supervisor.get("pid"), supervisor.get("host"))
    return {
        "alive": alive,
        "supervisor_pid": supervisor.get("pid"),
        "host": supervisor.get("host"),
        "lock_holder": holder,
        "heartbeat_at": attempt.get("heartbeat_at"),
        "harness_pid": attempt.get("pid"),
    }


def _last_cleanup(store: GoalStore, goal: Mapping[str, Any]) -> str:
    for event in reversed(store.events(goal["goal_id"])):
        cleanup = (event.get("data") or {}).get("cleanup")
        if cleanup:
            return str(cleanup)
    return "unknown"


def _summary_line(goal: Mapping[str, Any]) -> str:
    line = f"{goal['goal_id']}: {goal['state']}"
    if goal.get("outcome"):
        line += f" ({goal['outcome']})"
    if goal.get("reason"):
        line += f" — {safe(goal['reason'], limit=1024)}"
    pending = goal.get("pending_decision")
    if pending:
        line += f"\n  approve with: bm goal approve {goal['goal_id']}   then: bm goal resume {goal['goal_id']}"
    return line


def _public(goal: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in goal.items() if key != "bm_args"} | {"bm_args": list(goal.get("bm_args") or [])}


def _render(goal: Mapping[str, Any], as_json: bool, text: str) -> str:
    if as_json:
        return json.dumps(_public(goal), indent=2, sort_keys=True, default=str)
    return text


COMMANDS: dict[str, Callable[[GoalStore, Sequence[str], Callable[[str], None]], int]] = {
    "run": cmd_run,
    "runs": cmd_runs,
    "inspect": cmd_inspect,
    "logs": cmd_logs,
    "approve": cmd_approve,
    "reject": cmd_reject,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "cancel": cmd_cancel,
    "reconcile": cmd_reconcile,
    "schedule": cmd_schedule,
    "harvest": cmd_harvest,
    "capabilities": cmd_capabilities,
}

USAGE = """usage: bm goal <command> [args]

commands:
  run <goal> [bm flags] [--max-attempts N] [--max-seconds N] [--max-tokens N]
             [--stall-seconds N] [--verify-cmd CMD]... [--expect IDS|batch.json]
             [--attestations PATH] [--notify-cmd CMD] [--queue-only] [--json]
  runs [--state S] [--json]        list recorded goals
  inspect <goal-id> [--json]       state, budget, decisions, evidence, events
  logs <goal-id> [--attempt a<n>] [--tail N]
  approve <goal-id> [--decision d<n>] [--answer K=V]...
  reject <goal-id> [--reason TEXT]
  pause <goal-id>                  hold a queued goal
  resume <goal-id> [--restart] [--acknowledge-partial-effects]
  cancel <goal-id> [--grace-seconds N]
  reconcile [--json]               mark goals whose supervisor died
  schedule <goal-id> --at ISO|--every SECONDS [--export cron|launchd|json]
           (--every treats the goal as a template: each trigger starts a fresh
            <goal-id>-<UTC minute> occurrence via run --from-template)
  run --from-template <goal-id> --occurrence TOKEN [--queue-only]
  harvest [--since ISO] [--out FILE] [--json]
                                   propose skill/config changes from records (never applies)
  capabilities                     print the harness capability matrix

exit codes: 0 ok/succeeded, 1 failed/blocked, 2 usage, 3 breaker, 4 awaiting approval,
            5 cancelled, 6 unsupported for harness, 7 conflict/stale approval
"""


def main(argv: Sequence[str] | None = None, *, out: Callable[[str], None] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    emit = out or (lambda text: print(text))
    if not args or args[0] in ("-h", "--help", "help"):
        emit(USAGE)
        return EXIT_OK if args else EXIT_USAGE
    command = args.pop(0)
    handler = COMMANDS.get(command)
    if handler is None:
        print(f"bm goal: unknown command: {safe(command)}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    try:
        return handler(GoalStore(), args, emit)
    except LifecycleError as exc:
        print(f"bm goal: {exc}", file=sys.stderr)
        return exc.exit_code
    except SystemExit as exc:  # argparse
        code = exc.code
        return EXIT_USAGE if code not in (0, None) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
