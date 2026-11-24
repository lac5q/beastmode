# Agent-folder use cases — 2026-09-27

## Decision

Prefer an optional decision provider automatically **after it is proven better
for the specific use case**, with a working deterministic/director fallback.
Availability alone is not qualification. This is now explicit in the canonical
Beastmode skill and model-routing reference. No runtime dependency or mandatory
Jev call is introduced by this study.

The folder pattern is useful: preserve evidence state, bound model choices,
keep code in charge of side effects, and retain receipts. Its five questions
need different treatment; replacing all five with model calls is not supported.

## Measurements

| Hosted arm | Matches / attempted | Valid answers | Median / p95 latency | Measured request cost |
|---|---:|---:|---:|---:|
| Jev 1.13.0 | 64/64 | 64/64 | 632 / 3,066 ms | $0.0012075 estimated input cost |
| GPT-5.4 Nano, OpenRouter | 57/64 | 61/64 | 1,771 / 8,715 ms | $0.00344145 known subtotal; full cost unknown |
| Simple Jev Qwen3.5-4B demo | 58/64 | 64/64 | 611 / 1,730 ms | Unknown |

Latency includes failed measured requests; warmups are excluded. Calls were
serial, with Jev first, Nano second and Simple Jev third, so network/service
conditions are confounded with arm order. These are client-observed results
from this run, not provider-wide latency guarantees.

| Use case (8 unique cases, two passes) | Jev | Nano | Simple Jev |
|---|---:|---:|---:|
| Next worker | 16/16 | 14/16 | 14/16 |
| Relevance | 16/16 | 11/16 | 12/16 |
| Done | 16/16 | 16/16 | 16/16 |
| Risky | 16/16 | 16/16 | 16/16 |

Jev was correct on both 32-case passes. Nano scored 32/32 then 25/32: three
second-pass transport failures (`next_worker-05`, `next_worker-06`,
`relevance-01`) and four different relevance labels. Its valid-response score
was 57/61; failures stay in the 64-attempt denominator. No retries were made.
Simple Jev scored 29/32 on each pass, repeatedly selecting research instead of
writing in `next_worker-03`, and keeping the duplicate/unrelated outputs in
`relevance-05` and `relevance-06`.

No returned answer made one of the four prespecified dangerous errors: false
completion, classifying a known/unknown side effect as read-only, dropping a
required keep item, or dispatching when the gold was wait. This does not imply
zero operational risk: Nano dropped an **uncertain** item and lost a required
keep response to a transport failure. Preserve evidence and fall back.

At descriptive p_max >= 0.9, Jev covered 51/64 calls and Simple Jev 42/64,
with no wrong covered labels. Nano supplied no probabilities. These figures
are coverage observations on an easy synthetic set, not calibrated risk bounds.

Reported measured input/output tokens were 28,750/2,650 for Jev,
12,501/753 for Nano's 61 responses, and 85,908/64 for Simple Jev. Missing usage
and possible billing for Nano's three transport failures remain unknown.
Each arm also made one excluded warmup: Jev 479/45 tokens (estimated
$0.000020118), Nano 233/12 ($0.0000616 reported), and Simple Jev 1,487/1
(price unknown). Including warmup, known Jev inference estimate is
$0.001227618 and known Nano subtotal is $0.00350305. This excludes evaluation
labor, drafting, tools, infrastructure, and downstream error costs.

Jev is the strongest hosted candidate on this screen, particularly relevance.
The outcome supports continued evaluation with real traces; it does not prove
a benefit over the existing deterministic scheduler or completion checks.

## What each use case needs

