# LangSmith observability

Tracing is optional, off by default, and never load-bearing for provenance,
validation, review, or merge. `scripts/acn-report` and
`scripts/lib/acn_meta.py` remain the offline source of truth.

## Run ledger and progress digests

The target repository keeps an append-only run ledger at
`.beastmode/LEDGER.md`; create `.beastmode/` if it is missing. Write one line
for each worker dispatched, worker completed, worker failed or hung, phase gate
reached, and merge event:

```text
| <UTC hh:mm> | phase <n> | <worker-id or gate> | <requested>-><actual model> | <tokens> tok (<pct of phase budget>) | <done|failed|hung|drift|gate> | <one-line what> |
```

Emit a compact progress digest to the operator at every phase gate and at least
once per hour during a long phase. Keep it to eight lines or fewer and include
no raw logs:

```text
BM progress <elapsed> — phase <n>/<N> <name>
Workers: <d> done / <f> failed / <r> running
Tokens: <total> (<pct> of budget) — per model: <model a>: <tok> (<pct>), <model b>: <tok> (<pct>)
Completed since last digest: <one-liners>
Failures/drift: <one-liners or none>
```

Derive digests from the same worker `meta.json` data used by the drift gate.
`scripts/acn-report` already normalizes per-child usage and is the data source;
do not build a second usage or drift tool. Ledger and digest reporting apply at
every autonomy level.

## LangSmith setup

The three hosted-service variables are:

```bash
python -m pip install -e 'python[langgraph]'
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY='set-this-in-your-secret-manager'
export LANGSMITH_PROJECT=beastmode
# Required for organization-scoped or multi-workspace service keys:
export LANGSMITH_WORKSPACE_ID='workspace-id'
```

For a self-hosted deployment, add its endpoint:

```bash
export LANGSMITH_ENDPOINT=https://langsmith.example.test
export BEASTMODE_LANGSMITH_KEY='set-this-in-your-secret-manager'
scripts/acn-trace /path/to/run-dir --api-key-env BEASTMODE_LANGSMITH_KEY
```

`acn-trace` never forwards ambient LangSmith credentials to a custom endpoint;
the custom credential variable must be selected explicitly, and redirects are
not followed.

LangGraph supplies the graph/node spans. Beastmode adds stable metadata for
`goal_id`, `thread_id`, `phase`, `seat`, `autonomy`, `harness`,
`requested_model`, `actual_model`, and `beastmode_version`. Use tags such as
`beastmode`, `phase:design`, `seat:executor`, `drift`, and `unverifiable` for
filtering.

The resulting shape is:

```text
beastmode-pipeline
├── preflight
├── contract → design → challenge → dispatch
├── execute
│   └── beastmode.child        reconstructed from that child's meta.json
├── validate_mechanical
├── gate_provenance
├── review → gate_merge → merge
└── self_improve (also receives blocked exits)
```

Subprocess CLIs are not LangSmith-aware. `WorktreeSubprocessExecutor` therefore
reconstructs each `beastmode.child` span only after a canonical `meta.json`
exists. The span carries requested/actual model, stop reason, usage,
files-changed, commands-run, and the canonical provenance status. A silent or
malformed child gets no synthetic passing span. The input/output token counts
come from the same `usage` object printed by `scripts/acn-report`; the Python
test lane reconciles both views on the canonical fixture.

## Privacy and masking

Source code, diffs, prompts, paths, and model metadata may be sensitive. Prefer
self-hosting or leave tracing off. To suppress payloads in the current
LangSmith client:

```bash
export LANGSMITH_HIDE_INPUTS=true
export LANGSMITH_HIDE_OUTPUTS=true
export LANGSMITH_HIDE_METADATA=true
```

Applications that need selective masking can create their LangSmith client
with an anonymizer callback. Beastmode also bounds and redacts its custom trace
records and stream events before returning them; that is defense in depth, not
permission to put credentials in prompts or metadata.

## Sampling and long-running graphs

Sample before enabling tracing on high-fan-out or long-running graphs:

```bash
export LANGSMITH_TRACING_SAMPLING_RATE=0.10
```

The value is between `0` and `1`. Sampling controls telemetry volume only. A
sampled-out run still performs the same on-disk provenance check and receives
the same gate verdict.

## OpenTelemetry and custom streams

`beastmode.core.observability.trace_metadata` and `child_span_from_meta` return
bounded OpenTelemetry-shaped dictionaries without importing an observability
SDK. An application can pass them to its own OTel exporter; standard exporter
settings such as `OTEL_EXPORTER_OTLP_ENDPOINT` and
`OTEL_EXPORTER_OTLP_HEADERS` remain application-owned. LangGraph users can also
consume `graph.stream(..., stream_mode="custom")` for redacted phase, gate,
and executor progress.

Turning tracing off, configuring an unreachable hostname, pointing it at a
dead local endpoint, or sampling every trace out must produce byte-identical
gate verdict fields. The test suite negative-tests those configurations. Traces
may display `drift` or `unverifiable`; they never decide either verdict.

## Existing harness receipt projection

`LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`, `LANGCHAIN_ENDPOINT`, and
`LANGCHAIN_TRACING_V2` are accepted aliases by the LangChain/LangSmith SDK.
Do not commit keys or put them in a repository `.env` file.

The graph's node boundaries provide the normal in-process trace tree. For the
isolated subprocess work that the graph cannot observe directly, run
`scripts/acn-trace` after completion. Its `beastmode.child` records carry only
bounded metadata, model provenance, token counts, stop reason, and counts of
files/commands; they do not send prompts, diffs, file names, or raw command
arguments. A child with `drift` or `unverifiable` provenance is tagged in the
trace, but the offline gate still decides the verdict.

For additional privacy when tracing the graph, configure the SDK masking
options before running:

```bash
export LANGSMITH_HIDE_INPUTS=true
export LANGSMITH_HIDE_OUTPUTS=true
```

## Existing Pi, Hermes, Claude, and Codex runs

Those harnesses write the same canonical receipts but do not share a live
LangSmith context with the parent process. Project a completed run manually:

```bash
scripts/acn-trace /path/to/run-dir \
  --project beastmode \
  --goal-id goal-123 \
  --harness pi \
  --autonomy medium
```

`acn-trace` uses the standard-library HTTP client and LangSmith's `/runs` API,
so it does not add a dependency to the install-free shell lane. It creates one
`beastmode.run` parent and one `beastmode.child` per receipt, with filterable
`beastmode`, `phase:*`, `seat:*`, `drift`, and `unverifiable` tags. Use
`--workspace-id` or `LANGSMITH_WORKSPACE_ID` for a service key that can access
multiple workspaces; the value is sent as LangSmith's `x-tenant-id` header.
Use `--dry-run` to inspect the sanitized payload without contacting LangSmith.

The command exits zero when tracing is disabled or credentials are absent and
reports a clean skip. A submission failure is reported as an observability
failure only; it never substitutes for or overrides `acn-report` or
`enforce-models --check-meta`.

## Metadata contract

The framework-neutral APIs are `beastmode.core.observability.trace_metadata`
and `child_span_from_meta`. LangGraph users can also consume
`graph.stream(..., stream_mode="custom")` for phase/gate/executor progress.
The child projection uses the same `meta.json` reader and provenance vocabulary
as `acn-report`; it never turns a silent child into a passing record.
