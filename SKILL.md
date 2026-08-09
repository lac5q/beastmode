---
name: beastmode
description: >
  Multi-agent orchestration framework for high-intensity feature implementation.
  Routes work across model tiers: frontier models (Claude Fable, Kimi 3, Opus;
  Codex only when explicitly selected) own design, architecture, and review sign-off,
  while the pinned Luna Max economy lane handles implementation and mechanical
  validation in isolated worktrees,
  with a self-improving learning loop that promotes lessons back into skills.
  Harness-agnostic: works with Hermes ACN (async parallel sub-agents), Pi,
  Claude Code, Codex, Ultraswarm, GSD, delegate_task, or manual orchestration.
version: 2.5.0
author: Luis Calderon
tags: [beastmode, orchestration, multi-agent, cost-optimization, model-routing, self-improving, worktrees]
related_skills: [ultraswarm, gsd, subagent-driven-development, self-improvement]
agents: [hermes, codex, openclaw, claude-code, fable, kimi, minimax]
---

# Beastmode: Multi-Agent Orchestration Framework

Beastmode is a structured approach to multi-agent software development that separates high-judgment work (planning, architecture, review) from routine execution (implementation, tests, docs) across different model tiers, with strict cost discipline and a self-improving learning loop. It is designed for MofA (Mixture of Agents) orchestration and pairs well with MemroOS/memroos-style durable memory for long-running agent goals.

**Harness-agnostic:** Works with Ultraswarm, GSD, `delegate_task`, Claude Code subagents, or manual orchestration. No specific tool required.

## Core Principle

**Frontier models design. Cheap models build and validate. The loop learns.**

- **Director/Lead (Design tier):** Frontier model (Claude Fable, Kimi 3, or Opus) owns intent, architecture, creative judgment, and final sign-off. Codex is an explicit opt-in lane only.
- **Watcher/Reviewer:** Adversarial reviewer (frontier or mid-tier: Fable/Kimi 3/Opus) challenges plans, gates merges, and catches scope creep. Codex is used here only when explicitly named.
- **Executor (Execution tier):** Luna Max (`openai-codex/gpt-5.6-luna`, reasoning `max`) handles routine implementation *and mechanical validation* (running tests, lint, typecheck, diff summaries) in isolated worktrees. Legacy MiniMax/Qwen lanes remain explicit overrides only.
- **Harness:** Any orchestration tool (Ultraswarm, GSD, `delegate_task`, Claude Code subagents, or manual git workflow).
- **Memory:** Self-improvement loop records lessons and promotes repeated patterns into skills/config.

## Model Tiers & Routing

Beastmode routes every unit of work to a tier, not a specific model. Pick the best available model in each tier for your environment.

**One vocabulary (v2.2):** model **families**, **tiers**, **seats**, **autonomy levels** (including interview scaling), and the **ACN fan-out contract** are defined once, machine-readably, in `schema/` (`families.json`, `tiers.json`, `seats.json`, `autonomy-levels.json`, `acn-contract.json`). Every harness adapter and every doc references that schema — if prose and schema disagree, schema wins. Human-readable views: `references/families-tiers-seats.md`, `references/autonomy-levels.md`, `references/acn-contract.md`, `references/tier-aliases.md`.

| Tier | Example models | Owns |
|------|---------------|------|
| **Design (frontier)** | Claude Fable (`claude-fable-5`), Kimi 3, Claude Opus, Codex/GPT frontier | Intent interpretation, architecture, API/data-model design, tradeoff decisions, acceptance contracts, final review sign-off, escalations |
| **Execution (economy)** | Luna Max (`gpt-5.6-luna`); explicit legacy MiniMax/Qwen/Haiku overrides | Implementation, tests, docs, refactors, scripts, **mechanical validation** (run test suites, lint, typecheck, build, produce structured pass/fail reports) |

**The routing principle: verification cost, not task type.**

A task is safe for a cheap model exactly when its output can be **cheaply and objectively verified** — tests pass, schema validates, the diff matches a concrete spec. A task needs a frontier model when verification is expensive or subjective — "is this the right architecture?", "does this match user intent?". Phase labels (design/implement/validate) are just the common case of this rule, not the rule itself.

This reframes the frontier model's job: **its primary output is not code or even plans — it is verifiability.** The design phase converts an unverifiable goal ("build the feature well") into verifiable tasks (concrete interfaces + acceptance contract + verification commands). Once that conversion happens, the cheap tier can do everything downstream, because failures are caught by the verifier, not by expensive review.

**Routing decision, per task:**
1. Is there a cheap objective verifier for this task's output? → **Economy tier**, cheap-first cascade (retry once on failure, then escalate).
2. No verifier exists? → Don't route it to frontier by default. First ask: **can the current lane create a verifier** (tests, contract, checklist)? If a frontier judgment is genuinely required, stop and ask the user to name the model; never silently escalate.

