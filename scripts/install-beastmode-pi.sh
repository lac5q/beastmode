#!/usr/bin/env bash
# install-beastmode-pi.sh — run on main-mac to bring it to parity with oracle-1.
#
# Self-contained: installs pi 0.80.x (the version pi-goal requires), the six
# beastmode-pi companion packages, and drops the skill at the user-global
# location so pi discovers it in every repo.
#
# Usage (from anywhere on main-mac):
#   curl -fsSL https://raw.githubusercontent.com/lac5q/beastmode/feature/beastmode-pi/scripts/install-beastmode-pi.sh | bash
# or locally:
#   bash scripts/install-beastmode-pi.sh
#
# Idempotent: safe to re-run. Re-runs are no-ops once everything is in place.

set -euo pipefail

bold() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; }

# 1. pi itself
bold "Install pi 0.80.x (requires >=0.80.6 for pi-goal)"
if command -v pi >/dev/null 2>&1; then
  v="$(pi --version 2>/dev/null || echo 0)"
  if [ "$v" != "$(printf '%s\n%s' "$v" 0.80.6 | sort -V | tail -n1)" ]; then
    warn "pi $v is too old; upgrading to @earendil-works/pi-coding-agent@latest"
    npm i -g @earendil-works/pi-coding-agent --force >/dev/null 2>&1
    ok "pi upgraded"
  else
    ok "pi $v already satisfies >=0.80.6"
  fi
else
  npm i -g @earendil-works/pi-coding-agent --force >/dev/null 2>&1
  ok "pi installed: $(pi --version)"
fi

# 2. six companion packages
bold "Install beastmode-pi companion packages"
for p in \
  npm:@narumitw/pi-goal \
  npm:@quintinshaw/pi-dynamic-workflows \
  npm:pi-loop-police \
  npm:@gotgenes/pi-permission-system \
  npm:@juicesharp/rpiv-todo \
  npm:@llblab/pi-telegram; do
  pi install "$p" >/dev/null 2>&1
  ok "installed $p"
done

# 3. skill at user-global location
bold "Install beastmode-pi skill"
SKILL_DIR="${HOME}/.agents/skills/beastmode-pi"
mkdir -p "$SKILL_DIR"

# Pull from the lac5q/beastmode repo at the feature branch. Falls back to a
# raw URL fetch if curl/wget can reach github.
URL="https://raw.githubusercontent.com/lac5q/beastmode/feature/beastmode-pi/pi/SKILL.md"
DEST="${SKILL_DIR}/SKILL.md"
if command -v curl >/dev/null 2>&1; then
  if curl -fsSL "$URL" -o "$DEST.tmp" 2>/dev/null; then
    mv "$DEST.tmp" "$DEST"
    ok "skill fetched from $URL"
  else
    warn "could not fetch skill from $URL; paste it manually into $DEST"
    warn "  (the skill ships in lac5q/beastmode/pi/SKILL.md on the feature/beastmode-pi branch)"
  fi
elif command -v wget >/dev/null 2>&1; then
  if wget -q "$URL" -O "$DEST.tmp" 2>/dev/null; then
    mv "$DEST.tmp" "$DEST"
    ok "skill fetched from $URL"
  else
    warn "could not fetch skill from $URL; paste it manually into $DEST"
  fi
else
  warn "no curl/wget available; paste the skill manually into $DEST"
fi

# 4. verify
bold "Verify"
pi -p "Do you have a skill called beastmode-pi available? Reply SKILL-OK or MISSING." 2>&1 | tail -1 | grep -q 'SKILL-OK' \
  && ok "skill discoverable" \
  || warn "skill NOT discoverable — check $DEST"

pi -p "Without calling any tools, list tool names starting with goal_ or workflow. One per line." 2>&1 | grep -cE '^(goal_|workflow)' \
  | xargs -I{} bash -c '[ {} -ge 3 ] && echo "  ✓ registered tools: {}" || echo "  ! only {} tool(s) registered"'

bold "Done. Try:"
echo "  pi --skill ~/.agents/skills/beastmode-pi/SKILL.md"
echo "  # or just start pi in any repo — skill auto-discovers"