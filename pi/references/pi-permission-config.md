# Permission Config Starter (pi-permission-system)

A project-level `@gotgenes/pi-permission-system` config that encodes the
universal Beastmode worker contract. The published policy is deny/ask by
default: ordinary reads inside the repository are allowed, mutations and
shell commands require confirmation, and secrets, external paths, publishing,
commits, and destructive commands are denied.

The canonical JSON is `pi/config/pi-permission-system.json`. Install that
exact file at `<repo>/.pi/extensions/pi-permission-system/config.json` before
starting a Beastmode Pi run. Project config overrides global config only after
Pi marks the project trusted. If the file is absent, invalid, skipped because
the project is untrusted, or reports automatic approval enabled, stop the run;
prose is not a permission boundary.

From the repository root:

```bash
install -Dm600 pi/config/pi-permission-system.json \
  .pi/extensions/pi-permission-system/config.json
cmp -s pi/config/pi-permission-system.json \
  .pi/extensions/pi-permission-system/config.json
```

The `cmp` command must exit zero. Start Pi only after the project is trusted
and the permission-system startup output confirms that project policy was not
skipped.

## Starter config

```json
{
  "permissionReviewLog": true,
  "yoloMode": false,
  "doublePressToConfirm": true,
  "authorizerChain": [],
  "permission": {
    "*": "ask",
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
      "**/*.p12": "deny",
      "**/*.pfx": "deny",
      "**/*.sqlite": "deny",
      "**/*.sqlite3": "deny",
      "**/auth.json": "deny",
      "**/credentials.json": "deny",
      "**/.npmrc": "deny",
      "**/.pypirc": "deny",
      "**/.netrc": "deny",
      "**/.git-credentials": "deny",
      "**/.docker/config.json": "deny",
      "**/.config/gh/hosts.yml": "deny",
      "**/.aws/credentials": "deny",
      "**/.aws/config": "deny",
      "**/.kube/config": "deny",
      "**/*kubeconfig*": "deny",
      "**/application_default_credentials.json": "deny",
      ".env.example": "allow",
      "**/.env.example": "allow"
    },
    "read": "allow",
    "find": "allow",
    "grep": "allow",
    "ls": "allow",
    "write": "ask",
    "edit": "ask",
    "external_directory": "deny",
    "mcp": "ask",
    "skill": "ask",
    "bash": {
      "*": "ask",
      "git push *": "deny",
      "git push": "deny",
      "git commit *": "deny",
      "git commit": "deny",
      "rm -rf *": "deny",
      "sudo *": "deny",
      "gh pr create *": "deny",
      "gh release *": "deny",
      "npm publish *": "deny"
    }
  }
}
```

## Reading the rules

Surfaces evaluate **most-restrictive-wins** in this order:
`path` (cross-cutting, all file access) → `external_directory` (CWD
boundary) → per-tool patterns → `bash` (shell commands).

Within a surface, **last matching rule wins**, so put broad catch-alls
first and specific overrides after. The universal and bash fallbacks are
`ask`, so alternate spellings and indirection never become silently allowed.
A `path` deny cannot be overridden by a per-tool allow — that is what makes
it the right place to protect secrets from every tool at once.

The credential-filename denies are intentionally narrow. Ordinary source,
configuration, package manifests, and worker commands remain available; only
files conventionally used to hold package, VCS, container, cloud, and cluster
credentials are inaccessible to workers.

The `path` surface matches both the path as referenced and its canonical
(symlink-resolved) form, so symlink aliases cannot evade a deny.

## Tuning for the run mode

**Interactive director session (default).** The human director may approve
ordinary `ask` actions after inspecting them. Publishing, commits, destructive
commands, secret paths, and external paths remain `deny`; use a separately
reviewed, temporary policy for an intentional release instead of weakening the
published worker policy.

**Fully unattended director session.** Replace any remaining `ask` with
`deny`. Never enable automatic approval. The run will be evidence-only
close-out when a human decision would have been required; that is the correct
behavior (no watcher, no validated merge — per the universal skill).

**Per-agent overrides.** Pi agent frontmatter has higher precedence than the
project config. `bm` therefore fails preflight when a repository agent under
`.pi/agents/` or `.pi/agent/agents/` declares `permission` or `yoloMode`.
Shipped callable workers must not declare either field. The separately
installed, non-callable Claude marker is deny-only, but repository agents may
not rely on exceptions: review them and keep permission solely in the
canonical project policy.

## What this does NOT cover

- The global config still applies when the project policy is missing or the
  project is untrusted. Beastmode does not treat that fallback as sufficient:
  verify the canonical project policy loaded before starting workers.
- MCP-server behavior is not gated by this config — MCP tools are governed
  by the `mcp` surface in the permission system and by the MCP server's
  own auth. Keep `MEMROOS_AGENT_API_KEY` and similar secrets out of the
  project tree entirely; they belong in `~/.memroos/agent-env` (mode 600,
  owner-only directory) or 1Password.
- loop-police is a separate package and runs independently of this config.
