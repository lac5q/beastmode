#!/usr/bin/env bash
# run-all.sh — the whole beastmode gate in one command.
#
# The repo's own thesis is that a run is not validated until a gate says so.
# Until now the gates existed as three separate scripts with no entrypoint, so
# "all tests pass" meant "whichever ones you remembered to run". This is the
# entrypoint: CI runs it, and so should you before pushing.
#
# Mirrors the verification commands in .planning/ACCEPTANCE.md.
#
#   ./tests/run-all.sh          # run everything, print a summary
#
# Exit code: 0 all green, 1 any failure.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# py_compile would otherwise litter __pycache__ into the repo; a test run must
# leave the working tree exactly as it found it.
export PYTHONDONTWRITEBYTECODE=1

FAILED=()
PASSED=()

run_step() {
  local name="$1"; shift
  echo
  echo "=============================================================="
  echo ">> $name"
  echo "=============================================================="
  if "$@"; then
    PASSED+=("$name")
  else
    echo "!! FAILED: $name (exit $?)"
    FAILED+=("$name")
  fi
}

# ---- static checks ----
syntax_check() {
  local rc=0
  # shellcheck disable=SC2044
  for f in $(find scripts tests -type f \( -name '*.sh' -o -name 'bm' -o -name 'enforce-models' \)); do
    head -1 "$f" | grep -q 'bash\|sh' || continue
    bash -n "$f" || rc=1
  done
  python3 -m py_compile scripts/acn-report scripts/phase-estimate \
      scripts/cache-hitrate scripts/lib/acn_meta.py || rc=1
  return $rc
}

json_check() {
  local rc=0
  for f in schema/*.json scripts/tier-aliases.json; do
    python3 -m json.tool "$f" >/dev/null || { echo "invalid JSON: $f"; rc=1; }
  done
  return $rc
}

run_step "syntax (bash -n + py_compile)" syntax_check
run_step "JSON validity (schema/ + tier-aliases)" json_check
run_step "phase-estimate self-test" python3 scripts/phase-estimate --self-test
run_step "ACN parity" ./tests/test-acn-parity.sh
run_step "bm model preflight" ./tests/test-bm-model-check.sh
run_step "bm thinking passthrough" ./tests/test-bm-thinking.sh
run_step "shell security regressions" ./tests/test-shell-security.sh
run_step "installer integrity" ./tests/test-installer-integrity.sh
run_step "dependency integrity" ./tests/test-dependency-integrity.sh
run_step "public artifact guard" ./tests/test-public-artifact-guard.sh
run_step "Pi security regressions" ./tests/test-pi-security.sh

# ---- summary ----
echo
echo "=============================================================="
for name in "${PASSED[@]}"; do
  echo "  PASS  $name"
done
for name in "${FAILED[@]+"${FAILED[@]}"}"; do
  echo "  FAIL  $name"
done
echo "=============================================================="
if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "beastmode: ${#PASSED[@]}/${#PASSED[@]} steps green"
  exit 0
fi
echo "beastmode: ${#FAILED[@]} step(s) failed"
exit 1