**Validation is split in two:**

1. **Mechanical validation (cheap):** The executor tier runs verification commands, collects results, and produces a structured report (what passed, what failed, diff stats). This is deterministic work — never spend frontier tokens on it.
2. **Judgment review (frontier):** The design tier reads the *report + diff*, not the raw logs, and makes the merge decision. One frontier pass per phase, at the gate.

See `references/model-routing.md` for the verification-cost routing rule in full, the per-phase routing table it implies, provider configuration examples, and the escalation ladder.

## When to Use Beastmode

Use beastmode for complex tasks that need:
- Multi-phase workflows with planning and review gates
- Multiple workstreams or files
- High-stakes architecture/product/creative judgment
- Cost-efficient execution under an expensive lead model
- Strong QA and merge gates
- A reusable learning loop

**Do not use beastmode for:**
- Trivial one-file edits (use the cheap executor directly)
- Simple questions or information retrieval
- Tasks that don't benefit from role separation

## Two Beastmode Variants

### Variant A: Frontier-Led Beastmode (Fable / Kimi 3 / Opus)

**Use when:** You have a frontier model available as the lead (Claude Fable, Kimi 3, Claude Code / Opus) and need maximum judgment for product/creative/architecture decisions.

**Role split:**
- **Director (Fable / Kimi 3 / Opus):** Intent, architecture, design docs, creative judgment, final sign-off
- **Watcher (Codex/GSD or a second frontier model):** Adversarial planning, scope/cost review, merge gating — pairing two different frontier models (e.g. Fable designs, Kimi 3 challenges) catches blind spots a single model family misses
- **Executor (Luna Max):** Implementation, tests, docs, scripts, mechanical refactors, and mechanical validation (running verification commands, producing pass/fail reports)

**Key rule:** The frontier lead must aggressively avoid spending tokens on routine implementation *or* on watching test output scroll by. Delegate file edits, test writing, docs, refactors, command execution, and validation runs to the executor tier; the lead only reads the structured validation report and the diff.

### Variant B: Explicit Codex-Led Beastmode

**Use when:** The user explicitly names Codex for this bounded task. Codex/GSD leads, with Luna Max executing routine work.

**Role split:**
- **Director/Reviewer (Codex/GSD or current session):** Planning, review, merge decisions
- **Executor (Luna Max):** Implementation, tests, docs, scripts, mechanical validation
- **Escalation:** On security, auth, payments, data-loss, production incidents, or failed executor attempts, stop and ask the user to name the frontier lane. Codex or another frontier model runs only after explicit selection.

**Key rule:** Delegate routine work to the executor tier, but don't merge until the lead verifies acceptance.

## Hard Rules

1. **Main tree stays clean.** Executors work in isolated worktrees/branches. Never let cheap executors directly mutate the main working tree unless the task is tiny and explicitly approved by the lead.
2. **Lead reviews, executor implements.** The lead can plan, inspect, test, and merge. Routine work goes to the executor.
3. **Every phase has an acceptance contract.** Define goal, non-goals, verification commands, and escalation triggers before delegation.
4. **Every phase improves the loop.** Record learnings, errors, routing mistakes, and token/cost surprises. Promote repeated lessons into skills/config.
5. **Escalation doesn't skip self-improvement.** Record why the cheap route failed and whether routing rules should change.
6. **Usage is reported per phase, not just at the end.** Every phase closes with a usage report: requested vs actual model per task, tokens used vs phase budget, actual vs estimated time (see `references/autonomy-levels.md` for the format). If the harness doesn't expose a value, say "unavailable" — never omit the report.
7. **Model drift always surfaces, and so does not knowing.** If a task was served by a model other than the requested `provider/model` (router fallback, harness default, silent substitution), flag it as MODEL DRIFT in the phase report immediately, at every autonomy level. Drifted work is not `validated` until re-validated under the correct tier. A task whose serving model cannot be established at all is **unverifiable** and is treated the same way — never let a silent "unavailable" read as a pass.
8. **Gates are blocking below high autonomy.** At `low` and `medium` autonomy (medium is the default), the run stops at each phase gate — report, then wait for approval before the next phase or any merge. Only `--autonomy high` proceeds through gates automatically, and even it halts on its always-surface events.
9. **Codex and frontier escalation are explicit-only.** Automatic/background work uses the pinned Luna Max economy lane. Codex, GPT frontier profiles, Claude, Kimi, Fable, or any other frontier lane may run only when the user explicitly names that model/lane for the bounded task. If a worker fails or a risk trigger appears, stop, report the evidence, and ask before switching lanes. Never silently fall back, escalate, or inherit a frontier session default.
10. **Public GitHub release is security-gated.** Before every public push, merge, or deployment, run the repository security scan and inspect its completed coverage/findings artifacts. Never publish credentials, tokens, private keys, local auth files, or sensitive environment values. An unresolved security blocker stops the release.
11. **No silent assumptions.** Material ambiguity is either asked (per the autonomy interview matrix in schema/autonomy-levels.json) or recorded as an explicit Assumption in the acceptance contract and surfaced at the next gate. Workers never interview the user — they return needs_decision items in their meta/report and the director surfaces them at the gate.

