#!/usr/bin/env bash
# prompts.sh — shared prompt library for beastmode.
#
# Sourceable from scripts/bm and tests. No side effects on source: no
# set -e, no global state mutations, only functions defined then a no-op
# guard so callers can `source` this file safely.
#
# Strings mirror the PHASE_PROMPT / MODEL_FAILURE_PROMPT / GATE_PROMPT /
# INTERVIEW_PROMPT values used by scripts/bm. The bm_phase_prompt,
# bm_model_failure_prompt, bm_gate_prompt, and bm_interview_prompt functions
# values that used to live inline in scripts/bm. Keep them verbatim: the
# parity test in tests/test-acn-parity.sh asserts exact substrings, and
# downstream prompts (adapter SKILL.md, watcher validators) inherit the
# same wording.

# bm_phase_prompt — phase reporting contract.
# Verbatim from scripts/bm PHASE_PROMPT (no GSD variant).
bm_phase_prompt() {
  cat <<'EOF'
At the end of every phase, report phase name/status; requested model versus the model that actually served each task (from worker meta.json or the harness journal); tokens used / phase budget and percent; actual versus estimated time. Use the workflow journal or budget output. Say unavailable when a harness does not expose a value. If any task was served by a model other than the requested provider/model (router fallback, harness default, silent substitution), flag it as MODEL DRIFT in the phase report immediately with requested and actual IDs — never fold drift into a footnote.
Workers never question the user: a worker that hits ambiguity applies the contract's stated assumption if one covers it and records a needs_decision item in its meta.json, or stops with stop_reason needs_decision when blocked.
Append one line per worker completion, failure, and phase gate to .beastmode/LEDGER.md (create it if missing). Emit a compact progress digest (max 8 lines: elapsed, phase n/N, workers done/failed/running, tokens per model with percent of budget, one-liners of what completed, failures or drift) at every phase gate and at least once per hour during long phases.
EOF
}

# bm_interview_prompt <full|batched|assumptions>
# Upfront goal interview behavior keyed by interview mode, not autonomy.
bm_interview_prompt() {
  case "${1:-}" in
    full)
      cat <<'EOF'
Before writing the acceptance contract, interview the user: identify every gray area in the goal — decisions that could go multiple ways and would change the user-visible result — and present them as specific questions with concrete options and a recommended default. Keep asking until no material gray area remains; do not start design with an unasked material question. Never re-ask anything already decided in GOAL_STATE.md, .planning CONTEXT/SPEC files, or earlier gate answers. Record every answer as a locked decision in the acceptance contract. If the lane cannot reach the user (headless or CI), downgrade to assumptions-only and log the downgrade in the phase report.
EOF
      ;;
    batched)
      cat <<'EOF'
Before writing the acceptance contract, run one batched interview round: identify the gray areas in the goal, rank them by impact, and ask the top 3-5 as a single set of specific questions with concrete options and a recommended default. Never re-ask anything already decided in GOAL_STATE.md, .planning CONTEXT/SPEC files, or earlier gate answers. Record answers as locked decisions; convert every remaining ambiguity into an explicit Assumption in the acceptance contract with its impact-if-wrong. If the lane cannot reach the user (headless or CI), downgrade to assumptions-only and log the downgrade in the phase report.
EOF
      ;;
    assumptions)
      cat <<'EOF'
Do not block on clarifying questions. Convert every ambiguity into an explicit Assumption in the acceptance contract with a stated impact-if-wrong and carry the Assumptions ledger into the final report. If the lane cannot reach the user (headless or CI), downgrade to assumptions-only and log the downgrade in the phase report.
EOF
      ;;
    *)
      echo "bm_interview_prompt: mode must be full|batched|assumptions (got: $1)" >&2
      return 2
      ;;
  esac
}

# bm_model_failure_prompt <low|medium|high>
# low / medium: stop and return control variant.
# high: find one safe workaround variant.
bm_model_failure_prompt() {
  case "${1:-medium}" in
    low|medium)
      cat <<'EOF'
On a model failure or MODEL DRIFT, report phase, provider/model (requested and actual), error, tokens, and attempted work. Stop and return control. Do not retry or switch models.
EOF
      ;;
    high)
      cat <<'EOF'
On a model failure, report phase, provider/model, error, tokens, and attempted work. Find one safe workaround: narrow the task, retry once, or use an approved tier model. Validate it. If it fails, stop with goal_blocked evidence. MODEL DRIFT always surfaces in the phase report even at high autonomy; drifted work must be re-validated before merge.
EOF
      ;;
    *)
      echo "bm_model_failure_prompt: autonomy must be low|medium|high (got: $1)" >&2
      return 2
      ;;
  esac
}

# bm_gate_prompt <low|medium|high>
# low / medium: blocking variant.
# high: proceed variant.
bm_gate_prompt() {
  case "${1:-medium}" in
    low|medium)
      cat <<'EOF'
After each phase report, STOP and return control for approval before starting the next phase or merging. Do not continue past a gate on your own.
Each phase report must include an '## Open Questions' section listing every needs_decision item accrued during the phase, or 'none'; the gate is not passed until each item is answered or explicitly deferred.
EOF
      ;;
    high)
      cat <<'EOF'
Proceed through phase gates without stopping, but include every phase report in the final output in order.
Never block on questions after the upfront interview; fold accrued open questions into the final report's Assumptions section.
EOF
      ;;
    *)
      echo "bm_gate_prompt: autonomy must be low|medium|high (got: $1)" >&2
      return 2
      ;;
  esac
}
