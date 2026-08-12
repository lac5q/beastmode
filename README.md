# Beastmode 🔥 — "Chefs design it. Line cooks build it. The house keeps the receipts."

**Beastmode is a Mixture-of-Agents (MofA) orchestration framework** for AI-assisted software development that's equal parts mad scientist and ruthless accountant. It splits the work the way a great kitchen runs a dinner service: the **chefs** (frontier models) design the menu, taste-test every plate, and sign off at the door; the **line cooks** (cheap executor models) churn out the dishes and run the verification. And the whole operation gets *smarter every single shift*.

It runs with Hermes Agent, OpenClaw, Claude Code, Codex, Qwen, LangGraph, and `pi-coding-agent`, and it talks to your editor over ACP.

Exact search aliases: **beastmode**, **MofA**, **Mixture of Agents**, **memroos**, **Hermes Agent**, **OpenClaw**, **agent orchestration**, **context rot mitigation**.

**In plain English, Beastmode:**

- 💸 **Saves you a small fortune** — routes implementation *and mechanical validation* to the pinned Luna Max economy lane (`gpt-5.6-luna`) while keeping frontier models (Claude Fable, Kimi 3, Opus, Codex) for the design, judgment, and review only geniuses should sign off on.
- 🧠 **Improves quality** — mandatory acceptance contracts, adversarial review, and merge gates that actually mean something.
- 📈 **Gets better over time** — a self-improvement loop that writes down its lessons and promotes the patterns that keep winning into skills/config.
- 🧩 **Works anywhere** — harness-agnostic across Ultraswarm, GSD, `delegate_task`, Claude Code subagents, LangGraph, manual git, or `pi-coding-agent`.
- 🔁 **Upgrades itself** — a real installer (`bm install` / `bm upgrade` / `bm uninstall`) with clean versioned snapshots, so you're never stranded on a stale snapshot fighting yesterday's bugs.

## 🚀 Install it. Upgrade it. Uninstall it. (It actually works.)

Yes — Beastmode finally has the installer it's been begging for: one idempotent, GSD-style command with immutable versioned snapshots and an uninstall that leaves no trace (except, perhaps, the dramatic exit).

From a checkout, install the `bm` launcher plus the full runtime to `~/.local`:

```bash
./scripts/install-beastmode.sh                # install (default) — idempotent
./scripts/install-beastmode.sh status         # what's installed, where, how many files it owns
./scripts/install-beastmode.sh doctor         # check prerequisites + snapshot integrity
./scripts/install-beastmode.sh upgrade        # re-snapshot; --source git pulls the newest release
./scripts/install-beastmode.sh --yes uninstall  # clean uninstall (manifest-driven)
```

Once installed, `bm` manages itself — no cargo cult, no manual byte-shuffling:

```bash
bm install      # snapshot the framework, link bm into PATH
bm upgrade      # atomically re-point `current` to the newest snapshot
bm status       # version, source, install date, tracked files
bm doctor       # sanity-check python3, the bm link, and snapshot integrity
bm version      # which beastmode are you even on?
bm uninstall    # remove exactly what was installed — and nothing else
```

Scope it to one project with `--local`, or drop the skill into a runtime with `--runtimes claude,codex,cursor`. Under the hood every install is an **immutable versioned snapshot** behind a `current` symlink, tracked by a manifest — so upgrades are atomic, rollback is a one-symlink fix, and uninstall never touches a file it didn't create.

## The one-liner zoo

```bash
bm "<goal>"                                      # print the ETA, then run it locally (pi harness)
bm "<goal>" --harness hermes                     # Hermes ACN: async parallel sub-agents
bm "<goal>" --harness claude|codex|langgraph     # pick your poison
bm "<goal>" --harness langgraph --executor-command '<child command>'
bm "<goal>" --gsd --frontier kimi3 --economy luna-max   # pick tiers, force GSD gating
bm "<goal>" --frontier kimi3 --watcher grok      # cross-family watcher
bm "<goal>" --on <remote-host>                   # dispatch to a fleet node
bm "<goal>" --autonomy low|medium|high           # how loud should this be about itself?
scripts/phase-estimate "<goal>"                  # the ETA, without starting the fire
```

See `scripts/bm` and `references/autonomy-levels.md`.

## What is Beastmode?

Beastmode is an orchestration pattern for AI-assisted development and long-running agent goals. It uses MofA / Mixture of Agents at every decision gate, cheap executors for the bounded implementation work, and MemroOS-style durable state handoffs so agents never resume from a gnarly compressed chat history alone.

## Core Principle

**Frontier models design. Cheap models build and validate. The loop learns.**

The routing rule underneath: a task goes to a cheap model exactly when its output can be cheaply verified (tests, schema, contract); frontier models handle work that only judgment can verify — and their real job is *creating verifiability* (contracts, interfaces, verification commands) so as much work as possible becomes cheap-routable.


