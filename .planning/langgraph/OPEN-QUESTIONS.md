# Open questions — Beastmode on LangGraph

Q1–Q3 change the phase order in `ROADMAP.md` and should be answered before P1
starts. Q4–Q10 can be answered during P0/P1. Each has a recommendation, so
silence is not a blocker — but a different answer means different phases.

**Q1, Q2, Q3, Q5 are now DECIDED** (2026-08-03) — see the ✅ blocks. Q4, Q6–Q10
remain open.

---

## Q1 — What is the deliverable, exactly? (**blocks P1**)

> ### ✅ DECIDED — "Beastmode must still work without LangGraph. It's an upgrade for beastmode users."
>
> This is neither A nor B nor C as posed — it's a **constraint that outranks the
> question**, plus a priority. Recorded as:
>
> **C1 (hard constraint, non-negotiable): LangGraph is strictly additive.**
> Beastmode without LangGraph works exactly as it does today. No bash script,
> no test, no schema, no doc, and no adapter acquires a hard Python dependency.
> A user who never installs the package sees zero behavior change. This is
> promoted out of the risk register (§5.4) into `REQUIREMENTS.md` §2 as
> **invariant 0**, and it is a merge-blocking exit on every phase — not a
> footnote.
>
> **C2 (priority): existing beastmode users are the primary audience.**
> `bm --harness langgraph` is therefore a first-class deliverable, not a P5
> afterthought. The package still ships (it's the implementation, and it's the
> adoption channel for LangGraph users), but "beastmode users get an upgrade
> and lose nothing" is the success criterion that decides ties.
>
> *Assumption flagged for correction:* read as "must still work **without
> LangGraph**". If "Langston" meant something else, say so — C1 is doing a lot
> of load-bearing work.

Three different products hide behind "enable LangGraph":

- **A.** `pip install beastmode-langgraph` — a package for *LangGraph users*.
  They never run `bm`. Highest adoption ceiling; largest new surface (packaging,
  releases, docs for an audience that has never heard of beastmode).
- **B.** `bm --harness langgraph` — a fifth harness for *beastmode users*.
  Smallest change; near-zero adoption value, because it serves people who are
  already here.
- **C.** Both — the package is the implementation, `bm --harness langgraph`
  is a thin caller. One artifact, two audiences.

**Recommendation: C.** It costs almost nothing over A (the `bm` flag is ~20
lines) and it keeps the package honest: if the package can't run a real
beastmode goal from `bm`, it isn't finished. The roadmap is written for C —
package in P1–P4, `bm` flag in P5.

---

## Q2 — Do LangGraph nodes call models, or drive subprocesses? (**blocks P3/P4**)

> ### ✅ DECIDED — C: split by seat.
>
> Judgment seats (director, watcher, validator) call chat models directly —
> they read and decide, they don't write files. Executor seats spawn the
> existing coding agents (`pi`, `claude -p`, `codex exec`, `delegate_task`) as
> subprocesses in `git worktree`s.
>
> Consequences now locked into the roadmap:
> - Hard rule 1 survives untouched, because the only nodes that write files are
>   still separate processes with their own permission config.
> - Direct-call judgment nodes depend on provider response metadata for
>   `actual_model`. **P0.1 is now gating**: if a frontier provider we intend to
>   use can't prove the serving model, its judgment nodes are `unverifiable` and
>   must fall back to subprocess. P0.1's exit adds a per-provider
>   direct-call-viable column.
> - Fallback if P0.1 goes badly: option B (all seats subprocess).

This is the single biggest architectural call, and it decides whether hard
rule 1 survives.

- **A. Nodes call chat models directly.** Beastmode becomes a full agent
  runtime. Clean LangGraph idiom, best LangSmith traces. But nodes run in the
  orchestrator's process with the orchestrator's credentials — "workers never
  commit/push", "never access secrets", "stay in `allowed_paths`" become prose
  again, and drift detection depends entirely on provider metadata (risk 5.1).
