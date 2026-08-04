"""Prompt accessors that execute the canonical shell prompt library."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .schema import schema_root


def prompt_library_path(path: Path | None = None) -> Path:
    """Locate scripts/lib/prompts.sh without copying its prompt strings."""
    if path is not None:
        return path.resolve()
    return schema_root().parent / "scripts" / "lib" / "prompts.sh"


def render_prompt(name: str, *args: str, script: Path | None = None) -> str:
    """Render one canonical prompt-shell function with positional arguments."""
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
