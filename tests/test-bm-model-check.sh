#!/usr/bin/env bash
# Verify bm's model-availability preflight against a fake pi binary.
#
# bm must:
#   1. Exit 0 when the resolved provider/model exists in pi --list-models
#   2. Exit 2 with a clear message when the resolved provider/model is missing
#   3. Honor BM_SKIP_MODEL_CHECK=1 (bypass even when pi is missing)
#   4. Skip the check when --on is not local (remote host owns availability)
#
# Run from the repo root: ./tests/test-bm-model-check.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Fake pi that only knows anthropic/claude-opus-4-7 + minimax/MiniMax-M3.
# Anything else looks "unavailable" to the check.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/pi" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "--list-models" ]; then
  cat <<TABLE
provider      model                                      context  max-out  thinking  images
anthropic     claude-opus-4-7                            1M       128K     yes       yes
anthropic     claude-sonnet-4-6                          1M       128K     yes       yes
minimax       MiniMax-M3                                 1M       64K      yes       no
TABLE
  exit 0
fi
if [ "$1" = "list" ]; then
  printf '%s\n' '  npm:@gotgenes/pi-permission-system'
  exit 0
fi
exit 0
EOF
chmod +x "$TMP/bin/pi"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "ok: $*"; }

run_bm() {
  PATH="$TMP/bin:$PATH" "$ROOT/scripts/bm" "$@"
}

# Test 1: available frontier → bm proceeds past the check.
echo "Test 1: available frontier (anthropic/claude-opus-4-7)"
out="$(run_bm "do a thing" --frontier opus 2>&1)"
echo "$out" | grep -q "bm: pi not in PATH" && fail "preflight blocked an available model"
echo "$out" | grep -q "requested model(s) not available" && fail "preflight flagged available model as missing"
ok "available frontier passed"

# Test 2: missing frontier → bm exits 2 with alternatives listed.
echo "Test 2: missing frontier (anthropic/claude-fable-5)"
set +e
out="$(run_bm "do a thing" --frontier fable 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected exit 2, got $code"
echo "$out" | grep -q "anthropic/claude-fable-5"   || fail "did not name the missing model"
echo "$out" | grep -q "anthropic/claude-opus-4-7"  || fail "did not list claude-opus-4-7 as alternative"
echo "$out" | grep -q "minimax/MiniMax-M3"         || fail "did not list minimax as alternative"
echo "$out" | grep -qE "BM_SKIP_MODEL_CHECK|skip-model-check|skip model check" || fail "did not mention the bypass env var"
ok "missing frontier rejected with clear alternatives"

# Test 3: BM_SKIP_MODEL_CHECK=1 bypasses the check.
echo "Test 3: BM_SKIP_MODEL_CHECK=1 bypass"
out="$(BM_SKIP_MODEL_CHECK=1 run_bm "do a thing" --frontier fable 2>&1)"
echo "$out" | grep -q "requested model(s) not available" \
  && fail "bypass env var did not bypass"
ok "BM_SKIP_MODEL_CHECK=1 bypassed the check"

# Test 4: missing economy → exit 2.
echo "Test 4: missing economy (minimax/MiniMax-M99)"
set +e
out="$(run_bm "do a thing" --economy minimax/MiniMax-M99 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected exit 2, got $code"
echo "$out" | grep -q "minimax/MiniMax-M99" || fail "did not name the missing economy model"
ok "missing economy rejected"

# Test 5: no model args → check skipped (FRONTIER/ECONOMY empty).
echo "Test 5: no model args"
out="$(run_bm "do a thing" 2>&1)"
echo "$out" | grep -q "requested model(s) not available" \
  && fail "check ran with no models requested"
ok "no-model invocation skipped the check"

# Test 6: --on remote skips the local check (remote host owns availability).
echo "Test 6: --on remote-host skips the local check"
# Point ssh at a no-op so dispatch returns immediately without a real SSH.
mkdir -p "$TMP/ssh-bin"
cat > "$TMP/ssh-bin/ssh" <<'EOF'
#!/usr/bin/env bash
echo "fake-ssh: $*"
exit 0
EOF
chmod +x "$TMP/ssh-bin/ssh"
out="$(PATH="$TMP/bin:$TMP/ssh-bin:$PATH" run_bm "do a thing" --frontier fable --on remote-host 2>&1)"
echo "$out" | grep -q "requested model(s) not available" \
  && fail "local check ran during remote dispatch"
ok "remote dispatch skipped the local check"

# Test 7: a remote target cannot be parsed as an ssh option.
echo "Test 7: --on rejects ssh option injection"
set +e
out="$(PATH="$TMP/bin:$TMP/ssh-bin:$PATH" run_bm "do a thing" --on=-oProxyCommand=bad 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected exit 2 for ssh option target, got $code"
echo "$out" | grep -q "not an ssh option" || fail "did not explain rejected ssh option target"
ok "ssh option target rejected"

# Test 8: the optional LangGraph package is absent.  A -S interpreter keeps
# the source tree importable while excluding every site-package, including
# LangGraph itself.
echo "Test 8: absent LangGraph runtime exits 2 with an install hint"
cat > "$TMP/bin/python-no-site" <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 -S "$@"
EOF
chmod +x "$TMP/bin/python-no-site"
set +e
out="$(BEASTMODE_PYTHON="$TMP/bin/python-no-site" BM_SKIP_MODEL_CHECK=1 run_bm "do a thing" --harness langgraph 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected exit 2 without LangGraph, got $code"
echo "$out" | grep -q "pip install.*beastmode.*langgraph" || fail "missing LangGraph install hint"
echo "$out" | grep -q "Traceback" && fail "missing LangGraph runtime exposed a traceback"
ok "absent LangGraph runtime failed cleanly with an install hint"

echo ""
echo "All model-availability tests passed."