- **B. Nodes spawn the existing coding agents** (`pi`, `claude -p`,
  `codex exec`, `delegate_task`) as subprocesses in `git worktree`s. LangGraph
  replaces `bm`'s *control flow*, not the executor. Every existing guarantee
  survives untouched because the executor is unchanged. Beastmode becomes a
  harness-of-harnesses.
- **C. Both** — frontier/judgment nodes call models directly (they only read and
  decide), executor nodes are subprocesses (they write files).

**Recommendation: C, with B as the fallback if P0.1 says provenance is
unprovable.** The seats already split this way: directors and watchers produce
*judgments*, executors produce *diffs*. Only the second needs isolation. And it
gives the honest product story — "beastmode orchestrates your coding agent"
rather than "beastmode is another coding agent".

---

## Q3 — Which graph ships first? (**blocks P3 vs P7 ordering**)

> ### ✅ DECIDED — A: pipeline first, evolver as P7.
>
> Phase order in `ROADMAP.md` stands as written. The evolver stays gated on
> every phase before it (now P8 — a composability phase was later inserted at P6).

Your two messages describe different graphs:

- **A. The pipeline** — the current eight-step loop as a terminating DAG with
  `interrupt()` gates. A faithful port. Low risk; proves every invariant
  survives; ships something LangGraph users can use immediately.
- **B. The evolver** ("ForwardEditor" style) — PRD maintainer, priority curator,
  brainstormers, implementer, reviewer, context re-packer, cleanup, user-redirect
  edge. Cyclic, non-terminating, runs for days. This is the *new* capability and
  the thing the original post is actually about.

**Recommendation: A first, B as P7.** Not out of caution — B genuinely needs
things A builds: the provenance gate in state, ACN via `Send`, worktree
executors, checkpointing. Building B first means building all of A anyway, with
no gate to catch mistakes. But if the *point* is the evolver and the pipeline is
uninteresting to you, say so — the roadmap collapses to a much smaller P3 and
P7 moves up.

---

## Q4 — One distribution or two? (**P1**)

`beastmode-core` + `beastmode-langgraph` as separate PyPI packages, or one
`beastmode` package with `[langgraph]` / `[crewai]` extras?

**Recommendation: one package, extras.** Two packages means two release
cadences and a version-compatibility matrix for a project that has never
released a Python package at all. The `core` boundary is enforced by
import-linter either way — that's what actually protects the CrewAI future, not
the packaging split.

---

## Q5 — May the graph rewrite itself?

> ### ✅ DECIDED — B: topology mutation permitted at `--autonomy high` only.
>
> This **loosens a rule the repo earned**, so it ships with guardrails rather
> than as a bare permission. Below `high`, the notes-only rule is unchanged: the
> graph proposes a topology diff, a human approves it.
>
> Guardrails (proposed — these are my constraints, not your instruction; push
> back on any of them):
>
> 1. **A mutation may not remove or weaken a gate.** Not `gate_provenance`, not
>    `gate_merge`, not the budget ceiling. A graph that can delete its own drift
>    gate at `high` autonomy is a graph with no drift gate — `high` is exactly
>    the mode where nobody is watching. Enforced by validating the post-mutation
>    graph against a required-node/required-edge set before it is compiled.
> 2. **Mutations are checkpointed and diffable.** The pre-mutation topology is
>    persisted, the diff is rendered as mermaid, and both land in the phase
>    report. A self-edit nobody can read is not auditable.
> 3. **Mutation is a surfacing event.** `schema/autonomy-levels.json` gets
>    `topology_mutation` added to `high.always_surfaces`, alongside
>    `budget_limited` and the watcher-unavailable case. `high` never means
>    silent.
> 4. **Bounded per run.** A mutation counter with a ceiling, so a graph cannot
>    churn its own shape indefinitely.
>
> This makes `schema/autonomy-levels.json` and `SKILL.md`'s self-improvement
> section part of the P7 diff, and it is the first time an autonomy level grants
> a *capability* rather than just suppressing a prompt. Worth a second look
> before P7 starts.

