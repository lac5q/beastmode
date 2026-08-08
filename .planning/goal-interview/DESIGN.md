# Design Package: Beastmode Goal Interview (autonomy-scaled)

**Architect:** Claude Fable 5 (`anthropic/claude-fable-5`), effort high — this document is the
design-tier output. The executor implements it without judgment calls.
**Target repo:** `~/.claude/skills/beastmode` (github.com/lac5q/beastmode), branch `feat/goal-interview`.
**Version bump:** SKILL.md `2.4.0` → `2.5.0`.

## Problem

Beastmode never interviews the user. The loop goes raw goal → acceptance contract (SKILL.md
Step 1) with no gray-area identification and no clarifying questions. Gates below high
autonomy *block* ("STOP and return control for approval") but only ever *report* — they never
ask. GSD's `discuss-phase` has a full interview protocol; beastmode runs bypass it entirely.
Result: the operator sees zero questions up front and zero questions in-process, and goals run
on silent assumptions.

## Solution overview

Two mechanisms, both scaled by the existing autonomy level:

1. **Upfront Goal Interview** — a new loop step between Preflight and Acceptance Contract.
   Identifies gray areas GSD-style and asks them before any design work, with a question
   budget set by autonomy.
2. **In-process Open Questions at gates** — ambiguities discovered mid-phase accumulate as
   `needs_decision` items (workers record, never ask) and every blocking gate report at
   low/medium gains a mandatory `## Open Questions` section the user must answer or defer
   before the run continues.

The autonomy → interview matrix (machine source of truth goes in `schema/autonomy-levels.json`):

| Level | Upfront | In-process | Question budget |
|---|---|---|---|
| low | `full` — present every material gray area, deep-dive until resolved; no material ambiguity survives unasked | `gate-questions` — every gate presents accrued open questions; each answered or explicitly deferred | unbounded |
| medium (default) | `batched` — one batched round of the top 3–5 impact-ranked questions; every remaining ambiguity becomes an explicit contract Assumption | `gate-questions` (same as low) | 5 |
| high | `batched` — same single upfront round as medium (operator directive 2026-08-07: "high autonomy should interview at first but not afterwards"); remaining ambiguity becomes contract Assumptions | `escalation-only` — after the contract is written, never block on questions again; open questions fold into the final report's Assumptions section; only escalation triggers interrupt | 5 (upfront only) |

**Non-interactive downgrade rule:** any lane that cannot reach the user (headless `claude -p`,
`codex exec`, CI) automatically downgrades to `assumptions-only` and MUST log the downgrade in
the phase report ("interview downgraded: non-interactive lane").

**GSD interop rule:** if the repo runs GSD and a phase `CONTEXT.md` (or SPEC.md) exists for
this work, import its locked decisions instead of re-asking. Never re-ask a decided question.

## File-level changes (exhaustive — touch nothing else)

### 1. `schema/autonomy-levels.json`

Add to each level object an `interview` key, and nothing else:

```json
"low":    { "interview": { "upfront": "full",    "in_process": "gate-questions",  "question_budget": null }, ...existing keys... }
"medium": { "interview": { "upfront": "batched", "in_process": "gate-questions",  "question_budget": 5 }, ... }
"high":   { "interview": { "upfront": "batched", "in_process": "escalation-only", "question_budget": 5 }, ... }
```

Also add two top-level keys:
- `"interview_protocol": "references/goal-interview.md"`
- `"reporting": { "ledger": ".beastmode/LEDGER.md", "digest_cadence": "every phase gate and at least hourly", "final_worker_table": true }`

Keep valid JSON (verify with `python3 -m json.tool`).

### 2. New file `references/goal-interview.md`

Full protocol reference (~150–200 lines). Required sections, in order:

- **Why** — silent assumptions are the most expensive failure mode: a wrong assumption at
  design time multiplies executor waste downstream; asking costs one turn.
- **The interview matrix** — the table above, plus: schema is source of truth, prose loses.
- **Gray-area identification** (adapted from GSD discuss-phase):
  - Gray areas are decisions that could go multiple ways AND would change the user-visible
    result. Generate goal-specific areas, never generic labels (UI/UX/Behavior).
  - Ask about: intent, user-visible behavior, scope boundaries, essential-vs-nice-to-have,
    references the user has in mind, non-goals.
  - Never ask about: codebase patterns (director reads code), implementation approach,
    architecture tradeoffs the design tier owns, things derivable from the repo or prior
    decisions.
  - Skip-decided rule: before asking, check `GOAL_STATE.md`, `.planning/**/CONTEXT.md`,
    `.planning/**/SPEC.md`, prior gate answers in this run. Imported decisions are recorded
    as locked, annotated with their source.
  - Scope guardrail: interview clarifies HOW to do what's in the goal, never WHETHER to add
    new capabilities. New capabilities → "Deferred ideas" list, not questions.
