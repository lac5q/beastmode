#!/usr/bin/env bash
# test-install-beastmode.sh — hermetic lifecycle test for the GSD-style
# installer (scripts/install-beastmode.sh) and the bm self-management verbs.
#
# Everything runs under a mktemp prefix with --runtimes '' so it never touches
# the real ~/.claude / ~/.local. Expected to leave the working tree unchanged.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALLER="scripts/install-beastmode.sh"
BM="$ROOT/scripts/bm"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "ok: $*"; }

PREFIX="$TEST_ROOT/prefix"

# 1. syntax
bash -n "$ROOT/$INSTALLER" || fail "installer syntax"
bash -n "$BM" || fail "bm syntax"
pass "syntax"

# 2. version command resolves the canonical package version.
rm -rf "$PREFIX"
VER="$("$ROOT/$INSTALLER" --prefix "$PREFIX" version)"
[ "$VER" = "2.4.0" ] || fail "version=$VER (expected 2.4.0)"
pass "version resolves to $VER"

# 3. fresh install.
"$ROOT/$INSTALLER" --prefix "$PREFIX" --runtimes '' install >/dev/null 2>&1 \
  || fail "install"
[ -L "$PREFIX/bin/bm" ] || fail "no bin/bm symlink"
[ -f "$PREFIX/share/beastmode/current/scripts/bm" ] \
  || fail "snapshot current/scripts/bm missing"
[ -f "$PREFIX/share/beastmode/manifest.json" ] || fail "no manifest"
pass "install created bin link + snapshot + manifest"

# 4. idempotent re-install is a no-op (same version, no --force).
OUT="$("$ROOT/$INSTALLER" --prefix "$PREFIX" --runtimes '' install)"
case "$OUT" in
  *"already installed and current"*) ;;
  *) fail "re-install not idempotent: $OUT" ;;
esac
pass "re-install is idempotent"

# 5. installed bm runs and resolves its sibling support tree.
# (bm prints usage and exits 2 on an empty invocation; capture that without
#  letting pipefail confuse the check.)
OUT="$( "$PREFIX/bin/bm" 2>&1 || true )"
case "$OUT" in
  *"beastmode runner"*) ;;
  *) fail "installed bm usage: $OUT" ;;
esac
[ "$( "$PREFIX/bin/bm" version )" = "2.4.0" ] || fail "installed bm version"
pass "installed bm resolves sibling files + self-management"

# 6. status reports the installed version. (Capture output rather than piping
#    to `grep -q`: under pipefail, grep -q's early exit SIGPIPEs the producer.)
STATUS_OUT="$( "$ROOT/$INSTALLER" --prefix "$PREFIX" status )"
case "$STATUS_OUT" in
  *"version    : 2.4.0"*) ;;
  *) fail "status missing version: $STATUS_OUT" ;;
esac
pass "status reports installed version"

# 7. upgrade re-points current to a new version and keeps the old snapshot.
"$ROOT/$INSTALLER" --prefix "$PREFIX" --runtimes '' --version 3.0.0 --force upgrade >/dev/null 2>&1 \
  || fail "upgrade"
[ -d "$PREFIX/share/beastmode/beastmode-2.4.0" ] || fail "old snapshot pruned too early"
[ -d "$PREFIX/share/beastmode/beastmode-3.0.0" ] || fail "new snapshot missing"
[ "$(readlink "$PREFIX/share/beastmode/current")" = "$PREFIX/share/beastmode/beastmode-3.0.0" ] \
  || fail "current not re-pointed"
pass "upgrade re-points current and keeps old snapshot"

# 8. no-op upgrade when already current.
OUT="$("$ROOT/$INSTALLER" --prefix "$PREFIX" --runtimes '' --version 3.0.0 upgrade)"
case "$OUT" in
  *"nothing to upgrade"*) ;;
  *) fail "upgrade not a no-op on current version: $OUT" ;;
esac
pass "upgrade is a no-op on the current version"

# 9. bm self-management verbs delegate correctly.
BM_STATUS="$( "$BM" status --prefix "$PREFIX" )"
case "$BM_STATUS" in
  *"version    : 3.0.0"*) ;;
  *) fail "bm status: $BM_STATUS" ;;
esac
pass "bm status delegates to installer"

# 10. uninstall removes every snapshot, the manifest, and the bin link.
"$BM" uninstall --prefix "$PREFIX" --yes >/dev/null 2>&1 || fail "uninstall"
[ -e "$PREFIX/share/beastmode/manifest.json" ] && fail "manifest survived uninstall"
[ -e "$PREFIX/share/beastmode/current" ] && fail "current survived uninstall"
find "$PREFIX" -name 'beastmode-*' | grep -q . && fail "a snapshot survived uninstall"
[ -L "$PREFIX/bin/bm" ] && fail "bin/bm survived uninstall"
pass "uninstall removes snapshots + manifest + bin link"

echo "install-beastmode: all checks passed"
