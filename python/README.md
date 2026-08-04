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
from beastmode.langgraph import as_chat_model, provenance_gate

seat = resolve_alias("minimax/MiniMax-M3")
configured = seat.with_chat_model(your_base_chat_model)
chat_model = as_chat_model(configured)
```

The complete checkpointed pipeline is `build_pipeline()`. SQLite is the local
default; install the `postgres` extra for `PostgresSaver`. Every executor child
must write the schema-defined `meta.json`; drift and missing provenance fail
closed. See the repository README and `references/beastmode-on-langgraph.md`
for CLI and restart examples.
