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
| Provenance | `beastmode.core.provenance` delegates to `scripts/lib/acn_meta.py`; parent-keyed run/result MACs prevent attestation substitution and replay |
| Direct model | `beastmode.langgraph.as_chat_model(seat)` exposes a configured `BaseChatModel` |
| Observability | Custom stream events plus OTel-shaped `trace_metadata` and child spans |

Gates are blocking below high. `MODEL DRIFT` and `unverifiable` are always
surfaced and never count as validated. No watcher, no validated. A provider
that does not prove `actual_model` is unsupported for direct-call judgment
seats and must use the subprocess fallback.

## Usage

```python
from pathlib import Path
from beastmode.langgraph import BeastmodeContext
from beastmode.langgraph.graphs.pipeline import build_pipeline
from beastmode.langgraph.nodes import PipelineDependencies
from beastmode.langgraph.runtime import sqlite_checkpointer

with sqlite_checkpointer(Path.home() / ".beastmode" / "langgraph.sqlite") as saver:
    graph = build_pipeline(
        dependencies=PipelineDependencies(executor=your_executor),
        checkpointer=saver,
    )
    result = graph.invoke(
        {"goal": "add a health check"},
        config={"configurable": {"thread_id": "health-check"}},
        context=BeastmodeContext(
            autonomy="medium",
            run_dir=Path(".beastmode/runs/health-check"),
        ),
    )
```

The executor, `run_dir`, attestation key, and attestation run ID are trusted
runtime configuration. `WorktreeSubprocessExecutor` creates the credentials;
pass its `attestation_key` and `attestation_run_id` to `run_pipeline` with its
attestation directory. Omitting them causes authenticated provenance to block;
graph state cannot select its own provenance target or credentials.

Resume the same thread with `graph.invoke(Command(resume="approved"), ...)`.
Use `graph.get_graph().draw_mermaid()` for the living topology. Import
`provenance_gate`, `autonomy_gate`, and `route_by_verification_cost` directly
when embedding only the primitives you need in a foreign graph. Use
`build_fanout(executor)` for lane-grouped `Send` execution without the full
pipeline; all four copy-paste patterns are executable-tested in
`references/langgraph-templates.md`.

For an async caller, use `arun_pipeline` with the same goal id. SQLite is the
safe local default; install `beastmode[postgres]` and inject
`postgres_checkpointer` for a shared production database. The native
`AsyncSqliteSaver` path is available with `BEASTMODE_NATIVE_ASYNC_SQLITE=1`;
restricted hosts use a non-hanging compatibility fallback.

The real CLI driver requires an explicit child command:

```bash
bm "add a health check" --harness langgraph \
  --executor-command 'your-child-driver' \
  --attestor-command /trusted/bin/read-harness-journal \
  --validator-command /trusted/bin/validate-result \
  --reviewer-command /trusted/bin/review-result
```

The driver receives `BEASTMODE_META_DIR`, `BEASTMODE_TASK_ID`, and
`BEASTMODE_REQUESTED_MODEL` (and the goal in `BEASTMODE_TASK_GOAL`). It must
write `meta.json` there. The subprocess
environment excludes ambient credentials and a git shim blocks worker
`commit`/`push`. The default worktree executor additionally requires Linux
`bubblewrap`, mounting the shared checkout and Git metadata read-only. Missing
metadata remains an `unverifiable` gate failure. Other platforms must inject a
different executor with an equivalent isolation boundary.
