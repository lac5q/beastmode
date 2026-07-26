# Beastmode learnings — feat/acn-unification (v2.2.0 consolidation)

## BM-20260726-1200 feat/acn-unification consolidation
- Director: MiniMax-M3 (minimax) — economy-tier coordinator for a doc/schema/consolidation pass.
- Worker (executor): MiniMax-M3 (minimax) — bounded schema/prompt/adapter authoring in parallel batches.
- Watcher / validator: Grok 4.5 (xai-oauth) — cross-family review of phase reports + diffs.
- Harness: hermes ACN (parallel `delegate_task` batches; live transcripts in `~/.hermes/cache/delegation/live/`).
- Acceptance checks run:
  - `tests/test-bm-model-check.sh` — 6/6 PASS (existing preflight behaviour, adapted to `enforce-models` error wording).
  - `tests/test-bm-thinking.sh` — PASS (sanity print, no exit).
  - `tests/test-acn-parity.sh` — 12/12 PASS (schema validity, prompts lib parity, preflight+postflight drift, adapter vocabulary, `bm --harness` flag).
  - `bash -n` on `scripts/bm`, `scripts/enforce-models`, `scripts/acn-report`, `scripts/lib/prompts.sh`, `tests/test-acn-parity.sh` — all clean.
  - Grok validator prompt (cross-family review of staged diff + acceptance contract + roadmap) returned `VALIDATION: PASS`.
- Result: PASS. Staged on `feat/acn-unification`, no commit/push performed (director/worker contract: never commit/push).

## What worked
- **One vocabulary, defined once**: moving families/tiers/seats/autonomy into `schema/*.json` and then making the markdown docs reference that schema (instead of duplicating tables) closed three drift vectors at once. The `test-acn-parity.sh` check on tier-alias `family` membership is now the single source for "alias exists" — adding a row requires adding the family.
- **Shared prompt library (`scripts/lib/prompts.sh`)**: extracting the PHASE/MODEL_FAILURE/GATE strings from `scripts/bm` into a source-able lib let us reuse the exact same wording for `--harness hermes`, `--harness claude`, and `--harness codex` without forking. The parity test asserts substring matches so adapters can't silently drift.
- **`scripts/enforce-models` with `--harness`**: preflight was pi-only; extending it to hermes (provider presence check in `config.yaml`/`auth.json` — never print file contents), claude (CLI + namespace check), and codex (CLI presence) made the same "exit 2 with alternatives" UX work everywhere. `BM_SKIP_MODEL_CHECK=1` still bypasses.
- **`scripts/acn-report` (python3 stdlib)**: a 117-line helper that turns a directory of `meta.json` files into the universal "Models: requested X → actual Y / Drift: none | MODEL DRIFT" block — exit 1 on any drift. No jq, no extra deps.
- **Grok as cross-family validator**: even when director + workers share the MiniMax family, a separate xai reviewer caught vocabulary slips the workers let through (parity test check (f) failed on capitalisation first; patched the test, kept the wording, called it out).

## What failed / drifted
- **`BM_SKIP_MODEL_CHECK` mention lost in the refactor.** The original `bm` preflight printed "set BM_SKIP_MODEL_CHECK=1 to bypass" in its own missing-model output. After moving preflight into `enforce-models`, that hint only lived in the new tool's `--help` text, not in the missing-model output. Test 2 caught it. Fixed by adding the bypass hint to all three harness error branches in `enforce-models`. *Routing rule change?* No — the rule is "always tell the user how to bypass". The fix is in the message text, not the rule.
- **Adapter vocabulary inconsistency.** Adapters used capitalised "Gates are blocking below high" while the parity test grepped lowercase. Rather than rewrite every adapter heading, made the test `grep -qi` (case-insensitive). *Drift to record:* the canonical phrase in `references/autonomy-levels.md` uses capital G; tests are case-insensitive on the phrase. Either commit to a single casing in prose or accept case-insensitive matchers.
- **Phase 3 worker (W3, codex+claude adapters) never wrote a `.status` file** but its files all landed correctly. `wait`-then-check-by-file is brittle when background subagents finish mid-sleep; relying on `meta.json` arrival + filesystem presence is more reliable than on a sidecar status file. *Action:* the parity test already covers the result, so this is a logging gap, not a correctness gap. Will fix in a follow-up.

## Routing rule to change
- **None.** Verification-cost routing (cheap-first cascade, watcher must be cross-family when budget allows, gates blocking below `high`) all held up under the consolidation.
- **Add:** "directors MAY be economy-tier only when the work itself is bounded by an acceptance contract that contains no judgment calls." — recorded here because the v2.2 contract explicitly used MiniMax-M3 as director for a doc/schema/adapter/test pass; that's fine **because** the contract broke work into bounded slices each cheap-routable.

## Skill/config updates needed
- `references/autonomy-levels.md` should reference `schema/autonomy-levels.json` more visibly (already added the callout — keep).
- `references/tier-aliases.md` should add `family` as a required column for any new alias row (already done).
- The follow-up `~/.local/bin/bm` symlink should point at the worktree on merge (or the main checkout after merge) so the v2.2.0 binary is what runs by default. NOT promoted — handled after explicit ship-it.

## Promoted to
- None this run. Skills (`beastmode`, `beastmode-install`) still need their v2.2 version bump + adapter cross-refs as a separate maintenance pass.