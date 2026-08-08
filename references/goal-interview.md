# Goal Interview

## Why

Silent assumptions are the most expensive failure mode in an agent run. A wrong
assumption made at design time multiplies executor waste downstream; asking the
operator costs one turn. The goal interview makes material user-visible choices
explicit before design begins and keeps new ambiguities visible at phase gates.

## The interview matrix

The autonomy level scales both the upfront interview and what happens to open
questions discovered during a phase:

| Level | Upfront | In-process | Question budget |
|---|---|---|---|
| low | `full` — present every material gray area, deep-dive until resolved; no material ambiguity survives unasked | `gate-questions` — every gate presents accrued open questions; each answered or explicitly deferred | unbounded |
| medium (default) | `batched` — one batched round of the top 3–5 impact-ranked questions; every remaining ambiguity becomes an explicit contract Assumption | `gate-questions` (same as low) | 5 |
| high | `batched` — the same single upfront round as medium; remaining ambiguity becomes contract Assumptions | `escalation-only` — after the contract is written, never block on questions again; open questions fold into the final report's Assumptions section; only escalation triggers interrupt | 5 (upfront only) |

`schema/autonomy-levels.json` is the source of truth for this matrix. When
prose and schema disagree, the schema wins. The `interview_protocol` key points
back to this reference.

## Gray-area identification

Gray areas are decisions that could go multiple ways **and** would change the
user-visible result. Generate areas specific to the goal. Do not use generic
labels such as `UI`, `UX`, or `Behavior` without naming the actual decision and
its effect.

Look for choices about:

- intent and the outcome the operator is trying to achieve;
- user-visible behavior, including what happens on common edge cases;
- scope boundaries and what is explicitly in or out;
- essential behavior versus nice-to-have behavior;
- references, examples, or products the user has in mind;
- non-goals and constraints that must remain protected.

Do not ask about:

- codebase patterns, which the director reads from the repository;
- implementation approach or which files/functions to use;
- architecture tradeoffs owned by the design tier;
- facts derivable from the repository or from prior decisions.

### Skip-decided rule

Before asking a question, check `GOAL_STATE.md`, `.planning/**/CONTEXT.md`,
`.planning/**/SPEC.md`, and prior gate answers in the current run. Never re-ask
a decided question. Import those decisions as locked decisions in the
acceptance contract and annotate each one with its source, for example
`locked: keep existing CLI flags (source: .planning/.../CONTEXT.md)`.

### Scope guardrail

The interview clarifies **how to do what is in the goal**, never **whether to
add a new capability**. A capability that is not already in the goal becomes a
`Deferred ideas` item, not an interview question. Do not use an interview to
expand scope or to turn a suggestion into an acceptance criterion.

## Question format

Ask in rounds. A batched round is one combined set, ranked by impact on the
user-visible result. Each question has:

1. a specific label that names the decision;
2. two to four concrete options;
3. one recommended default, marked `(Recommended)` and listed first; and
4. one concise consequence for each option.

The operator can always answer freeform, choose a combination, or state a
different constraint. Preserve the answer in the contract as a locked
decision, including a source such as `goal interview` and the gate or round
where it was answered.

For `low`, keep asking material questions until no material gray area remains.
For `medium` and `high`, ask one upfront batch of the top 3–5 impact-ranked
questions. The remaining ambiguities are not silently discarded: record them
as explicit assumptions with their impact if wrong.

## Assumptions ledger

The acceptance contract carries an assumptions ledger for anything not resolved
by the interview or imported decisions. Use this exact shape:

```text
- A<i>: <assumption> — impact if wrong: <one line> — status: unconfirmed | confirmed@gate<N>
```

An answered or explicitly deferred gate question becomes a locked decision or a
confirmed assumption. Do not hide a material choice in general prose. At high
autonomy, carry the assumptions ledger into the final report even when no gate
blocks on it.

## In-process open questions

Workers return open questions in their metadata; they do not interview the
user. A `needs_decision` item has this shape:

```json
{"id", "question", "options", "assumed", "impact_if_wrong"}
```

Each field means:

- `id`: a stable identifier for the item in the phase, such as `Q-201-01`;
- `question`: the concrete user-visible decision still unresolved;
- `options`: an array of concrete choices, with the recommended choice first;
- `assumed`: the choice the worker used to continue, if it could continue;
- `impact_if_wrong`: the one-line consequence of choosing differently.

A worker that hits ambiguity applies the acceptance contract's stated
assumption if one covers it, records a `needs_decision` item in `meta.json`, and
continues. If no assumption covers the ambiguity and the work is genuinely
blocked, it stops with `stop_reason: "needs_decision"`. Workers never contact
the user and never invent an interview round.

The director accumulates items from worker metadata, watcher review, and its own
review. At low and medium, every phase report includes `## Open Questions` or
`## Open Questions: none`. The gate is not passed until every item is answered
or the user explicitly defers it. A deferral converts into an Assumption with
an impact-if-wrong line. At high, accrued items fold into the final report's
Assumptions section; only an escalation trigger interrupts after the upfront
interview.

## Harness mapping

- **Claude Code:** use `AskUserQuestion` for upfront rounds and gate open
  questions. Ask no more than four questions per call and put the recommended
  option first. A headless `claude -p` lane downgrades to assumptions-only and
  logs `interview downgraded: non-interactive lane`.
- **Hermes:** use one combined `clarify()` batch per interview round. Never
  issue N parallel clarifies. Surface gate open questions through the same
  combined batch mechanism.
- **Codex:** interactive sessions use a numbered-list plain-text question set.
  `codex exec` is non-interactive, so it downgrades to assumptions-only and
  logs `interview downgraded: non-interactive lane`.
- **Pi:** use the question/ask tool for the round and for blocking gate
  questions.
- **LangGraph:** checkpoint the upfront interview with `interrupt()` before
  the design node. Gate open questions ride the existing `interrupt()` gates.
- **Any non-interactive lane:** automatically downgrade to assumptions-only,
  record the downgrade in the phase report, and preserve the assumptions ledger
  in the final report.

## GSD interop

If `.planning/` exists with a matching phase `CONTEXT.md`, import its locked
decisions instead of asking again. A matching `SPEC.md` is also a locked
decision source. Record the imported decisions and their file paths in the
acceptance contract.

When a repository already uses GSD, `gsd-discuss-phase` may serve as the
upfront interview. Its resulting `CONTEXT.md` is then the locked-decisions
input to the acceptance contract. Gate answers from the current run remain
locked for that run and are never re-asked.
