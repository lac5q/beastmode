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

The director compares independently attested `actual_model` against `requested_model` before
reading the body. Any mismatch is **MODEL DRIFT** - surfaces at every
autonomy level, blocks `validated` until the same task is re-run under the
pinned model. Drift is fail-closed: a drifted child is treated as
unverified draft, even if the output looks plausible.

`requested_model` and `actual_model` are separate fields on purpose. A child
that reports a single merged `model` - the pre-v2.3 shape - gives the gate
nothing to compare, and a comparison that cannot be made is not a pass.

### Optional `needs_decision`

Workers may include an optional `needs_decision` array in `meta.json`; it is
not part of `meta_json_required_fields`, so metas without open questions remain
valid. Each item mirrors `schema/acn-contract.json`:

```json
{"id":"string","question":"string","options":[],"assumed":"string","impact_if_wrong":"string"}
```

Workers never interview the user. When an ambiguity is covered by the
acceptance contract, the worker continues under that assumption and records the
item. If it is genuinely blocked, it stops with
`stop_reason: "needs_decision"`. The director combines items from worker metas,
watcher review, and its own review. At low and medium, the next phase gate
includes `## Open Questions` and cannot pass until each item is answered or
explicitly deferred; a deferral becomes an Assumption. At high, items fold into
the final report's Assumptions section.

### Three verdicts, two of them failures

| Verdict | Condition | Gate |
|---|---|---|
| `ok` | `requested_model == actual_model` | pass |
| `drift` | `requested_model != actual_model` | **fail** - re-run under the pinned model |
| `unverifiable` | meta missing/unreadable, independent attestation missing or inconsistent, either model field missing, duplicate IDs, or an expected child wrote no meta | **fail** - provenance cannot be established |

`meta.json` is worker output, not independent evidence. The parent harness or
provider adapter must also write an attestation outside the worker-writable run
tree. Each attestation binds `id`, `requested_model`, `actual_model`, `run_id`,
and the exact result digest, is authenticated with a parent-held key, and names
a nonempty `source` such as `harness-journal` or `provider-response`:

```json
{"id":"child-1","requested_model":"minimax/MiniMax-M3","actual_model":"minimax/MiniMax-M3","source":"harness-journal","run_id":"<parent-run-id>","result_digest":"<sha256>","signature":"<hmac-sha256>"}
```

The gate rejects absent or unauthenticated attestations, cross-run replay,
result-byte substitution, disagreement between worker metadata and trusted
evidence, duplicate expected/observed IDs, and attestations stored inside the
run directory.

One valid sibling does not carry a batch. Each child is judged on its own
record, so a run where nine children proved their model and one did not is a
failed gate, not a 90% pass.

`unverifiable` is a gate failure because shared rule 2 already says so: a
child whose model the runtime cannot prove is an unverified draft lane. A
gate that exits 0 on "I don't know" inverts that rule, which is exactly what
the pre-v2.3 tooling did - legacy-shape metas were skipped as unrecognised,
and a run directory with no metas at all reported clean.

A batch that legitimately produced no children is asserted, not assumed:
pass `--allow-empty` to `enforce-models --check-meta` / `acn-report`.

### Catching a child that never wrote anything

Scanning a run directory can only judge records that exist. A worker killed
before it wrote any meta leaves no file, so a surviving sibling would carry
the batch to a clean exit. Pass the batch's expected child ids to close that:

```bash
enforce-models --check-meta <run-dir> --attestations <trusted.json> --trust-attestations --expect <batch.json>
enforce-models --check-meta <run-dir> --attestations <trusted.json> --trust-attestations --expect child-1,child-2
```

The manifest is not a new artifact - `tasks[].id` is already required by
`schema/acn-contract.json`, so the batch the director already wrote *is* the
list of children the gate should expect to hear from.

Both tools call one checker, `scripts/lib/acn_meta.py`, which reads
`meta_json_required_fields` out of `schema/acn-contract.json`. The schema is
load-bearing: change the field list there and the gate follows.

## The seven shared rules

1. **Preflight seats** before any batch - director / watcher / executor
 models resolve against the harness's known-model list. Missing model
 = exit 2 with the available alternatives, not a mid-run crash.
2. **Pin the executor model** for the run. The runtime must be able to
 prove the child model through parent-owned harness journal or provider-response evidence.
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
7. **Unprovable provenance fails closed.** A child that is `unverifiable`
 fails the gate exactly like a drifted one. Silence is not consent: an
 empty run directory, an unreadable meta, or a meta without both model
 fields all block `validated`.

## Harness primitive map

| Harness | Primitive | Notes |
|---|---|---|
| Hermes | `delegate_task` (single) / `delegate_task(tasks=[...])` (batch) | Background by default; live transcripts under `~/.hermes/cache/delegation/live/<id>/task-<n>.log`; `max_concurrent_children` controls concurrency |
| Pi | `pi-dynamic-workflows` `agent()` / `parallel()` | Lane-grouped, worktree isolation, JSON Schema `schema:` for typed results |
| Claude Code | `Task` tool + `/batch`; parallel `claude -p` from shell | Director keeps one chat; subagents run in parallel sandboxes |
| Codex | `codex exec` in parallel + worktrees per lane | Each Codex runs in its own worktree; consolidate via the director |
| LangGraph | `StateGraph` + `Send` + checkpointed `interrupt()` | Same-lane fan-out, isolated subprocess worktrees, SQLite by default; `PostgresSaver` is opt-in |

The vocabulary is identical across all four: autonomy level, the three
seats, the batch shape, the meta.json shape, MODEL DRIFT, gates blocking
below high, no watcher = no validated. The harness primitive is the only
thing that changes.

## Schema is the source of truth

`schema/acn-contract.json` is the machine-readable contract for ACN - 
batch fields, task fields, meta.json fields, drift policy, hard rules.
This doc is the human reading of it. When the schema changes, update
this doc in the same PR; do not let the prose drift from the JSON.

`tests/test-acn-parity.sh` enforces that: it asserts every field name in the
meta.json block above appears in the schema's `meta_json_required_fields` and
vice versa, so prose and JSON cannot silently diverge again.
