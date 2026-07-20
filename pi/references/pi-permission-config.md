# Permission Config Starter (pi-permission-system)

A project-level `@gotgenes/pi-permission-system` config that encodes the
universal Beastmode worker contract: workers (cheap subagents spawned via
`pi-dynamic-workflows`) physically cannot read secret paths or run
publishing / destructive commands without an explicit human `ask`.

Save this at `<repo>/.pi/extensions/pi-permission-system/config.json`.
Project config overrides global config at `~/.pi/agent/extensions/pi-permission-system/config.json`.

## Starter config

```json
{
  "permission": {
    "*": "allow",
    "path": {
      "*": "allow",
      "*.env": "deny",
      "*.env.*": "deny",
      ".env.local": "deny",
      "**/.ssh/*": "deny",
      "**/.memroos/agent-keys/*": "deny",
      "**/.memroos/*.env": "deny",
      "**/*.pem": "deny",
      "**/*.key": "deny",
      "**/auth.json": "deny",
      ".env.example": "allow",
      "**/.env.example": "allow"
    },
    "external_directory": "ask",
    "bash": {
      "*": "allow",
      "git push *": "ask",
      "git push": "ask",
      "git commit *": "ask",
      "git commit": "ask",
      "rm -rf *": "ask",
      "sudo *": "ask",
      "gh pr create *": "ask",
      "gh release *": "ask",
      "npm publish *": "ask",
      "curl *minimax*": "ask"
    }
  }
}
```

## Reading the rules

Surfaces evaluate **most-restrictive-wins** in this order:
`path` (cross-cutting, all file access) → `external_directory` (CWD
boundary) → per-tool patterns → `bash` (shell commands).

Within a surface, **last matching rule wins**, so put broad catch-alls
first and specific overrides after. A `path` deny cannot be overridden by
a per-tool allow — that is what makes it the right place to protect
secrets from every tool at once.

The `path` surface matches both the path as referenced and its canonical
(symlink-resolved) form, so symlink aliases cannot evade a deny.

## Tuning for the run mode

**Interactive director session (default).** `ask` is fine — the human
director is present and approves merges / destructive ops. Workers are
still blocked from secret paths via `deny`.

**Fully unattended director session.** Replace `ask` with `deny` for any
publishing / destructive rule. The run will be evidence-only close-out
when a human `ask` would have been required; that is the correct behavior
(no watcher, no validated merge — per the universal skill).

**Per-agent overrides.** pi-dynamic-workflows subagents can declare a
narrower policy via the `agentType` mechanism in `@gotgenes/pi-subagents`
or YAML frontmatter — see the pi-permission-system docs for the merge
order.

## What this does NOT cover

- The `~/.pi/agent/extensions/pi-permission-system/config.json` (global)
  config still applies if no project config exists; the project config
  fully overrides it when present.
- MCP-server behavior is not gated by this config — MCP tools are governed
  by the `mcp` surface in the permission system and by the MCP server's
  own auth. Keep `MEMROOS_AGENT_API_KEY` and similar secrets out of the
  project tree entirely; they belong in `~/.memroos/agent-env` (mode 600,
  owner-only directory) or 1Password.
- loop-police is a separate package and runs independently of this config.