#!/usr/bin/env bash
# install-beastmode-pi.sh — install the Pi adapter and Beastmode skill on a workstation.
#
# Self-contained: installs a pinned Pi release, the six
# beastmode-pi companion packages, and drops the skill at the user-global
# location so pi discovers it in every repo.
#
# Usage (from anywhere on the workstation): download the installer and its
# SHA-256 file from the same immutable GitHub release, verify, then execute:
#   curl -fSLO https://github.com/lac5q/beastmode/releases/download/v2.4.0/install-beastmode-pi.sh
#   curl -fSLO https://github.com/lac5q/beastmode/releases/download/v2.4.0/install-beastmode-pi.sh.sha256
#   sha256sum --check install-beastmode-pi.sh.sha256
#   bash install-beastmode-pi.sh
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
declare -Ar NPM_INTEGRITIES=(
  ['@earendil-works/pi-coding-agent@0.83.0']='sha512-uYhF+FsZxogoSX/AxBcUdiY+ZklubwaXyAoEGA2eQwsHcyEAhUYIKh/WLXe/a8+k8eTCmxb+ZN2Zo9mzQtzbWw=='
  ['@narumitw/pi-goal@0.48.0']='sha512-IOvGEPvqCwuHCNN+hAAGG1B4IzlC8QUj/clPq3E3G5iRHdNip6nsqWnTFCBnLHEiNrMFJkJw0L14n4ugjSft1Q=='
  ['@quintinshaw/pi-dynamic-workflows@3.5.0']='sha512-B/uq11yAxDECfEVL4D/bmO84+Hf/+RrdNEB2z6bnpzkh5yF2zTZiIhuHtZ/Dh2a7EO95xBrjeCPsm220NnFnXg=='
  ['pi-loop-police@1.14.0']='sha512-ZJS39Kmt98pcQhCvG7lAGIBC1VrFAJOPCvtgq+f1O4ZJZ/GudQkAe671TEUuzXBzxoTD8qbAUfGJI17vYagVTQ=='
  ['@gotgenes/pi-permission-system@24.0.0']='sha512-4WncumJPPDDs8Ulrjk7qvU3kHjQSjGyZnpLx1Nu9EkxWQZQi+qvVOpGpPGbHwlXt6rg8AjvI8zSl2Aj2bo5lfA=='
  ['@juicesharp/rpiv-todo@2.4.0']='sha512-MJOsfwkLyNk33SStM/q6wOey+tDGEvc3pc/oQ+/MlZbj3Pc8MJeJa7hVrVX1RGCp62M9xr03rWcvhvZicuSf1Q=='
  ['@llblab/pi-telegram@0.27.0']='sha512-xIr5XiCOo0rHKAQWc9h+qreP7JjIvMz+4ewr5h7tbNwdip3okc1zj8m79VwHSXDnJiqi72ojqxtNIggB83n6CA=='
)
NPM_REGISTRY='https://registry.npmjs.org/'
export npm_config_registry="$NPM_REGISTRY"
export npm_config_ignore_scripts=true
export npm_config_audit=false
export npm_config_fund=false

