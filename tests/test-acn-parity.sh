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
else
  cat > "$TMP/bin/pi" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "--list-models" ]; then
  cat <<TABLE
provider      model                                      context  max-out  thinking  images
anthropic     claude-opus-4-7                            1M       128K     yes       yes
TABLE
  exit 0
fi
exit 0
EOF
  chmod +x "$TMP/bin/pi"
  set +e
  out="$(PATH="$TMP/bin:$PATH" "$ROOT/scripts/enforce-models" --harness pi --model definitely-not-a-provider/nope 2>&1)"
  rc=$?
  set -e
  if [ "$rc" = "2" ]; then
    pass "enforce-models --harness pi rejects unknown model with exit 2"
  else
    fail "enforce-models pi preflight expected exit 2, got $rc; output: $out"
  fi

  # A broken model-list probe must still surface the documented preflight
  # code, rather than leaking the probe's status through pipefail.
  mkdir -p "$TMP/failing-pi"
  cat > "$TMP/failing-pi/pi" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "--list-models" ]; then
  exit 7
fi
exit 0
EOF
  chmod +x "$TMP/failing-pi/pi"
  set +e
  out="$(PATH="$TMP/failing-pi:$PATH" "$ROOT/scripts/enforce-models" --harness pi --model definitely-not-a-provider/nope 2>&1)"
  rc=$?
  set -e
  if [ "$rc" = "2" ]; then
    pass "enforce-models preserves exit 2 when pi model listing fails"
  else
    fail "enforce-models leaked pi listing status, expected exit 2, got $rc; output: $out"
  fi
fi

# ---- (e) enforce-models --check-meta fixture sanity ----
# Fixtures are committed under tests/fixtures/acn-meta and read, not
# regenerated. The old version rewrote them into the repo tree on every run,
# which made the committed copies decorative and let them drift from the
# schema they are supposed to exemplify.
echo "check (e): enforce-models --check-meta"
FIX="$ROOT/tests/fixtures/acn-meta"

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

# ---- (e2) the gate fails closed on unprovable provenance ----
# Regression for the v2.2 fail-open pair: a legacy {"id","model",...} meta was
# skipped as "not a meta file we recognise", and an empty run dir returned 0.
# Both reported a clean batch while proving nothing about which model ran.
echo "check (e2): provenance gate fails closed"
run_gate() { set +e; GATE_OUT="$("$@" 2>&1)"; GATE_RC=$?; set -e; }

run_gate "$ROOT/scripts/enforce-models" --check-meta "$FIX/legacy"
if [ "$GATE_RC" = "1" ] && echo "$GATE_OUT" | grep -q "UNVERIFIABLE"; then
  pass "legacy model-only meta is UNVERIFIABLE, exit 1"
else
  fail "legacy meta: expected exit 1 with UNVERIFIABLE, got rc=$GATE_RC out=$GATE_OUT"
fi

run_gate "$ROOT/scripts/enforce-models" --check-meta "$FIX/empty"
if [ "$GATE_RC" = "1" ] && echo "$GATE_OUT" | grep -q "UNVERIFIABLE"; then
  pass "empty run dir is UNVERIFIABLE, exit 1"
else
  fail "empty dir: expected exit 1 with UNVERIFIABLE, got rc=$GATE_RC out=$GATE_OUT"
fi

run_gate "$ROOT/scripts/enforce-models" --check-meta "$FIX/empty" --allow-empty
if [ "$GATE_RC" = "0" ]; then
  pass "empty run dir with --allow-empty exits 0"
else
  fail "empty dir --allow-empty: expected exit 0, got rc=$GATE_RC out=$GATE_OUT"
fi

printf '%s' '{"id": "half", "requested_model": "anthropic/claude-opus-4-7"' > "$TMP/meta.json"
run_gate "$ROOT/scripts/enforce-models" --check-meta "$TMP"
if [ "$GATE_RC" = "1" ] && echo "$GATE_OUT" | grep -q "UNVERIFIABLE"; then
  pass "truncated meta is UNVERIFIABLE, exit 1"
