# Requirements — Beastmode as a first-class LangGraph layer

Status: **draft for review**. Nothing here is committed to implementation until
the open questions in `OPEN-QUESTIONS.md` are answered — three of them change
the phase order in `ROADMAP.md`.

Target: beastmode **v2.4.0**, shipping a Python distribution alongside the
existing skill. LangGraph pinned at **1.2.x** (latest 1.2.10, 2026-07-28).

---

## 1. Why this is not a small change

Beastmode today has **no runtime**. It is:

| Layer | What it actually is |
|---|---|
| The framework | `SKILL.md` (36 KB of prose an LLM harness reads) |
| The vocabulary | `schema/*.json` — 5 files, machine-readable, load-bearing since v2.3 |
| The control flow | `scripts/bm` — 260 lines of bash that resolves seats, preflights, then `exec`s a harness |
| The enforcement | `scripts/enforce-models` + `scripts/acn-report`, both calling `scripts/lib/acn_meta.py` (348 lines, the only Python in the repo) |
| The execution | somebody else's agent: `pi`, `delegate_task`, `claude -p`, `codex exec` |

The orchestration is *prose executed by a model*, and the gates are *postflight
filesystem checks* over `meta.json` files the workers dropped. There is no
`pyproject.toml`, no `package.json`, no dependency file of any kind.

LangGraph is a Python library with typed state, a checkpointer, and an
in-process scheduler. Adopting it means the repo grows a **first-class runtime
and its first dependency tree**. That is the real cost of this effort — bigger
than any single graph we draw.

The upside is equally concrete: the beastmode loop stops being a set of
instructions a model may or may not follow, and becomes a graph that *cannot*
skip a gate, because the gate is an edge.

---

## 2. What must survive the port

These are the invariants the last two releases were spent earning. A LangGraph
port that loses any of them is a regression, not a feature.

0. **LangGraph is strictly additive. Beastmode works without it.** *(Decided
   2026-08-03 — Q1.)* No bash script, test, schema, doc, or adapter acquires a
   hard Python dependency. `./tests/run-all.sh` passes on a machine with zero
   Python packages installed. A user who never installs the package sees no
   behavior change, and no existing `bm` invocation changes meaning. This
   outranks every other consideration in this document: where LangGraph
   idiom and this invariant conflict, this invariant wins. It is a
   merge-blocking exit on **every** phase, not a §5 risk to manage.

   The corollary is a priority: **existing beastmode users are the primary
   audience.** `bm --harness langgraph` is a first-class deliverable, not a
   late add-on. The package still ships — it is the implementation, and it is
   the adoption channel for LangGraph users who arrive from the other
   direction — but "beastmode users get an upgrade and lose nothing" is what
   decides ties.

1. **One vocabulary.** `schema/*.json` stays the source of truth. Python types
   are *derived from or validated against* the JSON — never hand-copied.
   `.learnings/BEASTMODE.md` already records what happens when `schema/` becomes
   decorative: four documents called it the source of truth while no code read
   it, and the gate silently hard-coded its own field list.
2. **One gate implementation.** `scripts/lib/acn_meta.py` remains the only
   thing that decides `ok` / `drift` / `unverifiable`. The graph *calls* it. It
   does not get a Python twin — that is the exact "one contract, two
   implementations" failure the v2.3 review found between `enforce-models` and
   `acn-report`.
3. **Three verdicts, two of them failures.** A gate must have a verdict for
   "cannot determine", and that verdict must fail. LangGraph's retry and error
   handling must not be able to convert `unverifiable` into a pass or a silent
   skip.
4. **A gate over a set fails if any member fails.** `Send` fan-out aggregation
   must not let a passing sibling carry a batch. Recognition of a child record
   stays separate from judgment of it (`is_child_record` vs `Row._classify`).
5. **Main tree stays clean.** Executors work in isolated worktrees and never
   commit, push, or touch secrets. See §5 — this is the constraint LangGraph
   fits *worst*, and it drives the biggest design decision in the effort.
6. **Gates are blocking below `high`.** Default autonomy is `medium`.
7. **Model drift always surfaces**, at every autonomy level, and blocks
   `validated`.
8. **Self-improvement writes notes only — below `high`.** *(Amended 2026-08-03
   — Q5.)* At `low` and `medium` autonomy the rule is unchanged: a run records
   lessons, and any lasting behavior change is a separate user-approved task.
   At `--autonomy high`, the graph **may** mutate its own topology, subject to
   four guardrails: a mutation may not remove or weaken a gate; the pre-mutation
   topology is checkpointed and the diff rendered; mutation is added to
   `high.always_surfaces` in `schema/autonomy-levels.json`; and mutations are
   bounded per run. Scope: the evolver phase only — nothing before it mutates
   anything.

---

## 3. Concept mapping — beastmode → LangGraph

