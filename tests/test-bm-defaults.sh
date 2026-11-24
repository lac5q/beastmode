#!/usr/bin/env bash
# Verify trusted per-user bm defaults without starting any model or network call.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
TEST_HOME="$TMP/home"
mkdir -p "$TMP/bin" "$TEST_HOME"

cat > "$TMP/bin/codex" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then
  printf '%s\n' preflight >> "$BM_TEST_CALLS"
  printf '%s\n' 'fake-codex 1.0'
  exit 0
fi
printf '%s\n' dispatch >> "$BM_TEST_CALLS"
printf '%s\n' "BM_ALLOW_CLAUDE_OAUTH=${BM_ALLOW_CLAUDE_OAUTH:-}" "BM_SKIP_MODEL_CHECK=${BM_SKIP_MODEL_CHECK:-}" > "$BM_TEST_ENV"
python3 - "$BM_TEST_ARGS" "$@" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(sys.argv[2:], handle)
PY
EOF
chmod +x "$TMP/bin/codex"

cat > "$TMP/bin/hermes" <<'EOF'
#!/usr/bin/env bash
python3 - "$BM_TEST_ARGS" "$@" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(sys.argv[2:], handle)
PY
EOF
chmod +x "$TMP/bin/hermes"

cat > "$TMP/bin/ssh" <<'EOF'
#!/usr/bin/env bash
python3 - "$BM_TEST_SSH_ARGS" "$@" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(sys.argv[2:], handle)
PY
EOF
chmod +x "$TMP/bin/ssh"

cat > "$TMP/bin/pi" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  --list-models)
    printf '%s\n' 'provider model context max-out thinking images' \
      'vibeproxy gpt-6-luna 1M 128K yes yes' \
      'openai-codex gpt-6-luna 1M 128K yes yes'
    printf '%s\n' list-models >> "$BM_TEST_CALLS"
    exit 0
    ;;
  list)
    printf '%s\n' '  npm:@gotgenes/pi-permission-system'
    printf '%s\n' list >> "$BM_TEST_CALLS"
    exit 0
    ;;
esac
printf '%s\n' dispatch >> "$BM_TEST_CALLS"
python3 - "$BM_TEST_ARGS" "$@" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(sys.argv[2:], handle)
PY
EOF
chmod +x "$TMP/bin/pi"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }

run_bm() {
  local profile_mode="$1" profile_path="$2"
  shift 2
  local -a env_args
  env_args=(
    -u BM_ALLOW_CLAUDE_OAUTH -u BM_SKIP_MODEL_CHECK
    -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_BASE_URL
    -u CODEX_HOME
    -u BM_AUTO_TARGET
    -u BEASTMODE_GROK_WEEKLY_REMAINING_PCT
    -u BEASTMODE_GROK_WEEKLY_REMAINING_AT
    -u BEASTMODE_GROK_MIN_WEEKLY_REMAINING_PCT
  )
  if [ "$profile_mode" != explicit ]; then
    env_args+=(-u BM_DEFAULTS_FILE)
  fi
  env_args+=(
    HOME="$TEST_HOME" PATH="$TMP/bin:$PATH" BM_PROJECT_ROOT="$ROOT"
    TMPDIR="$TMP" BEASTMODE_CODEX_STATE_ROOT="$TMP/codex-state"
    BM_TEST_ARGS="${BM_TEST_ARGS:-$TMP/args.json}"
    BM_TEST_ENV="${BM_TEST_ENV:-$TMP/env.txt}"
    BM_TEST_CALLS="${BM_TEST_CALLS:-$TMP/calls.txt}"
    ${BM_TEST_API_KEY:+ANTHROPIC_API_KEY=$BM_TEST_API_KEY}
  )
  if [ "$profile_mode" = explicit ]; then
    env_args+=(BM_DEFAULTS_FILE="$profile_path")
  fi
  env "${env_args[@]}" "$ROOT/scripts/bm" "$@"
}

