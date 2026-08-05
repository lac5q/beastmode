# ROADMAP — Beastmode on LangGraph (v2.4.0)

Implementation status: the P1–P7 package, adapter, CLI, persistence, and
documentation work is present in the current `main` worktree. P0.1 produced a
provider matrix with no direct-call provider promoted; the safe subprocess
fallback is therefore the release configuration. P0.2 and P0.3 are complete.
Public push remains behind the repository security-release gate. The completed
Standard scan `4846cd52-de67-4f97-b6a2-c84933241ac9` is mapped into **P7S**
below: one critical, thirteen high, nine medium, two low, and one deferred
candidate. Its snapshot changed while the scan was running, so its findings are
planning input; a clean-snapshot verification scan is still required before
release.

Read `REQUIREMENTS.md` first — it holds the concept mapping, the LangGraph API
facts each phase depends on, and the risk register phases P0–P2 exist to retire.

**Decisions of 2026-08-03** (`OPEN-QUESTIONS.md` Q1, Q2, Q3, Q5) are folded in
below. Q4 and Q6–Q10 remain open but do not block P0.

> ### Invariant 0 — LangGraph is strictly additive
>
> **Beastmode works without LangGraph, exactly as it does today.** No bash
> script, test, schema, doc, or adapter acquires a hard Python dependency;
> `./tests/run-all.sh` passes with zero Python packages installed; no existing
> `bm` invocation changes meaning. This outranks every other consideration in
> this roadmap — where LangGraph idiom and this conflict, this wins. It appears
> as a merge-blocking exit on **every** phase below, deliberately repeated, so
> the dependency cannot leak in one phase at a time.
>
> Corollary: **existing beastmode users are the primary audience.**
> `bm --harness langgraph` is a first-class deliverable. The package is the
> implementation and the channel for LangGraph users arriving from the other
> side; when the two audiences conflict, beastmode users win.

### Current implementation status

- **P0.1:** provider provenance matrix recorded; no provider is approved for
  direct-call judgment seats until a successful live probe proves
  `actual_model`. The default executor path remains subprocess-based.
- **P0.2/P0.3:** interrupt replay and lane-grouping spikes are documented with
  passing evidence.
- **P1–P7:** implemented locally; the dependency-free bash lane, Python tests,
  package build, Studio import, CLI smoke run, and acceptance checks pass.
- **P7S:** required security hardening is planned below; it preserves worker
  capability by moving it behind explicit sandbox grants rather than disabling
  tools globally.
- **P8/P9:** intentionally deferred as separate efforts and gated on P7S.
- **Release:** not complete until P7S is green, generated distributions are
  inspected for sensitive data, and a final clean-snapshot scan passes.

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
  a written interface, test authoring, docs. Every P1–P7 task is specified to be
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
| **P0** | Spikes — retire the unknowns, throwaway code | Support matrix + 3 written verdicts (below). **Gating**: P0.1 decides which seats may be direct-call |
| **P1** | `python/` skeleton, `beastmode.core`, schema loader, CI lane | `pytest` green; import-linter proves `core` has zero framework imports; **`tests/run-all.sh` passes with no Python deps installed** |
| **P2** | Seat layer + provenance: `SeatModel`, `ChildMeta`, drift gate | Every `acn_meta.py` fixture returns the identical verdict through the Python path; negative test per verdict; **bash lane still install-free** |
| **P3** | `graphs/pipeline.py` — the loop as a DAG, gates via `interrupt()` | `--autonomy medium` stops at each gate and resumes on `Command(resume=…)`; `high` does not stop; **bash lane still install-free** |
| **P4** | ACN fan-out: `Send` dispatch, worktree subprocess executors, consolidation | 3-child batch runs concurrently; one child killed pre-meta ⇒ gate fails; main tree unmodified; **bash lane still install-free** |
| **P5** | `bm --harness langgraph` + persistence + mermaid export | `--harness langgraph` preflights and runs a real goal; absent package exits 2 with an install hint, never a traceback; kill/resume completes; **bash lane still install-free** |
| **P6** | **Composability — the LangGraph-user surface**: importable nodes, subgraph embedding, state interop, `langgraph.json` / Studio | A user drops `provenance_gate` into *their own* graph; beastmode embeds as a subgraph in a foreign parent; `langgraph dev` opens it in Studio; **bash lane still install-free** |
| **P7** | Docs, adapter SKILL, parity tests, release | `test-acn-parity.sh` covers the Python state shape; `SKILL.md` v2.4.0; package builds; **bash lane still install-free** |
| **P7S** | Capability-preserving security hardening and public-release gate | All critical/high findings closed; sensitive-data release findings closed regardless of severity; remaining medium/low items fixed or explicitly accepted; final scan targets the exact clean commit; **bash lane still install-free** |
| **P8** | `graphs/forever.py` — the continuous evolver + bounded topology mutation (separate effort) | Gated on P1–P7S |
| **P9** | CrewAI binding (separate effort) | Gated on P8 |

