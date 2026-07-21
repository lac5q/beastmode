# Autonomy Levels

How much the orchestrator decides on its own before surfacing to a human.
All three levels share the universal Beastmode hard rules (no workers
committing/pushing, no secrets, verifier-first, no watcher = no validated).

| Level | What runs without surfacing | What always surfaces | Default? |
|---|---|---|---|
| **low** | Single executor turn, one read-only tool call | Every phase transition, every merge, every cross-tier escalation, every Worker → Watcher jump, any diff > 1 file | no |
| **medium** | Whole phase: acceptance → design package → delegate → validate → review. Same-tier retries | Security/auth/payments/data-loss events, Watcher fallback landed on tier 2/3, merge gate on the front door, any goal_blocked | **yes** |
| **high** | Multi-phase until goal_complete or 3 identical goal_blocked in a row with concrete evidence | budget_limited stop, watcher unavailable after all 3 tiers, any `"No watcher, no validated"` violation, telegram-bound secrets in prompt | no |

**Default: medium.** Most feature work, most reviews, no chat spam — only the
high-risk gates escalate. Switch with `bm "<goal>" --autonomy low|high`.

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
