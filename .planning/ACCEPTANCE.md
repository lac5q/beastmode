# Acceptance Contract — Beastmode ACN Unification

Goal: one scales/families SoT + identical ACN (async parallel sub-agent) contract and enforcement across Hermes / Claude Code / Codex / Pi, shipped as beastmode v2.2.0 on branch `feat/acn-unification`.

Non-goals: standing-autonomy module merge, ACP editor integration, Ultraswarm, changes outside this repo (knowledge/memroos/devops get notes only), pushing to origin.

User-visible acceptance:
- `bm "<goal>" --harness hermes|pi|claude|codex --frontier <alias> --economy <alias> --watcher <alias> --autonomy low|medium|high` resolves seats, preflights models, and runs with the same phase-report / gate / drift prompts on every harness.
- `schema/` JSONs are the single source of truth for families, tiers, seats, autonomy levels, and the ACN contract; markdown docs point at them.
- Adapters document the same rules: pinned executor model, per-child meta.json (requested vs actual model), MODEL DRIFT always surfaces and blocks `validated`, gates blocking below high, workers never commit/push/secrets.

Run-time roles for this consolidation (v2.2):
- Director / orchestrator: MiniMax-M3 (minimax) — economy-tier coordinator; writes acceptance contracts, dispatches workers, holds gate decisions. Frontier tier not required for a doc/schema/consolidation pass.
- Worker (executor): MiniMax-M3 (minimax) — bounded schema/prompt/adapter authoring in parallel batches.
- Watcher / validator: Grok 4.5 (xai-oauth) — cross-family review of every phase report + diff.

Files/areas likely touched: `schema/`, `scripts/` (bm, lib/prompts.sh, enforce-models, acn-report, tier-aliases.json), `adapters/`, `references/`, `tests/`, `SKILL.md`, `README.md`, `.planning/`.

Verification commands:
- `bash tests/test-bm-model-check.sh`
- `bash tests/test-bm-thinking.sh`
- `bash tests/test-acn-parity.sh`
- `bash -n scripts/bm scripts/enforce-models scripts/acn-report scripts/lib/prompts.sh`
- `python3 -m json.tool` on every `schema/*.json` and `scripts/tier-aliases.json`
- `bm --harness bogus` exits 2

Manual QA: read adapter docs for vocabulary drift (low/medium/high, MODEL DRIFT, no watcher no validated); confirm SKILL.md version = 2.2.0.

Escalation triggers: changes to `scripts/bm` behavior beyond the new flag; anything touching `pi/`; deleting files.

Self-improvement log path: `.learnings/BEASTMODE.md`
