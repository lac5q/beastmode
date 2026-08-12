#!/usr/bin/env bash
# install-beastmode.sh — GSD-style installer/upgrader for the Beastmode shell lane.
#
# One idempotent command to install, upgrade, or cleanly remove Beastmode on a
# workstation, mirroring the `npx get-shit-done-cc@latest` lifecycle:
#   - `install`   (default) — snapshot the current framework and link `bm`.
#   - `upgrade`   — re-snapshot (and with --source git, pull the newest release).
#   - `uninstall` — remove exactly what was installed, using the manifest.
#   - `status`    — report what is installed and where.
#   - `version`   — print the installed (or would-install) version.
#
# Instead of copying loose files and hoping they stay in sync, each install
# produces an immutable, versioned snapshot under a share dir and updates a
# `current` symlink pointing at the active snapshot. `bm` in PATH is a symlink
# into that snapshot. Upgrades write a new snapshot and atomically re-point
# `current`; uninstalls delete only the files recorded in the manifest. This
# keeps every release self-contained, makes rollback trivial (re-point one
# symlink), and makes uninstall clean by construction.
#
# Layout (--global, the default):
#   ~/.local/bin/bm                      -> ~/.local/share/beastmode/current/scripts/bm
#   ~/.local/share/beastmode/current     -> ~/.local/share/beastmode/beastmode-<ver>
#   ~/.local/share/beastmode/beastmode-<ver>/   (full runtime snapshot)
#   ~/.local/share/beastmode/manifest.json      (install ledger for clean uninstall)
#
# Flags:
#   --global          install user-wide under ~/.local (default)
#   --local           install under <cwd>/.beastmode (bin=.../.beastmode/bin)
#   --prefix DIR      override the base directory (tests; implies --global)
#   --runtimes X,Y,Z  also link the Beastmode skill into each runtime
#                     (claude|codex|cursor); default: claude if ~/.claude exists
#   --source repo|git source of the snapshot. repo = this checkout (default);
#                     git = latest GitHub release tarball
#   --version VER     pin the snapshot version (default: repo __version__)
#   --yes             non-interactive
#   --force           re-snapshot even if the version is already current
#   --keep N          versions to keep on upgrade (default 2)
#
# Exit codes: 0 success; 1 error; 2 usage error.

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve the repository / script origin exactly like scripts/bm does, so the
# installer works whether it is run from the checkout or via an installed link.
# ---------------------------------------------------------------------------
BM_SOURCE="${BASH_SOURCE[0]}"
while [ -h "$BM_SOURCE" ]; do
  BM_SOURCE_DIR="$(cd -P -- "$(dirname -- "$BM_SOURCE")" && pwd)"
  BM_SOURCE_LINK="$(readlink "$BM_SOURCE")"
  case "$BM_SOURCE_LINK" in
    /*) BM_SOURCE="$BM_SOURCE_LINK" ;;
    *) BM_SOURCE="$BM_SOURCE_DIR/$BM_SOURCE_LINK" ;;
  esac
done
INSTALLER_DIR="$(cd -P -- "$(dirname -- "$BM_SOURCE")" && pwd)"
REPO_ROOT="$(cd -P -- "$INSTALLER_DIR/.." && pwd)"

bold() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# Command + flag parsing (position-agnostic: flags and the command can appear
# in any order; the first non-flag token is the command, default `install`).
# ---------------------------------------------------------------------------
COMMAND=""
BASE=""
SCOPE="global"
RUNTIMES=""
RUNTIMES_SET=0
SOURCE="repo"
PINNED_VERSION=""
YES=0
FORCE=0
KEEP=2

while [ $# -gt 0 ]; do
  case "$1" in
    --global)        SCOPE="global"; shift ;;
    --local)         SCOPE="local"; shift ;;
    --prefix)        BASE="${2:-}"; [ -n "$BASE" ] || { echo "bm-install: --prefix needs a value" >&2; exit 2; }; shift 2 ;;
    --runtimes)      RUNTIMES="${2:-}"; RUNTIMES_SET=1; shift 2 ;;
    --source)        SOURCE="${2:-repo}"; shift 2 ;;
    --version)       PINNED_VERSION="${2:-}"; shift 2 ;;
    --yes)           YES=1; shift ;;
    --force)         FORCE=1; shift ;;
    --keep)          KEEP="${2:-2}"; shift 2 ;;
    -h|--help|--help=*|help) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    install|upgrade|uninstall|status|doctor|version)
      if [ -n "$COMMAND" ]; then
        echo "bm-install: unexpected extra command '$1'" >&2; exit 2
      fi
      COMMAND="$1"; shift ;;
    -*) echo "bm-install: unknown flag '$1'" >&2; exit 2 ;;
    *) echo "bm-install: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

# Default command is `install` when none was given.
[ -z "$COMMAND" ] && COMMAND="install"

case "$SOURCE" in
  repo|git) ;;
  *) echo "bm-install: --source must be repo or git" >&2; exit 2 ;;
esac
case "$SCOPE" in
  global|local) ;;
  *) echo "bm-install: --scope must be global or local" >&2; exit 2 ;;
esac
if [ -n "$BASE" ]; then
  BIN_DIR="$BASE/bin"
  SHARE_DIR="$BASE/share/beastmode"
elif [ "$SCOPE" = "local" ]; then
  BASE="$PWD/.beastmode"
  BIN_DIR="$BASE/bin"
  SHARE_DIR="$BASE/share/beastmode"
else
  BASE="$HOME/.local"
  BIN_DIR="$BASE/bin"
  SHARE_DIR="$BASE/share/beastmode"
fi
MANIFEST="$SHARE_DIR/manifest.json"

# ---------------------------------------------------------------------------
# Version resolution.
# ---------------------------------------------------------------------------
repo_version() {
  # Canonical version lives in python/src/beastmode/__init__.py.
  python3 - "$REPO_ROOT/python/src/beastmode/__init__.py" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
print(m.group(1) if m else "0.0.0")
PY
}

github_latest_version() {
  # Newest release tag from the public API (public repo, no auth needed).
  curl -fsSL "https://api.github.com/repos/lac5q/beastmode/releases/latest" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tag_name", "").lstrip("v"))' \
    2>/dev/null || true
}

newer_version() {
  # Portable, dependency-free version compare (no deprecated distutils).
  python3 - "$1" "$2" <<'PY'
import sys

def seg(v):
    for part in v.split('.'):
        while part and not part[0].isdigit():
            part = part[1:]
        digits = ''.join(c for c in part if c.isdigit())
        yield int(digits) if digits else 0

cur = list(seg(sys.argv[1]))
cand = list(seg(sys.argv[2]))
print(1 if cand > cur else 0)
PY
}

resolve_version() {
  if [ -n "$PINNED_VERSION" ]; then
    echo "$PINNED_VERSION"
  elif [ "$SOURCE" = "git" ]; then
    local v
    v="$(github_latest_version)"
    if [ -z "$v" ]; then
      err "could not discover the latest release; pass --version or use --source repo"
      exit 1
    fi
    echo "$v"
  else
    repo_version
  fi
}


# ---------------------------------------------------------------------------
# Snapshot + manifest + install.
# ---------------------------------------------------------------------------
runtime_skill_root() {
  case "$1" in
    claude) echo "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/beastmode" ;;
    codex)  echo "$HOME/.codex/skills/beastmode" ;;
    cursor) echo "$HOME/.cursor/skills/beastmode" ;;
    *)      echo "" ;;
  esac
}

snapshot_from_repo() {
  local dest="$1"
  mkdir -p "$dest"
  # `bm` resolves its own symlink, so its sibling files must live under the
  # snapshot's scripts/. Copy only the runtime-relevant tree. python sources
  # are vendored at python/src so the installer can resolve the canonical
  # version even from an installed (non-checkout) snapshot.
  for entry in scripts references schema adapters pi SKILL.md; do
    [ -e "$REPO_ROOT/$entry" ] && cp -R "$REPO_ROOT/$entry" "$dest/"
  done
  if [ -d "$REPO_ROOT/python/src" ]; then
    mkdir -p "$dest/python"
    cp -R "$REPO_ROOT/python/src" "$dest/python/"
  fi
  [ -f "$dest/scripts/bm" ] || { err "snapshot missing scripts/bm"; exit 1; }
}

snapshot_from_git() {
  local dest="$1" ver="$2" tmp extracted entry
  tmp="$(mktemp -d)"
  curl -fsSL "https://codeload.github.com/lac5q/beastmode/tar.gz/refs/tags/v${ver}" -o "$tmp/release.tgz"
  tar -xzf "$tmp/release.tgz" -C "$tmp"
  extracted="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
  extracted="${extracted:-$tmp}"
  mkdir -p "$dest"
  for entry in scripts references schema adapters pi SKILL.md; do
    [ -e "$extracted/$entry" ] && cp -R "$extracted/$entry" "$dest/"
  done
  if [ -d "$extracted/python/src" ]; then
    mkdir -p "$dest/python"
    cp -R "$extracted/python/src" "$dest/python/"
  fi
  [ -f "$dest/scripts/bm" ] || { err "release tarball missing scripts/bm"; rm -rf "$tmp"; exit 1; }
  rm -rf "$tmp"
}

json_quote() { printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))'; }

write_manifest() {
  local ver="$1" installed_at first=1 f
  installed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  {
    printf '{\n'
    printf '  "version": %s,\n' "$(json_quote "$ver")"
    printf '  "installed_at": %s,\n' "$(json_quote "$installed_at")"
    printf '  "source": %s,\n' "$(json_quote "$SOURCE")"
    printf '  "base": %s,\n' "$(json_quote "$BASE")"
    printf '  "files": [\n'
    for f in "$BIN_DIR/bm" "$SHARE_DIR/current" "$SHARE_DIR/beastmode-$ver"; do
      if [ -e "$f" ] || [ -L "$f" ]; then
        [ "$first" -eq 1 ] || printf ',\n'
        printf '    %s' "$(json_quote "$f")"
        first=0
      fi
    done
    if [ -n "$RUNTIMES" ]; then
      local rt link
      IFS=',' read -r -a _runtime_list <<<"$RUNTIMES"
      for rt in "${_runtime_list[@]}"; do
        link="$(runtime_skill_root "$rt")"
        if [ -n "$link" ] && { [ -e "$link" ] || [ -L "$link" ]; }; then
          [ "$first" -eq 1 ] || printf ',\n'
          printf '    %s' "$(json_quote "$link")"
          first=0
        fi
      done
    fi
    printf '\n  ]\n}\n'
  } > "$MANIFEST"
}

do_install() {
  local ver="$1" snapshot current tmp_link
  snapshot="$SHARE_DIR/beastmode-$ver"
  current="$SHARE_DIR/current"

  if [ "$FORCE" = "0" ] && [ -L "$current" ] \
     && [ "$(readlink "$current")" = "$snapshot" ] \
     && [ -d "$snapshot" ] && [ -f "$MANIFEST" ]; then
    ok "beastmode $ver already installed and current — nothing to do"
    return 0
  fi

  bold "Install beastmode $ver (source: $SOURCE)"
  mkdir -p "$SHARE_DIR" "$BIN_DIR"
  rm -rf "$snapshot"
  if [ "$SOURCE" = "git" ]; then
    snapshot_from_git "$snapshot" "$ver"
  else
    snapshot_from_repo "$snapshot"
  fi

  # Atomic re-point of `current` (portable: mv -T is GNU-only, fall back).
  tmp_link="$SHARE_DIR/.current.tmp.$$"
  ln -s "$snapshot" "$tmp_link"
  if mv -T "$tmp_link" "$current" 2>/dev/null; then :; else rm -f "$current"; mv "$tmp_link" "$current"; fi
  ok "snapshot installed at $snapshot"
  ok "current -> $(readlink "$current")"

  ln -sfn "$current/scripts/bm" "$BIN_DIR/bm"
  ok "bin link: $BIN_DIR/bm -> $current/scripts/bm"

  install_skill_links "$current"

  write_manifest "$ver"
  ok "manifest written: $MANIFEST"
}

install_skill_links() {
  local current="$1" rt root
  if [ "$RUNTIMES_SET" -eq 0 ] && [ -d "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" ]; then
    RUNTIMES="claude"
  fi
  [ -z "$RUNTIMES" ] && return 0
  IFS=',' read -r -a _runtime_list <<<"$RUNTIMES"
  for rt in "${_runtime_list[@]}"; do
    [ -z "$rt" ] && continue
    root="$(runtime_skill_root "$rt")"
    if [ -z "$root" ]; then
      warn "unknown runtime '$rt' — leaving its skill link alone"
      continue
    fi
    if [ -f "$current/SKILL.md" ]; then
      mkdir -p "$(dirname "$root")"
      ln -sfn "$current" "$root"
      ok "skill linked for $rt -> $current"
    fi
  done
}


# ---------------------------------------------------------------------------
# status / version / upgrade / uninstall.
# ---------------------------------------------------------------------------
cmd_version() {
  echo "$(resolve_version)"
}

cmd_status() {
  local installed="none" source_str="-" at="-" scopename
  if [ -L "$SHARE_DIR/current" ]; then
    local active
    active="$(readlink "$SHARE_DIR/current")"
    installed="${active##*beastmode-}"
  fi
  if [ -f "$MANIFEST" ]; then
    if ! source_str="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["source"])' "$MANIFEST" 2>/dev/null)"; then
      source_str="-"
    fi
    at="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["installed_at"])' "$MANIFEST" 2>/dev/null || echo '-')"
  fi
  if [ -n "$BASE" ]; then
    scopename="prefix '$BASE'"
  elif [ "$SCOPE" = "local" ]; then
    scopename="local ($PWD/.beastmode)"
  else
    scopename="global (~/.local)"
  fi
  echo "beastmode install: $scopename"
  echo "  version    : $installed"
  echo "  source     : $source_str"
  echo "  installed  : $at"
  echo "  share dir  : $SHARE_DIR"
  echo "  bin link   : $BIN_DIR/bm"
  if [ -L "$BIN_DIR/bm" ]; then
    echo "    -> $(readlink "$BIN_DIR/bm")"
  else
    echo "    (not linked)"
  fi
  if [ -f "$MANIFEST" ]; then
    local n
    n="$(python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["files"]))' "$MANIFEST" 2>/dev/null || echo 0)"
    echo "  tracked    : $n files (for clean uninstall)"
  fi
}

cmd_upgrade() {
  local ver
  ver="$(resolve_version)"
  if [ -f "$MANIFEST" ]; then
    local cur
    cur="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$MANIFEST" 2>/dev/null || echo '')"
    if [ -n "$cur" ] && [ "$(newer_version "$cur" "$ver")" = "0" ] && [ "$cur" = "$ver" ] && [ "$FORCE" = "0" ]; then
      bold "Already on beastmode $ver"
      ok "nothing to upgrade"
      return 0
    fi
  fi
  do_install "$ver"
  prune_old
}

prune_old() {
  local active keep=0 d
  active="$(readlink "$SHARE_DIR/current" 2>/dev/null || echo '')"
  for d in "$SHARE_DIR"/beastmode-*; do
    [ -d "$d" ] || continue
    if [ -n "$active" ] && [ "$(cd -P -- "$d" && pwd)" = "$(cd -P -- "$active" && pwd 2>/dev/null || echo "$d")" ]; then
      continue
    fi
    keep=$((keep + 1))
    if [ "$keep" -gt "$KEEP" ]; then
      ok "pruning old snapshot: $d"
      rm -rf "$d"
    fi
  done
}

cmd_uninstall() {
  if [ "$YES" = "0" ] && { [ -d "$SHARE_DIR" ] || [ -f "$MANIFEST" ]; }; then
    read -r -p "Remove beastmode installed under '$BASE'? [y/N] " ans
    case "$ans" in
      y|Y|yes|YES) ;;
      *) warn "aborted"; exit 0 ;;
    esac
  fi
  bold "Uninstall beastmode"
  # Links we own in PATH and per-runtime skill links recorded in the manifest.
  local f removed=0
  if [ -f "$MANIFEST" ]; then
    while IFS= read -r f; do
      if [ -L "$f" ] || [ -e "$f" ]; then
        rm -rf "$f" && ok "removed $f"
        removed=1
      fi
    done < <(python3 -c 'import json,sys
for f in json.load(open(sys.argv[1]))["files"]:
    print(f)' "$MANIFEST")
  fi
  # The share dir owns every snapshot, `current`, and the manifest. Removing it
  # cleans all versions at once (independent of how many upgrades happened).
  if [ -d "$SHARE_DIR" ]; then
    rm -rf "$SHARE_DIR"
    [ "$removed" = "1" ] || ok "removed $SHARE_DIR (all snapshots + manifest)"
  fi
  [ -L "$BIN_DIR/bm" ] && rm -f "$BIN_DIR/bm" && ok "removed $BIN_DIR/bm"
  ok "beastmode uninstalled"
}

cmd_doctor() {
  local problems=0
  bold "Beastmode doctor"
  if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found — required to run bm and the installer"
    problems=$((problems + 1))
  else
    ok "python3: $(command -v python3)"
  fi
  if [ -L "$BIN_DIR/bm" ]; then
    ok "bm linked: $BIN_DIR/bm -> $(readlink "$BIN_DIR/bm")"
    if [ -f "$(readlink "$BIN_DIR/bm")" ]; then
      ok "bm target exists"
    else
      err "bm symlink points at a missing file"
      problems=$((problems + 1))
    fi
  else
    warn "bm not linked — run 'bm install' (or install-beastmode.sh install)"
  fi
  if [ -d "$SHARE_DIR/current" ]; then
    ok "snapshot present: $(readlink "$SHARE_DIR/current")"
  elif [ -L "$SHARE_DIR/current" ]; then
    err "current symlink is dangling — re-run 'bm install' "
    problems=$((problems + 1))
  else
    warn "no snapshot installed yet"
  fi
  # Recommended but optional companion: the Pi adapter.
  if command -v pi >/dev/null 2>&1; then
    ok "pi (adapter): $(pi --version 2>/dev/null || echo 'present')"
  else
    warn "pi adapter not detected — install it with scripts/install-beastmode-pi.sh"
  fi
  if [ "$problems" -eq 0 ]; then
    ok "all clear"
  else
    err "$problems problem(s) found"
  fi
  return "$problems"
}

case "$COMMAND" in
  version)  cmd_version ;;
  status)   cmd_status ;;
  doctor)   cmd_doctor ;;
  upgrade)  cmd_upgrade ;;
  uninstall) cmd_uninstall ;;
  install)  do_install "$(resolve_version)" ;;
esac

