---
name: beastmode-codex
description: Use when the Codex session is the Beastmode director and needs worker-lane mechanics.
version: 1.0.0
author: Luis Calderon
tags: [beastmode, mofa, codex, orchestration, multi-agent, model-routing, acn]
related_skills: [beastmode, gsd, beastmode-cloud]
source_repo: https://github.com/lac5q/beastmode/blob/main/adapters/codex/SKILL.md
---

# Beastmode Codex — Codex Harness Adapter

This skill is **only the harness mechanics**. The framework, tier-routing
rule, verifier-first design principle, and self-improvement loop live in
the canonical `beastmode` skill (v2.5.0) — load it first and follow it.
This adapter tells you which Codex primitives implement which seat and
which configured lanes the bounded workers can call.

**Note**: the legacy `beastmode-qwen-cloud` skill is superseded by this
adapter. The Qwen / MiniMax API / Droid / GLM lanes that used to live
there are listed as worker lanes below; the same contracts and smoke
gates apply.

## Trusted seat selection

When this skill loads, first resolve the trusted per-user profile: a non-empty
`BM_DEFAULTS_FILE`, otherwise `~/.beastmode/defaults.json`. Never read
checkout-local defaults. Saved model seats and harness choices are standing
explicit selections until changed; a current task request or CLI flag wins.
The profile records requested routing only. It cannot change Codex sandbox or
tool policy, and it cannot prove which model or effort is actually serving.

This operator's standing selections are `openai-codex/gpt-6.1-sol` at `max`
for the director, `openai-codex/gpt-6-luna` at `max` for economy work, and
`xai/grok-4.7` at `xhigh` for validation. A current task choice overrides the
trusted profile. These are requested seats, not evidence of what the active
session served; keep the portable built-in `bm` defaults when no user profile
is present.

If the running director cannot match the configured model or effort, report
the mismatch and identify the actual serving model if known. Use the matching
launcher on the next run; never claim the current session switched itself.
Cheapest-worker fallback is available only when no explicit standing/current
choice applies to the assignment. An explicitly pinned validator fails closed
by default. The sole exception is a configured `limit_fallback` or current
`--limit-fallback`, and only after a recorded provider quota/rate-limit
failure: route one agent-level retry of the same bounded contract, preserve
the original failure and requested/actual model receipts, and report failure
if the fallback is also limited. Authentication/network errors, missing
provenance, unsupported models, invalid output, and other failures do not
authorize it. `bm` supplies this routing instruction but does not retry
provider subprocesses.

## Only the harness mechanics

| Universal seat | Codex implementation |
|---|---|
| Director (frontier) | The Codex session itself when selected by the current task or trusted profile; owns intent, design, merge gate |
| Watcher (validator) | The selected Codex-side validator; Claude seats are not run from Codex on subscription login (use `--harness claude`, or an `ANTHROPIC_API_KEY`) |
| Executor (economy) | Native Codex child `openai-codex/gpt-6-luna` at max reasoning is preferred when approved; otherwise use the selected economy seat |
| Loop engine | Director self-prompts between worker results |
| Anti-spin | Director judgment + usage budget; abort on 3 identical blockers |
| Worker-contract enforcer | Codex sandbox defaults + starter worker contract; autonomy never weakens the sandbox |
| Live progress | `.codex/beastmode-runs/<ts>-<lane>/output.md` plus any task transcript |
| Goal record | `<repo>/GOAL.md` (universal fallback) |
| Self-improvement log | `<repo>/.learnings/BEASTMODE.md` (universal) |

When `codex exec` runs in the background or from a script, redirect stdin from
`/dev/null` (`codex exec ... </dev/null`). Otherwise it waits forever on
"Reading additional input from stdin..." (observed 2026-11-24).

## Worker lanes

Smoke-gate every lane before routing; failed lane = installed-but-not-live.
The trusted profile or current task selects a standing seat; these launchers
must pin that requested model and effort on every invocation.

| Lane | Model / effort | Launcher | Selection and smoke gate |
|------|---------------|---------|--------------------------|
| Native Codex worker (preferred) | `openai-codex/gpt-6-luna`, max reasoning | `codex exec --model gpt-6-luna -c 'model_reasoning_effort="max"'` | Use when the current task or trusted profile selects this seat and the model is available |
| Grok validator / authorized quota fallback | `xai/grok-4.7`, `xhigh` | `bin/beast-validator` (first-party Grok CLI) | Use when selected as validator or by the explicit quota fallback; pin `grok-4.7`, require `modelUsage` proof, and report failure if the native lane or provenance is unavailable |
| Qwen (legacy explicit override) | `qwen3.7-plus` | `~/.local/bin/qwen-agent` | Reply exactly `QWEN OK` |
| MiniMax API (legacy explicit override) | `MiniMax-M3` | `curl https://api.minimax.io/v1/chat/completions` | Reply exactly `MINIMAX OK` (never print the key) |
| Droid MiniMax (legacy explicit override) | `minimax-m3` | `~/.local/bin/droid exec --model minimax-m3` | Reply exactly `MINIMAX OK` |
| Droid custom | any `droid exec --list-tools` model id | `~/.local/bin/droid exec --model <id>` | Model-specific exact reply; select explicitly |
| GLM (legacy explicit override) | `glm-4.6` | `~/.local/bin/droid exec --model glm-4.6` (or direct API) | Reply exactly `GLM OK` |

