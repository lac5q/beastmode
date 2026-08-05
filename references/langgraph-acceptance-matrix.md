# LangGraph roadmap acceptance matrix

This matrix records the evidence for the refreshed LangGraph roadmap. It is
intentionally separate from the implementation notes: a green aggregate test
does not by itself prove every phase exit.

| Phase | Requirement | Evidence | Status |
|---|---|---|---|
| P0.1 | Record provider provenance capability and decide direct-call eligibility | [`langgraph-provider-provenance.md`](langgraph-provider-provenance.md) records all schema families, the unsuccessful live Minimax probe, and the fail-closed subprocess fallback | Decision complete; direct-call gate remains closed |
| P0.2 | Prove `interrupt()` replay ordering | [`langgraph-interrupt-replay.md`](langgraph-interrupt-replay.md) records the duplicate-side-effect spike and the authoring rule; gate tests cover medium/low resume behavior | Complete |
| P0.3 | Measure lane grouping tradeoff | [`langgraph-lane-grouping.md`](langgraph-lane-grouping.md) records the grouped/interleaved analytical estimate and the resulting grouped dispatcher | Complete as estimate; live provider tokens unavailable |
| P1 | Ship a dependency-free core and optional package boundary | `python/tests/test_core_boundary.py`, `test_schema.py`, `test_prompts.py`, `test_contract.py`; `PYTHONPATH=python/src python3 -S` base import; `./tests/run-all.sh` | Complete |
| P2 | Share canonical schema and provenance verdicts; fail closed | `test_provenance.py`, `test_seat_provenance.py`, executor provenance tests, and ACN parity check e3/e4/e6 | Complete |
| P3 | Build checkpointed pipeline with autonomy gates | `test_pipeline.py` verifies medium resume, high no-interrupt, low phase-by-phase interruptions, replay-safe side effects, and high-autonomy drift blocking; [`langgraph-pipeline.md`](langgraph-pipeline.md) matches the graph | Complete |
| P4 | Fan out with `Send`, isolate worktrees, and reject silent children | `test_pipeline.py::test_three_children_fan_out_and_rejoin_by_lane` proves concurrent child wall time and slowest-child join; `test_executor.py` covers isolation/blocked-git/killed-child cases | Complete |
| P5 | Provide CLI, persistence, replay, and Mermaid export | `test_runner.py`, `test_runtime.py`; absent system runtime exits 2 with an install hint; real `bm --harness langgraph` smoke reached merged status | Complete |
| P6 | Support foreign state, embedded subgraphs, primitives, and Studio | `test_composability.py`; all four snippets in [`langgraph-templates.md`](langgraph-templates.md) execute in `test_docs.py`; `python/scripts/studio-smoke.py` starts `langgraph dev`, discovers `pipeline`, and checks `/ok` | Complete |
| P7 | Document, package, and preserve the existing lane | `./tests/run-all.sh` (10/10), `pytest python/tests` (124 pass), `lint-imports`, `python -m build`, isolated-wheel import, CI workflow, adapter vocabulary and tracing fail-open checks | Complete locally |
| Release | Run security gate, publish README and implementation, merge, and clean branches | Local sensitive-artifact checks pass; official Codex Security completion and GitHub publication remain external release gates | Pending |

## Cross-cutting evidence

- `beastmode.core` has no framework imports; LangGraph dependencies are
  optional extras in `python/pyproject.toml`.
- Subprocess children receive a reduced environment, run in disposable Git
  worktrees inside a Linux `bubblewrap` filesystem sandbox, see the shared
  checkout and Git metadata read-only, and have normal `git commit`/`git push`
  blocked by the executor shim.
- Missing or drifted `meta.json` provenance is never synthesized or converted
  into a pass. The canonical checker remains `scripts/lib/acn_meta.py`.
- Trace records and custom stream events are optional; they do not determine a
  provenance or merge verdict.
- The repository security guard checks credential signatures, machine-specific
  paths, and credential-like filenames in CI. It is a defense in depth measure,
  not a substitute for the required release scan.
