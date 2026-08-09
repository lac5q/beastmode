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

# Fake pi that only knows anthropic/claude-opus-4-7 + the approved Luna Max
# economy alias.
# Anything else looks "unavailable" to the check.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/pi" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "--list-models" ]; then
  cat <<TABLE
provider      model                                      context  max-out  thinking  images
anthropic     claude-opus-4-7                            1M       128K     yes       yes
anthropic     claude-sonnet-4-6                          1M       128K     yes       yes
openai-codex  gpt-5.6-luna                              1M       128K     yes       yes
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

# Fake Hermes records the resolved provider/model arguments without contacting
# a remote service. The provider preflight only needs a key in its config.
cat > "$TMP/bin/hermes" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$BM_TEST_ARGS"
EOF
chmod +x "$TMP/bin/hermes"
mkdir -p "$TMP/hermes-home/.hermes"
printf '%s\n%s\n' 'vibeproxy:' 'openai-codex:' > "$TMP/hermes-home/.hermes/config.yaml"

# Fake Claude for the explicit, single-seat subscription watcher test. It
# never contacts Anthropic; it only proves bm forwards the opt-in path.
cat > "$TMP/bin/claude" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\n' 'fake-claude 1.0'
  exit 0
fi
printf '%s\n' 'FAKE CLAUDE SUBSCRIPTION WATCHER'
EOF
chmod +x "$TMP/bin/claude"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "ok: $*"; }

run_bm() {
  # These preflight cases use a fake Claude model and never contact Anthropic;
  # explicitly authorize the subscription lane so the production breaker does
  # not mask the model-availability assertions below.
  BM_ALLOW_CLAUDE_OAUTH=1 PATH="$TMP/bin:$PATH" "$ROOT/scripts/bm" "$@"
}

# Test 1: available frontier → bm proceeds past the check.
echo "Test 1: available frontier (anthropic/claude-opus-4-7)"
out="$(run_bm "do a thing" --frontier opus 2>&1)"
echo "$out" | grep -q "bm: pi not in PATH" && fail "preflight blocked an available model"
echo "$out" | grep -q "requested model(s) not available" && fail "preflight flagged available model as missing"
ok "available frontier passed"

# Test 2: Claude subscription OAuth is blocked unless explicitly authorized.
echo "Test 2: Claude OAuth breaker requires explicit authorization"
set +e
out="$(env -u BM_ALLOW_CLAUDE_OAUTH -u ANTHROPIC_API_KEY PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/bm" "do a thing" --frontier opus 2>&1)"
code=$?
set -e
[ "$code" = "3" ] || fail "expected Claude OAuth breaker exit 3, got $code"
echo "$out" | grep -q "BREAKER: blocked Claude OAuth seat" \
  || fail "Claude OAuth breaker did not explain the explicit authorization requirement"
ok "Claude OAuth breaker held"

# Test 3: missing frontier → bm exits 2 with alternatives listed.
echo "Test 3: missing frontier (anthropic/claude-fable-5)"
set +e
out="$(run_bm "do a thing" --frontier fable 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected exit 2, got $code"
echo "$out" | grep -q "anthropic/claude-fable-5"   || fail "did not name the missing model"
echo "$out" | grep -q "anthropic/claude-opus-4-7"  || fail "did not list claude-opus-4-7 as alternative"
echo "$out" | grep -q "openai-codex/gpt-5.6-luna"  || fail "did not list Luna Max as alternative"
echo "$out" | grep -qE "BM_SKIP_MODEL_CHECK|skip-model-check|skip model check" || fail "did not mention the bypass env var"
ok "missing frontier rejected with clear alternatives"

# Test 4: BM_SKIP_MODEL_CHECK=1 bypasses the check.
echo "Test 4: BM_SKIP_MODEL_CHECK=1 bypass"
out="$(BM_SKIP_MODEL_CHECK=1 run_bm "do a thing" --frontier fable 2>&1)"
echo "$out" | grep -q "requested model(s) not available" \
  && fail "bypass env var did not bypass"
ok "BM_SKIP_MODEL_CHECK=1 bypassed the check"

# Test 5: missing economy → exit 2.
echo "Test 5: missing economy (openai-codex/gpt-5.6-luna-missing)"
set +e
out="$(run_bm "do a thing" --economy openai-codex/gpt-5.6-luna-missing 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected exit 2, got $code"
echo "$out" | grep -q "openai-codex/gpt-5.6-luna-missing" || fail "did not name the missing economy model"
ok "missing economy rejected"

