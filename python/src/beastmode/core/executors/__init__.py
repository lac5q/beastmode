"""Subprocess executor adapters; they are intentionally outside ``core`` logic."""

from .subprocess import SubprocessExecutor, SubprocessResult, WorktreeSubprocessExecutor

__all__ = ["SubprocessExecutor", "SubprocessResult", "WorktreeSubprocessExecutor"]
