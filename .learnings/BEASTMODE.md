# Beastmode learnings

## BM-20260807 non-interactive macOS preflight repair

- Director/Lead: current Codex session; requested model: `openai-codex/gpt-5.6-luna`; Harness: Pi via `bm`; watcher unavailable.
- Acceptance checks: native `pi --list-models`/`enforce-models` preflight; canonical policy digest; read-only `bm` smoke on `main-mac`; `bash tests/run-all.sh` locally.
- Result: PASS after repair. The runner now appends standard user/Homebrew executable locations only when absent, preserving caller `PATH` precedence. Local Beastmode is 12/12 green, and the macOS smoke returned the expected project facts with `BM_EXIT`.
- What failed / drifted: a non-login SSH shell could not find Homebrew `pi` or `node`; the macOS Pi `better-sqlite3` binary was built for Node ABI 147 while the host ran ABI 137. Rebuilding `better-sqlite3` in the host-local Pi package directory removed the warnings; the rerun was clean.
- Routing rule to change: none. Model and permission preflight remain fail-closed; path discovery must not reorder an explicitly supplied test or worker `PATH`.
- Skill/config update: made the Pi policy-install recipe BSD/macOS-portable and documented the non-interactive path invariant in `pi/SKILL.md`.
- Promoted to: `scripts/bm`, `scripts/install-beastmode-pi.sh`, and `pi/SKILL.md`; host-local policy and dependency repair remain uncommitted runtime state until the governed rollout is authorized.

## BM-20260807 Luna high-autonomy read surface

- Director/Lead: current Codex session; requested director/worker seat: `openai-codex/gpt-5.6-luna` at max thinking; Watcher: unavailable; Harness: Pi via `bm`.
- Acceptance checks: native Luna read-only smoke through the actual `bm` executable; `bash tests/test-shell-security.sh`; no writes, commits, pushes, or outbound mutations by the worker.
- Result: partial but repaired locally. The repository launcher and installed `~/.local/bin/bm` now keep read/search access and exclude `bash,edit,write` at high autonomy. The native Luna smoke returned the expected repository facts. A multi-file audit exceeded the bounded wall-clock and produced no verifiable report, so it is not treated as validated.
- What worked: `enforce-models --harness pi --model openai-codex/gpt-5.6-luna` passed; the actual installed runner returned `memroos-monorepo` and the `dev` script; all shell-security tests passed.
- What failed / drifted: the first fix only changed the Beastmode checkout while `PATH` resolved a stale copied runner at `~/.local/bin/bm`; that runner still used `--no-builtin-tools`, so headless Luna could not inspect source. The multi-file audit also lacked exposed worker metadata before timeout.
- Routing rule to change: no model-routing change. Add an installation invariant: the runner invoked by `PATH` must match the reviewed source/release bytes before a high-autonomy run is called verifiable.
- Skill/config update needed: yes — keep high autonomy read-capable but mutation-excluding, and add an installed-runner parity check to the installation/host preflight procedure.
- Promoted to: `scripts/bm`, `references/autonomy-levels.md`, `tests/test-shell-security.sh`, and the local installed runner; remote hosts still require an explicitly authorized rollout.

## BM-20260803 LangGraph runtime implementation — P1–P7 mechanical pass