| Use case | Evidence and implication |
|---|---|
| Model tier | The earlier routing subset scored Jev 8/12, Nano 9/12, Simple Jev 10/12. Six unique cases repeated twice are insufficient to replace Beastmode's verification-cost rule. Use a model only for genuinely ambiguous requirements. |
| Next worker | Beastmode's pipeline already has fixed phase transitions and ordered worker batches. Dependencies and active ownership belong in code. Ranking several eligible workers is a separate, untested question. |
| Relevance | Models can classify optional context. Required failure logs, contradictory evidence and original receipts must remain available even when an output is excluded from the current prompt. |
| Done | Current receipts, hashes, acceptance predicates and open work determine completion. A model may flag semantic gaps; its confidence cannot replace verification. |
| Risky | Classify the actual operation and arguments. Code still enforces scope, permissions and approvals. An opaque wrapper is unknown; a high-confidence label does not authorize execution. |

Source inspection: `python/src/beastmode/core/routing.py`,
`python/src/beastmode/langgraph/graphs/pipeline.py`,
`python/src/beastmode/langgraph/dispatch.py`, and
`scripts/lib/goal_lifecycle.py` (`_run_verify_commands`, `_review`, `_provenance`).
The source checkout was `4efeb0a660a408d22e756e8629f5027a7148dff0`.

## Study boundaries

The [protocol](AGENT_FOLDER_PROTOCOL.md) froze 32 synthetic examples, eight per
new category, before inference. Each arm runs two serial passes (64 requests)
plus one excluded warmup. All arms receive the same state, question and options;
gold labels and rationales are withheld. Actions are never executed.

These are clean, short descriptions with explicit policies and simple quoted
injection attempts. Many labels are directly computable once facts are
structured. This checks whether a model applies a supplied policy; it does not
measure extracting trustworthy state from real tools, sustained adversarial
resistance, eligible-worker ranking, end-to-end task success, or a latency/cost
win over deterministic code. There is no measured code baseline and no tuned,
held-out confidence calibration. Perfect accuracy here cannot qualify a general
default. The two passes are not 64 independent examples.

Director review clarified ambiguity before freezing: gatherable missing facts
versus blocked dependencies; stale evidence versus a missing deliverable;
possible spreadsheet relevance versus known coincidence; stdout versus file
logging; and non-mutating public GET versus message delivery. Labels were not
changed after inference. The worker draft used the available GPT-5.6 Luna max
fallback lane; backend identity was not independently attested. The director
reviewed every label and the analysis implementation.

## Price and confidence claims

The quoted $0.42 for 10,000 decisions assumes approximately 1,000 billable input
tokens each at $0.042/million input tokens. It excludes generation, tools,
retries, review and error costs. A call median is not full-step latency.
[TypeSafe model documentation](https://docs.typesafe.ai/models).

Jev returns option probabilities and a separate confidence field. Neither is
a permission grant; a generic 0.95 threshold does not prove calibration on a
new task. This report uses p_max >= 0.9 descriptively, without fitting a
threshold or equating p_max with confidence.
[TypeSafe confidence documentation](https://docs.typesafe.ai/confidence).

The user-supplied post/commentary is the motivation for this test. Claims about
the author's posting habits, independent Claude comparisons and release timing
were not established by this study.

## Reproduction and evidence

Raw responses, excluded warmups, run metadata, commands, the pre-inference freeze
receipt and analysis are in `results/2026-09-27-agent-folder/`. The manifest
records SHA256s. Hosted observed model IDs are service-reported identifiers,
not independent attestation of immutable backend weights.

The original September 26 corpus and 300-call archive remain unchanged. See
[RESULTS.md](RESULTS.md) for that separate experiment and [README.md](README.md)
for the follow-up analysis command.

## Validation

All 28 targeted harness and audit tests pass, including fabricated response
fields, altered model pins, leaked labels, metadata hash drift, duplicate rows,
partial archives and unavailable providers. All 192 measured records and the
raw responses for three excluded warmups were independently checked.

GitNexus reports HIGH risk: 88 changed symbols and eight affected processes,
all eight in the new offline analyzer. The full result is archived; it is
neither partial nor truncated. No production runtime source was changed.
Pre-edit new-file lookups and documentation impact were UNKNOWN; literal
reference checks and source inspection supplied the missing scope evidence.
