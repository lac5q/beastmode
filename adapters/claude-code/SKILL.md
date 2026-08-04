---
name: beastmode-claude-code
description: Claude Code harness adapter for the universal Beastmode MofA framework
version: 1.0.0
author: Luis Calderon
tags: [beastmode, mofa, claude-code, orchestration, multi-agent, model-routing, acn]
related_skills: [beastmode, gsd]
source_repo: https://github.com/lac5q/beastmode/blob/main/adapters/claude-code/SKILL.md
---

# Beastmode Claude Code — Claude Code Harness Adapter

This skill is **only the harness mechanics**. The framework, tier-routing
rule, verifier-first design principle, and self-improvement loop live in
the canonical `beastmode` skill (v2.4.0) — load it first and follow it.

## Only the harness mechanics

| Universal seat | Claude Code implementation |
|---|---|
| Director (frontier) | The Claude Code session itself — frontier, e.g. opus or fable |
| Watcher (frontier) | A second frontier session, prefer cross-family via an external lane |
| Executor (economy) | Task subagents, or parallel `claude -p --model <economy>` lanes |
| Loop engine | Director self-prompts between subagent results |
| Anti-spin | Director judgment + usage budget; abort on 3 identical blockers |
| Worker-contract enforcer | `--permission-mode` plus a starter worker contract in the prompt |
| Live progress | Tail Task subagent transcripts or tmux panes running `claude -p` |
| Goal / self-improvement log | `<repo>/GOAL.md` and `<repo>/.learnings/BEASTMODE.md` (universal) |

## ACN — async parallel sub-agents

ACN is the universal Beastmode fan-out layer. In Claude Code it is the
Task tool plus parallel `claude -p` invocations.

Task spawns an in-session subagent (multiple Task calls in one turn run
sequentially). `/batch` fans worktree-isolated tasks out across separate
sessions for large parallel changes; each task gets its own branch and
worktree. Multiple background tmux / `claude -p` processes are the
parallel-of-parallel lane: each runs in its own shell, writes its own
out-file, director consolidates — one process per task keeps
prompt-cache locality. The director (this session) is always the merge
gate; workers never apply their own patches back without explicit approval.

## MODEL PINNING (hard rule)

Every ACN child must carry an explicit model:

- `--model <provider/model>` on every `claude -p` invocation.
- Subagent frontmatter `model: <provider/model>` for Task tool children.
- `~/.claude/settings.json` or the env-file the harness reads.

Never rely on the session default for economy work. Pin it. The director
board reads the requested model from the child's config and the actual
model from the harness journal — a mismatch is MODEL DRIFT.

After each child returns, persist a `meta.json` in the run record with
the shape from `schema/acn-contract.json` (`requested_model`,
`actual_model`, `stop_reason`, `usage`, `files_changed`, `commands_run`,
`verify`). Drift always surfaces and blocks `validated` until the task
is re-run under the pinned model. Unverifiable child model = unverified
draft lane, never validated.

## Claude Pro lane note

`claude -p` draws from the Pro/Max quota on claude.ai, not the
rate-limited API OAuth pool. Reserve it for **watcher judgment** and
**verifier review** — never bulk cheap work. For bulk economy workers,
route through a different lane (qwen, MiniMax via API, droid MiniMax)
and pin the model explicitly so the run record proves the actual model.

## Autonomy mapping

| Level | What runs without surfacing | What always surfaces |
|---|---|---|
| **low** | Single executor turn, one read-only tool call | Every phase, every child result, every merge — every merge waits for approval |
| **medium** (default) | Whole phase: acceptance → design → delegate → validate → review | Security/auth/payments/data-loss events, model failure, **MODEL DRIFT**, `goal_blocked`, the merge gate |
| **high** | Multi-batch until `goal_complete` or repeated `goal_blocked` (≤ 3) | Budget exhaustion, no-watcher / no-validated, secrets in prompt, unrevalidated drift |