Your framing includes "self-improvement loop that rewrites the orchestration
itself" and "a graph agents can walk, branch, or rewrite". Today that is
explicitly forbidden: *"The self-improvement loop writes notes only during a
beastmode run. Any lasting change to agent behavior belongs in a separate
user-approved maintenance task."*

Options: (a) keep the rule — the graph proposes topology diffs, a human
approves; (b) allow topology mutation inside a run at `--autonomy high` only;
(c) drop the rule.

**Recommendation: (a).** This rule was earned. Note that (a) still gets you most
of what you want, because in LangGraph the topology *is* data — a node can emit
a proposed graph diff, render it as mermaid, and open it as a PR. That is a
better artifact than a silent self-edit, and it's reviewable.

---

## Q6 — What happens on a provider that can't prove `actual_model`?

If P0.1 finds a provider that echoes the alias rather than the resolved model,
every direct-call child on that lane is `unverifiable` — a red gate, forever.

Options: (a) document it unsupported for direct-call nodes (subprocess
executors still work, since the harness writes its own meta); (b) add a
`provenance: best-effort` mode that downgrades those to a warning; (c) block
the provider entirely.

**Recommendation: (a).** (b) is exactly the fail-open the v2.3 review closed —
"we could not tell which model ran this" is not a pass, and a `best-effort` flag
is how that comes back.

---

## Q7 — Does this ship to PyPI under your name, and when?

Adoption depends on a real, installable, discoverable package. That means a
PyPI namespace, a release process, a support surface, and issues from people
who don't use any of your harnesses.

Is `beastmode-langgraph` the name (is it free on PyPI)? Publish at P6, or hold
until P7 makes the evolver story real? **Recommendation: publish at P6.** The
pipeline alone is useful, and shipping early gets the API critiqued before P7
builds on it.

---

## Q8 — Is LangSmith allowed to be the observability story?

It's the natural fit and the thing LangGraph users already have. It is also
hosted, which means run metadata leaves the machine.

**Recommendation: optional, off by default,** with `acn-report` as the offline
path. If a beastmode run's phase report requires a SaaS account, cost discipline
and provenance stop being self-contained.

### How onboarding actually works — scoped design

Still open as a *policy* question (do we bless it?), but the *mechanics* are
settled enough to scope, because two of them are non-obvious and one is a trap.

