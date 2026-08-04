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
    attestations=Path(".beastmode/health-check.attestations"),
    dependencies=PipelineDependencies(
        executor=your_executor,
        validator=your_mechanical_validator,
        reviewer=your_cross_family_reviewer,
    ),
)
```

`run_dir`, the external attestation path, and dependencies are explicit trusted
runtime inputs kept out of graph state. The attestation path must be outside
the worker-writable run tree. A production dependency set includes an
executor, mechanical validator, and reviewer; omission fails closed.

At medium autonomy, resume the same thread after each interrupt:

```python
from langgraph.types import Command

graph.invoke(Command(resume="approved"), config={"configurable": {"thread_id": "health-check"}})
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
