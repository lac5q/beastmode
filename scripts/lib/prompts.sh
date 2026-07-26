#!/usr/bin/env bash
# prompts.sh — shared prompt library for beastmode.
#
# Sourceable from scripts/bm and tests. No side effects on source: no
# set -e, no global state mutations, only functions defined then a no-op
# guard so callers can `source` this file safely.
#
# Strings mirror the PHASE_PROMPT / MODEL_FAILURE_PROMPT / GATE_PROMPT
# values that used to live inline in scripts/bm. Keep them verbatim: the
# parity test in tests/test-acn-parity.sh asserts exact substrings, and
# downstream prompts (adapter SKILL.md, watcher validators) inherit the
# same wording.

# bm_phase_prompt — phase reporting contract.
# Verbatim from scripts/bm PHASE_PROMPT (no GSD variant).
bm_phase_prompt() {
  cat <<'EOF'
At the end of every phase, report phase name/status; requested model versus the model that actually served each task (from worker meta.json or the harness journal); tokens used / phase budget and percent; actual versus estimated time. Use the workflow journal or budget output. Say unavailable when a harness does not expose a value. If any task was served by a model other than the requested provider/model (router fallback, harness default, silent substitution), flag it as MODEL DRIFT in the phase report immediately with requested and actual IDs — never fold drift into a footnote.
EOF
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
EOF
      ;;
    high)
      cat <<'EOF'
Proceed through phase gates without stopping, but include every phase report in the final output in order.
EOF
      ;;
    *)
      echo "bm_gate_prompt: autonomy must be low|medium|high (got: $1)" >&2
      return 2
      ;;
  esac
}