# The default is a release tag, not a moving branch.  BEASTMODE_PI_REF may
# only be changed when the caller also accepts the integrity hashes below.
REF="${BEASTMODE_PI_REF:-v2.4.0}"
[[ "$REF" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || { err "BEASTMODE_PI_REF must be an immutable semantic-version release tag"; exit 2; }

verify_npm_package() {
  local spec="$1" expected actual
  expected="${NPM_INTEGRITIES[$spec]:-}"
  [ -n "$expected" ] || { err "no reviewed npm integrity for $spec"; return 1; }
  actual="$(npm view "$spec" dist.integrity --registry "$NPM_REGISTRY" 2>/dev/null)" \
    || { err "could not retrieve npm integrity for $spec"; return 1; }
  [ "$actual" = "$expected" ] \
    || { err "npm integrity mismatch for $spec"; return 1; }
}

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
verify_npm_package "$PI_PACKAGE" || exit 1
if command -v pi >/dev/null 2>&1; then
  v="$(pi --version 2>/dev/null || echo 0)"
  if [ "$v" != "$(printf '%s\n%s' "$v" 0.80.6 | sort -V | tail -n1)" ]; then
    warn "pi $v is too old; upgrading to $PI_PACKAGE"
    npm i -g "$PI_PACKAGE" --force --ignore-scripts --registry "$NPM_REGISTRY" >/dev/null 2>&1
    ok "pi upgraded"
  else
    ok "pi $v already satisfies >=0.80.6"
  fi
else
  npm i -g "$PI_PACKAGE" --force --ignore-scripts --registry "$NPM_REGISTRY" >/dev/null 2>&1
  ok "pi installed: $(pi --version)"
fi

# 2. six companion packages
bold "Install beastmode-pi companion packages"
for p in "${COMPANION_PACKAGES[@]}"; do
  verify_npm_package "${p#npm:}" || exit 1
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
fetch_pinned "$URL" "$DEST" "990b223ec53dbfd1df58c9a56bd89b3928c22ba5f2dff2c137d2445bc1d2ae73" \
  && ok "skill fetched and verified from $URL" \
  || { err "could not fetch or verify $URL"; exit 1; }

# 4. canonical project policy template
bold "Install fail-closed Pi permission policy template"
POLICY_DIR="${SKILL_DIR}/config"
mkdir -p "$POLICY_DIR"
POLICY_URL="https://raw.githubusercontent.com/lac5q/beastmode/${REF}/pi/config/pi-permission-system.json"
POLICY_DEST="${POLICY_DIR}/pi-permission-system.json"
fetch_pinned "$POLICY_URL" "$POLICY_DEST" "3d372bb505d2da0af466b6ced70175598c282b2c7c4825a449f68a45a2f15053" \
  && chmod 600 "$POLICY_DEST" \
  && ok "permission policy template fetched and verified" \
  || { err "could not fetch or verify $POLICY_URL"; exit 1; }

# 5. verify
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

# 6. runner CLI + its support files (next to bm so it can find both)
bold "Install bm runner + support files"
BM_DIR="${HOME}/.local/bin"
mkdir -p "$BM_DIR"
for f in bm tier-aliases.json phase-estimate claude-pro check-pi-agent-policy lib/prompts.sh; do
  URL="https://raw.githubusercontent.com/lac5q/beastmode/${REF}/scripts/${f}"
  DEST="${BM_DIR}/${f}"
  mkdir -p "$(dirname "$DEST")"
  case "$f" in
    bm) HASH="72431758b5f70d6959a5e316ed025300a9686e2340a606efe3a5f1b8bac69455" ;;
    tier-aliases.json) HASH="0d1496a649ae41da492a99dc56ba10b8f8e07c89417b6d459755d613637399e5" ;;
    phase-estimate) HASH="8ccadec0811cd8c326f697fd72ed73b766565bfbdc0e1253d89771eadab99d53" ;;
    claude-pro) HASH="68dadf141030bf3c3c6b00c332a5528582d2532e1d8aa06ed67fae66b364ef15" ;;
    check-pi-agent-policy) HASH="0173f561520831381738f955fb8fb2eda9c33ab2ecc4637f263a1ca579deac23" ;;
    lib/prompts.sh) HASH="577fb743016a9b9cf194cdd087e558fad01f887a9fadcc18560ce03ba2db4950" ;;
  esac
  if fetch_pinned "$URL" "$DEST" "$HASH"; then
    chmod +x "$DEST" 2>/dev/null || true
    ok "fetched and verified $f"
  else
    err "could not fetch or verify $f from $URL"
    exit 1
  fi
done

# 7. agentType marker for the Claude Pro lane (pi workflow subagent registry)
# Workflow scripts may write `agentType: "claude-cli"` to flag a slot as
# "Claude Pro work goes here, director invokes the lane directly." See
# pi/agents/claude-cli.md and pi/SKILL.md "Claude routing rule (hard rule)".
bold "Install Claude Pro lane agentType marker"
AGENT_DIR="${HOME}/.pi/agent/agents"
mkdir -p "$AGENT_DIR"
AGENT_URL="https://raw.githubusercontent.com/lac5q/beastmode/${REF}/pi/agents/claude-cli.md"
AGENT_DEST="${AGENT_DIR}/claude-cli.md"
fetch_pinned "$AGENT_URL" "$AGENT_DEST" "77a2f36eba09242090bca70c53bcc3cf1db455ca757f7fc4c2da89a2ae9d68bd" \
  && ok "fetched and verified claude-cli.md agentType marker" \
  || { err "could not fetch or verify $AGENT_URL"; exit 1; }

bold "Done. Try:"
echo "  pi --skill ~/.agents/skills/beastmode-pi/SKILL.md"
echo "  # or just start pi in any repo — skill auto-discovers"
echo "  install -Dm600 $POLICY_DEST .pi/extensions/pi-permission-system/config.json"
echo "  check-pi-agent-policy \"\$PWD\""
echo "  bm '<goal>' --frontier kimi3 --economy luna-max --on <remote-host> --autonomy medium"
echo "  claude-pro \"<prompt>\"   # Claude Pro lane (claude.ai subscription quota)"