## The ACN Layer (Async Parallel Sub-agents)

Beastmode's execution fan-out is **ACN**: async parallel sub-agents. Every supported harness has a native primitive for it, and v2.2 makes them obey **one contract** (`schema/acn-contract.json`, human view `references/acn-contract.md`):

| Harness | ACN primitive | Adapter |
|---|---|---|
| **Hermes** | `delegate_task` background + batch (default 3 concurrent, live transcripts, `/agents` overlay, orchestrator children) | `adapters/hermes/SKILL.md` |
| **Pi** | `pi-dynamic-workflows` `agent()` / `parallel()` / worktrees | `pi/SKILL.md` |
| **Claude Code** | Task subagents, `/batch` worktrees, parallel `claude -p` | `adapters/claude-code/SKILL.md` |
| **Codex** | parallel `codex exec` + worktrees, external cheap lanes | `adapters/codex/SKILL.md` |
| **LangGraph** | `StateGraph` + `Send` fan-out, checkpointed `interrupt()` gates, subprocess executors | `adapters/langgraph/SKILL.md` |

The shared rules (all harnesses):

1. **Preflight every seat's model** before fan-out (`scripts/enforce-models`); missing → exit 2 with alternatives.
2. **Pin the executor model on children.** Never let economy work silently inherit a parent/session default. If the runtime cannot prove the child's model, the child is an unverified draft lane — never `validated`.
3. **Parallel by default** for independent executor slices; group same-lane workers (prompt-cache warmth); default concurrency 3 unless the harness is explicitly configured higher.
4. **Background where supported** — the director doesn't block the chat path waiting on workers (Hermes background batches or explicitly requested Codex/Claude parallel sessions). Orchestrator children may wait to synthesize. Automatic background workers are Luna Max only.
5. **Consolidate → mechanical validation (economy) → watcher judgment (frontier) → gate by autonomy.**
6. **MODEL DRIFT always surfaces** (requested vs actual per child, `meta.json` shape in `schema/acn-contract.json`) and blocks `validated` at every autonomy level. `scripts/acn-report` normalizes child metas into the phase report; `scripts/enforce-models --check-meta <dir>` is the gate. Both run the same checker (`scripts/lib/acn_meta.py`), so they cannot disagree about whether a batch is validated.
7. **Unprovable provenance fails closed.** A child whose `meta.json` is missing, unreadable, or reports a single merged `model` instead of `requested_model` + `actual_model` is **unverifiable** — the gate exits non-zero on it exactly as it does on drift. "We could not tell which model ran this" is not a pass. An ACN run that produced no child metas at all is likewise a failure unless you assert `--allow-empty`.
8. **Every child proves liveness; wall-clock never decides.** Embed a unique `BM-RUN: <id>` marker per dispatch (after the shared contract, so the cached prefix stays byte-identical) and arm a bounded startup probe (default 3 min) WITH the dispatch that finds the marker in the child's session artifact (codex rollout under `~/.codex/sessions/`, harness journal, or out-file). Judge long runs by progress signals — CPU time accruing, session artifact growing, output growing — never elapsed time. All signals flat = HUNG: kill the child AND its watchers, smoke the lane *after* killing (hung processes can wedge subsequent dispatches on the same lane), re-dispatch once; a second consecutive hang stops the retry loop and goes to the operator with a lane-substitution proposal. Any signal advancing = WORKING: never killed without operator approval. Watchers are always iteration-capped with an explicit failure line — an unbounded `until` loop whose condition can no longer come true becomes an orphan that "runs for hours". Prefer short inline child prompts pointing at an instruction file over long inline prompts (observed 2026-08-04: 3/3 long-inline codex dispatches hung at startup; all file-pointer and short dispatches succeeded). Full procedure: `references/child-liveness.md`.

### Luna Max throughput and Claude subscription validation

`luna-max` is the approved low-cost worker alias: `openai-codex/gpt-5.6-luna`
with `reasoning=max`. Use ACN's default concurrency of three for independent
Luna slices, with a pinned model and a per-child `meta.json`; do not create
duplicate slices just to increase the count. Close each batch with one
mechanical report and one judgment watcher.

Claude Pro/Max validation is a separate, explicit lane. Run one watcher only
through `bm --harness claude --frontier fable|opus|opus5
--claude-subscription`, which invokes `claude -p --permission-mode plan` and
uses the signed-in subscription quota. The switch rejects non-Claude harnesses
and multi-seat Claude fan-out, so subscription quota is never consumed by
bulk workers.

## Choosing Your Harness

