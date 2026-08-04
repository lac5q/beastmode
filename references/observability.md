# LangSmith observability

LangSmith tracing is optional and never load-bearing. The offline source of
truth remains `scripts/lib/acn_meta.py`: tracing being disabled, sampled,
unreachable, or rate-limited must not change a provenance or merge verdict.

## LangGraph pipeline

LangGraph/LangChain can trace the in-process graph when the optional runtime is
installed and the standard environment is configured:

```bash
python -m pip install -e 'python[langgraph]'
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY='set-this-in-your-secret-manager'
export LANGSMITH_PROJECT=beastmode
# optional self-hosted endpoint
export LANGSMITH_ENDPOINT=https://langsmith.example.test
```

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
`--dry-run` to inspect the sanitized payload without contacting LangSmith.

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