else
  fail "truncated meta: expected exit 1 with UNVERIFIABLE, got rc=$GATE_RC out=$GATE_OUT"
fi
rm -f "$TMP/meta.json"

# Metadata discovery and parsing are bounded before any report is built.
BOUNDS="$TMP/bounds"; mkdir -p "$BOUNDS"
python3 - "$BOUNDS/meta.json" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_text('{"id":"large","padding":"' + ('x' * (300 * 1024)) + '"}')
PY
run_gate "$ROOT/scripts/enforce-models" --check-meta "$BOUNDS"
if [ "$GATE_RC" = "1" ] && echo "$GATE_OUT" | grep -q "exceeds"; then
  pass "oversized child metadata fails closed"
else
  fail "oversized meta: expected bounded failure, got rc=$GATE_RC out=$GATE_OUT"
fi

python3 - "$BOUNDS/meta.json" <<'PY'
from pathlib import Path
import json, sys
value = {"id": "deep", "requested_model": "m", "actual_model": "m"}
for _ in range(12):
    value = {"nested": value}
Path(sys.argv[1]).write_text(json.dumps(value))
PY
run_gate "$ROOT/scripts/enforce-models" --check-meta "$BOUNDS"
if [ "$GATE_RC" = "1" ] && echo "$GATE_OUT" | grep -q "nesting"; then
  pass "deeply nested metadata fails closed"
else
  fail "deep meta: expected bounded failure, got rc=$GATE_RC out=$GATE_OUT"
fi

SECRET_MODEL="ghp_$(printf 'a%.0s' {1..24})"
printf '%s\n' "{\"id\":\"secret-child\",\"requested_model\":\"$SECRET_MODEL\",\"actual_model\":\"other\",\"stop_reason\":\"end\",\"usage\":{},\"files_changed\":[],\"commands_run\":[],\"verify\":{}}" > "$BOUNDS/meta.json"
run_gate "$ROOT/scripts/acn-report" "$BOUNDS"
if ! echo "$GATE_OUT" | grep -q "$SECRET_MODEL" && echo "$GATE_OUT" | grep -q "REDACTED"; then
  pass "ACN diagnostics redact child-controlled model values"
else
  fail "ACN report exposed a child-controlled secret: $GATE_OUT"
fi

# A half-written child alongside a good one. The first cut of the gate keyed
# candidate detection on provenance fields, so a child that died before
# writing them was not recognised as a child at all — it vanished from the
# report and the good sibling carried the batch to exit 0.
SIB="$TMP/siblings"; mkdir -p "$SIB"
cp "$FIX/match/a.json" "$SIB/a.json"
printf '%s\n' '{"id": "lost", "usage": {"input_tokens": 900, "output_tokens": 40}}' > "$SIB/lost.json"
run_gate "$ROOT/scripts/enforce-models" --check-meta "$SIB"
if [ "$GATE_RC" = "1" ] && echo "$GATE_OUT" | grep -q "lost"; then
  pass "half-written sibling is UNVERIFIABLE despite a valid sibling"
else
  fail "half-written sibling: expected exit 1 naming 'lost', got rc=$GATE_RC out=$GATE_OUT"
fi

# Hermes preflight must fail closed when no configuration or auth exists.
mkdir -p "$TMP/no-hermes-home"
run_gate env HOME="$TMP/no-hermes-home" "$ROOT/scripts/enforce-models" --harness hermes --model minimax/MiniMax-M3
if [ "$GATE_RC" = "2" ]; then
  pass "Hermes preflight rejects missing configuration with exit 2"
else
  fail "Hermes missing config: expected exit 2, got rc=$GATE_RC out=$GATE_OUT"
fi

# The network cache probe must reject resource-amplifying call counts before I/O.
run_gate "$ROOT/scripts/cache-hitrate" --base-url http://127.0.0.1:1 --calls 11
if [ "$GATE_RC" = "2" ] && echo "$GATE_OUT" | grep -q "between 1 and 10"; then
  pass "cache-hitrate bounds --calls"
