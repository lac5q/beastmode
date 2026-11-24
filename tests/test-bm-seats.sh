#!/usr/bin/env bash
# Verify Claude-led seat profile and the Claude OAuth breaker without any
# model or network call (fake CLIs only).
set -euo pipefail

# Nothing here may reach a real remote host.
unset BM_AUTO_TARGET BM_ON BM_REMOTE SSH_AUTH_SOCK SSH_CONNECTION

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
TEST_HOME="$TMP/home"
mkdir -p "$TMP/bin" "$TEST_HOME/.beastmode"

cat > "$TMP/bin/claude" <<'FAKE'
#!/usr/bin/env bash
[ "${1:-}" = "--version" ] && { echo 'fake-claude 1.0'; exit 0; }
printf '%s\n' "$@" > "$BM_TEST_ARGV"
cat > "$BM_TEST_STDIN"
echo FAKE-CLAUDE
FAKE
cat > "$TMP/bin/pi" <<'FAKE'
#!/usr/bin/env bash
echo pi-called >> "$BM_TEST_CALLS"
exit 0
FAKE
cat > "$TMP/bin/ssh" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$BM_TEST_SSH"
exit 0
FAKE
cat > "$TMP/bin/hermes" <<'FAKE'
#!/usr/bin/env bash
echo hermes-called >> "$BM_TEST_CALLS"
exit 0
FAKE
cat > "$TMP/bin/codex" <<'FAKE'
#!/usr/bin/env bash
echo codex-called >> "$BM_TEST_CALLS"
exit 0
FAKE
chmod +x "$TMP/bin/claude" "$TMP/bin/pi" "$TMP/bin/ssh" "$TMP/bin/hermes" "$TMP/bin/codex"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }

run_bm() {
  env -u BM_AUTO_TARGET -u BM_ALLOW_CLAUDE_OAUTH -u BM_SKIP_MODEL_CHECK -u BM_DEFAULTS_FILE \
    -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_BASE_URL \
    ${BM_T_OAUTH:+BM_ALLOW_CLAUDE_OAUTH=$BM_T_OAUTH} ${BM_T_SKIP:+BM_SKIP_MODEL_CHECK=1} ${BM_T_KEY:+ANTHROPIC_API_KEY=$BM_T_KEY} \
    HOME="$TEST_HOME" PATH="$TMP/bin:$PATH" BM_PROJECT_ROOT="$ROOT" TMPDIR="$TMP" \
    BM_TEST_STDIN="$TMP/stdin.txt" BM_TEST_ARGV="$TMP/argv.txt" BM_TEST_SSH="$TMP/ssh.txt" BM_TEST_CALLS="$TMP/calls.txt" \
    "$ROOT/scripts/bm" "$@" </dev/null
}

# expect_code <want> <cmd...>: run, capture output in $TMP/out.txt, assert exit code.
expect_code() {
  local want="$1" code; shift
  set +e; "$@" >"$TMP/out.txt" 2>&1; code=$?; set -e
  [ "$code" = "$want" ] || { cat "$TMP/out.txt" >&2; fail "exit $code, want $want: ${*:2}"; }
}

echo "Test 1: economy_thinking/watcher_thinking reach the seat prompt"
cat > "$TEST_HOME/.beastmode/defaults.json" <<'JSON'
{
  "schema_version": 1,
  "harness": "claude",
  "frontier": "anthropic/claude-opus-5-5",
  "economy": "anthropic/claude-sonnet-5-5",
  "watcher": "openai-codex/gpt-6.2-astra",
  "economy_thinking": "medium",
  "watcher_thinking": "high"
}
JSON
rm -f "$TMP/stdin.txt"
expect_code 0 run_bm "review it" --autonomy low --interview off
grep -Fq 'Run economy workers at reasoning effort medium.' "$TMP/stdin.txt" || fail "economy line missing"
grep -Fq 'Run the watcher at reasoning effort high.' "$TMP/stdin.txt" || fail "watcher line missing"
ok "both effort lines present"

