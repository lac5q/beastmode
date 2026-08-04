# Beastmode on LangGraph: a restartable example

Install the optional runtime in an isolated environment:

```bash
python -m pip install -e 'python[langgraph]'
```

Build a checkpointed goal. The goal id is the LangGraph `thread_id`, so a
process restart does not create a second run:

```python
from pathlib import Path

from beastmode.langgraph import BeastmodeContext
from beastmode.langgraph.nodes import PipelineDependencies
from beastmode.langgraph.runtime import run_pipeline

result = run_pipeline(
    {
        "goal": "add a health check",
        "run_dir": ".beastmode/runs/health-check",
        "tasks": [
            {
                "id": "health-check",
                "goal": "add a health check",
                "lane": "economy",
                "allowed_paths": ["src/"],
                "verify_cmds": ["pytest"],
            }
        ],
    },
    goal_id="health-check",
    autonomy="medium",
    database=Path.home() / ".beastmode" / "langgraph.sqlite",
    run_dir=Path(".beastmode/runs/health-check"),
    dependencies=PipelineDependencies(executor=your_executor),
)
```

`run_dir` and the executor are explicit trusted runtime inputs. The graph
fails closed when either is missing; it never trusts a caller-supplied state
path as the provenance target.

At medium autonomy, resume the same thread after each interrupt:

```python
from langgraph.types import Command

graph.invoke(Command(resume="approved"), config={"configurable": {"thread_id": "health-check"}})
```

For an end-to-end subprocess run, use `bm --harness langgraph` with an
explicit child command. The child receives `BEASTMODE_META_DIR` and must write
the schema-defined `meta.json`; the main worktree is never used as a child
workspace, and worker commits/pushes are blocked.
