#!/usr/bin/env bash
# test-goal-lifecycle.sh — end-to-end pilot for the native goal lifecycle
# (schema/goal-lifecycle.json, scripts/lib/goal_lifecycle.py, scripts/bm-goal).
#
# Drives `bm goal` against a fake harness so every lifecycle claim in the
# roadmap is exercised without a model: durable identity, append-only events,
# fail-closed transitions, revision-bound approvals, restart-vs-resume
# honesty, cancellation cleanup verdicts, lost-supervisor reconciliation,
# fail-closed provenance/review, and the acceptance record.
#
# Run from repo root: ./tests/test-goal-lifecycle.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap '[ "${KEEP_TMP:-0}" = 1 ] || rm -rf "$TMP"' EXIT
touch "$TMP/started"

FAILS=0
PASSES=0
pass() { echo "PASS: $*"; PASSES=$((PASSES + 1)); }
fail() { echo "FAIL: $*"; FAILS=$((FAILS + 1)); }

BG="$ROOT/scripts/bm-goal"
export XDG_STATE_HOME="$TMP/state"
export PYTHONDONTWRITEBYTECODE=1

# A parent-held attestation key: the supervisor uses it to verify trusted
# evidence and must never hand it to the harness.
KEY="$(printf '2a%.0s' {1..32})"
export BEASTMODE_ATTESTATION_KEY="$KEY"
export BEASTMODE_ATTESTATION_RUN_ID="pilot-run"

# ---- target worktree ----
REPO="$TMP/repo"
git init -q "$REPO"
git -C "$REPO" -c user.email=t@example.invalid -c user.name=t commit -q --allow-empty -m seed
export FAKE_REPO="$REPO"

# ---- fake harness ----
# Behaviour is selected by FAKE_MODE: ok | gate | fail | hang | leakcheck.
FAKE="$TMP/fake-bm"
cat > "$FAKE" <<'EOF'
#!/usr/bin/env bash
set -u
echo "fake-bm: $* goal=$BM_GOAL_ID attempt=$BM_ATTEMPT_ID"
mkdir -p "$BM_RUN_DIR/control"
mode="${FAKE_MODE:-ok}"
case "$mode" in
  leakcheck)
    if [ -n "${BEASTMODE_ATTESTATION_KEY:-}" ]; then echo "LEAK: attestation key visible to harness"; exit 9; fi
    mode=ok ;;
  gate)
    if [ -f "$BM_RUN_DIR/control/decisions.json" ]; then
      echo "resumed with decisions: $(cat "$BM_RUN_DIR/control/decisions.json")"; mode=ok
    else
      printf '{"gate":"plan","phase":"design","question":"approve plan?","options":["approved","rejected"],"recommended":"approved"}' > "$BM_RUN_DIR/control/gate.json"
      exit 0
    fi ;;
  fail) exit 1 ;;
  hang) sleep 300; exit 0 ;;
esac
mkdir -p "$BM_RUN_DIR/w1" "$BM_RUN_DIR/watcher"
for c in w1 watcher; do
  printf '{"id":"%s","requested_model":"openai/x","actual_model":"%s","stop_reason":"end_turn","usage":{"input_tokens":10,"output_tokens":5},"files_changed":[],"commands_run":[],"verify":{"passed":true}}' \
    "$c" "${FAKE_ACTUAL:-openai/x}" > "$BM_RUN_DIR/$c/meta.json"
done
if [ -n "${FAKE_ATTEST_DIR:-}" ]; then
  python3 "$FAKE_ATTEST_PY" "$BM_RUN_DIR" "$FAKE_ATTEST_DIR"
fi
if [ "${FAKE_REVIEW:-yes}" = yes ]; then
  rev="$(git -C "$FAKE_REPO" rev-parse HEAD)"
  [ "${FAKE_REVIEW_STALE:-0}" = 1 ] && rev="0000000000000000000000000000000000000000"
  printf '{"goal_id":"%s","attempt_id":"%s","revision":"%s","reviewer_id":"watcher","approved":true,"summary":"ok"}' \
    "$BM_GOAL_ID" "$BM_ATTEMPT_ID" "$rev" > "$BM_RUN_DIR/control/review.json"
fi
exit 0
EOF
chmod +x "$FAKE"
export BM_GOAL_HARNESS_BIN="$FAKE"

