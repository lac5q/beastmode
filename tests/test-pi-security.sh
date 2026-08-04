#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POLICY="$ROOT/pi/config/pi-permission-system.json"
FAILURES=0

pass() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; FAILURES=$((FAILURES + 1)); }

assert_jq() {
  local expression="$1"
  local description="$2"
  if jq -e "$expression" "$POLICY" >/dev/null; then
    pass "$description"
  else
    fail "$description"
  fi
}

jq empty "$POLICY"
pass "Pi policy is valid JSON"

assert_jq '.yoloMode == false' "automatic approval is disabled"
assert_jq '.permissionReviewLog == true' "permission decisions are logged"
assert_jq '.doublePressToConfirm == true' "interactive approvals require confirmation"
assert_jq '.permission["*"] == "ask"' "unmatched tools ask by default"
assert_jq '.permission.bash["*"] == "ask"' "unmatched shell commands ask by default"
assert_jq '.permission.external_directory == "deny"' "outside-repository access is denied"
assert_jq '[.permission.bash["git push *"], .permission.bash["git commit *"], .permission.bash["rm -rf *"], .permission.bash["sudo *"], .permission.bash["gh release *"], .permission.bash["npm publish *"]] | all(. == "deny")' \
  "publish, commit, privilege, and destructive commands are denied"
assert_jq '[.permission.path["*.env"], .permission.path["**/.ssh/*"], .permission.path["**/*.pem"], .permission.path["**/credentials.json"]] | all(. == "deny")' \
  "representative secret paths are denied"

if rg -n --glob '*.md' -- 'dangerously-skip-permissions|bypassPermissions' "$ROOT/pi" >/dev/null; then
  fail "Pi documentation contains a permission-bypass instruction"
else
  pass "Pi documentation contains no permission-bypass instruction"
fi

if rg -n --glob '*.md' -- 'claude-pro|exec\(`' "$ROOT/pi" >/dev/null; then
  fail "Pi documentation references an unsafe wrapper or interpolated shell command"
else
  pass "Claude prompts are not routed through unsafe shell wrappers"
fi

if rg -F 'printf '\''%s'\'' "$prompt" | claude -p --model opus --permission-mode plan' \
  "$ROOT/pi/SKILL.md" "$ROOT/pi/agents/claude-cli.md" >/dev/null; then
  pass "Claude prompt data is supplied on stdin in plan mode"
else
  fail "Claude stdin/plan-mode example is missing"
fi

if rg -F 'qwen-agent --max-tool-calls 0' "$ROOT/pi/SKILL.md" >/dev/null; then
  pass "Qwen smoke gate cannot call tools"
else
  fail "Qwen smoke gate is not tool-disabled"
fi

for spec in \
  '@narumitw/pi-goal@0.43.0' \
  '@quintinshaw/pi-dynamic-workflows@3.5.0' \
  'pi-loop-police@1.14.0' \
  '@gotgenes/pi-permission-system@24.0.0' \
  '@juicesharp/rpiv-todo@2.3.1' \
  '@llblab/pi-telegram@0.27.0'; do
  for doc in "$ROOT/pi/SKILL.md" "$ROOT/pi/references/requirements.md"; do
    if rg -F "npm:$spec" "$doc" >/dev/null; then
      pass "extension pin present in ${doc#"$ROOT/"}: $spec"
    else
      fail "extension pin missing from ${doc#"$ROOT/"}: $spec"
    fi
  done
done

if rg -n 'pi install npm:[^[:space:]\\`]+([[:space:]\\`]|$)' \
  "$ROOT/pi/SKILL.md" "$ROOT/pi/references/requirements.md" \
  | rg -v 'npm:(@narumitw/pi-goal@0\.43\.0|@quintinshaw/pi-dynamic-workflows@3\.5\.0|pi-loop-police@1\.14\.0|@gotgenes/pi-permission-system@24\.0\.0|@juicesharp/rpiv-todo@2\.3\.1|@llblab/pi-telegram@0\.27\.0)' \
  >/dev/null; then
  fail "an unpinned Pi extension install remains"
else
  pass "all published Pi extension installs are pinned"
fi

if rg -U 'yoloMode: false\npermission:\n  "\*": deny' "$ROOT/pi/agents/claude-cli.md" >/dev/null; then
  pass "Claude marker is fail-closed"
else
  fail "Claude marker does not deny all tools"
fi

if (( FAILURES > 0 )); then
  printf '%s Pi security test(s) failed\n' "$FAILURES" >&2
  exit 1
fi

printf 'All Pi security tests passed\n'
