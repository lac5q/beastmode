"""Schema-first access to the repository's machine-readable vocabulary."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class SchemaNotFoundError(FileNotFoundError):
    """Raised when the repository schema cannot be found."""


def _schema_candidates(start: Path | None) -> list[Path]:
    anchor = (start or Path(__file__)).resolve()
    if anchor.is_file():
        anchor = anchor.parent
    candidates: list[Path] = []
    configured = os.environ.get("BEASTMODE_SCHEMA_ROOT")
    if configured:
        configured_path = Path(configured).expanduser().resolve()
        candidates.append(
            configured_path
            if configured_path.name == "schema"
            else configured_path / "schema"
        )
    for parent in (anchor, *anchor.parents):
        candidates.append(parent if parent.name == "schema" else parent / "schema")
    return candidates


def schema_root(start: Path | None = None) -> Path:
    """Return the nearest directory containing the repository JSON schemas."""
    for candidate in _schema_candidates(start):
        if (candidate / "acn-contract.json").is_file():
            return candidate
    searched = ", ".join(str(path) for path in _schema_candidates(start))
    raise SchemaNotFoundError(
        "could not locate schema/acn-contract.json; searched: " + searched
    )


def load_schema(name: str, root: Path | None = None) -> dict[str, Any]:
    """Load one schema JSON object without duplicating its fields in Python."""
    filename = name if name.endswith(".json") else f"{name}.json"
    path = schema_root(root) / filename
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid schema JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"schema must be a JSON object: {path}")
    return value


def acn_contract(root: Path | None = None) -> dict[str, Any]:
    """Return the ACN contract from schema/acn-contract.json."""
    return load_schema("acn-contract", root)


def required_meta_fields(root: Path | None = None) -> tuple[str, ...]:
    """Return the canonical child meta fields directly from the schema."""
    fields = acn_contract(root).get("meta_json_required_fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError("acn-contract.json has no meta_json_required_fields list")
    return tuple(str(field) for field in fields)


def _required_fields(name: str, key: str, root: Path | None = None) -> tuple[str, ...]:
    """Read one required-field list from the canonical ACN schema."""
    fields = acn_contract(root).get(key)
    if not isinstance(fields, list) or not fields:
        raise ValueError(f"acn-contract.json has no {key} list")
    return tuple(str(field) for field in fields)


def required_batch_fields(root: Path | None = None) -> tuple[str, ...]:
    """Return the required ACN batch keys without copying the schema."""
    return _required_fields("batch", "batch_required_fields", root)


def required_task_fields(root: Path | None = None) -> tuple[str, ...]:
    """Return the required ACN task keys without copying the schema."""
    return _required_fields("task", "task_required_fields", root)


def concurrency_default(root: Path | None = None) -> int:
    """Return the schema-declared default ACN concurrency."""
    value = acn_contract(root).get("concurrency_default")
    if not isinstance(value, int) or value < 1:
        raise ValueError("acn-contract.json has no positive concurrency_default")
    return value