# Trusted attestor stand-in: signs the receipts with the parent key. It runs
# inside the fake harness only for the test; in production the harness journal
# or provider produces attestations and the parent signs them.
cat > "$TMP/attest.py" <<EOF
import hashlib, json, os, sys
sys.path.insert(0, "$ROOT/scripts/lib")
import acn_meta
run_dir, out_dir = sys.argv[1], sys.argv[2]
key = bytes.fromhex("$KEY"); run_id = "pilot-run"
records = []
for child in ("w1", "watcher"):
    p = os.path.join(run_dir, child, "meta.json")
    rec = {"id": child, "requested_model": "openai/x", "actual_model": os.environ.get("FAKE_ATTEST_ACTUAL", "openai/x"),
           "source": "pilot-journal", "run_id": run_id, "result_digest": hashlib.sha256(open(p, "rb").read()).hexdigest()}
    rec["signature"] = acn_meta.sign_attestation(rec, key)
    records.append(rec)
os.makedirs(out_dir, exist_ok=True); os.chmod(out_dir, 0o700)
with open(os.path.join(out_dir, "att.json"), "w") as f:
    json.dump({"attestations": records}, f)
os.chmod(os.path.join(out_dir, "att.json"), 0o600)
EOF
export FAKE_ATTEST_PY="$TMP/attest.py"

run_goal() { # run_goal <goal-id> [args...]  -> stdout captured, rc in $RC
  local id="$1"; shift
  OUT="$("$BG" run "goal $id" --goal-id "$id" --repo "$REPO" "$@" 2>&1)"; RC=$?
}
state_of() { "$BG" inspect "$1" --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["state"], d.get("outcome") or "-")'; }

cd "$REPO"

# ---- (a) contract + capabilities ----
echo "check (a): contract and capability matrix"
if python3 -m json.tool "$ROOT/schema/goal-lifecycle.json" >/dev/null \
   && "$BG" capabilities | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert d["version"]=="1.0"
assert d["capabilities"]["langgraph"]["resume"]=="checkpoint"
assert all(d["capabilities"][h]["resume"]=="prompt_continuation" for h in ("pi","hermes","claude","codex"))
assert d["transitions"]["succeeded"]==[] and d["transitions"]["cancelled"]==[]
assert set(d["exit_codes"])=={"0","1","2","3","4","5","6","7"}
'; then pass "GL0 contract loads; shell harnesses never claim checkpoint resume"; else fail "GL0 contract/capabilities"; fi

# ---- (b) fail-closed provenance: worker receipts alone never complete ----
echo "check (b): no attestation -> provenance_failed"
FAKE_MODE=ok run_goal g-noattest --verify-cmd true
if [ "$RC" = 1 ] && [ "$(state_of g-noattest)" = "failed provenance_failed" ]; then
  pass "worker-authored receipts are UNVERIFIABLE; goal fails closed (exit 1)"
else fail "no-attestation run: rc=$RC state=$(state_of g-noattest) out=$OUT"; fi

# ---- (c) happy path: verify + provenance ok + bound watcher review ----
echo "check (c): acceptance record"
FAKE_MODE=leakcheck FAKE_ATTEST_DIR="$TMP/att-ok" run_goal g-ok --verify-cmd true --attestations "$TMP/att-ok"
if [ "$RC" = 0 ] && "$BG" inspect g-ok --json | python3 -c '
import json,sys,subprocess
d=json.load(sys.stdin)
c=d["completion"]
assert d["state"]=="succeeded" and c["outcome"]=="succeeded"
assert c["goal_id"]=="g-ok" and c["attempt_id"]=="a1" and c["contract_digest"]==d["contract_digest"]
assert c["provenance"]["verdict"]=="ok" and c["review"]["approved"] and c["validation"]["passed"]
head=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
assert c["revision"]["head"]==head, (c["revision"], head)
assert d["budget"]["used"]["tokens"]==30
seqs=[e["seq"] for e in d["events"]]
assert seqs==list(range(1,len(seqs)+1)), seqs
assert "merge" not in c["outcome"]
'; then pass "GL4 completion binds goal+attempt+revision+digest; key not leaked to harness; events sequenced"; else fail "happy path: rc=$RC out=$OUT"; fi

