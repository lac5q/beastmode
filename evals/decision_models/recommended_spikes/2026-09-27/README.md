# Recommended repository spikes — 2026-09-27

The five feasibility spikes are complete to the extent this host supports them.
Full Kev, CLM, and Laya inference comparisons remain incomplete. None of these
results qualifies a new Beastmode default. Existing runtime routing and the
previous frozen datasets are unchanged.

| Candidate | Executed | Result | Decision |
| --- | --- | --- | --- |
| Kev-4B | Public Space, one excluded warmup, three measured attempts | Two valid, correct responses; third hit anonymous ZeroGPU quota | Resume on a configured endpoint or suitable local hardware; no full-corpus score |
| CLM | Genuine projection checkpoint on CPU; synthetic embedding contract checks | Safe load, tensor/schema/error/cache checks passed | Full Qwen3-8B encoder still required for accuracy and latency |
| Laya-MLX | Isolated install, normal import, pure Python utility checks | Normal import blocked by missing MLX on Linux; utility checks passed | Needs accessible Apple Silicon host |
| fast-jev-compaction | 29 upstream tests, type checks, eight synthetic histories plus a matched benign variant, nine live Jev requests | Lost two explicitly required pieces of evidence; result-body variants sent identical requests | Experimental only; cannot satisfy the tested retention requirements |
| jev-ultrafast | 31 upstream tests, 21 local browser guards, five offline validator checks, three live local trials | Two successful trials; one writer response rejected before any action | Useful loop prototype; requires stronger writer reliability and broader evaluation |

## Live findings

### Kev

The frozen 32-case agent-folder corpus was scheduled for two passes. The Space
returned a correct excluded warmup and two correct measured responses, then a
quota error. The run stopped immediately; there were no hidden retries or
substitute models. Only the first two measured cases completed, both in the
`next_worker` category. This cannot support an overall accuracy ranking.

Median client time was 1,155.6 ms versus 121.1 ms reported by the model on those
two measured responses. These are different measurements, with N=2. They do not
establish self-hosted latency. The returned model ID was `jaredpalmer/kev-4b`;
the Space source revision was pinned, but deployed weight revision was not
independently attested. Usage was 385 input / 146 output tokens for completed
measured calls; monetary cost was not reported.

### Compaction

Live model: `jev-1.13.0`. Eight frozen histories plus a benign counterpart made
nine HTTP-200 requests, using 6,069 reported input tokens. Median observed
request wall time was 152 ms. This is a synthetic retention probe, not a
production compression benchmark or model accuracy score.

The approval-scope fixture lost the only tool result containing the allowed
paths and prohibited directory. The long-result fixture lost its critical
middle marker. The original histories remain in the archived audit receipts.
The old failure receipt and contradictory evidence survived: although Jev
selected `drop_result`, the library kept those short results in full.

Changing only the long output body from critical evidence to benign text
produced byte-identical serialized requests, confirmed by the captured bodies
and SHA-256 hashes. The library sends result status and length, omitting its
contents. This establishes a structural information loss in its decision input;
it does not demonstrate that Jev would fail if given the evidence.

Call/result pairing, recent pins, and source-history immutability passed the
fixture checks. Missing-key and simulated HTTP-503 library calls raised errors;
the upstream hook fallback tests also passed. Both duplicate outputs were
dropped in the live duplicate case. That case did not assert that one copy must
survive, so it is not counted as a separate predefined retention failure.

Limitations: tiny synthetic histories use recent-message windows of one or two
to expose old calls (library default is six), a generic explicit goal
`adversarial compaction fixture`, and the default 0.5 threshold. Conversation
text supplies the individual task constraints. There are four explicit
required-evidence probes, not eight semantic accuracy cases. The fake run's
forced middle truncation demonstrates mechanism; it is not a gold safe action.
Fixture hashes were embedded and checked before live calls. The separate
pre-run manifest command failed due to its working directory; the script hash
was recorded after launch, with no script changes during the run. See
`compaction/run-manifest.json`.

### Browser loop

The pinned local fixture asks for Design stays in Lisbon with free cancellation,
then Casa Flora. Each trial used a dedicated browser profile, a loopback fixture,
at most 20 actions, and a 60-second budget per decision step. The exact final
DOM fields were frozen before live execution and checked independently of
Jev's `DONE` answer. Fixture links remain local; no reservation is made.

Decision model: `jev-1.13.0`; field writer: `inception/mercury-2.5` through
OpenRouter. Trial 1 failed after 4,423 ms because the writer returned
`{"text": "Lisbon"}` followed by a closing Markdown fence. The code rejected
the invalid JSON and executed zero actions. Trials 2 and 3 passed every frozen
DOM condition after five actions each, in 4,078 and 2,822 ms respectively.

There were 13 Jev calls (36,408 reported input tokens) and three writer calls.
Writer-reported cost totaled $0.00009905; that excludes Jev and infrastructure.
Receipts cover logical provider calls. Upstream code can retry HTTP 429/529/503
twice inside one logical call, so these receipts do not count individual retry
attempts. Model IDs were observed, not weight-attested.

