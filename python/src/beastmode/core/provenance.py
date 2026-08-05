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
from typing import Any, Iterable, Mapping

from .schema import source_repository_root


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
    """Find the immutable gate bundled with the package or source checkout."""
    bundled = Path(__file__).resolve().parents[1] / "_vendor" / "acn_meta.py"
    source_root = source_repository_root()
    path = bundled if bundled.is_file() else (
        source_root / "scripts" / "lib" / "acn_meta.py"
        if source_root is not None
        else bundled
    )
    if repo is not None:
        requested = Path(repo).resolve()
        trusted = source_root.resolve() if source_root is not None else None
        if trusted is None or requested != trusted:
            raise ValueError("provenance implementation cannot be selected by a repository")
    if not path.is_file():
        raise ProvenanceModuleNotFoundError(
            "could not locate the package's trusted acn_meta.py: "
            f"{path}"
        )
    return path.resolve()


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
    attestations: Path | None = None,
    attestation_key: bytes | None = None,
    attestation_run_id: str | None = None,
) -> ProvenanceResult:
    """Run ``acn_meta.check`` and preserve its verdicts and exit code."""
    gate = _load_gate(repo)
    result = gate.check(
        Path(target),
        allow_empty=allow_empty,
        strict=strict,
        expect=list(expect) if expect is not None else None,
        attestations=Path(attestations) if attestations is not None else None,
        attestation_key=attestation_key,
        attestation_run_id=attestation_run_id,
    )
    return ProvenanceResult(
        rows=tuple(result.rows),
        messages=tuple(result.messages),
        exit_code=result.exit_code,
    )


def sign_attestation(record: Mapping[str, object], key: bytes) -> str:
    """Use the canonical gate framing to authenticate a provider record."""
    return str(_load_gate().sign_attestation(record, key))


def required_meta_fields(repo: Path | None = None) -> tuple[str, ...]:
    """Expose the canonical gate's schema-derived field reader for adapters."""
    return tuple(_load_gate(repo).required_meta_fields())