# ---- (d) drift is a failure ----
echo "check (d): model drift"
FAKE_MODE=ok FAKE_ACTUAL=openai/other FAKE_ATTEST_ACTUAL=openai/other FAKE_ATTEST_DIR="$TMP/att-drift" run_goal g-drift --attestations "$TMP/att-drift"
if [ "$RC" = 1 ] && [ "$(state_of g-drift)" = "failed provenance_failed" ] && "$BG" inspect g-drift --json | python3 -c '
import json,sys; d=json.load(sys.stdin); a=d["attempt_records"][-1]["acceptance"]; assert a["provenance"]["verdict"]=="drift" and d["completion"] is None, a["provenance"]'; then
  pass "MODEL DRIFT blocks completion"; else fail "drift: rc=$RC state=$(state_of g-drift)"; fi

# ---- (e) review must bind the final revision ----
echo "check (e): stale watcher review"
FAKE_MODE=ok FAKE_REVIEW_STALE=1 FAKE_ATTEST_DIR="$TMP/att-stale" run_goal g-stalereview --attestations "$TMP/att-stale"
FAKE_MODE=ok FAKE_REVIEW=no FAKE_ATTEST_DIR="$TMP/att-norev" run_goal g-noreview --attestations "$TMP/att-norev"
if [ "$RC" = 1 ] && [ "$(state_of g-stalereview)" = "blocked review_missing" ] && [ "$(state_of g-noreview)" = "blocked review_missing" ] \
   && "$BG" inspect g-stalereview --json | python3 -c '
import json,sys; d=json.load(sys.stdin); a=d["attempt_records"][-1]["acceptance"]
assert a["provenance"]["verdict"]=="ok" and a["validation"]["passed"] and not a["review"]["approved"] and "revision" in a["review"]["reason"], a["review"]'; then
  pass "no watcher / unbound revision -> blocked review_missing (no watcher, no validated); exit 1"
else fail "review binding: stale=$(state_of g-stalereview) none=$(state_of g-noreview)"; fi

# ---- (f) gate -> approve -> resume, with stable goal id and new attempt ----
echo "check (f): durable approval boundary"
FAKE_MODE=gate FAKE_ATTEST_DIR="$TMP/att-gate" run_goal g-gate --attestations "$TMP/att-gate" --max-attempts 3
rc_gate=$RC
"$BG" resume g-gate >/dev/null 2>&1; rc_resume_early=$?
"$BG" approve g-gate --answer scope=narrow >/dev/null 2>&1; rc_approve=$?
"$BG" approve g-gate >/dev/null 2>&1; rc_double=$?
FAKE_MODE=gate FAKE_ATTEST_DIR="$TMP/att-gate" "$BG" resume g-gate >/dev/null 2>&1; rc_resume=$?
if [ "$rc_gate" = 4 ] && [ "$rc_resume_early" = 7 ] && [ "$rc_approve" = 0 ] && [ "$rc_double" = 7 ] && [ "$rc_resume" = 0 ] \
   && "$BG" inspect g-gate --json | python3 -c '
import json,sys; d=json.load(sys.stdin)
assert d["state"]=="succeeded" and d["attempts"]==["a1","a2"] and d["current_attempt"]=="a2"
assert d["decisions"][0]["id"]=="d1" and d["decisions"][0]["approved"] is True
assert d["decisions"][0]["attempt_id"]=="a1" and d["decisions"][0]["answers"]=={"scope":"narrow"}
assert [e["type"] for e in d["events"] if e["type"]=="decision"]==["decision"]
assert any(e["to"]=="awaiting_approval" for e in d["events"])
assert d["attempt_records"][1]["resume_mode"]=="prompt_continuation"
'; then pass "GL2 gate exit 4; approve once (7 on repeat); resume replays decision as prompt_continuation in a2"
else fail "gate flow: gate=$rc_gate early=$rc_resume_early approve=$rc_approve double=$rc_double resume=$rc_resume"; echo "$OUT" | tail -20; fi

