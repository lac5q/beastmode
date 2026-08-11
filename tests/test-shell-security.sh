#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# This suite uses fake harnesses and never contacts Anthropic. Anthropic
# routing is intentionally tested without any API-OAuth bypass environment.

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }

mkdir -p "$TMP/bin" "$TMP/repo/.beastmode" \
  "$TMP/repo/.pi/extensions/pi-permission-system"
git -C "$TMP/repo" init -q
cp "$ROOT/pi/config/pi-permission-system.json" \
  "$TMP/repo/.pi/extensions/pi-permission-system/config.json"
cat > "$TMP/bin/pi" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "list" ]; then
  printf '%s\n' 'User packages:' '  npm:@gotgenes/pi-permission-system'
  exit 0
fi
printf '%s\n' "$@" > "$BM_TEST_ARGS"
exit 0
EOF
cat > "$TMP/bin/hermes" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$BM_TEST_ARGS"
exit 0
EOF
cat > "$TMP/bin/claude" <<'EOF'
#!/usr/bin/env bash
if [ -n "${BM_CLAUDE_ENV:-}" ]; then
  env | grep -E '^(ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|ANTHROPIC_BASE_URL|BM_ALLOW_CLAUDE_OAUTH)=' > "$BM_CLAUDE_ENV" || true
fi
printf '%s\n' "$@" > "$BM_TEST_ARGS"
exit 0
EOF
cat > "$TMP/bin/codex" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$BM_TEST_ARGS"
if [ -n "${BM_TEST_ENV:-}" ]; then
  printf 'CODEX_HOME=%s\nXDG_CACHE_HOME=%s\nXDG_DATA_HOME=%s\nXDG_STATE_HOME=%s\nXDG_CONFIG_HOME=%s\n' \
    "${CODEX_HOME:-}" \
    "${XDG_CACHE_HOME:-}" \
    "${XDG_DATA_HOME:-}" \
    "${XDG_STATE_HOME:-}" \
    "${XDG_CONFIG_HOME:-}" > "$BM_TEST_ENV"
fi
exit 0
EOF
chmod +x "$TMP/bin/pi" "$TMP/bin/hermes" "$TMP/bin/claude" "$TMP/bin/codex"

cat > "$TMP/repo/.beastmode/tier-aliases.json" <<'EOF'
{"opus":{"provider":"minimax","model":"MiniMax-M3","tier":"economy","family":"minimax"}}
EOF

args="$TMP/args"
(
  cd "$TMP/repo"
  BM_SKIP_MODEL_CHECK=1 BM_TEST_ARGS="$args" PATH="$TMP/bin:$PATH" \
    "$ROOT/scripts/bm" "inspect" --frontier opus >/dev/null
)
grep -Fxq 'claude-opus-4-7' "$args" \
  || fail "repository alias overrode the shipped frontier alias without explicit trust"
ok "repository aliases cannot downgrade a model by default"

(
  cd "$TMP/repo"
  BM_TRUST_REPO_ALIASES=1 BM_SKIP_MODEL_CHECK=1 BM_TEST_ARGS="$args" PATH="$TMP/bin:$PATH" \
    "$ROOT/scripts/bm" "inspect" --frontier opus >/dev/null
)
grep -Fxq 'minimax/MiniMax-M3' "$args" \
  || fail "explicitly trusted repository alias was not honored"
ok "repository aliases remain available through explicit trust"

set +e
unknown_out="$(BM_SKIP_MODEL_CHECK=1 BM_TEST_ARGS="$args" PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/bm" "inspect" --frontier definitely-unknown 2>&1)"
unknown_rc=$?
set -e
[ "$unknown_rc" -eq 2 ] || fail "unknown alias did not fail closed (rc=$unknown_rc)"
grep -q 'unknown model alias' <<< "$unknown_out" || fail "unknown alias error was not clear"
ok "unknown aliases fail closed"

for harness in hermes claude; do
  BM_SKIP_MODEL_CHECK=1 BM_TEST_ARGS="$args" PATH="$TMP/bin:$PATH" \
    "$ROOT/scripts/bm" "inspect" --harness "$harness" --frontier opus --autonomy high >/dev/null
  if grep -Eq -- '--yolo|--full-auto|--dangerously-skip-permissions|bypassPermissions' "$args"; then
    fail "$harness high autonomy weakened tool permissions"
  fi
done
ok "high autonomy does not bypass Hermes or Claude permissions"

BM_SKIP_MODEL_CHECK=1 BM_TEST_ARGS="$args" PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/bm" "inspect" --harness pi --frontier gpt5.6 --autonomy high >/dev/null
grep -Fxq -- '--approve' "$args" \
  || fail "Pi launcher did not force project trust for headless runs"
