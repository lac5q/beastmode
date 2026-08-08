# Phase 201 Plan 01: Implement Beastmode Goal Interview

**Objective:** Land the autonomy-scaled interview protocol in `lac5q/beastmode` per
`201-DESIGN.md`, using the beastmode pipeline itself (Fable architect → luna-max executor →
opus5-high validator → director merge).

## Tasks

1. **[Fable, done in design] Research + design package** — root cause identified
   (no interview step; `bm` prompt composition has no interview language); design written to
   `201-DESIGN.md`.
2. **[luna max] Implement in isolated worktree** — branch `feat/goal-interview` of
   `~/.claude/skills/beastmode`; execute every numbered change in `201-DESIGN.md`
   (schema, new reference, SKILL.md step insertion + renumber, prompts.sh, bm flag,
   acn-contract schema+doc, 5 adapter sections, parity tests). Run all verification
   commands; return a structured validation report + `meta.json`
   (requested_model/actual_model).
3. **[opus5 high] Judgment review** — read diff + validation report against the acceptance
   contract; verdict: approve / reject with itemized reasons. Read-only.
4. **[Fable, director] Merge gate** — fix or bounce rejects, merge `feat/goal-interview` →
   `main`, sync installed adapter copy `~/.claude/skills/beastmode-claude-code/SKILL.md`,
   push, record learnings.

## Acceptance contract

- Goal: beastmode runs interview up front and surface open questions at gates, scaled by autonomy.
- Non-goals: no gate-weakening, no acn_meta verdict changes, no renames, no python/ changes.
- Verification: `bash tests/run-all.sh` green; both schemas parse; SKILL.md at 2.5.0 with
  renumbered steps; interview prompts assert-tested; gate prompt still contains
  "STOP and return control".
- Escalation: unrelated test failures, strict-key meta validation, non-goal collisions →
  stop and report.

## Verification (director re-runs at merge)

```bash
cd ~/.claude/skills/beastmode && bash tests/run-all.sh
python3 -m json.tool schema/autonomy-levels.json >/dev/null && python3 -m json.tool schema/acn-contract.json >/dev/null
diff -q adapters/claude-code/SKILL.md ~/.claude/skills/beastmode-claude-code/SKILL.md
```
