---
name: beastmode-acp
description: Thin Agent Client Protocol adapter for editor-launched Beastmode goals
tags: [beastmode, acp, editors, registry]
---

# Beastmode ACP adapter

This is intentionally a **thin transport adapter**, not a second Beastmode
runtime. It speaks ACP v1 over line-delimited JSON-RPC, owns editor session
state, and forwards each `session/prompt` goal to the existing `bm` runner.
Beastmode continues to own orchestration, model routing, permissions,
worktrees, validation, provenance, and the self-learning log.

## Supported ACP surface

- `initialize` / `authenticate`
- `session/new`
- `session/prompt` with text and resource-link blocks
- `session/cancel` and `session/close`
- `session/set_mode` and `session/set_config_option` for low/medium/high
  autonomy
- streamed `session/update` agent-message chunks

It intentionally does not implement ACP-native tools, MCP forwarding,
additional directories, session persistence, or a second worker graph.

## Local launch

From a checkout with the existing `bm` command available:

```bash
python -m beastmode.acp
# or, after installing the Python package:
beastmode --acp
beastmode-acp
```

The default backend argv template is:

```text
bm --autonomy {autonomy}
```

The editor prompt is appended after `--`, so a prompt beginning with `--`
cannot become a Beastmode flag. Configure a different non-shell argv template
with `BEASTMODE_ACP_BACKEND`, or a JSON argv array with
`BEASTMODE_ACP_BACKEND_JSON`. Supported placeholders are `{goal}`,
`{autonomy}`, and `{session_id}`. No shell is evaluated.

Example:

```bash
export BEASTMODE_ACP_BACKEND_JSON='["bm","--harness","langgraph","--autonomy","{autonomy}"]'
beastmode --acp
```

## Registry posture

`registry-entry.example.json` is a submission-shaped example only. It should
not be submitted until the package is published at the pinned version and the
registry's URL, archive, icon, and authentication checks pass. The adapter's
`initialize` response advertises a local backend authentication method because
the ACP registry requires `authMethods`; it does not receive or persist
provider credentials.
