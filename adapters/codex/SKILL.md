---
name: beastmode-codex
description: Codex harness adapter for the universal Beastmode MofA framework, absorbing the beastmode-cloud worker lanes
version: 1.0.0
author: Luis Calderon
tags: [beastmode, mofa, codex, orchestration, multi-agent, model-routing, acn]
related_skills: [beastmode, gsd, beastmode-cloud]
source_repo: https://github.com/lac5q/beastmode/blob/main/adapters/codex/SKILL.md
---

# Beastmode Codex — Codex Harness Adapter

This skill is **only the harness mechanics**. The framework, tier-routing
rule, verifier-first design principle, and self-improvement loop live in
the canonical `beastmode` skill (v2.2.0) — load it first and follow it.
This adapter tells you which Codex primitives implement which seat and
which external lanes the bounded workers can call.

**Note**: the legacy `beastmode-qwen-cloud` skill is superseded by this
adapter. The Qwen / MiniMax API / Droid / GLM lanes that used to live
there are listed as worker lanes below; the same contracts and smoke
gates apply.

## Only the harness mechanics

| Universal seat | Codex implementation |
|---|---|
| Director (frontier) | The Codex session itself — frontier model, owns intent, design, merge gate |
| Watcher (frontier) | A Codex-side validator, or a second frontier session via an external lane |
| Executor (economy) | External cheap lanes (Qwen, MiniMax API, Droid MiniMax, GLM, custom Droid models) |
| Loop engine | Director self-prompts between worker results |
| Anti-spin | Director judgment + usage budget; abort on 3 identical blockers |
| Worker-contract enforcer | Codex sandbox defaults + starter worker contract; `--yolo` is high-only |
| Live progress | `.codex/beastmode-runs/<ts>-<lane>/output.md` plus any task transcript |
| Goal record | `<repo>/GOAL.md` (universal fallback) |
| Self-improvement log | `<repo>/.learnings/BEASTMODE.md` (universal) |

## Worker lanes (absorbed from beastmode-cloud)

External cheap lanes the Codex director routes bounded workers into.
Smoke-gate every lane before routing; failed lane = installed-but-not-live,
route elsewhere.

| Lane | Default model | Command | Smoke gate |
|------|---------------|---------|------------|
| Qwen | `qwen3.7-plus` | `~/.local/bin/qwen-agent` | Reply exactly `QWEN OK` |
| MiniMax API | `MiniMax-M3` | `curl https://api.minimax.io/v1/chat/completions` | Reply exactly `MINIMAX OK` (never print the key) |
| Droid MiniMax | `minimax-m3` | `~/.local/bin/droid exec --model minimax-m3` | Reply exactly `MINIMAX OK` |
| Droid custom | any `droid exec --list-tools` model id | `~/.local/bin/droid exec --model <id>` | Model-specific exact reply |
| GLM | `glm-4.6` | `~/.local/bin/droid exec --model glm-4.6` (or direct API) | Reply exactly `GLM OK` |

Prefer the direct MiniMax API lane when `MINIMAX_API_KEY` is present and
the worker only needs a patch, plan, or analysis. Use Droid MiniMax when
you specifically need Factory's agent runtime or tool access. Use Qwen or
GLM when an independent cross-family validator is wanted.

### Lane smoke gates

```bash
# Qwen
~/.local/bin/qwen-agent --dangerously-skip-permissions -p "Reply with exactly: QWEN OK"

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

Every worker invocation names its model explicitly:

- CLI lanes: `--model <id>` on the invocation (e.g. `droid exec --model
  minimax-m3`).
- Direct MiniMax API: the `model` field in the JSON body.
- Codex children: `codex exec --model <provider/model>`.

Never rely on the harness default for economy work. Pin it. After each
worker returns, persist a `meta.json` in the run record with the shape
from `schema/acn-contract.json` (`requested_model`, `actual_model`,
`stop_reason`, `usage`, `files_changed`, `commands_run`, `verify`).
Drift (`actual_model != requested_model`) is silent substitution —
surface it as MODEL DRIFT and block `validated` until the task is re-run
under the pinned model.

Unverifiable child model = **UNVERIFIED DRAFT** lane. Output may be used
as input but is never `validated` until re-checked under a pinned model.

## Autonomy mapping

| Level | What runs without surfacing | What always surfaces |
|---|---|---|
| **low** | Single executor turn, one read-only tool call | Every phase, every child result, every merge — every merge waits for approval |
| **medium** (default) | Whole phase: acceptance → design → delegate → validate → review | Security/auth/payments/data-loss events, model failure, **MODEL DRIFT**, `goal_blocked`, the merge gate |
| **high** | Multi-batch until `goal_complete` or repeated `goal_blocked` (≤ 3) | Budget exhaustion, no-watcher / no-validated, secrets in prompt, unrevalidated drift |

Gates are blocking below high. At low, Codex sandbox approval prompts
stay on; no `--yolo`; every merge waits for approval. To enter high
inside the worker contract, pass
`--yolo` or `--full-auto` to `codex exec`. Even at high, the run still
halts on budget exhaustion, no watcher, no validated, secrets-in-prompt,
and unrevalidated MODEL DRIFT — those are universal. **gates are blocking
below high.**

```
Phase <n> <name>: <status>
Models: requested <tier: provider/model> → actual <provider/model per task>
Drift: none | MODEL DRIFT: <requested> → <actual> on <task(s)>
```

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

- `beastmode` (v2.2.0) — the canonical framework this adapter implements
- `schema/acn-contract.json` — machine source of truth for batch / task
  / meta.json shapes
- `references/autonomy-levels.md` and `references/orchestration-comparison.md`
