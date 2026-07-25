---
name: beastmode
description: >
  Multi-agent orchestration framework for high-intensity feature implementation.
  Routes work across model tiers: frontier models (Claude Fable, Kimi 3, Opus/Codex)
  own design, architecture, and review sign-off, while economy models (MiniMax M3,
  Qwen/Gwen) handle implementation and mechanical validation in isolated worktrees,
  with a self-improving learning loop that promotes lessons back into skills.
  Harness-agnostic: works with Ultraswarm, GSD, delegate_task, or manual orchestration.
version: 2.1.0
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

- **Director/Lead (Design tier):** Frontier model (Claude Fable, Kimi 3, Opus, or Codex) owns intent, architecture, creative judgment, and final sign-off.
- **Watcher/Reviewer:** Adversarial reviewer (frontier or mid-tier: Codex/GSD/Kimi 3) challenges plans, gates merges, catches scope creep.
- **Executor (Execution tier):** Economy model (MiniMax M3, Qwen 3.7 Plus / Gwen) handles routine implementation *and mechanical validation* (running tests, lint, typecheck, diff summaries) in isolated worktrees.
- **Harness:** Any orchestration tool (Ultraswarm, GSD, `delegate_task`, Claude Code subagents, or manual git workflow).
- **Memory:** Self-improvement loop records lessons and promotes repeated patterns into skills/config.

## Model Tiers & Routing

Beastmode routes every unit of work to a tier, not a specific model. Pick the best available model in each tier for your environment.

| Tier | Example models | Owns |
|------|---------------|------|
| **Design (frontier)** | Claude Fable (`claude-fable-5`), Kimi 3, Claude Opus, Codex/GPT frontier | Intent interpretation, architecture, API/data-model design, tradeoff decisions, acceptance contracts, final review sign-off, escalations |
| **Execution (economy)** | MiniMax M3, Qwen 3.7 Plus / Gwen, Haiku-class | Implementation, tests, docs, refactors, scripts, **mechanical validation** (run test suites, lint, typecheck, build, produce structured pass/fail reports) |

**The routing principle: verification cost, not task type.**

A task is safe for a cheap model exactly when its output can be **cheaply and objectively verified** — tests pass, schema validates, the diff matches a concrete spec. A task needs a frontier model when verification is expensive or subjective — "is this the right architecture?", "does this match user intent?". Phase labels (design/implement/validate) are just the common case of this rule, not the rule itself.

This reframes the frontier model's job: **its primary output is not code or even plans — it is verifiability.** The design phase converts an unverifiable goal ("build the feature well") into verifiable tasks (concrete interfaces + acceptance contract + verification commands). Once that conversion happens, the cheap tier can do everything downstream, because failures are caught by the verifier, not by expensive review.

**Routing decision, per task:**
1. Is there a cheap objective verifier for this task's output? → **Economy tier**, cheap-first cascade (retry once on failure, then escalate).
2. No verifier exists? → Don't route it to frontier by default. First ask: **can the frontier tier create a verifier** (tests, contract, checklist) and then delegate? Only work that resists verifier-creation — genuine judgment calls — is done directly by the frontier model.

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
- **Executor (MiniMax M3 / Qwen / Gwen):** Implementation, tests, docs, scripts, mechanical refactors, and mechanical validation (running verification commands, producing pass/fail reports)

**Key rule:** The frontier lead must aggressively avoid spending tokens on routine implementation *or* on watching test output scroll by. Delegate file edits, test writing, docs, refactors, command execution, and validation runs to the executor tier; the lead only reads the structured validation report and the diff.

### Variant B: Codex-Led Beastmode

**Use when:** You don't have a frontier lead, or the task doesn't require frontier-level judgment. Codex/GSD leads, with an economy model executing routine work.

**Role split:**
- **Director/Reviewer (Codex/GSD or current session):** Planning, review, merge decisions
- **Executor (MiniMax M3 / Qwen / Gwen):** Implementation, tests, docs, scripts, mechanical validation
- **Escalation:** Codex or a frontier model (Fable / Kimi 3) handles security, auth, payments, data-loss, production incidents, or failed executor attempts

**Key rule:** Delegate routine work to the executor tier, but don't merge until the lead verifies acceptance.

## Hard Rules

