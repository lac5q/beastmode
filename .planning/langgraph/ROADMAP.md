# ROADMAP — Beastmode on LangGraph (v2.4.0)

Branch: `claude/beastmode-langgraph-planning-1w3bl8` (planning only — no
implementation on this branch). Implementation branches per phase, merged to
`main` behind the existing CI gate.

Read `REQUIREMENTS.md` first — it holds the concept mapping, the LangGraph API
facts each phase depends on, and the risk register phases P0–P2 exist to retire.
Read `OPEN-QUESTIONS.md` before starting P1: **Q1–Q3 change this phase order**.

---

## Goal

Make beastmode a **first-class LangGraph layer**: a `pip`-installable package
that gives LangGraph users the beastmode loop — model-tier routing, acceptance
contracts, provenance/drift gates, ACN parallel fan-out, autonomy gating,
per-phase usage reporting, and the self-improvement checkpoint — as ready-to-use
`StateGraph`s, without asking them to leave LangGraph.

Secondary and equally load-bearing: keep the core framework-neutral so a CrewAI
binding later is an adapter, not a rewrite (`REQUIREMENTS.md` §5.6).

## Non-goals

Replacing any existing harness. Rewriting `bm` in Python. Hosted deployment.
CrewAI implementation. Changing the meaning of `schema/*.json`. Self-modifying
graph topology.

## Role routing for this effort

Per hard rule 9, frontier lanes are explicit-only — the seats below are a
*proposal*, not an authorization to spend. Confirm before P0 runs.

- **Director / orchestrator:** frontier. This effort is architecture-heavy: a
  new runtime, a new dependency tree, and five invariants that must survive a
  paradigm change. This is not an economy-tier consolidation pass like v2.2.
- **Worker (executor):** MiniMax-M3 for bounded slices — node authoring against
  a written interface, test authoring, docs. Every P1–P6 task is specified to be
  cheap-routable (concrete interface + verify command), per the verification-cost
  rule.
- **Watcher / validator:** cross-family frontier, and **mandatory on P2 and P4**.
  `.learnings/BEASTMODE.md` records that the last fail-open in the drift gate was
  caught by a cross-family reviewer on a diff with 19 passing checks and green
  CI. P2 and P4 are exactly that shape again.

---

## Phases

| Phase | Scope | Exit (deterministic) |
|---|---|---|
| **P0** | Spikes — retire the unknowns, throwaway code | Support matrix + 3 written verdicts (below) |
| **P1** | `python/` skeleton, `beastmode.core`, schema loader, CI lane | `pytest` green; import-linter proves `core` has zero framework imports; `tests/run-all.sh` still passes with no Python deps installed |
| **P2** | Seat layer + provenance: `SeatModel`, `ChildMeta`, drift gate | Every `acn_meta.py` fixture returns the identical verdict through the Python path; negative test per verdict |
| **P3** | `graphs/pipeline.py` — the loop as a DAG, gates via `interrupt()` | A run at `--autonomy medium` stops at each gate and resumes on `Command(resume=…)`; at `high` it does not stop |
| **P4** | ACN fan-out: `Send` dispatch, worktree subprocess executors, consolidation | 3-child batch runs concurrently; one child killed pre-meta ⇒ gate fails; main tree unmodified |
| **P5** | Persistence, `bm --harness langgraph`, mermaid export | Kill mid-run, resume from checkpoint, run completes; `--harness langgraph` preflights and runs |
| **P6** | Docs, adapter SKILL, parity tests, release | `test-acn-parity.sh` covers the Python state shape; `SKILL.md` v2.4.0; package builds |
| **P7** | `graphs/forever.py` — the continuous evolver (separate effort) | Gated on P1–P6 + Q3 |
| **P8** | CrewAI binding (separate effort) | Gated on P7 |

---

## P0 — Spikes

Throwaway code in a scratch worktree. Nothing merges. The deliverable is three
written verdicts and one table. **This phase exists to make P1–P6 estimable**;
skipping it means committing to a design whose central guarantee (drift
detection) is unverified.

### P0.1 — Can we prove `actual_model`? (retires risk 5.1)

