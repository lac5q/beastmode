"""The Python entry point for the repository's canonical provenance gate.

There is deliberately no verdict logic in this module.  The shell lane and
the LangGraph lane both call ``scripts/lib/acn_meta.py``; this adapter only
loads that module and translates its result into a small, stable Python
surface.  Keeping the import dynamic also means the framework-neutral core
does not grow a second copy of the gate.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

from .schema import schema_root


class ProvenanceModuleNotFoundError(FileNotFoundError):
    """Raised when the canonical ``acn_meta.py`` cannot be located."""


@dataclass(frozen=True)
class ProvenanceResult:
    """A serializable view over the canonical gate's result object."""

    rows: tuple[Any, ...]
    messages: tuple[str, ...]
    exit_code: int

    @property
    def verdict(self) -> str:
        """Return the aggregate verdict without reclassifying any row."""
        statuses = {getattr(row, "status", None) for row in self.rows}
        if "drift" in statuses:
            return "drift"
        if "unverifiable" in statuses or self.exit_code != 0:
            return "unverifiable"
        return "ok"


def canonical_gate_path(repo: Path | None = None) -> Path:
    """Find the one gate implementation shipped with the repository."""
    path = schema_root(repo).parent / "scripts" / "lib" / "acn_meta.py"
    if not path.is_file():
        raise ProvenanceModuleNotFoundError(
            "could not locate scripts/lib/acn_meta.py next to the schema: "
            f"{path}"
        )
    return path


def _load_gate(repo: Path | None = None) -> ModuleType:
    path = canonical_gate_path(repo)
    spec = importlib.util.spec_from_file_location("beastmode_canonical_acn_meta", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load canonical gate module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_provenance(
    target: Path,
    *,
    allow_empty: bool = False,
    strict: bool = False,
    expect: Iterable[str] | None = None,
    repo: Path | None = None,
) -> ProvenanceResult:
    """Run ``acn_meta.check`` and preserve its verdicts and exit code."""
    gate = _load_gate(repo)
    result = gate.check(
        Path(target),
        allow_empty=allow_empty,
        strict=strict,
        expect=list(expect) if expect is not None else None,
    )
    return ProvenanceResult(
        rows=tuple(result.rows),
        messages=tuple(result.messages),
        exit_code=result.exit_code,
    )


def required_meta_fields(repo: Path | None = None) -> tuple[str, ...]:
    """Expose the canonical gate's schema-derived field reader for adapters."""
    return tuple(_load_gate(repo).required_meta_fields())
