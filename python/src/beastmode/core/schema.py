"""Schema-first access to the repository's machine-readable vocabulary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SchemaNotFoundError(FileNotFoundError):
    """Raised when the repository schema cannot be found."""


def source_repository_root() -> Path | None:
    """Return the trusted source checkout containing this installed module."""
    path = Path(__file__).resolve()
    if len(path.parents) < 5:
        return None
    candidate = path.parents[4]
    if (
        (candidate / "python" / "pyproject.toml").is_file()
        and (candidate / "schema" / "acn-contract.json").is_file()
    ):
        return candidate
    return None


def _schema_candidates() -> tuple[Path, ...]:
    package_schema = Path(__file__).resolve().parents[1] / "schema"
    source_root = source_repository_root()
    if source_root is None:
        return (package_schema,)
    return (package_schema, source_root / "schema")


def schema_root(start: Path | None = None) -> Path:
    """Return the immutable package or source-checkout schema directory.

    ``start`` remains accepted for API compatibility, but may only identify
    one of those trusted locations. It can no longer redirect security policy
    through an arbitrary checkout or environment variable.
    """
    candidates = _schema_candidates()
    if start is not None:
        requested = Path(start).expanduser().resolve()
        if requested.name != "schema":
            requested = requested / "schema"
        if requested not in candidates:
            raise ValueError("schema root must be the installed package or its source checkout")
        candidates = (requested,)
    for candidate in candidates:
        if (candidate / "acn-contract.json").is_file():
            return candidate
    searched = ", ".join(str(path) for path in candidates)
    raise SchemaNotFoundError(
        "could not locate schema/acn-contract.json; searched: " + searched
    )


def load_schema(name: str, root: Path | None = None) -> dict[str, Any]:
    """Load one schema JSON object without duplicating its fields in Python."""
    filename = name if name.endswith(".json") else f"{name}.json"
    root_path = schema_root(root).resolve()
    path = (root_path / filename).resolve()
    try:
        path.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("schema name must remain inside the schema directory") from exc
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
