---
name: beastmode-langgraph
description: LangGraph binding for the universal Beastmode orchestration contract
version: 2.4.0
author: Luis Calderon
tags: [beastmode, langgraph, orchestration, model-routing, acn]
related_skills: [beastmode, gsd]
source_repo: https://github.com/lac5q/beastmode/blob/main/adapters/langgraph/SKILL.md
---

# Beastmode LangGraph — runtime adapter

This adapter supplies the LangGraph mechanics for the canonical `beastmode`
skill (v2.4.0). Install `beastmode[langgraph]` (plus `[studio]` for
`langgraph dev`); the shell lane remains
install-free and is unchanged for users who do not select this harness.

## Primitive map

| Beastmode concept | LangGraph implementation |
|---|---|
| Loop | `StateGraph` from `beastmode.langgraph.graphs.pipeline` |
| ACN fan-out | `Send` with same-lane batches and a join before validation |
| Gate | `interrupt()` with `Command(resume=...)` below high autonomy |
| Persistence | `SqliteSaver`, `thread_id` equal to the goal id |
| Executor | Existing coding-agent subprocess in an isolated worktree |
| Provenance | `beastmode.core.provenance` delegates to `scripts/lib/acn_meta.py` |
| Direct model | `SeatModel.as_chat_model()` exposes a configured `BaseChatModel` |
| Observability | Custom stream events plus OTel-shaped `trace_metadata` and child spans |

Gates are blocking below high. `MODEL DRIFT` and `unverifiable` are always
surfaced and never count as validated. No watcher, no validated. A provider
that does not prove `actual_model` is unsupported for direct-call judgment
seats and must use the subprocess fallback.

## Usage

```python
from langgraph.checkpoint.sqlite import SqliteSaver
from beastmode.langgraph import BeastmodeContext
from beastmode.langgraph.graphs.pipeline import build_pipeline

with SqliteSaver.from_conn_string(".beastmode/langgraph.sqlite") as saver:
    saver.setup()
    graph = build_pipeline(checkpointer=saver)
    result = graph.invoke(
        {"goal": "add a health check"},
        config={"configurable": {"thread_id": "health-check"}},
        context=BeastmodeContext(autonomy="medium"),
    )
```

Resume the same thread with `graph.invoke(Command(resume="approved"), ...)`.
Use `graph.get_graph().draw_mermaid()` for the living topology. Import
`provenance_gate`, `autonomy_gate`, and `route_by_verification_cost` directly
when embedding only the primitives you need in a foreign graph.

For an async caller, use `arun_pipeline` with the same goal id. SQLite is the
safe local default; install `beastmode[postgres]` and inject
`postgres_checkpointer` for a shared production database. The native
`AsyncSqliteSaver` path is available with `BEASTMODE_NATIVE_ASYNC_SQLITE=1`;
restricted hosts use a non-hanging compatibility fallback.

The real CLI driver requires an explicit child command:

```bash
bm "add a health check" --harness langgraph \
  --executor-command 'your-child-driver'
```

The driver receives `BEASTMODE_META_DIR`, `BEASTMODE_TASK_ID`, and
`BEASTMODE_REQUESTED_MODEL` (and the goal in `BEASTMODE_TASK_GOAL`). It must
write `meta.json` there. The subprocess
environment excludes ambient credentials and a git shim blocks worker
`commit`/`push`; missing metadata remains an `unverifiable` gate failure.
