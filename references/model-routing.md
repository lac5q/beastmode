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

## Per-user `bm` defaults

`bm` optionally reads a trusted JSON profile from `~/.beastmode/defaults.json`;
set `BM_DEFAULTS_FILE` to select another explicit file. A present profile must
use `schema_version: 1`. Supported fields are `harness`, provider-qualified
`frontier`, `economy`, `watcher`, and optional `limit_fallback` model IDs,
`thinking`, the optional `economy_thinking` and `watcher_thinking` (same values
as `thinking`; when set, the seat prompt tells economy workers or the watcher to
run at that reasoning effort), and the boolean `claude_subscription_watcher`.
CLI flags override
the profile; otherwise trusted profile seats remain standing selections until
changed. Profiles in a checkout are ignored, an absent default file keeps the
built-in behavior, and invalid or explicitly missing profiles stop before
dispatch. Profiles cannot skip model preflight or change harness
tool/sandbox policy. Economy provider names are kept as written; `bm` does not
translate a fully qualified profile value to another provider namespace.

Example `~/.beastmode/defaults.json` for a Codex Sol director, Luna worker, and
Grok 4.7 validator and authorized limit fallback:

```json
{
  "schema_version": 1,
  "harness": "codex",
  "frontier": "openai-codex/gpt-6.1-sol",
  "economy": "openai-codex/gpt-6-luna",
  "watcher": "xai/grok-4.7",
  "limit_fallback": "xai/grok-4.7",
  "thinking": "max"
}
```

