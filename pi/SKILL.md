---
name: beastmode-pi
description: Pi-specific harness adapter for the universal Beastmode MofA orchestration framework (see the `beastmode` skill, v2.1). Composes five installed pi packages into the universal loop — pi-goal as the in-session goal engine, pi-dynamic-workflows as the fan-out / model-router, pi-loop-police as the anti-spin circuit breaker, pi-permission-system as the worker-contract enforcer, rpiv-todo + pi-telegram as live visibility. Use when Luis asks for beastmode, a Mixture-of-Agents run, autonomous goal execution, planner/worker/watcher, or a phase takeover inside a pi session.
version: 1.0.0
author: Luis Calderon
tags: [beastmode, mofa, pi, orchestration, multi-agent, model-routing, worktrees, self-improving]
related_skills: [beastmode, gsd]
source_repo: https://github.com/lac5q/beastmode/blob/main/pi/SKILL.md
---

# Beastmode Pi — Pi Harness Adapter

This skill is **only the harness mechanics**. The framework, tier-routing
rule, verifier-first design principle, and self-improvement loop live in the
canonical `beastmode` skill (v2.1) — load it first and follow it. This
adapter tells you which pi packages implement which role and how to wire
them together.

| Universal Beastmode role | Pi implementation |
|---|---|
| Director / Lead (frontier tier) | The pi session itself — frontier model stays in charge |
| Watcher (adversarial review) | `pi-dynamic-workflows` `verify()` / `judgePanel()`, or the built-in `/adversarial-review` workflow |
| Worker (economy tier) | `pi-dynamic-workflows` `agent()` with `tier: "small"`/`"medium"` or an external lane (Qwen / MiniMax API / Droid MiniMax) routed via `model:` |
| Loop engine (continues until done) | `@narumitw/pi-goal` — `/goal`, `goal_complete`, `goal_blocked` |
| Anti-spin circuit breaker | `pi-loop-police` (passive, always on) |
| Worker-contract enforcer | `@gotgenes/pi-permission-system` project config (path / external_directory / bash deny + ask surfaces) |
| Live progress visibility | `@juicesharp/rpiv-todo` overlay (TUI) and `/workflows` navigator |
| Remote supervision | `@llblab/pi-telegram` proactive push (only if `/telegram-setup` was completed) |
| Durable goal record | Optional: any goal store (MemRoOS `/api/gsd/goal`, plain file, etc.). Beastmode itself does **not** require a specific store. |
| Self-improvement log | `<repo>/.learnings/BEASTMODE.md` (universal) — consumer projects (e.g., memroos) may overlay `.beastmode/learnings/<date>-<slug>.md` as a house flavor |

## Preflight (per host)

```bash
pi --version                    # must be >= 0.80.6 (pi-goal requires it)
pi list                         # must include all six packages; install missing:
pi install npm:@narumitw/pi-goal \
  npm:@quintinshaw/pi-dynamic-workflows \
  npm:pi-loop-police npm:@gotgenes/pi-permission-system \
  npm:@juicesharp/rpiv-todo npm:@llblab/pi-telegram
pi --list-models | head         # confirm frontier + economy models exist on this host
```

**Model availability.** `bm "<goal>" --frontier kimi3 --economy minimax` will
exit with code 2 before any `pi` invocation if either resolved
`provider/model` is missing from `pi --list-models`. The error lists the
available alternatives so you can pick a working alias without losing the
goal to a mid-run crash. Skip with `BM_SKIP_MODEL_CHECK=1` (CI / scripted
runs where `pi` may not be installed).

Telegram supervision is optional. `/telegram-setup` is interactive and needs a
bot token from `@BotFather`; if it was never completed, skip telegram silently
rather than blocking a run on it.

## Lane smoke gates (mirror `beastmode-cloud`)

Before routing work to an external cheap lane, prove it is live. If a lane
fails its smoke gate, report it as installed-but-not-live and route to a
different lane (or the pi-native tier).

```bash
# Qwen lane
~/.local/bin/qwen-agent --dangerously-skip-permissions -p "Reply with exactly: QWEN OK"

# Direct MiniMax API lane (the key is fed on stdin, never placed in process argv)
printf 'Authorization: Bearer %s\nContent-Type: application/json\n' "$MINIMAX_API_KEY" | \
curl -sS https://api.minimax.io/v1/chat/completions \
  -H @- \
  -d '{"model":"MiniMax-M3","thinking":{"type":"disabled"},"messages":[{"role":"user","content":"Reply with exactly: MINIMAX OK"}],"max_completion_tokens":20,"temperature":0}'

# Droid MiniMax lane
~/.local/bin/droid exec --model minimax-m3 "Reply with exactly: MINIMAX OK"

# Claude Pro lane (Claude Code CLI print mode, uses claude.ai Pro/Max quota)
claude --dangerously-skip-permissions -p --model opus "Reply with exactly: CLAUDE OK"
# Or via the wrapper:
~/.local/bin/claude-pro "Reply with exactly: CLAUDE OK"
```

