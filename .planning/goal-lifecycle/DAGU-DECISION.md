# GL7 decision record — Dagu is not bundled

**Decision (2026-09-17):** do not fork, vendor, embed or bundle Dagu (or any other
workflow service) into Beastmode. Keep the native goal lifecycle (`bm goal`,
`schema/goal-lifecycle.json`) as the only owner of goal state. Revisit an *external,
optional* Dagu adapter only when one of the triggers below is demonstrated in use.

## Evidence considered

The GL6 pilot (`tests/test-goal-lifecycle.sh`, `python/tests/test_goal_lifecycle.py`)
exercises everything the roadmap asked a scheduler/workflow layer to provide, natively:

| Need | Native mechanism | Evidence |
|---|---|---|
| Durable identity and inspection after restart | `goal.json` + append-only `events.jsonl` under `XDG_STATE_HOME` | pilot (b), (p), (r) |
| Approval pause that survives restart | `control/gate.json` → `awaiting_approval`, decision bound to revision + digest | pilot (f), (g), (h) |
| Resume / restart honesty | `prompt_continuation` vs `checkpoint` capability matrix; `--restart --acknowledge-partial-effects` | pilot (f), (i) |
| Crash recovery, duplicate start, cancellation, stall | supervisor pid/pgid, repository lock, `reconcile`, `cancel` with confirmed/uncertain cleanup | pilot (j), (k), (l), (m) |
| Revision-bound acceptance, no false success | verify commands + canonical provenance gate + bound watcher review → `result.json` | pilot (c), (d), (e) |
| Recurring triggers | cron/launchd export invoking `bm-goal` only; fresh goal per occurrence; UTC/overlap/duplicate/missed policies recorded | pilot (n), unit tests |
| Notifications | `--notify-cmd`, deduplicated, retried, failure visible, no authority | pilot (n2), unit tests |

No scenario in the pilot needed a queue, a workflow editor, a shared dashboard or a
second orchestration loop. The operational burden of a service (deployment,
upgrades, schema drift, auth, a second place where "running" can be wrong) is
therefore not justified by demonstrated need.

## Triggers that would reopen this decision

Any of the following, observed in actual operation and written down with the goal
IDs involved:

1. Fleet worker queues — more than one host must pull goals from a shared backlog.
2. Multiple mixed workflows — non-Beastmode steps (data jobs, deploys) must interleave
   with goals and share retry/ordering semantics.
3. A workflow editor is required by operators who do not use the CLI.
4. A shared operational dashboard across teams/hosts is required beyond
   `bm goal runs`/`inspect` and the optional trace exporters.
5. Centralized human-task administration (approval inboxes, delegation, SLAs) beyond
   `bm goal approve`.

## Constraints on any future adapter

If a trigger is met, the integration is a **thin optional CLI/API adapter**:

- Maps external workflow run/attempt IDs to Beastmode `goal_id`/`attempt_id`; the
  Beastmode record stays authoritative for state, outcome and evidence.
- Beastmode keeps sole ownership of model routing, acceptance, provenance, approvals,
  resume and cancellation. The external service owns triggers and outer attempts
  only; it never becomes a second LLM-directed orchestration loop.
- The selected Dagu schema/version is pinned and validated at adapter start; an
  unknown schema fails closed.
- Required proofs before enabling: a paused (`awaiting_approval`) goal is not retried
  by the external scheduler; a downstream merge/publish step cannot run before the
  bound approval exists; a cancelled goal is not restarted by an outer retry.
- MCP or API access starts **read-only**; scoped mutating operations are added only
  with the same lifecycle exit-code contract and the same gates.
- Existing invocations (`bm "<goal>"`, `bm goal …`) keep working with the service
  absent; the adapter declares its dependency and fails with an actionable message.
- A fork, embedded engine or combined distribution requires a separate maintenance,
  distribution and license review. None is planned.

## Status

GL7 is **closed as "not needed"** for this roadmap. This file is the written record
the roadmap requires; reopen it by appending the trigger evidence above.
