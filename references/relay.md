# Relay: architect, improve, review

`bm relay "<task>" [--dir WORKSPACE] [--out RUN_DIR] [--fable-floor 25] [--dry-run]`
runs three fresh sessions, one after another:

| Stage | Seat | How it runs |
|---|---|---|
| 1. Architect | Claude Fable 5.2, effort medium | `claude -p --permission-mode plan`, read-only |
| 1. Architect (fallback) | Claude Opus 5.5, effort high | same, when Fable is short (below) |
| 2. Improver | Gemini 4 Neon XHigh (`gemini-4-neon-xhigh`) | `agy --mode accept-edits`, told to make everything better; may edit WORKSPACE |
| 3. Reviewer | Claude Opus 5.5, effort medium | `claude -p --permission-mode plan`, reviews plan + summary + diff |

## Fable floor

Opus 5.5 high takes the architect seat when Fable has less than `--fable-floor`
percent (default 25) left, when the reading is unknown, or when the Fable call
itself comes back rate-limited (one retry, recorded as `fallback_from`).

"Left" is 100 minus the busiest window Claude Code reports for a Fable call
(5-hour, 7-day, and any Fable-only window it reports). Claude Code does not give
scripts a Fable-only meter today, so this can read higher than the Fable bar in
`/usage`. Readings come from, freshest first and at most 15 minutes old:

- `~/.beastmode/state/fable-rate-limits.json`, saved from the last relay Fable call;
- `~/.beastmode/state/claude-statusline.json`, saved by `~/.beastmode/bin/statusline-tee`
  wrapped around the Claude Code status line command.

With neither, the relay spends one one-word Fable call to read the windows.

## Rules it keeps

- Claude seats run only in Claude Code (`claude -p`) on its signed-in login:
  `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL` are removed
  for them. `agy` never runs a Claude model; it gets none of those and no
  `CLAUDE_CODE_OAUTH*` variable.
- `agy` print mode has no one to approve commands, so the improver may edit files
  and run read-only commands only (git status/diff/log/show, ls, grep, rg, head,
  tail, cat, wc, sha256sum, echo, pwd, true). A refused command ends the agy
  session, so the prompt asks for one command per call. The director runs the tests.
- An empty improver reply, an empty architect plan, an unreadable verdict or a
  crash is a stage failure (exit 3), never a verdict.
- Each stage writes `meta.json` with `requested_model` and `actual_model`
  (Claude: `modelUsage`; agy: the conversation's `transcript_full.jsonl`). A
  mismatch or missing proof stops the relay with exit 3.
- The improver's diff is taken from working-tree snapshots before and after, so
  existing uncommitted work in WORKSPACE is not attributed to it.
- Run it in a worktree. Nothing commits or pushes; the director reviews the
  diff, runs the real checks, and owns the merge.

Exit codes: 0 approved, 1 reviewer asked for changes, 2 usage, 3 stage failure.
Output: `RUN_DIR/01-architect/architecture.md`, `02-improver/{improver.md,changes.diff}`,
`03-reviewer/review.md`, `relay.json` (default RUN_DIR `~/.beastmode/relay/<time>`).
