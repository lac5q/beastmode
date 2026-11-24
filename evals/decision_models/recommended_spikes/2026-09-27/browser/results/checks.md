# Bounded browser-loop spike checks

Source checkout: `1231850a0bf1a0c0341fe408ef1668dbbfdfac46`.

Fixture: `source/jev_ultrafast/static/fixture.html`, SHA-256
`e48e7d7b6225b215060692e0a28c3d0b59e465e4b94c1bc510d5f37ff0b8bfbe`.

The copied checkout was installed with `uv sync --frozen --python 3.12` into
`source/.venv`. No `.env` was used and no model credentials were read by the
worker.

Checks completed:

- `uv run pytest -q`: 31 passed.
- `uv run ruff check .`: passed.
- `node --check jev_ultrafast/static/app.js`: passed.
- `node --check jev_ultrafast/snapshot.js`: passed.
- `uv build`: wheel and sdist built.
- `uv run python scripts/check_guards.py`: 21/21 local browser guard checks passed with no model calls.
- `uv run --project source python offline_faults.py`: 5/5 offline contract checks passed; see `offline-faults.json`. The malicious-page and external-navigation cases exercise the independent validator only; they do not claim live agent prompt-injection resistance.
- Dedicated Chrome 152 headless CDP connected at `http://127.0.0.1:9229` using scratch `chrome-profile`; the local fixture transport is loopback only.

The live Jev plus writer run was intentionally not invoked by this worker. The
root agent can opt in with `run_local_trials.py`; it requires credentials in the
caller environment, refuses non-loopback CDP, and writes one raw model receipt
JSONL plus per-tick state and verification files for each trial. The runner
enforces at most three trials, 20 actions per trial, and 60 seconds per
decision. The exact goal and exact DOM acceptance values are frozen in
`contract.json`; the validator accepts only those DOM values and ignores a
model `DONE` claim.

Provenance requested: `5.6 Luna Max`. Actual backend: `unverified`.