**Two audiences, two finish lines.** P5 is where *beastmode users* get served —
stop after P5 and they have a working upgrade; stop after P4 and they have
nothing they can invoke. **P6 is where LangGraph users get served** — stop
before it and the package is a monolithic take-it-or-leave-it graph that nobody
with an existing LangGraph app can adopt, which forfeits the entire adoption
thesis this effort exists for.

### Cross-cutting requirements (apply to P3, P4 and P5 — not a separate phase)

These are properties, not features, so they are built in rather than bolted on.
Retrofitting any of them is a rewrite of every node.

- **Async-first.** Nodes are `async def`; `ainvoke` / `astream` are the primary
  path with sync wrappers over them. `AsyncPostgresSaver` / `AsyncSqliteSaver`
  for the checkpointers. LangGraph deployments are async, and a sync-only
  library is unusable inside one.
- **Streaming.** `.stream()` and `astream_events` must produce useful output —
  node-level progress, token streams from judgment seats, and subprocess stdout
  from executor seats surfaced as custom stream events. A multi-hour
  orchestrator that only returns a final value is unusable in practice, and it
  is also how the phase report reaches a UI.
- **Accept a `BaseChatModel` directly.** Alias resolution via
  `tier-aliases.json` is a beastmode-ism. A LangGraph user already holds a
  configured model instance; every seat must accept one, with alias resolution
  as the convenience path, not the only path.
- **Retry and idempotency.** Per-node `retry_policy` via `set_node_defaults`,
  and a written statement of which nodes are safe to re-run. Gate nodes replay
  on resume (P0.2); executor nodes must be idempotent against a half-finished
  worktree.
- **Traceable, vendor-neutral, and never load-bearing.** Nodes carry beastmode
  metadata and tags (`goal_id`, `phase`, `seat`, `autonomy`, `requested_model`,
  `actual_model`; tags `drift` / `unverifiable` on a non-`ok` verdict) shaped to
  be OTel-compatible, so the backend is an operator choice rather than a
  rewrite. Two hard constraints: **(a)** each subprocess executor synthesizes a
  child span from the `meta.json` it already writes, or the majority of every
  run's tokens and wall-clock is invisible; **(b)** tracing being off,
  unreachable, or sampled has **zero** effect on any gate verdict — traces may
  display drift, never decide it. See `OPEN-QUESTIONS.md` Q8.

---

## P0 — Spikes

Throwaway code in a scratch worktree. Nothing merges. The deliverable is three
written verdicts and one table. **This phase exists to make P1–P7 estimable**;
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
`references/`, with a **`direct-call viable`** column per provider.

This spike is now **gating**, because Q2 decided that judgment seats
(director / watcher / validator) call chat models directly while executor seats
stay subprocesses. Direct-call seats have no harness journal to fall back on —
provider metadata is the only provenance they will ever have. Any frontier
provider that lands in "echoes the alias" or "reports nothing" is demoted to a
subprocess seat before P2 designs around it. If *no* frontier provider proves
its model, the Q2 fallback applies and every seat becomes a subprocess.

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

