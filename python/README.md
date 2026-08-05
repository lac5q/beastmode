# Beastmode Python package

The base package contains framework-neutral contracts, schema loading, seat
resolution, provenance, observability metadata, and worktree helpers. It has no
LangGraph dependency:

```bash
python -m pip install -e python
```

Install the optional LangGraph layer when you want the drop-in primitives:

```bash
python -m pip install -e 'python[langgraph]'
```

```python
from beastmode.core.seats import resolve_alias
from beastmode.langgraph import as_chat_model, build_fanout, provenance_gate

seat = resolve_alias("minimax/MiniMax-M3")
configured = seat.with_chat_model(your_base_chat_model)
chat_model = as_chat_model(configured)
```

Use `provenance_gate` alone in a foreign graph, `autonomy_gate(node)` to pause
any user node below high autonomy, or `build_fanout(executor)` for lane-grouped
`Send` execution without adopting the full pipeline. The complete checkpointed
workflow is `build_pipeline()`.

SQLite is the local default; install the `postgres` extra for `PostgresSaver`.
Every executor child writes schema-defined `meta.json`, while a parent-owned
harness/provider attestation outside the worker run tree independently proves
the serving model. Attestations carry a parent-keyed MAC over the run ID and
exact result digest, so replacement and replay fail closed. Missing evidence,
drift, validation, or review fails closed.
See `references/langgraph-templates.md` for four executable patterns and
`references/beastmode-on-langgraph.md` for the trusted helper contract, CLI,
and restart example.
