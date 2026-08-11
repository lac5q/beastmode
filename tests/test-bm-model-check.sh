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
if [ -n "${BM_TEST_PI_ARGS:-}" ]; then
  printf '%s\n' "$@" > "$BM_TEST_PI_ARGS"
fi
if [ "$1" = "--list-models" ]; then
  cat <<TABLE
provider      model                                      context  max-out  thinking  images
anthropic     claude-opus-4-7                            1M       128K     yes       yes
anthropic     claude-sonnet-4-6                          1M       128K     yes       yes
openai-codex  gpt-5.6-luna                              1M       128K     yes       yes
vibeproxy     gpt-5.6-luna                              1M       128K     yes       yes
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

# Fake Claude for the single-seat subscription lane tests. It never contacts
# Anthropic; it records the argv/stdin contract and proves bm uses the safe
# external lane instead of the Pi provider path.
cat > "$TMP/bin/claude" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\n' 'fake-claude 1.0'
  exit 0
fi
if [ -n "${BM_TEST_CLAUDE_ARGS:-}" ]; then
  printf '%s\n' "$@" > "$BM_TEST_CLAUDE_ARGS"
fi
if [ -n "${BM_TEST_CLAUDE_STDIN:-}" ]; then
  cat > "$BM_TEST_CLAUDE_STDIN"
fi
printf '%s\n' 'FAKE CLAUDE SUBSCRIPTION WATCHER'
EOF
chmod +x "$TMP/bin/claude"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "ok: $*"; }

run_bm() {
  # These cases use fake harnesses and never contact Anthropic.
  PATH="$TMP/bin:$PATH" "$ROOT/scripts/bm" "$@"
}

# Test 1: an Anthropic director is automatically routed through Claude print
# mode, without requiring the API-OAuth bypass environment variable.
echo "Test 1: Anthropic director prefers the Claude print lane"
claude_args="$TMP/claude-args"
claude_stdin="$TMP/claude-stdin"
pi_args="$TMP/pi-args"
out="$(BM_TEST_CLAUDE_ARGS="$claude_args" BM_TEST_CLAUDE_STDIN="$claude_stdin" \
  BM_TEST_PI_ARGS="$pi_args" run_bm "do a thing" --frontier opus \
  --autonomy low --interview off 2>&1)"
echo "$out" | grep -q "bm: pi not in PATH" && fail "preflight blocked an available model"
echo "$out" | grep -q "requested model(s) not available" && fail "preflight flagged available model as missing"
grep -Fxq -- '-p' "$claude_args" || fail "Anthropic route did not use claude -p"
grep -Fxq -- '--permission-mode' "$claude_args" || fail "Claude route omitted permission mode"
grep -Fxq 'plan' "$claude_args" || fail "Anthropic route did not use plan mode"
grep -Fxq -- '--model' "$claude_args" || fail "Claude route omitted the model pin"
grep -Fxq 'claude-opus-4-7' "$claude_args" || fail "Claude route lost the resolved model"
grep -q 'GOAL: do a thing' "$claude_stdin" || fail "Claude prompt was not supplied on stdin"
[ ! -e "$pi_args" ] || fail "Anthropic route incorrectly invoked Pi"
ok "Anthropic director used the single-seat Claude print lane"

# Test 2: the automatic route remains usable with both OAuth-bypass and API
# credentials absent; it must not fall back to an API-style Anthropic seat.
echo "Test 2: Claude print preference does not require API OAuth authorization"
set +e
out="$(env -u BM_ALLOW_CLAUDE_OAUTH -u ANTHROPIC_API_KEY \
  BM_TEST_CLAUDE_ARGS="$claude_args" PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/bm" "do a thing" --frontier opus --autonomy low --interview off 2>&1)"
code=$?
set -e
[ "$code" = "0" ] || fail "automatic Claude print route returned $code"
echo "$out" | grep -q "BREAKER: blocked Claude OAuth seat" \
  && fail "Anthropic route fell through to the API OAuth breaker"
ok "Claude print preference held without API OAuth authorization"

# Test 3: missing non-Anthropic frontier → bm exits 2 with alternatives listed.
echo "Test 3: missing frontier (openai-codex/gpt-5.6-luna-missing)"
set +e
out="$(run_bm "do a thing" --frontier openai-codex/gpt-5.6-luna-missing 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected exit 2, got $code"
echo "$out" | grep -q "openai-codex/gpt-5.6-luna-missing" || fail "did not name the missing model"
echo "$out" | grep -q "anthropic/claude-opus-4-7"  || fail "did not list claude-opus-4-7 as alternative"
echo "$out" | grep -q "openai-codex/gpt-5.6-luna"  || fail "did not list Luna Max as alternative"
echo "$out" | grep -qE "BM_SKIP_MODEL_CHECK|skip-model-check|skip model check" || fail "did not mention the bypass env var"
ok "missing frontier rejected with clear alternatives"

