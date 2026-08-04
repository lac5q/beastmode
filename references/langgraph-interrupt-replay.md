# P0.2 — LangGraph interrupt replay spike

Date: 2026-08-03
Runtime: `langgraph==1.2.10` with `InMemorySaver`
Thread: one stable `thread_id` resumed with `Command(resume="approve")`

## Evidence

| Gate implementation | Writes before first interrupt | Writes after resume | Result |
|---|---:|---:|---|
| side effect before `interrupt()` | 1 | 2 | replay duplicates the side effect |
| `interrupt()` first, side effect after resume | 0 | 1 | side effect occurs exactly once |

Both graphs resumed successfully and returned `approved=True`. The first graph
confirmed that LangGraph re-enters the node from its beginning on resume.

## Authoring rule

`interrupt()` must be the first executable statement in every gate node. Gate
nodes must perform no file writes, report appends, counter increments, model
calls, or other observable side effects before it. Side effects belong after the
resume value has been received, and must be idempotent if the node can be
re-entered for another retry or resume.

This rule is a P3 acceptance invariant and must be asserted with a write-counter
test. A gate that writes a phase report before interrupting is incorrect even if
the final state looks right.
