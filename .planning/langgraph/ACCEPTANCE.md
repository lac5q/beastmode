# Acceptance Contract — Beastmode on LangGraph (v2.4.0)

This contract covers **P0–P7S** of `ROADMAP.md`. P8 (the `forever` graph) and
P9 (CrewAI) get their own contracts when they're unblocked. P7S is the
capability-preserving security-release gate added from sealed Standard scan
`4846cd52-de67-4f97-b6a2-c84933241ac9`.

Written per `SKILL.md` §Step 1. `OPEN-QUESTIONS.md` Q1–Q6, Q8, and Q10 are
answered and folded in below. Q7 (PyPI publication) and Q9 (the future forever
graph's budget ceiling) remain outside this P0–P7S contract.

---

**Goal:** beastmode ships a `pip`-installable Python distribution that gives
LangGraph users the beastmode loop as ready-to-use `StateGraph`s — tier routing,
acceptance contracts, provenance/drift gates, ACN parallel fan-out, autonomy
gating, per-phase usage reporting, self-improvement checkpoint — with a
framework-neutral `beastmode.core` that a CrewAI binding can later reuse.

**Non-goals:** CrewAI implementation. The `forever` graph. Hosted deployment or
LangGraph Platform. Rewriting `scripts/bm` in Python. Replacing or modifying the
hermes / pi / claude / codex adapters. Any change to the meaning of
`schema/*.json`. Self-modifying graph topology. Pushing to origin without an
explicit ship-it.

**User-visible acceptance** (in priority order — the first decides ties):

- **A beastmode user who never installs the package sees no change at all.**
  Every existing `bm` invocation behaves identically to `main`, and
  `./tests/run-all.sh` passes with no Python packages present.
- `bm "<goal>" --harness langgraph --frontier <alias> --economy <alias>
  --watcher <alias> --autonomy low|medium|high` preflights seats and runs with
  the same phase-report / gate / drift prompts as every other harness — and
  exits 2 with an install hint, never a traceback, when the package is absent.
- A LangGraph user runs `pip install beastmode[langgraph]`, imports one builder,
  compiles a graph, and gets a beastmode run with gates that block below `high`
  autonomy — without reading `SKILL.md`.
- A run killed mid-phase resumes from its checkpoint on the same `thread_id`
  and completes.
- `graph.get_graph().draw_mermaid()` renders the loop as a living flowchart,
  committed to `references/langgraph-pipeline.md`.

**Invariants that must hold (each negative-tested by deliberately breaking it):**

0. **LangGraph is strictly additive.** `./tests/run-all.sh` passes with zero
   Python packages installed; no bash script, test, schema, doc, or adapter
   acquires a hard Python dependency; every pre-existing `bm` invocation behaves
   identically to `main`. This is checked on every phase, and it outranks every
   other item on this list.
1. `schema/*.json` remains the single source of truth — no field list exists in
   two places. Python types are read from the JSON at import.
2. `scripts/lib/acn_meta.py` remains the only implementation of the
   `ok` / `drift` / `unverifiable` verdict. The graph calls it.
3. `unverifiable` fails. LangGraph retry, error handling, and aggregation
   cannot convert it into a pass or a silent skip.
4. A passing child never carries a failing sibling. A child that wrote no meta
   at all is caught via `--expect`.
5. The main working tree is unmodified for the duration of any run. Per Q2,
   judgment seats (director / watcher / validator) may call chat models
   directly, but **every seat that writes files is a subprocess** in its own
   worktree, and never commits, pushes, or reads secrets.
6. Gates block below `high` autonomy; `MODEL DRIFT` surfaces at every level.
7. `beastmode.core` imports no agent framework — proven in CI, not by review.
8. Untrusted repository and worker capability stays inside the sandbox. The
   parent never executes repository hooks, trusts worker status as validation,
   or uses raw worker narratives as trusted reviewer instructions.
9. Resource controls bound worker memory, PIDs, CPU, disk, files, output, and
   aggregate concurrency without globally disabling worker commands or
   explicitly granted network access.
10. Public-release checks scan complete Git history **and** the exact generated
    wheel/sdist. A changed working tree invalidates the scan.
11. No critical/high security finding may remain open at release. Sensitive-data
    publication controls are merge-blocking at every severity.

**Files/areas likely touched:** `python/` (new), `scripts/bm`,
`scripts/enforce-models`, `scripts/lib/acn_meta.py` (possible relocation — Q10),
`adapters/langgraph/` (new), `references/`, `tests/test-acn-parity.sh`,
`.github/workflows/tests.yml`, `SKILL.md`, `README.md`, `.planning/`.

**Verification commands:**

```bash
./tests/run-all.sh                    # must pass with NO Python packages installed
pytest python/tests                   # new lane, package installed
lint-imports                          # beastmode.core has zero framework imports
bash tests/test-acn-parity.sh         # extended: Python ChildMeta == schema fields
bash tests/test-bm-model-check.sh     # regression: --harness bogus still exits 2
bash -n scripts/bm scripts/enforce-models scripts/acn-report scripts/lib/prompts.sh
python3 -m json.tool schema/*.json scripts/tier-aliases.json
python -m build python/              # wheel builds; imports with no provider SDKs
./scripts/public-artifact-guard --history  # exact clean release commit
# unpack + scan exact python/dist wheel/sdist with the P7S artifact guard
git status --porcelain               # empty after the full suite (CI already asserts this)
```

**P7S capability-preserving security acceptance:**

- A malicious target `post-checkout` hook cannot run during parent worktree
  creation, while worker Git and declared build tools still run inside policy.
- A symlinked run root or packaging resource fails before any external read,
  write, removal, or artifact inclusion.
- Worker-forged status, a reduced expected-child manifest, or adversarial logs
  cannot produce `validated`, reviewer approval, or a merge-ready state.
- Pi and Claude adapters retain their intended workflows while semantic policy
  bypasses and argv option injection fail closed.
- Kernel-enforced resource fixtures terminate abusive workers without killing
  the parent or disabling ordinary concurrent tasks.
- Binary-history, encoded-path, generated-only, and expanded-token fixtures all
  block public release without printing secret values.
- Installer and package dependencies are immutable and integrity-verified
  before execution.
- A fresh final Standard scan runs against the exact clean commit after all
  remediation, returns no open critical/high findings, and has no changed-tree
  warning.

**Manual QA:**

- Read `adapters/langgraph/SKILL.md` against the other four adapters for
  vocabulary drift (`low`/`medium`/`high`, `MODEL DRIFT`, "no watcher no
  validated", "gates are blocking below high").
- Confirm `SKILL.md` frontmatter version is `2.4.0` and every adapter's
  canonical cross-reference agrees.
- Run one real goal end-to-end at `--autonomy medium`; confirm it stops at each
  gate and that the phase report shows requested vs actual model per child.
- Confirm the mermaid render matches the actual node/edge set.

**Escalation triggers:**

- P0.1 finds that `actual_model` is unprovable for a frontier provider we intend
  to run as a direct-call judgment seat → demote that provider to a subprocess
  seat; if no frontier provider proves its model, stop and re-decide Q2 before
  P2 designs around it.
- Any proposal to add a hard Python dependency to the bash lane, or to make an
  existing `bm` flag behave differently — invariant 0 is merge-blocking.
- Any change to `scripts/lib/acn_meta.py`'s verdict logic — that file is the
  gate; edits to it are frontier-review-mandatory, not economy work.
- Any proposal to add a `best-effort` or `warn-only` provenance mode.
- Adding a dependency to the bash lane, or making `tests/run-all.sh` require an
  install.
- Anything that would make `schema/*.json` decorative again.
- Deleting files; touching `pi/`; pushing to origin.

**Watcher requirement:** cross-family adversarial review is **mandatory on P2
and P4** and blocking for merge. `.learnings/BEASTMODE.md` records the reason: the
last fail-open in this exact gate survived 19 passing checks and green CI, and
was caught only by a cross-family reviewer. No watcher, no `validated`.

**Self-improvement log path:** `.learnings/BEASTMODE.md`