# Test 4: BM_SKIP_MODEL_CHECK=1 bypasses the check for a Claude route.
echo "Test 4: BM_SKIP_MODEL_CHECK=1 bypass"
out="$(BM_SKIP_MODEL_CHECK=1 run_bm "do a thing" --frontier opus 2>&1)"
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

# Test 8: Pi keeps its friendly Luna worker seat on the canonical authenticated
# openai-codex provider unless a fleet host explicitly opts into another lane.
echo "Test 8: Pi friendly Luna alias uses openai-codex"
pi_args="$TMP/pi-args"
out="$(BM_SKIP_MODEL_CHECK=0 BM_TEST_PI_ARGS="$pi_args" run_bm "do a thing" \
  --autonomy low --interview off 2>&1)"
grep -Fxq -- '--model' "$pi_args" || fail "Pi invocation omitted the model pin"
grep -Fxq 'openai-codex/gpt-5.6-luna' "$pi_args" \
  || fail "Pi friendly Luna seat did not use openai-codex"
ok "Pi friendly Luna alias retained openai-codex"

# Test 8a: a host with an authenticated managed extension can explicitly opt
# the friendly Pi alias into vibeproxy without changing the model pin.
echo "Test 8a: Pi Luna provider override uses vibeproxy"
pi_args="$TMP/pi-vibeproxy-args"
out="$(BM_SKIP_MODEL_CHECK=0 BM_PI_LUNA_PROVIDER=vibeproxy \
  BM_TEST_PI_ARGS="$pi_args" run_bm "do a thing" \
  --autonomy low --interview off 2>&1)"
grep -Fxq 'vibeproxy/gpt-5.6-luna' "$pi_args" \
  || fail "Pi Luna provider override did not use vibeproxy"
ok "Pi Luna provider override preserved"

# Test 8b: high autonomy advances gates automatically but must not strip the
# implementation tools from the Pi worker. The project permission policy is
# the mutation boundary.
echo "Test 8b: Pi high autonomy retains implementation tools"
pi_args="$TMP/pi-high-args"
out="$(BM_SKIP_MODEL_CHECK=0 BM_TEST_PI_ARGS="$pi_args" run_bm "do a thing" \
  --autonomy high --interview off 2>&1)"
grep -Fxq -- '--exclude-tools' "$pi_args" \
  && fail "Pi high autonomy still excluded implementation tools"
ok "Pi high autonomy retained bash/edit/write"

# Test 9: Hermes translates a friendly Luna alias to its authenticated
# provider namespace while preserving the model pin.
echo "Test 9: Hermes friendly Luna alias uses vibeproxy"
hermes_args="$TMP/hermes-args"
out="$(HOME="$TMP/hermes-home" PATH="$TMP/bin:$PATH" BM_TEST_ARGS="$hermes_args" \
  BM_SKIP_MODEL_CHECK=0 run_bm "do a thing" --harness hermes --economy luna-max 2>&1)"
grep -q 'economy=vibeproxy/gpt-5.6-luna' "$hermes_args" \
  || fail "friendly Luna alias did not translate to vibeproxy in the worker seat"
ok "Hermes friendly Luna alias translated to vibeproxy"

# Test 10: a qualified provider/model is an explicit operator choice and must
# not be rewritten for Hermes.
echo "Test 10: Hermes qualified Luna provider remains explicit"
out="$(HOME="$TMP/hermes-home" PATH="$TMP/bin:$PATH" BM_TEST_ARGS="$hermes_args" \
  BM_SKIP_MODEL_CHECK=0 run_bm "do a thing" --harness hermes \
    --economy openai-codex/gpt-5.6-luna 2>&1)"
grep -q 'economy=openai-codex/gpt-5.6-luna' "$hermes_args" \
  || fail "explicit Hermes provider was rewritten"
if grep -q 'economy=vibeproxy/gpt-5.6-luna' "$hermes_args"; then
  fail "explicit qualified Hermes provider was rewritten to vibeproxy"
fi
ok "Hermes qualified provider remained explicit"

# Test 11: the subscription lane is explicit and single-seat.
echo "Test 11: Claude subscription watcher uses one pinned seat"
out="$(PATH="$TMP/bin:$PATH" "$ROOT/scripts/bm" "review the phase report" \
  --harness claude --frontier opus --claude-subscription --autonomy high --interview off 2>&1)"
echo "$out" | grep -q "FAKE CLAUDE SUBSCRIPTION WATCHER" \
  || fail "Claude subscription watcher did not dispatch"
ok "Claude subscription watcher dispatched"

# Test 12: automatic subscription routing rejects a second Claude seat.
echo "Test 12: Claude multi-seat fan-out rejected"
set +e
out="$(run_bm "review the phase report" --frontier opus --economy haiku \
  --autonomy high --interview off 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected automatic multi-seat rejection, got $code"
echo "$out" | grep -q "exactly one seat" \
  || fail "multi-seat rejection did not explain the seat limit"