Beastmode works with any orchestration harness. Choose based on your environment:

### Runner CLI (`bm`)

For one-shot goals without writing a full plan: `bm "<goal>"` from any repo.
Parses `--harness hermes|pi|claude|codex|langgraph` (default `pi`), `--gsd`,
`--frontier <alias>`, `--economy <alias>`, `--watcher <alias>`,
`--on local|<host>`, `--autonomy low|medium|high` (default `medium`). Tier
aliases resolve via `scripts/tier-aliases.json` — `kimi3` →
`kimi-coding/k3`, `fable` → `anthropic/claude-fable-5`, `luna-max` →
`openai-codex/gpt-5.6-luna`, `grok` → `xai-oauth/grok-4.5`, etc. Override per-repo
with the user-global `~/.beastmode/tier-aliases.json`. Repository-local
aliases are ignored unless the operator explicitly sets
`BM_TRUST_REPO_ALIASES=1` after review. See `scripts/bm` and
`references/autonomy-levels.md`.

Before spawning, `bm` runs `scripts/enforce-models` to preflight each
resolved `provider/model` for the selected harness (pi: `pi --list-models`;
hermes: provider presence in Hermes config/auth; claude/codex: CLI presence).
If any are missing, `bm` exits with code 2 and prints the available
alternatives, so a goal never starts against an unresolvable model. Skip
with `BM_SKIP_MODEL_CHECK=1` (CI / scripted runs). The check is also
skipped when `--on` is not local (the remote host owns availability).
Postflight, `enforce-models --check-meta <dir>` and `scripts/acn-report`
detect MODEL DRIFT from child metas and emit the phase usage report.

### Harness 1: Ultraswarm (Preferred for Git Repos)

**Use when:** You have Ultraswarm installed and want worktree isolation, adaptive QA, merge gates, and cost reporting.

**Commands:**
```bash
ultraswarm run "<task + acceptance contract>" --repo . --provider auto --mode direct
ultraswarm qa <task-id>
ultraswarm merge <task-id> --repo . --approved
ultraswarm report
```

**For multi-phase work:**
```bash
ultraswarm plan "<goal>" --repo . --mode gsd
ultraswarm run "<goal or phase>" --repo . --provider auto --mode gsd
```

### Harness 2: GSD (Get Shit Done)

**Use when:** The repo already uses GSD for planning/phase management.

**Commands:**
```bash
gsd-plan-phase "<phase goal>"
gsd-execute-phase "<phase>"
gsd-verify-work
gsd-ship
```

Let GSD handle planning/phase gates, and delegate routine implementation units to the Luna Max executor tier via Ultraswarm or `delegate_task`.

### Harness 3: delegate_task (Hermes/OpenClaw)

**Use when:** You're in Hermes or OpenClaw and need subagent orchestration without worktrees.

> **v2.2:** For full beastmode runs on Hermes, use the ACN adapter at `adapters/hermes/SKILL.md` (background batches, model pinning, meta.json, drift fail-closed) via `bm "<goal>" --harness hermes`. Raw `delegate_task` remains the fallback for small parallel tasks.

**Example:**
```python
delegate_task(
    goal="<tight task with acceptance contract>",
    context="Repo, acceptance contract, files, verification commands, commit requirement",
    toolsets=['terminal', 'file']
)
```

**Note:** `delegate_task` doesn't provide worktree isolation. Use for small parallel tasks or when worktrees aren't needed.

**Cache note:** `delegate_task` gives each subagent a fresh context, so the shared
prefix (repo path, acceptance contract, verification commands) is re-sent every call.
Keep that `context=` block byte-identical across delegations and fire them
consecutively — the first pays a 1.25x write, the rest read at 0.10x while warm.
Re-wording the context per task, or interleaving delegations with other model calls,
forfeits that.

### Harness 4: Claude Code Subagents

**Use when:** You're in Claude Code and want to spawn subagents for routine work.

> **v2.2:** Use the adapter at `adapters/claude-code/SKILL.md` (Task, `/batch` worktrees, parallel `claude -p`, permission-mode autonomy mapping) via `bm "<goal>" --harness claude`.

**Example:**
```bash
# In Claude Code, use the Task tool or subagent spawning
Task("<tight task with acceptance contract>")
```

**Note:** Claude Code subagents don't provide worktree isolation by default. Use git branches manually if needed.

### Harness 5: Manual Git Workflow

**Use when:** No orchestration tool is available, but you still want isolation.

**Workflow:**
```bash
# Create isolated branch
git checkout -b beastmode/<task-id>

# Executor works in the branch (manually or via cheap model)
# ...

# Lead reviews
git diff main...beastmode/<task-id>

# Merge after approval
git checkout main
git merge beastmode/<task-id>
```

**Note:** Manual workflow requires discipline. Don't skip the review step.

### Harness Selection Guide

