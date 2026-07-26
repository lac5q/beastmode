# ACN - Async Parallel Sub-Agents

ACN is the universal Beastmode fan-out layer. It is the same contract on
every harness: the only difference is which primitive implements `batch`
and `parallel`. This doc is the human reading of
`schema/acn-contract.json` - that JSON is the machine source of truth; this
file is the prose.

## What ACN is

ACN is async parallel sub-agents. One director delegates a batch of
independent tasks to N workers, the runtime runs them concurrently, and
the director gets one consolidated result back. The director does not
block the chat path while the workers run; the harness returns a handle
and re-enters the conversation when the batch finishes.

The three seats in an ACN run:

- **Director** - frontier-tier model, in the original session. Owns the
 goal, the contract, the merge, and the final close-out.
- **Watcher** - frontier-tier model, prefer cross-family vs director.
 Either a second `delegate_task` child or a separate skill call. Its job
 is adversarial review, not authorship.
- **Executor** - economy-tier model. This is where the bulk of the work
 happens; one child per task. Pinned to a specific `provider/model` for
 the duration of the run.

## Batch shape

The batch is the universal envelope every harness accepts. Required
fields (from `schema/acn-contract.json`):

```
autonomy low | medium | high (default medium)
director_model provider/model (e.g. kimi/kimi-k3)
executor_model provider/model (e.g. minimax/MiniMax-M3)
watcher_model provider/model (e.g. xai/grok-4.5)
tasks [task, ...] (see below)
concurrency int (default 3)
```

Each task in the batch:

```
id string (stable across runs)
goal string (the per-task objective)
allowed_paths [path, ...] (worker stays in scope)
verify_cmds [bash, ...] (smallest thing that fails when the work is wrong)
```

Workers receive the byte-identical shared contract (the universal beastmode
worker prompt: paths, allowed/forbidden commands, the meta.json shape)
plus the per-task objective appended after it. The shared prefix is the
prompt-cache hot zone - keep it identical across every child in the same
batch; splice only the task-specific slice.

## Per-child meta.json

Every child returns a `meta.json` matching the schema's required fields:

```
id string
requested_model provider/model (what the batch pinned)
actual_model provider/model (what actually ran)
stop_reason string (end_turn | max_tokens | tool_error | ...)
usage { input_tokens, output_tokens, ... }
files_changed [path, ...]
commands_run [bash, ...]
verify { commands: [...], passed: bool, notes: string }
```

The director compares `actual_model` against `requested_model` before
reading the body. Any mismatch is **MODEL DRIFT** - surfaces at every
autonomy level, blocks `validated` until the same task is re-run under the
pinned model. Drift is fail-closed: a drifted child is treated as
unverified draft, even if the output looks plausible.

## The six shared rules

1. **Preflight seats** before any batch - director / watcher / executor
 models resolve against the harness's known-model list. Missing model
 = exit 2 with the available alternatives, not a mid-run crash.
2. **Pin the executor model** for the run. The runtime must be able to
 prove the child model (config pin, harness journal, or response meta).
 If it cannot prove it, the child is an unverified draft lane.
3. **Parallel by default, lane-grouped.** Group same-model tasks so the
 prompt cache stays hot; alternating lanes force a fresh 1.25x write on
 every switch.
4. **Background where supported.** The director does not block the chat
 path while the batch runs. Orchestrator children (nested fan-out) may
 wait to synthesize.
5. **Consolidate to mechanical validation first, then watcher judgment.**
 Run `verify_cmds` mechanically; only then hand the surviving output
 to the watcher for adversarial review.
6. **MODEL DRIFT always surfaces.** At every autonomy level. Blocks
 `validated`. Recorded in the self-improvement entry.

## Harness primitive map

| Harness | Primitive | Notes |
|---|---|---|
| Hermes | `delegate_task` (single) / `delegate_task(tasks=[...])` (batch) | Background by default; live transcripts under `~/.hermes/cache/delegation/live/<id>/task-<n>.log`; `max_concurrent_children` controls concurrency |
| Pi | `pi-dynamic-workflows` `agent()` / `parallel()` | Lane-grouped, worktree isolation, JSON Schema `schema:` for typed results |
| Claude Code | `Task` tool + `/batch`; parallel `claude -p` from shell | Director keeps one chat; subagents run in parallel sandboxes |
| Codex | `codex exec` in parallel + worktrees per lane | Each Codex runs in its own worktree; consolidate via the director |

The vocabulary is identical across all four: autonomy level, the three
seats, the batch shape, the meta.json shape, MODEL DRIFT, gates blocking
below high, no watcher = no validated. The harness primitive is the only
thing that changes.

## Schema is the source of truth

`schema/acn-contract.json` is the machine-readable contract for ACN - 
batch fields, task fields, meta.json fields, drift policy, hard rules.
This doc is the human reading of it. When the schema changes, update
this doc in the same PR; do not let the prose drift from the JSON.
