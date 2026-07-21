---
name: claude-cli
description: |
  MARKER — Claude Pro lane. The director (pi session) must invoke `claude -p --model opus "<prompt>"` directly via bash as an external lane, NOT call workflow `agent()` with this agentType. The Claude Pro lane draws from the claude.ai Pro/Max subscription quota, separate from the API OAuth credential in `~/.pi/agent/auth.json` (which shares a single rate-limited "extra usage" pool across every Claude model). See pi/SKILL.md "Claude routing rule (hard rule)".
model: claude-cli-do-not-call-via-agent
---

# Claude Pro lane marker

STOP. This agentType is a marker, not a callable workflow subagent. The
beastmode routing rule requires that all Claude work in beastmode runs
routes through the `claude -p` external lane, not through `workflow
agent()`.

If you reached this file because a workflow script wrote
`agent(prompt, { agentType: "claude-cli" })`, replace that call with a
direct invocation from the director (the pi session itself):

```bash
claude -p --model opus --dangerously-skip-permissions "<prompt>"
# or equivalently:
~/.local/bin/claude-pro "<prompt>"
```

Both forms draw from the claude.ai Pro/Max subscription quota. The
`workflow agent()` path with `model: "anthropic/claude-opus-4-8"` (or
any other `anthropic/*` spec) draws from the `anthropic` OAuth API
credential in `~/.pi/agent/auth.json`, which shares a single "extra
usage" pool across every Claude model and is rate-limited. That path
fails with HTTP 400 *"You're out of extra usage"* and burns the whole
run.

The `model: claude-cli-do-not-call-via-agent` field on this agentType
is deliberately invalid. Any `agent()` call that names this agentType
will fail at session creation with a model-resolution error — by
design. The description field above is what shows up in tool listings
when workflow authors explore available agentTypes, which is why the
rule is repeated here.

## When to use this marker

Write `agentType: "claude-cli"` in a workflow script whenever a slot is
"reserved for Claude Pro work." The director reading the script sees
the marker and knows to invoke the lane directly rather than fanning
out via `agent()`. Common pattern:

```js
// Instead of:
//   await agent("audit this", { agentType: "claude-cli" })
//
// Do this from the director (this pi session):
//   const out = await exec(`~/.local/bin/claude-pro "audit this"`)
//   return out.stdout
```

The marker is documentation that survives into committed scripts, which
is the point — anyone editing the workflow later sees the rule without
having to read this file.

## See also

- `pi/SKILL.md` — "Claude routing rule (hard rule)"
- `~/.pi/workflows/model-tiers.json` — tier map (no `anthropic/*` in any tier)
- `~/.local/bin/claude-pro` — wrapper for the Claude Pro lane
- `scripts/claude-pro` — same wrapper in the source repo