## P5 — The `bm` entrypoint and persistence

**The phase that serves the primary audience.** Everything before this is
machinery only a LangGraph user could reach; this is where an existing
beastmode user types one flag and gets the upgrade.

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
- `bm "<goal>" --harness langgraph` runs a real goal end to end with the same
  phase-report / gate / drift prompts as every other harness
- `bm --harness langgraph` with the package absent exits 2 with an install hint,
  never a traceback — and every *other* harness still works on that machine
  (invariant 0, at the entrypoint where it is easiest to break)
- `bm --harness bogus` still exits 2 (regression on `test-bm-model-check.sh`)
- Every pre-existing `bm` invocation produces byte-identical behavior to `main`
- Kill the process mid-phase; re-invoke with the same `thread_id`; the run
  resumes at the last checkpoint and completes
- Time-travel: replay from an earlier checkpoint produces a divergent thread
  without corrupting the original

---

## P6 — Composability: the LangGraph-user surface

**Why this phase exists.** P1–P5 produce one prebuilt `build_pipeline()` graph.
That serves a beastmode user (via `bm`) and a greenfield LangGraph user who is
happy to adopt our whole topology. It serves **nobody who already has a
LangGraph app** — and that is the population the adoption thesis is aimed at.
A monolithic graph is take-it-or-leave-it; the ask was ready-to-use *patterns*
people can copy into their own graphs.

Without this phase the effort ships something technically complete and
strategically pointless.

**Scope**

1. **Nodes as importable primitives.** Every node from P3 is exported and
   independently usable in a foreign graph, with a documented signature and no
   hidden dependency on the rest of the pipeline:
   - `provenance_gate` — the drift/unverifiable check as a drop-in node
   - `autonomy_gate(node)` — a wrapper that adds `interrupt()`-below-`high` to
     *any* node, including the user's own
   - `route_by_verification_cost` — the tier-routing rule as a conditional edge
   - `acceptance_contract` / `mechanical_validation` / `judgment_review`
   - `SeatModel` — usable standalone as a `BaseChatModel` wrapper that records
     requested-vs-actual provenance on any call, in any graph
2. **Subgraph embedding.** `build_pipeline()` compiles cleanly as a subgraph of
   a foreign parent. Concretely: the checkpointer stays on the parent only (per
   `REQUIREMENTS.md` §4), `interrupt()` still propagates to the parent's resume
   path, and the beastmode phase report reaches the parent's stream.
3. **State interop.** `BeastmodeState` is a *mixin over* a user's own state
   schema, not a replacement for it. Documented reducers, a documented reserved
   key prefix, and a test proving a user's unrelated state keys survive a full
   beastmode run untouched.
4. **Custom node injection.** Replace or wrap any seat's node — swap `review`
   for your own reviewer, insert a node before `merge` — without forking the
   package. A `build_pipeline(overrides={...})` seam plus a documented list of
   which nodes are safe to replace and which are load-bearing (the gates are not
   replaceable; that is the point of them).
5. **`langgraph.json` + Studio.** Ship a `langgraph.json` so `langgraph dev`
   picks the graphs up, and confirm the pipeline renders and steps in LangGraph
   Studio. This is how LangGraph users actually inspect a graph, and it is the
   real version of the "living flowchart" story — better than a static mermaid
   file.
6. **Templates, plural.** Not one worked example: a small set of copy-pasteable
   patterns — minimal-gated-loop, ACN-fan-out-only, provenance-gate-only,
   full-pipeline. The provenance-gate-only template is the cheapest possible
   on-ramp and probably the most-used artifact in the whole effort.

**Exit (deterministic)**
- A test builds a **foreign** `StateGraph` (its own state schema, its own
  nodes), drops in `provenance_gate` and `autonomy_gate`, and both behave
  correctly — gate blocks below `high`, drift fails closed
