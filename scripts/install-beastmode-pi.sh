#!/usr/bin/env bash
# install-beastmode-pi.sh — install the Pi adapter and Beastmode skill on a workstation.
#
# Self-contained: installs pi 0.80.x (the version pi-goal requires), the six
# beastmode-pi companion packages, and drops the skill at the user-global
# location so pi discovers it in every repo.
#
# Usage (from anywhere on the workstation):
#   curl -fsSL https://raw.githubusercontent.com/lac5q/beastmode/main/scripts/install-beastmode-pi.sh | bash
# or locally:
#   bash scripts/install-beastmode-pi.sh
#
# Idempotent: safe to re-run. Re-runs are no-ops once everything is in place.

set -euo pipefail

bold() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; }

PI_PACKAGE='@earendil-works/pi-coding-agent@0.83.0'
COMPANION_PACKAGES=(
  'npm:@narumitw/pi-goal@0.48.0'
  'npm:@quintinshaw/pi-dynamic-workflows@3.5.0'
  'npm:pi-loop-police@1.14.0'
  'npm:@gotgenes/pi-permission-system@24.0.0'
  'npm:@juicesharp/rpiv-todo@2.4.0'
  'npm:@llblab/pi-telegram@0.27.0'
)

# The default is a release tag, not a moving branch.  BEASTMODE_PI_REF may
# only be changed when the caller also accepts the integrity hashes below.
REF="${BEASTMODE_PI_REF:-v2.4.0}"

fetch_pinned() {
  local url="$1" dest="$2" expected="$3" tmp actual
  tmp="$(mktemp "${dest}.tmp.XXXXXX")"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$tmp" || { rm -f "$tmp"; return 1; }
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$url" -O "$tmp" || { rm -f "$tmp"; return 1; }
  else
    rm -f "$tmp"
    return 1
  fi
  actual="$(sha256sum "$tmp" | awk '{print $1}')"
  if [ "$actual" != "$expected" ]; then
    err "integrity check failed for $url"
    rm -f "$tmp"
    return 1
  fi
  mv "$tmp" "$dest"
}

# 1. pi itself
bold "Install pi 0.80.x (requires >=0.80.6 for pi-goal)"
if command -v pi >/dev/null 2>&1; then
  v="$(pi --version 2>/dev/null || echo 0)"
  if [ "$v" != "$(printf '%s\n%s' "$v" 0.80.6 | sort -V | tail -n1)" ]; then
    warn "pi $v is too old; upgrading to $PI_PACKAGE"
    npm i -g "$PI_PACKAGE" --force >/dev/null 2>&1
    ok "pi upgraded"
  else
    ok "pi $v already satisfies >=0.80.6"
  fi
else
  npm i -g "$PI_PACKAGE" --force >/dev/null 2>&1
  ok "pi installed: $(pi --version)"
fi

# 2. six companion packages
bold "Install beastmode-pi companion packages"
for p in "${COMPANION_PACKAGES[@]}"; do
  pi install "$p" >/dev/null 2>&1
  ok "installed $p"
done

# 3. skill at user-global location
bold "Install beastmode-pi skill"
SKILL_DIR="${HOME}/.agents/skills/beastmode-pi"
mkdir -p "$SKILL_DIR"

# Pull from the immutable release ref and verify the downloaded bytes.
URL="https://raw.githubusercontent.com/lac5q/beastmode/${REF}/pi/SKILL.md"
DEST="${SKILL_DIR}/SKILL.md"
fetch_pinned "$URL" "$DEST" "24178afe3b90d38ac5369be321d64804e6c53cac5b89a8d3426af12fef9f512d" \
  && ok "skill fetched and verified from $URL" \
  || { err "could not fetch or verify $URL"; exit 1; }

# 4. verify
bold "Verify"
pi -p "Do you have a skill called beastmode-pi available? Reply SKILL-OK or MISSING." 2>&1 | tail -1 | grep -q 'SKILL-OK' \
  && ok "skill discoverable" \
  || warn "skill NOT discoverable — check $DEST"

pi -p "Without calling any tools, list tool names starting with goal_ or workflow. One per line." 2>&1 | grep -cE '^(goal_|workflow)' | {
  read -r n
  if [ "$n" -ge 3 ]; then ok "registered tools: $n"
  else warn "only $n tool(s) registered (expected >= 3)"
  fi
}

# 5. runner CLI + its support files (next to bm so it can find both)
bold "Install bm runner + support files"
BM_DIR="${HOME}/.local/bin"
mkdir -p "$BM_DIR"
for f in bm tier-aliases.json phase-estimate claude-pro; do
  URL="https://raw.githubusercontent.com/lac5q/beastmode/${REF}/scripts/${f}"
  DEST="${BM_DIR}/${f}"
  case "$f" in
    bm) HASH="86f0bbc3ac7e7274cbf00358db1bea4ce409861f566bad7ff9a95548e68753b8" ;;
    tier-aliases.json) HASH="f731437e1a6917ae8f21302c3e8d54cb2c82a9e937623993b031e935e12356b4" ;;
    phase-estimate) HASH="8ccadec0811cd8c326f697fd72ed73b766565bfbdc0e1253d89771eadab99d53" ;;
    claude-pro) HASH="de550548e30f0634c275a4d6f78acebddceb838a80b33cf5c369e0323c85bbda" ;;
  esac
  if fetch_pinned "$URL" "$DEST" "$HASH"; then
    chmod +x "$DEST" 2>/dev/null || true
    ok "fetched and verified $f"
  else
    err "could not fetch or verify $f from $URL"
    exit 1
  fi
done

# 6. agentType marker for the Claude Pro lane (pi workflow subagent registry)
# Workflow scripts may write `agentType: "claude-cli"` to flag a slot as
# "Claude Pro work goes here, director invokes the lane directly." See
# pi/agents/claude-cli.md and pi/SKILL.md "Claude routing rule (hard rule)".
bold "Install Claude Pro lane agentType marker"
AGENT_DIR="${HOME}/.pi/agent/agents"
mkdir -p "$AGENT_DIR"
AGENT_URL="https://raw.githubusercontent.com/lac5q/beastmode/${REF}/pi/agents/claude-cli.md"
AGENT_DEST="${AGENT_DIR}/claude-cli.md"
fetch_pinned "$AGENT_URL" "$AGENT_DEST" "2f606e5b21bdc7907ac9e4c47d58e6612897b8fc5a55cebd5bb1ef4b4d1d5537" \
  && ok "fetched and verified claude-cli.md agentType marker" \
  || { err "could not fetch or verify $AGENT_URL"; exit 1; }

bold "Done. Try:"
echo "  pi --skill ~/.agents/skills/beastmode-pi/SKILL.md"
echo "  # or just start pi in any repo — skill auto-discovers"
echo "  bm '<goal>' --frontier kimi3 --economy minimax --on <remote-host> --autonomy medium"
echo "  claude-pro \"<prompt>\"   # Claude Pro lane (claude.ai subscription quota)"
