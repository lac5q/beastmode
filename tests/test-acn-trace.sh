#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/run"
SECRET="ghp_$(printf 'z%.0s' {1..24})"
cat > "$TMP/run/meta.json" <<JSON
{
  "id": "child-1",
  "requested_model": "minimax/MiniMax-M3",
  "actual_model": "minimax/MiniMax-M3",
  "stop_reason": "end_turn",
  "usage": {"input_tokens": 12, "output_tokens": 7},
  "files_changed": ["src/secret.py"],
  "commands_run": ["pytest"],
  "verify": {"passed": true}
}
JSON

set +e
DISABLED_OUT="$(LANGSMITH_TRACING=false "$ROOT/scripts/acn-trace" "$TMP/run" 2>&1)"
DISABLED_RC=$?
set -e
if [[ "$DISABLED_RC" -ne 0 || "$DISABLED_OUT" != *"disabled"* ]]; then
  echo "acn-trace did not cleanly skip when disabled: rc=$DISABLED_RC out=$DISABLED_OUT" >&2
  exit 1
fi

DRY_OUT="$(LANGSMITH_TRACING=true LANGSMITH_API_KEY="$SECRET" "$ROOT/scripts/acn-trace" "$TMP/run" \
  --dry-run --project beastmode-test --goal-id goal-1 --harness pi --autonomy medium)"
if [[ "$DRY_OUT" == *"$SECRET"* || "$DRY_OUT" == *"src/secret.py"* ]]; then
  echo "acn-trace dry-run exposed secret or source path" >&2
  exit 1
fi
printf '%s\n' "$DRY_OUT" | python3 -c 'import json, sys; p=json.load(sys.stdin); assert p["parent"]["name"] == "beastmode.run"; assert len(p["children"]) == 1; assert p["children"][0]["outputs"]["usage"]["input_tokens"] == 12'
echo "acn-trace is opt-in, sanitized, and dry-run verifiable"
