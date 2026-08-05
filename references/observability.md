# LangGraph observability

Tracing is optional, off by default, and never load-bearing for provenance,
validation, review, or merge. `scripts/acn-report` and
`scripts/lib/acn_meta.py` remain the offline source of truth.

## LangSmith setup

The three hosted-service variables are:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=...
export LANGSMITH_PROJECT=beastmode
```

For a self-hosted deployment, add its endpoint:

```bash
export LANGSMITH_ENDPOINT=https://langsmith.example.test
```

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
└── self_improve
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
