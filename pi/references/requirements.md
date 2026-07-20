# Pi Package Requirements

The `beastmode-pi` skill requires a pi installation with six companion
packages. This document is the canonical list for new-host onboarding,
CI checks, and drift audits.

## Hard requirements

| Requirement | Minimum | Why |
|---|---|---|
| `pi` (pi-coding-agent) | **≥ 0.80.6** | `@narumitw/pi-goal` registers an `agent_settled` lifecycle handler that was added in 0.80.6. Earlier versions will load the extension but the loop engine will silently never auto-continue. |
| `node` | **≥ 20.x** | Pi package extensions are TypeScript ESM; modern pi releases depend on Node 20+ APIs. |
| `npm` | **≥ 10.x** | Required by `pi install` for package resolution and the user-level install path (`~/.pi/agent/npm/`). |
| Operating system | Linux x86_64 / aarch64, macOS arm64 / x86_64, WSL2 | Tested targets. Other Unix-likes likely work but are not in the support matrix. |

## Required packages

All six are MIT-licensed (or near-MIT) and install from npm:

```bash
pi install npm:@narumitw/pi-goal \
  npm:@quintinshaw/pi-dynamic-workflows \
  npm:pi-loop-police \
  npm:@gotgenes/pi-permission-system \
  npm:@juicesharp/rpiv-todo \
  npm:@llblab/pi-telegram
```

| Package | Role | Optional? | Notes |
|---|---|---|---|
| `@narumitw/pi-goal` | Loop engine — `/goal`, `goal_complete`, `goal_blocked` | **required** | Without this, the skill's auto-continuation step is inert. |
| `@quintinshaw/pi-dynamic-workflows` | Fan-out + model routing + verifier primitives | **required** | Without this, only single-agent work is possible. |
| `pi-loop-police` | Anti-spin circuit breaker | **required** | Unattended runs WILL spin eventually; this is the kill switch. |
| `@gotgenes/pi-permission-system` | Worker-contract enforcer | **required** | Without a project-level config, worker contracts rely on prose alone. See `pi-permission-config.md`. |
| `@juicesharp/rpiv-todo` | Live progress overlay (TUI) | recommended | Strongly recommended for visibility; not blocking. |
| `@llblab/pi-telegram` | Remote supervision (phone) | optional | Requires one-time `/telegram-setup` with a bot token. If absent, skip telegram and continue. |

## One-line install + verify

```bash
# Install
pi install npm:@narumitw/pi-goal \
  npm:@quintinshaw/pi-dynamic-workflows \
  npm:pi-loop-police \
  npm:@gotgenes/pi-permission-system \
  npm:@juicesharp/rpiv-todo \
  npm:@llblab/pi-telegram

# Verify all six are present
pi list | grep -E 'pi-goal|pi-dynamic-workflows|pi-loop-police|pi-permission-system|rpiv-todo|pi-telegram' | wc -l   # expect: 6

# Verify the four required tools register when a session starts
pi -p "Without calling any tools, list tool names that start with goal_ or relate to workflows. One per line." \
  | grep -E '^goal_|^workflow'   # expect: goal_complete, goal_blocked, workflow, workflow_control
```

## Skill placement

The `beastmode-pi` skill can live in any of three locations; pi discovers
from all of them and project-local wins over global on name collision:

| Location | Scope | Best for |
|---|---|---|
| `~/.agents/skills/beastmode-pi/SKILL.md` | global | one-shot install across every repo |
| `<repo>/.agents/skills/beastmode-pi/SKILL.md` | project (requires trusted project) | repos that want to pin a version |
| Shipped as a pi package | npm-installable | shared team installs via `pi install npm:@scope/beastmode-pi` |

For the canonical lac5q/beastmode home, both a project copy and the
`pi/SKILL.md` reference live in the repo; install via copy or as a pi
package.

## Permission-system config

The worker contract from the universal `beastmode` skill requires a
project-level permission config at
`<repo>/.pi/extensions/pi-permission-system/config.json`. Without it,
secrets are not gated and `git push` / `git commit` run unprompted.
See `pi-permission-config.md` for the starter.

## Compatibility notes

- **pi-goal** uses session-scoped goal state — it does not persist goals
  across pi sessions. For durable goals, pair with a goal store (MemRoOS
  `/api/gsd/goal`, a plain file, or the consumer repo's overlay).
- **pi-dynamic-workflows** writes workflow runs to the user-level session
  directory (`~/.pi/agent/sessions/`). Quotas and disk usage scale with
  the number of long-running workflows.
- **pi-permission-system** follows most-restrictive-wins semantics; a
  broad `allow` cannot override a narrow `deny` on the same surface.
  Project config overrides global config; per-agent YAML frontmatter
  overrides both.
- **pi-loop-police** has no configuration; counters reset on
  `/loop-police reset` if you want a manual clear mid-session.
- **pi-telegram** requires a BotFather token and a one-time
  `/telegram-setup` interaction. It is the only optional package.

## Known constraints

- All six packages rely on pi's extension lifecycle (registration on
  session start, `agent_settled` for pi-goal, etc.). Some packages
  (notably pi-goal) advertise a minimum pi version; always check
  `pi --version` before upgrading or downgrading.
- `pi install` writes to user settings (`~/.pi/agent/settings.json`) by
  default. Use `-l` to write to project settings (`.pi/settings.json`)
  instead — useful for shared/reproducible installs.
- The skill does not provision lane credentials (Qwen, MiniMax API,
  Droid). Those are host-level environment concerns and live in
  `~/.memroos/agent-env` (mode 600) or 1Password, never in the skill.

## Updating the list

When adding a new pi package to the skill, update this file in the
same PR so the requirements list and the skill frontmatter stay in
sync.