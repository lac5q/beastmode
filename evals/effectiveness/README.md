# Effectiveness harness

This directory contains the stdlib-only runner for protocol amendment A. It
does not create director plans, reviews, retries, or model calls implicitly.
`prepare` freezes the task inputs, prompt templates, plans, code inputs, seeded
24-block schedule, and 72-cell final matrix under `runs/<id>/`. An existing run
identifier is never overwritten.

The research worktree supplies the protocol, fixtures, prompt templates, and
plans. A production preparation command is:

```sh
python3 evals/effectiveness/harness.py prepare \
  --run-id 20260911-main \
  --fixtures evals/effectiveness/fixtures \
  --protocol evals/effectiveness/PROTOCOL.md \
  --prompts evals/effectiveness/prompts \
  --plans evals/effectiveness/plans
```

The four call stages are `single`, `self_revision`, `beast_initial`, and
`beast_revision`. Execute one already-authored, fully rendered prompt
explicitly. The harness does not render templates or fill placeholders:

```sh
python3 evals/effectiveness/harness.py invoke \
  --run evals/effectiveness/runs/20260911-main \
  --task task01 --rep 1 --stage single \
  --prompt /path/to/rendered/task01_rep1_single.txt
```

The invocation retains the exact prompt, raw JSONL, final output, optional
candidate module, timestamps, exit status, returned usage, requested model
configuration, and restricted runtime `turn_context` evidence. Tool use,
ambiguous output, missing `solve`, syntax errors, timeouts, and missing or
mismatched runtime evidence remain explicit invalid or unsolved outcomes.

Score one retained artifact with:

```sh
python3 evals/effectiveness/harness.py score \
  --run evals/effectiveness/runs/20260911-main \
  --task task01 --rep 1 --stage single
```

Each private case runs in a fresh bubblewrap namespace with no host home,
network, or inherited environment. The scorer requires an operational
`bwrap --unshare-all` setup, a 256 MiB address-space limit, a 2 second CPU
limit, a 5 second wall limit, and a 1 MiB stdout limit. It fails closed if
those guarantees cannot be established; there is no direct-process fallback.
Expected values stay in the parent scorer and are never sent to the candidate.

Analyze retained score records with fixed planned denominators and task-level
paired bootstrap intervals:

```sh
python3 evals/effectiveness/harness.py analyze \
  --run evals/effectiveness/runs/20260911-main
```

The analysis reports artifact quality separately from provenance validity,
missing cells, per-case fractions, observed token/time fields, primary
12-task and adjacent-pair six-family bootstrap checks, and a warning for
degenerate paired intervals. Dollar costs are omitted when authoritative
billing units are unavailable. No effectiveness calls have been made by this
harness construction.

Run the focused tests with:

```sh
python3 -m unittest discover -s evals/effectiveness -p 'test_harness.py' -v
```