| Harness | Worktree Isolation | QA Gates | Cost Reporting | Best For |
|---------|-------------------|----------|----------------|----------|
| Hermes ACN (`adapters/hermes`) | ❌ No (use branches) | ✅ Phase gates + drift fail-closed | ✅ Per-child meta + acn-report | Async parallel sub-agents, default on this fleet |
| Pi (`pi/`) | ✅ Yes (workflows) | ✅ Adaptive | ✅ Yes | Local pi hosts, goal loops |
| Claude Code (`adapters/claude-code`) | ✅ Yes (`/batch`) | ✅ Phase gates | ❌ No | Claude-led runs, Pro-lane watcher |
| Codex (`adapters/codex`) | ✅ Yes (worktrees) | ✅ Phase gates | ❌ No | Codex-led runs, external cheap lanes |
| Ultraswarm | ✅ Yes | ✅ Adaptive | ✅ Yes | Git repos, multi-phase work |
| GSD | ❌ No (uses branches) | ✅ Phase gates | ❌ No | Repos already using GSD |
| delegate_task (raw) | ❌ No | ❌ No | ❌ No | Small parallel tasks, no repo |
| Manual git | ✅ Yes (branches) | ❌ Manual | ❌ No | No orchestration tool available |

**Default recommendation:** Use Hermes ACN on Hermes boxes (`bm --harness hermes`) and Pi where the pi packages are installed (`--harness pi`, the `bm` default), with Luna Max pinned for automatic workers and concurrency 3. Use Claude Code or Codex adapters only when the user explicitly names them. Fall back to GSD if the repo uses it, `delegate_task` raw for small tasks, manual git as last resort.

## The Beastmode Loop

### Step 0: Preflight

```bash
cd "$REPO"
git status --short
# If using Ultraswarm:
ultraswarm doctor
ultraswarm report || true
# If using the bm runner:
bm --help                  # confirm the runner is on PATH
pi --list-models | head     # confirm your frontier/economy models are present
```

If your harness is unavailable, fall back to a simpler harness (e.g., `delegate_task` or manual git), then record the failure in the self-improvement log.

**Model availability preflight (`bm`).** Before invoking `pi`, `bm` validates every `--frontier` and `--economy` alias against `pi --list-models` on the local host. If a resolved `provider/model` is not present, `bm` exits with code 2 and prints the available alternatives, so a goal never starts against an unresolvable model. The check is skipped when `BM_SKIP_MODEL_CHECK=1` (CI / scripted runs) or when `--on` is not local (the remote host owns availability).

### Step 1: Goal Interview (Autonomy-Scaled)

Before writing the acceptance contract, interview the user according to the
matrix in `schema/autonomy-levels.json`: `low` presents every material gray
area and keeps asking until resolved; `medium` and `high` ask one batched round
of the top 3–5 impact-ranked questions, then record remaining ambiguity as
explicit Assumptions. Never re-ask decisions already locked in
`GOAL_STATE.md`, `.planning/**/CONTEXT.md`, `.planning/**/SPEC.md`, or earlier
gate answers. The interview clarifies how to deliver the stated goal, never
whether to add a new capability; put new capabilities in Deferred ideas. A
non-interactive lane downgrades to assumptions-only and logs
`interview downgraded: non-interactive lane` in the phase report. Full protocol:
`references/goal-interview.md`.

### Step 2: Define Acceptance Contract

Before any delegation, write:

```markdown
Goal: <user-visible outcome>
Non-goals: <scope boundaries>
User-visible acceptance: <what the user will see/test>
Files/areas likely touched: <paths>
Locked decisions: <from interview + imported CONTEXT.md/SPEC.md, with sources>
Assumptions (unconfirmed): <A1..An, each with impact-if-wrong>
Open questions deferred to gates: <ids or none>
Verification commands: <unit/integration/e2e commands>
Manual QA: <visual/security checks>
Escalation triggers: <auth/security/payments/data-loss/architecture-uncertainty>
Self-improvement log path: <.learnings/BEASTMODE.md or project-local path>
```

### Step 3: Design (Frontier Tier — With Challenge)

Design is the highest-leverage phase — this is where frontier tokens are worth spending. Do not skimp here to save cost; a bad design multiplies executor waste downstream.

**For frontier-led (Fable / Kimi 3 / Opus):**
- The lead drafts intent, constraints, architecture, and interface contracts
- A second model (Codex/GSD, or the other frontier model) turns it into phases and tries to find gaps
- The lead resolves tradeoffs and approves the phase map
- The output is a **design package** the executor can implement without judgment calls: file-level plan, interfaces/signatures, acceptance contract, verification commands

**For Codex-led:**
- Lead writes the plan directly, or uses harness planning commands

**Planning commands by harness:**
- Ultraswarm: `ultraswarm plan "<goal>" --repo . --mode gsd`
- GSD: `gsd-plan-phase "<phase goal>"`
- Manual: Write plan in markdown, commit to `.planning/` or similar

