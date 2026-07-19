# Beastmode: MofA Multi-Agent Orchestration Framework

Beastmode is a **Mixture of Agents (MofA)** orchestration framework for AI-assisted software development, Hermes Agent, OpenClaw, Claude Code, Codex, Qwen, and MemroOS/memroos-style agent memory systems.

Beastmode separates high-judgment work (planning, architecture, review) from routine execution (implementation, tests, docs) across different model tiers, with strict cost discipline, context-rot protection, and a self-improving learning loop.

## What is Beastmode?

Beastmode is an orchestration pattern for AI-assisted development and long-running agent goals. It uses MofA / Mixture of Agents at decision gates, cheap executors for bounded implementation work, and MemroOS-style durable state handoffs so agents do not resume from compressed chat history alone.

Exact search aliases: **beastmode**, **MofA**, **Mixture of Agents**, **memroos**, **MemroOS**, **Hermes Agent**, **OpenClaw**, **agent orchestration**, **context rot mitigation**.

Beastmode:

- **Saves money** by routing implementation *and mechanical validation* to economy models (MiniMax M3, Qwen/Gwen) while keeping frontier models (Claude Fable, Kimi 3, Opus, Codex) for design, judgment, and review sign-off
- **Improves quality** through mandatory acceptance contracts, adversarial review, and merge gates
- **Gets better over time** via a self-improvement loop that records lessons and promotes repeated patterns into skills/config
- **Works anywhere** — harness-agnostic, compatible with Ultraswarm, GSD, `delegate_task`, Claude Code subagents, or manual git workflows

## Core Principle

**Frontier models design. Cheap models build and validate. The loop learns.**

The routing rule underneath: a task goes to a cheap model exactly when its output can be cheaply verified (tests, schema, contract); frontier models handle work that only judgment can verify — and their real job is *creating verifiability* (contracts, interfaces, verification commands) so as much work as possible becomes cheap-routable.

## Model Tiers

- **Design tier (frontier):** Claude Fable, Kimi 3, Opus, frontier Codex/GPT — architecture, acceptance contracts, judgment review, escalations
- **Execution tier (economy):** MiniMax M3, Qwen/Gwen — implementation, tests, docs, and mechanical validation (running verification commands, producing pass/fail reports)

See `references/model-routing.md` for the per-phase routing table and escalation ladder.

## Two Variants

- **Frontier-led:** Maximum judgment for product/creative/architecture decisions. Fable or Kimi 3 directs (optionally pairing the two — one designs, the other challenges), MiniMax M3/Qwen executes and validates.
- **Codex-led:** Cost-efficient lead with strong gates. Codex plans and reviews, MiniMax M3/Qwen executes.

## Quick Start

1. Read `SKILL.md` — the full framework
2. Choose your variant (frontier-led or Codex-led) and map your models to tiers (`references/model-routing.md`)
3. Choose your harness (Ultraswarm, GSD, delegate_task, Claude Code subagents, or manual git)
4. Follow the beastmode loop: Preflight → Acceptance Contract → Design (frontier) → Delegate (economy) → Validate (economy) → Review (frontier) → Merge → Self-Improve

## Files

- `SKILL.md` — The complete beastmode framework (start here)
- `references/model-routing.md` — Tier definitions, per-phase routing table, design package template, escalation ladder, provider config sketches
- `references/orchestration-comparison.md` — Evolution from early prototypes to v2.0
- `references/context-rot-mitigation.md` — MemroOS-style goal-state capsules, compact/resume rules, and MofA decision memory
- `references/public-sharing-checklist.md` — Guidelines for publishing beastmode skills publicly

## Compatibility

Works with:
- **Claude Code** (Opus-led or Codex-led)
- **Hermes Agent** (Codex-led with delegate_task)
- **OpenClaw** (Codex-led with delegate_task)
- **Codex CLI** (Codex-led with subagents)
- **Any agent environment** with git and model access

## License

MIT — use it, fork it, improve it.
