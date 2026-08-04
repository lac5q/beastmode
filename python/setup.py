"""Build hooks that bundle the repository's canonical runtime resources.

The shell lane remains dependency-free and owns the checked-in source files.
Python wheels receive immutable copies at build time so installed packages do
not need (or trust) an arbitrary repository checkout.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist


PROJECT = Path(__file__).resolve().parent
REPOSITORY = PROJECT.parent


def _resource_sources() -> tuple[Path, Path, Path, Path]:
    """Return schema, provenance, and prompt sources in repo or sdist form."""
    repository_schema = REPOSITORY / "schema"
    if (repository_schema / "acn-contract.json").is_file():
        return (
            repository_schema,
            REPOSITORY / "scripts" / "lib" / "acn_meta.py",
            REPOSITORY / "scripts" / "lib" / "prompts.sh",
            REPOSITORY / "scripts" / "tier-aliases.json",
        )
    return (
        PROJECT / "schema",
        PROJECT / "vendor" / "acn_meta.py",
        PROJECT / "vendor" / "prompts.sh",
        PROJECT / "vendor" / "tier-aliases.json",
    )


class build_py(_build_py):
    """Copy canonical non-Python resources into the built package."""

    def run(self) -> None:
        super().run()
        schema_source, provenance_source, prompts_source, aliases_source = _resource_sources()
        package = Path(self.build_lib) / "beastmode"
        schema_destination = package / "schema"
        vendor_destination = package / "_vendor"
        schema_destination.mkdir(parents=True, exist_ok=True)
        vendor_destination.mkdir(parents=True, exist_ok=True)
        for source in sorted(schema_source.glob("*.json")):
            shutil.copy2(source, schema_destination / source.name)
        shutil.copy2(provenance_source, vendor_destination / "acn_meta.py")
        shutil.copy2(prompts_source, vendor_destination / "prompts.sh")
        shutil.copy2(aliases_source, vendor_destination / "tier-aliases.json")


class sdist(_sdist):
    """Place external canonical resources inside the source archive."""

    def make_release_tree(self, base_dir: str, files: list[str]) -> None:
        super().make_release_tree(base_dir, files)
        schema_source, provenance_source, prompts_source, aliases_source = _resource_sources()
        destination = Path(base_dir)
        shutil.copytree(schema_source, destination / "schema", dirs_exist_ok=True)
        vendor_destination = destination / "vendor"
        vendor_destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(provenance_source, vendor_destination / "acn_meta.py")
        shutil.copy2(prompts_source, vendor_destination / "prompts.sh")
        shutil.copy2(aliases_source, vendor_destination / "tier-aliases.json")


setup(cmdclass={"build_py": build_py, "sdist": sdist})
