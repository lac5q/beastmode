# Agent-folder use-case follow-up — 2026-09-27

This separate exploratory study checks the user-supplied folder pattern. The
September 26 corpus and measurements stay frozen. Routing was already tested;
this follow-up adds next-worker selection, tool-output relevance, completion
evidence, and side-effect classification. It executes no selected action.

## Acceptance contract

- Freeze 32 reviewed synthetic cases: eight per new category, two serial passes
  per model. Repetitions measure stability, not independent new examples.
- Compare pinned Jev 1.13.0, GPT-5.4 Nano via OpenRouter, and the identified
  Simple Jev Qwen3.5-4B demo using the existing API runner unchanged.
- Send identical state/question/options; withhold gold labels and rationales.
  Preserve original order, raw responses, warmup, usage and observed model IDs.
- Report per-use-case matches, invalid/unavailable responses, coverage, p50/p95,
  reported tokens, actual Nano cost, estimated Jev input cost and unknown demo
  cost. Missing providers do not block the fallback or acquire a fabricated score.
- Count false completion, missed side effects, dropped relevant evidence and
  premature worker dispatch separately. A model's label never grants permission.
- Report descriptive p_max >= 0.9 coverage/errors; do not tune thresholds on this
  set or confuse Jev's separate confidence field with maximum option probability.
- Review the corpus before calls, especially unknown versus unmet, contradictory
  evidence versus irrelevant output, and planned operations versus quoted text.
- Preserve any failure. Do not silently rerun a poor answer or alter a gold label
  after seeing outcomes. Keep follow-up results separate from the earlier corpus.

## Default-selection policy to evaluate

Prefer a decision provider automatically for a specific use case after held-out,
representative evidence shows better quality at acceptable latency/cost, or lower
latency/cost at an accepted quality level. Availability alone is not qualification.
If unavailable, unconfigured, explicitly disabled, invalid or below a validated
threshold, continue through the existing deterministic/director path. No decision
provider is a required dependency of Beastmode.

Code retains action budgets, dependencies, approval checks, evidence validation
and side effects. A valid model choice, high confidence, or a generic threshold
such as 0.95 does not override them. Structured predicates are the baseline where
the necessary facts are already known; semantic classification is a separate job.

This small synthetic screen cannot by itself qualify a production default.
The user-supplied post and commentary are source material, not verified facts.
Published price is checked against TypeSafe's current model documentation; its
$0.42/10,000 figure assumes roughly 1,000 billable input tokens per decision and
excludes generation, tools, retries and review.

## Reproduction

Use `benchmark_api.py` with `--cases agent_folder_cases.json --repeats 2` and a
fresh output path for each provider. See the existing README for authentication.
The completed report and archive will record fixture/runner hashes, checks,
source checkout, exact CLI invocations and any provider-availability limits.
