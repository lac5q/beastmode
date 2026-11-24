#!/usr/bin/env bash
# bm relay: Fable gate, Opus fallback, agy provenance and Claude login scrub,
# all against stub `claude` and `agy` binaries (no network, no real models).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }

mkdir -p "$TMP/bin" "$TMP/userhome" "$TMP/ws"
cat > "$TMP/bin/claude" <<'SH'
#!/usr/bin/env bash
model=""; while [ $# -gt 0 ]; do case "$1" in --model) model="$2"; shift 2 ;; --) shift; prompt="$1"; break ;; *) shift ;; esac; done
echo "$model" >> "$FAKE_LOG"
echo "base=${ANTHROPIC_BASE_URL:-unset} key=${ANTHROPIC_API_KEY:-unset}" >> "$FAKE_LOG.env"
util="${FAKE_UTIL:-0.10}"
printf '{"type":"rate_limit_event","rate_limit_info":{"unifiedWindows":{"five_hour":{"utilization":0.01,"status":"allowed"},"seven_day":{"utilization":%s,"status":"allowed"}}}}\n' "$util"
if [ "$model" = "claude-fable-5-2" ] && [ -n "${FAKE_FABLE_LIMITED:-}" ] && [[ "$prompt" != *"single word ok"* ]]; then
  echo '{"type":"result","is_error":true,"result":"You have hit your Fable limit. Resets 5pm."}'; exit 1
fi
served="${FAKE_CLAUDE_SERVED:-$model}"
text="plan"; [[ "$prompt" == *"Review all the work"* ]] && text="${FAKE_VERDICT:-VERDICT: approve}"
printf '{"type":"result","is_error":false,"result":"%s","modelUsage":{"%s":{},"claude-haiku-5-5":{}}}\n' "$text" "$served"
SH
cat > "$TMP/bin/agy" <<'SH'
#!/usr/bin/env bash
model=""; settings=""; while [ $# -gt 0 ]; do case "$1" in --model) model="$2"; shift 2 ;; --settings) settings="$2"; shift 2 ;; *) shift ;; esac; done
{ echo "oauth=${CLAUDE_CODE_OAUTH_TOKEN:-unset}"; echo "other=${CLAUDE_CODE_OAUTH_X:-unset}"; echo "key=${ANTHROPIC_API_KEY:-unset}"; echo "other_env=${KEEP_ME:-unset}"; echo "settings=$settings"; } > "$FAKE_AGY_ENV"
if [ -n "${FAKE_AGY_EMPTY:-}" ]; then echo '{"conversation_id":"c1","status":"SUCCESS","response":""}'; exit 0; fi
echo improved > better.txt
d="$HOME/.gemini/antigravity-cli/brain/c1/.system_generated/logs"; mkdir -p "$d"
printf '{"model":"%s"}\n' "${FAKE_AGY_SERVED:-$model}" > "$d/transcript_full.jsonl"
echo '{"conversation_id":"c1","status":"SUCCESS","response":"made it better"}'
SH
chmod +x "$TMP/bin/claude" "$TMP/bin/agy"
git -C "$TMP/ws" init -q && git -C "$TMP/ws" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init

relay() {
  rm -f "$TMP/claude.log" "$TMP/claude.log.env"
  ( cd "$TMP/ws" && env -i PATH="$TMP/bin:/usr/bin:/bin" HOME="$TMP/userhome" FAKE_LOG="$TMP/claude.log" \
      FAKE_AGY_ENV="$TMP/agy-env.txt" CLAUDE_CODE_OAUTH_TOKEN=secret CLAUDE_CODE_OAUTH_X=secret3 \
      ANTHROPIC_API_KEY=apikey ANTHROPIC_BASE_URL=test-base-url KEEP_ME=yes "$@" \
      python3 "$ROOT/scripts/bm-relay" "fix it" --out "$TMP/run" ) >"$TMP/out.txt" 2>"$TMP/err.txt"
}
code() { set +e; relay "$@"; echo $?; set -e; }
state="$TMP/userhome/.beastmode/state"

# 1. No saved reading -> probe; 10% used -> Fable architects; full relay approves.
[ "$(code)" = 0 ] || { cat "$TMP/err.txt"; fail "relay did not approve"; }
[ "$(sed -n 2p "$TMP/claude.log")" = claude-fable-5-2 ] || fail "architect was not Fable"
[ "$(sed -n 3p "$TMP/claude.log")" = claude-opus-5-5 ] || fail "reviewer was not Opus"
grep -q '"effort": "medium"' "$TMP/run/03-reviewer/meta.json" || fail "reviewer not at medium effort"
grep -q 'better.txt' "$TMP/run/02-improver/changes.diff" || fail "improver diff not captured"
grep -q '"actual_model": "gemini-4-neon-xhigh"' "$TMP/run/02-improver/meta.json" || fail "agy provenance missing"
grep -qx 'oauth=unset' "$TMP/agy-env.txt" || fail "Claude login token reached agy"
grep -qx 'other=unset' "$TMP/agy-env.txt" || fail "CLAUDE_CODE_OAUTH* prefix not scrubbed for agy"
grep -qx 'key=unset' "$TMP/agy-env.txt" || fail "Anthropic API key reached agy"
grep -qx 'other_env=yes' "$TMP/agy-env.txt" || fail "unrelated env was dropped"
grep -q 'command(git diff)' "$TMP/agy-env.txt" || fail "agy not given the read-only command allow list"
! grep -v 'base=unset key=unset' "$TMP/claude.log.env" | grep -q . || fail "Anthropic API key or base URL reached claude -p"
grep -q '"served_models"' "$TMP/run/01-architect/meta.json" || fail "served_models not recorded"
ok "probe, Fable architect, Neon improver, Opus medium reviewer, envs scrubbed"

# 2. Fresh status line reading with 80% used -> Opus high, no probe.
rm -f "$state/fable-rate-limits.json"; rm -rf "$TMP/run"
echo '{"rate_limits":{"seven_day":{"used_percentage":80}}}' > "$state/claude-statusline.json"
( cd "$TMP/ws" && env -i PATH="$TMP/bin:/usr/bin:/bin" HOME="$TMP/userhome" FAKE_LOG="$TMP/claude.log" \
    python3 "$ROOT/scripts/bm-relay" x --dry-run ) > "$TMP/dry.txt" 2>/dev/null
grep -q '"claude-opus-5-5", "high"' "$TMP/dry.txt" || fail "below 25% did not pick Opus high"
ok "below the Fable floor -> Opus 5.5 high"

# 3. Stale reading is ignored (probe again: 10% used -> Fable).
touch -d '1 hour ago' "$state/claude-statusline.json"
( cd "$TMP/ws" && env -i PATH="$TMP/bin:/usr/bin:/bin" HOME="$TMP/userhome" FAKE_LOG="$TMP/claude.log" \
    python3 "$ROOT/scripts/bm-relay" x --dry-run ) > "$TMP/dry.txt" 2>/dev/null
grep -q '"claude-fable-5-2", "medium"' "$TMP/dry.txt" || fail "stale reading was trusted"
ok "stale reading ignored"

# 3b. Malformed reading counts as unknown -> probe (not a crash).
echo '[1,2]' > "$state/claude-statusline.json"; rm -f "$state/fable-rate-limits.json"
( cd "$TMP/ws" && env -i PATH="$TMP/bin:/usr/bin:/bin" HOME="$TMP/userhome" FAKE_LOG="$TMP/claude.log" \
    python3 "$ROOT/scripts/bm-relay" x --dry-run ) > "$TMP/dry.txt" 2>/dev/null || fail "malformed reading crashed"
echo '{"rate_limits":{"seven_day":{"used_percentage":null}}}' > "$state/claude-statusline.json"
( cd "$TMP/ws" && env -i PATH="$TMP/bin:/usr/bin:/bin" HOME="$TMP/userhome" FAKE_LOG="$TMP/claude.log" \
    python3 "$ROOT/scripts/bm-relay" x --dry-run ) > "$TMP/dry.txt" 2>/dev/null || fail "null percentage crashed"
ok "malformed readings fall back to a probe"

# 4. Fable rate-limited mid-run -> one retry on Opus high.
rm -f "$state"/*.json; rm -rf "$TMP/run"
[ "$(code FAKE_FABLE_LIMITED=1)" = 0 ] || fail "rate-limit fallback did not complete"
grep -q '"fallback_from": "claude-fable-5-2"' "$TMP/run/01-architect/meta.json" || fail "fallback not recorded"
grep -q '"requested_model": "claude-opus-5-5"' "$TMP/run/01-architect/meta.json" || fail "fallback model wrong"
ok "Fable rate limit -> Opus high retry, recorded"

# 5. Provenance and verdict failures.
rm -rf "$TMP/run"; [ "$(code FAKE_AGY_SERVED=gemini-3.8-flash-low)" = 3 ] || fail "agy drift passed"
rm -rf "$TMP/run"; [ "$(code FAKE_CLAUDE_SERVED=claude-sonnet-5-5)" = 3 ] || fail "claude drift passed"
rm -rf "$TMP/run"; [ "$(code FAKE_VERDICT='VERDICT: changes_needed')" = 1 ] || fail "changes_needed did not exit 1"
rm -rf "$TMP/run"; [ "$(code FAKE_AGY_EMPTY=1)" = 3 ] || fail "empty improver reply passed"
rm -rf "$TMP/run"; [ "$(code FAKE_VERDICT='looks fine')" = 3 ] || fail "unreadable verdict did not exit 3"
ok "model drift, empty improver, unreadable verdict exit 3; changes_needed exits 1"

echo "All bm relay tests passed."