The Qwen, MiniMax, and GLM rows are legacy explicit overrides, not fallback
choices. Use the selected lane only. Without an explicit standing/current
choice, use native Luna Max/max as the economy default; if that lane is down,
the existing cheapest-live-worker fallback may run. A selected validator is
never replaced for authentication/network errors, missing provenance,
unsupported models, invalid output, or other failures. Only the configured
quota/rate-limit fallback above can authorize the single bounded retry.

### Lane smoke gates

```bash
# Qwen
printf '%s\n' 'Reply with exactly: QWEN OK' | \
  ~/.local/bin/qwen-agent --max-tool-calls 0

# Direct MiniMax API (MINIMAX_API_KEY in env; never print the key)
curl -sS https://api.minimax.io/v1/chat/completions \
  -H "Authorization: Bearer ***" -H "Content-Type: application/json" \
  -d '{"model":"MiniMax-M3","thinking":{"type":"disabled"},"messages":[{"role":"user","content":"Reply with exactly: MINIMAX OK"}],"max_completion_tokens":20,"temperature":0}'

# Droid MiniMax / Droid custom / GLM
~/.local/bin/droid exec --model minimax-m3 "Reply with exactly: MINIMAX OK"
~/.local/bin/droid exec --model <id> "Reply with exactly: <MODEL> OK"
~/.local/bin/droid exec --model glm-4.6 "Reply with exactly: GLM OK"
```

If a smoke check fails, continue without that lane and report it as
installed-but-not-live. Do not silently retry — document and route
elsewhere.

## ACN — async parallel sub-agents

ACN is the universal Beastmode fan-out layer. In Codex it is parallel
`codex exec` invocations on per-task git worktrees.

- Each ACN task runs in its own `codex exec` process, started in
  background with the task's prompt and the worker contract. The
  director passes the desired `--model` explicitly.
- Per-task git worktrees give each worker an isolated copy of the repo.
  The director reviews the diffs, runs the verifier, merges only the
  acceptable slices.
- The director (this Codex session) is always the merge gate. Workers
  never apply their own patches back without explicit approval.
- For high-concurrency fan-out, batch up to `concurrency_default` (3 by
  default) parallel `codex exec` processes; the universal
  `schema/acn-contract.json` `concurrency` field caps the batch.

Run records land under `.codex/beastmode-runs/<UTCts>-<lane>/` with
three files: `prompt.md` (the worker contract), `output.md` (the worker's
reply), and `meta.json` (the schema shape with requested/actual models
and usage).

## MODEL PINNING (hard rule)

Every worker invocation pins the model selected by the current task or trusted
profile. The saved choice determines the requested model, but each command must
still pass its model and effort explicitly:

- CLI lanes: `--model <id>` on the invocation (e.g. `droid exec --model
  minimax-m3`).
- Direct MiniMax API: the `model` field in the JSON body.
- Codex children: pass the selected CLI model id with `--model` (for example,
  `codex exec --model gpt-6-luna`); record the provider-qualified requested
  model and actual served model in the receipt.

Never rely on the harness default for economy work. Pin it. After each
worker returns, persist a `meta.json` in the run record with the shape
from `schema/acn-contract.json` (`requested_model`, `actual_model`,
`stop_reason`, `usage`, `files_changed`, `commands_run`, `verify`).
Drift (`actual_model != requested_model`) is silent substitution —
surface it as MODEL DRIFT and block `validated` until the task is re-run
under the pinned model.

Unverifiable child model = **UNVERIFIED DRAFT** lane. Output may be used
as input but is never `validated` until re-checked under a pinned model.
A meta carrying a single merged `model` instead of both `requested_model`
and `actual_model` is unverifiable — there is nothing to compare.
`scripts/enforce-models --check-meta <run-dir> --attestations <parent-owned-evidence.json> --trust-attestations` is the gate; exit 1 means
drift or unverifiable.

## Review source completeness

Before a cross-model review, materialize the exact prompt and check it against
a manifest of required sources: the latest user request, the original answer
or draft, decisive messages, and any promised transcript or document. Verify
source identifiers and non-empty content in the bytes being sent. Do not
assume in-memory stores survive turn, voice, or runtime boundaries, and do not
replace a missing required source with an "unavailable" placeholder.

Ask the reviewer to confirm source completeness before giving a verdict.
If a required source is absent, mark that review incomplete, retrieve the
source, and rerun or continue with an explicit correction. A model-identical
receipt cannot validate a review of the wrong or incomplete evidence. Keep
invalidated output separate from the final review and record the correction
in the run receipt.

## Autonomy mapping

