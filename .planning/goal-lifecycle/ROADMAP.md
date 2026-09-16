# ROADMAP — Native goal lifecycle and operations

**Status:** planned, not started. Added 2026-09-16 at the operator's request.
Version assignment follows implementation readiness; this is not a release claim.

## Goal and decision

Every Beastmode goal can be inspected, paused, resumed where supported, cancelled,
and proven complete without reconstructing its state from a chat transcript.
Build the native goal-management contract first. Reuse existing checkpoint and
provenance machinery; then add small optional scheduling and notification features.
Dagu remains a possible external integration after demonstrated operational need.
Do not fork, vendor, combine repositories, or bundle Dagu into a Beastmode release
as part of this effort.

The priority is reliable execution across harnesses. Scheduling alone does not
solve context loss, poor decomposition, false acceptance, or model drift.

## Existing foundations and gaps

- LangGraph already provides goal threads, SQLite checkpoints, optional PostgreSQL,
  interrupts and resume. Extend/adapt these rather than build another graph engine.
- `scripts/bm` launches the Hermes harness with Beastmode instructions; prompt-level
  phase rules do not by themselves provide a durable scheduler handshake.
- `scripts/langgraph-runner` exposes thread/database/run-directory/resume options
  and JSON results, but currently returns zero only for `merged`. An approval pause
  must not be classified as an ordinary retryable failure.
- Reuse ACN receipts and the canonical provenance gate. Connect the existing
  [visibility effort](../observability/ROADMAP.md) to goal IDs and lifecycle events;
  traces remain optional and never decide acceptance.
