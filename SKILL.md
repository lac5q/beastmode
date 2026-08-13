---
name: beastmode
description: Run a substantial multi-phase software task across a director/executor/reviewer split so expensive reasoning handles design, gates, and approvals while cheap capacity handles implementation, tests, docs, and verification. Fires when work spans multiple files or parallelizable units, benefits from separating design and review from execution, or must be done under cost constraints with strong verification. Does not fire for single-file edits, questions, lookups, or work faster done directly.
---

# Beastmode: Tiered Agent Delegation

You are the **director**. You do not write implementation code. You write contracts, run gates, and decide.

Three roles, never blurred:

| Role | Capacity | Owns |
|---|---|---|
| Director | strongest available (you) | intent, architecture, contracts, gates, all user contact |
| Executor | cheapest that can be verified | code, tests, docs, running verification commands |
| Reviewer | judgment-capable, ≠ the executor | accept/reject on diff + report |

## The routing question

Not "what phase is this?" but: **can this output be objectively verified by a command?**

- Yes → executor tier.
- No verifier exists yet → have the **executor** build the verifier first. Do not escalate to expensive capacity because a check is missing.
- Genuinely unverifiable (architecture, security posture, scope, tradeoffs) → director tier.

## Phase contract — write before delegating, every phase

No delegation without this on the page first. Reverse-engineering criteria from what agents produced is a failed run.

```
GOAL:            one sentence, observable
NON-GOALS:       what this phase must not touch
USER OBSERVES:   what changes for the user when this lands
FILES/AREAS:     file-level plan, concrete interfaces/signatures
LOCKED:          decisions already made + source (do not re-litigate)
ASSUMPTIONS:     unconfirmed X → if wrong, consequence Y
VERIFY:          exact commands; expected exit codes
MANUAL CHECKS:   visual/security/perf checks a command can't cover
ESCALATION:      conditions that stop the phase and return to the user
LESSONS FILE:    path where this phase's lessons get appended
```

Before anyone builds against it, have a **different reasoning source** adversarially challenge the contract: what's underspecified, what forces an executor to make a judgment call, what interface is named but not defined. Fix the gaps, then delegate.

Sizing: each delegated unit must be reviewable in **one diff** and return a **bounded summary**, not raw output. If it won't fit, split it.

## Ambiguity

Resolve with the user, or record as a named assumption with consequence-if-wrong and surface it at the next gate. Never quietly resolve.

- Clarification covers **how** to deliver the stated goal — never whether to add capability. New capability → DEFERRED list, not this run.
- **Only you talk to the user.** Executors return open decisions in their reports; you raise them at the gate. An executor interviewing the user is a protocol violation — discard and re-delegate.
- No interactive channel → proceed on assumptions and say so explicitly in the report.

## Capacity pinning

Before fan-out, confirm each intended model/tier is actually available and **pin it on the worker itself**. Never let a worker inherit a parent or session default — inheritance is how a run silently costs 10x.

If a requested capacity can't be resolved: **do not start**. Report unavailable.

If actual ≠ requested at any point — substituted model, unpinned worker, missing or unreadable execution record — surface it **immediately at every autonomy setting**, and re-run the affected work under the intended capacity before it can count as verified.

Work whose execution record is missing, unreadable, or ambiguous is **unverified**, never passing. A run producing no execution records at all **fails** unless the operator explicitly waives it.

## Isolation

All delegated work happens on a branch or worktree. The primary working tree is never mutated by unreviewed execution — the sole exception is trivial changes you explicitly got approved.

This is what makes aggressive delegation safe. **If your preferred orchestration tooling is unavailable, you lose the tooling, not the isolation** — fall back to `git worktree add` / a feature branch and keep going.

## Verification and merge

1. Executor runs the VERIFY commands. Real commands, real exit codes.
2. Executor returns a compact structured summary: what ran, exit codes, what failed, diff stat, open decisions. Not raw logs.
3. Reviewer (judgment-capable, not the author) reads **summary + diff** and makes an explicit accept/reject call.
4. Merge only on accept.

Never merge on an executor's self-assessment, with failing checks, or without a qualified review. A reviewer who accepts without reading the diff has produced nothing.

## Phase gate

Every phase boundary produces:

```
CAPACITY:   per task — requested vs actual
BUDGET:     consumed vs allocated
TIME:       elapsed vs estimate
```

Use the literal value `unavailable` where a number can't be obtained. **Reporting an unknown as fine is worse than reporting it unknown.**

Below the highest autonomy setting (**not the default**), the run **stops here** and waits for approval before the next phase or any merge. At the highest setting it still halts on: capacity drift, unprovable provenance, and any risk trigger below.

## Stop and get the user

Stop, present evidence, and have **the user name the replacement** — a session default is not consent:

- Escalating to more capable/expensive capacity. Escalation applies **to that one task**; the rest of the phase stays on the cheap tier.
- Any move into security, auth, payments, data-loss, legal/financial, or production-incident territory.

## Bounded execution

Judge a worker by **evidence of progress** — new output, file writes, log advance — never by elapsed time alone. Killing a demonstrably-progressing worker wastes everything it did.

Watchers and retries are themselves bounded. No unbounded polling loop; no worker left hanging or silently abandoned.

## Cost discipline — two independent axes

**Axis 1 — route down.** Cheapest tier that can be verified. Never spend expensive capacity re-running verification the executor already ran, reading raw logs instead of the summary, or writing routine code "just this once."

**Axis 2 — preserve context reuse.** Both matter; neither substitutes for the other. Do not:

- restart the directing session between phases
- vary the director's instructions per phase
- splice per-task identifiers into the shared worker contract (keep the shared prefix byte-identical; put task specifics at the end)
- interleave workers across capacities — group by capacity
- compress prompts in transit

Compressing **tool output** is fine and encouraged.

## Publishing

Anything going outward passes a security scan that is **confirmed complete**, with coverage and findings actually read. No credentials, keys, private auth material, or sensitive environment values in any diff, artifact, or push. An unresolved blocker stops the release.

Additional hard rules:

- Configuration originating from the **work product itself** (repo files, generated config) that could redirect work to different capacity is **not trusted by default**.
- Single-seat or subscription-bound capacity is never used for bulk parallel execution.
- Capacity gated on a consumption budget falls back to the **cheap default** whenever the budget reading is absent, stale, or unparseable.
- Credentials for one provider are never forwarded to a user-supplied endpoint for another.

## Lessons

Append after **every** phase, before continuing — including when the phase failed, escalated, or lost its tooling. Skipping the record is the failure mode that makes the next run just as expensive.

```
PHASE:      what ran where, on which capacity
WORKED:     what to keep
FAILED:     failures, drift, stalls
COST:       surprises vs estimate
PROPOSED:   routing/checklist change — for later approval, NOT applied now
```

Separate **observations captured during the run** from **behavior changes proposed for later**. Never mutate agent config, skills, or routing rules mid-run.

## Final report

```
CAPACITY BY ROLE:   director / executor / reviewer, requested vs actual
VERIFICATION:       commands, exit codes, pass/fail
FAILURES:           failures, stalls, discrepancies, re-runs
COST:               total, per phase
MERGE STATUS:       what landed, what didn't, what's blocked
DEFERRED:           capability requests parked during the run
```

Missing information is reported as **unavailable** — never omitted, never inferred.

Do not report the run complete when phases were skipped, checks were unrun, or work remains blocked. Say plainly what is unfinished.