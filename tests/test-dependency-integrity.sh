#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="$ROOT/python/requirements-ci.lock"
WORKFLOW="$ROOT/.github/workflows/tests.yml"

fail() { echo "FAIL: $*" >&2; exit 1; }

[ -f "$LOCK" ] || fail "python hash lock is missing"
python3 - "$LOCK" <<'PY' || fail "every locked Python package must have an artifact hash"
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text)
packages = 0
for block in blocks:
    first = block.splitlines()[0].strip()
    if not re.match(r"^[A-Za-z0-9_.-]+==[^ ]+", first):
        continue
    packages += 1
    if "--hash=sha256:" not in block:
        raise SystemExit(f"missing hash: {first}")
if packages < 80:
    raise SystemExit(f"unexpectedly small lock: {packages} packages")
PY

rg -Fq 'pip install --require-hashes -r python/requirements-ci.lock' "$WORKFLOW" \
  || fail "CI does not enforce the Python hash lock"
rg -Fq 'python -m build --no-isolation python/' "$WORKFLOW" \
  || fail "CI build isolation could download unverified build requirements"
rg -Fq 'sudo apt-get install --yes ripgrep' "$WORKFLOW" \
  || fail "CI does not install the shell gate's ripgrep dependency"
rg -Fq 'kernel.apparmor_restrict_unprivileged_userns=0' "$WORKFLOW" \
  || fail "CI does not enable the Bubblewrap user namespace on restricted runners"
rg -Fq 'bwrap --ro-bind / / true' "$WORKFLOW" \
  || fail "CI does not verify Bubblewrap works before sandbox tests"
if rg -q 'pip install .*constraints-ci|PIP_CONSTRAINT=' "$WORKFLOW"; then
  fail "CI still has an unhashed constraints-only install path"
fi

echo "ok: Python CI dependencies and build tools are hash locked"
