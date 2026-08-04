#!/usr/bin/env bash

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
printf '#!/usr/bin/env bash\nexit 7\n' > "$TMP/bin/git"
chmod +x "$TMP/bin/git"

set +e
PATH="$TMP/bin:$PATH" "$ROOT/scripts/public-artifact-guard" >/dev/null 2>&1
rc=$?
set -e

if [ "$rc" -ne 2 ]; then
  echo "public-artifact-guard did not fail closed for scanner exit 7 (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard fails closed on scanner errors"
