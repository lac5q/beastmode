---
name: beastmode-hermes
description: Hermes harness adapter for the universal Beastmode MofA framework - ACN async parallel sub-agents via delegate_task. Use when Luis asks for beastmode, Mixture-of-Agents, autonomous goal execution, or a phase takeover inside a Hermes session.
version: 1.0.0
author: Luis Calderon
tags: [beastmode, mofa, hermes, orchestration, multi-agent, model-routing, acn]
related_skills: [beastmode, gsd]
source_repo: https://github.com/lac5q/beastmode/blob/main/adapters/hermes/SKILL.md
---

# Beastmode Hermes - Hermes Harness Adapter

This skill is **only the harness mechanics**. The framework, tier-routing
rule, verifier-first design principle, and self-improvement loop live in the
canonical `beastmode` skill (v2.5.0) - load it first and follow it. This
adapter tells you which Hermes primitives implement which seat and how to
wire them together.

## Only the harness mechanics

| Universal seat | Hermes implementation |
|---|---|
| Director / Lead (frontier tier) | The Hermes session itself - frontier model |
| Watcher (adversarial review, frontier) | A second `delegate_task` on a frontier model only after the user explicitly names it |
| Executor (economy tier) | `delegate_task` children pinned to MiniMax-M3 |
| Loop engine (continues until done) | The agent's own phase loop (director prompts itself between subagent results) |
| Anti-spin circuit breaker | Director judgment + the run's usage / wall-clock budget; abort on 3 identical blockers |
| Worker-contract enforcer | `~/.hermes/config.yaml` `permissions` / `toolsets` denials + a starter worker contract in the prompt |
| Live progress visibility | `~/.hermes/cache/delegation/live/<id>/task-<n>.log` (tail in a terminal) |
| Remote supervision | Optional: any deliver='telegram' cron mirroring, or the parent OpenClaw channel |
| Durable goal record | Optional: write the acceptance contract to `<repo>/GOAL.md` (universal fallback) |
| Self-improvement log | `<repo>/.learnings/BEASTMODE.md` (universal) |

Automatic Hermes children use MiniMax-M3 only. If a failure or risk trigger
would normally call for a frontier watcher, stop and ask the user to name the
model; never silently fall back to Codex, GPT, Claude, Kimi, or another
frontier lane.

## ACN - async parallel sub-agents

ACN is the universal Beastmode fan-out layer. In Hermes, it is `delegate_task`.

- A single top-level `delegate_task(goal=...)` **runs in the background** and
 returns a handle immediately. The child finishes; the result re-enters the
 director's conversation as a new message. The chat path is not blocked.
- `delegate_task(tasks=[...])` is the **batch shape** - one handle, up to
 `delegation.max_concurrent_children` (default 3) running in parallel, all
 results consolidated into a single message when the last task finishes.
- Each child writes a live transcript under
 `~/.hermes/cache/delegation/live/<delegation_id>/task-<n>.log` - tail
 that file to watch progress without polluting the director context.
- The `/agents` overlay in the Hermes dashboard surfaces every active child
 with its model, elapsed time, and last log line.
- `role="orchestrator"` children can spawn their own workers
 (`max_spawn_depth` in `delegation.*`). Nesting is OFF by default
 (`max_spawn_depth=1`); raise it in `config.yaml` only when a phase truly
 needs fan-out-of-fan-out.

## MODEL PINNING (hard rule)

Before a beastmode ACN run, pin the executor seat so the runtime can prove
the child model. Edit `~/.hermes/config.yaml`:

```yaml
delegation:
 provider: minimax
 model: MiniMax-M3
 max_concurrent_children: 3
```

Director-board policy: director and watcher seats get the same treatment
when the ACN batch includes them as separate children. After the run,
restore the previous `delegation.{provider,model}` (back the file up first).

If the runtime cannot prove the child model - no meta in the response, no
config pin, no harness journal - the children are **UNVERIFIED DRAFT** lanes.
Their output may be used as input (read it, summarize it, react to it) but
is never `validated` until re-checked under a pinned model. Drift is fail-
closed: drift invalidates the lane for the rest of the run.

## Autonomy mapping

| Level | What runs without surfacing | What always surfaces |
|---|---|---|
| **low** | Single executor turn, one read-only tool call | Every phase, every child result, every merge - wait for human approval between each batch |
| **medium** (default) | Whole phase: acceptance → design → delegate → validate → review | Security/auth/payments/data-loss events, any model failure, **MODEL DRIFT**, `goal_blocked`, the merge gate |
| **high** | Multi-batch until `goal_complete` or repeated `goal_blocked` (≤ 3) | Budget exhaustion, no-watcher / no-validated, secrets in prompt, unrevalidated drift |

**Gates are blocking below high.**

**stops**: at low and medium, "surfaces" means
before the next phase or any merge. A run that keeps going past a surfaced
gate at low/medium is a harness bug - treat it as `goal_blocked` and stop.

Per-phase usage report at every level:

