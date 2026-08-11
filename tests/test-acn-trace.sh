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

HELP_OUT="$($ROOT/scripts/acn-trace --help)"
if [[ "$HELP_OUT" != *"--workspace-id"* ]]; then
  echo "acn-trace does not expose workspace-id configuration" >&2
  exit 1
fi

mkdir -p "$TMP/python-stub"
cat > "$TMP/python-stub/sitecustomize.py" <<'PY'
from pathlib import Path
import json
import os
import urllib.request

capture = Path(os.environ["BM_TRACE_HEADER_CAPTURE"])


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class Opener:
    def open(self, request, timeout=0):
        del timeout
        headers = {key.lower(): value for key, value in request.header_items()}
        with capture.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(headers, sort_keys=True) + "\n")
        return Response()


urllib.request.build_opener = lambda *_handlers: Opener()
PY

HEADER_CAPTURE="$TMP/trace-headers.jsonl"
PYTHONPATH="$TMP/python-stub" BM_TRACE_HEADER_CAPTURE="$HEADER_CAPTURE" \
  LANGSMITH_TRACING=true LANGSMITH_API_KEY="$SECRET" \
  "$ROOT/scripts/acn-trace" "$TMP/run" --project beastmode-test \
    --workspace-id workspace_123 >/dev/null
python3 - "$HEADER_CAPTURE" <<'PY'
import json
from pathlib import Path
import sys

rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
assert len(rows) == 2, rows
assert all(row.get("x-tenant-id") == "workspace_123" for row in rows), rows
PY

set +e
CUSTOM_OUT="$(LANGSMITH_TRACING=true LANGSMITH_API_KEY="$SECRET" \
  "$ROOT/scripts/acn-trace" "$TMP/run" --endpoint http://127.0.0.1:9 2>&1)"
CUSTOM_RC=$?
set -e
if [[ "$CUSTOM_RC" -ne 2 || "$CUSTOM_OUT" != *"--api-key-env"* || "$CUSTOM_OUT" == *"$SECRET"* ]]; then
  echo "acn-trace did not reject ambient credentials for a custom endpoint" >&2
  exit 1
fi
echo "acn-trace is opt-in, sanitized, and dry-run verifiable"
