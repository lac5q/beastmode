# Autonomy Levels

How much the orchestrator decides on its own before surfacing to a human.
All three levels share the universal Beastmode hard rules (no workers
committing/pushing, no secrets, verifier-first, no watcher = no validated).

> Machine source of truth: `schema/autonomy-levels.json`. This file is the
> human view; if the two disagree, the schema wins.

| Level | What runs without surfacing | What always surfaces | Default? |
|---|---|---|---|
| **low** | Single executor turn, one read-only tool call | Every phase transition, every merge, every cross-tier escalation, every Worker → Watcher jump, any diff > 1 file, **any model failure** | no |
| **medium** | Whole phase: acceptance → design package → delegate → validate → review | Security/auth/payments/data-loss events, tier-2/3 Watcher fallback, front-door merge gate, any `goal_blocked`, **any model failure** | **yes** |
| **high** | Multi-phase until goal_complete or 3 identical goal_blocked in a row with concrete evidence; one safe workaround after a model failure | budget_limited stop, watcher unavailable after all 3 tiers, any `"No watcher, no validated"` violation, telegram-bound secrets in prompt, model failure + workaround result | no |

**Default: medium.** Most feature work, most reviews, no chat spam — only the
high-risk gates escalate. Switch with `bm "<goal>" --autonomy low|high`.

## Interview scaling

The autonomy interview matrix is defined by `schema/autonomy-levels.json`; the
schema wins if this prose differs. The full protocol, including gray-area
identification and harness mapping, is in `references/goal-interview.md`.

| Level | Upfront | In-process | Question budget |
|---|---|---|---|
| **low** | full | gate-questions | unbounded |
| **medium** (default) | batched | gate-questions | 5 |
| **high** | batched | escalation-only | 5 upfront only |

Any non-interactive lane downgrades to assumptions-only and logs
`interview downgraded: non-interactive lane` in the phase report.

## Surfacing is blocking below high

At **low** and **medium**, "surfaces" means **stops**: the run emits its phase
report, then halts and waits for human approval before the next phase or any
merge. It never continues past a surfaced gate on its own. Only **high**
proceeds through gates automatically (and even then it halts on its
always-surface events above). If a run at low/medium keeps going after a gate,
that is a harness bug — treat it as a `goal_blocked` and stop it. Gates also
present accrued open questions; unanswered items block exactly like unapproved
phases.

## Per-phase usage reports (all levels)

Every phase ends with a usage report, at every autonomy level — this is how
you see cost as it accrues instead of at the end:

```
Phase <n> <name>: <status>
Models: requested <tier: provider/model> → actual <provider/model per task>
Tokens: <used> / <phase budget> (<percent>)  Time: <actual> vs <estimate>
Drift: none | MODEL DRIFT: <requested> → <actual> on <task(s)>
Open questions: <n> (answered <a>, deferred <d>) | none
Workers: <id>: <model> <tokens> (<pct of phase>) <status>; ...
```

At low/medium the report is the gate — approval resumes the run. At high the
reports accumulate into the final output in order. The append-only ledger at
`.beastmode/LEDGER.md` and the compact progress digest at every phase gate and
at least once per hour apply at every autonomy level; reporting is not
autonomy-scaled.

## Model drift always surfaces

**MODEL DRIFT** = a task was served by a model other than the requested
`provider/model` — router fallback, harness default, or silent substitution.
Detect it by comparing the worker `meta.json` `actual_model` against its
`requested_model` (shape: `schema/acn-contract.json`; tooling:
`scripts/enforce-models --check-meta` and `scripts/acn-report`, both of which
run the same checker in `scripts/lib/acn_meta.py`). A meta that carries only a
single `model` field cannot prove drift either way — it is **unverifiable**,
which fails the gate exactly like drift does. Drift surfaces at **every** level,
including high, because it breaks two guarantees at once: cost (a frontier
substitute burns budget) and trust (an economy substitute on design-tier work
skips the judgment the gate assumed). Drifted work is not `validated` until
re-validated under the correct tier. Record every drift in the learning entry
— repeated drift on the same alias means the tier alias or provider config is
wrong.

## Mapping to harness flags

The autonomy scale is one vocabulary; each harness enforces it with its own knobs. Adapters (`adapters/hermes`, `pi/`, `adapters/claude-code`, `adapters/codex`) implement the same gate/drift semantics on top of these mappings.

| Level | pi flag | Hermes ACN | Claude Code | Codex | What you give up |
|---|---|---|---|---|---|
| low    | `--approve` | approval before each delegate_task batch; every child result surfaces; merges wait | plan/ask permission mode before each batch; no Task storm | approval prompts on; no `--yolo`; no background free-run | All asks prompt you. Slowest, safest. |
| medium | (default)   | batches run silently; surface security/auth/payments, model failure, MODEL DRIFT, goal_blocked, merge gate | default mode; batches silent; same always-surface list | default sandbox; batches silent; same always-surface list | Phase transitions and tier-2/3 fallback surface. Routine work is silent. |
| high   | `--exclude-tools bash,edit,write` (plus pi-permission-system config with `ask`→`deny` on publishing) | multi-batch until goal_complete / repeated goal_blocked; still halts on budget, no-watcher, secrets, unrevalidated drift | normal permission mode; same halt events | normal sandbox and approval mode; same halt events | Director retains read/search access for evidence; mutation-capable built-ins are disabled and the permission policy remains fail-closed. |

`--autonomy high` is only meaningful with a project-level permission config
(`<repo>/.pi/extensions/pi-permission-system/config.json`) that turns every
`ask` into `deny` for publishing/destructive ops. With that in place the run
becomes a long silent sequence that lands a compact final report on
goal_complete or halts on goal_blocked — never silently.
Autonomy controls continuation and batching only. It never disables a harness
sandbox, approval prompt, or permission policy.

## Surface rules (apply to all levels)

- Tier 2 / tier 3 Watcher degradation always surfaces — it's a budget signal
  the weekly `bm-lesson-promoter` review consumes.
- A goal that's been `goal_blocked` three consecutive turns on the same
  evidence always surfaces. No fourth attempt.
- A run that exceeds 4 hours wall-clock always surfaces for a budget check,
  regardless of level.

## Adding the autonomy argument to a goal

```
bm "ship the new ingest endpoint behind a feature flag" \
   --autonomy medium \
   --on <remote-host> \
   --frontier kimi3 \
   --economy minimax
```

Worker prompt contract (universal — see `pi/SKILL.md`):
workers never commit/push, never reach secrets, never publish, and return the
meta.json shape declared in `schema/acn-contract.json`:
`{"id","requested_model","actual_model","stop_reason","usage":{...},"files_changed","commands_run","verify"}`.

`requested_model` and `actual_model` are both required and must be separate
fields. A worker that reports one merged `model` gives the gate nothing to
compare, and an unprovable child is never `validated`.