- A test embeds `build_pipeline()` as a subgraph of a foreign parent that owns
  the checkpointer; an `interrupt()` inside the subgraph is resumable from the
  parent
- A user state key unrelated to beastmode survives a full run byte-identical
- `build_pipeline(overrides={"review": my_node})` runs with the replacement;
  attempting to override `gate_provenance` raises rather than silently allowing
  it
- `langgraph dev` serves the graphs; the pipeline renders in Studio
- Each template in the docs is executed by a test, so no published example can
  rot
- **bash lane still install-free**

---

## P7 — Docs, parity, release

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
- `python/README.md` for the PyPI page — leads with the P6 drop-in primitives,
  not with `build_pipeline()`; the smallest on-ramp goes first
- `references/observability.md` — the LangSmith / OTel onboarding page: the
  three env vars, self-hosted `LANGSMITH_ENDPOINT`, what the trace tree looks
  like, how subprocess child spans are reconstructed from `meta.json`, the
  metadata/tag vocabulary, masking options, sampling guidance, and the standing
  rule that tracing is never load-bearing for a gate

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
- With `LANGSMITH_TRACING=true`, one run produces a trace whose executor nodes
  each carry a child span reconstructed from the child's `meta.json` — token
  counts in the trace reconcile against `acn-report`'s phase report
- With tracing off, unreachable, and pointed at a dead endpoint, all three
  produce byte-identical gate verdicts (negative-tested — this is the fail-open
  the rule exists to prevent)

---

## P7S — Capability-preserving security hardening and release gate

P7S is release work, not a feature rollback. Beastmode remains a capable
development tool: workers may still write code, run commands, and use network
access when explicitly granted. The security boundary is that those
capabilities live **inside** the worker environment; untrusted repositories and
worker narratives do not execute in, select evidence for, or mutate the trusted
parent control plane.

Source: sealed Standard scan `4846cd52-de67-4f97-b6a2-c84933241ac9`
(2026-08-04 working-tree snapshot). Coverage was 128/128 files, 31 candidates,
31 validations, and 26 attack paths. One provider-metadata candidate remains
deferred, so the scan's semantic coverage is partial. The scan warned that the
working tree changed during review; its results therefore drive remediation,
but do not satisfy the final release scan.

### P7S design rules

1. **Power stays in the capability plane.** File writes, shell commands,
   package tools, and optional network access run inside the worktree sandbox
   with explicit task grants. Security fixes may scope or broker a capability;
   they may not silently remove a supported workflow.
2. **The parent is a narrow control plane.** Parent code may prepare trusted
   paths, manifests, attestations, validation facts, and merge decisions. It
   never executes target-repository hooks, trusts worker status as validation,
   or passes raw worker narratives as reviewer instructions.
3. **Two deployment postures, one safe default.** `untrusted` is the default
   for arbitrary repositories and requires the complete boundary below.
   `trusted-dev` may relax only documented convenience controls after an
   explicit operator choice; provenance, release scanning, and secret
   redaction never become warn-only.
4. **Environment isolation is enforceable, not prose.** The untrusted profile
   runs in an ephemeral dev container/VM or equivalent boundary without host
   credential mounts, SSH agent, Docker socket, or broad home-directory mounts.
   Network and secret access are separately brokered capabilities.
5. **Public release is a different trust boundary from local development.** A
   successful local run never substitutes for scanning Git history and the
   exact generated wheel/sdist that will be published.
6. **Invariant 0 still outranks the phase.** The dependency-free bash lane
   remains install-free after every P7S subphase.

### P7S.0 — Close parent-boundary code execution