### Step 4: Delegate Routine Work

Use tight task specs. One task should be reviewable in a single diff.

**Batch delegations to the same lane consecutively.** Every worker starts with a cold
prefix and pays a cache write (1.25x); subsequent workers on the same lane, model, and
system prompt read that prefix at 0.10x while it is warm (5-minute TTL, refreshed on
each hit). Ten workers fired back-to-back on one lane pay roughly one write; the same
ten interleaved across three lanes pay a write each time you switch back. Group by
lane, don't round-robin.

**Keep the worker contract byte-identical across workers.** The universal worker
contract (allowed files, forbidden commands, required output) is the shared prefix.
Inject the per-task objective *after* it, never inside it — a task ID or timestamp
spliced into the contract header gives every worker a unique prefix and forfeits the
discount entirely.

**Delegation by harness:**
- **Ultraswarm:** `ultraswarm run "<task>" --repo . --provider auto --mode auto`
- **delegate_task:** `delegate_task(goal="<task>", context="...", toolsets=['terminal', 'file'])`
- **Claude Code:** `Task("<task>")`
- **Manual:** Executor works in branch, commits changes

### Step 5: Validate (Cheap), Then Review (Frontier)

**Stage 1 — Mechanical validation (executor tier):** the pinned Luna Max economy worker runs the contract's verification commands and produces a structured report:

```markdown
## Validation Report <task-id>
- Commands run: <each command + exit code>
- Tests: <passed>/<total> (list failures with one-line reasons)
- Lint/typecheck: pass | fail (<count> issues)
- Diff stats: <files changed, +/- lines>; unrelated files touched: yes/no
- Contract checklist: <each acceptance item: met / not met / can't verify>
- Needs decision: <items or none>
```

**Stage 2 — Judgment review (frontier tier):** the lead or Codex reviews the *report + diff* against the contract. Frontier tokens go to reading the diff and making the call, not to re-running or watching tests.

**Review commands:**
```bash
# If using Ultraswarm:
ultraswarm qa <task-id>

# Manual review:
git diff --stat main...<branch>
git diff main...<branch>
```

**Reject if:**
- Tests fail
- Diff includes unrelated files
- Scope expanded beyond the acceptance contract
- Code uses nondeterminism or network calls where not allowed
- Secrets/credentials were exposed
- The executor made decisions reserved for the lead

### Step 6: Merge Gate

**Merge commands by harness:**
- **Ultraswarm:** `ultraswarm merge <task-id> --repo . --approved`
- **GSD:** `gsd-ship` (after verification)
- **Manual:** `git checkout main && git merge <branch>`

Never merge on executor self-report alone. The lead or Codex watcher must verify.

### Step 7: Self-Improving Checkpoint

After every phase, append a learning entry before continuing.

**Preferred locations (in order):**
1. Project-local `.learnings/BEASTMODE.md`
2. `.planning/LEARNINGS.md`
3. Relevant skill patch if the lesson is immediately reusable

**Template:**

```markdown
## BM-YYYYMMDD-HHMM <phase/task-id>
- Director/Lead: <model/agent>
- Watcher/Reviewer: <model/agent>
- Executor: <model/agent>
- Harness: <ultraswarm/gsd/delegate_task/claude-code/manual>
- Acceptance checks: <commands run>
- Result: pass | fail | partial
- Token/cost note: <estimate or harness report>
- What worked: <specific observations>
- What failed / drifted: <specific observations>
- Routing rule to change: <if applicable>
- Skill/config update needed: yes | no
- Promoted to: <skill/config/file or none>
```

**Promotion rules:**

The self-improvement loop writes **notes only** during a beastmode run. Any lasting change to agent behavior belongs in a separate user-approved maintenance task after the run is complete.

- Same routing mistake twice → record a proposed routing-rule change
- Same QA gap twice → record a proposed addition to the acceptance contract checklist
- Same tool failure twice → record a proposed troubleshooting entry
- Reusable workflow discovered → draft reusable procedure notes for later review
- User correction → record immediately and flag whether a lead-approved future update is needed

## Cost Discipline

### Frontier-Led Cost Rules (Fable / Kimi 3 / Opus)

**Keep the frontier tier for:**
- Interpreting user intent
- Product/creative judgment
- Architecture tradeoffs and design packages
- Judgment review of validation reports + diffs
- Final sign-off
- Escalation decisions

**Move to the Luna Max economy lane (legacy MiniMax/Qwen only by explicit override):**
- Code generation
- Tests
- Docs
- Data transformations
- Scripts
- Asset assembly
- Repetitive refactors
- Command execution
- **Mechanical validation** (running test suites, lint, typecheck, build; summarizing results into a validation report)

**Use Codex (or the second frontier model) for:**
- GSD planning
- Adversarial scope/cost review
- Merge gating
- High-risk analysis
- Debugging failed executor attempts

