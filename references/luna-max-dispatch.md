# Luna Max dispatch

Load this procedure with the `beastmode` skill when routing work.

When this skill loads, resolve the trusted profile first: a non-empty
`BM_DEFAULTS_FILE`, otherwise `~/.beastmode/defaults.json`. Never read
checkout-local defaults. Saved model seats and harness choices are standing
explicit selections until changed; current task requests and CLI flags override
them. The profile selects requested routing only. It cannot change permission
policy or prove which provider, model, or effort is actually serving a session.
If the current director cannot match its configured model or effort, report the
mismatch, identify the actual serving model if known, and use the matching
launcher on the next run. Never claim the session switched itself.

Standing Beastmode rule: menial work goes to the configured economy seat. If
neither a trusted profile nor the current task selects a seat, use Luna Max
(`openai-codex/gpt-6-luna`) with maximum reasoning. The current agent stays
director, reviewer, and merge gate.

Classify each unit of work as you start it, and re-classify as the work changes
shape. Do not ask permission to downshift when an approved economy seat is
already selected. Route, then report what ran where.

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
- Route menial work to the saved or currently requested economy seat. If no
  explicit standing/current seat exists, default to Luna Max at max reasoning.
  Use the launcher that matches the selected provider/model. Codex lanes:
  `adapters/codex/SKILL.md`.
- Use the selected effort and verify the live model before dispatch. Never
  claim a profile selection proves the actual model or effort.
- Hand the worker a bounded slice: scope, allowed files, acceptance checks.
- Review worker output and run the real checks yourself.
- An explicitly selected lane fails closed by default. The sole authorized
  exception is a configured `limit_fallback` (trusted profile) or current
  `--limit-fallback` for a recorded provider quota/rate-limit failure: route
  one agent-level retry of the same bounded contract, preserve the original
  failure and requested/actual model receipts, and report failure if the
  fallback is also limited. Authentication/network errors, missing
  provenance, unsupported models, invalid output, and other failures do not
  authorize fallback. With no configured fallback, report the seat failure.
  `bm` supplies routing guidance; it does not retry provider subprocesses.
  Only when no explicit standing/current choice applies and no quota recovery
  is authorized may the director use the cheapest available configured worker,
  then the cheapest subagent, then work inline.
- Name the lane that actually ran.

## Never

- Never wait to be told to delegate.
- Never let a worker commit, push, access secrets, or claim final verification.
- Never spend director tokens on a mechanical pass the live economy lane could do.
- Never delegate architecture, security, impact analysis, or planning.
