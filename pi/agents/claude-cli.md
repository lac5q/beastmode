---
name: claude-cli
description: |
  MARKER — read-only Claude Pro lane. The director must supply prompt bytes on stdin to `claude -p --model opus --permission-mode plan`, NOT call workflow `agent()` with this agentType. See pi/SKILL.md "Claude routing rule (hard rule)".
model: claude-cli-do-not-call-via-agent
yoloMode: false
permission:
  "*": deny
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
printf '%s' "$prompt" | claude -p --model opus --permission-mode plan
```

This form draws from the claude.ai Pro/Max subscription quota. The
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
"reserved for Claude Pro work." The marker itself denies every tool and
cannot be used as a working agent. The director invokes the external,
read-only lane with an argv array and prompt bytes on stdin. Common pattern:

```js
// Instead of:
//   await agent("audit this", { agentType: "claude-cli" })
//
// Do this from the director (this pi session):
//   const out = spawnSync(
//     "claude",
//     ["-p", "--model", "opus", "--permission-mode", "plan"],
//     { input: prompt, encoding: "utf8" },
//   )
//   return out.stdout
```

Never build a shell command by interpolating `prompt`. Never add a permission
bypass flag or route this marker through a wrapper that adds one.

The marker is documentation that survives into committed scripts, which
is the point — anyone editing the workflow later sees the rule without
having to read this file.

## See also

- `pi/SKILL.md` — "Claude routing rule (hard rule)"
- `~/.pi/workflows/model-tiers.json` — tier map (no `anthropic/*` in any tier)