echo "Test 2: unset keys add no effort text"
sed -i '/_thinking/d; s/"openai-codex\/gpt-6.2-astra",/"openai-codex\/gpt-6.2-astra"/' "$TEST_HOME/.beastmode/defaults.json"
rm -f "$TMP/stdin.txt"
expect_code 0 run_bm "review it" --autonomy low --interview off
grep -Fq 'reasoning effort' "$TMP/stdin.txt" && fail "effort text present when unset"
ok "no effort text when unset"

echo "Test 3: invalid value exits 2"
for key in economy_thinking watcher_thinking; do
  printf '{"schema_version":1,"%s":"turbo"}\n' "$key" > "$TEST_HOME/.beastmode/defaults.json"
  expect_code 2 run_bm "x"
  grep -Fq "$key must be" "$TMP/out.txt" || fail "no $key message"
done
ok "invalid effort rejected"

echo "Test 4: Anthropic seats are not blocked on --harness claude, blocked on --harness pi"
rm -f "$TEST_HOME/.beastmode/defaults.json" "$TMP/calls.txt" "$TMP/stdin.txt"
expect_code 0 run_bm "do it" --harness claude --frontier anthropic/claude-opus-5-5 --economy openai-codex/gpt-6-luna \
  --autonomy low --interview off
grep -q BREAKER "$TMP/out.txt" && fail "claude harness hit the breaker"
[ -s "$TMP/stdin.txt" ] || fail "claude not invoked"
grep -Fq 'Claude Code workers:' "$TMP/stdin.txt" && fail "worker-pin sentence present for non-Anthropic economy seat"
expect_code 3 run_bm "do it" --harness pi --frontier openai-codex/gpt-6.1-sol --economy openai-codex/gpt-6-luna \
  --watcher anthropic/claude-opus-5-5 --autonomy low --interview off
grep -Fq 'non-Anthropic tool' "$TMP/out.txt" || fail "new breaker message missing"
grep -Fq 'ANTHROPIC_API_KEY' "$TMP/out.txt" || fail "breaker message omits API-key option"
[ ! -e "$TMP/calls.txt" ] || fail "pi was dispatched"
ok "claude passes; pi exits 3 with the new message"

echo "Test 5: non-claude harness + Anthropic seat: OAuth env is no override; API key and claude harness pass"
bm_pi() { run_bm "do it" --harness pi --frontier openai-codex/gpt-6.1-sol --economy openai-codex/gpt-6-luna \
  --watcher anthropic/claude-opus-5-5 --autonomy low --interview off; }
BM_T_OAUTH=1 expect_code 3 bm_pi
rm -f "$TMP/calls.txt"
BM_T_KEY=dummy BM_T_SKIP=1 expect_code 0 run_bm "do it" --harness hermes --frontier openai-codex/gpt-6.1-sol \
  --economy openai-codex/gpt-6-luna --watcher anthropic/claude-opus-5-5 --autonomy low --interview off
grep -q BREAKER "$TMP/out.txt" && fail "API key still hit the breaker"
grep -Fxq hermes-called "$TMP/calls.txt" || fail "hermes not dispatched with an API key"
expect_code 0 run_bm "do it" --harness claude --frontier anthropic/claude-opus-5-5 --watcher anthropic/claude-sonnet-5-5 \
  --autonomy low --interview off
ok "exit 3 without key (override ignored); key and claude harness exit 0"

echo "Test 6: director opus + economy sonnet + watcher astra on --harness claude"
cat > "$TEST_HOME/.beastmode/defaults.json" <<'JSON'
{
  "schema_version": 1,
  "harness": "claude",
  "frontier": "anthropic/claude-opus-5-5",
  "economy": "anthropic/claude-sonnet-5-5",
  "watcher": "openai-codex/gpt-6.2-astra"
}
JSON
rm -f "$TMP/stdin.txt"
expect_code 0 run_bm "review it" --autonomy low --interview off
grep -q BREAKER "$TMP/out.txt" && fail "trio hit the breaker"
grep -Fq 'director=anthropic/claude-opus-5-5 economy=anthropic/claude-sonnet-5-5 watcher=openai-codex/gpt-6.2-astra' "$TMP/stdin.txt" \
  || fail "seat prompt does not name all three seats"