- Director/Lead: current Codex session; Watcher/Reviewer: unavailable; Executor: current session; Harness: manual/GSD with local `.venv`.
- Acceptance checks: P1 framework-neutral core, P2 canonical provenance parity, P3 interrupt/replay graph, P4 `Send` lane fan-out, P5 SQLite resume, P6 foreign-graph/subgraph composition, P7 package/Studio/docs surfaces.
- Result: implementation mechanically green through the shipped pipeline surface; not a final `validated` release because the mandatory cross-family watcher was unavailable and P0.1/P0.3 provider evidence remains incomplete.
- What worked: `beastmode[langgraph]` installs LangGraph 1.2.10, LangChain Core 1.5.3, SQLite checkpointing 3.1.1, and the OpenAI-compatible adapter 1.4.1. The optional `studio` extra provides `langgraph dev`. The shell lane stays install-free.
- What failed / drifted: the first Studio config pointed at a four-argument builder; LangGraph CLI requires a 0–2 argument factory. A zero-argument `studio_pipeline()` entrypoint fixed the load failure. The isolated package build also needed local `wheel` because the sandbox could not reach package indexes.
- Routing rule to change: none. Keep direct-call judgment seats fail-closed until P0.1 proves a provider's resolved serving model; use subprocess executors otherwise. Keep same-lane grouping because P0.3's live token measurement is still unavailable.
- Skill/config update needed: no; promoted the runtime, adapter, parity, pipeline, template, and observability surfaces into the repository.
- Promoted to: `python/`, `scripts/langgraph-runner`, `langgraph.json`, `adapters/langgraph/SKILL.md`, `references/langgraph-pipeline.md`, `references/langgraph-templates.md`, and `references/observability.md`.

## BM-20260803 P0 LangGraph spikes

- Director/Lead: current Codex session; Watcher/Reviewer: unavailable; Executor: current session; Harness: manual/GSD.
- Acceptance checks: isolated LangGraph 1.2.10 replay spike; sanitized Minimax provenance probe; install-free bash lane not changed.
- Result: partial — P0.2 passed; P0.1 live provider matrix is blocked by missing provider access and Minimax HTTP 402; P0.3 lacks live usage metadata.
- What worked: the replay spike reproduced the duplicate-side-effect hazard and confirmed `interrupt()`-first ordering fixes it. The local `.venv` keeps LangGraph optional and leaves the bash lane dependency-free.
- What failed / drifted: provider provenance and cache-token measurement cannot be inferred from missing or failed calls; the matrix records those rows as unmeasured/unverifiable instead of promoting them to direct-call viable.
- Routing rule to change: none. Keep direct-call seats fail-closed and preserve lane grouping until live provider evidence exists.
- Skill/config update needed: no.
- Promoted to: `references/langgraph-provider-provenance.md`, `references/langgraph-interrupt-replay.md`, `references/langgraph-lane-grouping.md`.

## BM-20260803 roadmap completion — preflight probe failures

- Acceptance checks: `bash tests/run-all.sh` — 6/6 steps green; ACN parity 27 PASS / 0 FAIL / 0 SKIP.
- Result: PASS. The GSD roadmap surfaces were already present; completion required hardening the `pi` model-list preflight and its regression coverage.

## What failed / drifted

- A failed `pi --list-models` probe leaked exit 1 through `set -euo pipefail` while `enforce-models` was printing alternatives, violating the documented exit-2 preflight contract. The preflight now captures the probe once, treats a failed listing as no available models, and reaches the explicit exit 2.
- The parity test depended on the host's installed `pi`, which made it sensitive to sandbox/auth filesystem failures. It now uses temporary fake `pi` binaries and covers both a normal unavailable-model response and a failed listing probe.

## Routing rule to change

- None. The verifier-first route held; the change was a deterministic preflight/test hardening pass.

## BM-20260726-2300 architecture review (v2.3.0)

- Reviewer: claude-opus-5, single session, no fan-out (review scope, not an ACN run).
- Harness: claude-code, direct.
- Acceptance checks: `./tests/run-all.sh` — 6/6 steps green, ACN parity 19 PASS / 0 FAIL / 1 SKIP (pi not on host). Every new check negative-tested by deliberately breaking the invariant and confirming a FAIL.
- Result: PASS.

## What failed / drifted

