# LangGraph templates

These four patterns are executable documentation: the Python test lane extracts
every named block, compiles it, and runs its `smoke()` function. Applications
should namespace their own state keys (for example `app_*`) and reserve the
`beastmode_` prefix for future Beastmode extensions.

## Provenance gate only

Drop the fail-closed provenance check into an existing graph. The trusted
`run_dir`, attestation path, and expected child IDs belong in
`BeastmodeContext`, not caller-controlled graph state.

```python
# template: provenance-gate-only
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from beastmode.langgraph import BeastmodeContext, provenance_gate


class AppState(TypedDict, total=False):
    provenance_verdict: str


builder = StateGraph(AppState, context_schema=BeastmodeContext)
builder.add_node("provenance", provenance_gate)
builder.add_edge(START, "provenance")
builder.add_edge("provenance", END)
graph = builder.compile()


def smoke():
    result = graph.invoke({}, context=BeastmodeContext(autonomy="high"))
    return result["provenance_verdict"] == "unverifiable"
```

## Minimal gated loop

Wrap any user node with `autonomy_gate`. It pauses before the wrapped node at
low or medium autonomy and runs directly at high autonomy.

```python
# template: minimal-gated-loop
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from beastmode.langgraph import BeastmodeContext, autonomy_gate


class LoopState(TypedDict, total=False):
    steps: int
    gate_decision: str


def work(state, runtime):
    return {"steps": int(state.get("steps", 0)) + 1}


builder = StateGraph(LoopState, context_schema=BeastmodeContext)
builder.add_node("work", autonomy_gate(work))
builder.add_edge(START, "work")
builder.add_edge("work", END)
graph = builder.compile()


def smoke():
    result = graph.invoke({"steps": 0}, context=BeastmodeContext(autonomy="high"))
    return result["steps"] == 1
```

## ACN fan-out only

`build_fanout` groups tasks by `lane`, runs each lane's tasks concurrently with
`Send`, advances lanes sequentially, and reports only after every child has
joined. The executor must return `execution_status`. This report is untrusted
execution completion; add independent validation and provenance before treating
the work as validated.

```python
# template: acn-fanout-only
from beastmode.langgraph import build_fanout


def executor(state):
    return {"execution_status": "ok", "summary": state["task"]["goal"]}


graph = build_fanout(executor)


def smoke():
    tasks = [
        {"id": "a", "lane": "economy", "goal": "one", "allowed_paths": [], "verify_cmds": []},
        {"id": "b", "lane": "economy", "goal": "two", "allowed_paths": [], "verify_cmds": []},
        {"id": "c", "lane": "frontier", "goal": "review", "allowed_paths": [], "verify_cmds": []},
    ]
    result = graph.invoke({"goal": "fan out", "tasks": tasks}, config={"max_concurrency": 3})
    return result["status"] == "executed" and result["execution_report"]["observed"] == ["a", "b", "c"]
```

## Full pipeline

Use the complete builder when the application wants acceptance, design,
challenge, lane fan-out, mechanical validation, provenance and merge gates,
review, persistence, and self-improvement notes as one subgraph. Replace only
documented non-load-bearing nodes through `overrides`; control gates reject
replacement.

The replaceable node names are `contract`, `design`, `challenge`, `execute`,
`review`, and `self_improve`. `before_merge` inserts a trusted build-time hook
after `gate_merge` and immediately before `merge`. The protected names are
`preflight`, `dispatch`, `dispatch_next`, `validate_mechanical`,
`gate_provenance`, `gate_merge`, `merge`, and `blocked`; unknown names raise so
a typo cannot silently create an unreachable node. Graph state cannot choose
or alter these build-time hooks.

```python
# template: full-pipeline
from beastmode.langgraph.graphs.pipeline import build_pipeline
from beastmode.langgraph.nodes import PipelineDependencies


dependencies = PipelineDependencies(
    executor=lambda state: {"execution_status": "ok"},
    validator=lambda state: {"validation_report": {"passed": True}},
    reviewer=lambda state: {"review_report": {"approved": True}},
)
graph = build_pipeline(dependencies=dependencies)


def smoke():
    return "gate_provenance" in graph.get_graph().draw_mermaid()
```