assert_codex() {
  python3 - "$TMP/args.json" "$@" <<'PY'
import json
import sys
args = json.load(open(sys.argv[1], encoding="utf-8"))
expected_model, effort, prompt_parts = sys.argv[2], sys.argv[3], sys.argv[4:]
assert args[args.index("--model") + 1] == expected_model, args
assert f'model_reasoning_effort="{effort}"' in args[args.index("-c") + 1], args
prompt = args[-1]
for part in prompt_parts:
    assert part in prompt, (part, prompt)
PY
}

echo "Test 1: trusted profile pins the requested seats and the API-key Claude watcher"
mkdir -p "$TEST_HOME/.beastmode"
cat > "$TEST_HOME/.beastmode/defaults.json" <<'JSON'
{
  "schema_version": 1,
  "harness": "codex",
  "frontier": "openai-codex/gpt-6.1-sol",
  "economy": "openai-codex/gpt-6-luna",
  "watcher": "anthropic/claude-opus-5-5",
  "limit_fallback": "xai/grok-4.7",
  "thinking": "max",
  "claude_subscription_watcher": true
}
JSON
rm -f "$TMP/args.json" "$TMP/env.txt" "$TMP/calls.txt"
BM_TEST_API_KEY=dummy BM_TEST_ARGS="$TMP/args.json" BM_TEST_ENV="$TMP/env.txt" BM_TEST_CALLS="$TMP/calls.txt" \
  run_bm default unused "review the implementation"
assert_codex gpt-6.1-sol max \
  'Seats: director=openai-codex/gpt-6.1-sol economy=openai-codex/gpt-6-luna watcher=anthropic/claude-opus-5-5 limit-fallback=xai/grok-4.7.' \
  'Claude seats on this harness must authenticate with ANTHROPIC_API_KEY (billed API); never use a Claude subscription login.' \
  'limit-fallback=xai/grok-4.7' \
  'Only a recorded provider quota/rate-limit failure authorizes one agent-level retry' \
  'Authentication or network errors, missing provenance, unsupported models, invalid output' \
  'bm does not automatically retry provider subprocesses' \
  'bin/beast-validator with model grok-4.7 and effort xhigh' \
  'modelUsage evidence of the served model'
grep -Fxq preflight "$TMP/calls.txt" || fail "trusted profile skipped Codex model preflight"
grep -Fxq dispatch "$TMP/calls.txt" || fail "trusted profile did not dispatch to the fake Codex CLI"
grep -Fxq 'BM_ALLOW_CLAUDE_OAUTH=' "$TMP/env.txt" || fail "profile exported the global OAuth bypass"
grep -Fxq 'BM_SKIP_MODEL_CHECK=' "$TMP/env.txt" || fail "profile enabled the model-check bypass"
ok "profile pins Codex Sol 6.1/max, Luna, and an API-key Opus 5.5 watcher"

echo "Test 2: CLI flags override profile seats, harness, and thinking"
cat > "$TEST_HOME/.beastmode/defaults.json" <<'JSON'
{
  "schema_version": 1,
  "harness": "pi",
  "frontier": "openai-codex/gpt-5.6-sol",
  "economy": "vibeproxy/gpt-6-luna",
  "watcher": "xai/grok-4.5",
  "thinking": "high"
}
JSON
mkdir -p "$TEST_HOME/.hermes"
cat > "$TEST_HOME/.hermes/config.yaml" <<'YAML'
openai-codex:
vibeproxy:
xai:
YAML
rm -f "$TMP/args.json" "$TMP/calls.txt"
BM_TEST_ARGS="$TMP/args.json" run_bm default unused "review the implementation" \
  --harness hermes --frontier openai-codex/gpt-6.1-sol \
  --economy openai-codex/gpt-6-luna --watcher xai/grok-4.6 --thinking medium
