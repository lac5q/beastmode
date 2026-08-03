# ROADMAP — Run visibility (`acn-trace`)

**Status:** planned, not started. Independent of the LangGraph effort — nothing
here needs LangGraph, and it works on every harness beastmode already supports.

## The problem

Today you can't see what a beastmode run is doing. Work happens across parallel
workers, the run finishes, and the only record is a pile of files on disk plus
whatever scrolled past in the terminal. There's no place to look at a run
afterwards, and no way to compare two runs.

The LangGraph effort fixes this eventually, but it's several phases away and
serves a different purpose. This is the short path.

## The idea

**Beastmode already collects everything needed. It just never sends it
anywhere.**

Every worker writes a `meta.json` receipt when it finishes — which model was
asked for, which model actually ran, tokens used, how it stopped, which files it
touched, which commands it ran, whether checks passed. `scripts/acn-report`
already reads those into a text summary, and `scripts/lib/acn_meta.py` already
classifies each one as pass / drift / unprovable.

That receipt is, structurally, a trace entry. It has a model, a cost, and an
outcome. Turning a directory of receipts into a run tree on LangSmith is a
reading-and-posting job, not a new instrumentation project.

**Three things fall out of that:**

1. **It works today, on every harness** — hermes, pi, claude, codex. The
   receipts don't care which one produced them.
2. **It doesn't depend on LangGraph at all.** If the LangGraph effort slips or
   gets dropped, this still works.
3. **The privacy problem mostly disappears.** Receipts hold model names, token
   counts, file paths, and pass/fail. No prompts, no diffs, no source code. This
   is a much smaller thing to send off the machine than tracing a live graph
   would be, which is exactly why it can ship sooner.

## What ships

`scripts/acn-trace <run-dir>` — a sibling of `acn-report`, taking the same
input and reusing the same reader. Where `acn-report` renders text, `acn-trace`
posts a run tree.

Shape of what lands in LangSmith:

- one parent entry per run or phase
- one child entry per worker receipt, nested under it
- details attached: goal id, phase, seat (director / watcher / executor),
  harness, autonomy level, requested model, actual model, tokens
- labels attached: `beastmode`, `seat:<name>`, and — the useful one —
  `drift` or `unverifiable` whenever the gate didn't return a clean pass

That last label is the payoff. "Show me every run last month where a worker
used the wrong model" becomes a filter instead of a search across run
directories.

## Rules it must follow

1. **Never load-bearing.** Tracing being off, broken, or unreachable must have
   no effect on whether a run passes its gate. The gate stays
   `scripts/lib/acn_meta.py` reading receipts off disk. A monitoring outage that
   makes failing work look approved is the same class of bug the v2.3 review
   closed twice — see `.learnings/BEASTMODE.md`.
2. **Never required.** Beastmode works with no tracing configured and nothing
   installed. `./tests/run-all.sh` keeps passing with zero Python packages
   present. Missing credentials produce a clean skip, not an error.
3. **One reader.** `acn-trace` calls `acn_meta.py` like the other two tools do.
   A third way of parsing receipts would be the "one contract, two
   implementations" problem again.
4. **Nothing new for workers to write.** If this needs a field workers don't
   already produce, that's a schema change and gets decided on its own merits
   (see the timestamps question below) — not smuggled in.

## Phases

| Phase | Scope | Done when |
|---|---|---|
| **V0** | Decide the two open questions below | Written answers |
| **V1** | `scripts/acn-trace <run-dir>`, run by hand after a run | A finished run appears in LangSmith with one entry per worker, correct models and token counts, drift labelled; missing credentials skip cleanly; `tests/run-all.sh` unaffected with nothing installed |
| **V2** | `bm` calls it at phase close when tracing is switched on | A normal `bm` run shows up without any extra command; tracing off, broken, and pointed at a dead address all produce identical gate results (tested by deliberately breaking each) |
| **V3** | Live view during the run, not only after | Workers appear as they finish rather than at the end. Hermes already writes live transcripts under `~/.hermes/cache/delegation/live/`, so it goes first; other harnesses follow if their runtimes expose the same |

V1 is the whole point. V2 is convenience. V3 is optional and only worth doing if
V1 turns out to get used.

## Open questions

**Q1 — Receipts have no timestamps.** A trace entry needs a start and an end.
The required fields are id, requested model, actual model, stop reason, usage,
files changed, commands run, and verify — no times. Options: (a) approximate
from file modification time, which is rough but needs no schema change;
(b) add optional `started_at` / `ended_at` to `schema/acn-contract.json` and
have harness adapters fill them in. **Leaning (b) with (a) as fallback** —
durations are most of the value of a trace, and "which worker was slow" is a
question you'll want answered. But it touches the schema, so it's a real
decision.

**Q2 — Official SDK, or plain HTTP?** The LangSmith SDK is a Python package.
Every other script in this repo runs on the standard library alone, which is
why `tests/run-all.sh` needs no install. LangSmith also has a plain HTTP ingest
endpoint. **Leaning plain HTTP** — it keeps the repo dependency-free, which is
worth more than SDK convenience for a script this small. The cost is writing
the request bodies by hand and tracking their format.

**Q3 — Does it need to handle runs with no fan-out?** A single-worker run
still produces a receipt. Probably yes and probably free, but worth confirming
rather than discovering.

**Q4 — Project naming.** One LangSmith project for all beastmode runs, or one
per repo? Per-repo is likely right, but it affects how filters and comparisons
work later.

## Relationship to the LangGraph effort

These don't compete; the second reuses the first.

`.planning/langgraph/` already scopes reconstructing worker entries from
receipts, because LangGraph has the same blind spot for exactly the same reason
— the workers run as separate programs it can't see inside. Building
`acn-trace` first means that phase becomes "call the existing tool" instead of
"build a tracing layer".

So this is worth doing even if the LangGraph work never starts, and it makes
the LangGraph work smaller if it does.