else
  fail "cache-hitrate --calls bound: expected exit 2, got rc=$GATE_RC out=$GATE_OUT"
fi

# ...and it must still appear as a row in the report, not just in the verdict.
run_gate "$ROOT/scripts/acn-report" "$SIB"
if echo "$GATE_OUT" | grep -q "lost"; then
  pass "acn-report lists the half-written child as a row"
else
  fail "acn-report omitted the half-written child: $GATE_OUT"
fi

# Provider config that merely mentions a model must NOT be read as a child —
# false-failing it would train people to pass --allow-empty everywhere.
CFG="$TMP/withcfg"; mkdir -p "$CFG"
cp "$FIX/match/a.json" "$CFG/a.json"
printf '%s\n' '{"model": "minimax/MiniMax-M3", "provider": "minimax"}' > "$CFG/config.json"
run_gate "$ROOT/scripts/enforce-models" --check-meta "$CFG"
if [ "$GATE_RC" = "0" ]; then
  pass "provider config is not mistaken for a child record"
else
  fail "provider config false-failed the gate: rc=$GATE_RC out=$GATE_OUT"
fi

# A child that wrote nothing at all leaves no file to scan, so only the
# batch's own id list can catch it.
run_gate "$ROOT/scripts/enforce-models" --check-meta "$FIX/match" --expect a,ghost
if [ "$GATE_RC" = "1" ] && echo "$GATE_OUT" | grep -q "ghost"; then
  pass "--expect catches a child that wrote no meta"
else
  fail "--expect: expected exit 1 naming 'ghost', got rc=$GATE_RC out=$GATE_OUT"
fi

run_gate "$ROOT/scripts/enforce-models" --check-meta "$FIX/match" --expect a
if [ "$GATE_RC" = "0" ]; then
  pass "--expect passes when every expected child reported"
else
  fail "--expect all-present: expected exit 0, got rc=$GATE_RC out=$GATE_OUT"
fi

# --expect also reads the batch file directly, since schema/acn-contract.json
# already requires tasks[].id — the manifest is a file the contract guarantees.
cat > "$TMP/batch.json" <<'JSON'
{"autonomy": "medium", "concurrency": 3,
 "tasks": [{"id": "a", "goal": "g", "allowed_paths": ["src"], "verify_cmds": ["true"]},
           {"id": "ghost", "goal": "g", "allowed_paths": ["src"], "verify_cmds": ["true"]}]}
JSON
run_gate "$ROOT/scripts/enforce-models" --check-meta "$FIX/match" --expect "$TMP/batch.json"
if [ "$GATE_RC" = "1" ] && echo "$GATE_OUT" | grep -q "ghost"; then
  pass "--expect reads child ids from a batch file"
else
  fail "--expect batch file: expected exit 1 naming 'ghost', got rc=$GATE_RC out=$GATE_OUT"
fi

# ---- (e3) enforce-models and acn-report agree on every fixture ----
# They used to be two implementations of one contract with different file
# discovery, so a child could pass one tool and fail the other.
echo "check (e3): enforce-models and acn-report agree"
AGREE=1
for case_dir in match drift legacy empty; do
  set +e
  "$ROOT/scripts/enforce-models" --check-meta "$FIX/$case_dir" >/dev/null 2>&1
  rc_enforce=$?
  "$ROOT/scripts/acn-report" "$FIX/$case_dir" >/dev/null 2>&1
  rc_report=$?
  set -e
  if [ "$rc_enforce" != "$rc_report" ]; then
    fail "$case_dir: enforce-models exit $rc_enforce but acn-report exit $rc_report"
    AGREE=0
  fi
done
[ "$AGREE" = "1" ] && pass "enforce-models and acn-report agree on all fixtures"

# ---- (e4) prose meta.json fields match the schema ----
# references/acn-contract.md documents the meta shape in prose; the schema
# declares it in JSON. Neither is allowed to drift from the other.
echo "check (e4): acn-contract.md meta fields match schema"
python3 - "$ROOT" <<'PY' && pass "acn-contract.md meta fields match schema" || fail "acn-contract.md meta fields drifted from schema/acn-contract.json"
import json, re, sys
from pathlib import Path

