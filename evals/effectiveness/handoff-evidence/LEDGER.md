# Effectiveness study ledger

## 2026-09-11 — protocol and construction
- Goal: run controlled effectiveness evaluations and write an evidence-grounded paper.
- Skill: /tmp/codex/skills/beastmode/SKILL.md; Codex adapter loaded.
- Director/reviewer: current Codex session. Economy: explicitly pinned gpt-5.6-luna/max.
- Worktree: /tmp/beastmode-evals, branch research/effectiveness-evals-20260911.
- Inventory: no prior controlled evaluation artifacts found in main checkout or its ignored paths.
- GitNexus: current source revision matches indexed lastCommit 346bbb4; new evals target returned UNKNOWN/absent, then text inventory confirmed new namespace. Production symbols unchanged.
- Worker eval_preflight: requested gpt-5.6-luna/max; parent-observed runtime turn_context model gpt-5.6-luna, effort max; rollout 01a0916b-e3e5-7991-b813-cf26720b1b34. Read-only inventory complete.
- CLI smoke: CODEX_LUNA_OK; requested and runtime model gpt-5.6-luna/max, rollout 01a0916d-86c8-7b63-b75b-7d9de16247a9; exit 0. Usage input 19942, cached input 9984, output 28, reasoning output 17. Dollar cost unavailable.
- Fixtures worker: isolated research/eval-fixtures-20260911; 12 public specifications plus held-out cases/reference/mutants; must not reveal hidden artifacts to director.
- Harness worker: isolated research/eval-harness-20260911; freeze/invoke/isolated score/analyze and meaningful tests.
- Protocol: evals/effectiveness/PROTOCOL.md, pending pre-trial review and freeze.
- Phase status: construction in progress; no scored trials or effectiveness findings yet.
- Timing estimate and per-worker token totals: unavailable. No model drift detected in the two completed preflights; other worker provenance pending.
- Merge/push: none.
- Operational amendment A reviewed by pinned Luna worker: PASS with environment/scope caveats addressed. 24 paired blocks,72 final artifacts,96 economy calls, serial frozen schedule, fixed failure denominators and paired bootstrap; related-family sensitivity added.
- Public-only director plans task01..task08 drafted. No hidden cases/reference read by director. All plans must be rechecked against finalized public specs before freeze.
- Unscored code-output smoke: CODE_PIPELINE_OK in bubblewrap. Raw .beastmode/code-smoke.jsonl; thread01a09180-cd93-7da1-8be2-f893b072a32c; input19749,cached9984,output45,reasoning32. No model tools. Runtime receipt still to be checked.
- MemroOS protocol saved/read back (commit9d9fd326); working paper methods draft saved/read back (commitd8589b6c). No effectiveness result is claimed.

## Continuation — integrated pre-trial validation
- Integrated12 fixtures: parent independently ran validate.py, exit0/oktrue;41 public examples,285 held-out cases,24 mutants. Both batches independently audited by workers who did not author them; PASS.
- Mutant schema mismatch fixed by wrapping source strings in named objects without changing source hashes. Reusable lesson recorded in evals/effectiveness/SKILL.md.
- Harness initial11 tests and driver3 tests passed in director runs; native JSONL parser smoke parsed real output, no tools. Initial model lookup implementation found unsafe for provenance despite successful smoke; correction is pending.
- Independent harness audit found explicit-candidate provenance bypass, score-order-dependent taint, missing Beastmode-minus-self-revision contrast, and missing CLI generation gates. Director additionally found cross-session model attestation risk. Targeted fixes active in beastmode-eval-fixes.
- Graph impact: score_candidate LOW (CLI caller); _runtime_model_evidence LOW (invoke_call -> CLI). Index process enumeration warned truncation; not a clean global completeness claim.
- No scored trials yet. Do not treat initial green tests as final harness acceptance; pending corrections require rerun.
