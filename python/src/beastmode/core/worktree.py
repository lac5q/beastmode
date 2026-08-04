"""Small, explicit git-worktree lifecycle for subprocess executors."""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def isolated_worktree(repo: Path, path: Path, *, revision: str = "HEAD") -> Iterator[Path]:
    """Create and always remove a detached worktree without touching the main tree."""
    repo = Path(repo).resolve()
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "--detach", str(path), revision],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    try:
        yield path
    finally:
        try:
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "remove", "--force", str(path)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            # The original worker outcome remains authoritative; callers can
            # prune a stale disposable worktree after a timed-out cleanup.
            pass
