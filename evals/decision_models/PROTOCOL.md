# Jev-style decision model spike

Goal: measure whether typed decision models can make Beastmode control decisions faster,
cheaper, or with fewer generated tokens while preserving correctness.

This is an isolated evaluation, not a runtime routing change. Final reviews, permissions,
credential handling, and promotion remain director-owned.

## Acceptance contract (2026-09-26)

- Recover Content Machine research, research current candidates with Grok, verify primary sources.
- Run several actual models, explicitly pinning Decider 4B v2 rather than latest.
- Compare synthetic, hand-labelled Beastmode routing, retry/escalation, evidence-completeness,
  and tool-selection cases; include an exploratory ads subset because the request's wording
  is ambiguous. These cases are smoke tests, not representative production traffic.
- Freeze cases before inference; report per-use-case accuracy, invalid outputs, latency,
  prompt/generated tokens, provider-reported cost when available, and local cost assumptions.
- Use identical state, question and options across candidates. Preserve raw responses and
  requested/observed model versions. Record quantization and hardware; distinguish local
  compute from network-inclusive latency. Never claim quantized results reproduce bf16.
- Compare a cheap generative API baseline, hosted Jev, hosted Simple Jev, and two local Decider sizes if live.
  Additional base-model logit/generation comparison is exploratory, not AnyJev itself.
- Make no production change from this small sample. Preserve deterministic policy gates.
- Save the research and measured result in MemroOS and verify the read-back.

## Measurement

Use 30 cases (six per category), fixed labels and option order, two passes per candidate.
First pass and repeated pass reported separately; repetitions are not independent new examples.
Local requests disable prompt caching; one untimed warm-up is excluded. Serial calls, no
concurrent inference between candidates. Network providers may cache; record reported usage.
Read Decider probabilities at its exact `Answer: (` slot over the supplied option-letter
tokens, with release temperature (4B v2: 1.935; 0.8B v1: 1.03).
The llama.cpp transport samples one token to expose pre-sampling logits; report that token
as transport generation, not zero. Read the top 512 unmodified log probabilities, require
every option-letter token to be present, and normalize over those letters after division
by the release temperature. A missing letter is an invalid result, never a zero probability.
Do not use post-sampling grammar probabilities: rejection sampling can leave those unmasked
when the first sampled token is already legal. Verify API probability semantics before running.
Never interpret normalized confidence as p_max. No confidence threshold fitted on test labels.

Latency: wall-clock p50/p95, plus backend prompt/decode timings when returned.
Cost: reported API cost preferred; published-rate estimates explicitly labelled; local
hardware/electricity unknown, show break-even machine dollars/hour rather than calling it free.
Tokens: provider prompt/completion usage and local tokenizer counts; distinguish input processing
from avoided prose generation. Do not infer whole-agent savings from decision-call savings.

## Verification and risk

GitNexus index refreshed at source commit 6e668a5. Upstream impact for
`route_by_verification_cost` returned UNKNOWN (zero resolved callers); text confirmation found
tests and re-exports. The runtime is untouched; new files live only under this evaluation.
Index flow enumeration itself reports truncation, so absent graph flows are not an all-clear.
Director verifies fixtures, adapter logits/token accounting, result denominators and files.
Run evaluation unit tests, validate raw result totals, and graph change analysis before any commit.

Assumptions: “comparison models” means Jev-style decision models; “use ads” may mean use cases.
Open question sent to user; ads subset kept separately. No model training, deployment, or
paid infrastructure provisioning is part of this spike.