| ID | Sev | Work item | Capability-preserving implementation | Exit |
|---|---:|---|---|---|
| S-01 | critical | Pre-sandbox Git checkout hooks | Disable target hooks and untrusted Git config only for parent worktree preparation; worker Git remains available inside policy | A malicious `post-checkout` fixture never runs before Bubblewrap |
| S-02 | high | Repository-local run-root symlinks | Anchor runs in an owner-only trusted base and use no-follow, descriptor-relative path operations | Every symlink-component and replacement-race fixture fails before an external write |
| S-03 | high | Trusted-helper replacement race | Require trusted ancestors and bind execution to the verified file identity | A helper swapped after verification never executes |
| S-04 | hardening | Parent-side tool resolution | Centralize parent Git/helper invocation around trusted absolute executables and a sanitized environment | A repository-local fake `git` cannot run as the parent |

### P7S.1 — Preserve independent trust decisions

| ID | Sev | Work item | Capability-preserving implementation | Exit |
|---|---:|---|---|---|
| S-05 | high | Caller-selected provenance manifest | Require parent-owned `expected_child_ids`; mutable graph state cannot select the obligation | Omitting a failed child is always `unverifiable` |
| S-06 | high | Fan-out self-validation | Keep fan-out execution, but reserve `validated` for independent validator + provenance gates | Forged worker `execution_status=ok` cannot produce `validated` |
| S-07 | high | Reviewer prompt injection | Give the reviewer a typed report + diff projection; store raw logs separately as untrusted evidence | Adversarial stdout is absent from reviewer instructions and cannot approve work |
| S-08 | medium | Mechanical-validator prompt injection | Give the validator bounded measured facts only; model-backed validators must use a hardened typed contract | Validation is unchanged when worker narratives are adversarial |
| S-09 | high | Missing Pi project policy | Verify policy path, digest, and active extension before `exec pi` | Missing/stale policy blocks Pi without disabling Pi itself |
| S-10 | high | Pi YAML policy parser bypass | Parse frontmatter with Pi-equivalent YAML semantics; reject forbidden keys, aliases, duplicates, and unsupported forms | Differential fixtures cannot encode `permission` or `yoloMode` around the checker |
| S-11 | high | Claude prompt/option injection | Make reviewer prompt transport stdin-only and reject unknown wrapper flags | Dash-prefixed prompts never enter option-parsed argv |
| S-12 | low | Claude stdin prompt exposed in argv | Keep prompt bytes on stdin or a protected descriptor | Process listings contain fixed options only |
| S-13 | medium | Hermes provider regex bypass | Validate provider syntax and compare parsed keys literally | Regex metacharacter providers fail preflight |
| S-14 | medium | Same-UID attestation substitution | Bind evidence to run/child/result with a parent-held nonce or MAC, or explicitly narrow and enforce the principal boundary | Same-UID replacement/replay cannot produce `ok` provenance |

### P7S.2 — Bound resources and process lifetime

| ID | Sev | Work item | Capability-preserving implementation | Exit |
|---|---:|---|---|---|
| S-15 | high | Worker memory/PID/CPU exhaustion | Add cgroup or RLIMIT memory, PID, and CPU quotas plus an aggregate concurrency budget | Allocation, fork, and CPU fixtures are kernel-terminated without affecting the host |
| S-16 | medium | Metadata pre-limit enumeration | Replace per-directory `os.walk` materialization with a bounded incremental walk | A directory beyond the cap fails within bounded memory/time |
| S-17 | medium | Public-guard output buffering | Stream NUL-safe Git records with explicit item/byte/diagnostic limits | Large-history fixtures fail closed without unbounded shell memory |
| S-18 | medium | Studio descendant cleanup | Start a dedicated process group/session and terminate the complete tree | No descendant survives success, timeout, crash, or SIGTERM resistance |

### P7S.3 — Make public release fail closed