For each provider in `schema/families.json` (anthropic, openai-codex, kimi,
minimax, qwen, xai, zai): send one trivial completion via `init_chat_model`
with a deliberately *aliased* model id, and record what comes back in
`response_metadata` and `usage_metadata`.

Classify each into:
- **echoes resolved model** — drift gate works on direct-call nodes
- **echoes the alias we sent** — gate is blind to router substitution; direct
  calls to this provider are `unverifiable` by construction
- **reports nothing** — same, `unverifiable`

**Exit:** a `provider → provenance capability` matrix committed to
`references/`, plus a one-paragraph verdict on whether direct-call nodes are
viable at all or whether **every** executor must be a subprocess (which would
make Q2 moot and simplify P4).

### P0.2 — What does `interrupt()` replay actually cost? (retires risk 5.2)

Build a two-node graph with a gate that writes a file *before* `interrupt()`.
Confirm the file is written twice on resume. Then confirm the ordering rule
(`interrupt()` first, side effects after resume) fixes it.

**Exit:** a written node-authoring rule for gate nodes, to be enforced by
review in P3 and asserted by a test.

### P0.3 — What does losing lane grouping cost? (retires risk 5.3)

Fan out 9 trivial tasks across 3 lanes, twice: once lane-grouped into sequential
`Send` super-steps, once interleaved. Compare cache-read vs cache-write tokens
from `usage_metadata`.

**Exit:** a number. If the delta is small, accept interleaving and delete the
complexity from P4. If large, P4 gets an explicit lane-grouped dispatcher.

---

## P1 — Package skeleton and framework-neutral core

Nothing LangGraph-specific ships in this phase. The point is the boundary.

**Scope**
- `python/pyproject.toml`, `src/beastmode/core/`, `python/tests/`
- `core/schema.py` — loads `schema/*.json` by path resolution (same walk-up
  strategy as `acn_meta.contract_path`). **Never restates a field list.**
- `core/seats.py` — alias → `{provider, model, tier, family}` resolution with
  the same precedence `bm` uses today: project-local
  `<repo>/.beastmode/tier-aliases.json`, then `~/.beastmode/`, then
  `scripts/tier-aliases.json`
- `core/contract.py` — `AcceptanceContract`, fields from `SKILL.md` §Step 1
- `core/prompts.py` — the worker contract / phase / gate / model-failure
  strings, sourced from `scripts/lib/prompts.sh` so wording cannot fork
- `core/routing.py` — the verification-cost rule as a function
- Optional-extras layout so `pip install beastmode` pulls **no provider SDKs**
- Second CI job that installs the package and runs `pytest`

**Exit (deterministic)**
- `pytest python/tests` green
- An import-linter (or equivalent) contract fails the build if anything under
  `beastmode/core/` imports `langgraph`, `langchain*`, or `crewai`
- `./tests/run-all.sh` passes on a machine with **no** Python packages
  installed — the existing bash lane must not acquire a dependency
- `core/prompts.py` strings are asserted identical to the `prompts.sh` bodies
  (extend `test-acn-parity.sh`, which already does substring parity for adapters)
- `python -c "from beastmode.core.schema import acn_contract; acn_contract()"`
  returns the same dict `acn_meta.required_meta_fields()` reads

---

## P2 — Seats and provenance

The highest-risk phase. **Cross-family watcher review is mandatory here** —
this is the same gate, in a new language, and the last two times it was touched
it failed open.

**Scope**
- `core/provenance.py` — a wrapper over `scripts/lib/acn_meta.py`. It calls
  `check()`. It does not reimplement `is_child_record`, `Row._classify`,
  `expected_ids`, or the verdict logic.
- `langgraph/state.py` — `ChildMeta` TypedDict whose field list is **read from**
  `schema/acn-contract.json` at import, not typed out
- `SeatModel` — wraps a chat model, records `requested_model` and the observed
  `actual_model` from response metadata per P0.1, emits a `meta.json` in the
  run dir in the canonical shape
- Build-time seat preflight raising `SeatUnavailable` with the available
  alternatives, mirroring `enforce-models`' exit-2 message including the
  `BM_SKIP_MODEL_CHECK=1` bypass hint

**Exit (deterministic)**
- For every fixture in `tests/fixtures/acn-meta/`, the Python path and
  `enforce-models --check-meta` return the **same verdict and the same exit
  code**. This is check (e3) from `test-acn-parity.sh`, extended to a third
  caller.