grep -Fq 'Claude Code workers: pass model=claude-sonnet-5-5 explicitly' "$TMP/stdin.txt" || fail "workers not told to pin claude-sonnet-5-5"
grep -Fxq -- 'claude-opus-5-5' "$TMP/argv.txt" || { cat "$TMP/argv.txt" >&2; fail "claude argv lacks director model"; }
grep -Fq 'Pin the executor model on every child' "$TMP/stdin.txt" || fail "prompt lacks pin rule"
ok "trio accepted; dispatched prompt and argv carry the sonnet-5-5 worker pin"

echo "Test 7: limit-fallback Claude seat trips the breaker (local and --on)"
rm -f "$TEST_HOME/.beastmode/defaults.json"
LF=(--frontier openai-codex/gpt-6.1-sol --economy openai-codex/gpt-6-luna --limit-fallback anthropic/claude-opus-5-5 --autonomy low --interview off)
rm -f "$TMP/calls.txt" "$TMP/ssh.txt"
expect_code 3 run_bm "do it" --harness pi "${LF[@]}"
grep -Fq 'anthropic/claude-opus-5-5' "$TMP/out.txt" || fail "breaker did not name the fallback seat"
expect_code 3 run_bm "do it" --harness pi --on somehost "${LF[@]}"
[ ! -e "$TMP/ssh.txt" ] && [ ! -e "$TMP/calls.txt" ] || fail "fallback seat was dispatched"
ok "fallback seat blocked before dispatch"

echo "Test 8: hermes/codex without --frontier exit 2"
rm -f "$TEST_HOME/.beastmode/defaults.json" "$TMP/calls.txt"
for h in hermes codex; do
  expect_code 2 run_bm "do it" --harness "$h" --autonomy low --interview off
  grep -Fq -- "--harness $h requires --frontier" "$TMP/out.txt" || fail "$h: pin message missing"
  expect_code 2 run_bm "do it" --harness "$h" --economy openai-codex/gpt-6-luna --autonomy low --interview off
  grep -Fq -- "--harness $h requires --frontier" "$TMP/out.txt" || fail "$h: pin message missing (explicit economy)"
done
[ ! -e "$TMP/calls.txt" ] || fail "unpinned hermes/codex was dispatched"
ok "unpinned director rejected"

echo "Test 9: --claude-subscription needs an anthropic/* director; extra Claude seats still pass"
expect_code 2 run_bm "do it" --harness claude --claude-subscription --autonomy low --interview off
grep -Fq 'pin the director model' "$TMP/out.txt" || fail "subscription missing-frontier director message missing"
expect_code 2 run_bm "do it" --harness claude --claude-subscription --frontier openai-codex/gpt-6.1-sol \
  --autonomy low --interview off
grep -Fq 'anthropic/*' "$TMP/out.txt" || fail "subscription director message missing"
expect_code 0 run_bm "do it" --harness claude --claude-subscription --frontier anthropic/claude-opus-5-5 \
  --economy anthropic/claude-sonnet-5-5 --watcher anthropic/claude-sonnet-5-5 --autonomy low --interview off
ok "unpinned or non-Claude director rejected; Claude trio accepted"

echo "Test 10: --economy-thinking/--watcher-thinking override the profile, forward over --on, reject on langgraph"
cat > "$TEST_HOME/.beastmode/defaults.json" <<'JSON'
{"schema_version":1,"harness":"claude","frontier":"anthropic/claude-opus-5-5","economy":"anthropic/claude-sonnet-5-5","economy_thinking":"low","watcher_thinking":"low"}
JSON
rm -f "$TMP/stdin.txt"
expect_code 0 run_bm "do it" --economy-thinking high --watcher-thinking=xhigh --autonomy low --interview off
grep -Fq 'Run economy workers at reasoning effort high.' "$TMP/stdin.txt" || fail "economy override missing"
grep -Fq 'Run the watcher at reasoning effort xhigh.' "$TMP/stdin.txt" || fail "watcher override missing"
grep -Fq 'effort low' "$TMP/stdin.txt" && fail "profile value leaked past the override"
expect_code 2 run_bm "do it" --economy-thinking turbo
rm -f "$TEST_HOME/.beastmode/defaults.json" "$TMP/ssh.txt"
expect_code 0 run_bm "do it" --harness claude --frontier anthropic/claude-opus-5-5 --on somehost \
  --economy-thinking medium --watcher-thinking high --autonomy low --interview off
