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


def _trusted_resource(path: Path, *, root: Path, directory: bool = False) -> Path:
    """Require build inputs to be regular, contained, non-symlink resources."""
    root = root.resolve(strict=True)
    candidate = Path(path).absolute()
    if not candidate.is_relative_to(root):
        raise RuntimeError(f"build resource escapes trusted root: {candidate}")
    current = root
    for part in candidate.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"build resource must not contain symlinks: {candidate}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise RuntimeError(f"build resource escapes trusted root: {candidate}")
    if directory:
        if not resolved.is_dir():
            raise RuntimeError(f"build resource directory is missing: {candidate}")
        for child in resolved.rglob("*"):
            if child.is_symlink():
                raise RuntimeError(f"build resource directory contains a symlink: {child}")
    elif not resolved.is_file() or resolved.is_symlink():
        raise RuntimeError(f"build resource must be a regular file: {candidate}")
    return candidate


def _validated_sources(
    sources: tuple[Path, Path, Path, Path], *, root: Path
) -> tuple[Path, Path, Path, Path]:
    return (
        _trusted_resource(sources[0], root=root, directory=True),
        _trusted_resource(sources[1], root=root),
        _trusted_resource(sources[2], root=root),
        _trusted_resource(sources[3], root=root),
    )


def _resource_sources() -> tuple[Path, Path, Path, Path]:
    """Return schema, provenance, and prompt sources in repo or sdist form."""
    vendored = (
        PROJECT / "schema",
        PROJECT / "vendor" / "acn_meta.py",
        PROJECT / "vendor" / "prompts.sh",
        PROJECT / "vendor" / "tier-aliases.json",
    )
    # An sdist carries immutable copies beside this setup.py.  Prefer those
    # whenever they exist: the directory containing an extracted sdist may be
    # attacker-controlled and must never substitute look-alike parent files.
    if all(path.is_dir() if index == 0 else path.is_file() for index, path in enumerate(vendored)):
        return _validated_sources(vendored, root=PROJECT)
    repository_schema = REPOSITORY / "schema"
    repository_files = (
        repository_schema / "acn-contract.json",
        REPOSITORY / "scripts" / "lib" / "acn_meta.py",
        REPOSITORY / "scripts" / "lib" / "prompts.sh",
        REPOSITORY / "scripts" / "tier-aliases.json",
    )
    if all(path.is_file() for path in repository_files):
        return _validated_sources((
            repository_schema,
            *repository_files[1:],
        ), root=REPOSITORY)
    raise RuntimeError(
        "cannot locate a complete trusted resource set; build from the source "
        "checkout or from the generated sdist"
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
