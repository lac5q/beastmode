# LangGraph observability

Tracing is optional and never load-bearing. With the LangChain/LangSmith
integration installed, the usual environment is:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=...
export LANGSMITH_PROJECT=beastmode
# optional self-hosted endpoint
export LANGSMITH_ENDPOINT=https://langsmith.example.test
```

The graph's node boundaries provide a trace tree; subprocess executors should
attach a child span from the canonical `meta.json` they write, including
`goal_id`, `phase`, `seat`, `autonomy`, `requested_model`, `actual_model`, and
the `drift`/`unverifiable` tags when the verdict is not `ok`.

The framework-neutral APIs are `beastmode.core.observability.trace_metadata`
and `child_span_from_meta`. LangGraph users can also consume
`graph.stream(..., stream_mode="custom")` for phase/gate/executor progress.
The `WorktreeSubprocessExecutor` attaches a child span only when the child
actually wrote a canonical metadata file; it never turns a silent child into a
passing record.

`acn-report` and `scripts/lib/acn_meta.py` remain the offline source of truth.
Turning tracing off, pointing it at an unreachable endpoint, or sampling a run
must not change a gate verdict.