1. **Main tree stays clean.** Executors work in isolated worktrees/branches. Never let cheap executors directly mutate the main working tree unless the task is tiny and explicitly approved by the lead.
2. **Lead reviews, executor implements.** The lead can plan, inspect, test, and merge. Routine work goes to the executor.
3. **Every phase has an acceptance contract.** Define goal, non-goals, verification commands, and escalation triggers before delegation.
4. **Every phase improves the loop.** Record learnings, errors, routing mistakes, and token/cost surprises. Promote repeated lessons into skills/config.
5. **Escalation doesn't skip self-improvement.** Record why the cheap route failed and whether routing rules should change.
6. **Usage is reported per phase, not just at the end.** Every phase closes with a usage report: requested vs actual model per task, tokens used vs phase budget, actual vs estimated time (see `references/autonomy-levels.md` for the format). If the harness doesn't expose a value, say "unavailable" — never omit the report.
7. **Model drift always surfaces.** If a task was served by a model other than the requested `provider/model` (router fallback, harness default, silent substitution), flag it as MODEL DRIFT in the phase report immediately, at every autonomy level. Drifted work is not `validated` until re-validated under the correct tier.
8. **Gates are blocking below high autonomy.** At `low` and `medium` autonomy (medium is the default), the run stops at each phase gate — report, then wait for approval before the next phase or any merge. Only `--autonomy high` proceeds through gates automatically, and even it halts on its always-surface events.

## Choosing Your Harness

Beastmode works with any orchestration harness. Choose based on your environment:

### Runner CLI (`bm`)

For one-shot goals without writing a full plan: `bm "<goal>"` from any repo.
Parses `--gsd`, `--frontier <alias>`, `--economy <alias>`, `--on local|<host>`,
`--autonomy low|medium|high` (default `medium`). Tier aliases resolve via
`references/tier-aliases.json` — `kimi3` → `kimi-coding/k3`, `fable` →
`anthropic/claude-fable-5`, `minimax` → `minimax/MiniMax-M3`, etc. Override
per-repo with `<repo>/.beastmode/tier-aliases.json`. See `scripts/bm` and
`references/autonomy-levels.md`.

Before invoking `pi`, `bm` runs a model-availability preflight that checks
each resolved `provider/model` against `pi --list-models` on the local host.
If any are missing, `bm` exits with code 2 and prints the available
alternatives, so a goal never starts against an unresolvable model. Skip
with `BM_SKIP_MODEL_CHECK=1` (CI / scripted runs). The check is also
skipped when `--on` is not local (the remote host owns availability).

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

Let GSD handle planning/phase gates, and delegate routine implementation units to the executor tier (MiniMax M3 / Qwen) via Ultraswarm or `delegate_task`.

### Harness 3: delegate_task (Hermes/OpenClaw)

**Use when:** You're in Hermes or OpenClaw and need subagent orchestration without worktrees.

**Example:**
```python
delegate_task(
    goal="<tight task with acceptance contract>",
    context="Repo, acceptance contract, files, verification commands, commit requirement",
    toolsets=['terminal', 'file']
)
```

**Note:** `delegate_task` doesn't provide worktree isolation. Use for small parallel tasks or when worktrees aren't needed.

### Harness 4: Claude Code Subagents

**Use when:** You're in Claude Code and want to spawn subagents for routine work.

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
| Ultraswarm | ✅ Yes | ✅ Adaptive | ✅ Yes | Git repos, multi-phase work |
| GSD | ❌ No (uses branches) | ✅ Phase gates | ❌ No | Repos already using GSD |
| delegate_task | ❌ No | ❌ No | ❌ No | Small parallel tasks, no repo |
| Claude Code subagents | ❌ No | ❌ No | ❌ No | Claude Code environments |
| Manual git | ✅ Yes (branches) | ❌ Manual | ❌ No | No orchestration tool available |

**Default recommendation:** Use Ultraswarm if available. Fall back to GSD if the repo uses it. Use `delegate_task` or Claude Code subagents for small tasks. Use manual git workflow as last resort.

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

### Step 1: Define Acceptance Contract

Before any delegation, write:

```markdown
Goal: <user-visible outcome>
Non-goals: <scope boundaries>
User-visible acceptance: <what the user will see/test>
Files/areas likely touched: <paths>
Verification commands: <unit/integration/e2e commands>
Manual QA: <visual/security checks>
Escalation triggers: <auth/security/payments/data-loss/architecture-uncertainty>
Self-improvement log path: <.learnings/BEASTMODE.md or project-local path>
```

### Step 2: Design (Frontier Tier — With Challenge)

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

### Step 3: Delegate Routine Work

Use tight task specs. One task should be reviewable in a single diff.

**Delegation by harness:**
- **Ultraswarm:** `ultraswarm run "<task>" --repo . --provider auto --mode auto`
- **delegate_task:** `delegate_task(goal="<task>", context="...", toolsets=['terminal', 'file'])`
- **Claude Code:** `Task("<task>")`
- **Manual:** Executor works in branch, commits changes

### Step 4: Validate (Cheap), Then Review (Frontier)

**Stage 1 — Mechanical validation (executor tier):** the economy model (MiniMax M3 / Qwen) runs the contract's verification commands and produces a structured report:

```markdown
## Validation Report <task-id>
- Commands run: <each command + exit code>
- Tests: <passed>/<total> (list failures with one-line reasons)
- Lint/typecheck: pass | fail (<count> issues)
- Diff stats: <files changed, +/- lines>; unrelated files touched: yes/no
- Contract checklist: <each acceptance item: met / not met / can't verify>
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

### Step 5: Merge Gate

**Merge commands by harness:**
- **Ultraswarm:** `ultraswarm merge <task-id> --repo . --approved`
- **GSD:** `gsd-ship` (after verification)
- **Manual:** `git checkout main && git merge <branch>`

Never merge on executor self-report alone. The lead or Codex watcher must verify.

### Step 6: Self-Improving Checkpoint

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

**Move to MiniMax M3 / Qwen / Gwen:**
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

### Codex-Led Cost Rules

**Keep Codex for:**
- Planning and architecture
- Adversarial review
- Security/auth/payments/data-loss risk
- Production incidents
- Failed executor attempts

**Move to MiniMax M3 / Qwen / Gwen:**
- Everything else (implementation, tests, docs, refactors, scripts, commands, mechanical validation)

## Required Final Report

End every beastmode run with:

```text
✅ Beastmode complete: <goal>
Variant: frontier-led | codex-led
Harness: <ultraswarm/gsd/delegate_task/claude-code/manual>
Phases completed: <n>
Director / watcher / executor split: <summary>
Models: Frontier (Fable/Kimi 3/Opus) <x%>, Codex/GPT <y%>, Executor (MiniMax M3/Qwen) <z%>
Token/cost report: <harness report or estimate>
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

Escalate from the executor tier (MiniMax M3 / Qwen / Gwen) to the frontier tier (Fable / Kimi 3 / Opus / Codex) when:
- Security, auth, payments, data-loss, legal/financial data, or production incident risk appears
- The work requires non-obvious architecture tradeoffs
- The executor fails the same acceptance check twice
- The diff is too broad to review cheaply
- The user explicitly asks for frontier reasoning

Escalate a *task*, not the whole phase — the rest of the phase keeps running on the cheap tier. See `references/model-routing.md` for the full escalation ladder.

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
2. **Limit sessions to 30 minutes** — save state (commit work, write learnings), start fresh, resume from saved state.
3. **Subagent output summarization** — instruct subagents to return only final results (files changed, tests passed/failed, issues), not intermediate tool outputs. One subagent task should add <10KB to context, not 100KB.
4. **Break large tasks into small units** — one subagent = one small, bounded task. "Implement auth system" = 200KB output. "Create User model" + "Implement /login" + "Add password hashing" = 3x 20KB outputs.
5. **Enable headroom fail-open mode** — set `HEADROOM_WS_FAIL_OPEN_ON_COMPRESSION_FAILURE=1` in headroom launchd plist. Makes headroom pass through uncompressed instead of returning 413 errors.
6. **Use layered compression** — squeez (CLI output, 60-95%) + headroom (API layer, 60-95%) = 70-80% total savings. Watch for compression tax (agent asking more follow-ups = compression too aggressive).
7. **Compact after 3+ subagent delegations** — rule of thumb. If you've delegated 3 tasks, compact before continuing.

**Alert thresholds:**
- Context size > 200KB → compact now
- Compression failures > 3/hour → enable fail-open or increase timeout
- Session duration > 30 minutes → save state and restart

**What NOT to compress:**
- Error messages and stack traces (need full context for debugging)
- Small files (< 100 lines) — compression overhead > savings
- Structured data the agent needs to parse exactly (JSON APIs, CSV)

See `references/context-rot-mitigation.md` for full details on architectural fixes and monitoring.

## References

- **Model routing:** See `references/model-routing.md` for the per-phase tier routing table, provider configuration examples (Fable, Kimi 3, MiniMax M3), the mechanical-vs-judgment validation split, and the escalation ladder.
- **Tier aliases:** See `references/tier-aliases.md` (and `tier-aliases.json`) for the friendly-name → `provider/model` map consumed by `scripts/bm`. Verified against `pi --list-models` on oracle-1 / maeve-u1.
- **Autonomy levels:** See `references/autonomy-levels.md` for `low` / `medium` (default) / `high` autonomy — what surfaces, what runs silent, blocking-gate semantics below high, the per-phase usage report format, model-drift detection, and how to map levels to `pi --approve` / `--no-builtin-tools`.
- **Context rot mitigation:** See `references/context-rot-mitigation.md` for detailed analysis of context accumulation, architectural fixes, and monitoring strategies.
- **Orchestration comparison:** See `references/orchestration-comparison.md` for the evolution from early prototypes to v2.0.
- **Public sharing checklist:** See `references/public-sharing-checklist.md` for sanitization guidelines when publishing beastmode skills publicly.