- **The drift gate failed open in two ways, and both were reachable from the repo's own docs.** `enforce-models --check-meta` skipped any meta lacking `requested_model`/`actual_model` as "not a meta file we recognise", and `acn-report` rendered the same meta as `requested: unavailable → actual: unavailable`, i.e. equal, i.e. `Drift: none`. Meanwhile `references/autonomy-levels.md` and `pi/SKILL.md` both instructed workers to emit `{"id","model","stop_reason","usage"}` — the one shape neither tool could evaluate. A pi worker following the documented contract passed the gate while proving nothing. An empty run directory also exited 0.
  *Routing rule to change?* No. The rule ("no watcher, no validated"; "if the runtime cannot prove the child's model, the child is an unverified draft lane") was already correct and already written down — in `adapters/codex/SKILL.md`, which was the only surface that named the unverifiable case. The tooling just never implemented it. **The lesson is about where rules live:** a hard rule stated in prose in one adapter is not enforced anywhere. It has to be a verdict the gate can return.

- **One contract, two implementations.** `enforce-models --check-meta` and `acn-report` each walked the meta directory with different glob rules (`**/*.json` vs `*.json` + `**/meta.json`) and compared fields differently. Nothing asserted they agreed, so a child could pass one tool and fail the other. Collapsed onto `scripts/lib/acn_meta.py`; parity check (e3) now asserts identical exit codes across every fixture.

- **`schema/` was decorative.** Called "the machine source of truth" in four documents, but no code read it — `meta_json_required_fields`, `batch_required_fields`, and `task_required_fields` were declared and then ignored, while the tools hard-coded their own field expectations. The gate now reads the schema; check (e4) asserts the prose block in `references/acn-contract.md` and the schema list are the same set.

- **Tests rewrote their own fixtures.** `test-acn-parity.sh` regenerated `tests/fixtures/acn-meta/*` on every run, so the committed copies were decorative too and had already drifted from the schema (missing `stop_reason`, `files_changed`, `commands_run`, `verify`). Fixtures are now read, not written; CI asserts the suite leaves the tree clean.

- **No entrypoint, no CI.** Three test scripts, no way to run them together, nothing running them automatically. A repo whose thesis is "nothing is validated until a gate says so" had no gate on itself. Added `tests/run-all.sh` + `.github/workflows/tests.yml`.

- **`bm` defects found while tracing seat resolution:** `--models "$FRONTIER,$ECONOMY"` emitted a leading comma when `--economy` was passed without `--frontier`; the `--on` remote dispatch spliced the raw goal into `bm '$GOAL' ...`, so a goal containing an apostrophe ended the quote and the remainder ran as remote shell words; and `--harness claude` handed the resolved `provider/model` to `claude --model`, which wants a bare model id (`enforce-models` even warned about it on every correct invocation).

- **The first fix reintroduced the same bug one level up — caught by the repo's automated reviewer, not by me.** Candidate detection keyed on provenance fields (`requested_model`, `actual_model`, `stop_reason`, …), so a child that died *before* writing any of them was not recognised as a child at all: it vanished from the report entirely and a valid sibling carried the batch to exit 0. Reproduced — a directory holding one good meta plus `{"id":"lost","usage":{...}}` printed `Drift: none`, exit 0, with `lost` appearing nowhere. *The lesson:* recognition must key on "is this a child record" and never on "did this child prove something". The moment those two questions share a predicate, failing to prove something makes you invisible rather than failing. Detection and judgment have to be separate functions — they now are (`is_child_record` vs `Row._classify`).
- **Scanning can only judge what exists.** Even with detection fixed, a worker killed before writing any file leaves nothing to find, and one surviving sibling still passed the batch. Closed with `--expect`, which reads the batch's `tasks[].id` — a manifest `schema/acn-contract.json` already required, so nothing new had to be invented to make absence detectable.

## Routing rule to change

- **None.** Verification-cost routing held up.
- **Add, as a contract rule rather than a routing rule:** *a gate must have a verdict for "cannot determine", and that verdict must fail.* Every fail-open here was a two-valued gate (drift / no-drift) meeting a three-valued reality (drift / no-drift / unprovable), and "unprovable" fell into the pass bucket by default. Now `ok` / `drift` / `unverifiable`, with `--allow-empty` as the explicit assertion when a batch legitimately had no children.
- **Add:** *a gate over a set fails if any member fails; no member's pass may substitute for another's.* Both rounds of this bug had that shape — an unprovable child disappearing into a batch a valid sibling then carried. Aggregate verdicts hide precisely the members that failed hardest.
- **Add, on review routing:** the adversarial reviewer earned its seat here. A cross-family automated review caught a fail-open in the very change that existed to remove fail-opens, on a diff that had 19 passing checks and green CI. "Tests green" is not "reviewed", and self-review by the author of the fix is the weakest link in the chain.

