# Effectiveness evaluation — pending

Status: **PENDING — paused for handoff at user request (2026-09-11)**. The evaluation and paper are unfinished. Do not resume generation merely because this roadmap exists.

## Verified checkpoint

Run: `evals/effectiveness/runs/20260911-main`.
85/96 terminal stages: 84 completed, 1 interrupted failed. 21/24 director reviews. Zero scores.
Next action when explicitly resumed: review task01 repetition 1 Beastmode initial, then write `reviews/task01_rep1.md`.
Read only `fixtures/task01/public.md`, `plans/task01.md`, and `runs/20260911-main/invocations/task01_rep1_beast_initial/final_output.txt` under `evals/effectiveness/`.
The previous driver session 74706 exited normally at this barrier; no suspended process needs SIGCONT. The old pause receipt has empty PID arrays.

Remaining calls: task01 rep1 beast_revision, single, self_revision; then task06 rep2 single, self_revision, beast_initial, beast_revision; then task10 rep2 in the same four-stage order. Three reviews remain, including task01.

## Frozen study and harness transfer

Read `evals/effectiveness/PROTOCOL.md` including Amendment A and `README.md` before execution.
Manifest SHA256: `a70093e22325429d31029f812a428bc467658d479087c758dd97d3de56b50972`.
84 frozen inputs, 12 tasks, 2 repetitions, 72 final artifacts, 96 economy calls. Never rerun prepare or modify frozen code, fixtures, plans, templates, environment or protocol.

Director was gpt-6-astra/low; economy calls gpt-5.6-luna/max, serial, 600-second timeout. A different agent harness may coordinate the handoff, but must preserve the frozen model identities and execution/provenance contract. If it cannot, leave this run pending and propose a separately versioned study; do not silently substitute a model or rewrite the manifest.
Manifest and invocation records contain absolute paths to `/tmp/beastmode-evals` and native session evidence. Keep that worktree available. For another machine, restore required paths and provenance files, verify frozen hashes, and document any portability gap before running. Git alone does not include external native session logs or the ignored report virtualenv.

Before any new call, verify no existing driver/child is live and inspect invocation metadata only. Do not print complete records' requested command/prompt fields.
After review:
```bash
cd /tmp/beastmode-evals
python -u evals/effectiveness/driver.py advance --run evals/effectiveness/runs/20260911-main
```
Driver exits at each missing director review. Write each review once, then advance. Do not run concurrent drivers, retry completed calls, or restart because observation timed out.

## Blinding and deviations

Until all 24 director reviews are recorded, do not inspect baseline candidates, private cases, references, mutants or scores. Inspect only the current Beastmode initial and public contract/plan. Always run required revisions, even with no defect; final artifact is always the revision, never best-of selection.

Task09 brace guard rejected legitimate JSON before launch. Identical frozen-template substitution recovery receipts are retained in the run; both task09 blocks are now terminal. No frozen source was edited.
Task09 rep2 beast_initial was interrupted (harness exit143), output unavailable, no eligible retry established. Its required revision inherits invalidity and remains unsolved in the fixed denominator. Do not fabricate timing, usage or output.
Task05 rep2 initial had a real malformed-op type-validation defect; director review requested a guard. Repair effectiveness has not been scored.
PAPER.md documents these deviations. No effectiveness result has been established.

## Remaining roadmap

- [x] Design protocol and controls; construct and independently audit fixtures.
- [x] Validate harness/driver (18 tests passed before freeze); freeze 84 inputs.
- [x] Preserve partial run and 21 director reviews.
- [ ] **Pending:** complete remaining 3 reviews and 11 calls without unblinding.
- [ ] Seal outputs; score 72 finals plus 24 Beastmode initials with guarded harness.
- [ ] Independently rescore retained artifacts; reconcile matrix, provenance and inherited invalidity.
- [ ] Analyze paired outcomes, task/family bootstrap intervals, regressions, usage and latency.
- [ ] Complete honest paper, tables, figures and PDF; report limitations and inconclusive/negative findings if warranted.
- [ ] Persist results and final paper to MemroOS with readback; verify final deliverables.

Use frozen score/analyze CLI documented in README. No scoring until all generation and reviews finish. Equal call counts do not mean equal compute; no unsupported savings or general effectiveness claims.

## Durable evidence

Study source, run artifacts, reviews and manuscript draft are committed under `evals/effectiveness/`. Supporting local receipts are copied to `evals/effectiveness/handoff-evidence/`; legacy RESUME is historical and superseded by this roadmap.
MemroOS:
- `content/research/beastmode-effectiveness-protocol-2026-09-11.md`
- `content/research/beastmode-effectiveness-paper-2026-09-11.md`
- `content/research/beastmode-effectiveness-progress-2026-09-11.md`

The user authorized documenting, committing and merging the checkpoint, not resuming the experiment or publishing results.