Pi-native tiers (`small` / `medium` / `big` via `/workflows-models`) need no
smoke gate. Keep automatic worker and watcher routing on MiniMax-M3; use a
frontier director or watcher only when the user explicitly names it. Prefer
external CLI lanes for the bulk cheap-worker execution you already pay for.
The verifier-first rule from the universal skill governs everything:
if a cheap lane cannot produce a verifiable artifact cheaply, escalate to
the frontier tier.

## Claude routing rule (hard rule)

**All Claude work in beastmode routes through the Claude Pro lane (`claude -p`,
`~/.local/bin/claude-pro`), never through the workflow tool's `agent()` with
an `anthropic/*` model spec.** The `anthropic` OAuth API credential in
`~/.pi/agent/auth.json` shares a single "extra usage" pool across every
Claude model (`claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5`,
etc.) and that pool is rate-limited. Routing Claude work through
`workflow agent({model: "anthropic/claude-opus-4-8"})` fails with HTTP 400
*"You're out of extra usage"* and burns the whole run.

The hard rule is enforced by:

- `~/.pi/workflows/model-tiers.json` — every automatic tier maps to the
  **approved cheap lane** (small/medium/big → MiniMax-M3). No automatic tier
  maps to Codex or another frontier model. Any frontier/Codex worker must be
  explicitly named by the user and pinned by exact `model:`.
- A workflow author who explicitly writes
  `agent(prompt, { model: "anthropic/claude-opus-4-8" })` is bypassing the
  tier system. Don't do it. Use `claude -p --model opus` from the director
  instead, exactly like the Qwen / MiniMax / droid lanes above.

For Claude frontier work, the pattern is:

```bash
# Director (this pi session) calls the lane directly via bash
claude -p --model opus --dangerously-skip-permissions "<prompt>"
# or, equivalently:
~/.local/bin/claude-pro "<prompt>"
```

`claude -p` is non-interactive (`--print`), reads the prompt from argv (or
stdin via `<`), and exits with the model's reply on stdout. It draws from
the claude.ai Pro/Max subscription quota, which is separate from and not
rate-coupled to the API OAuth credential.

If you find yourself wanting Claude inside a workflow subagent — for example
because you want it to fan out in parallel — escalate to the universal
beastmode framework first: the verifier-first rule plus parallel cheap
lanes almost always covers the case without paying Claude frontier prices
on every worker. Reserve `claude -p` for watcher-tier judgment and
verifier-tier review, never for bulk cheap work.

## Operating loop

1. **Load the universal skill first.** Read `beastmode` v2.1 — Step 0
   (preflight), Step 1 (acceptance contract), Step 2 (design with
   challenge). This adapter does not redefine those.

2. **Optional durable goal record.** Beastmode itself does not require a
   specific goal store. If the consumer repo overlays one (e.g., memroos
   posts to `/api/gsd/goal`), call it; if absent, write the acceptance
   contract to a file (`GOAL.md` at the repo root is the universal fallback)
   and proceed.

3. **Write the acceptance contract** in the universal format (see the
   `beastmode` skill, Step 1). Capture: goal / non-goals / user-visible
   acceptance / files likely touched / verification commands / manual QA /
   escalation triggers / self-improvement log path.

4. **Start the loop engine.** Activate pi-goal with the contract condensed
   into a `/goal` invocation:

   ```
   /goal --tokens 100k <goal statement + numbered done-when criteria>
   ```

   pi-goal auto-continues from pi's idle boundary until the model calls
   `goal_complete({goal_id, summary})`. Summaries that contradict evidence
   ("tests still failing") are rejected by the tool — don't try to word
   around it. A true impasse (same blocker on 3 consecutive goal turns, with
   concrete evidence) goes through `goal_blocked({goal_id, reason, evidence,
   repeated_turns})`. Budget exhaustion (`budget_limited`) is a normal stop
   state: report spent vs remaining and propose a resume slice.

   Prefer one long goal run over several short ones. The director's prefix
   (contract + accumulated history) stays cached across auto-continued turns;
   stopping and re-invoking `/goal` restarts cold and re-pays the write.

5. **Fan out with pi-dynamic-workflows** for any phase where the work is
   wider than a single agent (multi-file audits, >3 independent slices,
   parallel reviews, codebase-wide research). Write a deterministic JS
   orchestration script using `agent()` / `parallel()` / `pipeline()` /
   `phase()` with these conventions:

   - Route workers to `tier: "small"`/`"medium"` or an exact
     `model: "provider/modelId"` for a proven external lane
   - **Group agents by lane, not round-robin.** Each distinct model/lane keeps
     its own prompt cache. Consecutive `agent()` calls sharing a lane and a
     byte-identical prefix read at 0.10x; alternating lanes forces a fresh
     1.25x write on every switch. In `parallel()`, order the array so same-lane
     workers are adjacent.
   - **Put the shared contract first, the per-task objective last.** The worker
     contract is the cacheable prefix — keep it identical across every worker
     and append only the task-specific slice after it. Never splice a task ID,
     timestamp, or worker index into the contract header.
   - Set `isolation: "worktree"` whenever workers edit, so parallel edits do
     not collide
   - Cross-check with `verify()` or `judgePanel()` as the watcher; or use
     the built-in `/adversarial-review` workflow directly
   - Add `checkpoint()` for any human-approval gate you want journaled into
     the workflow's resume log
   - Set phase budgets on expensive phases; use `budget` to inspect real
     spend mid-run
   - The `/workflows` navigator shows phases, agents, models, tokens, cost,
     and live tok/s; `agent()` accepts a JSON Schema `schema:` for typed
     results so cross-checking is structural

   Every worker prompt MUST carry the universal beastmode worker contract:
   exact repo path, objective, allowed files/directories, allowed commands,
   forbidden commands (commit, push, delete outside scope, publish, send
   email, access secrets, change cloud config), required output (summary,
   unified diff or exact files changed, commands run, verification notes,
   risks/blockers). Workers never commit or push — the director merges.

