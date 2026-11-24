# Local backend component spike

This directory contains the bounded 2026-09-27 CLM and Laya-MLX feasibility
artifacts. It is an ignored working tree output and contains no production
integration, credentials, cloud provisioning, M3 latency claim, or advertised
task-accuracy result.

Inputs were inspected at these immutable commits:

- CLM: `bb42c6c5bf914fd449bed2f6ca65be80602cb1f7`
- Laya-MLX: `0a859518634112655cb97c745dbf04f5191aaf13`

The CLM smoke uses the genuine 75,557,149-byte projection-head checkpoint and
a deterministic synthetic embedding source. Synthetic embeddings are explicitly
`FAKE NONSEMANTIC`; the smoke only checks loading, tensor contracts, schema
contracts, invalid input handling, and cache reuse. The 32-case runner is ready
for a real encoder endpoint but was not run here.

The Laya-MLX preflight installs the package's non-platform dependencies and runs
pure-Python contract checks. MLX model loading is unavailable on this Linux
x86_64 host because the project declares MLX only for Darwin arm64.

See `commands.md` for reproducible commands, `clm/REPORT.md` and
`laya-mlx/REPORT.md` for results, and the per-backend dependency/weight
receipts.
