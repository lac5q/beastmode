#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALLER="$ROOT/scripts/install-beastmode-pi.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

expected_hash() {
  local name="$1"
  sed -n "s/^[[:space:]]*${name}) HASH=\"\([0-9a-f]\{64\}\)\" ;;/\1/p" "$INSTALLER"
}

for name in bm claude-pro; do
  expected="$(expected_hash "$name")"
  [ -n "$expected" ] || fail "installer has no pinned hash for $name"
  actual="$(sha256sum "$ROOT/scripts/$name" | awk '{print $1}')"
  [ "$actual" = "$expected" ] \
    || fail "$name hash mismatch: installer=$expected actual=$actual"
  echo "ok: installer hash matches scripts/$name"
done
