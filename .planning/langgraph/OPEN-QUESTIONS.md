# Open questions — Beastmode on LangGraph

Q1–Q3 change the phase order in `ROADMAP.md` and should be answered before P1
starts. Q4–Q10 can be answered during P0/P1. Each has a recommendation, so
silence is not a blocker — but a different answer means different phases.

---

## Q1 — What is the deliverable, exactly? (**blocks P1**)

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
