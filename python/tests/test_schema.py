from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from beastmode.core.schema import acn_contract, load_schema, required_meta_fields, schema_root


def _load_acn_meta():
    root = Path(__file__).parents[2]
    path = root / "scripts" / "lib" / "acn_meta.py"
    spec = importlib.util.spec_from_file_location("beastmode_acn_meta", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_root_finds_repository_source_of_truth() -> None:
    assert schema_root().name == "schema"
    assert schema_root().parent.name == "beastmode"


def test_required_meta_fields_match_the_existing_gate() -> None:
    expected = required_meta_fields()
    contract_fields = tuple(acn_contract()["meta_json_required_fields"])
    assert expected == contract_fields
    assert expected == _load_acn_meta().required_meta_fields()


def test_schema_name_cannot_escape_schema_root() -> None:
    with pytest.raises(ValueError, match="inside the schema"):
        load_schema("../scripts/tier-aliases")


def test_schema_root_rejects_caller_controlled_checkout(tmp_path: Path) -> None:
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "acn-contract.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="installed package"):
        schema_root(tmp_path)
