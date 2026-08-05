from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_sdist_resources_win_over_lookalike_parent(tmp_path: Path) -> None:
    parent = tmp_path / "attacker-parent"
    project = parent / "beastmode-sdist" / "python"
    vendor = project / "vendor"
    schema = project / "schema"
    vendor.mkdir(parents=True)
    schema.mkdir()
    (vendor / "acn_meta.py").write_text("trusted provenance\n", encoding="utf-8")
    (vendor / "prompts.sh").write_text("trusted prompts\n", encoding="utf-8")
    (vendor / "tier-aliases.json").write_text("{}\n", encoding="utf-8")
    (schema / "acn-contract.json").write_text("{}\n", encoding="utf-8")

    malicious_schema = project.parent / "schema"
    malicious_schema.mkdir()
    (malicious_schema / "acn-contract.json").write_text("malicious\n", encoding="utf-8")
    malicious_scripts = project.parent / "scripts" / "lib"
    malicious_scripts.mkdir(parents=True)
    (malicious_scripts / "acn_meta.py").write_text("malicious\n", encoding="utf-8")
    (malicious_scripts / "prompts.sh").write_text("malicious\n", encoding="utf-8")
    (project.parent / "scripts" / "tier-aliases.json").write_text("{}\n", encoding="utf-8")

    with patch("setuptools.setup"):
        namespace = runpy.run_path(str(ROOT / "python" / "setup.py"))
    resource_sources = namespace["_resource_sources"]
    resource_sources.__globals__["PROJECT"] = project
    resource_sources.__globals__["REPOSITORY"] = project.parent
    sources = resource_sources()
    assert sources == (
        schema,
        vendor / "acn_meta.py",
        vendor / "prompts.sh",
        vendor / "tier-aliases.json",
    )


def test_build_resources_reject_external_symlink(tmp_path: Path) -> None:
    project = tmp_path / "python"
    vendor = project / "vendor"
    schema = project / "schema"
    vendor.mkdir(parents=True)
    schema.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("sensitive sentinel\n", encoding="utf-8")
    (vendor / "acn_meta.py").symlink_to(outside)
    (vendor / "prompts.sh").write_text("safe\n", encoding="utf-8")
    (vendor / "tier-aliases.json").write_text("{}\n", encoding="utf-8")
    (schema / "acn-contract.json").write_text("{}\n", encoding="utf-8")

    with patch("setuptools.setup"):
        namespace = runpy.run_path(str(ROOT / "python" / "setup.py"))
    resource_sources = namespace["_resource_sources"]
    resource_sources.__globals__["PROJECT"] = project
    resource_sources.__globals__["REPOSITORY"] = project.parent
    with pytest.raises(RuntimeError, match="symlink"):
        resource_sources()