- Negative test per verdict, each written by breaking the invariant
  deliberately: a drifted child fails; a child missing `requested_model` fails;
  an unreadable meta fails; an empty run dir fails without `--allow-empty`; a
  child in `--expect` that wrote nothing fails.
- A passing sibling does not rescue a failing one — asserted directly.
- `SeatModel` writes a meta that `acn_meta.is_child_record()` recognises.
- A provider from P0.1's "reports nothing" column produces `unverifiable`, not
  a pass.

---

## P3 — `graphs/pipeline.py`: the loop as a DAG

The faithful port. Same eight steps, same gates, same reports — as a graph.

**Nodes**

| Node | Tier | Does |
|---|---|---|
| `preflight` | — | `git status`, seat resolution, model preflight |
| `contract` | frontier | Writes the acceptance contract into state |
| `design` | frontier | Design package: file plan, interfaces, verify commands |
| `challenge` | frontier (cross-family) | Adversarial pass over the design; optional at `high` |
| `dispatch` | — | Splits the design package into ACN tasks (`Send` in P4) |
| `execute` | economy | One per task (P4) |
| `validate_mechanical` | economy | Runs `verify_cmds`, emits the structured report |
| `gate_provenance` | — | `acn_meta.check()` — `ok` / `drift` / `unverifiable` |
| `review` | frontier | Reads **report + diff**, never raw logs |
| `gate_merge` | — | `interrupt()` below `high` |
| `merge` | — | |
| `self_improve` | economy | Appends to `.learnings/BEASTMODE.md`. **Notes only.** |

**Edges**
- `gate_provenance`: `ok` → `review`; `drift` | `unverifiable` → `dispatch`
  (re-run under the pinned model), with a bounded retry count that routes to
  `blocked` rather than looping
- `gate_merge`: approved → `merge`; rejected → `design`
- Every gate: `interrupt()` when `runtime.context.autonomy != "high"`, and
  `interrupt()` is the **first statement** in the node (P0.2)

**Exit (deterministic)**
- `--autonomy medium` on a toy goal stops at each gate; `Command(resume=…)`
  continues; `--autonomy high` runs through without stopping
- `--autonomy low` stops at every phase transition, not only merge gates
- A gate node re-entered after resume does not duplicate its side effects
  (asserted by a file-write counter, per P0.2)
- `graph.get_graph().draw_mermaid()` renders and is committed to
  `references/langgraph-pipeline.md` — the living flowchart, free
- `MODEL DRIFT` surfaces at `high` autonomy too, and blocks `validated`

---

## P4 — ACN fan-out

**Scope**
- `dispatch.py` — build `Send(...)` per task from the batch, honoring
  `batch_required_fields` and `task_required_fields` from the schema
- `max_concurrency` from `concurrency_default` (3)
- Lane grouping per P0.3's number
- `core/worktree.py` — `git worktree add` per child, torn down on completion
- `core/executors/` — subprocess drivers for `pi`, `claude -p`, `codex exec`,
  `delegate_task`; each writes the child `meta.json` (this is where hard rule 1
  survives — see `REQUIREMENTS.md` §5.2)
- Consolidation as a **deferred node** so ragged child completion doesn't run
  the consolidator early

**Exit (deterministic)**
- A 3-task batch runs concurrently (wall clock < sum of children)
- Each child gets its own worktree; `git status --porcelain` in the main tree
  is empty for the whole run
- A child killed before writing its meta ⇒ `gate_provenance` fails via
  `--expect`, and the killed child appears in the report by id rather than
  vanishing
- A child that attempts `git commit` or `git push` is blocked by the executor's
  permission config, and the attempt is recorded
- Consolidation observes all children, including the slowest

---

## P5 — Persistence and the `bm` entrypoint

**Scope**
- `SqliteSaver` default, `PostgresSaver` opt-in (`.setup()` on first use;
  `autocommit=True` + `row_factory=dict_row` on manual connections)
- `thread_id` = beastmode goal id, so a goal is resumable by name
- `durability` policy: `"sync"` for any gate-bearing run, `"exit"` permitted
  only at `--autonomy high`