# ---- (g) stale approval after the worktree moved ----
echo "check (g): stale approval"
FAKE_MODE=gate FAKE_ATTEST_DIR="$TMP/att-stalea" run_goal g-stale --attestations "$TMP/att-stalea" --max-attempts 3
"$BG" approve g-stale >/dev/null 2>&1
git -C "$REPO" -c user.email=t@example.invalid -c user.name=t commit -q --allow-empty -m move
FAKE_MODE=gate FAKE_ATTEST_DIR="$TMP/att-stalea" "$BG" resume g-stale >/dev/null 2>&1; rc_stale=$?
if [ "$rc_stale" = 7 ] && [ "$(state_of g-stale)" = "awaiting_approval awaiting_approval" ]; then
  pass "approval bound to revision is refused after HEAD moved (exit 7, still awaiting)"
else fail "stale approval: rc=$rc_stale state=$(state_of g-stale)"; fi

# ---- (h) reject ----
echo "check (h): reject"
FAKE_MODE=gate run_goal g-reject
"$BG" reject g-reject --reason nope >/dev/null 2>&1; rc_rej=$?
if [ "$rc_rej" = 0 ] && [ "$(state_of g-reject)" = "failed rejected" ]; then pass "reject records decision and fails the goal"; else fail "reject: rc=$rc_rej state=$(state_of g-reject)"; fi

# ---- (i) restart is not resume ----
echo "check (i): failed harness, restart honesty, attempt budget"
FAKE_MODE=fail run_goal g-fail --max-attempts 2
rc_fail=$RC
FAKE_MODE=fail "$BG" resume g-fail >/dev/null 2>&1; rc_plain=$?
FAKE_MODE=fail "$BG" resume g-fail --restart >/dev/null 2>&1; rc_restart=$?
FAKE_MODE=fail "$BG" resume g-fail --restart --acknowledge-partial-effects >/dev/null 2>&1; rc_ack=$?
FAKE_MODE=fail "$BG" resume g-fail --restart --acknowledge-partial-effects >/dev/null 2>&1; rc_budget=$?
if [ "$rc_fail" = 1 ] && [ "$rc_plain" = 7 ] && [ "$rc_restart" = 7 ] && [ "$rc_ack" = 1 ] && [ "$rc_budget" = 7 ] \
   && "$BG" inspect g-fail --json | python3 -c '
import json,sys; d=json.load(sys.stdin)
assert d["attempts"]==["a1","a2"], d["attempts"]
assert d["attempt_records"][1]["resume_mode"]=="restart"
assert d["budget"]["used"]["attempts"]==2
'; then pass "GL3 restart requires --restart + partial-effects ack, labelled restart; attempt budget enforced"
else fail "restart: fail=$rc_fail plain=$rc_plain restart=$rc_restart ack=$rc_ack budget=$rc_budget"; fi

# ---- (j) cancel a running goal ----
echo "check (j): cancel"
( FAKE_MODE=hang "$BG" run "goal g-cancel" --goal-id g-cancel --repo "$REPO" --stall-seconds 60 >/dev/null 2>&1; echo $? > "$TMP/cancel-run-rc" ) &
for _ in $(seq 1 50); do [ "$(state_of g-cancel 2>/dev/null)" = "running -" ] && break; sleep 0.1; done
"$BG" cancel g-cancel --grace-seconds 1 >"$TMP/cancel-out" 2>&1; rc_cancel=$?
wait
if [ "$rc_cancel" = 0 ] && [ "$(cat "$TMP/cancel-run-rc")" = 5 ] && [ "$(state_of g-cancel)" = "cancelled cancelled" ] \
   && grep -q "cleanup: confirmed" "$TMP/cancel-out" && ! pgrep -f "sleep 300" >/dev/null; then
  pass "cancel: supervisor exits 5, process group gone, cleanup=confirmed recorded"
else fail "cancel: rc=$rc_cancel run_rc=$(cat "$TMP/cancel-run-rc") state=$(state_of g-cancel) out=$(cat "$TMP/cancel-out")"; pkill -f "sleep 300" 2>/dev/null; fi

# ---- (k) stall detection ----
echo "check (k): stall budget"
FAKE_MODE=hang run_goal g-stall --stall-seconds 2
if [ "$RC" = 1 ] && [ "$(state_of g-stall)" = "failed stalled" ]; then pass "stalled harness is killed and recorded"; else fail "stall: rc=$RC state=$(state_of g-stall)"; fi