python3 - "$TMP/args.json" <<'PY'
import json
import sys
args = json.load(open(sys.argv[1], encoding="utf-8"))
assert args[args.index("--model") + 1] == "gpt-6.1-sol", args
assert args[args.index("--provider") + 1] == "openai-codex", args
prompt = args[args.index("-z") + 1]
for expected in (
    "director=openai-codex/gpt-6.1-sol",
    "economy=openai-codex/gpt-6-luna",
    "watcher=xai/grok-4.6",
):
    assert expected in prompt, (expected, prompt)
for stale in ("gpt-5.6-sol", "vibeproxy/gpt-6-luna", "grok-4.5"):
    assert stale not in prompt, (stale, prompt)
PY
ok "CLI selections replaced the profile and kept the explicit economy provider"

echo "Test 3: absent profile preserves built-in Pi defaults"
rm -f "$TEST_HOME/.beastmode/defaults.json" "$TMP/args.json" "$TMP/calls.txt"
BM_TEST_ARGS="$TMP/args.json" BM_TEST_CALLS="$TMP/calls.txt" \
  run_bm default unused "legacy defaults"
python3 - "$TMP/args.json" <<'PY'
import json
import sys
args = json.load(open(sys.argv[1], encoding="utf-8"))
assert args[args.index("--thinking") + 1] == "max", args
assert args[args.index("--model") + 1] == "vibeproxy/gpt-6-luna", args
prompt = args[args.index("--append-system-prompt") + 1]
assert "director= economy=vibeproxy/gpt-6-luna watcher=unset" in prompt, prompt
assert "limit-fallback=unset" in prompt, prompt
assert "No fallback is authorized when unset" in prompt, prompt
PY
grep -Fxq list-models "$TMP/calls.txt" || fail "legacy defaults skipped Pi model preflight"
grep -Fxq dispatch "$TMP/calls.txt" || fail "legacy defaults did not dispatch to fake Pi"
ok "no profile retained Pi, Luna, and max reasoning defaults"

echo "Test 4: checkout-local defaults remain untrusted"
mkdir -p "$TMP/local-project/.beastmode"
cat > "$TMP/local-project/.beastmode/defaults.json" <<'JSON'
{
  "schema_version": 1,
  "harness": "claude",
  "frontier": "xai/grok-4.5",
  "economy": "vibeproxy/gpt-6-luna",
  "thinking": "high"
}
JSON
rm -f "$TMP/args.json"
(cd "$TMP/local-project" && BM_TEST_ARGS="$TMP/args.json" run_bm default unused \
  "ignore local config" --harness codex --frontier sol)
assert_codex gpt-6.1-sol max \
  'Seats: director=openai-codex/gpt-6.1-sol economy=openai-codex/gpt-6-luna watcher=unset limit-fallback=unset.'
ok "checkout-local profile was ignored"

echo "Test 5: malformed, unknown, invalid, and missing explicit profiles fail before dispatch"
invalid_index=0
while IFS= read -r invalid_profile; do
  invalid_index=$((invalid_index + 1))
  profile_path="$TMP/invalid-$invalid_index.json"
  printf '%s\n' "$invalid_profile" > "$profile_path"
  rm -f "$TMP/args.json" "$TMP/calls.txt"
  set +e
  out="$(BM_TEST_ARGS="$TMP/args.json" BM_TEST_CALLS="$TMP/calls.txt" \
    run_bm explicit "$profile_path" "must not launch" --harness codex --frontier sol 2>&1)"
  code=$?
  set -e
  [ "$code" = 2 ] || fail "invalid profile $invalid_index returned $code: $invalid_profile"
  echo "$out" | grep -q "invalid defaults profile" || fail "invalid profile $invalid_index was not explained"
  [ ! -e "$TMP/args.json" ] || fail "invalid profile $invalid_index reached the provider"