| Beastmode concept | LangGraph primitive | Confidence | Notes |
|---|---|---|---|
| The loop (Preflight → Contract → Design → Delegate → Validate → Review → Merge → Self-Improve) | `StateGraph` nodes + `add_edge` | **High** | Faithful port; a mostly-linear DAG with conditional edges at gates |
| Acceptance contract | typed `AcceptanceContract` in graph state, written by the contract node | **High** | Field names come from `.planning/ACCEPTANCE.md` template in `SKILL.md` §Step 1 |
| Autonomy level (`low`/`medium`/`high`) | `context_schema` → read via `Runtime[BeastmodeContext]` | **High** | Config, not state — it does not change during a run |
| "Gates are blocking below high" | `interrupt()` inside the gate node when `autonomy != "high"` | **High** | See §4 — has a sharp edge |
| ACN batch fan-out | `Send(node, payload)` from a dispatch node | **High** | `concurrency_default: 3` → `config={"max_concurrency": 3}` |
| Lane grouping for prompt-cache warmth | **no native primitive** | **Low** | See §5.3 — a real, costed degradation |
| Per-child `meta.json` | `ChildMeta` appended to state via reducer **and** written to the run dir | **High** | Keep the filesystem write so `acn-report` / `enforce-models --check-meta` keep working unchanged |
| Drift / provenance gate | a `gate_provenance` node that shells to `acn_meta.check()` | **High** | Import the module, call `check()`; do not reimplement |
| Model preflight (`enforce-models`, exit 2) | build-time validation before `.compile()`, raising `SeatUnavailable` | **High** | Fail before the graph exists, matching today's "never start against an unresolvable model" |
| requested vs actual model | `SeatModel` wrapper recording `response_metadata` | **Low** | ⚠️ **Spike required** — see §5.1 |
| Worktree isolation | executor node spawns a subprocess inside `git worktree add` | **Medium** | See §5.2 |
| MemroOS-style durable handoff | checkpointer (`SqliteSaver` local, `PostgresSaver` prod); `thread_id` = goal id | **High** | This is the single best fit in the whole mapping |
| Cross-session project memory (PRD, priority list) | LangGraph `Store` (cross-thread), not the checkpointer | **Medium** | Only needed for the "forever" graph (P7) |
| Session restart / context re-pack | a re-pack node + `Command(goto=...)` | **Medium** | Replaces "restart the session and recompact" |
| Phase usage report | `usage_metadata` accumulated by a reducer, rendered by `acn-report` | **High** | |
| Self-improvement entry | node appends to `.learnings/BEASTMODE.md` | **High** | Notes only |
| Living flowchart | `graph.get_graph().draw_mermaid()` | **High** | Free. Also the answer to "prompt a graph and drop it in" — the graph becomes an inspectable artifact |
| Multi-day unattended evolution | checkpointer + **external supervisor** | **Medium** | See §5.5 — checkpoints are not durable execution |

---

## 4. LangGraph API facts this design depends on

Verified against LangGraph 1.2.x docs, August 2026. If any of these change,
the phase that depends on it is invalidated.

- **`interrupt()` requires a checkpointer.** No checkpointer, no gates. This
  makes persistence a P3 dependency, not a P5 nice-to-have.
- **`interrupt()` replays its node from the top on resume.** Everything in a
  gate node before the `interrupt()` call runs *twice*. Gate nodes must
  therefore be side-effect-free, and `interrupt()` should be the first
  statement. A gate node that writes the phase report before interrupting will
  write it twice.
- **Resume is `Command(resume=<value>)`** on the same `thread_id`.
- **`durability`** has three modes: `"exit"` (checkpoint only at the end,
  fastest), `"async"` (persist while the next step runs), `"sync"` (persist
  before the next step starts). Any run that can hit a gate needs at least
  `"async"`; `"sync"` for anything gate-bearing that we care about resuming
  exactly. `"exit"` is only acceptable for `--autonomy high` fire-and-forget.
- **`Send` is the map-reduce primitive** — dynamic fan-out from runtime data,
  which is exactly the ACN batch shape.
- **Deferred nodes** delay a node until all pending branches finish — the
  correct primitive for the consolidation step after a ragged fan-out, where
  children finish at different times.
- **`set_node_defaults`** sets `retry_policy` / `timeout` / `cache_policy` /
  `error_handler` once per graph instead of per `add_node`.
- **Subgraphs: only the parent should carry a checkpointer.** Relevant because
  a phase-as-subgraph layout is otherwise attractive.
- **`max_concurrency`** in the run config caps concurrent node execution.

Sources are listed at the bottom of this document.

---

## 5. Risks, ranked

### 5.1 — `actual_model` may not be knowable (**HIGH — blocks the drift gate**)