# ---- (l) lost supervisor -> reconcile ----
echo "check (l): reconcile"
FAKE_MODE=hang "$BG" run "goal g-lost" --goal-id g-lost --repo "$REPO" --stall-seconds 60 >/dev/null 2>&1 &
SUP=$!
for _ in $(seq 1 50); do [ "$(state_of g-lost 2>/dev/null)" = "running -" ] && break; sleep 0.1; done
kill -9 "$SUP"; wait "$SUP" 2>/dev/null
runs_out="$("$BG" runs)"
rec_out="$("$BG" reconcile)"; rc_rec=$?
sleep 0.3
if [ "$rc_rec" = 0 ] && echo "$runs_out" | grep -q "supervisor lost" && [ "$(state_of g-lost)" = "failed supervisor_lost" ] \
   && echo "$rec_out" | grep -q '"harness_was_running": true' && echo "$rec_out" | grep -q '"cleanup": "confirmed"' \
   && ! pgrep -f "sleep 300" >/dev/null; then
  pass "GL3 reconcile: lost supervisor detected, orphan harness stopped, effects recorded"
else fail "reconcile: rc=$rc_rec state=$(state_of g-lost) runs=$runs_out rec=$rec_out"; pkill -f "sleep 300" 2>/dev/null; fi

# ---- (m) terminal states are immutable; repo lock ----
echo "check (m): illegal transitions and repository lock"
"$BG" approve g-ok >/dev/null 2>&1; rc_a=$?
"$BG" pause g-ok >/dev/null 2>&1; rc_p=$?
"$BG" cancel g-ok >/dev/null 2>&1; rc_c=$?
run_goal g-ok --queue-only; rc_dup=$RC
if [ "$rc_a" = 7 ] && [ "$rc_p" = 7 ] && [ "$rc_c" = 7 ] && [ "$rc_dup" = 7 ]; then pass "succeeded goal refuses approve/pause/cancel; duplicate id refused (exit 7)"; else fail "terminal: a=$rc_a p=$rc_p c=$rc_c dup=$rc_dup"; fi

# ---- (n) queue / pause / schedule ----
echo "check (n): GL5 scheduling export"
run_goal g-later --queue-only
"$BG" pause g-later >/dev/null 2>&1
cron="$("$BG" schedule g-later --every 7200 --export cron 2>&1 | tail -1)"; rc_cron=${PIPESTATUS[0]}
plist="$(TZ=UTC "$BG" schedule g-later --at 2030-01-02T03:04:00Z --export launchd 2>&1)"; rc_pl=$?
"$BG" schedule g-ok --every 3600 >/dev/null 2>&1; rc_sched_done=$?
# A recurring schedule starts a fresh goal per occurrence; the same occurrence twice is a duplicate.
FAKE_ATTEST_DIR="$TMP/att-occ" "$BG" run --from-template g-later --occurrence 20300102T0304 --queue-only >/dev/null 2>&1; rc_occ=$?
"$BG" run --from-template g-later --occurrence 20300102T0304 --queue-only >/dev/null 2>&1; rc_dup=$?
if [ "$rc_cron" = 0 ] && [ "$rc_pl" = 0 ] && [ "$rc_sched_done" = 7 ] \
   && [[ "$cron" == "0 */2 * * * "*"bm-goal run --from-template g-later --occurrence "* ]] \
   && echo "$plist" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["Label"]=="ai.beastmode.goal.g-later"; assert d["StartCalendarInterval"]=={"Month":1,"Day":2,"Hour":3,"Minute":4}; assert d["ProgramArguments"][1:]==["resume","g-later"]' \
   && [ "$(state_of g-later)" = "paused -" ] && [ "$rc_occ" = 0 ] && [ "$rc_dup" = 7 ] \
   && [ "$(state_of g-later-20300102T0304)" = "queued -" ]; then
  pass "schedule exports cron/launchd that only invoke bm-goal; occurrences are fresh goals, duplicates and terminal goals refused"
else fail "schedule: cron=$rc_cron ($cron) launchd=$rc_pl done=$rc_sched_done occ=$rc_occ dup=$rc_dup"; fi

