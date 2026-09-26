# Jev-style decision model spikes

An isolated comparison of typed decisions for Beastmode. See [PROTOCOL.md](PROTOCOL.md)
for the frozen design, [SOURCES.md](SOURCES.md) for candidate research and pins, and
[results/2026-09-26](results/2026-09-26) for responses and provenance. Production routing
is unchanged. The synthetic cases test the supplied policies, not an entire agent run.

Read [RESULTS.md](RESULTS.md) for the completed five-model comparison (300 calls).

## Run the checks

From the repository root:

```bash
python -m unittest discover -s evals/decision_models -p 'test_*.py' -v
python evals/decision_models/analyze_results.py \
  --results evals/decision_models/results/2026-09-26 \
  --cases evals/decision_models/cases.json --output /tmp/decision-analysis.json
```

The fixture file has 30 unique cases across routing, retries, evidence, tools, and a
separate fictional ads subset. Gold labels and rationales are excluded from requests.
Two passes provide repeatability information, not 60 independent examples.

## Hosted models

The runner uses only the Python standard library. Supply credentials through
`TYPESAFE_API_KEY` or `OPENROUTER_API_KEY` in the environment. The public Simple Jev
demo does not use credentials. Use new output names to preserve earlier runs.

```bash
python evals/decision_models/benchmark_api.py \
  --cases evals/decision_models/cases.json --output .beastmode/jev.jsonl \
  --provider jev --model jev-1.13.0 --repeats 2

python evals/decision_models/benchmark_api.py \
  --cases evals/decision_models/cases.json --output .beastmode/simplejev.jsonl \
  --provider simplejev --model featherless-ai/Qwen3.5-4B-classifier --repeats 2

python evals/decision_models/benchmark_api.py \
  --cases evals/decision_models/cases.json --output .beastmode/nano.jsonl \
  --provider openrouter --model openai/gpt-5.4-nano --repeats 2
```

Each API run saves JSONL, warmup, metadata and summary files. Auth/rate-limit errors
stop the run; no hidden retries are charged outside the record. The initial Simple Jev
urllib client received HTTP 403/code 1010. A truthful benchmark User-Agent fixed client
compatibility; the failed warmup and corrected run are both retained. Scientific prompts
and labels were not changed between them.

## Local Decider

Use the pinned llama.cpp commit and verified GGUF artifacts in [SOURCES.md](SOURCES.md).
The September run built the `llama-server` CMake target with `GGML_NATIVE=ON`,
`GGML_CUDA=OFF`, Release mode and GCC 13.3. Model files are deliberately excluded
from the repository; their download receipts contain repository revisions and SHA256s.

Start one model at a time (replace the two paths):

```bash
path/to/llama-server -m path/to/decider-4b.v2-Q4_K_M.gguf \
  -ngl 0 -c 2048 -t 4 -tb 4 -np 1 --host 127.0.0.1 --port 18089 --no-webui
```

Wait for `/health` to report ready. Then:

```bash
python evals/decision_models/benchmark_local.py \
  --cases evals/decision_models/cases.json --output .beastmode/decider4.jsonl \
  --model-id Mapika/decider-4b@v2:Q4_K_M \
  --model-receipt path/to/decider-4b.v2-Q4_K_M.gguf.json \
  --temperature 1.935 --repeats 2 > .beastmode/decider4.summary.json
```

For 0.8B, load `decider-0.8b.Q4_K_M.gguf`, use its receipt and temperature `1.03`.
Receipt shape: `{ "repo": "...", "revision": "...", "file": "...gguf",
"sha256": "64 hex characters", "bytes": 123 }`. Verify the actual downloaded file
hash separately; a receipt by itself is not proof of the file's contents.

The adapter checks the loaded path against the receipt. It requests one transport token
to obtain raw option logits, reconstructs restricted probabilities and chooses their
argmax. It does not generate a prose explanation. Missing option logits invalidate the
row. Warmup and model startup are excluded from measured request latency.

## Reading the evidence

Archived raw JSONL uses gzip to keep file sizes reasonable; decompress with Python's
`gzip.open(path, "rt")`. The manifest lists SHA256s. Local rows include original server
responses, prompts, model-file receipts and timings. API rows preserve payloads and raw
responses, without credentials or headers. Some hosted IDs identify a service rather
than an immutable weights revision; the observed response ID is the available evidence.

Jev cost is an estimate from reported input tokens and the official input price;
OpenRouter cost is reported by the provider. Local hardware cost and the anonymous
demo's production billing are not measured. Report output-token fields as returned:
non-generative operation does not imply zero reported output tokens.