- Coordinate with [LangGraph P8](../langgraph/ROADMAP.md#p8--graphsforeverpy-separate-effort-gated):
  checkpointing and supervision are distinct. This effort supplies bounded-goal
  supervision; it does not authorize or implement the continuous evolver.

## Compatibility and ownership

Existing `bm "<goal>"` invocations retain their meaning. Existing harnesses remain
usable without Dagu, LangGraph, tracing credentials, or new Python packages.
New optional functionality declares its dependencies and fails with an actionable
message when unavailable. Document a capability matrix per harness: inspect,
checkpoint, pause, resume, child supervision and cancellation. Never claim parity
where a harness lacks the necessary runtime support; never silently restart a
partially completed goal under the name of resume.

Beastmode owns goal state, model routing, acceptance contracts, provenance,
autonomy enforcement and verified outcomes. Optional schedulers own triggers and
outer workflow attempts. Notifications and trace exporters consume events and
cannot approve work. Preserve one scheduler of record per recurring job.

## Proposed command surface

These are planned interfaces, not commands available today:

```text
bm run "Implement the next slice"
bm runs
bm inspect <goal-id>
bm logs <goal-id>
bm approve <goal-id>
bm resume <goal-id>
bm cancel <goal-id>
```

P0 specifies durable pause/reject operations and machine-readable modes alongside
these commands. Preserve `bm status` as installation status; goal inspection gets
its own command. Approval records a scoped decision; resume continues execution
only after required decisions are satisfied.

## Phases and acceptance

All phases below are unchecked. Phase exits are future acceptance criteria.

| Phase | Scope | Deterministic exit |
|---|---|---|
| GL0 | Versioned goal/event/result contract; harness capability matrix; command and exit-code design | Fixtures distinguish every state, separate goals from attempts, and reject illegal transitions; compatibility plan covers every existing harness |
| GL1 | Persistent identity, local registry, atomic state updates, run history, `runs`/`inspect`/`logs` | Restart preserves IDs, phase, workspace and history; interrupted writes do not fabricate success; exact goal can be located without scanning arbitrary receipts |
| GL2 | Checkpoint/resume and durable approval boundaries | Approval survives restart; resume keeps goal identity; stale/replayed approval cannot authorize changed work; unsupported resume fails explicitly |
| GL3 | Supervisor, liveness, locks, cancellation, recovery and retry budgets | Concurrent duplicate start is rejected; crash recovery reconciles partial effects; cancelled/timed-out children are terminated or explicitly reported unresolved; retries cannot duplicate protected effects |
| GL4 | Revision-bound acceptance and completion records | Failed tests, missing evidence, model drift and missing watcher prevent success; valid evidence identifies exact goal, attempt, child and revision; process exit alone cannot establish completion |
| GL5 | Optional local scheduling and notifications | Recurring trigger uses lifecycle API; timezone/overlap/missed-run behavior is tested; approval pauses do not retry; failure and approval notifications are delivered or visibly recorded as undelivered |
| GL6 | End-to-end pilot and release evidence | Supported harness matrix passes success, pause/restart/resume, crash, duplicate, cancellation and negative acceptance scenarios; existing shell lane remains dependency-free |
| GL7 | Conditional external operations integration | Written need justifies Dagu or another service; adapter passes the same lifecycle contract without weakening gates or making that service mandatory |

GL0 → GL1 → GL2 → GL3 → GL4 is the core reliability sequence. GL5 follows the
core contract; GL6 verifies the combined release. GL7 is deferred until the pilot
shows a need beyond native operation. A core release may ship before GL5 if all
core acceptance criteria pass; do not delay reliable interactive use for cron.

### GL0–GL1 — Durable goal records

Persist stable goal ID separately from attempt ID, goal text/contract version,
repository and worktree identity, base/current revision, harness and requested
seats, current phase, timestamps, checkpoint reference, expected child manifest,
log/artifact paths and budget usage. Define explicit states including queued,
running, awaiting_approval, blocked, failed, cancelled and succeeded. Do not equate
succeeded with merged: a review-only goal can satisfy its contract without a merge.
Record transition reasons and append-only events; define schema migration,
retention and redaction behavior. Logs must be bounded and safe to inspect.

### GL2 — Pause, approval and resume

Reuse existing LangGraph persistence and expose its identity/resume controls through
the public interface. Implement equivalent adapters only where harness capabilities
permit. Persist pending decision, actor, scope and approved contract/revision before
continuing. Gates run before protected actions. Separate pause from failure and
blocker; an unattended job can remain awaiting approval without burning retry or
model budget. New changes invalidate approvals whose scope no longer matches.

### GL3 — Supervision and safe recovery

Track parent/child execution ownership, heartbeat and bounded stall deadlines.
Use per-goal and appropriate repository/worktree exclusion across manual and
scheduled starts. Define lock ownership, stale-lock recovery and reconciliation
before takeover. Cancellation must cover child process groups and report uncertain
remote cleanup honestly. Timeout is not proof that a remote child stopped.

Default mutating-agent automatic retries off. Add classified retry policy only
with idempotency/reconciliation evidence: transient infrastructure failure,
awaiting approval, failed validation and provenance failure are different outcomes.
Resume the existing goal instead of launching overlapping ACN batches. Bound
attempts, elapsed time and spend; persist budget stops. Preserve scoped sandbox
permissions: worktrees and worker labels alone are not security boundaries.

### GL4 — Verified results and artifacts

Store structured acceptance results, independent review, requested/actual model
provenance, test outputs and a concise report tied to exact goal/attempt/revision.
Consume only expected children from the current run directory; reject stale,
missing, forged or cross-run evidence. Reuse the canonical ACN verifier. External
mechanical checks must feed the same acceptance decision, not create a competing
completion authority. Separate successful preparation from approved merge/publish.
Map outcomes and machine-readable results consistently across adapters.

### GL5 — Jobs as optional functionality

Store reusable job definitions that invoke the goal API, not a second agent loop.
Prefer a small integration with an existing OS scheduler before owning a scheduler
daemon. Specify timezone and daylight-saving behavior, overlap policy (skip, queue,
or reject), missed-trigger policy, deduplication and a fresh goal per intended
occurrence. Concurrency one must not silently imply no backlog.

Provide configurable success/failure/awaiting-approval notifications with event IDs,
bounded delivery retries, deduplication and visible delivery failures. Keep secrets
outside job definitions; safely encode webhook payloads. A notification cannot
approve a goal. Include a separate learning-harvest job that proposes skill/config
changes for review, without silently applying them.

### GL6 — Pilot and release gate

Start manually in an isolated worktree, with automatic mutating retries and
merge/deploy disabled. Demonstrate:

- A successful goal produces independently verified revision-bound evidence.
- Failed validation, model drift and absent watcher cannot become success.
- Approval pause survives restart and resumes the same goal once approved.
- Process crash before/after a side effect is reconciled without duplicate work.
- Duplicate starts from manual and scheduled entry points are rejected.
- Cancellation/stall timeout handles children and exposes unresolved cleanup.
- Unsupported harness capabilities return explicit limitations.
- Budget exhaustion stops; unavailable notifications/tracing do not change verdicts.
- Scheduling covers timezone transitions, missed triggers and overlap policy.

Run existing shell and relevant Python/adapter checks, compatibility checks and
security checks appropriate to the implementation. Publish capability-specific
results; no cross-harness reliability claim without evidence. Only then enable
recurring execution. Fleet deployment and automatic publishing remain separate.

### GL7 — When Dagu earns its place

Revisit external Dagu integration when actual use requires fleet worker queues,
multiple mixed workflows, a workflow editor, shared operational dashboard, or
centralized human-task administration beyond native goal management. Compare
operational burden against demonstrated requirements before selecting a service.

Use a thin optional CLI/API adapter mapping workflow run/attempt IDs to Beastmode
goal IDs, structured outcomes, exact artifacts, approvals, resume and cancellation.
Keep one owner for model/acceptance decisions. Do not move Beastmode into a second
LLM-directed orchestration loop. Pin and validate the selected Dagu schema; prove
that a paused goal is not retried and downstream merge cannot precede approval.
Start MCP access read-only, then add scoped operations if needed. A fork, embedded
engine or combined distribution requires a separate maintenance/distribution
proposal and license review; none is planned here.

## Definition of done

A user can leave the terminal, return after restart, inspect the goal's actual
state, approve or cancel it, resume supported work safely, and verify exactly why
it completed. Scheduling is optional. Dagu is optional. Existing invocations and
provenance/autonomy guarantees remain intact.
