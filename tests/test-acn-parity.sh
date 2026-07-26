#!/usr/bin/env bash
# test-acn-parity.sh — ACN parity checks for the v2.2.0 unification.
#
# Verifies schema validity, alias resolution, prompt-lib content parity,
# enforce-models preflight/postflight, adapter vocabulary, and the bm
# --harness flag. Each check prints PASS/FAIL; the script exits non-zero
# on any FAIL. SKIP is allowed when a phase hasn't shipped its surface
# yet (no schema/, no adapters/).
#
# Run from repo root: ./tests/test-acn-parity.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"

FAILS=0
PASSES=0
SKIPS=0

pass() { echo "PASS: $*"; PASSES=$((PASSES + 1)); }
fail() { echo "FAIL: $*"; FAILS=$((FAILS + 1)); }
skip() { echo "SKIP: $*"; SKIPS=$((SKIPS + 1)); }

# ---- (a) schema/*.json parses ----
echo "check (a): schema/*.json parses"
if [ -d "$ROOT/schema" ]; then
  schema_files=( "$ROOT/schema"/*.json )
  if [ ! -e "${schema_files[0]}" ]; then
    skip "schema/ has no *.json files"
  elif find "$ROOT/schema" -maxdepth 1 -name '*.json' -print0 | xargs -0 -I{} \
       python3 -m json.tool {} >/dev/null; then
    pass "schema/*.json parses"
  else
    fail "schema/*.json has invalid JSON"
  fi
else
  skip "schema/ missing (phase 001 not shipped yet)"
fi

# ---- (b) tier-aliases.json: every alias has tier; family (if present) exists ----
echo "check (b): scripts/tier-aliases.json alias sanity"
if [ ! -f "$ROOT/scripts/tier-aliases.json" ]; then
  fail "scripts/tier-aliases.json missing"
else
  python3 - "$ROOT" "$ROOT/scripts/tier-aliases.json" <<'PY' && pass "tier-aliases.json valid" || fail "tier-aliases.json invalid"
import json, sys, os
root, alias_path = sys.argv[1], sys.argv[2]
with open(alias_path) as f:
    data = json.load(f)
known_tiers = {"frontier", "economy"}
families_path = os.path.join(root, "schema", "families.json")
families = set()
if os.path.exists(families_path):
    with open(families_path) as f:
        fam = json.load(f)
    # families.json shape: either a list of names or {"families": [...]}
    if isinstance(fam, list):
        families = {str(x) for x in fam}
    elif isinstance(fam, dict):
        families = {str(x) for x in fam.get("families", list(fam.keys()))}
for key, val in data.items():
    if key.startswith("_"):
        continue
    if not isinstance(val, dict):
        print(f"alias {key!r} is not a dict", file=sys.stderr)
        sys.exit(1)
    tier = val.get("tier")
    if tier not in known_tiers:
        print(f"alias {key!r} has unknown tier {tier!r}", file=sys.stderr)
        sys.exit(1)
    if "family" in val:
        if families and val["family"] not in families:
            print(f"alias {key!r} family {val['family']!r} not in families.json", file=sys.stderr)
            sys.exit(1)
PY
fi

# ---- (c) prompts.sh source + verify substrings ----
echo "check (c): scripts/lib/prompts.sh content parity"
if [ ! -f "$ROOT/scripts/lib/prompts.sh" ]; then
  fail "scripts/lib/prompts.sh missing"
else
  out="$(bash -c 'set -e; . "$1"; bm_gate_prompt medium' bash "$ROOT/scripts/lib/prompts.sh" 2>&1)"
  echo "$out" | grep -q "STOP and return control" && pass "bm_gate_prompt medium → STOP and return control" || fail "bm_gate_prompt medium missing 'STOP and return control'; got: $out"

  out="$(bash -c 'set -e; . "$1"; bm_model_failure_prompt high' bash "$ROOT/scripts/lib/prompts.sh" 2>&1)"
  echo "$out" | grep -q "safe workaround" && pass "bm_model_failure_prompt high → safe workaround" || fail "bm_model_failure_prompt high missing 'safe workaround'; got: $out"

  out="$(bash -c 'set -e; . "$1"; bm_phase_prompt' bash "$ROOT/scripts/lib/prompts.sh" 2>&1)"
  echo "$out" | grep -q "MODEL DRIFT" && pass "bm_phase_prompt → MODEL DRIFT" || fail "bm_phase_prompt missing 'MODEL DRIFT'; got: $out"
fi

# ---- (d) enforce-models --harness pi rejects unknown model ----
echo "check (d): enforce-models preflight rejects unknown model"
if [ ! -f "$ROOT/scripts/enforce-models" ]; then
  fail "scripts/enforce-models missing"
elif ! command -v pi >/dev/null 2>&1; then
  skip "pi not in PATH"
else
  set +e
  out="$("$ROOT/scripts/enforce-models" --harness pi --model definitely-not-a-provider/nope 2>&1)"
  rc=$?
  set -e
  if [ "$rc" = "2" ]; then
    pass "enforce-models --harness pi rejects unknown model with exit 2"
  else
    fail "enforce-models pi preflight expected exit 2, got $rc; output: $out"
  fi
fi

# ---- (e) enforce-models --check-meta fixture sanity ----
echo "check (e): enforce-models --check-meta"
FIX="$ROOT/tests/fixtures/acn-meta"
mkdir -p "$FIX/match" "$FIX/drift"
cat > "$FIX/match/a.json" <<'JSON'
{"id": "a", "requested_model": "anthropic/claude-opus-4-7", "actual_model": "anthropic/claude-opus-4-7", "usage": {"input_tokens": 10, "output_tokens": 20}}
JSON
cat > "$FIX/drift/b.json" <<'JSON'
{"id": "b", "requested_model": "anthropic/claude-opus-4-7", "actual_model": "kimi-coding/k2", "usage": {"input_tokens": 1, "output_tokens": 2}}
JSON

set +e
out_match="$("$ROOT/scripts/enforce-models" --check-meta "$FIX/match" 2>&1)"
rc_match=$?
out_drift="$("$ROOT/scripts/enforce-models" --check-meta "$FIX/drift" 2>&1)"
rc_drift=$?
set -e

if [ "$rc_match" = "0" ] && ! echo "$out_match" | grep -q "MODEL DRIFT"; then
  pass "enforce-models --check-meta all-matching exits 0"
else
  fail "enforce-models --check-meta matching dir: expected exit 0 no drift, got rc=$rc_match out=$out_match"
fi
if [ "$rc_drift" = "1" ] && echo "$out_drift" | grep -q "MODEL DRIFT"; then
  pass "enforce-models --check-meta drifting exits 1 with MODEL DRIFT"
else
  fail "enforce-models --check-meta drift dir: expected exit 1 with 'MODEL DRIFT', got rc=$rc_drift out=$out_drift"
fi

# ---- (f) adapter SKILL.md vocabulary ----
echo "check (f): adapters/*/SKILL.md vocabulary"
ANY_ADAPTER=0
for adapter in hermes claude-code codex; do
  f="$ROOT/adapters/$adapter/SKILL.md"
  if [ ! -f "$f" ]; then
    skip "adapters/$adapter/SKILL.md missing (phase 003/004 not shipped yet)"
    continue
  fi
  ANY_ADAPTER=1
  if grep -qi -- "MODEL DRIFT" "$f" && grep -qi -- "gates are blocking below high" "$f"; then
    pass "adapters/$adapter/SKILL.md contains MODEL DRIFT and gates vocabulary"
  else
    fail "adapters/$adapter/SKILL.md missing required vocabulary"
  fi
done
[ "$ANY_ADAPTER" -eq 0 ] && skip "no adapter SKILL.md files yet"

# ---- (g) scripts/bm --harness bogus exits 2 ----
echo "check (g): scripts/bm --harness bogus exits 2"
if [ ! -f "$ROOT/scripts/bm" ]; then
  fail "scripts/bm missing"
elif ! grep -q -- "--harness" "$ROOT/scripts/bm"; then
  skip "scripts/bm has no --harness flag yet"
else
  set +e
  out="$("$ROOT/scripts/bm" --harness bogus "x" 2>&1)"
  rc=$?
  set -e
  if [ "$rc" = "2" ]; then
    pass "scripts/bm --harness bogus exits 2"
  else
    fail "scripts/bm --harness bogus expected exit 2, got $rc; output: $out"
  fi
fi

# ---- summary ----
echo
echo "----------------------------------------"
echo "PASS: $PASSES  FAIL: $FAILS  SKIP: $SKIPS"
if [ "$FAILS" -eq 0 ]; then
  echo "ACN parity: all checks passed"
  exit 0
fi
echo "ACN parity: $FAILS failure(s)"
exit 1