## Model Tiers

- **Design tier (frontier):** Claude Fable, Kimi 3, Opus, frontier Codex/GPT — architecture, acceptance contracts, judgment review, escalations
- **Execution tier (economy):** Luna Max (`gpt-5.6-luna`) by default — implementation, tests, docs, and mechanical validation (running verification commands, producing pass/fail reports)

See `references/model-routing.md` for the per-phase routing table and escalation ladder.

## Two Variants

- **Frontier-led:** Maximum judgment for product/creative/architecture decisions. Fable or Kimi 3 directs (optionally pairing the two — one designs, the other challenges), Luna Max executes and validates.
- **Codex-led:** Cost-efficient lead with strong gates. Codex plans and reviews, Luna Max executes.

## Autonomy Levels

Beastmode runs with one of three autonomy levels — how much the orchestrator decides on its own before surfacing to a human. **Default: medium.** Below `high`, surfaced gates are **blocking** — the run posts its per-phase usage report (requested vs actual models, tokens vs budget, time vs estimate) and stops for approval; only `high` rolls through gates on its own. **Model drift** (a task served by a model other than the one requested) surfaces at every level.

| Level | Surfaces to you | Best for |
|---|---|---|
| **low** | every phase transition, every merge gate, every cross-tier escalation | high-stakes / first runs in a new repo |
| **medium** (default) | security/auth/payments, tier-2/3 Watcher fallback, front-door merge gates, `goal_blocked` | most feature work — chat stays quiet unless something breaks |
| **high** | budget exhaustion, "no watcher no validated", secrets in prompts | fire-and-forget multi-phase runs — needs a locked permission config |

See `references/autonomy-levels.md` for the full table and pi-flag mapping.

## First run, in five easy steps

1. Read `SKILL.md` — the full framework (the whole enchilada).
2. Pick your variant (frontier-led or Codex-led) and map your models to tiers (`references/model-routing.md`).
3. Pick your harness: Ultraswarm, GSD, `delegate_task`, Claude Code subagents, LangGraph, manual git, or `pi` + `pi-dynamic-workflows`.
4. Run the loop: Preflight → Acceptance Contract → Design (frontier) → Delegate (economy) → Validate (economy) → Review (frontier) → Merge → Self-Improve.
5. Optional hardening gates (postflight provenance, usage reports):

```bash
scripts/enforce-models --harness pi --model kimi-coding/k3              # preflight a seat model
export BEASTMODE_ATTESTATION_KEY="$(openssl rand -hex 32)"
export BEASTMODE_ATTESTATION_RUN_ID="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
scripts/enforce-models --check-meta <run-dir> --attestations <trusted.json> --trust-attestations
scripts/acn-report <dir-of-meta.json> --attestations <trusted.json> --trust-attestations   # usage + MODEL DRIFT
```

Anthropic director aliases (`fable`, `opus`, `opus5`, `sonnet`, `haiku`) automatically use the single-seat `claude -p` plan-mode lane. Multiple Anthropic seats fail closed; Beastmode does not fall back to API OAuth for subscription seats.


## Editor goals via ACP

The optional thin ACP adapter makes Beastmode goals launchable from ACP-aware
editors without duplicating the orchestration runtime. It speaks ACP v1 over
stdio and forwards `session/prompt` to the existing `bm` runner:

```bash
python -m pip install -e python/
beastmode --acp
# or: beastmode-acp
```

The default backend is `bm --autonomy {autonomy}`. Set
`BEASTMODE_ACP_BACKEND_JSON` for a non-shell argv template; the adapter keeps
editor text after `--` and never evaluates it as shell syntax. See
[`adapters/acp/SKILL.md`](adapters/acp/SKILL.md) and the submission-shaped
[`registry-entry.example.json`](adapters/acp/registry-entry.example.json).
This is an editor/registry boundary only: Beastmode still owns permissions,
model routing, worktrees, gates, provenance, and learning.

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

The smallest integrations are importable directly:

```python
from beastmode.langgraph import autonomy_gate, build_fanout, provenance_gate
from beastmode.langgraph.graphs.pipeline import build_pipeline
```

Use `provenance_gate` in an existing graph, `build_fanout()` for lane-grouped
ACN execution without the full loop, or `build_pipeline()` for the complete
checkpointed workflow. All four executable patterns are in
[`references/langgraph-templates.md`](references/langgraph-templates.md).

For a real CLI goal, provide the child driver and trusted parent-side evidence,
validation, and review helpers explicitly:

```bash
bm "add a health check" --harness langgraph \
  --executor-command 'your-child-driver' \
  --attestor-command /trusted/bin/read-harness-journal \
  --validator-command /trusted/bin/validate-result \
  --reviewer-command /trusted/bin/review-result
```