- **Question format** — batched rounds; each question: specific label, 2–4 concrete options,
  one recommended default marked as such, one-line consequence per option. The user can
  always answer freeform.
- **Assumptions ledger** — contract section format:
  `- A<i>: <assumption> — impact if wrong: <one line> — status: unconfirmed | confirmed@gate<N>`
- **In-process open questions** —
  - `needs_decision` item shape: `{"id", "question", "options", "assumed", "impact_if_wrong"}`.
  - Workers NEVER interview the user (no user contact from executor tier). A worker that hits
    ambiguity: applies the contract's stated assumption if one covers it, records a
    `needs_decision` item in its meta.json, and continues; if genuinely blocked, stops with
    `stop_reason: "needs_decision"`.
  - The director accumulates items from worker metas + watcher review + its own review.
  - Gate integration: at low/medium every phase report includes `## Open Questions` (or
    `## Open Questions: none`); the gate is not passed until each item is answered or the
    user explicitly defers it. Deferrals convert to Assumptions. At high, items fold into
    the final report.
- **Harness mapping** — Claude Code: `AskUserQuestion` (≤4 questions per call, options with
  recommended-first); Hermes: one combined `clarify()` batch per round (never N parallel);
  Codex interactive: numbered-list plain text; Pi: question/ask tool; LangGraph:
  `interrupt()` at the gate node; any non-interactive lane: automatic downgrade to
  assumptions-only + logged downgrade.
- **GSD interop** — if `.planning/` exists with a matching phase CONTEXT.md, import; when a
  repo already uses GSD, `gsd-discuss-phase` MAY serve as the upfront interview and its
  CONTEXT.md is then the locked-decisions input to the acceptance contract.

### 3. `references/autonomy-levels.md`

- Add an **Interview** column to the main level table (values: full / batched /
  assumptions-only) or a compact "## Interview scaling" section with the matrix table —
  section preferred to keep the existing table narrow.
- Add to the per-phase usage report template one line: `Open questions: <n> (answered <a>, deferred <d>) | none`.
- Add a sentence under "Surfacing is blocking below high": gates also present accrued open
  questions; unanswered items block exactly like unapproved phases.
- Point to `references/goal-interview.md` and note schema precedence.

### 4. `SKILL.md` (canonical beastmode skill)

- Frontmatter: `version: 2.5.0`.
- **The Beastmode Loop**: insert new **"Step 1: Goal Interview (Autonomy-Scaled)"** after
  Step 0 Preflight; renumber existing Steps 1–6 to 2–7 (update any in-document references to
  step numbers). Step 1 content: one-paragraph summary of the matrix + skip-decided rule +
  scope guardrail + non-interactive downgrade + pointer to `references/goal-interview.md`.
  Keep it under ~35 lines; the reference file holds the full protocol.
- **Acceptance contract template** (now Step 2): add three lines:
  ```
  Locked decisions: <from interview + imported CONTEXT.md/SPEC.md, with sources>
  Assumptions (unconfirmed): <A1..An, each with impact-if-wrong>
  Open questions deferred to gates: <ids or none>
  ```
- **Validation report template** (Step 5): add line `- Needs decision: <items or none>`.
- **Hard Rules**: append rule 11:
  `11. **No silent assumptions.** Material ambiguity is either asked (per the autonomy interview matrix in schema/autonomy-levels.json) or recorded as an explicit Assumption in the acceptance contract and surfaced at the next gate. Workers never interview the user — they return needs_decision items in their meta/report and the director surfaces them at the gate.`
- **References section**: add a Goal interview bullet pointing at `references/goal-interview.md`.
- Mention `interview` in the schema list sentence ("One vocabulary" paragraph) — autonomy
  levels now include interview scaling.

### 5. `scripts/lib/prompts.sh`