**1. The graph traces itself for free.** Three env vars and every node becomes a
span:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=...
export LANGSMITH_PROJECT=beastmode          # optional, defaults to "default"
export LANGSMITH_ENDPOINT=https://...       # self-hosted only
```

No code change. `graph.ainvoke()` produces a trace tree with one run per node,
nested correctly, with token usage on every model call.

**2. The subprocess executors are a hole, and they're where the run actually
lives.** Per Q2, executor seats are `pi` / `claude -p` / `codex exec`
subprocesses. LangSmith sees a node that took eight minutes and returned a
dict — the implementation work, the tool calls, and the majority of the run's
tokens and wall-clock are all invisible. Tracing that shows only the cheap half
of a cost-discipline framework is worse than no tracing, because it looks
complete.

LangSmith supports distributed tracing via a `langsmith-trace` header and a
`tracing_context` manager, but that only helps when the child process is itself
LangSmith-aware. `pi`, `codex exec`, and `claude -p` are not.

**The fix falls out of something beastmode already does.** Every child already
writes a `meta.json` with `usage`, `requested_model`, `actual_model`,
`stop_reason`, `files_changed`, `commands_run`, and `verify`. **That record is a
span.** The executor node synthesizes a LangSmith child run from it after the
subprocess exits, attached to the node's own run as parent (the SDK's `parent`
accepts a `RunTree` or a dotted-order string). No new artifact, no new
collection, no change to the worker contract — the provenance record beastmode
already requires becomes the trace.

**3. The trap: LangSmith must never become the source of truth for the gate.**
LangSmith records what the SDK reports, which is exactly the `response_metadata`
P0.1 is investigating. It is therefore tempting to read drift out of the trace.
Don't. The gate stays `scripts/lib/acn_meta.py` reading `meta.json` off disk.
Tracing being off, unreachable, rate-limited, or sampled must have **zero**
effect on whether a run is `validated`. An observability outage that turns a
safety gate green is the same fail-open class the v2.3 review closed twice.

Traces may *display* drift; they may never *decide* it.

**4. What to attach so the trace is useful to beastmode specifically.** Default
LangGraph traces show node names and tokens. Beastmode needs its own vocabulary
on them:

- `metadata`: `goal_id`, `thread_id`, `phase`, `seat` (director/watcher/executor),
  `autonomy`, `harness`, `requested_model`, `actual_model`, `beastmode_version`
- `tags`: `beastmode`, `phase:design`, `seat:executor`, and — the valuable one —
  `drift` / `unverifiable` stamped on any run whose gate verdict wasn't `ok`

That last tag is the whole payoff: "show me every run in the last month where a
child drifted off its pinned model" becomes a filter instead of a grep across
run directories.

**5. Privacy is the real blocker, not cost.** Beastmode prompts contain the
codebase — diffs, file contents, repo paths, design packages. The worker
contract keeps secrets out of *prompts*, but source code is not nothing. Three
postures, in order of preference:
- **self-hosted LangSmith** via `LANGSMITH_ENDPOINT` — traces never leave your
  network
- **input/output masking** — LangSmith supports hiding inputs/outputs; confirm
  the exact env-var / anonymizer surface at implementation time rather than
  trusting this doc
- **off** — the default

**6. Cost, for the evolver.** LangSmith bills on ingested traces. A `forever`
graph at high fan-out running for days generates enormous span volume. Sampling
policy is a prerequisite for that phase, not a tuning step after it.

**7. OpenTelemetry is the escape hatch.** LangSmith has native OTel support in
both directions — the SDK exports OTLP, and `OTEL_EXPORTER_OTLP_ENDPOINT` /
`OTEL_EXPORTER_OTLP_HEADERS` redirect it anywhere. So the instrumentation
decision and the vendor decision are separable: instrument once, and let the
operator point it at LangSmith, Langfuse, or their own collector. **Design the
metadata and span shape as OTel-compatible from the start**, so choosing a
backend never means re-instrumenting.

---

## Q9 — What's the budget ceiling for a `forever` run?

P7 has no natural termination. Beastmode has autonomy levels but no spend cap
primitive, and LangGraph has no equivalent of `pi-loop-police`'s anti-spin
breaker.

Needed before P7: a hard token/dollar ceiling per thread, a stall detector
(N cycles with no diff), and what happens at the ceiling — `interrupt()` and
wait, or halt.

---

## Q10 — Does `acn_meta.py` move?

A `pip`-installed package can't reach `scripts/lib/acn_meta.py` in a repo that
may not be checked out. Either it moves into `beastmode/core/` and the bash
scripts import it from there, or the package vendors a copy.

**Recommendation: move it.** Vendoring is how "one contract, two
implementations" comes back. One file, one location, both callers import it.

---

## Not questions, but things worth knowing before you commit

- **This adds a dependency tree to a repo that has none.** `langgraph` pulls
  `langchain-core` and its transitive set. The bash lane must stay
  install-free — that constraint is in the roadmap exits, but it's worth
  deciding you actually want the split rather than discovering it in P1.
- **Checkpoints are not durable execution.** The checkpointer saves state; it
  does not detect that your process died. "Runs for days while you ignore it"
  needs a supervisor outside LangGraph. Any claim made before that exists is
  false.
- **CrewAI Flows shares no API shape with `StateGraph`.** The only thing that
  transfers is `beastmode.core`. That's why the core split is P1 and not a
  refactor later — it's the entire cost of "in a perfect world it works with
  CrewAI too", paid once and up front.
- **Prompt-cache lane grouping may not survive `Send`.** It's a real cost line
  in `SKILL.md` and LangGraph has no primitive for it. P0.3 measures it rather
  than guessing.