| Level | What runs without surfacing | What always surfaces |
|---|---|---|
| **low** | Single executor turn, one read-only tool call | Every phase, every child result, every merge — every merge waits for approval |
| **medium** (default) | Whole phase: acceptance → design → delegate → validate → review | Security/auth/payments/data-loss events, model failure, **MODEL DRIFT**, `goal_blocked`, the merge gate |
| **high** | Multi-batch until `goal_complete` or repeated `goal_blocked` (≤ 3) | Budget exhaustion, no-watcher / no-validated, secrets in prompt, unrevalidated drift |

Gates are blocking below high. Codex sandbox and approval controls stay
on at every level; every merge waits for approval. High autonomy changes
phase progression only and never enables `--yolo` or `--full-auto`.
Even at high, the run still
halts on budget exhaustion, no watcher, no validated, secrets-in-prompt,
and unrevalidated MODEL DRIFT — those are universal. **gates are blocking
below high.**

```
Phase <n> <name>: <status>
Models: requested <tier: provider/model> → actual <provider/model per task>
Drift: none | MODEL DRIFT: <requested> → <actual> on <task(s)>
```

## Interview mapping

Interactive Codex sessions present interview and gate questions as numbered-list
plain text. `codex exec` lanes are non-interactive, so they downgrade to
assumptions-only and log `interview downgraded: non-interactive lane` in the
phase report.

## Worker prompt contract

Byte-identical shared contract across every worker; the per-task
objective is appended **after** the shared prefix. Claude / Qwen prompt
cache penalizes divergent prefixes at ~1.25x write, so keep the contract
stable and only splice the task-specific slice.

Every worker must:

- Receive: exact repo path, objective, allowed files/directories,
  allowed commands, forbidden commands (commit, push, rm -rf, publish,
  send, access secrets, change cloud config), required output shape.
- Return: meta.json shape from `schema/acn-contract.json`.
- Never commit, never push, never reach secrets, never publish.

MODEL DRIFT is the worker returning `actual_model != requested_model` —
router fallback, harness default, or silent substitution. Drift surfaces
at every autonomy level (including high) and blocks `validated` until
the task is re-run under the pinned model.

## Operating loop

1. Load the universal `beastmode` skill first. Read the acceptance
   contract step and autonomy-levels reference.
2. Smoke-gate every worker lane before routing. If a lane fails,
   document it as installed-but-not-live and skip it for the run.
3. Write the acceptance contract in the universal format. Capture: goal
   / non-goals / user-visible acceptance / files likely touched /
   verification commands / manual QA / escalation triggers /
   self-improvement log path.
4. For each ACN task, create a per-task git worktree, write the worker
   prompt to `.codex/beastmode-runs/<ts>-<lane>/prompt.md`, and dispatch
   a pinned-model invocation (`codex exec --model <id>`, `droid exec
   --model <id>`, `qwen-agent`, or the MiniMax API).
5. Wait for each worker. Read each child's `actual_model` against the
   requested tier; flag MODEL DRIFT before reading the body.
6. Surface the phase report. At low and medium, halt and wait for
   approval. At high, continue into the next batch.
7. The director applies acceptable patches. Workers never commit.

## Completion contract (on `goal_complete`)

Universal Beastmode artifacts, written in this order:

1. **Worker run record** — Codex-specific: each
   `.codex/beastmode-runs/<ts>-<lane>/` directory holds `prompt.md`,
   `output.md`, and the `meta.json` shape from `schema/acn-contract.json`.
2. **Acceptance contract delta** — update the contract file with actual
   vs planned for each acceptance bullet, and the verification commands
   that passed.
3. **Self-improvement entry** — append to `<repo>/.learnings/BEASTMODE.md`
   with `## Role Routing`, `## Acceptance Checks`, `## Result`, `## What
   Worked`, `## What Failed / Drifted`, `## Routing Rule To Change`.
4. **Report**: goal statement, lane, acceptance criteria, verification
   evidence, run-record path(s), self-improvement entry path, next
   action.

## Hard rules (universal, non-negotiable)

- The director (the Codex session, always frontier) reviews and applies
  all worker output. Workers never commit, push, hold secrets, or claim
  final verification.
- The verifier-first rule beats cost optimization.
- No watcher, no validated: evidence-only close-out, goal stays active.
- MODEL DRIFT always surfaces and blocks `validated` at every level.
- Gates are blocking below high.

## Legacy note

The legacy `beastmode-qwen-cloud` skill is superseded by this adapter.
The Qwen / MiniMax API / Droid MiniMax / GLM lanes that used to live
there are listed as worker lanes in this adapter; the same contracts,
smoke gates, and `--auto low` style Droid invocations apply. Consumers
still referencing `beastmode-qwen-cloud` should migrate to this adapter.

## See also

- `beastmode` (v2.5.0) — the canonical framework this adapter implements
- `schema/acn-contract.json` — machine source of truth for batch / task
  / meta.json shapes
- `references/autonomy-levels.md` and `references/orchestration-comparison.md`