- `bm --harness langgraph` in `scripts/bm`, plus the matching `enforce-models
  --harness langgraph` preflight (package importable + checkpointer reachable)
- `bm --graph <name>` to choose `pipeline` (later `forever`)

**Exit (deterministic)**
- Kill the process mid-phase; re-invoke with the same `thread_id`; the run
  resumes at the last checkpoint and completes
- `bm --harness bogus` still exits 2 (regression on `test-bm-model-check.sh`)
- `bm --harness langgraph` with the package absent exits 2 with an install hint,
  never a traceback
- Time-travel: replay from an earlier checkpoint produces a divergent thread
  without corrupting the original

---

## P6 — Docs, parity, release

**Scope**
- `adapters/langgraph/SKILL.md`, matching the vocabulary of the other four
  adapters (autonomy levels, MODEL DRIFT, "no watcher no validated", gates
  blocking below high) — `test-acn-parity.sh` check (f) already greps for this
- `SKILL.md` → v2.4.0: harness table gains LangGraph; ACN table gains the
  `Send` primitive
- `README.md`, `references/acn-contract.md` harness map, `schema/` unchanged
- `references/langgraph-pipeline.md` — the mermaid render + node/edge reference
- A worked example: "Beastmode on LangGraph" evolving a small project, showing
  the PRD + priority list surviving a restart
- `python/README.md` for the PyPI page

**Exit (deterministic)**
- `test-acn-parity.sh` gains: Python `ChildMeta` fields == schema
  `meta_json_required_fields`; adapter vocabulary check covers the new adapter;
  the LangGraph adapter's canonical version cross-reference matches `SKILL.md`
- `./tests/run-all.sh` green with **no** Python packages installed
- The new CI job green with the package installed
- CI's "working tree unchanged" assertion still passes (no test may write into
  the repo — the v2.3 fixture-rewriting bug)
- `python -m build` produces a wheel; the wheel imports with no provider SDKs
  present

---

## P7 — `graphs/forever.py` (separate effort, gated)

Not the same thing as P3, and worth stating plainly: P3 ports the *existing*
fixed loop. P7 is the **new capability** — the continuously-cooking evolver that
keeps a project moving for days, with a graph that cycles rather than
terminates.

Sketched nodes: `prd_maintainer`, `priority_curator`, brainstormers (fan-out by
specialty), `implementer` (reuses P4's ACN dispatch), `reviewer`,
`context_repacker`, `cleanup`, and a `user_redirect` priority edge that
preempts the current cycle when the human drops in a new instruction.

New concerns this raises that P3 does not:
- Cross-thread memory — the PRD and priority list live in a `Store`, not the
  checkpointer, because they outlive any single thread
- Termination and budget — a graph with no exit needs a spend ceiling and an
  anti-spin breaker (`pi-loop-police`'s role, with no LangGraph equivalent)
- Supervision — checkpoints are not durable execution (`REQUIREMENTS.md` §5.5);
  an external supervisor is required before any "runs for days" claim is made
- Whether the graph may edit its own topology (Q5) — currently forbidden by
  hard rule "self-improvement writes notes only"

**Gated on:** P1–P6 shipped, and Q3 answered.

---

## P8 — CrewAI binding (separate effort, gated)

A `beastmode.crewai` binding over the same `beastmode.core`: Flows'
`@start` / `@listen` / `@router` wrapping the same seats, contract, provenance
gate, and reports. Its exit criterion is that it adds **no** logic already in
`core` — if it needs to reimplement the gate, P1's boundary failed and that is
the finding.

**Gated on:** P7, and a decision that CrewAI adoption is still worth it then.

---

## Success criteria for the effort

- A LangGraph user runs `pip install beastmode-langgraph`, imports one builder,
  and gets tier routing + contracts + drift gates + autonomy gating without
  reading `SKILL.md`
- The five invariants in `REQUIREMENTS.md` §2 hold, each asserted by a test that
  was negative-tested by deliberately breaking it
- `schema/*.json` is still the only source of truth; no field list exists twice
- `scripts/lib/acn_meta.py` is still the only gate implementation
- A bash-only beastmode user sees no change and installs nothing
- `beastmode.core` has zero framework imports, proven by CI
