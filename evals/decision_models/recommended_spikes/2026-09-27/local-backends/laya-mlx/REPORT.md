# Laya-MLX bounded preflight

Source pin: `0a859518634112655cb97c745dbf04f5191aaf13`.

The isolated CPython 3.12.3 environment installed the package in editable mode
and resolved NumPy, tokenizers, huggingface-hub, and the other ordinary Python
dependencies. The project's MLX dependency is guarded by
`sys_platform == 'darwin' and platform_machine == 'arm64'`, so it was not
selected on this Linux x86_64 host.

The normal `import laya_mlx` load was attempted and failed with
`ModuleNotFoundError: No module named 'mlx'`. No MLX substitute, checkpoint
download, Agent construction, model inference, or Apple M3 latency measurement
was attempted. This is an honest platform/dependency blocker for the actual
Laya-MLX backend.

`preflight.py` bypasses the package initializer only to run pure-Python utility
contracts: temperature clamping/bucketing, script/language routing, aliases,
email state construction, and question presets. Those checks passed and are
reported as pure-Python checks; they do not establish Laya-MLX model support.
