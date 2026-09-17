# Goal lifecycle: `bm goal`

Every goal started through `bm goal run` is a durable record you can list, inspect,
approve, resume, cancel and prove complete after leaving the terminal — without
reading a chat transcript. The machine-readable contract is
`schema/goal-lifecycle.json`; `scripts/lib/goal_lifecycle.py` is the only writer.
`bm "<goal>"` keeps its meaning and stays dependency-free; the lifecycle is an
opt-in wrapper around it.

## Where state lives

```text
$XDG_STATE_HOME/beastmode/goals/<goal-id>/     (default ~/.local/state/beastmode/goals)
  goal.json                 replaced atomically (temp + fsync + rename)
  events.jsonl              append-only, sequenced; every state change has a reason
  attempts/a<n>/attempt.json   pid, pgid, host, heartbeat, exit code, run dir, usage
  attempts/a<n>/result.json    acceptance record (only when the attempt was judged)
```

The registry is owner-only (`0700`) and never lives inside the target worktree.
Goal IDs are validated; symlinked records are refused; a goal-id lookup never scans
receipts.

## Identity

| Field | Meaning |
|---|---|
| `goal_id` | stable identity, assigned once (`g<UTC timestamp>-<hex>` or `--goal-id`) |
| `attempt_id` | one supervised harness process, `a1`, `a2`, … |
| `contract_digest` | sha256 of goal text + seats + autonomy + harness |
| `revision` | `git rev-parse HEAD` of the worktree when a decision or completion is recorded |

Approvals and completions bind to all four. A decision recorded for one revision is
**stale** (exit 7) once HEAD moves; a completion is valid only for the revision it names.

## States and exit codes

```text
queued → running → awaiting_approval → running → succeeded
                 → blocked | failed  → running (restart)      cancelled and succeeded are terminal
queued → paused → queued
```

| Exit | Meaning |
|---|---|
| 0 | command ok / goal succeeded (acceptance record exists for the final revision) |
| 1 | failed or blocked (validation, provenance, review, harness, stall, budget) |
| 2 | usage or configuration error |
| 3 | breaker refusal (model preflight, Claude OAuth seat, remote dispatch) |
| 4 | awaiting approval — `inspect`, then `approve`/`reject`, then `resume` |
| 5 | cancelled |
| 6 | unsupported for this harness (see `capabilities`) |
| 7 | conflict: repository lock, illegal transition, stale approval, foreign supervisor |

**Succeeded never means merged.** It means: every `--verify-cmd` passed at the final
revision, the canonical provenance gate (`scripts/lib/acn_meta.py`) returned `ok` for
every expected child, and a watcher review bound to the same goal/attempt/revision
approved. No watcher, no `validated`.

## Commands

```text
bm goal run "<goal>" [bm flags] [--max-attempts N] [--max-seconds N] [--max-tokens N]
                     [--stall-seconds N] [--verify-cmd CMD]... [--expect IDS|batch.json]
                     [--attestations PATH] [--notify-cmd CMD] [--queue-only] [--json]
bm goal runs [--state S] [--json]
bm goal inspect <goal-id> [--json]        state, budget, decisions, evidence, events, liveness
bm goal logs <goal-id> [--attempt a<n>] [--tail N]
bm goal approve <goal-id> [--decision d<n>] [--answer K=V]...
bm goal reject <goal-id> [--reason TEXT]
bm goal pause <goal-id>                   queued goals only; a running harness cannot be paused
bm goal resume <goal-id> [--restart] [--acknowledge-partial-effects]
bm goal cancel <goal-id> [--grace-seconds N]
bm goal reconcile [--json]                detect lost supervisors, stop orphans, record effects
bm goal schedule <goal-id> --at ISO | --every SECONDS [--export cron|launchd|json]
bm goal harvest [--since ISO] [--out FILE] [--json]
bm goal capabilities
```

`scripts/bm-goal` is the same CLI without the `bm` dispatcher. The roadmap's
top-level spellings (`bm run`, `bm runs`, `bm inspect`, …) are intentionally **not**
aliased: `bm inspect` already means model inspection and `bm status` stays
installation status.

