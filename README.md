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
- **Works anywhere** — harness-agnostic, compatible with Ultraswarm, GSD, `delegate_task`, Claude Code subagents, manual git workflows, or `pi-coding-agent` (see `pi/SKILL.md`)

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

## Autonomy Levels

Beastmode runs with one of three autonomy levels — how much the orchestrator decides on its own before surfacing to a human. **Default: medium.** Below `high`, surfaced gates are **blocking** — the run posts its per-phase usage report (requested vs actual models, tokens vs budget, time vs estimate) and stops for approval; only `high` rolls through gates on its own. **Model drift** (a task served by a model other than the one requested) surfaces at every level.

| Level | Surfaces to you | Best for |
|---|---|---|
| **low** | every phase transition, every merge gate, every cross-tier escalation | high-stakes / first runs in a new repo |
| **medium** (default) | security/auth/payments, tier-2/3 Watcher fallback, front-door merge gates, `goal_blocked` | most feature work — chat stays quiet unless something breaks |
| **high** | budget exhaustion, "no watcher no validated", secrets in prompts | fire-and-forget multi-phase runs — needs a locked permission config |

See `references/autonomy-levels.md` for the full table and pi-flag mapping.

## Quick Start

1. Read `SKILL.md` — the full framework
2. Choose your variant (frontier-led or Codex-led) and map your models to tiers (`references/model-routing.md`)
3. Choose your harness (Ultraswarm, GSD, delegate_task, Claude Code subagents, LangGraph, manual git, or pi + `pi-dynamic-workflows`)
4. Follow the beastmode loop: Preflight → Acceptance Contract → Design (frontier) → Delegate (economy) → Validate (economy) → Review (frontier) → Merge → Self-Improve
5. **(Optional) one-shot runner:**

   ```bash
   bm "<goal>"                                          # prints rough phase ETA, then runs locally (pi harness)
   bm "<goal>" --harness hermes                         # Hermes ACN: async parallel sub-agents via delegate_task
   bm "<goal>" --harness claude|codex                   # Claude Code / Codex adapters
   bm "<goal>" --harness langgraph                    # optional StateGraph/checkpoint runtime
   bm "<goal>" --harness langgraph --executor-command '<child command>'
   bm "<goal>" --gsd --frontier kimi3 --economy minimax # pick tiers, force GSD gating
   bm "<goal>" --frontier kimi3 --economy minimax --watcher grok # cross-family watcher
   bm "<validation goal>" --frontier sol --thinking medium # OAuth-backed Sol validator
   bm "<goal>" --on <remote-host>                       # dispatch to a fleet node
   bm "<goal>" --autonomy low|medium|high               # change how much surfaces
   scripts/phase-estimate "<goal>"                      # print the ETA without starting a run
   scripts/enforce-models --harness pi --model kimi-coding/k3   # preflight a seat model
   scripts/enforce-models --check-meta <run-dir>        # postflight gate: drift + unprovable provenance
   scripts/enforce-models --check-meta <run-dir> --expect <batch.json>  # also catch a child that wrote nothing
   scripts/acn-report <dir-of-meta.json>                # phase usage report + MODEL DRIFT check
   ```

   See `scripts/bm` and `references/autonomy-levels.md`.

## Optional LangGraph runtime

LangGraph support is additive. Existing shell and agent harnesses remain
usable with no LangGraph installation. Install the optional package in an
isolated environment:

```bash
python -m pip install -e 'python[langgraph]'
```

The package exposes `StateGraph` primitives, `Send` fan-out, checkpointed
autonomy gates, schema-backed ACN validation, isolated subprocess worktrees,
custom phase/executor streaming, and fail-closed model provenance. SQLite is
the local persistence default; PostgreSQL is opt-in with
`python -m pip install -e 'python[postgres]'`.

For a real CLI goal, provide the child driver explicitly:

```bash
bm "add a health check" --harness langgraph \
  --executor-command 'your-child-driver'
```

The driver receives `BEASTMODE_META_DIR`, `BEASTMODE_TASK_ID`, and
`BEASTMODE_REQUESTED_MODEL` (and the goal in `BEASTMODE_TASK_GOAL`), and must
write the canonical `meta.json` there.
Child processes run with a reduced environment, each child uses a disposable
git worktree, and worker `git commit`/`git push` attempts are blocked. A
missing or silent metadata file fails the provenance gate; tracing is optional
and never changes that verdict. See
[`references/beastmode-on-langgraph.md`](references/beastmode-on-langgraph.md),
[`adapters/langgraph/SKILL.md`](adapters/langgraph/SKILL.md), and
[`references/langgraph-pipeline.md`](references/langgraph-pipeline.md).

## One Vocabulary (v2.2)