## Skill/config updates needed

- The `opus5` alias in `scripts/tier-aliases.json` resolves to `claude-opus-4-8` and `sonnet` to `claude-sonnet-4-6`. Left alone — the file states it was verified against `pi --list-models` on a configured worker host, so the alias names are worth re-checking whenever that host's catalog changes.
- `bm`'s documented exit-code contract ("0 = goal_complete, 1 = goal_blocked") is not implemented — `bm` `exec`s the harness, so callers get the harness's exit code with no mapping. Either implement the mapping or drop the claim from the header.
- Autonomy → harness flag mapping is only symmetric at `high`. `low` maps to `--approve` on pi and to nothing on hermes/claude/codex, so "autonomy semantics are identical across harnesses by construction" currently holds for the prompt strings only, not the enforcement flags.
- `bm --watcher <alias>` resolves and preflights the watcher seat but never passes it to any harness — it reaches the run as prompt text only.

## Promoted to

- `schema/acn-contract.json` (v1.1): `unverifiable_policy`, `gate_verdicts`, `gate_implementation`, and a fifth hard rule.
- `scripts/lib/acn_meta.py`: the rule as executable code rather than prose.

---

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

## BM-20260807-2315 phase-201 goal-interview (v2.5.0)
- Director/Lead: anthropic/claude-fable-5 (Claude Code session, effort high)
- Watcher/Reviewer: anthropic/claude-opus-4-8 (claude -p --effort high)
- Executor: openai-codex/gpt-5.6-luna (codex exec, model_reasoning_effort=max)
- Harness: claude-code manual ACN (codex exec + claude -p children, git worktree isolation)
- Acceptance checks: tests/run-all.sh (12/12), python3 -m json.tool both schemas, parity greps, bash -n
- Result: pass (merged a7cb9c6)
- Token/cost note: luna 353,984 tokens; opus/fable usage unavailable from harness
- What worked: file-pointer child prompt started instantly (no long-inline hang); the new needs_decision protocol fired correctly on its very first run — executor hit the installer-hash non-goal boundary, recorded a clean decision item instead of improvising, and stopped
- What failed / drifted:
  1. Startup probe watched the child's stdout, which was piped through `tail` — fully buffered, so the probe reported HUNG while the child was fine. Valid liveness signals for codex children: the rollout artifact under ~/.codex/sessions/ growing, process CPU, worktree dirtiness. Never a piped stdout file.
  2. The "read-only" opus reviewer ran via claude -p with Bash allowed and reverted worktree state mid-review (reflog: reset moving to HEAD), erasing a director fix. Reviewers must get --permission-mode plan, or review a snapshot/second worktree — prompt-level "do not edit" is not an enforcement mechanism.
  3. The reviewer brief was written before a design amendment and never regenerated; it contradicted DESIGN.md (high-autonomy interview matrix). The reviewer correctly treated DESIGN.md as authoritative, but briefs must be regenerated after any design amendment.
  4. Goal launched from a memroos worktree initially wrote planning docs into memroos .planning; operator directive: beastmode work always lands in ~/github/beastmode regardless of session cwd (also note ~/.claude/skills/beastmode is a symlink to it).
- Routing rule to change: none (requested == actual on all children)
- Skill/config update needed: yes — promote lessons 1–2 into references/child-liveness.md and the claude-code adapter watcher section
- Promoted to: notes only (separate user-approved maintenance task per promotion rules)