**Anti-patterns that burn frontier tokens:**
- Frontier lead re-running tests the executor already ran
- Frontier lead reading raw test/lint output instead of the validation report
- Frontier lead writing boilerplate ("just this once") because delegation feels slow
- Sending the executor an underspecified design so the frontier lead has to answer clarifying questions mid-implementation
- **Restarting the director session between phases** — the frontier prefix is the most
  expensive thing in the run and the most valuable to keep cached; a restart re-pays it
  in full at 1.25x
- **Varying the frontier system prompt per phase** — a phase label injected into the
  system prompt makes every phase a cache miss on the entire prefix

**Tier routing and prompt caching are independent levers — apply both.** Routing moves
work to a 10–50x cheaper model; caching takes up to 90% off the repeated prefix on
*whatever* tier you land on. Caching matters most exactly where routing helps least:
the frontier director, whose long stable prefix is re-sent on every turn.

### Codex-Led Cost Rules

**Keep Codex for:**
- Planning and architecture
- Adversarial review
- Security/auth/payments/data-loss risk
- Production incidents
- Failed executor attempts

**Move to the Luna Max economy lane (legacy MiniMax/Qwen only by explicit override):**
- Everything else (implementation, tests, docs, refactors, scripts, commands, mechanical validation)

## Required Final Report

End every beastmode run with:

```text
✅ Beastmode complete: <goal>
Variant: frontier-led | codex-led
Harness: <ultraswarm/gsd/delegate_task/claude-code/manual>
Phases completed: <n>
Director / watcher / executor split: <summary>
Models: Frontier (Fable/Kimi 3/Opus) <x%>, Codex/GPT <y%>, Executor (Luna Max) <z%>
Token/cost report: <harness report or estimate>
Worker table:
| worker | phase | model requested→actual | tokens (% of run) | status | produced |
Failures/hangs/drift: <itemized one-liners or none>
Ledger: .beastmode/LEDGER.md (<n> entries)
Verification: <commands and results, per validation report>
Self-improvement: <learning entry path + promoted updates, if any>
Merge status: <merged/branch ready/blocked>
```

## Choosing Your Variant

**Use frontier-led when:**
- You have a frontier model available (Claude Fable, Kimi 3, Claude Code / Opus)
- The task requires maximum product/creative/architecture judgment
- You're willing to pay for frontier-level design decisions but want implementation and validation on the cheap tier

**Use Codex-led when:**
- You don't have a frontier lead, or the task doesn't require frontier-level judgment
- Codex/GSD is sufficient for planning and review
- You want the cheapest possible lead with strong gates

**Both variants share:**
- The same worktree isolation, QA, merge, cost-report, and self-improvement gates
- The same acceptance contract requirements
- The same escalation rules
- The same final report format

## Escalation Rules

When an executor issue reaches a frontier trigger, stop and ask the user to name the frontier lane. Do not auto-escalate from the executor tier (Luna Max) to Fable, Kimi 3, Opus, or Codex.

Frontier triggers include:
- Security, auth, payments, data-loss, legal/financial data, or production incident risk appears
- The work requires non-obvious architecture tradeoffs
- The executor fails the same acceptance check twice
- The diff is too broad to review cheaply
- The user explicitly asks for frontier reasoning

Escalate a *task*, not the whole phase, only after the user explicitly names the lane. The rest of the phase stays on the cheap tier. See `references/model-routing.md` for the escalation ladder.

Escalation does not skip self-improvement. Record why the cheap route failed and whether the routing rule should change.

## Implementation Notes

**Worktree isolation is non-negotiable.** Executors must work in branches/worktrees, never directly in the main tree (unless the task is tiny and explicitly approved by the lead).

**If your preferred harness is unavailable:**
- Fall back to a simpler harness (e.g., `delegate_task` or manual git)
- Record the harness failure in the self-improvement log
- Don't skip isolation — use git branches manually if needed

**The goal is portability.** Beastmode should work in any agent environment (Claude Code, Hermes, OpenClaw, Codex) with any available harness. The principles (role separation, acceptance contracts, self-improvement) are constant; the harness is flexible.

## Self-Improvement Philosophy

Beastmode is not just an execution framework—it's a learning system. Every run should make the next run better.

**During a run:**
- Record observations, errors, and routing mistakes
- Note token/cost surprises
- Flag acceptance gaps

**After a run (in a separate maintenance task):**
- Review learning entries
- Promote repeated patterns into skills/config
- Update routing rules
- Improve acceptance contract checklists
- Draft reusable procedures

**The goal:** Beastmode should get cheaper, faster, and more reliable over time as the learning loop promotes lessons into permanent improvements.

## Context Management (Critical)

Beastmode runs accumulate context fast — subagent outputs, tool results, file diffs, planning docs. Without active management, you'll hit 300-500KB in 10-15 minutes, causing compression timeouts and /compact failures.

