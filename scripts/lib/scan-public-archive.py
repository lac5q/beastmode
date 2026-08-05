#!/usr/bin/env python3
"""Bounded, path-safe scanner for generated wheel and sdist archives."""

from __future__ import annotations

import re
import stat
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


MAX_MEMBERS = 20_000
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
CREDENTIAL = re.compile(
    rb"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    rb"gh[pousr]_[A-Za-z0-9_]{20,}|github_[p]at_[A-Za-z0-9_]{20,}|"
    rb"sk-[A-Za-z0-9]{20,}|sk-[p]roj-[A-Za-z0-9_-]{16,}|"
    rb"sk-[a]nt-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{20,}|"
    rb"pass(?:word|wd)\s*[:=]\s*[^\s\"]{8,}"
)
PRIVATE_PATH = re.compile(
    rb"/(?:h[o]me|U[s]ers)/[A-Za-z0-9_.-]+|C:[\\/]+U[s]ers[\\/]+[A-Za-z0-9_.-]+"
)
BLOCKED_PATH = re.compile(
    r"(?:^|/)(?:\.env(?:$|\.)|.*\.(?:pem|key|p12|pfx|sqlite|sqlite3)$|auth\.json$|credentials\.json$)"
)


def _safe_name(raw: str) -> str:
    if "\x00" in raw or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ValueError("archive member name contains control bytes")
    path = PurePosixPath(raw.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("archive member escapes its root")
    name = str(path)
    if BLOCKED_PATH.search(name):
        raise PermissionError("credential-like archive member name found")
    return name


def _scan_bytes(data: bytes) -> None:
    if CREDENTIAL.search(data) or PRIVATE_PATH.search(data):
        raise PermissionError("sensitive material found in generated artifact")


def _scan_zip(path: Path) -> None:
    total = 0
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise ValueError("archive member count exceeds safety bound")
        for member in members:
            _safe_name(member.filename)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("archive symlinks are not allowed")
            if member.file_size > MAX_MEMBER_BYTES:
                raise ValueError("archive member exceeds safety bound")
            total += member.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("archive expanded size exceeds safety bound")
            if not member.is_dir():
                with archive.open(member) as stream:
                    _scan_bytes(stream.read(MAX_MEMBER_BYTES + 1))


def _scan_tar(path: Path) -> None:
    total = 0
    with tarfile.open(path, "r:*") as archive:
        for count, member in enumerate(archive, start=1):
            if count > MAX_MEMBERS:
                raise ValueError("archive member count exceeds safety bound")
            _safe_name(member.name)
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError("archive links and devices are not allowed")
            if member.size > MAX_MEMBER_BYTES:
                raise ValueError("archive member exceeds safety bound")
            total += member.size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("archive expanded size exceeds safety bound")
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("archive member cannot be read")
                _scan_bytes(stream.read(MAX_MEMBER_BYTES + 1))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: scan-public-archive.py <wheel-or-sdist>", file=sys.stderr)
        return 2
    path = Path(argv[0])
    if path.is_symlink() or not path.is_file():
        print("public-artifact-guard: artifact must be a regular non-symlink file", file=sys.stderr)
        return 2
    try:
        if zipfile.is_zipfile(path):
            _scan_zip(path)
        elif tarfile.is_tarfile(path):
            _scan_tar(path)
        else:
            raise ValueError("unsupported distribution archive format")
    except PermissionError as exc:
        print(f"public-artifact-guard: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"public-artifact-guard: archive scan failed: {exc}", file=sys.stderr)
        return 2
    print(f"public artifact archive: clean ({path.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
