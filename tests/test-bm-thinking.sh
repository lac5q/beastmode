#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat > "$TMP/bin/pi" <<'EOF'
#!/usr/bin/env bash
# Mock pi: capture args, and report a minimal --list-models output that
# satisfies the model-availability preflight in bm.
if [ "$1" = "--list-models" ]; then
  cat <<TABLE
provider      model                                      context  max-out  thinking  images
openai-codex  gpt-5.6-sol                                200K     64K      yes       no
openai-codex  gpt-5.6-terra                              200K     64K      yes       no
openai-codex  gpt-5.6-luna                              1M       128K     yes       yes
vibeproxy     gpt-5.6-luna                              1M       128K     yes       yes
TABLE
  exit 0
fi
if [ "$1" = "list" ]; then
  printf '%s\n' '  npm:@gotgenes/pi-permission-system'
  exit 0
fi
printf '%s\n' "$@" > "$BM_TEST_ARGS"
EOF
chmod +x "$TMP/bin/pi"

BM_TEST_ARGS="$TMP/args" PATH="$TMP/bin:$PATH" \
  "$ROOT/scripts/bm" "validate the diff" --frontier sol --thinking medium

python3 - "$TMP/args" <<'PY'
from pathlib import Path
import sys
args = Path(sys.argv[1]).read_text().splitlines()

def value(flag):
    return args[args.index(flag) + 1]

assert value("--model") == "openai-codex/gpt-5.6-sol", args
assert value("--thinking") == "medium", args
PY

# The Claude lane maps --thinking onto the CLI's --effort. Regression guard:
# claude-pro used to accept only --model, so --thinking was silently dropped
# on every `--harness claude` run.
cat > "$TMP/bin/claude" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null            # prompt arrives on stdin; discard it
printf '%s\n' "$@" > "$BM_TEST_ARGS"
EOF
chmod +x "$TMP/bin/claude"

check_effort() {
  local thinking="$1" want="$2"
  BM_TEST_ARGS="$TMP/claude-args" PATH="$TMP/bin:$PATH" \
    "$ROOT/scripts/bm" "review the diff" --harness claude \
      --frontier sonnet5 --thinking "$thinking" >/dev/null
  python3 - "$TMP/claude-args" "$want" <<'PY'
from pathlib import Path
import sys
args = Path(sys.argv[1]).read_text().splitlines()
want = sys.argv[2]

def value(flag):
    return args[args.index(flag) + 1]

assert value("--model") == "claude-sonnet-5", args
assert value("--effort") == want, args
assert "--permission-mode" in args and value("--permission-mode") == "plan", args
PY
  echo "ok: --thinking $thinking -> claude --effort $want"
}

check_effort high high
check_effort max max
check_effort none low        # --effort has no sub-`low` step
check_effort minimal low