## Approval, resume and restart

A harness stops at a gate by writing `$BM_RUN_DIR/control/gate.json` and exiting;
the supervisor records the pending decision and exits 4. `approve` records the
answer bound to goal, attempt, revision and contract digest (a second `approve`
of the same decision is exit 7). `resume` then continues:

| Harness | `resume` means | `pause` while running | `cancel` |
|---|---|---|---|
| pi, hermes, claude, codex | **prompt continuation**: a new attempt in the same worktree with the recorded decisions injected via `control/decisions.json`; filesystem state persists, conversation state does not | no (exit 6) | process group |
| langgraph | **checkpoint**: `Command(resume=decision)` on the same thread/database; no work repeated | no (exit 6) | process group |

After `failed`/`blocked`, `resume` is refused: use `--restart`, and unless the outcome
is retryable (`infrastructure_failed`, `stalled`, `supervisor_lost`) also pass
`--acknowledge-partial-effects`. The new attempt is labelled a restart, never a resume.

## Supervision and recovery

- One supervisor per goal and one running goal per repository (lock files under the
  state root, owner + pid + host recorded). Duplicate starts exit 7.
- Heartbeats, stall budget, elapsed and attempt/token budgets are enforced by the
  supervisor; a budget stop is persisted as `budget_exhausted`.
- `cancel` sends SIGTERM then SIGKILL to the harness process group and records
  `cleanup: confirmed` only when the group is observed gone, otherwise `uncertain`.
- `reconcile` marks goals whose supervisor pid is gone as `supervisor_lost`,
  terminates orphaned harness process groups where possible, and records effects
  (worktree dirty state, HEAD before/after) so the operator can decide on `--restart`.
- `--on <remote>` is unsupported under the supervisor (exit 6): remote cleanup and
  cancellation cannot be verified.

## Scheduling (optional, GL5)

Beastmode owns no scheduler daemon; `schedule` exports an entry for cron or launchd
that invokes `bm-goal` only, so every gate still applies.

- `--at ISO` resumes the same queued/paused goal once.
- `--every SECONDS` treats the goal as a **template**: each trigger runs
  `bm-goal run --from-template <id> --occurrence <UTC yyyymmddTHHMM>`, creating a
  fresh goal `<id>-<occurrence>` with its own budget and history.
- Policies are fixed and recorded on the goal: **UTC** (`CRON_TZ=UTC`; launchd
  calendar entries are host-local and annotated), **overlap = reject** (repository
  lock, exit 7), **duplicate = reject** (occurrence id already exists, exit 7),
  **missed trigger = skip** on cron / coalesce-on-wake on launchd. A rejected
  occurrence is a visible non-zero exit, not a silent backlog.
- Paused/awaiting goals are never retried by the scheduler: `resume` refuses without
  an approval and `--from-template` never touches the template's state.

## Notifications (optional, GL5)

`--notify-cmd CMD` receives one JSON payload on stdin per `(attempt, outcome)`:
`notification_id`, `goal_id`, `attempt_id`, `state`, `outcome`, `reason`, `goal`,
`event_seq`. Delivery is deduplicated by `notification_id`, retried 3 times, and
recorded as a `notified` or `notification_failed` event. The command has no
lifecycle authority: nothing it does can approve, resume or complete a goal. Keep
credentials in the command's environment, never in the goal record.

## Learning harvest (optional, GL5)

`bm goal harvest` reads terminal/failed/blocked records and writes a Markdown or JSON
**proposal** of skill/config changes (budgets, routing pins, watcher prompt, verify
timing). It never applies anything; review and land the changes yourself.

## Evidence

`bm goal inspect <id> --json` shows `completion` (the acceptance record), every
decision with its bound revision, attempt usage and the sequenced event log.
`tests/test-goal-lifecycle.sh` is the GL6 pilot: a fake harness drives success,
drift, missing review, gate/approve/resume, stale approval, reject, restart, budget,
cancel, stall, lost supervisor, duplicate start, scheduling, notifications and
state-root isolation. `python/tests/test_goal_lifecycle.py` covers the contract,
store, decision binding, scheduling, notifications, harvest and the LangGraph bridge.
