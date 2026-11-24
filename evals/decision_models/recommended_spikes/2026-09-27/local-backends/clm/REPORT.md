# CLM bounded component smoke

Source pin: `bb42c6c5bf914fd449bed2f6ca65be80602cb1f7`.

The isolated CPython 3.12.3 environment installed CPU-only `torch==2.14.0+cpu`,
NumPy, requests, and FastAPI. vLLM was deliberately not installed. The genuine
head is recorded in `weights-receipt.json`.

The head loaded with `TORCH_FORCE_WEIGHTS_ONLY_LOAD=1`, which is required for the
pinned source's `torch.load` call. The checkpoint contains the expected state and
action head state dicts, a 4096-wide input, 512-wide projections, and a scale of
100.0. The smoke observed 18,887,680 head parameters. Projected state and action
rows were finite and had maximum unit-norm error `1.19e-07`.

`synthetic_contract_smoke.py` used deterministic SHA-256-seeded NumPy noise as
the embedding source. This is explicitly `FAKE NONSEMANTIC`: it cannot measure
encoder quality, task accuracy, calibration, or advertised CLM inference. It
did exercise the real projection weights, Noul/Choice/Score answer contracts,
invalid question/temperature/model handling, and a 1 MiB bounded cache. The
second identical request reused every cached vector and spent zero new synthetic
tokens.

`run_frozen_32_choice_cases.py` is a ready runner for the repository's frozen
32-case Choice fixture. It requires a caller-provided real encoder endpoint and
does not read API keys. It was intentionally not run because no endpoint was
provided; therefore there is no 32-case accuracy or latency result.