**Hard rules:**

1. **Compact every 5-10 minutes** — don't wait for context to break. Run `/compact` after each major phase (planning, execution, QA, merge).
2. **Limit sessions to 30 minutes** — save state (commit work, write learnings), start fresh, resume from saved state. Note the tension: a restart also discards a warm prompt cache, so restart on *context pressure*, not on the clock. If context is still healthy at 30 minutes, keep going.
3. **Subagent output summarization** — instruct subagents to return only final results (files changed, tests passed/failed, issues), not intermediate tool outputs. One subagent task should add <10KB to context, not 100KB.
4. **Break large tasks into small units** — one subagent = one small, bounded task. "Implement auth system" = 200KB output. "Create User model" + "Implement /login" + "Add password hashing" = 3x 20KB outputs.
5. **Never compress prompts at the API layer** — prompt caching is prefix-keyed and bills cache reads at **0.10x**. Any middlebox that rewrites the payload (LLMLingua/headroom-style) turns a 0.10x read into a 1.00x uncached read. At a measured 5% compression rate, break-even is only a **5.6%** cache hit rate — agent workloads run far above that, so compression is a net loss.
6. **Compress tool output, not prompts** — squeez on CLI/tool results shrinks text *before* it enters context and leaves the prefix byte-stable. That is cache-safe and worth doing.
7. **Compact after 3+ subagent delegations** — rule of thumb, but note each `/compact` rewrites history and resets the cached prefix. Prefer bounded subagents that keep the orchestrator prefix small over frequent compaction.

**Keep the prefix byte-identical.** Cache is keyed on an exact byte prefix, so one changed byte early invalidates everything after it:
- Order context **stable → volatile**: system prompt, tool definitions, reference docs, conversation, new turn last.
- No timestamps, session IDs, or rotating text in the system prompt.
- Don't edit or re-order earlier messages mid-conversation.
- Cache TTL is 5 minutes, refreshed on each hit — one continuous session stays warm; ten scattered one-shots pay the write cost ten times.

**Alert thresholds:**
- Context size > 200KB → compact now
- Cache hit rate < 30% on a long session → something is invalidating the prefix
- Session duration > 30 minutes → save state and restart

**What NOT to compress:**
- Error messages and stack traces (need full context for debugging)
- Small files (< 100 lines) — compression overhead > savings
- Structured data the agent needs to parse exactly (JSON APIs, CSV)

Verify caching survives your proxy chain with `scripts/cache-hitrate`. See
`references/context-rot-mitigation.md` for the break-even math, architectural fixes,
and monitoring. Custom endpoints require `--allow-custom-base-url`; ambient
Anthropic credentials are never forwarded to them.

## References

- **Schema (source of truth):** `schema/families.json`, `schema/tiers.json`, `schema/seats.json`, `schema/autonomy-levels.json`, `schema/acn-contract.json` — one machine-readable vocabulary for families, tiers, seats, autonomy, and the ACN contract.
- **Families / tiers / seats:** See `references/families-tiers-seats.md` for the human view of the schema and how to add a family or alias.
- **ACN contract:** See `references/acn-contract.md` for async parallel sub-agent fan-out — batch shape, per-child meta.json, the six shared rules, and the harness primitive map. Adapters: `adapters/hermes/`, `adapters/claude-code/`, `adapters/codex/`, `adapters/langgraph/`, plus the Pi adapter in `pi/`.
- **Model routing:** See `references/model-routing.md` for the per-phase tier routing table, provider configuration examples (Fable, Kimi 3, Luna Max), the mechanical-vs-judgment validation split, and the escalation ladder.
- **Tier aliases:** See `references/tier-aliases.md` (and `scripts/tier-aliases.json`) for the friendly-name → `provider/model` (+ family, tier) map consumed by `scripts/bm`. Verify them against `pi --list-models` on the configured worker host.
- **Autonomy levels:** See `references/autonomy-levels.md` for `low` / `medium` (default) / `high` autonomy — what surfaces, what runs silent, blocking-gate semantics below high, the per-phase usage report format, model-drift detection, and the per-harness enforcement map.
- **Goal interview:** See `references/goal-interview.md` for gray-area identification, question rounds, assumptions, needs_decision gate integration, and harness mappings.
- **Child liveness:** See `references/child-liveness.md` for the hung-agent contract — progress signals over wall-clock, marker-based startup probes, bounded watchers, and the kill → smoke → retry-once → escalate ladder.
- **Context rot mitigation:** See `references/context-rot-mitigation.md` for detailed analysis of context accumulation, architectural fixes, and monitoring strategies.
- **Orchestration comparison:** See `references/orchestration-comparison.md` for the evolution from early prototypes to v2.x.
- **Public sharing checklist:** See `references/public-sharing-checklist.md` for sanitization guidelines when publishing beastmode skills publicly.
