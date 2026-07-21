#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat > "$TMP/bin/pi" <<'EOF'
#!/usr/bin/env bash
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