The driver receives `BEASTMODE_META_DIR`, `BEASTMODE_TASK_ID`, and
`BEASTMODE_REQUESTED_MODEL` (and the goal in `BEASTMODE_TASK_GOAL`), and must
write the canonical `meta.json` there. The worker record is not trusted as its
own model proof; the attestor produces parent-owned evidence outside the
worker-writable run tree. The validator and reviewer must explicitly pass
before the trusted runtime wrapper can invoke a merger.
Child processes run with a reduced environment, each child uses a disposable
git worktree, and the optional runtime requires a Linux `bubblewrap` filesystem
sandbox so the shared checkout and Git metadata are read-only to workers.
Worker `git commit`/`git push` attempts are also rejected by the Git shim. A
missing or silent metadata file fails the provenance gate; tracing is optional
and never changes that verdict. See
[`references/beastmode-on-langgraph.md`](references/beastmode-on-langgraph.md),
[`adapters/langgraph/SKILL.md`](adapters/langgraph/SKILL.md), and
[`references/langgraph-pipeline.md`](references/langgraph-pipeline.md). Optional
LangSmith/OTel setup, masking, sampling, and fail-open regressions are covered
in [`references/observability.md`](references/observability.md).

## One Vocabulary (v2.4)

Families, tiers, seats, autonomy levels, and the ACN fan-out contract are defined once in `schema/` (machine-readable) and rendered for humans in `references/families-tiers-seats.md`, `references/autonomy-levels.md`, `references/acn-contract.md`, and `references/tier-aliases.md`. Harness adapters (`adapters/hermes`, `pi/`, `adapters/claude-code`, `adapters/codex`, `adapters/langgraph`) implement the same rules: pinned executor models, per-child `meta.json` (requested vs actual), MODEL DRIFT always surfaces and blocks `validated`, and gates are blocking below `high` autonomy.

The provenance gate is fail-closed in both directions: a child whose independently attested serving model **differs** from the pin is `drift`, while missing/unreadable metadata, a legacy merged `model` field, or a worker-authored `actual_model` without parent/provider evidence is `unverifiable`. Both block `validated`. Parent/provider attestations are authenticated with a parent-held key and bind the run ID plus the exact child-result digest; replacement, result tampering, and cross-run replay fail closed. The LangGraph runtime manages this key in memory. Standalone tools receive it through `BEASTMODE_ATTESTATION_KEY` and `BEASTMODE_ATTESTATION_RUN_ID` and additionally require current-user/root-owned, non-group/world-writable evidence outside the worker-writable run directory. One implementation (`scripts/lib/acn_meta.py`) backs both `enforce-models --check-meta` and `acn-report`.

## Files

- `SKILL.md` — The complete beastmode framework (start here)
- `schema/` — Machine source of truth: `families.json`, `tiers.json`, `seats.json`, `autonomy-levels.json`, `acn-contract.json`
- `adapters/hermes/SKILL.md` — Hermes ACN adapter (`delegate_task` background/batch)
- `adapters/claude-code/SKILL.md` — Claude Code adapter (Task, `/batch`, one `claude -p` watcher)
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
- `scripts/bm` — Runner CLI for one-shot goals with harness/tier picks, phase reports, and `--on` dispatch; also self-manages via `bm install` / `upgrade` / `status` / `doctor` / `version` / `uninstall`
- `scripts/install-beastmode.sh` — The 🚀 GSD-style installer: idempotent, versioned snapshots, manifest-driven clean uninstall, `--global` / `--local` / `--runtimes`
- `scripts/enforce-models` — Model preflight/postflight (drift fail-closed) shared by all harnesses
- `scripts/acn-report` — Normalize ACN child metas into the phase usage report
- `scripts/lib/acn_meta.py` — The model-provenance gate itself (`ok` / `drift` / `unverifiable`), read by both of the above so they cannot disagree
- `scripts/lib/prompts.sh` — Shared phase/gate/model-failure prompt builders used by `bm` and adapters
- `scripts/phase-estimate` — Rough per-phase wall-clock estimate from the goal scope
- `scripts/install-beastmode-pi.sh` — Idempotent bootstrap of `pi` + 6 companion packages
- `tests/test-install-beastmode.sh` — Hermetic lifecycle test for the installer (`install` → `upgrade` → `status` → `uninstall`)
- `tests/run-all.sh` — Every gate in one command (syntax, schema validity, ACN parity, `bm` preflight, installer lifecycle); what CI runs

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
- **LangGraph 1.2.x** (optional `beastmode[langgraph]` runtime and Studio manifest)
- **Any agent environment** with git and model access

## License

MIT — use it, fork it, improve it.