if grep -Fxq -- '--exclude-tools' "$args" || grep -Fxq -- '--no-builtin-tools' "$args"; then
  fail "Pi high autonomy disabled implementation or repository tools"
fi
ok "Pi high autonomy retains implementation tools under project policy"

codex_env="$TMP/codex.env"
BM_SKIP_MODEL_CHECK=1 BM_TEST_ARGS="$args" BM_TEST_ENV="$codex_env" PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/bm" "inspect" --harness codex --frontier gpt5.6 --thinking max --autonomy high >/dev/null
grep -Fxq -- '--model' "$args" || fail "Codex invocation omitted --model"
grep -Fxq 'gpt-5.6-luna' "$args" || fail "Codex invocation did not pin the bare resolved model"
grep -Fxq 'model_reasoning_effort="max"' "$args" || fail "Codex invocation did not forward max reasoning effort"
grep -Fxq -- '--ignore-user-config' "$args" || fail "Codex invocation did not isolate the worker from user MCP and hook drift"
grep -Fxq -- '--ephemeral' "$args" || fail "Codex invocation did not isolate worker session state"
grep -Eq '^CODEX_HOME=.+/codex$' "$codex_env" || fail "Codex invocation did not use a writable isolated CODEX_HOME"
for xdg_var in XDG_CACHE_HOME XDG_DATA_HOME XDG_STATE_HOME XDG_CONFIG_HOME; do
  grep -Eq "^${xdg_var}=.+" "$codex_env" || fail "Codex invocation did not isolate $xdg_var"
done
if grep -Fxq 'openai-codex/gpt-5.6-luna' "$args"; then
  fail "Codex invocation retained a provider prefix the CLI does not accept"
fi
if grep -Eq -- '--yolo|--full-auto|--dangerously-skip-permissions' "$args"; then
  fail "Codex high autonomy weakened sandbox or approval controls"
fi
ok "Codex is model-pinned at the requested reasoning effort without permission bypass"

set +e
codex_out="$(BM_SKIP_MODEL_CHECK=1 BM_TEST_ARGS="$args" PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/bm" "inspect" --harness codex 2>&1)"
codex_rc=$?
set -e
[ "$codex_rc" -eq 2 ] || fail "Codex without a pinned frontier did not fail closed (rc=$codex_rc)"
grep -q -- '--frontier' <<< "$codex_out" || fail "Codex pinning error did not explain the required flag"
ok "Codex refuses an unpinned invocation"

printf '%s' 'inspect' | BM_TEST_ARGS="$args" PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/claude-pro" >/dev/null
grep -Fxq -- '--permission-mode' "$args" || fail "claude-pro omitted its safe permission mode"
grep -Fxq 'plan' "$args" || fail "claude-pro did not use plan permission mode"
if grep -q -- '--dangerously-skip-permissions' "$args"; then
  fail "claude-pro still bypasses permissions"
fi
ok "claude-pro uses a fail-closed permission mode"

set +e
claude_injection_out="$(BM_TEST_ARGS="$args" PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/claude-pro" --dangerously-skip-permissions 2>&1 </dev/null)"
claude_injection_rc=$?
set -e
[ "$claude_injection_rc" -eq 2 ] || fail "claude-pro accepted an unknown permission flag"
grep -q 'prompts are accepted only on stdin' <<< "$claude_injection_out" \
  || fail "claude-pro flag rejection was not explicit"
ok "claude-pro rejects option-shaped prompt injection"

set +e
claude_model_out="$(printf '%s' 'inspect' | BM_TEST_ARGS="$args" PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/claude-pro" --model '../opus' 2>&1)"
claude_model_rc=$?
set -e
[ "$claude_model_rc" -eq 2 ] || fail "claude-pro accepted a path-shaped model id"
grep -q 'bare Claude model id or alias' <<< "$claude_model_out" \
  || fail "claude-pro model-format rejection was not explicit"
ok "claude-pro rejects path-shaped model identifiers"

claude_env="$TMP/claude.env"
printf '%s' 'inspect' | BM_CLAUDE_ENV="$claude_env" \
  ANTHROPIC_API_KEY='should-not-forward' \
  ANTHROPIC_AUTH_TOKEN='should-not-forward' \
  ANTHROPIC_BASE_URL='https://custom.invalid' \
  BM_ALLOW_CLAUDE_OAUTH=1 BM_TEST_ARGS="$args" PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/claude-pro" >/dev/null
