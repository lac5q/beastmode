# Commands and scope receipt

Host: Linux x86_64 under WSL2, 12 GiB RAM, no CUDA, Python 3.12.3, uv 0.11.6.
CPU threads were capped at two for inference checks (`OMP_NUM_THREADS=2`,
`MKL_NUM_THREADS=2`). No API key was read and no paid or remote model call was
made.

## CLM setup and smoke

```sh
uv venv --python /usr/bin/python3.12 \
  .beastmode/recommended-spikes-20260927/local-backends/clm/.venv
uv pip install --python .../clm/.venv/bin/python \
  --index-url https://download.pytorch.org/whl/cpu 'torch>=2.6,<3'
uv pip install --python .../clm/.venv/bin/python \
  --index-url https://pypi.org/simple 'numpy>=1.24' 'requests>=2.28' 'fastapi>=0.100'
PYTHONPATH=/tmp/beastmode-local-repos-20260927/clm/src \
  TORCH_FORCE_WEIGHTS_ONLY_LOAD=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  .../clm/.venv/bin/python .../clm/synthetic_contract_smoke.py
```

The CLM source was loaded through `PYTHONPATH`; installing its project metadata
was intentionally skipped because its default dependency set includes vLLM.

The ready real-encoder runner requires an endpoint URL that already serves the
Qwen3-8B embedding contract. It does not read `CLM_API_KEY` or any other key:

```sh
PYTHONPATH=/tmp/beastmode-local-repos-20260927/clm/src \
  TORCH_FORCE_WEIGHTS_ONLY_LOAD=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  .../clm/.venv/bin/python .../clm/run_frozen_32_choice_cases.py \
  --endpoint 'http://127.0.0.1:8090/v1/embeddings' \
  --cases evals/decision_models/agent_folder_cases.json
```

No encoder endpoint was available for this spike, so the 32 cases were not run.

## Laya-MLX setup and preflight

```sh
uv venv --python /usr/bin/python3.12 \
  .beastmode/recommended-spikes-20260927/local-backends/laya-mlx/.venv
uv pip install --python .../laya-mlx/.venv/bin/python \
  -e /tmp/beastmode-local-repos-20260927/laya-mlx
.../laya-mlx/.venv/bin/python .../laya-mlx/preflight.py
```

The normal package import/load was attempted and recorded as unsupported on
this platform. Only pure-Python routing, language, preset, and email utility
contracts ran. No MLX substitute was installed and no Laya checkpoint or M3
latency measurement was attempted.