Example for a Claude-led operator (director and workers run through first-party
Claude Code, `claude -p`, on the operator's own subscription):

```json
{
  "schema_version": 1,
  "harness": "claude",
  "frontier": "anthropic/claude-opus-5-5",
  "economy": "anthropic/claude-sonnet-5-5",
  "watcher": "openai-codex/gpt-6.2-astra",
  "thinking": "max",
  "watcher_thinking": "high"
}
```

Claude models run only inside Claude Code (`--harness claude`: Task subagents
with a pinned model, or `claude -p --model <id>`). `--harness pi` with an
Anthropic director is rewritten to `--harness claude` (first-party Claude Code).
Exit 3 is the case where a Claude economy, watcher or limit-fallback seat sits
under a non-Claude director (or on hermes/codex/langgraph) and `ANTHROPIC_API_KEY`
is not set. With a key, the seat prompt tells the director that Claude seats must
use the API key and never a subscription login. `BM_ALLOW_CLAUDE_OAUTH` and
prompts do not authorize it. Hermes and codex require an explicit `--frontier`
so the director model is pinned. `--claude-subscription` needs an `anthropic/*`
frontier. `--economy-thinking` and `--watcher-thinking` override the profile
values and are not supported by the local LangGraph runner. The legacy
`claude_subscription_watcher: true` flag is still parsed but does nothing.

### Explicit quota/rate-limit recovery

Seat failure is explicit by default. A trusted profile's optional
`limit_fallback`, or the current task's `--limit-fallback <alias|provider/model>`,
authorizes exactly one agent-level retry of the same bounded contract after a
provider records a quota or rate-limit failure. Keep the original failure and
requested/actual model receipts for both attempts; report failure if the
fallback is also limited. Authentication or network errors, missing
provenance, unsupported models, invalid output, and other failures do not
authorize this route. With no configured fallback, report the seat failure.

When the built-in economy seat is implicit and local availability proves that
no configured economy provider is live, Beastmode may first use an external
economy alias explicitly marked `worker_fallback: true` in a trusted user or
shipped alias file. If no marked external lane is live, it may use a reviewed
lower same-provider worker seat for an Anthropic frontier director: `haiku`
first, then `sonnet-worker`. The director remains on the requested Fable/Opus
seat; the worker model is pinned on every child and its requested/actual
provenance is retained. An explicit `--economy` or trusted profile economy
selection is never silently changed. Claude Code has no portable model listing,
so its automatic Anthropic lane uses `haiku` unless `BM_CLAUDE_WORKER_MODEL`
selects `sonnet-worker`, `sonnet`, or `sonnet5`.

`bm` resolves the selected fallback, forwards it to remote dispatch, and puts
the instruction in the seat prompt. It does not automatically retry a provider
subprocess. In this operating setup, Grok 4.7 is the authorized validator and
quota fallback: use the first-party Grok CLI through `bin/beast-validator`, pin
`grok-4.7` with `xhigh` effort, and require `modelUsage` as evidence of the
served model. The native regular Grok 4.7 route can report `grok-4.7-build`;
retain that observed identity separately from requested `grok-4.7`, and reject
older, fast or mixed model usage. If the native lane or its provenance is unavailable, report
failure and do not substitute. This routing choice is not a portable `bm`
default; when no trusted profile is present, the caller keeps the built-in
defaults.

The per-phase table below is what this principle implies for a standard beastmode run — it's the default mapping, not the rule. When a task doesn't fit the table, apply the principle directly.

## Optional decision providers: preferred when proven better

The operator's default is conditional preference, not a required dependency.
For each bounded use case, prefer a configured, available decision provider once
reviewed evidence shows better quality within the accepted latency/cost budget,
or lower latency/cost at an accepted quality level. Compare against the actual
existing path, including deterministic code when its inputs are already known.
Do not infer whole-workflow savings from an isolated API call.

Qualification belongs to a specific model version, question/criteria version,
input shape and use case. Use reviewed representative labels, a held-out set,
error severity, abstention/coverage and complete request accounting. A small
synthetic spike, leaderboard position, credential presence or an arbitrary
confidence threshold does not qualify a new default. Revalidate material model
or criteria changes; keep previous evidence and support rollback.

Once qualified, select it automatically where its evidence applies. Respect an
explicit disable setting. Missing keys/dependencies, unavailable service,
timeout, rate limits, invalid output, version mismatch, out-of-scope input or
confidence below a validated threshold use the existing deterministic/director
path. Record why; never disguise provider failure as a confident task answer.
This optional decision-provider rule is separate from the explicit model-seat
quota fallback described above.
This policy does not introduce a mandatory package, network call or account.
The current runtime remains unchanged until a provider integration is qualified.

| Decision | Deterministic responsibility | Possible model contribution |
|---|---|---|
| Model tier | Apply verification-cost policy to known flags | Extract or classify ambiguous task requirements |
| Next worker | Dependencies, active ownership, allowed stages and action budget | Rank several eligible workers when a fixed schedule is insufficient |
| Tool-output relevance | Retain original receipts and required evidence | Rank optional context; an uncertain drop keeps the evidence available |
| Goal completion | Check the acceptance contract, current receipts and remaining work | Identify possible semantic gaps; never substitute for final verification |
| Side-effect risk | Check actual tool/arguments, scope and authorization | Flag suspicious or unclear intent for additional review |

Thresholds are use-case-specific evidence, not permission grants. A quoted
"fraud needs 0.95" rule does not authorize payments or certify calibration.
Compute counts, dates and budget predicates in code. Preserve input provenance,
allowed options, chosen ID, model/criteria versions, score semantics, re-check,
fallback, latency and usage in decision receipts. Do not treat Jev's confidence
field as identical to maximum option probability or cross-provider confidence.

The September 26 spike and the separate agent-folder follow-up are under
`evals/decision_models/`. Their results inform qualification; they do not replace
it or install a general-purpose control plane.

## Tier Definitions

| Tier | Role | Example models | Cost profile |
|------|------|---------------|--------------|
| **Frontier (design)** | Architecture, product judgment, review sign-off | Claude Fable (`claude-fable-5`), Kimi 3, Claude Opus, frontier GPT/Codex | Expensive per token; used in short, high-leverage bursts |
| **Economy (execution)** | Implementation, tests, docs, mechanical validation | Luna Max (`gpt-6-luna`) by default; legacy MiniMax/Qwen/Haiku by explicit override | 10–50× cheaper; used for the bulk of tokens |

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
2. **Stop and ask before frontier diagnosis:** if the failure or diff requires frontier judgment, report the evidence and ask the user to name the frontier lane. Do not silently switch lanes.
3. **Run frontier execution only after explicit selection:** frontier implements the task itself only when the user names the model/lane for this bounded task. Reserved for: second identical acceptance failure, security/auth/payments/data-loss surface, non-obvious architecture tradeoffs, or explicit user request.

Rung 2 is the workhorse. Most executor failures are spec failures in disguise — the frontier model fixing the *spec* is cheaper than the frontier model doing the *work*, and it upgrades every similar future task.

Frontier triggers that require a user decision (never automatic):
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
    model: <explicitly selected frontier model>
    use_for: [plan, review, escalation]  # only after the user names the lane
  execute:
    model: minimax-m3            # automatic/default lane
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
