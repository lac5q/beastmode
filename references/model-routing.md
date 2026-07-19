# Model Routing: Frontier Design, Economy Execution

This reference defines how beastmode routes work across model tiers.

## The Routing Principle: Verification Cost

Don't route by task *type* — route by how cheaply the task's output can be **verified**.

- **Cheap objective verifier exists** (tests pass, schema validates, lint clean, diff matches a concrete spec) → economy model. If it produces garbage, the verifier catches it for pennies; the worst case is a bounded retry, not a shipped mistake.
- **Verification is expensive or subjective** ("is this the right architecture?", "does this match what the user actually wants?", "is this security-sensitive change sound?") → frontier model. Here a wrong output is only caught by expensive judgment, so the judgment should happen *once, up front*, in the generation itself.

This reframes what the frontier model is *for*. Its primary output is not code, and not even plans — **it is verifiability**. Design, in beastmode terms, is the act of converting an unverifiable goal ("build this feature well") into verifiable tasks: concrete interfaces, an acceptance contract, executable verification commands, an out-of-scope list. Every hour of frontier design that makes one more task cheaply verifiable moves that task — and all its retries — permanently onto the cheap tier.

Three consequences fall out of the principle:

1. **Cheap-first cascade.** For any task with a verifier, default to the cheapest model and escalate only on verified failure (see Escalation Ladder). Never pre-route to frontier "because it's important" — importance is handled by the verifier and the gate, not by the generation model.
2. **When no verifier exists, the first question is not "which model does the work?" but "can the frontier model create a verifier?"** Writing characterization tests, tightening the contract, or producing a review checklist is usually cheaper than having the frontier model do the task — and it pays off on every future task of the same shape.
3. **Frontier review reads compressed evidence, not raw output.** Judgment is expensive; spend it on the decision (report + diff), never on re-deriving the evidence (logs, test runs).

The per-phase table below is what this principle implies for a standard beastmode run — it's the default mapping, not the rule. When a task doesn't fit the table, apply the principle directly.

## Tier Definitions

| Tier | Role | Example models | Cost profile |
|------|------|---------------|--------------|
| **Frontier (design)** | Architecture, product judgment, review sign-off | Claude Fable (`claude-fable-5`), Kimi 3, Claude Opus, frontier GPT/Codex | Expensive per token; used in short, high-leverage bursts |
| **Economy (execution)** | Implementation, tests, docs, mechanical validation | MiniMax M3, Qwen 3.7 Plus / Gwen, Haiku-class | 10–50× cheaper; used for the bulk of tokens |

Model names are examples, not requirements — beastmode routes to *tiers*. Substitute whatever frontier and economy models your environment provides. Verify exact model IDs with your provider/router (OpenRouter, direct APIs, local serving) before configuring; provider-specific IDs change frequently.

**Two-frontier pairing:** When you have access to two frontier models from different families (e.g. Fable + Kimi 3), use one as Director and the other as adversarial Watcher. Cross-family review catches blind spots that same-family self-review misses, at the cost of one extra frontier pass per phase.

## Per-Phase Routing Table

| Beastmode step | Work | Tier | Notes |
|---|---|---|---|
| 0. Preflight | Repo status, harness checks | Economy (or scripted) | Pure command execution |
| 1. Acceptance contract | Write goal/non-goals/verification/escalation triggers | **Frontier** | The contract is the executor's spec — ambiguity here is paid for many times downstream |
| 2. Design | Architecture, interfaces, file-level plan, phase map | **Frontier** | Highest-leverage spend in the whole run. Output a *design package* (see below) |
| 2b. Design challenge | Adversarial gap-finding on the plan | **Frontier** (second model) or Codex | Cross-family challenge preferred |
| 3. Implementation | Code, tests, docs, refactors, scripts | Economy | One task = one reviewable diff |
| 4a. Mechanical validation | Run verification commands, collect results, write validation report | Economy | Deterministic; never frontier |
| 4b. Judgment review | Read validation report + diff, accept/reject against contract | **Frontier** | One pass per phase, at the gate |
| 5. Merge | Execute merge commands after approval | Economy (or scripted) | Decision already made in 4b |
| 6. Self-improvement | Append learning entry | Economy drafts, frontier approves promotions | Notes are cheap; changing routing rules is a judgment call |

