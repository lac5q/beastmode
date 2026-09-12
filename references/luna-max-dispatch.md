# Luna Max dispatch

Moved out of always-on AGENTS.md on 2026-09-12 so Astra/Sol/Hermes sessions
do not pay this on every email. Load with skill `beastmode`.

Luis standing rule: menial work goes to a Luna Max coworker. The current
agent stays director, reviewer, and merge gate. GPT-5.6 Luna is the bounded
worker and must run with maximum reasoning.

This is automatic while Beastmode is in play. Classify each unit of work as
you start it, and re-classify as the work changes shape. Do not ask permission
to downshift. Route, then report what ran where.

Menial means mechanical and checkable without judging whether it was the
right thing: bulk find/replace, boilerplate, fixtures, format/lint, comment
tidying, log triage, changelog from a known diff, data reshape, the same
operation over a list the director already scoped.

Not menial (director keeps): architecture, security, secrets, impact analysis,
final verification, planning, commits, pushes, merges.

## Dispatch test

1. Checkable by inspection or a command, without judging whether it was the
   right thing? Menial.
2. Director already decided the approach, leaving only execution? Menial.
3. Same operation repeated over a list? Menial.
4. Getting it wrong costs a re-run, not a bad decision? Menial.

Any no that involves design, security, or a truth claim stays with the
director. When unsure, downshift with a tighter scope and review the result.

## Mid-flight

- Mechanical remainder downshifts. Do not finish it inline out of momentum.
- A menial task that surfaces design, security, or correctness escalates back.
- Long tasks split: mechanical slices down, judgment slices stay.

## Always

- Run the dispatch test unprompted when this skill is loaded.
- Route menial work to Luna Max when that lane is live. Prefer
  `bin/beast-luna` in memroos-product (pins `gpt-5.6-luna`, max reasoning).
  Codex adapter lanes: `beastmode/adapters/codex/SKILL.md`.
- Maximum reasoning on Luna Max workers. Verify the live model before sending.
- Hand the worker a bounded slice: scope, allowed files, acceptance checks.
- Review worker output and run the real checks yourself.
- If Luna Max is down: next configured lane, then cheapest subagent, then
  director-inline. Never claim Luna ran when it did not.
- Name the lane that actually ran.

## Never

- Never wait to be told to delegate.
- Never let a worker commit, push, access secrets, or claim final verification.
- Never spend director tokens on a mechanical pass a live Luna Max lane could do.
- Never delegate architecture, security, impact analysis, or planning.
