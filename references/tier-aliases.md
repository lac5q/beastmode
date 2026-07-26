# Tier Aliases

Resolve friendly tier names (`kimi3`, `fable`, `opus`, `sol`, `terra`,
`grok`, `glm`, `minimax`, `gpt5.5`, `qwen`) to concrete provider/model IDs,
each carrying a **tier** (frontier | economy) and a **family** (anthropic,
openai-codex, kimi, minimax, qwen, xai, zai). Read by `scripts/bm` before any
harness invocation. Project-local override: `<repo>/.beastmode/tier-aliases.json`.

> Machine source of truth for families/tiers/seats: `schema/`. This file and
> `scripts/tier-aliases.json` are co-versioned — change one, change both in
> the same PR.

## Resolution order

1. `<repo>/.beastmode/tier-aliases.json` if it exists (project override)
2. `~/.beastmode/tier-aliases.json` if it exists (user override)
3. `scripts/tier-aliases.json` (shipped next to `bm` — fresh installs work)
4. Fallback: pass `--frontier <alias>` through to `pi --model` unchanged

## Defaults (verified against `pi --list-models` on oracle-1 / maeve-u1)

| Alias | Provider | Model | Tier | Family | Notes |
|---|---|---|---|---|---|
| `kimi3` | `kimi-coding` | `k3` | frontier | kimi | K3, the current flagship. Use for design + judgment. |
| `k2` | `kimi-coding` | `k2p7` | frontier | kimi | K2.7, fallback if K3 quota gone. |
| `fable` | `anthropic` | `claude-fable-5` | frontier | anthropic | 1M ctx, strongest judgment for product/creative. |
| `opus` | `anthropic` | `claude-opus-4-7` | frontier | anthropic | 1M ctx; current production Opus. |
| `opus5` | `anthropic` | `claude-opus-4-8` | frontier | anthropic | Bleeding edge; quotas tighter. |
| `sonnet` | `anthropic` | `claude-sonnet-4-6` | frontier | anthropic | Cheaper frontier option for tight budgets. |
| `gpt5.5` | `openai-codex` | `gpt-5.5` | frontier | openai-codex | Default Codex-tier frontier. |
| `gpt5.6` | `openai-codex` | `gpt-5.6-luna` | frontier | openai-codex | Latest Codex frontier (luna profile). |
| `sol` | `openai-codex` | `gpt-5.6-sol` | frontier | openai-codex | Validator profile; use `--thinking medium`. |
| `terra` | `openai-codex` | `gpt-5.6-terra` | frontier | openai-codex | Lead profile; use `--thinking high`. |
| `grok` | `xai-oauth` | `grok-4.5` | frontier | xai | Grok via OAuth (Hermes lane); cross-family watcher/validator. |
| `glm` | `zai` | `glm-5.2` | frontier | zai | GLM validator lane. |
| `minimax` | `minimax` | `MiniMax-M3` | economy | minimax | Default cheap execution tier. 1M ctx. |
| `minimax-fast` | `minimax` | `MiniMax-M2.7-highspeed` | economy | minimax | Lower latency, smaller ctx. |
| `qwen` | `qwen` | `qwen3.7-plus` | economy | qwen | Use when you need a second opinion from a different family. |
| `gwen` | `qwen` | `qwen3.7-max` | economy | qwen | Larger Qwen variant. |
| `haiku` | `anthropic` | `claude-haiku-4-5` | economy | anthropic | Anthropic-native cheap tier. |

## JSON shape (used by `scripts/bm`)

```json
{
  "kimi3": { "provider": "kimi-coding", "model": "k3", "tier": "frontier" },
  "fable": { "provider": "anthropic",   "model": "claude-fable-5", "tier": "frontier" },
  "minimax": { "provider": "minimax",   "model": "MiniMax-M3",    "tier": "economy" }
}
```

Canonical defaults live at `scripts/tier-aliases.json` (shipped). Project
overrides go in `<repo>/.beastmode/tier-aliases.json` — same shape, project
wins on collision. The reference doc and the JSON are co-versioned: if you
add a row to one, add it to the other in the same PR.

## How `bm` uses it

`bm "<goal>" --frontier kimi3 --economy minimax`:

1. Looks up `kimi3` → `kimi-coding/k3` (frontier), `minimax` → `minimax/MiniMax-M3` (economy).
2. **Preflight check**: validates each resolved `provider/model` exists in
   `pi --list-models` on the local host. If any are missing, `bm` exits with
   code 2 and lists the available frontier/economy alternatives the user can
   pick from — instead of letting `pi` fail mid-goal. Skipped when
   `BM_SKIP_MODEL_CHECK=1` (CI / scripted runs) or when `--on` is not local
   (the remote host owns availability).
3. Invokes: `pi --model kimi-coding/k3 --models kimi-coding/k3,minimax/MiniMax-M3 ...`.
4. Unresolved alias → passes through unchanged so the user sees the real
   `pi` error and can fix the alias instead of silently mapping wrong.

Reasoning effort is independent of the model alias. For the Terra lead and
Sol validator split, run the lead through Hermes as Terra/high, then run the
validation goal with `bm "<validation goal>" --frontier sol --thinking medium`.

## How to verify on a new host

```bash
pi --list-models | awk 'NR>3 {print $1, $2}' > /tmp/host-models.txt
# diff against the table above; any missing row is an alias that needs
# a project-local override at <repo>/.beastmode/tier-aliases.json.
```

## When to update

- New model release (`k4`, `opus-4-9`, `MiniMax-M4`) → add a row.
- Host drops a provider entirely → mark alias `unavailable` and pick a
  fallback in the same tier.
- Provider renames a model ID → update `model` field; alias name stays stable.