## The Design Package

The design phase must produce an artifact the executor can implement **without judgment calls**. If the executor has to make an architecture decision mid-task, the design package was incomplete — that's a design-tier failure, and it should be recorded in the self-improvement log.

A design package contains:

```markdown
# Design Package: <feature>
## Intent
<user-visible outcome, one paragraph>
## Architecture decisions (already made — do not revisit)
- <decision>: <choice> because <reason>
## File-level plan
- <path>: <create/modify> — <what goes here>
## Interfaces / signatures
<function signatures, API shapes, schema definitions — concrete enough to code against>
## Acceptance contract
<goal, non-goals, verification commands, manual QA, escalation triggers>
## Out of scope
<explicitly deferred items so the executor doesn't "helpfully" add them>
```

## Mechanical vs. Judgment Validation

Validation splits into two stages routed to different tiers:

**Stage 1 — Mechanical (economy):** run every verification command in the contract; capture exit codes and failures; compute diff stats; check each contract item as met / not met / can't verify; emit the structured Validation Report (format in SKILL.md Step 4). No opinions — just evidence.

**Stage 2 — Judgment (frontier):** read the report and the diff. Ask: does this diff *actually* satisfy the intent, not just the checklist? Any scope creep, security smells, decisions the executor wasn't authorized to make? Accept, reject with specific fixes (back to economy tier), or escalate.

Why this split works: mechanical validation is where naive setups burn frontier tokens (long tool outputs, test logs, retries). Piping raw logs into a frontier model is the single most common beastmode cost leak. The report compresses hundreds of KB of logs into <2 KB of decision-relevant signal.

## Escalation Ladder (Cheap-First Cascade)

Every verifiable task starts at the bottom and climbs only on *verified* failure, per *task* (the rest of the phase stays on the cheap tier):

1. **Retry on economy tier** with the verifier's failure output appended to the task spec (one retry max).
2. **Escalate to frontier for diagnosis only:** frontier reads the failure + diff, writes a corrected task spec — often this means tightening the verifier or the design package, which is the real fix — then hands back to economy tier.
3. **Escalate to frontier for execution:** frontier implements the task itself. Reserved for: second identical acceptance failure, security/auth/payments/data-loss surface, non-obvious architecture tradeoffs, or explicit user request.

Rung 2 is the workhorse. Most executor failures are spec failures in disguise — the frontier model fixing the *spec* is cheaper than the frontier model doing the *work*, and it upgrades every similar future task.

Automatic escalation triggers (skip the ladder, go straight to frontier):
- Security, auth, payments, data-loss, legal/financial data, production incidents
- The executor proposes changing an interface defined in the design package

Every escalation gets a self-improvement entry: why the cheap route failed, and whether the routing rule or the design-package template should change.

## Configuration Sketches

### Ultraswarm

Map tiers to providers so `--provider auto` routes by task type:

```yaml
# ultraswarm config sketch — adapt to your installed version
providers:
  design:
    model: claude-fable-5        # or kimi-3 via your router
    use_for: [plan, review, escalation]
  execute:
    model: minimax-m3            # via OpenRouter/direct API — verify exact ID
    use_for: [implement, test, docs, validate]
```

```bash
ultraswarm plan "<goal>" --repo . --provider design --mode gsd
ultraswarm run "<phase>" --repo . --provider execute --mode gsd
ultraswarm qa <task-id>          # runs on execute tier; report reviewed by design tier
```

### Claude Code subagents

Lead session runs on the frontier model; delegate execution to a cheaper subagent model where the harness supports per-agent model selection (e.g. a `.claude/agents/executor.md` with a cheap `model:` in its frontmatter, or the Task tool's model override).

### delegate_task / manual

Run the lead conversation on the frontier model. For each executor task, call the economy model's API/CLI with the design package + task spec as the full prompt, and require the commit + validation report as the only output.

## Cost Sanity Check

After each run, the final report's model split should look roughly like:

- **Frontier: 10–25% of tokens** (design, challenge, judgment reviews, escalations)
- **Economy: 75–90% of tokens** (implementation, validation, merges)

If frontier share exceeds ~30%, something is leaking — usually raw logs reaching the lead, underspecified design packages causing back-and-forth, or the lead writing code. Record the leak in the self-improvement log and fix the routing rule.
