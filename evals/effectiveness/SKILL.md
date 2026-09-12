---
name: beastmode-effectiveness-evaluation
description: Design, execute, and report controlled Beastmode effectiveness studies with held-out grading and reproducible provenance.
---

# Beastmode effectiveness evaluation

Use the Beastmode framework for role separation and pinned workers. An evaluation tests a hypothesis; a favorable outcome is never an acceptance criterion. Read the study's frozen protocol before operating its runner.

## Lessons from construction

- Freeze a machine-readable fixture schema before parallel authors start. Validate one example from each author against the shared validator immediately. Natural-language descriptions of the schema are insufficient: this study's two authors produced different mutant representations (source strings versus named source objects), and their separate checks both passed while integration failed. Normalize representation without changing source, verify source hashes, and rerun integrated validation before any trial.
- Validate reference outputs independently. Generating all expected values from the same reference and then checking the reference against them is circular. Include independently reasoned cases and a separate semantic reviewer.
- A clean revision cannot erase forbidden tool use or missing model provenance in its initial artifact. Preserve dependency validity through the final arm's reporting.
- Runtime metadata identifies configured model/reasoning, not an independently attested backend snapshot. Preserve both the requested identity and the exact evidence available.
- Distinguish candidate failure from infrastructure failure. Broken sandbox setup must stop grading rather than turn every candidate into a wrong answer. Decode malformed output inside the failure boundary and bound CPU, wall time, memory, and output.
- Keep expected outputs and reference files outside the candidate's sandbox. Freeze director plans before generation; withhold held-out scores until every review is finished. Shared baseline outputs must be explicit dependencies, not misrepresented as independent samples.
- Count paired task units, arm outputs, and model calls separately. Match claims to the actual resource control: equal executor-call counts do not equal total compute when a director adds planning and review.
- Bootstrap at the task level and disclose related task families. A degenerate interval on a small saturated sample is not proof of equivalence.
- Read the primary paper's exact version. Search snippets can retain numerical claims from an older version; record the version used in the related-work notes.

## Study-specific sources

The executable contract, frozen schedule, failure rules, and analysis choices belong in PROTOCOL.md and the run manifest. This skill stores reusable procedure lessons; it must not duplicate or substitute for the study's results. Save research deliverables through MemroOS and verify read-back. Do not update an in-progress study's frozen inputs after seeing outcomes to obtain a favorable result.

## Model-provenance pitfall

Bind a child-model receipt to that child's exact thread identity. A parent or unrelated transcript may mention the child ID; its model context is not evidence about the child. Match the exact rollout filename and session metadata ID, inspect only actual top-level turn-context records, and reject mismatches. Never scan arbitrary transcript content for an ID and then accept that file's model. Include an adversarial test with a wrong-model child and a correct-model parent mentioning it.

## Prompt rendering pitfall

Validate placeholder names in the template before substituting task data. Do not reject arbitrary doubled braces in the rendered result: nested JSON naturally contains consecutive closing braces, and source code or specifications may legitimately contain template-like text. Prefer one-pass substitution of known template tokens so inserted data is never reinterpreted as a template. Preflight every frozen task/stage prompt with representative initial code and reviews before generation.

If this guard fails mid-run before a model launch, retain the failure receipt and frozen files. Explicitly render the same intended prompt, verify its known substitutions and hash, and use the frozen invocation CLI with its schedule/provenance checks when that preserves the protocol. Record this operational deviation in the paper; do not silently patch a frozen driver, alter task wording, or rerun completed candidates.

## Interrupted orchestration evidence

Stream child stdout/stderr to durable per-call files while collecting them; buffering until process completion loses evidence if the harness is terminated. If the harness dies, inspect the exact child PID before declaring interruption. Preserve the original running record and observed process exit separately from the unknown model exit. Never infer pre-response retry eligibility from missing buffered output. Keep unknown provenance and dependent revision invalidity visible; use the protocol's missing-output sentinel when appropriate.
