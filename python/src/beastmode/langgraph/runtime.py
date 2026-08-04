"""Checkpoint and invocation helpers for Beastmode's LangGraph binding."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
import os
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Mapping

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from .context import BeastmodeContext
from .graphs.pipeline import build_pipeline
from .nodes import PipelineDependencies


@contextmanager
def sqlite_checkpointer(path: Path) -> Iterator[SqliteSaver]:
    """Open the local checkpointer and initialize its tables."""
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
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
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
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
    with sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=dependencies, checkpointer=saver)
        config = _run_config(goal_id, initial_state)
        context = BeastmodeContext(
            autonomy=autonomy, goal_id=goal_id, run_dir=run_dir
        )
        payload: Mapping[str, Any] | Command = initial_state
        if resume is not None:
            payload = Command(resume=resume)
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
    async with async_sqlite_checkpointer(database) as saver:
        graph = build_pipeline(dependencies=dependencies, checkpointer=saver)
        config = _run_config(goal_id, initial_state)
        context = BeastmodeContext(
            autonomy=autonomy, goal_id=goal_id, run_dir=run_dir
        )
        payload: Mapping[str, Any] | Command = initial_state
        if resume is not None:
            payload = Command(resume=resume)
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
        value = initial_state.get("concurrency") or batch.get("concurrency")
        if isinstance(value, int) and value > 0:
            config["max_concurrency"] = value
    return config
