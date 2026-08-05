"""Small, explicit git-worktree lifecycle for subprocess executors."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_TRUSTED_GIT_PATH = os.pathsep.join(
    path
    for path in ("/usr/local/bin", "/usr/bin", "/bin", "/opt/homebrew/bin")
    if Path(path).is_dir()
)
_PARENT_GIT_CONTROLS = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "credential.helper=",
    "-c",
    "diff.external=",
)


def trusted_git_path() -> Path:
    """Resolve Git outside repository-controlled PATH entries."""
    candidate = shutil.which("git", path=_TRUSTED_GIT_PATH)
    if candidate is None:
        raise RuntimeError("a trusted system Git executable is required")
    resolved = Path(candidate).resolve(strict=True)
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise RuntimeError("trusted Git path must be an executable regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise RuntimeError("trusted Git must not be writable by another principal")
    return resolved


def parent_git_environment() -> dict[str, str]:
    """Return a minimal environment for privileged parent-side Git calls."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"LANG", "LC_ALL", "LC_CTYPE"} or key.startswith("LC_")
    }
    environment.update(
        {
            "PATH": _TRUSTED_GIT_PATH,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": os.devnull,
            "SSH_ASKPASS": os.devnull,
        }
    )
    return environment


def parent_git_command(repo: Path, *args: str) -> tuple[str, ...]:
    """Build a fixed-control parent Git command for an untrusted repository."""
    return (
        str(trusted_git_path()),
        *_PARENT_GIT_CONTROLS,
        "-C",
        str(Path(repo).resolve()),
        *args,
    )


@contextmanager
def isolated_worktree(repo: Path, path: Path, *, revision: str = "HEAD") -> Iterator[Path]:
    """Create and always remove a detached worktree without touching the main tree."""
    repo = Path(repo).resolve()
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        parent_git_command(repo, "worktree", "add", "--detach", str(path), revision),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=parent_git_environment(),
        timeout=30,
    )
    try:
        yield path
    finally:
        try:
            subprocess.run(
                parent_git_command(repo, "worktree", "remove", "--force", str(path)),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=parent_git_environment(),
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            # The original worker outcome remains authoritative; callers can
            # prune a stale disposable worktree after a timed-out cleanup.
            pass
