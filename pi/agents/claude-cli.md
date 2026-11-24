---
name: claude-cli
description: |
  MARKER — deny-all. Pi must not run or launch Claude work: no `claude -p` from Pi and no workflow `agent()` call with this agentType or an anthropic/* model. Claude models run only inside Claude Code. See pi/SKILL.md "Claude routing rule (hard rule)".
model: claude-cli-do-not-call-via-agent
yoloMode: false
permission:
  "*": deny
---

# Claude lane marker (deny-all)

STOP. This agentType is a marker, not a callable workflow subagent. It denies
every tool and exists only so committed workflow scripts carry the rule.

**Pi must not run or launch Claude work.** No `claude -p` from Pi, and no
workflow `agent()` call with an `anthropic/*` model or this agentType. Claude
models run only inside Claude Code, and a Claude subscription login must never
be driven through Pi, Hermes, Codex, or LangGraph.

Claude work goes to a Claude Code director:

```bash
bm "<goal>" --harness claude
```

Any `agent()` call that names this agentType fails at session creation with a
model-resolution error (`model: claude-cli-do-not-call-via-agent` is
deliberately invalid). Never add a permission bypass flag or route this marker
through a wrapper that adds one.

## See also

- `pi/SKILL.md` — "Claude routing rule (hard rule)"
- `~/.pi/workflows/model-tiers.json` — tier map (no `anthropic/*` in any tier)
