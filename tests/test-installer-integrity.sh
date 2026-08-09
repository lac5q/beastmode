#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALLER="$ROOT/scripts/install-beastmode-pi.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

if rg -n 'raw\.githubusercontent\.com/.*/main/|curl[^|]*\|[[:space:]]*(ba)?sh' "$INSTALLER"; then
  fail "installer documentation must not execute moving-branch content"
fi
rg -Fq 'releases/download/v2.4.0/install-beastmode-pi.sh.sha256' "$INSTALLER" \
  || fail "installer documentation must require the immutable release checksum"
echo "ok: installer bootstrap is immutable and verified before execution"

expected_hash() {
  local name="$1"
  sed -n "s|^[[:space:]]*${name}) HASH=\"\([0-9a-f]\{64\}\)\" ;*|\1|p" "$INSTALLER"
}

for name in bm claude-pro check-pi-agent-policy lib/prompts.sh; do
  expected="$(expected_hash "$name")"
  [ -n "$expected" ] || fail "installer has no pinned hash for $name"
  actual="$(sha256sum "$ROOT/scripts/$name" | awk '{print $1}')"
  [ "$actual" = "$expected" ] \
    || fail "$name hash mismatch: installer=$expected actual=$actual"
  echo "ok: installer hash matches scripts/$name"
done

for path in \
  pi/SKILL.md \
  pi/agents/claude-cli.md \
  pi/config/pi-permission-system.json; do
  actual="$(sha256sum "$ROOT/$path" | awk '{print $1}')"
  rg -Fq "$actual" "$INSTALLER" \
    || fail "$path digest is not pinned by the installer"
  rg -Fq "/$path" "$INSTALLER" \
    || fail "$path release URL is not present in the installer"
  echo "ok: installer pins $path"
done

for spec in \
  '@earendil-works/pi-coding-agent@0.83.0' \
  '@narumitw/pi-goal@0.48.0' \
  '@quintinshaw/pi-dynamic-workflows@3.5.0' \
  'pi-loop-police@1.14.0' \
  '@gotgenes/pi-permission-system@24.0.0' \
  '@juicesharp/rpiv-todo@2.4.0' \
  '@llblab/pi-telegram@0.27.0'; do
  rg -Fq "['$spec']='sha512-" "$INSTALLER" \
    || fail "installer is missing repository-owned integrity for $spec"
  if [ "$spec" != '@earendil-works/pi-coding-agent@0.83.0' ]; then
    rg -Fq "npm:$spec" "$INSTALLER" \
      || fail "installer is missing exact package pin $spec"
  fi
done
rg -Fq 'npm_config_ignore_scripts=true' "$INSTALLER" \
  || fail "installer must disable npm lifecycle scripts"
rg -Fq 'actual="$(npm view "$spec" dist.integrity' "$INSTALLER" \
  || fail "installer must compare registry metadata to repository-owned integrity"
echo "ok: installer package pins and integrity values match the reviewed Pi stack"
