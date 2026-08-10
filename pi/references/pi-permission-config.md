# Permission Config Starter (pi-permission-system)

A project-level `@gotgenes/pi-permission-system` config that encodes the
universal Beastmode worker contract. The published policy allows ordinary
reads inside the repository and auto-approves routine asks via `yoloMode: true`.
Normal director commits and pushes are `ask` rules, while force/delete/mirror
pushes, short destructive flags, destructive refspecs, secrets, external paths,
publishing, and destructive commands remain hard-denied.

The canonical JSON is `pi/config/pi-permission-system.json`. Install that
exact file at `<repo>/.pi/extensions/pi-permission-system/config.json` before
starting a Beastmode Pi run. Project config overrides global config only after
Pi marks the project trusted. If the file is absent, invalid, skipped because
the project is untrusted, or diverges from the pinned policy digest, stop the
run; `scripts/bm` passes `--approve` on every headless launch so the project
policy is loaded for that run; prose is not a permission boundary.

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
  "yoloMode": true,
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
      "git push *": "ask",
      "git push": "ask",
      "git commit *": "ask",
      "git commit": "ask",
      "git push *--force*": "deny",
      "git push *--delete*": "deny",
      "git push *--mirror*": "deny",
      "git push *-f*": "deny",
      "git push *-F*": "deny",
      "git push *-d*": "deny",
      "git push *:*": "deny",
      "git push *+*": "deny",
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

The destructive push rules cover long and short options plus force/delete
refspecs; normal `git push origin branch` remains an ask rule.

The credential-filename denies are intentionally narrow. Ordinary source,
configuration, package manifests, and worker commands remain available; only
files conventionally used to hold package, VCS, container, cloud, and cluster
credentials are inaccessible to workers.

The `path` surface matches both the path as referenced and its canonical
(symlink-resolved) form, so symlink aliases cannot evade a deny.

## Tuning for the run mode

**Interactive director session (default).** Ordinary `ask` actions
auto-approve under `yoloMode`; the director reviews the permission log instead
of answering live prompts. Normal commits and pushes are available to the
director, while force/delete/mirror pushes, short destructive forms and
refspecs, releases, destructive commands, secret paths, and external paths
remain `deny`.

**Worker session.** Worker contracts still forbid commits and pushes. The
director owns staging, commit, push, and merge; the policy's normal Git `ask`
rules exist for that director release step.

**Fully unattended director session.** The published default already
auto-approves `ask` via `yoloMode`. If a stricter unattended posture is
required, replace `ask` with `deny` in a separately reviewed, temporary policy.
The run will be evidence-only close-out when a human decision would have been
required; that is the correct behavior (no watcher, no validated merge — per
the universal skill).

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