Gates are blocking below high. At low, prefer `--permission-mode plan` or
`ask` before each batch; every child result surfaces; every merge waits
for approval. To enter high inside the worker contract, use
`--dangerously-skip-permissions` on the worker `claude -p` invocation or
the Task subagent's permission field. Even at high, the run still halts
on budget exhaustion, no watcher, no validated, secrets-in-prompt, and
unrevalidated MODEL DRIFT — those are universal. **gates are blocking
below high.**

```
Phase <n> <name>: <status>
Models: requested <tier: provider/model> → actual <provider/model per task>
Drift: none | MODEL DRIFT: <requested> → <actual> on <task(s)>
```

## Worker prompt contract

Byte-identical shared contract across every child; the per-task objective
is appended **after** the shared prefix. The Claude prompt cache
penalizes divergent prefixes at ~1.25x write, so keep the contract
stable and only splice the task-specific slice.

Every child receives: exact repo path, objective, allowed
files/directories, allowed commands, forbidden commands (commit, push,
rm -rf, publish, send, access secrets, change cloud config), required
output shape. Returns: meta.json shape from `schema/acn-contract.json`.
Never commits, never pushes, never reaches secrets, never publishes.

MODEL DRIFT is the child returning `actual_model != requested_model` —
router fallback, harness default, or silent substitution. Drift surfaces
at every autonomy level (including high) and blocks `validated` until
the task is re-run under the pinned model.

Unverifiable child model = **UNVERIFIED DRAFT** lane. A child whose meta is
missing, unreadable, or carries a single merged `model` instead of both
model fields cannot be compared, and an impossible comparison is not a
pass. Output may be used as input but is never `validated` until re-checked
under a pinned model. `scripts/enforce-models --check-meta <run-dir>` is the
gate; exit 1 means drift or unverifiable.

## Operating loop

1. Load the universal `beastmode` skill first. Read the acceptance
   contract step and autonomy-levels reference.
2. Pin the executor model on every child (--model flag or Task
   frontmatter). Group tasks by lane, not round-robin.
3. Write the acceptance contract in the universal format. Capture: goal
   / non-goals / user-visible acceptance / files likely touched /
   verification commands / manual QA / escalation triggers /
   self-improvement log path.
4. Fan out with Task for in-session subagents, `/batch` for worktree
   fan-out, parallel `claude -p` for independent cross-session lanes.
   Pass the worker contract verbatim; append the task-specific objective
   last.
5. Wait for children. Read each child's `actual_model` against the
   requested tier; flag MODEL DRIFT before reading the body.
6. Surface the phase report. At low and medium, halt and wait for
   approval. At high, continue into the next batch.
7. The director applies acceptable patches. Workers never commit.

## Completion contract (on `goal_complete`)

Universal Beastmode artifacts, written in this order:

1. **Worker run record** — Task subagent transcripts and the `claude -p`
   out-files, plus each child's `meta.json` shape from
   `schema/acn-contract.json`.
2. **Acceptance contract delta** — update the contract file with actual
   vs planned for each acceptance bullet, and the verification commands
   that passed.
3. **Self-improvement entry** — append to `<repo>/.learnings/BEASTMODE.md`
   with `## Role Routing`, `## Acceptance Checks`, `## Result`, `## What
   Worked`, `## What Failed / Drifted`, `## Routing Rule To Change`.
4. **Report**: goal statement, lane, acceptance criteria, verification
   evidence, run-record path(s), self-improvement entry path, next
   action.

## Hard rules

- The director (the Claude Code session, always frontier) reviews and
  applies all worker output. Workers never commit, push, hold secrets,
  or claim final verification.
- The verifier-first rule beats cost optimization.
- No watcher, no validated: evidence-only close-out, goal stays active.
- MODEL DRIFT always surfaces and blocks `validated` at every level.
- Gates are blocking below high.

## See also

- `beastmode` (v2.4.0) — the canonical framework this adapter implements
- `schema/acn-contract.json` — batch / task / meta.json shapes
- `references/autonomy-levels.md` and `references/orchestration-comparison.md`
