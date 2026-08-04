from __future__ import annotations

import json
from pathlib import Path

from beastmode.core.seats import resolve_alias


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_alias_precedence_is_project_then_user_then_shipped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    _write(
        repo / ".beastmode" / "tier-aliases.json",
        {"demo": {"provider": "project", "model": "one", "tier": "economy", "family": "qwen"}},
    )
    _write(
        home / ".beastmode" / "tier-aliases.json",
        {"demo": {"provider": "user", "model": "two", "tier": "frontier", "family": "xai"}},
    )
    assert resolve_alias("demo", repo=repo, home=home).qualified == "project/one"


def test_concrete_provider_model_is_already_resolved(tmp_path: Path) -> None:
    seat = resolve_alias("minimax/MiniMax-M3", repo=tmp_path, home=tmp_path / "home")
    assert seat.qualified == "minimax/MiniMax-M3"
    assert seat.resolved is True
