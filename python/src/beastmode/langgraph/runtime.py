"""Checkpoint and invocation helpers for Beastmode's LangGraph binding."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
import os
from pathlib import Path
import stat
from typing import Any, AsyncIterator, Iterator, Mapping

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from .context import BeastmodeContext
from .graphs.pipeline import build_pipeline
from .limits import validate_concurrency
from .nodes import PipelineDependencies


@contextmanager
def sqlite_checkpointer(path: Path) -> Iterator[SqliteSaver]:
    """Open the local checkpointer and initialize its tables."""
    database = _secure_sqlite_path(path)
    with SqliteSaver.from_conn_string(str(database)) as saver:
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
    database = _secure_sqlite_path(path)
    if os.environ.get("BEASTMODE_NATIVE_ASYNC_SQLITE") == "1":
        async with AsyncSqliteSaver.from_conn_string(str(database)) as saver:
            await saver.setup()
            yield saver
        return
    with sqlite_checkpointer(database) as saver:
        yield saver


def run_pipeline(
    initial_state: Mapping[str, Any] | Command,
    *,
    goal_id: str,
    autonomy: str = "medium",
    database: Path,
    run_dir: Path | None = None,
    dependencies: PipelineDependencies | None = None,
    resume: Any = None,
) -> dict[str, Any]:
    """Run or resume a pipeline with ``thread_id`` equal to the goal id."""
    payload = _pipeline_payload(initial_state, goal_id=goal_id, run_dir=run_dir, resume=resume)
    config = _run_config(goal_id, payload)
    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=dependencies, checkpointer=saver)
        context = BeastmodeContext(
            autonomy=autonomy, goal_id=goal_id, run_dir=run_dir
        )
        return graph.invoke(
            payload,
            config=config,
            context=context,
            durability=durability_for(autonomy),
        )


async def arun_pipeline(
    initial_state: Mapping[str, Any] | Command,
    *,
    goal_id: str,
    autonomy: str = "medium",
    database: Path,
    run_dir: Path | None = None,
    dependencies: PipelineDependencies | None = None,
    resume: Any = None,
) -> dict[str, Any]:
    """Async-first counterpart to :func:`run_pipeline`."""
    payload = _pipeline_payload(initial_state, goal_id=goal_id, run_dir=run_dir, resume=resume)
    config = _run_config(goal_id, payload)
    async with async_sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=dependencies, checkpointer=saver)
        context = BeastmodeContext(
            autonomy=autonomy, goal_id=goal_id, run_dir=run_dir
        )
        if os.environ.get("BEASTMODE_NATIVE_ASYNC_SQLITE") == "1":
            return await graph.ainvoke(
                payload,
                config=config,
                context=context,
                durability=durability_for(autonomy),
            )
        # SqliteSaver intentionally rejects aget_tuple/aput.  On restricted
        # hosts the connection is thread-bound, so keep this compatibility
        # fallback in the owning event-loop thread rather than moving it to a
        # worker and deadlocking SQLite's connection guard.
        return graph.invoke(
            payload,
            config=config,
            context=context,
            durability=durability_for(autonomy),
        )


def checkpoint_history(
    *,
    database: Path,
    goal_id: str,
    dependencies: PipelineDependencies | None = None,
    limit: int | None = None,
) -> list[Any]:
    """Return durable snapshots for a goal, newest first."""
    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=dependencies, checkpointer=saver)
        config = {"configurable": {"thread_id": goal_id}}
        return list(graph.get_state_history(config, limit=limit))


def replay_from_checkpoint(
    *,
    database: Path,
    goal_id: str,
    checkpoint_id: str,
    new_goal_id: str | None = None,
    autonomy: str = "medium",
    run_dir: Path | None = None,
    dependencies: PipelineDependencies | None = None,
) -> dict[str, Any]:
    """Replay a goal from a selected checkpoint.

    LangGraph's checkpoint id is intentionally explicit.  With
    ``new_goal_id`` the selected snapshot values seed a separate durable
    thread, leaving the original history untouched; without it LangGraph's
    native same-thread replay is used.  Callers can discover ids with
    :func:`checkpoint_history`.
    """
    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=dependencies, checkpointer=saver)
        original_config = {"configurable": {"thread_id": goal_id, "checkpoint_id": checkpoint_id}}
        if new_goal_id:
            snapshot = graph.get_state(original_config)
            return graph.invoke(
                dict(snapshot.values),
                config={"configurable": {"thread_id": new_goal_id}},
                context=BeastmodeContext(autonomy=autonomy, goal_id=new_goal_id, run_dir=run_dir),
                durability=durability_for(autonomy),
            )
        return graph.invoke(
            None,
            config=original_config,
            context=BeastmodeContext(autonomy=autonomy, goal_id=goal_id, run_dir=run_dir),
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
    run_dir: Path | None,
    resume: Any,
) -> Mapping[str, Any] | Command:
    """Bind trusted runtime identity and reject command-based graph jumps."""
    if not isinstance(goal_id, str) or not goal_id or len(goal_id) > 256:
        raise ValueError("goal_id must be a non-empty string no longer than 256 characters")
    if resume is not None:
        return Command(resume=resume)
    if isinstance(initial_state, Command):
        if initial_state.goto or initial_state.update is not None or initial_state.graph is not None:
            raise ValueError("initial Command may resume only; goto, update, and graph are forbidden")
        if initial_state.resume is None:
            raise ValueError("initial Command must contain a resume value")
        return initial_state
    if not isinstance(initial_state, Mapping):
        raise TypeError("initial_state must be a mapping or a resume-only Command")
    payload = dict(initial_state)
    payload["goal_id"] = goal_id
    if run_dir is not None:
        payload["run_dir"] = str(Path(run_dir).resolve())
    return payload


def _secure_sqlite_path(path: Path) -> Path:
    """Create checkpoint storage with private directory and file modes."""
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
    if database.exists():
        database_stat = database.stat()
        if not stat.S_ISREG(database_stat.st_mode):
            raise ValueError("SQLite checkpoint path must be a regular file")
        if database_stat.st_nlink != 1:
            raise ValueError("SQLite checkpoint file must not have hard links")
    database.touch(mode=0o600, exist_ok=True)
    database.chmod(0o600)
    return database


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError("SQLite checkpoint path and parents must not be symlinks")
