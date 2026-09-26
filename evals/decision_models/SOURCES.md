# Candidate research and provenance

Research date: 2026-09-26. This is a shortlist for evaluation, not a claim of general superiority.

Prior Content Machine research was retrieved through MemroOS:
`content/ai-frontier/custom-jev-memory-articles-2026-09-25.md`. Its existing AnyJev/learning
discussion was research-only; it explicitly recorded no inference experiment.

Native Grok X Search ran with requested model `grok-4.5`, September 20–26 filters,
and returned citations with `degraded: false`. Grok's named model field records the requested
model; the Hermes wrapper does not preserve an independent response-model attestation.
Grok output is discovery evidence, checked against the primary sources below.

The [user's post](https://x.com/bluecow009/status/2103326124835311700) says
“Jev was beaten by opensource.” Its quoted post concerns JevBench v1.4.2.
The [benchmark itself](https://benchmarkheaven.com/jev-models) distinguishes official
composite score from capability: Decider 4B v2 is official #1, but Jev leads capability.
This does not establish Beastmode accuracy, end-to-end speed, or whole-agent cost savings.

| Candidate | Mechanism and fit | Evaluation status |
| --- | --- | --- |
| [Decider 4B v2](https://huggingface.co/Mapika/decider-4b/commit/7ab294cbdf6be6ac17fc818c10cdead744393d92) | Fine-tuned one-pass option-logit readout; explicit requested candidate | Pinned community Q4 conversion for this CPU host |
| [Decider 0.8B](https://huggingface.co/Mapika/decider-0.8b) | Smaller typed decision checkpoint; low local memory footprint | Pinned Q4 conversion |
| [TypeSafe Jev](https://docs.typesafe.ai/models) | Hosted Choice/Score/Noul; versioned `jev-1.13.0` | Live smoke passed; published $0.042/M input, output free |
| [Simple Jev](https://github.com/featherless-ai/simple-jev) | Scores label logits from existing LMs; probabilities are not calibrated correctness | Public demo smoke passed on Qwen3.5-4B-classifier; demo cost is separate from production pricing |
| [AnyJev](https://github.com/nokia-applied-research/AnyJev) | Toolkit: raw/L0 bias correction, L1 temperature, L2 learned head | Promising when reviewed labels exist; not an independently trained model or a reproduced run here |
| [Kev](https://github.com/jaredpalmer/kev) | Open adaptation with custom pointer head and training workflow | Candidate for subsequent domain training; checkpoint, precision and in-domain confidence must be checked |
| [Tev1](https://github.com/togethercomputer/tev1) | Fine-tuned letter-generating decision model; logits are preferences, not calibrated confidence | Alternative generation baseline; no Together inference credential used |

The generic API baseline is `openai/gpt-5.4-nano`, selected from the live
[OpenRouter model catalog](https://openrouter.ai/api/v1/models). At retrieval it lists
$0.20/M input, $1.25/M output, and $0.02/M cached input; use response-reported cost in
results. This is a cheap decision-call baseline, not a measurement of a complete Luna run.

## Exact local artifacts

4B GGUF: [mindchain/decider-4b-v2-GGUF](https://huggingface.co/mindchain/decider-4b-v2-GGUF),
repository revision `2796fac5cdad018ef6d9a4a004735ff819f424a2`, file
`decider-4b.v2-Q4_K_M.gguf`, SHA256
`f7e2e510ef51d212ea9b7fb8bf27906b5f516d7939ca847428fb91f6a8acfa79`.
Downloaded bytes match the publisher's provenance. The publisher identifies upstream tag
`v2`; we did not independently reproduce quantization.

The upstream v2 tag now resolves to `49564ddcfccafb6db563eb757c1d41e6c78dcb56`.
Hugging Face metadata confirms that its weights, tokenizer, and Decider configuration
are byte-identical to benchmark commit `7ab294cbdf6be6ac17fc818c10cdead744393d92`:
weights SHA256 `69e6895461c425c6469cd304838a2e5673141613c2da04782026e37c1481d936`.
This is distinct from latest v2.1. The v2 temperature is 1.935.

0.8B GGUF: [mindchain/decider-0.8b-GGUF](https://huggingface.co/mindchain/decider-0.8b-GGUF),
repository revision `754c9ead4495c7c032293d4f47f07fca65bfec07`, file
`decider-0.8b.Q4_K_M.gguf`, SHA256
`aa40eca91f41e475b7c20a10af4247e8ae5b623f386b5c24501971909199496b`.
Upstream revision `a0a01d6f8135298f400a8c856b355793012ae971`, v1 temperature 1.03.
Downloaded bytes match publisher provenance; quantization not independently reproduced.

Runtime: [llama.cpp](https://github.com/ggml-org/llama.cpp) commit
`2145525a4081d66ff1a87cf43ef809f95a85ac0c`, local CPU build. This is an inference
adapter experiment and cannot be compared directly to upstream GPU/bf16 latency claims.

Grok's claims about additional OpenRouter Kev listings and local millisecond latencies
were not verified and are not used as conclusions. The live OpenRouter catalog only
returned Jev Router in that candidate search; a router product is not the typed Jev API.
