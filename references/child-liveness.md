# Child Liveness: Catching Hung Agents

Added 2026-08-04 after a validator child (`codex exec --model gpt-5.6-sol`) hung at startup
for ~4 hours with zero CPU, no API session, and empty output — and its re-dispatch hung the
same way until stale processes were cleared. The director "waited politely" because slow
high-effort reasoning and a dead process look identical from wall-clock alone.

## The rule

**Wall-clock never decides. Progress signals decide.** A child is HUNG when *all* of its
progress signals are flat; it is WORKING when *any* of them is advancing — and a working
child is never killed without operator approval, no matter how long it runs.

## The three progress signals

| Signal | Working | Hung |
|---|---|---|
| CPU time (`ps -o time -p <pid>`) | accrues, even slowly | frozen at `00:00:00` |
| Session artifact (harness journal / codex rollout / `claude -p` transcript) | file exists and grows | never created, or frozen |
| Child stdout/out-file | grows (unless the harness buffers until exit — then rely on the other two) | empty AND the others flat |

Codex-lane artifact: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` containing the child's
dispatch marker. The rollout is written at request start — **a child alive for minutes with
no rollout containing its marker never reached the API. That is a startup hang, not thinking.**

## Mandatory dispatch pattern

1. **Unique dispatch marker — in the INLINE prompt, not only the instruction file.** With
   file-pointer dispatch, the inline string is what reaches the session artifact at request
   start; the file content appears only once the child gets around to reading it. Dispatch as
   `"Read the file <path> and follow it exactly. BM-RUN: <run-id>"` — a marker only inside
   the file makes the probe race the child's first file read (observed false HUNG 2026-08-04).
2. **Startup probe armed WITH the dispatch, never after.** A bounded probe (default 3 min,
   ~10s polls; use 5 min for max/xhigh-effort children, which think before acting) that looks
   for the session artifact containing the marker:
   - found → `STARTUP-CONFIRMED`, switch to slow liveness polling
   - not found by the deadline → emit `STARTUP-HUNG` loudly. Do not silently retry.
3. **Bounded watchers only.** Every watcher loop has an iteration cap and emits an explicit
   failure line when it trips. `until <condition>; do sleep N; done` with no cap is forbidden:
   when the condition can no longer come true (child killed, output file abandoned) the
   watcher becomes an orphan that "runs for hours" and pollutes the task list. Cap it, and
   kill remaining watchers whenever their child dies.
4. **Liveness poll for long runs.** After startup confirms, check the three signals every
   ~5 min. All flat across two consecutive polls → treat as mid-run hang.

## Dispatch shape (codex lane)

The inline prompt is ONLY `"Read the file <path> and follow it exactly. BM-RUN: <id>"` —
nothing more. Observed 2026-08-04: every dispatch with a longer inline prompt (~700+ chars)
hung at startup (4/4), every short file-pointer dispatch succeeded (8/8). Instructions,
findings, and evidence all go in the file.

## On HUNG

1. Kill the child **and its watchers** (the whole process group; check for wrapper shells
   that still match the dispatch string). **Self-match hazard:** `pkill -f <pattern>` will
   kill your own shell when the pattern appears in your own command line (exit 144 observed).
   Collect PIDs first (`pgrep -f`), inspect, then `kill` the PIDs — or pkill from a command
   that does not contain the pattern verbatim.
2. **Smoke the lane before re-dispatch** (`Reply with exactly: <LANE> OK`, low effort,
   ≤90s timeout). Observed 2026-08-04: hung codex processes can wedge subsequent dispatches
   on the same lane; killing them cleared it — so smoke AFTER killing, not before.
3. Smoke passes → re-dispatch once, probe armed.
4. Second consecutive hang on the same lane, or smoke fails → **stop retrying.** Surface to
   the operator with the evidence and propose a lane substitution (record it in the
   substitution history like `bin/beast-validator` does). Never loop dispatch→hang→kill.

## Meta.json additions

Record per child: `startup_confirmed_at` (ISO timestamp or null), and
`liveness: "confirmed" | "startup-hung-killed" | "midrun-hung-killed"`. A killed child is
never `validated`; its replacement's meta records `retry_of`.

## Operator interaction rule

If any progress signal is advancing, the child is working: report, don't kill — killing a
working child requires explicit operator approval (standing instruction 2026-08-04). If all
signals are flat, the evidence IS the approval to kill a *first* hang; the *second* hang on
a lane goes back to the operator with options.