root = Path(sys.argv[1])
schema = json.loads((root / "schema" / "acn-contract.json").read_text())
declared = set(schema["meta_json_required_fields"])

doc = (root / "references" / "acn-contract.md").read_text()
block = re.search(r"## Per-child meta\.json.*?```\n(.*?)```", doc, re.S)
if not block:
    print("could not find the meta.json block in references/acn-contract.md", file=sys.stderr)
    sys.exit(1)
documented = {
    line.split()[0]
    for line in block.group(1).splitlines()
    if line.strip() and not line.startswith(" ")
}

if documented != declared:
    print(f"only in schema: {sorted(declared - documented)}", file=sys.stderr)
    print(f"only in doc:    {sorted(documented - declared)}", file=sys.stderr)
    sys.exit(1)
PY

# ---- (e6) Python ChildMeta derives the schema field list ----
echo "check (e6): Python ChildMeta fields match schema"
PYTHONPATH="$ROOT/python/src" python3 - "$ROOT" <<'PY' && pass "Python ChildMeta fields match schema" || fail "Python ChildMeta fields drifted from schema/acn-contract.json"
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
from beastmode.langgraph.state import ChildMeta

schema_fields = set(json.loads((root / "schema" / "acn-contract.json").read_text())["meta_json_required_fields"])
if set(ChildMeta.__required_keys__) != schema_fields:
    print("schema:", sorted(schema_fields), file=sys.stderr)
    print("python:", sorted(ChildMeta.__required_keys__), file=sys.stderr)
    raise SystemExit(1)
PY

# ---- (e5) no spec still prescribes the pre-v2.3 merged-model meta shape ----
# Scoped to the surfaces that *specify* the contract. .learnings/ and
# .planning/ are records of what happened, and a record of this defect has to
# be able to quote the broken shape verbatim to be worth reading.
echo "check (e5): no legacy meta shape in specs"
LEGACY_SHAPE='"id", *"model"'
legacy_hits="$(grep -rn "$LEGACY_SHAPE" --include='*.md' \
  "$ROOT/SKILL.md" "$ROOT/README.md" "$ROOT/references" "$ROOT/adapters" "$ROOT/pi" \
  2>/dev/null || true)"
if [ -n "$legacy_hits" ]; then
  echo "$legacy_hits" >&2
  fail "a spec still prescribes the merged-model meta shape (gate cannot compare it)"
else
  pass "no spec prescribes the merged-model meta shape"
fi

# ---- (f) adapter SKILL.md vocabulary ----
echo "check (f): adapters/*/SKILL.md vocabulary"
ANY_ADAPTER=0
for adapter in hermes claude-code codex langgraph; do
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

# ---- (h) adapter version cross-refs track SKILL.md ----
# Each adapter names the canonical skill version it implements. Nothing kept
# those in sync with SKILL.md's frontmatter, so a bump silently left three
# adapters claiming an older contract.
echo "check (h): adapter version cross-refs match SKILL.md"
python3 - "$ROOT" <<'PY' && pass "adapter version cross-refs match SKILL.md" || fail "adapter version cross-refs drifted from SKILL.md frontmatter"
import re, sys
from pathlib import Path

root = Path(sys.argv[1])
skill = (root / "SKILL.md").read_text()
match = re.search(r"^version:\s*(\S+)\s*$", skill, re.M)
if not match:
    print("no version in SKILL.md frontmatter", file=sys.stderr)
    sys.exit(1)
canonical = match.group(1)

bad = []
for adapter in sorted((root / "adapters").glob("*/SKILL.md")):
    for ref in re.findall(r"`beastmode`[^\n]*?\(v(\d+\.\d+\.\d+)\)", adapter.read_text()):
        if ref != canonical:
            bad.append(f"{adapter.relative_to(root)} claims v{ref}, SKILL.md is v{canonical}")
for line in bad:
    print(line, file=sys.stderr)
sys.exit(1 if bad else 0)
PY

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