## BM-20260809-1800 luna-max-throughput
- Director/Lead: Codex root session.
- Watcher/Reviewer: Claude Opus via `claude -p --permission-mode plan` (prior bounded review).
- Executor: `openai-codex/gpt-5.6-luna`, reasoning `max`.
- Harness: native `bin/beast-luna` provenance wrapper, three concurrent read-only smoke seats.
- Acceptance checks: three parallel `bin/beast-luna --smoke` invocations; each wrapper inspected the Codex session artifact and required `gpt-5.6-luna` + `max`.
- Result: pass for lane availability; no repository work was delegated by the smoke batch.
- What worked: concurrency 3 completed with independent attestation for all three sessions. The wrapper's session-level evidence is stronger than child self-identification.
- What failed / drifted: the earlier local ACN batch requested Luna but one child self-reported GPT-5/Codex and the siblings had no independent attestation; that batch was stopped and remains unvalidated.
- Routing rule to change: never increase fan-out above three merely to compensate for unverifiable provenance; re-run the same bounded slices through an attesting wrapper, then gate.
- Skill/config update needed: yes — Luna Max is now the explicit default economy seat; Claude subscription validation remains one watcher only.
- Promoted to: `SKILL.md`, `scripts/bm`, `scripts/langgraph-runner`, and harness docs in commit `c266696` (local; public push held by pre-existing history guard finding).

## BM-20260809 self-learning-loop-and-host-limits
- Director/Lead: current Codex session; Executor: current session; Harness: manual/Python LangGraph.
- Acceptance checks: focused executor/pipeline/learning tests; `python -m pytest --cov=src/beastmode`; `tests/run-all.sh`.
- Result: pass after repair. The repository now records redacted, replay-idempotent issue entries for successful and blocked LangGraph exits, tracks recurring items for promotion review, and marks same-goal issues addressed only after a clean run. Coverage is enforced at 80%; the current suite is 146 tests at 86.18%.
- What failed / drifted: the worktree executor applied `RLIMIT_NPROC=256` before Bubblewrap namespace setup while this host already had 876 tasks for the UID, producing `EAGAIN`; pytest fixtures also inherited umask `0002`, making security fixtures group-writable. The tests were environment-sensitive rather than exposing a sandbox bypass.
- What worked: dynamic host-task headroom preserves the configured worker budget and trusted launcher slots; the test process pins umask `0022`; blocked exits now flow through `self_improve`; learning writes are path-confined, bounded, redacted, append-only, and replay-idempotent.
- Routing rule to change: no model-routing change. Resource-limit failures must be diagnosed against host task counts before weakening Bubblewrap or removing the process ceiling.
- Skill/config update needed: yes — keep the learning-loop and coverage gates documented; recurring issue promotion remains a separate approved maintenance task.
- Promoted to: `python/src/beastmode/core/learning.py`, LangGraph pipeline/state/nodes, `references/langgraph-pipeline.md`, `SKILL.md`, `python/pyproject.toml`, and CI coverage configuration.

## BM-20260809-release-deploy
- Director/Lead: current session; Executor: current session after MiniMax, Qwen, and Droid smoke gates were unavailable; Harness: manual.
- Acceptance checks: `tests/run-all.sh` (12/12), `python/tests` (150 passed), import-linter, Studio smoke, package build/wheel smoke, public artifact guard on exact commits and complete history, GitNexus change detection, clean local checkout.
- Result: partial deployment. Commits `65296f2`, `00a387a`, and `bceb6bb` are pushed to `origin/main`; maeve-u1 is clean and at `bceb6bb`. main-mac deployment remains blocked by SSH/Tailscale authentication from this session.
- What worked: local `bm` resolves to the current checkout, the editable Python package is current, all Pi companion packages are installed, and generated build/test artifacts and local Codex capture refs were removed.
- What failed / drifted: direct MiniMax returned HTTP 402; Qwen and Droid smoke gates returned no exact response. User-global skill/marker copies on maeve-u1 remain stale because the project permission boundary denies external-directory writes; the canonical repository policy and runner remain current.
- Routing rule to change: no model-routing change. Host deployment needs a preflight that proves SSH/Tailscale authentication and user-global write authorization before claiming rollout.
- Skill/config update needed: no; this is host-specific handoff state.
- Promoted to: none.