- New function `bm_interview_prompt <full|batched|assumptions>` following the existing style
  (heredoc, case, error on bad arg, return 2). **Keyed by interview MODE, not autonomy** —
  `scripts/bm` maps autonomy → mode (low→full, medium→batched, high→batched). Upfront
  behavior only; in-process behavior lives in `bm_gate_prompt`/`bm_phase_prompt`:
  - **full:** "Before writing the acceptance contract, interview the user: identify every gray area in the goal — decisions that could go multiple ways and would change the user-visible result — and present them as specific questions with concrete options and a recommended default. Keep asking until no material gray area remains; do not start design with an unasked material question. Never re-ask anything already decided in GOAL_STATE.md, .planning CONTEXT/SPEC files, or earlier gate answers. Record every answer as a locked decision in the acceptance contract."
  - **batched:** "Before writing the acceptance contract, run one batched interview round: identify the gray areas in the goal, rank them by impact, and ask the top 3-5 as a single set of specific questions with concrete options and a recommended default. Never re-ask anything already decided in GOAL_STATE.md, .planning CONTEXT/SPEC files, or earlier gate answers. Record answers as locked decisions; convert every remaining ambiguity into an explicit Assumption in the acceptance contract with its impact-if-wrong."
  - **assumptions:** "Do not block on clarifying questions. Convert every ambiguity into an explicit Assumption in the acceptance contract with a stated impact-if-wrong and carry the Assumptions ledger into the final report."
  - All three variants end with: "If the lane cannot reach the user (headless or CI), downgrade to assumptions-only and log the downgrade in the phase report."
- Extend `bm_gate_prompt` low/medium heredoc with one sentence appended after the existing
  text: "Each phase report must include an '## Open Questions' section listing every needs_decision item accrued during the phase, or 'none'; the gate is not passed until each item is answered or explicitly deferred."
  Keep the existing first sentence byte-identical (the parity test greps "STOP and return control").
- Extend `bm_gate_prompt` high heredoc with: "Never block on questions after the upfront interview; fold accrued open questions into the final report's Assumptions section."
- Extend `bm_phase_prompt` heredoc (universal, all levels) with: "Workers never question the user: a worker that hits ambiguity applies the contract's stated assumption if one covers it and records a needs_decision item in its meta.json, or stops with stop_reason needs_decision when blocked." (plus the ledger/digest sentence from section 10).
- Update the file's header comment to mention the new functions.

### 6. `scripts/bm`

- New flag `--interview full|batched|assumptions|off` (and `--interview=` form), default
  empty → derived from autonomy (low→full, medium→batched, high→batched). Validate the
  value; error exit 2 on anything else, matching the `--autonomy` validation style.
- Derive `INTERVIEW_MODE` from autonomy (low→full, medium→batched, high→batched) unless
  `--interview` overrides it. Compose `bm_interview_prompt "$INTERVIEW_MODE"` into the run
  prompt wherever `bm_gate_prompt` is composed; if `--interview off`, skip injection
  entirely.
- Forward `--interview` on remote (`--on`) invocations exactly like `--autonomy` is
  forwarded (see `REMOTE_CMD` assembly).
- Update the usage header comment (lines near the top) with the new flag.

### 7. `schema/acn-contract.json`

- Add top-level key `"meta_json_optional_fields": ["needs_decision"]`.
- Add key `"needs_decision_shape": {"id": "string", "question": "string", "options": "array", "assumed": "string", "impact_if_wrong": "string"}`.
- Add to `hard_rules`: `"workers never interview the user: ambiguity becomes a needs_decision item surfaced at the gate"`.
- Do NOT add `needs_decision` to `meta_json_required_fields` — it is optional and absent
  metas must keep passing the gate. Verify `scripts/lib/acn_meta.py` tolerates the extra
  field on metas that include it (it validates required fields; confirm no strict-key
  rejection — if there is one, allow the key, changing nothing else about validation).

### 8. `references/acn-contract.md`