| ID | Sev | Work item | Capability-preserving implementation | Exit |
|---|---:|---|---|---|
| S-19 | high | Binary-history and encoded-path secret bypass | Scan reachable historical blob bytes and NUL-safe paths with a fail-closed object limit | Historical binary credentials and control-byte filenames are rejected |
| S-20 | high | Generated distributions not scanned | Build first, unpack wheel/sdist, then scan their exact bytes and paths | A generated-only fake secret blocks release |
| S-21 | high | Packaging resource symlinks | Reject symlinks and require resolved build resources under canonical source roots | External sentinel files cannot enter wheel/sdist |
| S-22 | medium | Runtime redaction gaps | Share credential families between runtime and release guard; redact before stream/persistence | Bare `github_pat_` and `sk-proj-` fixtures never reach traces or state |
| S-23 | high | Mutable branch bootstrap | Publish immutable signed/versioned installer assets and verify before execution | Documentation contains no moving-branch pipe-to-shell path |
| S-24 | medium | Unhashed Python CI artifacts | Generate hash-locked inputs and install with hash enforcement | Altered allowed-version artifact fails before install |
| S-25 | medium | Registry package content integrity | Record/verify package tarball integrity and disable unnecessary lifecycle scripts | Every executable installer dependency has repository-owned integrity evidence |
| S-26 | low | Commit-subject log injection | Omit subjects or render bounded escaped diagnostics | Control bytes never reach public CI logs |
| S-27 | high | Repo-local credential files readable by Pi workers | Preserve ordinary repository reads while denying high-signal package, VCS, container, cloud, and cluster credential filenames at the cross-cutting path surface | `.npmrc`, `.pypirc`, `.netrc`, `.git-credentials`, and representative cloud/container auth files are denied by the canonical enforced policy |
| S-28 | high | Package credentials bypass public release guard | Extend Git-history and archive path/token vocabularies for package registries and adjacent credential families | A real `.npmrc`/`npm_` history fixture and generated archive fixtures fail closed while clean artifacts pass |
| S-29 | CI parity | Hosted runner lacks declared shell/sandbox prerequisites | Install ripgrep explicitly and enable/probe Bubblewrap's user namespace only on the ephemeral least-privilege CI runner | The shell gate finds `rg`; the Bubblewrap probe passes before executor tests; runtime sandbox policy remains fail closed |

### P7S.4 — Resolve the deferred provider bound

Candidate `candidate-a87094c809d2c537` remains follow-up, not silently clean.
Add a supported-provider/fake-provider fixture with oversized nested
`response_metadata` and `usage_metadata`; establish documented maximum size,
depth, and item count; enforce the bound before copying or serializing child
metadata. The candidate must leave P7S as either a tested finding with a fix or
a rejected row with concrete provider-contract evidence.

**Implemented 2026-08-04:** provider response metadata is fixed-key projected,
usage metadata is incrementally bounded by item count/depth/text size, and the
final child document is capped before write. The oversized supported-provider
fixture fails before serialization. Candidate `candidate-a87094c809d2c537` is
therefore resolved as a tested resource-exhaustion case.

### P7S implementation status — 2026-08-04

- [x] S-01–S-04: trusted parent Git/path/helper boundary
- [x] S-05–S-14: independent manifests, validation/review contracts, Pi and
  Claude policy, literal Hermes parsing, authenticated run/result attestations
- [x] S-15–S-18: worker quotas, bounded metadata walking/guard output, complete
  Studio process-group cleanup
- [x] S-19–S-29: raw history and distribution scanning, packaging containment,
  redaction, immutable installer bootstrap, Python/npm artifact integrity, and
  terminal-safe diagnostics, plus repo-local credential isolation and package
  credential release scanning, and hosted-runner sandbox/tool parity
- [x] P7S.4 deferred provider metadata bound
- [ ] Release gate: clean exact-commit security scan, public push, remote CI,
  and branch cleanup

### P7S release exit (deterministic)

- S-01 through S-29 have regression tests. Critical/high rows are closed; any
  remaining medium/low risk has an explicit owner, rationale, and expiry.
- S-19 through S-23 are merge-blocking regardless of accepted severity because
  the operator requirement is **never publish sensitive material**.
- The `untrusted` profile proves worker capability still works: one fixture
  writes only allowed files, runs declared commands, uses explicitly granted
  network access, emits provenance, and reaches review without host credentials.