# Test 6: an installed symlink still resolves the runner's sibling files.
# macOS installs ~/.local/bin/bm as a symlink; BASH_SOURCE must not make the
# launcher look for scripts/lib/prompts.sh under ~/.local/bin.
echo "Test 6: symlinked bm resolves its support files"
ln -s "$ROOT/scripts/bm" "$TMP/bin/bm-symlink"
set +e
out="$(PATH="$TMP/bin:$PATH" "$TMP/bin/bm-symlink" "do a thing" --economy openai-codex/gpt-5.6-luna-missing 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected symlinked bm to reach model preflight, got $code"
echo "$out" | grep -q "requested model(s) not available" \
  || fail "symlinked bm did not reach model preflight"
echo "$out" | grep -q "lib/prompts.sh: No such file" \
  && fail "symlinked bm resolved support files from the wrong directory"
ok "symlinked bm resolved support files"

# Test 7: no explicit economy arg → Luna Max is pinned by default.
echo "Test 7: implicit Luna Max economy seat"
out="$(run_bm "do a thing" 2>&1)"
echo "$out" | grep -q "requested model(s) not available" \
  && fail "implicit Luna Max preflight failed"
ok "implicit Luna Max economy seat passed preflight"

# Test 8: Hermes translates a friendly Luna alias to its authenticated
# provider namespace while preserving the model pin.
echo "Test 8: Hermes friendly Luna alias uses vibeproxy"
hermes_args="$TMP/hermes-args"
out="$(HOME="$TMP/hermes-home" PATH="$TMP/bin:$PATH" BM_TEST_ARGS="$hermes_args" \
  BM_SKIP_MODEL_CHECK=0 run_bm "do a thing" --harness hermes --economy luna-max 2>&1)"
grep -q 'economy=vibeproxy/gpt-5.6-luna' "$hermes_args" \
  || fail "friendly Luna alias did not translate to vibeproxy in the worker seat"
ok "Hermes friendly Luna alias translated to vibeproxy"

# Test 9: a qualified provider/model is an explicit operator choice and must
# not be rewritten for Hermes.
echo "Test 9: Hermes qualified Luna provider remains explicit"
out="$(HOME="$TMP/hermes-home" PATH="$TMP/bin:$PATH" BM_TEST_ARGS="$hermes_args" \
  BM_SKIP_MODEL_CHECK=0 run_bm "do a thing" --harness hermes \
    --economy openai-codex/gpt-5.6-luna 2>&1)"
grep -q 'economy=openai-codex/gpt-5.6-luna' "$hermes_args" \
  || fail "explicit Hermes provider was rewritten"
if grep -q 'economy=vibeproxy/gpt-5.6-luna' "$hermes_args"; then
  fail "explicit qualified Hermes provider was rewritten to vibeproxy"
fi
ok "Hermes qualified provider remained explicit"

# Test 10: the subscription lane is explicit and single-seat.
echo "Test 10: Claude subscription watcher uses one pinned seat"
out="$(PATH="$TMP/bin:$PATH" "$ROOT/scripts/bm" "review the phase report" \
  --harness claude --frontier opus --claude-subscription --autonomy high --interview off 2>&1)"
echo "$out" | grep -q "FAKE CLAUDE SUBSCRIPTION WATCHER" \
  || fail "Claude subscription watcher did not dispatch"
ok "Claude subscription watcher dispatched"

# Test 11: subscription mode rejects a second Claude seat.
echo "Test 11: Claude subscription multi-seat fan-out rejected"
set +e
out="$(PATH="$TMP/bin:$PATH" "$ROOT/scripts/bm" "review the phase report" \
  --harness claude --frontier opus --economy haiku --claude-subscription \
  --autonomy high --interview off 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected subscription multi-seat rejection, got $code"
echo "$out" | grep -q "exactly one Claude seat" \
  || fail "multi-seat rejection did not explain the seat limit"
ok "Claude subscription multi-seat fan-out rejected"

# Test 12: --on remote skips the local check (remote host owns availability).
echo "Test 12: --on remote-host skips the local check"
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

# Test 13: a remote target cannot be parsed as an ssh option.
echo "Test 13: --on rejects ssh option injection"
set +e
out="$(PATH="$TMP/bin:$TMP/ssh-bin:$PATH" run_bm "do a thing" --on=-oProxyCommand=bad 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected exit 2 for ssh option target, got $code"
echo "$out" | grep -q "not an ssh option" || fail "did not explain rejected ssh option target"
ok "ssh option target rejected"

# Test 14: the optional LangGraph package is absent.  A -S interpreter keeps
# the source tree importable while excluding every site-package, including
# LangGraph itself.
echo "Test 14: absent LangGraph runtime exits 2 with an install hint"
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
