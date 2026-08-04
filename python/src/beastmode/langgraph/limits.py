"""Boundaries for caller-controlled LangGraph work."""

from __future__ import annotations


MAX_CONCURRENCY = 32


def validate_concurrency(value: object) -> int:
    """Return a safe positive concurrency value or reject the request."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("concurrency must be a positive integer")
    if value > MAX_CONCURRENCY:
        raise ValueError(f"concurrency cannot exceed {MAX_CONCURRENCY}")
    return value