grep -Fq -- '--economy-thinking' "$TMP/ssh.txt" && grep -Fq -- '--watcher-thinking' "$TMP/ssh.txt" || { cat "$TMP/ssh.txt" >&2; fail "remote command lacks thinking flags"; }
for f in --economy-thinking --watcher-thinking; do
  expect_code 2 run_bm "do it" --harness langgraph --frontier openai-codex/gpt-6.1-sol --economy openai-codex/gpt-6-luna "$f" high
  grep -Fq 'not supported by the local LangGraph runner' "$TMP/out.txt" || fail "langgraph $f message missing"
done
ok "flags override, forward, and langgraph rejects"

echo "Test 11: worker-pin sentence under claude; Claude OAuth stripped for non-claude harnesses, API key kept"
cat > "$TEST_HOME/.beastmode/defaults.json" <<'JSON'
{"schema_version":1,"harness":"claude","frontier":"anthropic/claude-opus-5-5","economy":"anthropic/claude-sonnet-5-5"}
JSON
rm -f "$TMP/stdin.txt"
expect_code 0 run_bm "review it" --autonomy low --interview off
grep -Fq 'Claude Code workers: pass model=claude-sonnet-5-5 explicitly on every Task subagent and every `claude -p --model claude-sonnet-5-5`; never inherit the director model.' "$TMP/stdin.txt" \
  || fail "claude worker-pin sentence missing"
rm -f "$TEST_HOME/.beastmode/defaults.json" "$TMP/stdin.txt" "$TMP/env.txt" "$TMP/ssh.txt"
expect_code 0 run_bm "review it" --harness claude --claude-subscription --frontier anthropic/claude-opus-5-5 \
  --autonomy low --interview off
[ -s "$TMP/stdin.txt" ] || fail "claude not invoked for default luna-max economy"
grep -Fq 'economy=openai-codex/gpt-6-luna' "$TMP/stdin.txt" || fail "default luna-max economy was not retained"
grep -Fq 'Claude Code workers:' "$TMP/stdin.txt" && fail "worker-pin sentence present for default luna-max economy"
cat > "$TMP/bin/hermes" <<'FAKE'
#!/usr/bin/env bash
echo hermes-called >> "$BM_TEST_CALLS"
{ echo "oauth=${CLAUDE_CODE_OAUTH_TOKEN:-unset}"; echo "refresh=${CLAUDE_CODE_OAUTH_REFRESH_TOKEN:-unset}"; echo "other=${CLAUDE_CODE_OAUTH_X:-unset}"; echo "key=${ANTHROPIC_API_KEY:-unset}"; } > "$BM_TEST_ENV"
exit 0
FAKE
HERMES_ARGS=(run_bm "do it" --harness hermes --frontier openai-codex/gpt-6.1-sol --economy openai-codex/gpt-6-luna --autonomy low --interview off)
BM_TEST_ENV="$TMP/env.txt" CLAUDE_CODE_OAUTH_TOKEN=secret CLAUDE_CODE_OAUTH_REFRESH_TOKEN=secret2 CLAUDE_CODE_OAUTH_X=secret3 \
  BM_T_KEY=apikey BM_T_SKIP=1 expect_code 0 "${HERMES_ARGS[@]}"
grep -Fxq 'oauth=unset' "$TMP/env.txt" && grep -Fxq 'refresh=unset' "$TMP/env.txt" && grep -Fxq 'other=unset' "$TMP/env.txt" \
  || { cat "$TMP/env.txt" >&2; fail "Claude OAuth variable reached hermes"; }
grep -Fxq 'key=apikey' "$TMP/env.txt" || fail "ANTHROPIC_API_KEY did not reach hermes"
CLAUDE_CODE_OAUTH_TOKEN=secret BM_T_SKIP=1 expect_code 0 run_bm "do it" --harness hermes --on somehost \
  --frontier openai-codex/gpt-6.1-sol --economy openai-codex/gpt-6-luna --autonomy low --interview off
grep -Fq 'CLAUDE_CODE_OAUTH_TOKEN' "$TMP/ssh.txt" || fail "remote command does not strip the OAuth token"
ok "pin sentence present; OAuth stripped locally and remotely, API key kept"

echo ""
echo "All bm seat tests passed."