Families, tiers, seats, autonomy levels, and the ACN fan-out contract are defined once in `schema/` (machine-readable) and rendered for humans in `references/families-tiers-seats.md`, `references/autonomy-levels.md`, `references/acn-contract.md`, and `references/tier-aliases.md`. Harness adapters (`adapters/hermes`, `pi/`, `adapters/claude-code`, `adapters/codex`, `adapters/langgraph`) implement the same rules: pinned executor models, per-child `meta.json` (requested vs actual), MODEL DRIFT always surfaces and blocks `validated`, and gates are blocking below `high` autonomy.

The provenance gate is fail-closed in both directions: a child whose model **differs** from the pinned one is `drift`, and a child whose model **cannot be established** — missing meta, unreadable meta, or a single merged `model` field instead of `requested_model` + `actual_model` — is `unverifiable`. Both block `validated`. One implementation (`scripts/lib/acn_meta.py`) backs both `enforce-models --check-meta` and `acn-report`, and it reads the required field list out of `schema/acn-contract.json` rather than hard-coding it.

## Files

- `SKILL.md` — The complete beastmode framework (start here)
- `schema/` — Machine source of truth: `families.json`, `tiers.json`, `seats.json`, `autonomy-levels.json`, `acn-contract.json`
- `adapters/hermes/SKILL.md` — Hermes ACN adapter (`delegate_task` background/batch)
- `adapters/claude-code/SKILL.md` — Claude Code adapter (Task, `/batch`, parallel `claude -p`)
- `adapters/codex/SKILL.md` — Codex adapter (parallel `codex exec`, external worker lanes; supersedes beastmode-cloud / beastmode-qwen-cloud)
- `adapters/langgraph/SKILL.md` — LangGraph adapter (`StateGraph`, `Send`, checkpointed gates)
- `python/` — optional installable package (`pip install 'beastmode[langgraph]'`)
- `references/model-routing.md` — Tier definitions, per-phase routing table, design package template, escalation ladder, provider config sketches
- `references/autonomy-levels.md` — `low` / `medium` (default) / `high` autonomy levels, mapped to pi/Hermes/Claude/Codex flags and surface rules
- `references/acn-contract.md` — The ACN fan-out contract (batch shape, child meta.json, shared rules)
- `references/families-tiers-seats.md` — Human view of the schema vocabulary
- `references/orchestration-comparison.md` — Evolution from early prototypes to v2.x
- `references/context-rot-mitigation.md` — MemroOS-style goal-state capsules, compact/resume rules, and MofA decision memory
- `references/public-sharing-checklist.md` — Guidelines for publishing beastmode skills publicly
- `pi/SKILL.md` — Pi harness adapter (`pi-coding-agent` ≥ 0.80.6 + 6 companion npm packages)
- `scripts/bm` — Runner CLI for one-shot goals with harness/tier picks, phase reports, and `--on` dispatch
- `scripts/enforce-models` — Model preflight/postflight (drift fail-closed) shared by all harnesses
- `scripts/acn-report` — Normalize ACN child metas into the phase usage report
- `scripts/lib/acn_meta.py` — The model-provenance gate itself (`ok` / `drift` / `unverifiable`), read by both of the above so they cannot disagree
- `scripts/lib/prompts.sh` — Shared phase/gate/model-failure prompt builders used by `bm` and adapters
- `scripts/phase-estimate` — Rough per-phase wall-clock estimate from the goal scope
- `scripts/install-beastmode-pi.sh` — Idempotent bootstrap of `pi` + 6 companion packages
- `tests/run-all.sh` — Every gate in one command (syntax, schema validity, ACN parity, `bm` preflight); what CI runs

## Testing

```bash
./tests/run-all.sh      # syntax + JSON validity + ACN parity + bm preflight
```

Runs on every push via `.github/workflows/tests.yml`, which additionally
asserts the suite leaves the working tree unmodified. The ACN parity test
covers the invariants prose alone can't hold: the drift gate fails closed on
unprovable provenance, `enforce-models` and `acn-report` return the same
verdict for the same directory, `references/acn-contract.md` lists exactly the
meta fields `schema/acn-contract.json` declares, and each adapter's canonical
version cross-reference matches `SKILL.md`.

## Compatibility

Works with:

- **Claude Code** (Opus-led or Codex-led)
- **Hermes Agent** (Codex-led with delegate_task)
- **OpenClaw** (Codex-led with delegate_task)
- **Codex CLI** (Codex-led with subagents)
- **Pi** (`pi-coding-agent` ≥ 0.80.6 + 6 companion packages — see `pi/SKILL.md`)
- **Any agent environment** with git and model access

## License

MIT — use it, fork it, improve it.
