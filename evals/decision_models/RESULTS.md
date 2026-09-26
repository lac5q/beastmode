# Beastmode Jev-style decision model spikes

Jev is the strongest first hosted candidate for an **advisory** Beastmode trial in this spike: 3.76× faster at the median than GPT-5.4 Nano, approximately 64.9% cheaper at its published input rate, and the same 85% agreement with the frozen labels. **It did not save reported tokens.** Simple Jev had the highest label agreement, 52/60, but the difference is too small to establish superiority.

The explicitly requested **Decider 4B v2** completed all 60 calls at 80% label agreement. Its median was 22.5 seconds on this heavily shared CPU host. It used 19.5% fewer total tokens than Nano, but this setup did not demonstrate useful speed or cost savings. This is a pinned Q4 CPU experiment, not a reproduction of the upstream bf16/GPU benchmark.

## Research and candidates

Native Grok X Search ran with requested model `grok-4.5`, September 20–26 filters, citations and `degraded:false`. The wrapper records the requested model, not independently attested backend identity. Its raw output is archived. Grok supplied leads; primary sources supplied accepted facts.

The [linked post](https://x.com/bluecow009/status/2103326124835311700) concerns JevBench's composite ranking. The [benchmark](https://benchmarkheaven.com/jev-models) separately reports capability: Decider 4B v2 led the official composite, while Jev led capability. Neither ranking establishes Beastmode savings.

| Candidate | Fit and actual work |
|---|---|
| [Jev](https://docs.typesafe.ai/models) | Hosted typed decisions; ran pinned `jev-1.13.0`. |
| [Simple Jev](https://github.com/featherless-ai/simple-jev) | Label-logit readout from existing models; ran public Qwen3.5-4B-classifier demo. |
| [Decider](https://github.com/Mapika/decider) | Trained decision checkpoints; ran 0.8B and 4B v2 community Q4 conversions locally. |
| [AnyJev](https://github.com/nokia-applied-research/AnyJev) | Toolkit for bias correction, temperature fitting and learned question-specific heads. Promising once reviewed domain labels exist; no inference/training run here. |
| [Kev](https://github.com/jaredpalmer/kev) | Custom pointer-head/training approach; researched, not run. |
| [Tev1](https://github.com/togethercomputer/tev1) | Letter-generating decision model with uncalibrated logprobs; researched, not run. |
| GPT-5.4 Nano | Cheap generative decision baseline via OpenRouter; reasoning disabled. |

Prior Content Machine research was retrieved through MemroOS at `content/ai-frontier/custom-jev-memory-articles-2026-09-25.md`. Full pins and primary-source notes are in `evals/decision_models/SOURCES.md`.

## Design and scope

Thirty synthetic, hand-labelled cases: six each for routing, retry/escalation, evidence completeness, tool selection and fictional ads rules. Two serial passes per model, one excluded warmup: **300 measured calls, 30 unique cases**. Repetitions are not independent examples. “Use ads” was ambiguous, so general use cases and a separate ads subset are both included.

Only state, question and options were sent; gold labels and rationales were withheld. Fixed option order; no threshold fitting or domain training. The raw fixture SHA256 is `f8fd2c484aeb7e9ebde260c158458c8e369729636b9b5709845000e3ffb90c01`.

These are decision-call comparisons, not complete Beastmode/Luna runs. Production routing and gates are unchanged. No advertising action was taken.

## Measured results

All five arms produced 60/60 structurally valid responses with matching observed API model IDs or local model-file identities. Accuracy below means agreement with frozen labels, not proven production correctness.

| Model | Matches | Pass 1; pass 2 | Median ms | p95 ms | Input tokens | Reported output tokens |
|---|---:|---:|---:|---:|---:|---:|
| Jev 1.13.0 | 51/60 | 25/30; 26/30 | 235.4 | 297.6 | 24,564 | 2,554 |
| GPT-5.4 Nano | 51/60 | 25/30; 26/30 | 884.4 | 1261.6 | 9,928 | 762 |
| Simple Jev / Qwen3.5-4B | 52/60 | 26/30; 26/30 | 470.6 | 587.0 | 69,288 | 60 |
| Decider 0.8B Q4 | 32/60 | 16/30; 16/30 | 628.3 | 4312.0 | 8,544 | 60 |
| Decider 4B v2 Q4 | 48/60 | 24/30; 24/30 | 22523.7 | 63860.1 | 8,544 | 60 |

Per-category matches out of 12 calls, representing six unique examples:

| Model | Routing | Retry | Evidence | Tools | Ads |
|---|---:|---:|---:|---:|---:|
| Jev 1.13.0 | 8 | 10 | 10 | 11 | 12 |
| GPT-5.4 Nano | 9 | 11 | 9 | 12 | 10 |
| Simple Jev / Qwen3.5-4B | 10 | 8 | 12 | 10 | 12 |
| Decider 0.8B Q4 | 6 | 2 | 10 | 8 | 6 |
| Decider 4B v2 Q4 | 10 | 8 | 12 | 8 | 10 |

The ads cases concern supplied fictional asset/format/claim rules, not platform compliance or legal accuracy. Jev and Simple Jev matched all six examples twice; that is encouraging for triage, insufficient for an approval gate.

Retry handling needs particular attention. Decider 4B chose “stop” for both first-transient-failure cases on both passes; 0.8B missed five of six retry cases per pass. Jev and Nano also made retry errors. Six tool cases were matched by Nano on both passes; a deterministic tool rule remains preferable when the required facts are already structured.

## Faster, cheaper, fewer tokens?

**Latency:** Jev's 235.4 ms median versus Nano's 884.4 ms is 3.76× faster. Simple Jev's 470.6 ms is about 1.88× faster. Network-inclusive hosted calls and local calls share a wall-clock metric but not hardware or deployment conditions.

**Cost for 60 measured calls:** Nano returned **$0.0029381** in provider usage. Jev's **$0.001031688** is an estimate from 24,564 reported input tokens and the [published $0.042/M input price](https://docs.typesafe.ai/models); output is listed as free. Jev's actual bill was not returned. That estimate is 64.9% lower, approximately **$31.77 saved per million similar decisions**. Simple Jev demo and local actual costs were not reported.

These costs exclude warmups, failed preflights, Grok research, build/setup and orchestration. They are not the total cost of this investigation. Nano reported no cached input tokens.

**Tokens:** Jev reported **27,118 total**, versus Nano's **10,690**: **2.54× as many**, not a saving. Simple Jev reported **69,348** (6.49× Nano), despite one output token per call. Both Decider sizes used **8,604** (19.5% fewer). Different tokenizers and internal templates make token count an accounting measure, not a direct cross-model compute measure. Non-generative decisions do not imply zero reported output usage.

Local inference is not free. At observed mean wall time, serial operation and 100% utilization, the maximum allocated machine cost to break even is:

| Local arm | Mean seconds/call | Break-even $/hour vs Jev estimate | Break-even $/hour vs Nano |
|---|---:|---:|---:|
| Decider 0.8B | 1.073 | $0.05769 | $0.16429 |
| Decider 4B v2 | 26.633 | $0.002324 | $0.006619 |

Formula: `API dollars/call × 3600 / observed seconds/call`. This excludes startup, idle time and operations overhead, assumes the charged resource is dedicated to this serial workload, and uses highly host-dependent timings. It is not a GPU cost projection or a measured local bill.

## Hardware, pins and timing limitations

Local runtime: llama.cpp commit `2145525a4081d66ff1a87cf43ef809f95a85ac0c`, Release CPU build, four threads, 2,048-token context, one slot, prompt cache disabled. Host: WSL2, Intel i7-10700, 12 exposed logical CPUs, about 11 GiB RAM, no NVIDIA runtime, shared with other active workloads. A late-run snapshot showed approximately 6.9 GiB swap in use and load average around 9–11. It does not establish how much pressure any one process caused.

4B file SHA256: `f7e2e510ef51d212ea9b7fb8bf27906b5f516d7939ca847428fb91f6a8acfa79`, matching the publisher's GGUF provenance. The upstream v2 tag resolves to `49564ddcfccafb6db563eb757c1d41e6c78dcb56`; weights/config/tokenizer blobs match benchmark commit `7ab294cbdf6be6ac17fc818c10cdead744393d92`. We did not reproduce quantization. This is v2, not latest v2.1.

The adapter reads exact option-letter pre-sampling log probabilities, requires every label, divides by release temperature (4B: 1.935; 0.8B: 1.03), then normalizes and independently chooses argmax. One transport token exposes logits and is counted. Grammar post-sampling probabilities were avoided because rejection sampling may leave them unmasked.

4B startup took approximately 74.5 seconds and is excluded. A loading-time 503 was followed by readiness from the same server. Our graph indexing briefly overlapped the first seven completed 4B rows, was cancelled, then rerun after all inference and server shutdown. Unrelated host workloads continued. Second-pass results remove that known index overlap but are **still not isolated measurements**.

| Model | Pass 1 median ms | Pass 2 median ms |
|---|---:|---:|
| Jev 1.13.0 | 229.8 | 244.7 |
| GPT-5.4 Nano | 879.5 | 887.1 |
| Simple Jev / Qwen3.5-4B | 493.5 | 463.7 |
| Decider 0.8B Q4 | 608.7 | 740.8 |
| Decider 4B v2 Q4 | 19210.2 | 23087.0 |

The 4B second-pass median remained 23.1 seconds. Dedicated hardware, different quantization, batching or a GPU may change the result; none was measured here.

Simple Jev's default urllib client received HTTP 403/code 1010 before any measured call. A truthful benchmark User-Agent was accepted. Failed warmup and corrected-run receipts are preserved; scientific inputs were unchanged.

## Label ambiguity and confidence

An independent blind review saw only cases and protocol. It found all gold labels defensible, but three had plausible alternatives: routing-03/routing-04 (frontier versus blocked), evidence-04 (missing current receipt versus contradictory older receipt). Original labels and headline results remain unchanged.

A **post-hoc diagnostic** excluding those three cases gives Jev 51/54, Nano 50/54, Simple Jev 48/54, Decider 4B 44/54 and 0.8B 30/54. This is not a replacement benchmark; the sensitivity itself shows why a 30-case ranking is fragile.

At `p_max ≥ 0.9`, primary-set wrong decisions/covered calls were Jev 2/47, Simple Jev 0/36, 4B 2/36 and 0.8B 4/20. Nano did not expose comparable probabilities. After the ambiguity exclusions: Jev 0/45, Simple Jev 0/34, 4B 0/32 and 0.8B 4/18. Repeated examples and tiny samples cannot establish calibration or a safe threshold. These calculations use maximum option probability, not Jev's separate confidence field.

## Recommendation for Beastmode

1. **Keep deterministic structured gates.** Existing `route_by_verification_cost` measured about 0.3 microseconds/call across 500,000 calls with zero API tokens. That excludes extracting flags from prose and is not a like-for-like semantic classifier.
2. **Try Jev first in shadow/advisory mode for prose triage.** Record suggestions alongside the existing decision; review disagreements before considering integration. Evidence completeness and fictional ads triage are plausible uses. Do not give it permission, merge or completion authority from this test.
3. **Explore Simple Jev for an open-model deployment experiment.** It matched 52/60 labels, including all evidence and ads examples, but demo price and production latency remain unknown.
4. **Do not adopt Decider 0.8B as a general controller from these results.** Its retry errors and confident mistakes outweigh its small token footprint here.
5. **Keep Decider 4B v2 as a targeted hardware/domain retest candidate.** It improved sharply over 0.8B and matched all evidence labels, but the observed CPU run was slow and only 80% overall. AnyJev becomes interesting when a reviewed real Beastmode dataset supports held-out calibration or learned heads.

The next useful experiment is held-out, reviewed real decisions with fixed schemas and representative load, followed by whole-workflow measurements. This spike supplies reproducible evidence for choosing that experiment, not a production promotion.

## Reproducibility and verification

Source checkout started at `6e668a5`. Runners, frozen protocol/cases, primary sources, tests and this report live in `evals/decision_models/`. Raw responses, metadata, warmups, failed transport attempt, Grok discovery, model receipts, hardware conditions, independent aggregation and SHA256 manifest live in `results/2026-09-26/`. Model weights, credentials and build products are excluded.

Director verification: 17 harness tests passed; independent analyzer validated all 300 rows, exact payloads, complete case/pass coverage, usage, model identity and local raw-logit decisions. Separate checks matched every hosted answer/probability and Nano cost to its raw response. Final graph/diff/archive checks are recorded in `results/2026-09-26/validation.json`. The full change analysis retains an aggregate `critical` risk rating; director review found changed symbol paths confined to the evaluation and its skill documentation, with no production runtime diff. Its structured result has no partial/truncated flag. Graph indexing separately warns that global flow enumeration is truncated; no absence of a flow is treated as proof of no impact.

Reusable evaluation lessons were added to `evals/effectiveness/SKILL.md`: pinning quantization, raw-logit semantics, label mapping, token accounting and decision-call versus whole-agent economics. No production behavior was changed.

Durable knowledge path: `content/ai-frontier/beastmode-jev-decision-spikes-2026-09-26.md`.