# ---- (n2) GL5 notifications: delivered once, failures visible, never change the verdict ----
echo "check (n2): notifications"
NOTIFY_SINK="$TMP/notify.jsonl"
cat > "$TMP/notify-ok" <<EOF
#!/usr/bin/env bash
cat >> "$NOTIFY_SINK"; echo >> "$NOTIFY_SINK"
EOF
chmod +x "$TMP/notify-ok"
FAKE_ATTEST_DIR="$TMP/att-notify" run_goal g-notify --attestations "$TMP/att-notify" --notify-cmd "$TMP/notify-ok"; rc_notify_ok=$RC
FAKE_ATTEST_DIR="$TMP/att-notify2" run_goal g-notify-fail --attestations "$TMP/att-notify2" --notify-cmd "/bin/false"; rc_notify_fail=$RC
if [ "$rc_notify_ok" = 0 ] && [ "$rc_notify_fail" = 0 ] && [ "$(wc -l < "$NOTIFY_SINK")" = 1 ] \
   && python3 -c '
import json,sys; p=json.loads(open(sys.argv[1]).read().strip())
assert p["notification_id"]=="g-notify:a1:succeeded" and p["state"]=="succeeded" and "approve" not in p' "$NOTIFY_SINK" \
   && "$BG" inspect g-notify --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert [e["type"] for e in d["events"]].count("notified")==1' \
   && "$BG" inspect g-notify-fail --json | python3 -c '
import json,sys; d=json.load(sys.stdin); e=[e for e in d["events"] if e["type"]=="notification_failed"]
assert len(e)==1 and e[0]["data"]["retries"]==3 and d["state"]=="succeeded", e'; then
  pass "notification delivered once with an event id; failed delivery is a visible event and leaves the verdict alone"
else fail "notifications: ok=$rc_notify_ok fail=$rc_notify_fail sink=$(cat "$NOTIFY_SINK" 2>/dev/null)"; fi

# ---- (o) remote dispatch unsupported; usage errors ----
echo "check (o): unsupported and usage exit codes"
run_goal g-remote --on remote --queue-only; rc_remote=$RC
"$BG" run >/dev/null 2>&1; rc_usage=$?
"$BG" inspect nope-nope >/dev/null 2>&1; rc_missing=$?
"$BG" frobnicate >/dev/null 2>&1; rc_cmd=$?
if [ "$rc_remote" = 6 ] && [ "$rc_usage" = 2 ] && [ "$rc_missing" = 2 ] && [ "$rc_cmd" = 2 ]; then pass "remote=6, usage/unknown goal/unknown verb=2"; else fail "codes: remote=$rc_remote usage=$rc_usage missing=$rc_missing cmd=$rc_cmd"; fi

# ---- (p) logs + runs ----
echo "check (p): logs and runs"
if "$BG" logs g-gate --attempt a2 --tail 50 | grep -q "resumed with decisions" && "$BG" runs --state succeeded | grep -q "^g-gate " \
   && "$BG" runs --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert all("goal_id" in g and "state" in g for g in d)'; then
  pass "GL1 logs/runs read the durable record"; else fail "logs/runs"; fi

# ---- (q) `bm goal` dispatch and prompt hook ----
echo "check (q): bm dispatch"
if "$ROOT/scripts/bm" goal capabilities | grep -q '"version": "1.0"' \
   && bash -c ". '$ROOT/scripts/lib/prompts.sh'; bm_lifecycle_prompt /tmp/run g a1" | grep -q "control/gate.json"; then
  pass "bm goal <verb> dispatches to bm-goal; lifecycle prompt names the control files"; else fail "bm dispatch/prompt"; fi

# ---- (r) state stays outside the target repository ----
echo "check (r): state root isolation"
if [ -z "$(git -C "$REPO" status --porcelain)" ] \
   && [ -z "$(find "$ROOT/scripts/lib" -name '*.pyc' -newer "$TMP/started" 2>/dev/null)" ] \
   && [ "$(stat -c %a "$XDG_STATE_HOME/beastmode/goals" 2>/dev/null || stat -f %Lp "$XDG_STATE_HOME/beastmode/goals")" = 700 ]; then
  pass "target worktree untouched; no bytecode written into the source tree; goal registry is owner-only under XDG_STATE_HOME"
else fail "state isolation"; fi

echo
echo "goal-lifecycle: $PASSES passed, $FAILS failed"
[ "$FAILS" = 0 ]
