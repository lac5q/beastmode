"""Prompt accessors that execute the canonical shell prompt library."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .schema import source_repository_root


_ALLOWED_PROMPTS = frozenset(
    {"bm_phase_prompt", "bm_model_failure_prompt", "bm_gate_prompt"}
)


def prompt_library_path(path: Path | None = None) -> Path:
    """Locate the immutable bundled or source-checkout prompt library."""
    bundled = Path(__file__).resolve().parents[1] / "_vendor" / "prompts.sh"
    source_root = source_repository_root()
    canonical = bundled if bundled.is_file() else (
        source_root / "scripts" / "lib" / "prompts.sh"
        if source_root is not None
        else bundled
    )
    if path is not None and path.resolve() != canonical.resolve():
        raise ValueError("prompt script must be the package's trusted canonical library")
    if not canonical.is_file():
        raise FileNotFoundError(f"could not locate bundled prompt library: {canonical}")
    return canonical.resolve()


def render_prompt(name: str, *args: str, script: Path | None = None) -> str:
    """Render one canonical prompt-shell function with positional arguments."""
    if name not in _ALLOWED_PROMPTS:
        raise ValueError(f"unknown prompt name: {name}")
    script_path = prompt_library_path(script)
    command = 'set -e; source "$1"; shift; "$@"'
    completed = subprocess.run(
        ["bash", "-c", command, "beastmode-prompts", str(script_path), name, *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def bm_phase_prompt(*, script: Path | None = None) -> str:
    return render_prompt("bm_phase_prompt", script=script)


def bm_model_failure_prompt(autonomy: str = "medium", *, script: Path | None = None) -> str:
    return render_prompt("bm_model_failure_prompt", autonomy, script=script)


def bm_gate_prompt(autonomy: str = "medium", *, script: Path | None = None) -> str:
    return render_prompt("bm_gate_prompt", autonomy, script=script)