done <<'JSONLINES'
not-json
{"schema_version":1,"unknown":true}
{"schema_version":2}
{"schema_version":1,"frontier":"openai-codex/model with spaces"}
{"schema_version":1,"limit_fallback":"xai/grok-4.7","limit_fallback":"xai/grok-4.6"}
{"schema_version":1,"limit_fallback":"openai-codex/model with spaces"}
{"schema_version":1,"limit_fallback":null}
{"schema_version":1,"thinking":"infinite"}
{"schema_version":1,"harness":[]}
{"schema_version":1,"economy":null}
JSONLINES
rm -f "$TMP/args.json" "$TMP/calls.txt"
set +e
out="$(BM_TEST_ARGS="$TMP/args.json" run_bm explicit "$TMP/does-not-exist.json" \
  "must not launch" --harness codex --frontier sol 2>&1)"
code=$?
set -e
[ "$code" = 2 ] || fail "explicit missing profile returned $code"
echo "$out" | grep -q "defaults profile not found" || fail "missing explicit profile was not explained"
[ ! -e "$TMP/args.json" ] || fail "missing explicit profile reached the provider"
ok "invalid profiles and explicit missing paths failed closed"

echo "Test 6: claude_subscription_watcher is parsed but does nothing"
cat > "$TEST_HOME/.beastmode/defaults.json" <<'JSON'
{
  "schema_version": 1,
  "harness": "codex",
  "frontier": "openai-codex/gpt-6.1-sol",
  "economy": "openai-codex/gpt-6-luna",
  "watcher": "anthropic/claude-opus-5-5",
  "claude_subscription_watcher": true
}
JSON
rm -f "$TMP/args.json" "$TMP/calls.txt"
set +e
out="$(BM_TEST_ARGS="$TMP/args.json" BM_TEST_CALLS="$TMP/calls.txt" run_bm default unused "must not launch" 2>&1)"
code=$?
set -e
[ "$code" = 3 ] || fail "legacy watcher flag returned $code, want 3 (breaker)"
echo "$out" | grep -q BREAKER || fail "legacy watcher flag exempted the breaker"
[ ! -e "$TMP/args.json" ] || fail "legacy watcher flag reached the provider"
ok "legacy claude_subscription_watcher exempts nothing"

echo "Test 7: CLI limit fallback overrides the trusted profile"
cat > "$TEST_HOME/.beastmode/defaults.json" <<'JSON'
{
  "schema_version": 1,
  "harness": "codex",
  "frontier": "openai-codex/gpt-6.1-sol",
  "economy": "openai-codex/gpt-6-luna",
  "limit_fallback": "xai/grok-4.7"
}
JSON
rm -f "$TMP/args.json"
BM_TEST_ARGS="$TMP/args.json" run_bm default unused "limited worker" \
  --limit-fallback xai/grok-4.6
assert_codex gpt-6.1-sol max \
  'limit-fallback=xai/grok-4.6' \
  'Only a recorded provider quota/rate-limit failure authorizes one agent-level retry of the same bounded contract with xai/grok-4.6' \
  'requested_model/actual_model receipts for both attempts' \
  'Authentication or network errors, missing provenance, unsupported models, invalid output' \
  'bm does not automatically retry provider subprocesses'
python3 - "$TMP/args.json" <<'PY'
import json
import sys
args = json.load(open(sys.argv[1], encoding="utf-8"))
prompt = args[-1]
assert "limit-fallback=xai/grok-4.7" not in prompt, prompt
PY
ok "CLI provider/model fallback replaced the profile value in the seat prompt"
rm -f "$TMP/args.json"
set +e
out="$(BM_TEST_ARGS="$TMP/args.json" run_bm default unused "invalid fallback" \
  --limit-fallback 'xai/grok-4.7 with spaces' 2>&1)"
code=$?
set -e
[ "$code" = 2 ] || fail "invalid qualified CLI fallback returned $code"
echo "$out" | grep -q "must resolve to a provider-qualified model ID" \
  || fail "invalid qualified CLI fallback was not rejected"
[ ! -e "$TMP/args.json" ] || fail "invalid qualified CLI fallback reached the provider"
ok "CLI qualified fallback uses the same conservative model-ID validation"

