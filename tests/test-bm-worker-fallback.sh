#!/usr/bin/env bash
# Verify implicit worker routing when an Anthropic frontier director has no
# live economy provider from the normal Luna lane.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
mkdir -p "$TMP/hm/.beastmode"
mkdir -p "$TMP/uh/.beastmode"
printf '%s\n' '{"schema_version":1}' > "$TMP/defaults.json"
cat > "$TMP/hm/.beastmode/tier-aliases.json" <<'EOF'
{
  "external-worker": {
    "provider": "vibeproxy",
    "model": "gemini-3.6-flash-high",
    "tier": "economy",
    "family": "google",
    "worker_fallback": true
  }
}
EOF

cat > "$TMP/bin/pi" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "--list-models" ]; then
  cat <<TABLE
provider      model                                      context  max-out  thinking  images
anthropic     claude-fable-5                             1M       128K     yes       yes
anthropic     claude-haiku-4-5                          1M       128K     yes       yes
TABLE
  if [ "${BM_TEST_FALLBACK_MODE:-haiku}" = "external" ]; then
    printf '%s\n' 'vibeproxy     gemini-3.6-flash-high                    1M       128K     yes       yes'
  fi
  exit 0
fi
if [ "$1" = "list" ]; then
  printf '%s\n' '  npm:@gotgenes/pi-permission-system'
  exit 0
fi
printf '%s\n' "$@" > "${BM_TEST_PI_ARGS:?}"
EOF
# The sonnet case uses a separate fake so model-list output stays deterministic.
chmod +x "$TMP/bin/pi"

cat > "$TMP/bin/claude" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then
  printf '%s\n' 'fake-claude 1.0'
  exit 0
fi
printf '%s\n' "$@" > "${BM_TEST_CLAUDE_ARGS:?}"
cat > "${BM_TEST_CLAUDE_STDIN:?}"
printf '%s\n' 'FAKE CLAUDE SUBSCRIPTION WATCHER'
EOF
chmod +x "$TMP/bin/claude"

run_bm() {
  local test_home="$TMP/hm"
  [ "${BM_TEST_NO_MARKED_ALIAS:-0}" = "1" ] && test_home="$TMP/uh"
  BM_DEFAULTS_FILE="$TMP/defaults.json" \
  HOME="$test_home" \
  BM_SKIP_MODEL_CHECK=0 \
  BM_TEST_CLAUDE_ARGS="$TMP/claude-args" \
  BM_TEST_CLAUDE_STDIN="$TMP/claude-stdin" \
  BM_TEST_PI_ARGS="$TMP/pi-args" \
  PATH="$TMP/bin:$PATH" \
    "$ROOT/scripts/bm" "$@"
}

echo "Test 1: unavailable default economy falls back to Anthropic Haiku"
rm -f "$TMP/claude-args" "$TMP/claude-stdin" "$TMP/pi-args"
out="$(run_bm "implement the bounded task" --frontier fable --autonomy low --interview off 2>&1)"
echo "$out" | grep -q 'using Anthropic worker fallback anthropic/claude-haiku-4-5'
grep -q 'economy=anthropic/claude-haiku-4-5' "$TMP/claude-stdin"
grep -q 'pass model=haiku explicitly' "$TMP/claude-stdin"
grep -Fxq 'claude-fable-5' "$TMP/claude-args"
test ! -e "$TMP/pi-args"
echo "ok: Haiku fallback was pinned in the worker contract"

echo "Test 1b: a live non-Anthropic economy lane wins first"
rm -f "$TMP/claude-args" "$TMP/claude-stdin" "$TMP/pi-args"
out="$(BM_TEST_FALLBACK_MODE=external run_bm "implement with the live economy lane" \
  --frontier fable --autonomy low --interview off 2>&1)"
echo "$out" | grep -q 'using live economy worker vibeproxy/gemini-3.6-flash-high'
grep -q 'economy=vibeproxy/gemini-3.6-flash-high' "$TMP/claude-stdin"
if echo "$out" | grep -q 'Anthropic worker fallback'; then
  echo "same-provider fallback won over a live external economy lane" >&2
  exit 1
fi
echo "ok: live external economy lane was preferred"

echo "Test 1c: an unmarked external lane remains manual"
rm -f "$TMP/claude-args" "$TMP/claude-stdin" "$TMP/pi-args"
out="$(BM_TEST_FALLBACK_MODE=external BM_TEST_NO_MARKED_ALIAS=1 run_bm \
  "keep provenance strict" --frontier fable --autonomy low --interview off 2>&1)"
echo "$out" | grep -q 'using Anthropic worker fallback anthropic/claude-haiku-4-5'
if echo "$out" | grep -q 'using live economy worker'; then
  echo "unmarked external lane was selected automatically" >&2
  exit 1
fi
echo "ok: unmarked external lane stayed manual"

echo "Test 2: Claude harness permits an explicit Sonnet worker override"
rm -f "$TMP/claude-args" "$TMP/claude-stdin" "$TMP/pi-args"
out="$(BM_CLAUDE_WORKER_MODEL=sonnet run_bm "review the bounded task" \
  --harness claude --frontier fable --autonomy low --interview off 2>&1)"
echo "$out" | grep -q 'using Anthropic worker fallback anthropic/claude-sonnet-4-6'
grep -q 'economy=anthropic/claude-sonnet-4-6' "$TMP/claude-stdin"
grep -q 'pass model=sonnet explicitly' "$TMP/claude-stdin"
echo "ok: Sonnet worker override was pinned"

echo "Test 3: explicit economy selection is not silently downgraded"
out="$(run_bm "keep explicit worker" --harness claude --frontier fable \
  --economy openai-codex/gpt-6-luna-missing --autonomy low --interview off 2>&1)"
grep -q 'economy=openai-codex/gpt-6-luna-missing' "$TMP/claude-stdin"
if echo "$out" | grep -q 'worker fallback'; then
  echo "explicit economy unexpectedly fell back" >&2
  exit 1
fi
echo "ok: explicit economy was preserved"

echo
echo "All worker fallback tests passed."
