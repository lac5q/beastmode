# LangGraph templates

The binding is composable. The smallest useful on-ramp is a provenance gate;
the complete builder is available when the caller wants the full loop.

`BeastmodeState` is a mixin-style vocabulary: unrelated parent keys are
preserved. Its flattened v2.4 keys are reserved by the binding; applications
should namespace their own additions (for example `app_*`) and reserve the
`beastmode_` prefix for future namespaced Beastmode extensions.

```python
from beastmode.langgraph import BeastmodeContext, autonomy_gate, provenance_gate
```

## Provenance-gate-only

Add `provenance_gate` to a user's `StateGraph` after the node that writes child
metadata. The parent owns the checkpointer and resumes with
`Command(resume="approved")`.

## Minimal gated loop

```python
from beastmode.langgraph.graphs.pipeline import build_pipeline

graph = build_pipeline()
```

Pass `overrides={"review": my_review_node}` to replace a non-load-bearing node.
`gate_provenance` and `gate_merge` are intentionally not replaceable.

## ACN fan-out only

Supply `PipelineDependencies(executor=my_executor)` and pass tasks with a
`lane` field. The dispatcher emits `Send("execute", ...)` for each task in one
lane, then advances to the next lane before mechanical validation.

## Full pipeline

Use `beastmode.langgraph.runtime.run_pipeline` for a SQLite-backed goal whose
`thread_id` is the goal id. The returned state contains the phase, reports,
provenance verdict, and final status.