6. **Guardrails are already on.** loop-police needs no configuration; if it
   fires repeatedly on one subtask, shrink the slice or switch worker lane.
   The project permission config (see `references/pi-permission-config.md`
   for a starter) denies secret paths and forces `ask` on `git push`,
   `git commit`, `rm -rf`, `sudo`, publish-class commands; the director
   (human or pi session) approves merges; workers physically cannot reach
   secrets or leave the repo. `/goal --tokens` plus workflow phase budgets
   bound total spend.

7. **Visibility.** In the TUI, rpiv-todo keeps a live checklist and
   `/workflows` opens the run navigator. If telegram was set up, proactive
   push mirrors completed checkpoints to the phone; never paste tokens,
   diffs containing secrets, or private data into telegram-bound text.

## Completion contract (on `goal_complete`)

Beastmode's universal artifacts, written in this order:

1. **Worker run record** — harness-specific. With pi-dynamic-workflows, this
   is the workflow run journal (id, phases, agent transcripts, token / cost
   per agent, real `usage` blocks) — export or reference it; the universal
   shape is the one in `schema/acn-contract.json`: `{"id",
   "requested_model", "actual_model", "stop_reason", "usage":
   {"input_tokens", "output_tokens"}, "files_changed", "commands_run",
   "verify"}`. For runs that used external CLI lanes (qwen-agent, droid
   exec, MiniMax curl), persist a `meta.json` next to the run record with
   the same shape, populated from the lane's reported usage.

   `requested_model` is what the batch pinned; `actual_model` is what the
   lane reports it actually ran. Both are required — a record with one
   merged `model` field cannot prove drift in either direction, and
   `scripts/enforce-models --check-meta` fails it as **unverifiable**
   rather than passing it. Verify a run's records with
   `scripts/enforce-models --check-meta <run-dir>` before claiming
   `validated`.
2. **Acceptance contract delta** — update the contract file (the one from
   Step 3) with actual vs planned for each acceptance bullet, and the
   verification commands that passed.
3. **Self-improvement entry** — append a section to
   `<repo>/.learnings/BEASTMODE.md` (universal) with: `## Role Routing`,
   `## Acceptance Checks`, `## Result`, `## What Worked`, `## What Failed /
   Drifted`, `## Routing Rule To Change` (Yes/No + what). If every watcher
   tier failed, record the code/test/build evidence and leave the goal
   active — never claim beastmode validation without a watcher.
4. **Optional: post completion** to the consumer repo's durable goal store
   if one is configured.
5. **Report**: goal statement, lane, acceptance criteria, verification
   evidence, run-record path(s), self-improvement entry path, next action.

Consumer projects may overlay additional house artifacts (e.g., memroos
also writes `.beastmode/worker-runs/<UTCts>-<slug>/{prompt,output,meta}`
files). The universal contract above is the floor; consumer extras are
fine.

## Hard rules (universal, non-negotiable)

- The director (pi session, always a frontier-tier model) reviews and
  applies all worker output. Workers never commit, push, hold secrets, or
  claim final verification.
- The verifier-first rule beats cost optimization: a cheap lane with a
  cheap verifier always wins over a frontier lane doing the same work.
- Never unset strict memory, widen permission config, or disable
  loop-police to make a run pass. A blocked run is a finding, not a bug
  in the guardrail.
- No watcher, no "validated": evidence-only close-out, goal stays active.
- Budget exhaustion (`budget_limited`) is a normal stop state: report
  spent vs remaining and propose the resume slice, do not silently
  continue.

## See also

- `beastmode` (v2.1) — the canonical framework this adapter implements
- `references/pi-permission-config.md` — starter permission-system config
  encoding the worker contract
- `references/context-rot-mitigation.md` (in the universal skill) — keep
  orchestrator context small; route bulk work into pi-dynamic-workflows so
  the director context only carries summaries. Also covers prompt-cache
  preservation (never compress prompts at the API layer) and the break-even
  math; `scripts/cache-hitrate` verifies caching survives your proxy chain.
- `references/model-routing.md` (in the universal skill) — the
  verification-cost routing rule that governs tier choice