ok "Claude multi-seat fan-out rejected"

# Test 13: --on remote skips the local check (remote host owns availability).
echo "Test 13: --on remote-host skips the local check"
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

# Test 14: a remote target cannot be parsed as an ssh option.
echo "Test 14: --on rejects ssh option injection"
set +e
out="$(PATH="$TMP/bin:$TMP/ssh-bin:$PATH" run_bm "do a thing" --on=-oProxyCommand=bad 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "expected exit 2 for ssh option target, got $code"
echo "$out" | grep -q "not an ssh option" || fail "did not explain rejected ssh option target"
ok "ssh option target rejected"

# Test 15: the optional LangGraph package is absent.  A -S interpreter keeps
# the source tree importable while excluding every site-package, including
# LangGraph itself.
echo "Test 15: absent LangGraph runtime exits 2 with an install hint"
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

# Test 16: Grok is fail-closed when the weekly budget reading is absent.
echo "Test 16: Grok without a verified budget reading switches to Luna Max"
grok_args="$TMP/grok-args"
out="$(BM_SKIP_MODEL_CHECK=1 BM_TEST_PI_ARGS="$grok_args" run_bm "do a thing" \
  --frontier grok --autonomy low --interview off 2>&1)"
echo "$out" | grep -q "Grok weekly budget is below 40% or unverified" \
  || fail "missing Grok fail-closed guard message"
grep -Fxq 'xai/grok-4.5' "$grok_args" \
  && fail "Grok seat was still passed to pi without a verified budget"
grep -Fxq 'openai-codex/gpt-5.6-luna' "$grok_args" \
  || fail "Grok seat did not switch to Luna Max"
ok "unverified Grok budget switched to Luna Max"

# Test 17: 39% remains below the hard floor, while exactly 40% is allowed
# when the reading is current.
echo "Test 17: Grok 39% switches and 40% remains eligible"
grok_now="$(date +%s)"
out="$(BEASTMODE_GROK_WEEKLY_REMAINING_PCT=39 BEASTMODE_GROK_WEEKLY_REMAINING_AT="$grok_now" BM_SKIP_MODEL_CHECK=1 \
  BM_TEST_PI_ARGS="$grok_args" run_bm "do a thing" --frontier grok --autonomy low --interview off 2>&1)"
echo "$out" | grep -q "Grok weekly budget is below 40%" \
  || fail "39% did not trigger the Grok floor"
grep -Fxq 'xai/grok-4.5' "$grok_args" \
  && fail "39% Grok seat was not replaced"

out="$(BEASTMODE_GROK_WEEKLY_REMAINING_PCT=40 BEASTMODE_GROK_WEEKLY_REMAINING_AT="$grok_now" BM_SKIP_MODEL_CHECK=1 \
  BM_TEST_PI_ARGS="$grok_args" run_bm "do a thing" --frontier grok --autonomy low --interview off 2>&1)"
echo "$out" | grep -q "Grok weekly budget is below" \
  && fail "40% incorrectly triggered the Grok floor"
grep -Fxq 'xai/grok-4.5' "$grok_args" \
  || fail "40% did not preserve the explicitly requested Grok seat"
ok "39% switched and 40% preserved the Grok seat"

# Test 18: stale readings fail closed even when their percentage is above the floor.
echo "Test 18: stale Grok budget readings switch to Luna Max"
grok_old="$((grok_now - 604801))"
out="$(BEASTMODE_GROK_WEEKLY_REMAINING_PCT=90 BEASTMODE_GROK_WEEKLY_REMAINING_AT="$grok_old" BM_SKIP_MODEL_CHECK=1 \
  BM_TEST_PI_ARGS="$grok_args" run_bm "do a thing" --frontier grok --autonomy low --interview off 2>&1)"
echo "$out" | grep -q "Grok weekly budget is below 40% or unverified/stale" \
  || fail "stale Grok reading did not fail closed"
grep -Fxq 'xai/grok-4.5' "$grok_args" \
  && fail "stale Grok reading was still passed to pi"
grep -Fxq 'openai-codex/gpt-5.6-luna' "$grok_args" \
  || fail "stale Grok reading did not switch to Luna Max"
ok "stale Grok reading switched to Luna Max"

# Test 19: malformed readings fail before any provider invocation.
echo "Test 19: malformed Grok budget readings are rejected"
set +e
out="$(BEASTMODE_GROK_WEEKLY_REMAINING_PCT=unknown BM_SKIP_MODEL_CHECK=1 \
  BM_TEST_PI_ARGS="$grok_args" run_bm "do a thing" --frontier grok --autonomy low --interview off 2>&1)"
code=$?
set -e
[ "$code" = "2" ] || fail "malformed Grok budget reading returned $code"
echo "$out" | grep -q "must be a number from 0 to 100" \
  || fail "malformed Grok budget reading was not explained"
ok "malformed Grok budget reading rejected"

echo ""
echo "All model-availability tests passed."
