"""Checkpoint and invocation helpers for Beastmode's LangGraph binding."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
import errno
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any, AsyncIterator, Iterator, Mapping

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from .context import BeastmodeContext
from .gates import _is_approved
from .graphs.pipeline import build_pipeline
from .limits import validate_concurrency, validate_executor_result
from .nodes import PipelineDependencies


DEFAULT_CHECKPOINT_HISTORY_LIMIT = 100
MAX_CHECKPOINT_HISTORY_LIMIT = 1_000


@contextmanager
def sqlite_checkpointer(path: Path) -> Iterator[SqliteSaver]:
    """Open the local checkpointer and initialize its tables."""
    with _secure_sqlite_connection(path) as connection:
        saver = SqliteSaver(connection)
        saver.setup()
        yield saver


@contextmanager
def postgres_checkpointer(connection_string: str) -> Iterator[Any]:
    """Open the opt-in synchronous PostgreSQL checkpointer."""
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Postgres persistence is optional; install beastmode[postgres]"
        ) from exc
    with PostgresSaver.from_conn_string(connection_string) as saver:
        saver.setup()
        yield saver


@asynccontextmanager
async def async_postgres_checkpointer(connection_string: str) -> AsyncIterator[Any]:
    """Open the opt-in asynchronous PostgreSQL checkpointer."""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Async PostgreSQL persistence is optional; install beastmode[postgres]"
        ) from exc
    async with AsyncPostgresSaver.from_conn_string(connection_string) as saver:
        await saver.setup()
        yield saver


def durability_for(autonomy: str) -> str:
    """Gate-bearing runs checkpoint synchronously; high may opt into exit."""
    return "exit" if autonomy == "high" else "sync"


@asynccontextmanager
async def async_sqlite_checkpointer(path: Path) -> AsyncIterator[Any]:
    """Open a non-hanging async checkpoint backend.

    Set ``BEASTMODE_NATIVE_ASYNC_SQLITE=1`` to select LangGraph's native
    ``AsyncSqliteSaver``.  Some restricted Python hosts cannot start the
    aiosqlite worker thread; the default uses the synchronous saver while the
    graph remains on LangGraph's async ``ainvoke`` path, preserving durable
    behavior instead of hanging a goal.  PostgreSQL deployments can provide a
    true async saver through their own checkpointer injection.
    """
    if os.environ.get("BEASTMODE_NATIVE_ASYNC_SQLITE") == "1":
        import aiosqlite

        with _secure_sqlite_fd(path) as database_fd:
            connection = await aiosqlite.connect(
                _sqlite_fd_uri(database_fd), uri=True, check_same_thread=False
            )
            try:
                await connection.execute("PRAGMA journal_mode=MEMORY")
                saver = AsyncSqliteSaver(connection)
                await saver.setup()
                yield saver
            finally:
                await connection.close()
        return
    with sqlite_checkpointer(path) as saver:
        yield saver


def run_pipeline(
    initial_state: Mapping[str, Any] | Command,
    *,
    goal_id: str,
    autonomy: str = "medium",
    database: Path,
    run_dir: Path | None = None,
    attestations: Path | None = None,
    dependencies: PipelineDependencies | None = None,
    resume: Any = None,
) -> dict[str, Any]:
    """Run or resume with trusted run and attestation paths kept out of state."""
    trusted_run_dir = _trusted_run_dir(run_dir)
    trusted_attestations = _trusted_attestations_path(
        attestations, run_dir=trusted_run_dir
    )
    dependencies = dependencies or PipelineDependencies()
    payload = _pipeline_payload(
        initial_state,
        goal_id=goal_id,
        run_dir=trusted_run_dir,
        resume=resume,
    )
    config = _run_config(goal_id, payload)
    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=dependencies, checkpointer=saver)
        context = BeastmodeContext(
            autonomy=autonomy,
            goal_id=goal_id,
            run_dir=trusted_run_dir,
            attestations=trusted_attestations,
        )
        result = graph.invoke(
            payload,
            config=config,
            context=context,
            durability=durability_for(autonomy),
        )
    return _finalize_merge(result, dependencies)


async def arun_pipeline(
    initial_state: Mapping[str, Any] | Command,
    *,
    goal_id: str,
    autonomy: str = "medium",
    database: Path,
    run_dir: Path | None = None,
    attestations: Path | None = None,
    dependencies: PipelineDependencies | None = None,
    resume: Any = None,
) -> dict[str, Any]:
    """Async-first counterpart to :func:`run_pipeline`."""
    trusted_run_dir = _trusted_run_dir(run_dir)
    trusted_attestations = _trusted_attestations_path(
        attestations, run_dir=trusted_run_dir
    )
    dependencies = dependencies or PipelineDependencies()
    payload = _pipeline_payload(
        initial_state,
        goal_id=goal_id,
        run_dir=trusted_run_dir,
        resume=resume,
    )
    config = _run_config(goal_id, payload)
    async with async_sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=dependencies, checkpointer=saver)
        context = BeastmodeContext(
            autonomy=autonomy,
            goal_id=goal_id,
            run_dir=trusted_run_dir,
            attestations=trusted_attestations,
        )
        if os.environ.get("BEASTMODE_NATIVE_ASYNC_SQLITE") == "1":
            result = await graph.ainvoke(
                payload,
                config=config,
                context=context,
                durability=durability_for(autonomy),
            )
        else:
            # SqliteSaver intentionally rejects aget_tuple/aput.  Keep this
            # compatibility fallback in the owning event-loop thread.
            result = graph.invoke(
                payload,
                config=config,
                context=context,
                durability=durability_for(autonomy),
            )
    return _finalize_merge(result, dependencies)


def checkpoint_history(
    *,
    database: Path,
    goal_id: str,
    dependencies: PipelineDependencies | None = None,
    limit: int | None = DEFAULT_CHECKPOINT_HISTORY_LIMIT,
) -> list[Any]:
    """Return durable snapshots for a goal, newest first."""
    bounded_limit = _checkpoint_history_limit(limit)
    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=dependencies, checkpointer=saver)
        config = {"configurable": {"thread_id": goal_id}}
        return list(graph.get_state_history(config, limit=bounded_limit))


def replay_from_checkpoint(
    *,
    database: Path,
    goal_id: str,
    checkpoint_id: str,
    new_goal_id: str | None = None,
    autonomy: str = "medium",
    run_dir: Path | None = None,
    attestations: Path | None = None,
    dependencies: PipelineDependencies | None = None,
) -> dict[str, Any]:
    """Replay a goal from a selected checkpoint.

    LangGraph's checkpoint id is intentionally explicit.  With
    ``new_goal_id`` the selected snapshot values seed a separate durable
    thread, leaving the original history untouched; without it LangGraph's
    native same-thread replay is used.  Callers can discover ids with
    :func:`checkpoint_history`.
    """
    trusted_run_dir = _trusted_run_dir(run_dir)
    trusted_attestations = _trusted_attestations_path(
        attestations, run_dir=trusted_run_dir
    )
    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=dependencies, checkpointer=saver)
        original_config = {
            "configurable": {
                "thread_id": goal_id,
                "checkpoint_id": checkpoint_id,
            }
        }
        if new_goal_id:
            snapshot = graph.get_state(original_config)
            return graph.invoke(
                dict(snapshot.values),
                config={"configurable": {"thread_id": new_goal_id}},
                context=BeastmodeContext(
                    autonomy=autonomy,
                    goal_id=new_goal_id,
                    run_dir=trusted_run_dir,
                    attestations=trusted_attestations,
                ),
                durability=durability_for(autonomy),
            )
        return graph.invoke(
            None,
            config=original_config,
            context=BeastmodeContext(
                autonomy=autonomy,
                goal_id=goal_id,
                run_dir=trusted_run_dir,
                attestations=trusted_attestations,
            ),
            durability=durability_for(autonomy),
        )


def _run_config(goal_id: str, initial_state: Mapping[str, Any] | Command) -> dict[str, Any]:
    config: dict[str, Any] = {"configurable": {"thread_id": goal_id}}
    if isinstance(initial_state, Mapping):
        batch = initial_state.get("batch")
        batch = batch if isinstance(batch, Mapping) else {}
        value = (
            initial_state.get("concurrency")
            if "concurrency" in initial_state
            else batch.get("concurrency")
        )
        if value is not None:
            config["max_concurrency"] = validate_concurrency(value)
    return config


def _pipeline_payload(
    initial_state: Mapping[str, Any] | Command,
    *,
    goal_id: str,
    run_dir: Path,
    resume: Any,
) -> Mapping[str, Any] | Command:
    """Bind trusted runtime identity and reject command-based graph jumps."""
    if not isinstance(goal_id, str) or not goal_id or len(goal_id) > 256:
        raise ValueError("goal_id must be a non-empty string no longer than 256 characters")
    if resume is not None:
        return Command(resume=resume)
    if isinstance(initial_state, Command):
        if (
            initial_state.goto
            or initial_state.update is not None
            or initial_state.graph is not None
        ):
            raise ValueError("initial Command may resume only; goto, update, and graph are forbidden")
        if initial_state.resume is None:
            raise ValueError("initial Command must contain a resume value")
        return initial_state
    if not isinstance(initial_state, Mapping):
        raise TypeError("initial_state must be a mapping or a resume-only Command")
    payload = dict(initial_state)
    payload.pop("attestations", None)
    payload["goal_id"] = goal_id
    payload["run_dir"] = str(run_dir)
    return payload


def _trusted_run_dir(run_dir: Path | None) -> Path:
    if run_dir is None:
        raise ValueError("run_dir must be supplied as trusted runtime configuration")
    return Path(run_dir).expanduser().resolve()


def _trusted_attestations_path(
    attestations: Path | None, *, run_dir: Path
) -> Path | None:
    if attestations is None:
        return None
    candidate = Path(attestations).expanduser().absolute()
    if candidate == run_dir or run_dir in candidate.parents:
        raise ValueError(
            "attestations must be outside the worker-writable run_dir"
        )
    source = candidate.resolve()
    if source == run_dir or run_dir in source.parents:
        raise ValueError(
            "attestations must resolve outside the worker-writable run_dir"
        )
    return source


def _checkpoint_history_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_CHECKPOINT_HISTORY_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("checkpoint history limit must be a positive integer")
    if limit > MAX_CHECKPOINT_HISTORY_LIMIT:
        raise ValueError(
            f"checkpoint history limit cannot exceed {MAX_CHECKPOINT_HISTORY_LIMIT}"
        )
    return limit


def _finalize_merge(
    result: Mapping[str, Any], dependencies: PipelineDependencies
) -> dict[str, Any]:
    final = dict(result)
    if final.get("status") != "ready_to_merge":
        return final
    validation = final.get("validation_report")
    review_report = final.get("review_report")
    if (
        final.get("preflight_ok") is not True
        or not isinstance(validation, Mapping)
        or validation.get("passed") is not True
        or final.get("provenance_verdict") != "ok"
        or not isinstance(review_report, Mapping)
        or review_report.get("approved") is not True
        or not _is_approved(final.get("merge_decision"))
    ):
        raise PermissionError("trusted runtime refused an unvalidated merge")
    merge_report: dict[str, Any] = {}
    if dependencies.merger is not None:
        merge_report = validate_executor_result(dependencies.merger(dict(final)))
    final.update(merge_report)
    final["merge_report"] = merge_report
    final["status"] = "merged"
    return final


def _secure_sqlite_path(path: Path) -> Path:
    """Prepare a private parent without opening the database by pathname."""
    database = Path(path).expanduser().absolute()
    _reject_symlink_components(database)
    parent_missing = not database.parent.exists()
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent_missing:
        database.parent.chmod(0o700)
    parent_mode = stat.S_IMODE(database.parent.stat().st_mode)
    if parent_mode & 0o077:
        raise PermissionError("SQLite checkpoint directory must be owner-only (mode 0700)")
    _reject_symlink_components(database)
    return database


@contextmanager
def _secure_sqlite_fd(path: Path) -> Iterator[int]:
    database = _secure_sqlite_path(path)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    parent_fd = os.open(database.parent, directory_flags)
    try:
        parent_stat = os.fstat(parent_fd)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ValueError("SQLite checkpoint parent must be a directory")
        if (
            parent_stat.st_uid != os.geteuid()
            or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise PermissionError(
                "SQLite checkpoint directory must be owned by the current user "
                "and mode 0700"
            )
        file_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        file_flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            database_fd = os.open(database.name, file_flags, 0o600, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                raise ValueError("SQLite checkpoint file must not be a symlink") from exc
            raise
        try:
            database_stat = os.fstat(database_fd)
            if not stat.S_ISREG(database_stat.st_mode):
                raise ValueError("SQLite checkpoint path must be a regular file")
            if database_stat.st_uid != os.geteuid():
                raise PermissionError(
                    "SQLite checkpoint file must be owned by the current user"
                )
            if database_stat.st_nlink != 1:
                raise ValueError("SQLite checkpoint file must not have hard links")
            os.fchmod(database_fd, 0o600)
            yield database_fd
        finally:
            os.close(database_fd)
    finally:
        os.close(parent_fd)


def _sqlite_fd_uri(database_fd: int) -> str:
    descriptor_path = Path("/proc/self/fd") / str(database_fd)
    if not descriptor_path.exists():
        descriptor_path = Path("/dev/fd") / str(database_fd)
    if not descriptor_path.exists():
        raise RuntimeError("secure descriptor-backed SQLite is unavailable on this platform")
    return f"file:{descriptor_path}?mode=rw"


@contextmanager
def _secure_sqlite_connection(path: Path) -> Iterator[sqlite3.Connection]:
    with _secure_sqlite_fd(path) as database_fd:
        connection = sqlite3.connect(
            _sqlite_fd_uri(database_fd), uri=True, check_same_thread=False
        )
        try:
            connection.execute("PRAGMA journal_mode=MEMORY")
            yield connection
        finally:
            connection.close()


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError("SQLite checkpoint path and parents must not be symlinks")
