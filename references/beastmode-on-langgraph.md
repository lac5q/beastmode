# Beastmode on LangGraph: a restartable example

Install the optional runtime in an isolated environment:

```bash
python -m pip install -e 'python[langgraph]'
```

Build a checkpointed goal over your own state schema. The goal id is the
LangGraph `thread_id`, so a process restart does not create a second run and
project-owned PRD and priority-list fields remain in the same durable state:

```python
from pathlib import Path

from langgraph.types import Command

from beastmode.langgraph import BeastmodeContext, BeastmodeState
from beastmode.langgraph.graphs.pipeline import build_pipeline
from beastmode.langgraph.nodes import PipelineDependencies
from beastmode.langgraph.runtime import sqlite_checkpointer


class ProjectState(BeastmodeState, total=False):
    prd: str
    priority_list: list[str]


database = Path.home() / ".beastmode" / "langgraph.sqlite"
run_dir = Path(".beastmode/runs/health-check")
config = {"configurable": {"thread_id": "health-check"}}
context = BeastmodeContext(autonomy="medium", run_dir=run_dir)
dependencies = PipelineDependencies(
    executor=your_executor,
    validator=your_mechanical_validator,
    reviewer=your_cross_family_reviewer,
)
initial = {
    "goal": "add a health check",
    "prd": "GET /health reports dependency status.",
    "priority_list": ["contract", "implementation", "verification"],
    "run_dir": str(run_dir),
    "tasks": [
        {
            "id": "health-check",
            "goal": "add a health check",
            "lane": "economy",
            "allowed_paths": ["src/"],
            "verify_cmds": ["pytest"],
        }
    ],
}

with sqlite_checkpointer(database) as saver:
    graph = build_pipeline(
        dependencies=dependencies,
        checkpointer=saver,
        state_schema=ProjectState,
    )
    paused = graph.invoke(initial, config=config, context=context)
assert "__interrupt__" in paused
```

`run_dir`, the external attestation path, parent-held attestation key, run ID,
and dependencies are explicit trusted runtime inputs kept out of graph state.
The attestation path must be outside the worker-writable run tree. The key and
run ID authenticate each child/result binding and block file substitution or
cross-run replay. A production dependency set includes an
executor, mechanical validator, and reviewer; omission fails closed.

After a process restart, rebuild the graph over the same database and resume
the same thread after each medium-autonomy interrupt:

```python
with sqlite_checkpointer(database) as saver:
    graph = build_pipeline(
        dependencies=dependencies,
        checkpointer=saver,
        state_schema=ProjectState,
    )
    paused_again = graph.invoke(
        Command(resume="approved"), config=config, context=context
    )
    completed = graph.invoke(
        Command(resume="approved"), config=config, context=context
    )

assert "__interrupt__" in paused_again
assert completed["prd"] == initial["prd"]
assert completed["priority_list"] == initial["priority_list"]
```

For an end-to-end subprocess run, use `bm --harness langgraph` with four
explicit commands:

```bash
bm "add a health check" --harness langgraph \
  --executor-command 'your-child-driver' \
  --attestor-command /trusted/bin/read-harness-journal \
  --validator-command /trusted/bin/validate-result \
  --reviewer-command /trusted/bin/review-result
```

The three trusted helpers must each be one absolute executable outside the
target repository, owned by root/current user, executable, and not
group/world-writable. They read bounded JSON on stdin and return one JSON
object. The attestor returns `id`, `requested_model`, `actual_model`, and
`source`; the validator returns `validation_report`; the reviewer returns
`review_report`. Worker networking is off unless
`--allow-worker-network` is explicitly supplied.

The child receives `BEASTMODE_META_DIR` and writes schema-defined `meta.json`,
but that file cannot attest its own model. The parent helper's evidence is
written outside the worker mount. The main worktree is never used as a child
workspace, and worker commits/pushes are blocked.