Beastmode's headline guarantee is that drift always surfaces. Today that works
because the *worker harness* writes `actual_model` into `meta.json` from its own
journal. Move orchestration into LangGraph and, for any node that calls a chat
model directly, the only source of truth is the provider's response metadata —
typically `response_metadata["model_name"]` or `usage_metadata`.

**Some providers echo the resolved model. Some echo the alias you sent. Some
echo nothing.** Where a provider does not report it, `actual_model` is
unknowable and every child through that lane is `unverifiable` — which
fail-closed correctly turns into a red gate, i.e. the feature is unusable on
that provider rather than silently wrong. That is the right failure mode and
also a potentially fatal one for adoption.

**Mitigation:** P0 spike measures this per provider before anything is built,
and produces a support matrix. Providers that cannot prove the serving model
are documented as unsupported for direct-call nodes (they remain fine behind a
subprocess executor that writes its own meta).

### 5.2 — In-process nodes cannot be constrained (**HIGH — hard rule 1**) — *resolved by Q2*

"Workers never commit/push", "workers never access secrets", and "stay inside
`allowed_paths`" are enforced today by the worker being a *separate process*
with its own permission config (`pi-permission-system`) and its own worktree.
A LangGraph node is a Python function in the orchestrator's own process with
the orchestrator's own environment and credentials. Prose cannot constrain it.

**Mitigation and the biggest design call in this effort:** LangGraph replaces
`scripts/bm`'s *control flow*, not the executor. Executor nodes spawn the
existing coding agents (`pi`, `claude -p`, `codex exec`, `delegate_task`) as
subprocesses inside `git worktree`s, exactly as today. Beastmode-on-LangGraph
then becomes a **harness-of-harnesses** — which is a stronger product position
than a fifth harness, because it orchestrates any coding agent rather than
competing with them.

**Decided (Q2): split by seat.** Judgment seats — director, watcher, validator —
call chat models directly, because they read and decide and never write files.
Executor seats are subprocesses in worktrees. Hard rule 1 survives untouched,
since the only nodes that touch the filesystem are still separate processes with
their own permission config.

The residual exposure is narrow but real: direct-call judgment nodes get their
`actual_model` only from provider response metadata, so risk 5.1 now **gates**
this decision rather than sitting beside it. P0.1's matrix gains a
`direct-call viable` column, and any frontier provider that cannot prove its
serving model falls back to a subprocess seat rather than being trusted.

### 5.3 — Lane grouping has no LangGraph expression (**MEDIUM — cost**)

`SKILL.md` §Step 3 is explicit: batch same-lane workers consecutively so the
shared prefix stays cache-warm (0.10x reads vs a 1.25x write on every lane
switch). `Send` hands the runtime a set of tasks and lets it schedule them.
Ten workers across three lanes, interleaved, pay a cache write on every switch.

**Mitigation options:** (a) group by lane into sequential `Send` super-steps —
loses some parallelism, keeps the discount; (b) accept the degradation and
measure it; (c) custom scheduling in the dispatch node. Decide with numbers
from the P0 spike, not in advance.

### 5.4 — The repo becomes polyglot (**HIGH — this is now invariant 0, not a risk**)

First `pyproject.toml`, first dependency tree, first release process, first
version-sync problem (`SKILL.md` frontmatter `version:` vs package version).
CI currently runs `./tests/run-all.sh` on Python 3.11 with **zero installs**
and asserts the working tree is unchanged afterward. A Python package adds an
install step, a lockfile, and a lane that can break for reasons unrelated to
beastmode. `langgraph` also pulls `langchain-core` and friends — the transitive
tree is not small.

**Mitigation — now mandatory, not a mitigation:** per Q1 this is invariant 0.
`tests/run-all.sh` keeps passing with no Python deps installed; graph tests live
behind a separate CI job that installs the package. Every phase carries the
install-free bash-lane assertion as an exit, so the dependency cannot leak in
gradually. A user who never touches LangGraph sees no change.

### 5.5 — Checkpoints are not durable execution (**MEDIUM — only for P7**)

The checkpointer saves state, but nothing detects failure. If the process
crashes, no one knows and nothing resumes. The "runs for days while you ignore
it" story therefore needs a supervisor *outside* LangGraph: a cron/systemd loop
that re-invokes the thread, or LangGraph Platform, or Temporal/Inngest.
Promising multi-day autonomy on a bare checkpointer would be a false claim.

### 5.6 — CrewAI later means a rewrite unless the core is split now (**HIGH, cheap to prevent**)

CrewAI Flows (`@start` / `@listen` / `@router`) is an event-driven decorator
model, not a graph-construction API. Nothing about a `StateGraph`-shaped
codebase transfers. But almost everything valuable in beastmode is
*framework-neutral*: seat resolution, tier routing, the acceptance contract,
the provenance gate, the usage report, worker-contract prompts.

