"""Runtime-only configuration for Beastmode graphs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


Autonomy = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class BeastmodeContext:
    """Configuration that must not be merged into graph state."""

    autonomy: Autonomy = "medium"
    goal_id: str | None = None
    run_dir: Path | None = None
    max_provenance_retries: int = 1
    executor: Any = None
    reviewer: Any = None
    merger: Any = None