```
Phase <n> <name>: <status>
Models: requested <tier: provider/model> → actual <provider/model per task>
Drift: none | MODEL DRIFT: <requested> → <actual> on <task(s)>
```

## Interview mapping

Run one combined `clarify()` batch per upfront interview round; never issue N
parallel clarifies. Surface accrued gate open questions through that same
combined batch mechanism, including explicit answers or deferrals.

## Worker prompt contract

Byte-identical shared contract across every child in the batch; the per-task
objective is appended **after** the shared prefix. Hermes prompt-cache
penalizes divergent prefixes at ~1.25x write, so keep the contract stable
across children and only splice the task-specific slice.

Every child must:

- Receive: exact repo path, objective, allowed files/directories, allowed
 commands, forbidden commands (commit, push, rm -rf, publish, send, access
 secrets, change cloud config), required output shape.
- Return: meta.json shape from `schema/acn-contract.json`
 (`requested_model`, `actual_model`, `stop_reason`, `usage`,
 `files_changed`, `commands_run`, `verify`).
- Never commit, never push, never reach secrets, never publish.

**MODEL DRIFT** is the child returning `actual_model != requested_model` - 
router fallback, harness default, or silent substitution. Drift surfaces at
**every** autonomy level (including high) and blocks `validated` until the
same task is re-run under the pinned model. Record every drift in the
self-improvement entry; repeated drift on the same alias means the tier
alias or provider config is wrong.

Unverifiable child model = **UNVERIFIED DRAFT** lane. A child whose meta is
missing, unreadable, or carries a single merged `model` instead of both
model fields cannot be compared, and an impossible comparison is not a pass.
Its output may be used as input but is never `validated` until re-checked
under a pinned model. Run the gate over the batch directory before you
report `validated`:

```bash
scripts/enforce-models --check-meta <run-dir> --attestations <parent-owned-harness-journal.json> --trust-attestations
```

Exit 1 means drift or unverifiable; either way the batch is not validated.

## Operating loop

1. Load the universal `beastmode` skill first. Read the acceptance contract
 step and the autonomy-levels reference. This adapter does not redefine
 those.
2. Pin the executor model in `~/.hermes/config.yaml` (see MODEL PINNING).
 Back the file up first.
3. Write the acceptance contract in the universal format (see
 `beastmode`, Step 2). Capture: goal / non-goals / user-visible acceptance
 / files likely touched / verification commands / manual QA / escalation
 triggers / self-improvement log path.
4. Fan out with `delegate_task(tasks=[...])` for any phase wider than one
 agent. Group tasks by lane, not round-robin - same model + same
 byte-identical contract prefix keeps the cache hot (~0.10x read);
 alternating lanes force a fresh 1.25x write on every switch.
5. Pass the worker prompt contract into every child verbatim. Append the
 task-specific objective last.
6. Wait for the consolidated batch result. Compare each child's
 `actual_model` against the requested tier; flag MODEL DRIFT before
 reading the body.
7. Surface the phase report (models / drift / tokens / time). At low and
 medium, halt and wait for approval. At high, continue into the next
 batch.
8. Restore the previous `delegation.{provider,model}` (or leave the pin if
 the run will continue).

## Completion contract (on `goal_complete`)

Universal Beastmode artifacts, written in this order:

1. **Worker run record** - Hermes-specific: the delegation journal
 (`<id>` from the `delegate_task` handle) plus each child's
 `meta.json` shape from `schema/acn-contract.json`. Persist them under
 the run-record path the universal skill specifies.
2. **Acceptance contract delta** - update the contract file from Step 2
 with actual vs planned for each acceptance bullet, and the verification
 commands that passed.
3. **Self-improvement entry** - append to `<repo>/.learnings/BEASTMODE.md`
 with: `## Role Routing`, `## Acceptance Checks`, `## Result`,
 `## What Worked`, `## What Failed / Drifted`, `## Routing Rule To
 Change`. If every watcher tier failed, record the code/test/build
 evidence and leave the goal active - never claim beastmode validation
 without a watcher.
4. **Report**: goal statement, lane, acceptance criteria, verification
 evidence, run-record path(s), self-improvement entry path, next
 action.

## Hard rules (universal, non-negotiable)

- The director (the Hermes session, always front-tier) reviews and applies
 all worker output. Workers never commit, push, hold secrets, or claim
 final verification.
- The verifier-first rule beats cost optimization: a cheap lane with a
 cheap verifier always wins over a frontier lane doing the same work.
- no watcher, no validated: evidence-only close-out, goal stays active.
- MODEL DRIFT always surfaces and blocks `validated` at every level.
- Gates are blocking below high.

## See also

- `beastmode` (v2.5.0) - the canonical framework this adapter implements
- `schema/acn-contract.json` - machine source of truth for the batch / task
 / meta.json shapes
- `references/autonomy-levels.md` - the three-level scale and surfacing rules
- `references/orchestration-comparison.md` - how this ACN shape lines up
 with pi / Claude Code / Codex
