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

## Defaults (verify against `pi --list-models` on the configured worker host)

| Alias | Provider | Model | Tier | Family | Notes |
|---|---|---|---|---|---|
| `kimi3` | `kimi-coding` | `k3` | frontier | kimi | K3, the current flagship. Use for design + judgment. |
| `k2` | `kimi-coding` | `k2p7` | frontier | kimi | K2.7, fallback if K3 quota gone. |
| `fable` | `anthropic` | `claude-fable-5` | frontier | anthropic | 1M ctx, strongest judgment for product/creative. |
| `opus` | `anthropic` | `claude-opus-4-7` | frontier | anthropic | 1M ctx; current production Opus. |
| `opus5` | `anthropic` | `claude-opus-4-8` | frontier | anthropic | Bleeding edge; quotas tighter. |
| `sonnet` | `anthropic` | `claude-sonnet-4-6` | frontier | anthropic | Cheaper frontier option for tight budgets. |
| `sonnet5` | `anthropic` | `claude-sonnet-5` | frontier | anthropic | Current Sonnet, 1M ctx. Pair with `--thinking high`. |
| `gpt5.5` | `openai-codex` | `gpt-5.5` | frontier | openai-codex | Default Codex-tier frontier. |
| `gpt5.6` | `openai-codex` | `gpt-5.6-luna` | frontier | openai-codex | Latest Codex frontier (luna profile). |
| `sol` | `openai-codex` | `gpt-5.6-sol` | frontier | openai-codex | Validator profile; use `--thinking medium`. |
| `terra` | `openai-codex` | `gpt-5.6-terra` | frontier | openai-codex | Lead profile; use `--thinking high`. |
| `grok` | `xai` | `grok-4.5` | frontier | xai | Grok via the installed xAI OAuth/API provider; cross-family watcher/validator. |
| `glm` | `zai` | `glm-5.2` | frontier | zai | GLM validator lane. |
| `luna-max` | `openai-codex` | `gpt-5.6-luna` | economy | openai-codex | Approved low-cost worker; reasoning `max`. Use for independent ACN slices. |
| `minimax` | `openai-codex` | `gpt-5.6-luna` | economy | openai-codex | Deprecated compatibility alias for `luna-max`. |
| `minimax-fast` | `openai-codex` | `gpt-5.6-luna` | economy | openai-codex | Deprecated compatibility alias; preserves Luna Max reasoning. |
| `qwen` | `openai-codex` | `gpt-5.6-luna` | economy | openai-codex | Deprecated compatibility alias; use `luna-max`. |
| `gwen` | `openai-codex` | `gpt-5.6-luna` | economy | openai-codex | Deprecated compatibility alias; use `luna-max`. |
| `haiku` | `anthropic` | `claude-haiku-4-5` | economy | anthropic | Anthropic-native cheap tier. |
| `gemini-flash` | `vibeproxy` | `gemini-3.6-flash-high` | economy | google | Opt-in worker lane. Requires the `vibeproxy` provider in host-local `~/.pi/agent/models.json`; see below. |

## JSON shape (used by `scripts/bm`)

```json
{
  "kimi3": { "provider": "kimi-coding", "model": "k3", "tier": "frontier" },
  "fable": { "provider": "anthropic",   "model": "claude-fable-5", "tier": "frontier" },
  "luna-max": { "provider": "openai-codex", "model": "gpt-5.6-luna", "tier": "economy", "reasoning": "max" }
}
```

Canonical defaults live at `scripts/tier-aliases.json` (shipped). Project
overrides go in `<repo>/.beastmode/tier-aliases.json` — same shape, project
wins on collision. The reference doc and the JSON are co-versioned: if you
add a row to one, add it to the other in the same PR.

## How `bm` uses it

`bm "<goal>" --frontier kimi3 --economy luna-max`:

1. Looks up `kimi3` → `kimi-coding/k3` (frontier), `luna-max` → `openai-codex/gpt-5.6-luna` (economy, reasoning `max`).
2. **Preflight check**: validates each resolved `provider/model` exists in
   `pi --list-models` on the local host. If any are missing, `bm` exits with
   code 2 and lists the available frontier/economy alternatives the user can
   pick from — instead of letting `pi` fail mid-goal. Skipped when
   `BM_SKIP_MODEL_CHECK=1` (CI / scripted runs) or when `--on` is not local
   (the remote host owns availability).
3. Invokes: `pi --model kimi-coding/k3 --models kimi-coding/k3,openai-codex/gpt-5.6-luna ...`.
4. Unresolved alias → passes through unchanged so the user sees the real
   `pi` error and can fix the alias instead of silently mapping wrong.

Anthropic aliases (`fable`, `opus`, `opus5`, `sonnet`, `sonnet5`, and `haiku`)
are the exception to the Pi invocation above: when one is the active director
seat, `bm` uses the single-seat `claude -p --permission-mode plan` lane,
supplies the prompt on stdin, and rejects multiple Anthropic seats instead of
using an API OAuth fallback. This holds for *any* `--harness`; an Anthropic seat
under `--harness pi` is re-routed to `claude -p` rather than the API pool.

Reasoning effort is independent of the model alias. For the Terra lead and
Sol validator split, run the lead through Hermes as Terra/high, then run the
validation goal with `bm "<validation goal>" --frontier sol --thinking medium`.

On the Claude lane, `--thinking` maps onto the CLI's `--effort`. That scale has
no sub-`low` step, so `none` and `minimal` both resolve to `low`; every other
level passes through unchanged:

```bash
bm "<goal>" --harness claude --frontier sonnet5 --thinking high
```

## Proxy-backed worker lanes

`gemini-flash` resolves to `vibeproxy/gemini-3.6-flash-high`. The alias carries
the provider name and model id only — the proxy's base URL is **host-local
configuration and must never be committed**. Configure it per host in
`~/.pi/agent/models.json` (mode `600`), which is where `pi` reads providers
from; confirm with `pi --list-models`. Nothing about the endpoint belongs in
this repo, and `scripts/public-artifact-guard` fails closed on any endpoint host
outside its allowlist.

The default economy seat is unchanged — automatic worker routing stays on Luna
Max. This lane is an explicit opt-in:

```bash
bm "<goal>" --frontier kimi3 --economy gemini-flash
```

Aliases resolve **before** `--on` dispatch, so a remote host receives the fully
qualified `vibeproxy/gemini-3.6-flash-high` and does not need its own alias
table — only the same host-local provider entry:

```bash
bm "<goal>" --frontier kimi3 --economy gemini-flash --on <tailscale-host>
```

### Known constraint: this lane reports drift under the provenance gate

The `-high` suffix is a *reasoning-effort selector*, not a distinct served
model. The proxy applies high reasoning (the response carries
`reasoning_tokens`) but reports `model: gemini-3.6-flash` — the base id, without
the suffix. Requested and actual therefore differ by construction.

That is precisely what `scripts/lib/acn_meta.py` is built to catch, so every ACN
child pinned to this alias resolves to `drift` and blocks `validated`. Until the
proxy echoes back the requested id, treat `gemini-flash` as a **direct/manual
lane**, not an ACN fan-out worker. Do not "fix" this by loosening the drift gate:
the gate is behaving correctly, and weakening it would blind every other lane.

## How to verify on a new host

```bash
host_models="$(mktemp "${TMPDIR:-/tmp}/beastmode-host-models.XXXXXX")"
trap 'rm -f "$host_models"' EXIT
pi --list-models | awk 'NR>3 {print $1, $2}' > "$host_models"
# diff against the table above; any missing row is an alias that needs
# a project-local override at <repo>/.beastmode/tier-aliases.json.
```

## When to update

- New model release (`k4`, `opus-4-9`, `MiniMax-M4`) → add a row.
- Host drops a provider entirely → mark alias `unavailable` and pick a
  fallback in the same tier.
- Provider renames a model ID → update `model` field; alias name stays stable.
