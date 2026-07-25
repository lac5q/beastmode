# Autonomy Levels

How much the orchestrator decides on its own before surfacing to a human.
All three levels share the universal Beastmode hard rules (no workers
committing/pushing, no secrets, verifier-first, no watcher = no validated).

| Level | What runs without surfacing | What always surfaces | Default? |
|---|---|---|---|
| **low** | Single executor turn, one read-only tool call | Every phase transition, every merge, every cross-tier escalation, every Worker → Watcher jump, any diff > 1 file, **any model failure** | no |
| **medium** | Whole phase: acceptance → design package → delegate → validate → review | Security/auth/payments/data-loss events, tier-2/3 Watcher fallback, front-door merge gate, any `goal_blocked`, **any model failure** | **yes** |
| **high** | Multi-phase until goal_complete or 3 identical goal_blocked in a row with concrete evidence; one safe workaround after a model failure | budget_limited stop, watcher unavailable after all 3 tiers, any `"No watcher, no validated"` violation, telegram-bound secrets in prompt, model failure + workaround result | no |

**Default: medium.** Most feature work, most reviews, no chat spam — only the
high-risk gates escalate. Switch with `bm "<goal>" --autonomy low|high`.

## Surfacing is blocking below high

At **low** and **medium**, "surfaces" means **stops**: the run emits its phase
report, then halts and waits for human approval before the next phase or any
merge. It never continues past a surfaced gate on its own. Only **high**
proceeds through gates automatically (and even then it halts on its
always-surface events above). If a run at low/medium keeps going after a gate,
that is a harness bug — treat it as a `goal_blocked` and stop it.

## Per-phase usage reports (all levels)

Every phase ends with a usage report, at every autonomy level — this is how
you see cost as it accrues instead of at the end:

```
Phase <n> <name>: <status>
Models: requested <tier: provider/model> → actual <provider/model per task>
Tokens: <used> / <phase budget> (<percent>)  Time: <actual> vs <estimate>
Drift: none | MODEL DRIFT: <requested> → <actual> on <task(s)>
```

At low/medium the report is the gate — approval resumes the run. At high the
reports accumulate into the final output in order.

## Model drift always surfaces

**MODEL DRIFT** = a task was served by a model other than the requested
`provider/model` — router fallback, harness default, or silent substitution.
Detect it by comparing the worker `meta.json` `model` field (or harness
journal) against the resolved tier alias. Drift surfaces at **every** level,
including high, because it breaks two guarantees at once: cost (a frontier
substitute burns budget) and trust (an economy substitute on design-tier work
skips the judgment the gate assumed). Drifted work is not `validated` until
re-validated under the correct tier. Record every drift in the learning entry
— repeated drift on the same alias means the tier alias or provider config is
wrong.

## Mapping to pi flags

| Level | pi flag | What you give up |
|---|---|---|
| low    | `--approve` | All asks prompt you. Slowest, safest. |
| medium | (default)   | Phase transitions and tier-2/3 fallback surface. Routine work is silent. |
| high   | `--no-builtin-tools` (plus pi-permission-system config with `ask`→`deny` on publishing) | Workers can't even `git commit` without deny → evidence-only close-out. |

`--autonomy high` is only meaningful with a project-level permission config
(`<repo>/.pi/extensions/pi-permission-system/config.json`) that turns every
`ask` into `deny` for publishing/destructive ops. With that in place the run
becomes a long silent sequence that lands a compact final report on
goal_complete or halts on goal_blocked — never silently.

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
   --on maeve-u1 \
   --frontier kimi3 \
   --economy minimax
```

Worker prompt contract (universal — see `pi/SKILL.md`):
workers never commit/push, never reach secrets, never publish, return a
meta.json shape `{"id","model","stop_reason","usage":{...}}`.