The offline checks reject changed DOM outcomes and unsupported actions. They
do not test live prompt-injection resistance. The 21 real-browser guard checks
cover freshness, replaced nodes, overlays and related execution conditions.
Three trials on one bundled fixture are a smoke test, not a general browser
success rate or a comparison against another agent.

## Local backend limits

This is a Linux x86_64 WSL host with about 12 GB RAM and no detected NVIDIA
device. `mainmac` did not resolve; `main-mac` rejected SSH authentication. No
new cloud resources were provisioned. An accessible GPU/encoder endpoint and
Apple Silicon host were requested; none was supplied during this run.

CLM's real 75,557,149-byte checkpoint matches its Hugging Face LFS SHA-256.
`TORCH_FORCE_WEIGHTS_ONLY_LOAD=1` was enforced. Its 18,887,680 projection-head
parameters loaded with CPU PyTorch 2.14.0; 4096-wide inputs produced finite,
normalized 512-wide projections. Deterministic synthetic embeddings exercised
Noul/Choice/Score contracts, invalid inputs and cache reuse. They carry no
semantic meaning. No reference encoder, task accuracy, calibration or full
model latency was measured. The ready runner requires explicit `--cases` and
a caller-provided real encoder endpoint.

Laya's actual package import raised `ModuleNotFoundError: No module named
'mlx'`. Pure Python checks bypassed package initialization only to exercise
routing, language, temperature, email-state and preset utilities. No substitute
MLX backend, model inference, checkpoint download or Mac speed claim was used.

## Reproduction and integrity

Run the independent archive audit from any directory:

```sh
python /path/to/beastmode/evals/decision_models/recommended_spikes/2026-09-27/audit.py
```

It verifies the SHA manifest, frozen corpus and runner hashes, raw model IDs,
Kev payloads and labels, actual compaction text retention, identical compaction
requests, browser acceptance fields and malformed writer response. It requires
only Python's standard library and makes no network calls.

For live reproduction, create fresh scratch checkouts at the source pins below.
Copy `compaction/compaction-fixtures.ts` into the compaction checkout's `spikes/`
directory, install its lockfile (`npm ci`), then run `npm test`,
`npm run typecheck`, and `node_modules/.bin/tsx spikes/compaction-fixtures.ts`
(add `--live` with the configured `TYPESAFE_API_KEY` for fresh receipts). Do not
overwrite this archive. Copy browser scripts and contract alongside a pinned
`source/` checkout, install its uv lockfile, start dedicated headless Chrome,
and set the BH directories and loopback CDP endpoint as in `browser/results/checks.md`.
The browser runner requires explicit live opt-in and caller-supplied keys;
pin the decision/writer models and reasoning setting from `live-freeze.json`
(`TEXT_MODEL_REASONING=none`). Local backend commands and dependency pins live
under `local-backends/`; the Laya utility script retains this run's `/tmp`
source path and must point at an equivalent pinned checkout when moved.

The archive excludes dependencies, downloaded weights, browser profiles and
credentials. Compressed JSON files preserve synthetic inputs, provider outputs,
states and errors. Worker scripts were requested using the available GPT-5.6
Luna max fallback; actual worker backend identity was unverified. The director
reviewed the scripts, ran live calls, reran component/upstream checks, and
independently audited the retained evidence.

## Source pins and next steps

- [Kev](https://github.com/jaredpalmer/kev/tree/5920c5fe4ca8e0970ed4209ac2c9b8e18bea5109); [Space source](https://huggingface.co/spaces/jaredpalmer/kev/tree/bc58df8299d0bcaaa6cf5466bdc48bb4a30dd961).
- [CLM](https://github.com/Contrastive-LM/CLM/tree/bb42c6c5bf914fd449bed2f6ca65be80602cb1f7); [head checkpoint](https://huggingface.co/Contrastive-LM/CLM-v0.1-8B/tree/e939398d4556fcd9400c76fa8c5a513202f42b0a).
- [Laya-MLX](https://github.com/mizorewww/laya-mlx/tree/0a859518634112655cb97c745dbf04f5191aaf13).
- [fast-jev-compaction](https://github.com/tamaratran/fast-jev-compaction/tree/e3f262a7f4d42bd8dd32ced30d26176f7cb545b0).
- [jev-ultrafast](https://github.com/browser-use/jev-ultrafast/tree/1231850a0bf1a0c0341fe408ef1668dbbfdfac46).

Resume Kev and CLM on suitable existing hardware; run Laya on Apple Silicon.
Before considering compaction adoption, preserve constraints and irreplaceable
receipts deterministically and test a representation that exposes relevant
result content. Before considering browser adoption, evaluate a reliably
schema-constrained writer, failure recovery, held-out sites and live adversarial
pages. Keep the frozen failing trials when testing improvements. Beastmode's
existing optional-provider qualification policy remains the adoption gate.
