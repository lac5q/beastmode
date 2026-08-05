# Beastmode roadmap index

| Effort | Status | Docs |
|---|---|---|
| ACN Unification (v2.2.0) | **shipped** — see below; hardened in v2.3.0 | this file, `ACCEPTANCE.md` |
| Beastmode on LangGraph (v2.4.0) | **implemented locally; P7S security hardening blocks public release** — P0.1 matrix recorded with the safe subprocess fallback; P0.2/P0.3 and P1–P7 are green; the 2026-08-04 Standard scan is sealed and mapped into P7S | `langgraph/ROADMAP.md`, `langgraph/REQUIREMENTS.md`, `langgraph/ACCEPTANCE.md`, `langgraph/OPEN-QUESTIONS.md` |
| Run visibility (`acn-trace`) | **planned** — independent of LangGraph, works on every harness today | `observability/ROADMAP.md` |
| CrewAI binding | **deferred** — gated on the LangGraph effort's evolver phase | `langgraph/ROADMAP.md` §P9 |

---

# ROADMAP — Beastmode ACN Unification (v2.2.0)

Branch: `feat/acn-unification` (worktree `../.bm-worktrees/acn`). Merges to `main` locally; no push to origin without explicit ship-it.

## Goal

Unify beastmode under one set of **scales** (autonomy levels) and **families** (model families/tiers/seats), and make the **ACN layer** (async parallel sub-agents) work the same across Hermes, Claude Code, Codex, and Pi — with identical enforcement of autonomy gates and requested models.

## Role Routing

- **Director / orchestrator:** MiniMax-M3 (provider `minimax`) — economy seat used here as the planning/coordination tier for this consolidation run. Issues acceptance contracts, dispatches bounded workers, holds gate decisions. (For production beastmode runs, a frontier director — kimi-k3 / fable / opus / terra — owns this role; the design framework treats director/validator as the decision layer regardless of which model fills it.)
- **Worker (executor):** MiniMax-M3 — bounded file authoring, mechanical validation. (Same model as director in this run because the consolidation work is itself economy-tier: schema authoring, prompt extraction, adapter docs, parity tests. No judgment review needed from a second family for this scope.)
- **Watcher / validator:** Grok 4.5 (`xai-oauth`) — cross-family review of phase reports + diffs, MODEL DRIFT judgment, merge gate.

## Phases

| Phase | Scope | Exit (deterministic) |
|---|---|---|
| 001 | `schema/` SoT (families, tiers, seats, autonomy-levels, acn-contract JSON) + `scripts/tier-aliases.json` gains `family` | `python3 -c` loads every schema JSON; every alias has `family` + `tier`; alias family exists in families.json |
| 002 | `scripts/lib/prompts.sh` extracted from `bm`; `scripts/enforce-models`; `scripts/acn-report`; `bm` sources lib + calls enforce-models + `--harness` flag | `tests/test-bm-model-check.sh` still passes; `bash -n` on all scripts; `bm --harness bogus` exits 2; enforce-models rejects missing model with exit 2 |
| 003 | `adapters/hermes/SKILL.md` + `references/acn-contract.md` | File exists; names delegate_task background/batch, delegation.model pin, meta.json shape, drift fail-closed |
| 004 | `adapters/claude-code/SKILL.md` + `adapters/codex/SKILL.md` | Files exist; same autonomy/gate/drift vocabulary as hermes adapter; codex absorbs beastmode-cloud lane table |
| 005 | Docs sync: `SKILL.md` v2.2.0 (harness table, adapters, ACN section), `README.md`, `references/autonomy-levels.md` + `tier-aliases.md` point at schema | version frontmatter 2.2.0; grep finds `--harness` in README + SKILL |
| 006 | Tests: `tests/test-acn-parity.sh` (prompt parity + schema validity + harness list), full suite green | `bash tests/test-acn-parity.sh` exit 0; all tests pass |

Explicitly out of scope: standing-autonomy merge (separate), ACP editor mode, Ultraswarm changes, edits to knowledge/memroos/devops repos (notes only).

## Success criteria

- One vocabulary: autonomy scale + families/tiers/seats defined once in `schema/`, docs reference it.
- `bm` enforces requested models on every supported harness (preflight fail-closed).
- ACN contract identical across adapters: background/parallel fan-out, meta.json per child, MODEL DRIFT always surfaces and blocks validated, gates block below high.
- All tests pass on the branch.