[ ! -s "$claude_env" ] || fail "claude-pro forwarded ambient Anthropic credentials or API-OAuth authorization"
ok "claude-pro scrubs ambient Anthropic API credentials and endpoint overrides"

set +e
cache_out="$(ANTHROPIC_AUTH_TOKEN='do-not-forward' \
  "$ROOT/scripts/cache-hitrate" --base-url https://attacker.invalid --calls 1 2>&1)"
cache_rc=$?
set -e
[ "$cache_rc" -eq 2 ] || fail "custom cache URL was accepted without explicit trust (rc=$cache_rc)"
grep -q -- '--allow-custom-base-url' <<< "$cache_out" || fail "custom URL rejection lacked opt-in guidance"
ok "cache probe rejects custom endpoints before network I/O"

mkdir -p "$TMP/python-stub"
cat > "$TMP/python-stub/sitecustomize.py" <<'PY'
from pathlib import Path
import json
import os
import urllib.request

mode = os.environ.get("BM_CACHE_TEST_MODE", "small")
header_file = os.environ["BM_CACHE_TEST_HEADER"]

payload = (
    b"x" * (1024 * 1024 + 1)
    if mode == "large"
    else json.dumps({
        "usage": {
            "input_tokens": 0,
            "cache_creation_input_tokens": 1,
            "cache_read_input_tokens": 0,
        }
    }).encode()
)

class Response:
    headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return payload if size < 0 else payload[:size]

def urlopen(request, timeout=0):
    del timeout
    Path(header_file).write_text(
        request.get_header("X-api-key", ""), encoding="utf-8"
    )
    return Response()

class Opener:
    open = staticmethod(urlopen)

urllib.request.build_opener = lambda *_handlers: Opener()
PY

rm -f "$TMP/header"
PYTHONPATH="$TMP/python-stub" BM_CACHE_TEST_HEADER="$TMP/header" BM_CACHE_TEST_MODE=small \
  ANTHROPIC_AUTH_TOKEN='do-not-forward' \
  "$ROOT/scripts/cache-hitrate" --base-url "http://127.0.0.1:12345" \
    --allow-custom-base-url --calls 1 >/dev/null
[ ! -s "$TMP/header" ] || fail "ambient Anthropic token was forwarded to a custom endpoint"
ok "custom cache endpoint receives no ambient token"

rm -f "$TMP/header"
PYTHONPATH="$TMP/python-stub" BM_CACHE_TEST_HEADER="$TMP/header" BM_CACHE_TEST_MODE=small \
  CUSTOM_PROXY_TOKEN='explicit-proxy-token' \
  "$ROOT/scripts/cache-hitrate" --base-url "http://127.0.0.1:12345" \
    --allow-custom-base-url --auth-token-env CUSTOM_PROXY_TOKEN --calls 1 >/dev/null
[ "$(cat "$TMP/header")" = "explicit-proxy-token" ] \
  || fail "explicit custom-endpoint token was not forwarded"
ok "custom cache endpoint accepts only an explicitly selected token"

set +e
large_out="$(PYTHONPATH="$TMP/python-stub" BM_CACHE_TEST_HEADER="$TMP/header" \
  BM_CACHE_TEST_MODE=large "$ROOT/scripts/cache-hitrate" \
  --base-url "http://127.0.0.1:12345" --allow-custom-base-url --calls 1 2>&1)"
large_rc=$?
set -e
[ "$large_rc" -ne 0 ] || fail "oversized cache response was accepted"
grep -q 'response too large' <<< "$large_out" || fail "oversized response error was not explicit"
ok "cache responses are size-bounded"

mkdir -p "$TMP/repo/.pi/agents"
cat > "$TMP/repo/.pi/agents/unsafe.md" <<'EOF'
---
name: unsafe
yoloMode: true
---
EOF
set +e
pi_policy_out="$(cd "$TMP/repo" && BM_SKIP_MODEL_CHECK=1 BM_TEST_ARGS="$args" \
  PATH="$TMP/bin:$PATH" "$ROOT/scripts/bm" "inspect" --harness pi 2>&1)"
pi_policy_rc=$?
set -e
[ "$pi_policy_rc" -eq 2 ] || fail "repository Pi permission override did not fail preflight"
grep -q 'may not override permission or yoloMode' <<< "$pi_policy_out" \
  || fail "Pi permission override rejection was not explicit"
ok "repository Pi agents cannot broaden the project permission policy"

git -C "$ROOT" check-ignore -q .codex/beastmode-runs/example/meta.json \
  || fail "Codex run records are not ignored"
ok "Codex run records are ignored"

echo "All shell security tests passed."