- The `trusted-dev` profile is explicit, documented, and cannot weaken
  provenance, redaction, or public-release gates.
- `./tests/run-all.sh` passes without Python packages after every subphase.
- `pytest python/tests`, import-linter, package build, Studio smoke, isolated
  wheel smoke, and all security regressions pass from a clean tree.
- `public-artifact-guard --history` scans the exact release commit, and the
  generated-artifact guard scans the exact wheel/sdist selected for release.
- A fresh Codex Security scan targets the exact clean commit and reports no
  open critical/high findings. The scan runs after all edits and immediately
  before public push; a changed-tree warning invalidates the gate.
- Only after those checks may `main` be pushed/tagged. Branch cleanup follows
  successful remote CI, never precedes it.

---

## P8 — `graphs/forever.py` (separate effort, gated)

Not the same thing as P3, and worth stating plainly: P3 ports the *existing*
fixed loop. P8 is the **new capability** — the continuously-cooking evolver that
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

### Bounded topology mutation (decided — Q5)

At `--autonomy high` **only**, the graph may rewrite its own topology. Below
`high`, the existing rule holds unchanged: propose a diff, a human approves it.
This loosens a rule the repo earned, so it ships with four guardrails:

1. **A mutation may not remove or weaken a gate** — not `gate_provenance`, not
   `gate_merge`, not the budget ceiling. `high` is precisely the mode where
   nobody is watching, so a graph that can delete its own drift gate there is a
   graph with no drift gate. Enforced by validating the post-mutation graph
   against a required-node / required-edge set *before* `.compile()`, so an
   illegal mutation cannot run even once.
2. **Mutations are checkpointed and diffable** — pre-mutation topology
   persisted, diff rendered as mermaid, both in the phase report.
3. **Mutation is a surfacing event** — `topology_mutation` is added to
   `high.always_surfaces` in `schema/autonomy-levels.json`, alongside
   `budget_limited`. `high` never means silent.
4. **Bounded per run** — a mutation counter with a ceiling.

This makes `schema/autonomy-levels.json` and `SKILL.md`'s self-improvement
section part of the P7 diff. Note that it is the first time an autonomy level
grants a *capability* rather than merely suppressing a prompt — worth one more
look before P7 starts.

**Gated on:** P1–P7 shipped and P7S release exit green.

---

## P9 — CrewAI binding (separate effort, gated)

A `beastmode.crewai` binding over the same `beastmode.core`: Flows'
`@start` / `@listen` / `@router` wrapping the same seats, contract, provenance
gate, and reports. Its exit criterion is that it adds **no** logic already in
`core` — if it needs to reimplement the gate, P1's boundary failed and that is
the finding.

**Gated on:** P8, and a decision that CrewAI adoption is still worth it then.

---

## Success criteria for the effort

In priority order — the first one decides ties.

1. **A bash-only beastmode user installs nothing and sees no change.**
   Invariant 0. Asserted on every phase, not just at the end.
2. **An existing beastmode user types `bm --harness langgraph` and gets an
   upgrade** — the same loop, now with durable checkpoints, resumable runs,
   `interrupt()`-backed gates, and an inspectable graph.
3. A LangGraph user `pip install`s the package, imports one builder, and gets
   tier routing + contracts + drift gates + autonomy gating without reading
   `SKILL.md`.
4. The invariants in `REQUIREMENTS.md` §2 hold, each asserted by a test that was
   negative-tested by deliberately breaking it.
5. `schema/*.json` is still the only source of truth; no field list exists twice.
6. `scripts/lib/acn_meta.py` is still the only gate implementation.
7. `beastmode.core` has zero framework imports, proven by CI.
8. Capability remains available behind explicit sandbox grants; no security
   fix moves untrusted execution into the parent or turns a gate into prose.
9. Public release scans both complete Git history and exact generated
   distributions, and a changed tree invalidates the final security gate.