echo "Test 8: local LangGraph fails closed when its runner cannot consume fallback routing"
rm -f "$TMP/args.json" "$TMP/calls.txt"
set +e
out="$(BM_TEST_ARGS="$TMP/args.json" BM_TEST_CALLS="$TMP/calls.txt" \
  run_bm default unused "unsupported graph fallback" --harness langgraph 2>&1)"
code=$?
set -e
[ "$code" = 2 ] || fail "local LangGraph fallback returned $code instead of stopping"
echo "$out" | grep -q "LangGraph runner, which does not consume the shared seat prompt" \
  || fail "local LangGraph fallback was not rejected with the routing limitation"
[ ! -e "$TMP/args.json" ] || fail "local LangGraph fallback reached a fake model CLI"
ok "local LangGraph did not silently drop the configured fallback"

echo "Test 9: trusted fallback is forwarded to remote bm dispatch"
cat > "$TEST_HOME/.beastmode/defaults.json" <<'JSON'
{
  "schema_version": 1,
  "harness": "codex",
  "frontier": "openai-codex/gpt-6.1-sol",
  "limit_fallback": "xai/grok-4.6"
}
JSON
rm -f "$TMP/ssh-args.json"
BM_TEST_SSH_ARGS="$TMP/ssh-args.json" run_bm default unused "remote limited worker" --on fakehost
python3 - "$TMP/ssh-args.json" <<'PY'
import json
import sys
args = json.load(open(sys.argv[1], encoding="utf-8"))
assert args[0] == "--" and args[1] == "fakehost", args
remote_command = args[2]
assert "--limit-fallback 'xai/grok-4.6'" in remote_command, remote_command
assert "--frontier 'openai-codex/gpt-6.1-sol'" in remote_command, remote_command
PY
ok "profile fallback crossed the SSH boundary as a safely quoted qualified model ID"

echo "Test 10: Grok 4.7 watcher and fallback survive missing quota metadata"
cat > "$TEST_HOME/.beastmode/defaults.json" <<'JSON'
{
  "schema_version": 1,
  "harness": "codex",
  "frontier": "openai-codex/gpt-6.1-sol",
  "economy": "openai-codex/gpt-6-luna"
}
JSON
rm -f "$TMP/args.json"
out="$(BM_TEST_ARGS="$TMP/args.json" run_bm default unused "Grok selected explicitly" \
  --watcher grok --limit-fallback grok 2>&1)"
python3 - "$TMP/args.json" <<'PY'
import json
import sys
args = json.load(open(sys.argv[1], encoding="utf-8"))
prompt = args[-1]
assert "watcher=xai/grok-4.7 limit-fallback=xai/grok-4.7" in prompt, prompt
assert "bin/beast-validator with model grok-4.7 and effort xhigh" in prompt, prompt
assert "modelUsage evidence" in prompt, prompt
assert "grok-4.5" not in prompt, prompt
PY
if grep -q "switching every Grok seat" <<< "$out"; then
  fail "Grok 4.7 was silently downgraded without quota metadata"
fi
ok "grok alias resolved to 4.7 without quota metadata downgrade"

echo "Test 11: legacy explicit Grok 4.5 retains its quota guard"
rm -f "$TMP/args.json"
out="$(BM_TEST_ARGS="$TMP/args.json" run_bm default unused "legacy Grok selected" \
  --watcher xai/grok-4.5 2>&1)"
grep -q "switching every Grok seat to openai-codex/gpt-6-luna" <<< "$out" \
  || fail "legacy Grok 4.5 quota guard did not retain its downgrade"
python3 - "$TMP/args.json" <<'PY'
import json
import sys
args = json.load(open(sys.argv[1], encoding="utf-8"))
prompt = args[-1]
assert "watcher=openai-codex/gpt-6-luna" in prompt, prompt
PY
ok "legacy explicit Grok 4.5 still follows its existing quota guard"

echo ""
echo "All bm defaults tests passed."
