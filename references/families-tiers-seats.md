# Families, Tiers, and Seats

ACN is async parallel sub agents. Every Beastmode run resolves down to the same three concepts: which model **family**, on which cost **tier**, in which **seat**. This file is the human-readable view; `schema/` is the machine source of truth. Treat this file as generated documentation — if you change it without editing the JSON, the next regeneration will clobber you.

## Families

A family is a vendor / model lineage. Aliases inside a family inherit the same tier default and the same provider-routing quirks.

| family | providers | notes |
|---|---|---|
| anthropic | `anthropic`, `claude-pro-lane` | Claude models; Pro lane routes via `claude -p` |
| openai-codex | `openai-codex` | GPT/Codex frontier incl. terra/sol profiles; Luna Max economy worker |
| kimi | `kimi-coding` | k3 flagship, k2p7 fallback |
| minimax | `minimax` | legacy economy family; use Luna Max by default |
| qwen | `qwen` | cross-family second opinion |
| xai | `xai`, `xai-oauth` | grok |
| zai | `zai` | glm validators |
| google | `vibeproxy` | Gemini via an operator-run proxy provider |

Source: `schema/families.json`.

Proxy-backed providers (`vibeproxy`) are named here by provider only. Their base
URL is host-local configuration — `~/.pi/agent/models.json`, mode `600` — and
must never appear in this repository. `scripts/public-artifact-guard` enforces
that: endpoint hosts are deny-by-default, so any host outside its allowlist
fails the guard on both `HEAD` and full history.

## Tiers

A tier is a cost posture, not a task type. Routing follows verification cost — what it costs to *re-verify* the work, not how clever the prompt looks.

| tier | owns | cost profile |
|---|---|---|
| frontier | design, judgment review, escalations, acceptance contracts | expensive, short bursts |
| economy | implementation, tests, docs, mechanical validation | 10-50x cheaper, bulk tokens |

Source: `schema/tiers.json`.

## Seats

A seat is a role in the run. Three of the four seats resolve to frontier; one resolves to economy. That asymmetry is the design — the watcher reading your work is more expensive than the work it reads.

| seat | tier | role |
|---|---|---|
| director | frontier | intent, architecture, final sign-off |
| watcher | frontier (prefer cross-family) | adversarial review, merge gating |
| executor | economy | implementation + mechanical validation |
| validator | frontier | merge/standing validation; may be sol/terra/opus/glm/grok |

Source: `schema/seats.json`.

## Why the watcher prefers cross-family

The watcher exists to catch what the director missed. If the watcher runs on the same family as the director, they share the same blind spots — same training cutoff, same routing quirks, same failure modes. A cross-family watcher (e.g. director on `kimi`, watcher on `xai`) breaks that coupling: their disagreements are evidence the work is contested, and the run halts on that signal instead of rubber-stamping. The `prefer_cross_family` flag on the watcher seat encodes this; if you can't honor it on a given run (single-family provider outage, cost cap), say so in the phase report.

## Adding a family or alias

Edit `schema/families.json`, then mirror the change in `scripts/tier-aliases.json` so existing aliases resolve. New alias example:

```json
"openai-codex": {
  "providers": ["openai-codex", "codex-cloud"],
  "notes": "GPT/Codex frontier incl. terra/sol profiles + cloud lane"
}
```

Verification after any schema edit:

```
python3 -m json.tool schema/families.json > /dev/null
python3 -m json.tool schema/tiers.json > /dev/null
python3 -m json.tool schema/seats.json > /dev/null
python3 -m json.tool schema/autonomy-levels.json > /dev/null
python3 -m json.tool schema/acn-contract.json > /dev/null
```

If a downstream doc still says "frontier models do X" and the schema says otherwise, the schema wins — fix the doc.