- Document the optional `needs_decision` meta field, its shape, the worker rule (record and
  continue under the contract's assumption, or stop with `stop_reason: "needs_decision"`),
  and gate integration. One short section, mirroring the schema.

### 9. Adapters — one short "Interview mapping" section each

- `adapters/claude-code/SKILL.md`: upfront rounds and gate open-questions use the
  `AskUserQuestion` tool (≤4 questions per call, recommended option first); headless
  `claude -p` lanes downgrade to assumptions-only and log it. Add an `interview` row to the
  autonomy mapping table if one fits naturally, otherwise a standalone short section.
- `adapters/hermes/SKILL.md`: one combined `clarify()` batch per interview round (never N
  parallel clarifies); gates surface open questions through the same batch mechanism.
- `adapters/codex/SKILL.md`: interactive sessions use numbered-list plain-text questions;
  `codex exec` lanes are non-interactive → assumptions-only + logged downgrade.
- `adapters/langgraph/SKILL.md`: the upfront interview is a checkpointed `interrupt()`
  before the design node; gate open-questions ride the existing `interrupt()` gates.
- `pi/SKILL.md`: add to the universal worker contract text: workers never interview the
  user; ambiguity → `needs_decision` in meta.json (shape per `schema/acn-contract.json`),
  or `stop_reason: "needs_decision"` when blocked.

### 10. Run ledger + progress digests (operator directive 2026-08-07)

Operator problem: "I'm not sure what happened / what was completed; token % per worker and
model gets lost; I want to scroll back every hour or so and check." Requirement: compact,
not overdone.

- **`references/observability.md`** — add a section "Run ledger and progress digests":
  - **Ledger:** append-only `.beastmode/LEDGER.md` in the target repo (create dir if
    missing). One line per event; events are: worker dispatched, worker completed, worker
    failed/hung, phase gate reached, merge. Line format:
    `| <UTC hh:mm> | phase <n> | <worker-id or gate> | <requested>-><actual model> | <tokens> tok (<pct of phase budget>) | <done|failed|hung|drift|gate> | <one-line what> |`
  - **Progress digest:** emitted to the user at every phase gate AND at least once per hour
    of wall-clock during long phases. Maximum 8 lines, no raw logs:
    ```
    BM progress <elapsed> — phase <n>/<N> <name>
    Workers: <d> done / <f> failed / <r> running
    Tokens: <total> (<pct> of budget) — per model: <model a>: <tok> (<pct>), <model b>: <tok> (<pct>)
    Completed since last digest: <one-liners>
    Failures/drift: <one-liners or none>
    ```
  - Digests are derived from the same worker meta.json data the drift gate reads
    (`scripts/acn-report` already normalizes per-child usage — reference it as the data
    source; do not build new tooling).
- **`scripts/lib/prompts.sh`** — append to `bm_phase_prompt` heredoc (existing text stays
  byte-identical, parity test greps it): "Append one line per worker completion, failure,
  and phase gate to .beastmode/LEDGER.md (create it if missing). Emit a compact progress
  digest (max 8 lines: elapsed, phase n/N, workers done/failed/running, tokens per model
  with percent of budget, one-liners of what completed, failures or drift) at every phase
  gate and at least once per hour during long phases."
- **`SKILL.md` Required Final Report** — add to the template, after the Token/cost line:
  ```
  Worker table:
  | worker | phase | model requested→actual | tokens (% of run) | status | produced |
  Failures/hangs/drift: <itemized one-liners or none>
  Ledger: .beastmode/LEDGER.md (<n> entries)
  ```
- **`references/autonomy-levels.md`** — in the per-phase usage report format block, add one
  line: `Workers: <id>: <model> <tokens> (<pct of phase>) <status>; ...` and note the
  ledger + hourly digest requirement applies at every autonomy level (reporting is not
  autonomy-scaled).

### 11. `tests/test-acn-parity.sh`

Add asserts in the existing style (source prompts.sh, grep substrings):
- `bm_phase_prompt` → contains "LEDGER.md" and "progress digest".
- `bm_interview_prompt full` → contains "interview the user" and "no material gray area".
- `bm_interview_prompt batched` → contains "one batched interview round" and "top 3-5".
- `bm_interview_prompt assumptions` → contains "Do not block on clarifying questions".
- `bm_interview_prompt bogus` → exits non-zero.
- `bm_gate_prompt medium` → still contains "STOP and return control" AND now "Open Questions".
- `bm "$goal" --interview bogus` style validation if a cheap test exists for flags
  (mirror how `--autonomy` validation is tested if it is; otherwise skip flag test).

## Non-goals (do not touch)

- No changes to `acn_meta.py` gate verdict logic, drift detection, or provenance rules
  (only confirm optional-field tolerance).
- No changes to permission/sandbox/autonomy *gating* semantics — interview adds a step and
  extends reports; it never weakens a gate.
- No renames of existing functions, files, or schema keys.
- No changes under `python/`, `langgraph.json`, installers, or unrelated references.
- Do not sync the installed copy `~/.claude/skills/beastmode-claude-code/` — the director
  does that at merge.

## Verification commands (executor must run all, report pass/fail each)

```bash
cd <worktree>
python3 -m json.tool schema/autonomy-levels.json > /dev/null
python3 -m json.tool schema/acn-contract.json > /dev/null
bash tests/run-all.sh
grep -n "Step 7" SKILL.md   # renumbering landed
grep -n "version: 2.5.0" SKILL.md
grep -c "Open Questions" scripts/lib/prompts.sh   # >= 1
bash -c '. scripts/lib/prompts.sh; bm_interview_prompt full; bm_interview_prompt batched; bm_interview_prompt assumptions' > /dev/null
bash -c '. scripts/lib/prompts.sh; bm_interview_prompt bogus' && echo FAIL || echo OK
```

## Escalation triggers

Stop and report (do not improvise) if: `tests/run-all.sh` fails for reasons unrelated to your
change; `acn_meta.py` rejects unknown meta fields; step renumbering collides with external
references you cannot see; any change would touch a non-goal area.
