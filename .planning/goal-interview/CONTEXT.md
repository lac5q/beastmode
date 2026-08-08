# Phase 201: Beastmode Goal Interview — CONTEXT

**Date:** 2026-08-07
**Source:** Operator goal (verbatim concern): beastmode "just runs" — the GSD planning phase
asks good clarifying questions, but beastmode runs never surface interview questions, neither
up front nor during execution. Requested: interviews ahead of time and in-process when
autonomy is low or default (medium).

## Domain

Add an autonomy-scaled interview protocol to the beastmode skill (repo
`lac5q/beastmode`, installed at `~/.claude/skills/beastmode`): an upfront Goal Interview step
before the acceptance contract, and Open Questions surfaced at the existing blocking phase
gates for low/medium autonomy.

## Decisions (locked)

- **D1 — Upfront interview is a first-class loop step** (new Step 1 between Preflight and
  Acceptance Contract), not an optional flag. Source: operator ("implement them ahead of time").
- **D2 (amended 2026-08-07) — Autonomy scales the interview**: low = full interview until no
  material gray areas; medium (default) = one batched round of top 3–5 questions, remainder
  become explicit Assumptions; high = same batched round up front, then NEVER asks again
  (escalation triggers only). Source: operator ("when autonomy is set to a lower level or
  default"; amendment: "high autonomy should interview at first but not afterwards").
- **D3 — In-process questions ride the existing gates.** Workers never contact the user;
  ambiguity becomes a `needs_decision` item in worker meta; at low/medium every gate report
  gains a mandatory `## Open Questions` section that blocks until answered/deferred. No new
  gate types invented.
- **D4 — Schema is source of truth**: interview matrix lands in
  `schema/autonomy-levels.json`; prose references mirror it.
- **D5 — Runtime enforcement via `bm` prompt composition**: new `bm_interview_prompt` in
  `scripts/lib/prompts.sh` injected by `scripts/bm`, plus `--interview` override flag. This is
  the actual fix for "I never see questions" — the composed run prompt previously contained
  zero interview language.
- **D6 — GSD interop, not duplication**: existing GSD CONTEXT.md/SPEC.md decisions are
  imported, never re-asked; `gsd-discuss-phase` may serve as the upfront interview when the
  repo uses GSD.
- **D7 — Non-interactive lanes auto-downgrade** to assumptions-only and log the downgrade.
- **D9 (added 2026-08-07) — Run ledger + progress digests**: append-only
  `.beastmode/LEDGER.md` (one line per worker dispatch/completion/failure/gate/merge with
  requested→actual model, tokens, % of budget); compact ≤8-line progress digest at every
  phase gate and at least hourly; final report gains a per-worker table + failures section.
  Deliberately light — no new tooling, data comes from existing worker meta.json /
  acn-report. Source: operator ("track worker usage and failures along the way and at the
  end; don't overdo it — enough to scroll back every hour or so").
- **D8 — Pipeline per operator instruction**: architect = Fable (high), implement =
  gpt-5.6-luna (`model_reasoning_effort="max"` via codex exec, isolated worktree), validate =
  claude-opus-4-8 (`--effort high`, read-only review). Director (Fable session) merges.

## Deferred ideas

- `bm` TUI/interactive question renderer (beyond prompt-level instruction) — separate phase.
- Persisting interview transcripts as GSD DISCUSSION-LOG.md equivalents in `.beastmode/`.
- Wiring `needs_decision` counts into `acn-report` summary output.

## Canonical refs

- `~/.claude/skills/beastmode/SKILL.md` — canonical skill (v2.4.0 → 2.5.0)
- `~/.claude/skills/beastmode/schema/autonomy-levels.json` — machine source of truth
- `~/.claude/skills/beastmode/scripts/lib/prompts.sh` — run-prompt composition
- `~/.cursor/get-shit-done/workflows/discuss-phase.md` — GSD interview protocol (pattern source)
- `.planning/goal-interview/DESIGN.md` — full design package (Fable)