**Mitigation — and this is why the CrewAI ask matters in phase 1 even though
CrewAI is out of scope:** ship `beastmode-core` (zero framework imports) plus a
thin `beastmode-langgraph` binding. A CrewAI binding later is then a small
adapter over the same core instead of a second implementation. If phase 1 ships
LangGraph-native, "one at a time" turns into "twice".

### 5.7 — Schema fork (**HIGH, mitigated by construction**)

The moment a Python `TypedDict` restates `meta_json_required_fields`, the JSON
and the code can disagree. `tests/test-acn-parity.sh` already asserts the prose
in `references/acn-contract.md` matches the schema; it must be extended to
assert the Python state shape matches too.

---

## 6. Package layout (proposed)

Framework-neutral core, thin bindings. Reserves the CrewAI slot without
building it.

```
python/
  pyproject.toml                     # workspace / single dist, TBD by Q4
  src/beastmode/
    core/                            # ZERO framework imports. Enforced by a test.
      __init__.py
      schema.py                      #   loads schema/*.json — never restates it
      seats.py                       #   alias -> provider/model, tier, family
      contract.py                    #   AcceptanceContract type + template
      provenance.py                  #   thin wrapper over scripts/lib/acn_meta.py
      routing.py                     #   verification-cost routing rule
      prompts.py                     #   worker contract, phase, gate, drift prompts
      report.py                      #   phase usage report
      worktree.py                    #   git worktree lifecycle
      executors/                     #   subprocess drivers: pi, claude, codex, hermes
    langgraph/                       # the binding
      __init__.py
      state.py                       #   BeastmodeState + reducers
      context.py                     #   BeastmodeContext (autonomy, seats, budget)
      nodes/                         #   one module per node
      graphs/
        pipeline.py                  #   P3: the beastmode loop as a DAG
        forever.py                   #   P7: the continuous evolver
      gates.py                       #   interrupt() wrappers
      dispatch.py                    #   Send fan-out, lane grouping
    crewai/                          # P8 — reserved, empty, not shipped
  tests/
```

`scripts/lib/acn_meta.py` is **imported**, not vendored. If the distribution
must be installable standalone, it moves into `beastmode/core/` and the bash
scripts import it from there — one file, one location, either way.

---

## 7. Platform and dependency requirements

| Requirement | Minimum | Why |
|---|---|---|
| `python` | **3.11** | Matches `.github/workflows/tests.yml` and `acn_meta.py`'s `Path \| None` syntax |
| `langgraph` | **1.2.x** | `durability` modes, deferred nodes, `set_node_defaults`, `Runtime[ContextT]` |
| `langgraph-checkpoint-sqlite` | latest | Local default checkpointer |
| `langgraph-checkpoint-postgres` | latest | Production / long-running. Call `.setup()` on first use; manual connections need `autocommit=True` + `row_factory=dict_row` |
| `langchain-core` | transitive | Chat model interface, `usage_metadata` |
| provider packages | optional extras | `[anthropic]`, `[openai]`, `[minimax]`, … — never a hard dep |
| `git` | 2.5+ | `git worktree` |
| LangSmith | **optional** | Tracing. Hosted; must not be required. `acn-report` stays the offline path |

Nothing above may become a requirement of the existing skill. A beastmode user
on bash-only must see zero change.

---

## 8. Out of scope for this effort

- CrewAI binding (layout reserved; implementation is P8, a separate effort)
- LangGraph Platform / hosted deployment
- Replacing any existing harness — hermes / pi / claude / codex adapters are untouched
- Rewriting `scripts/bm` in Python
- Anything that changes the meaning of `schema/*.json`
- Self-modifying graph topology (needs its own approval — Q5)

---

## Sources

- [langgraph · PyPI](https://pypi.org/project/langgraph/) — version 1.2.10, 2026-07-28
- [Interrupts — Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Durable execution — Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/durable-execution)
- [Durability | langgraph | LangChain Reference](https://reference.langchain.com/python/langgraph/types/Durability)
- [Use the graph API — Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/use-graph-api)
- [Deferred nodes in LangGraph — LangChain Changelog](https://changelog.langchain.com/announcements/deferred-nodes-in-langgraph)
- [Memory — Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/add-memory)
- [langgraph-checkpoint-postgres · PyPI](https://pypi.org/project/langgraph-checkpoint-postgres)
- [Why Checkpoints Aren't Durable Execution — Diagrid](https://www.diagrid.io/blog/checkpoints-are-not-durable-execution-why-langgraph-crewai-google-adk-and-others-fall-short-for-production-agent-workflows)
- [CrewAI Flows: Production Multi-Agent Guide 2026](https://www.jahanzaib.ai/blog/crewai-flows-production-multi-agent-guide)
- [LangGraph vs CrewAI: Honest Comparison for 2026](https://fast.io/resources/langgraph-vs-crewai/)
