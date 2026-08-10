from __future__ import annotations

from pathlib import Path

import pytest

from beastmode.core.learning import record_learning


def _blocked_state(root: Path, *, run_name: str = "run-1") -> dict[str, object]:
    return {
        "goal_id": "learning-goal",
        "goal": "exercise the learning loop",
        "repo": str(root),
        "run_dir": str(root / run_name),
        "phase": "blocked",
        "status": "blocked",
        "preflight_ok": False,
        "preflight_report": {"token": "secret-value", "available": False},
    }


def test_records_redacted_issue_and_next_action(tmp_path: Path) -> None:
    report = record_learning(_blocked_state(tmp_path), repo=tmp_path)

    assert report["recorded"] is True
    assert report["result"] == "blocked"
    assert report["issue_count"] == 1
    assert report["issues"][0]["status"] == "open"
    log = (tmp_path / ".learnings" / "BEASTMODE.md").read_text(encoding="utf-8")
    assert "Fix the preflight report" in log
    assert "secret-value" not in log
    assert "[REDACTED]" in log


def test_replay_is_idempotent_and_repeated_issue_is_promoted(tmp_path: Path) -> None:
    first = record_learning(_blocked_state(tmp_path), repo=tmp_path)
    replay = record_learning(_blocked_state(tmp_path), repo=tmp_path)
    recurring = record_learning(
        _blocked_state(tmp_path, run_name="run-2"), repo=tmp_path
    )

    assert first["duplicate"] is False
    assert replay["duplicate"] is True
    assert recurring["issues"][0]["status"] == "recurring"
    assert recurring["promotions"][0]["issue_id"] == recurring["issues"][0]["id"]
    assert (
        (tmp_path / ".learnings" / "BEASTMODE.md").read_text(encoding="utf-8").count("<!-- beastmode-learning:")
        == 2
    )


def test_clean_same_goal_marks_prior_issue_addressed(tmp_path: Path) -> None:
    record_learning(_blocked_state(tmp_path), repo=tmp_path)
    clean = record_learning(
        {
            "goal_id": "learning-goal",
            "goal": "exercise the learning loop",
            "repo": str(tmp_path),
            "run_dir": str(tmp_path / "run-fixed"),
            "phase": "merge",
            "status": "ready_to_merge",
            "preflight_ok": True,
            "validation_report": {"passed": True, "failures": []},
            "provenance_verdict": "ok",
        },
        repo=tmp_path,
    )

    assert clean["result"] == "pass"
    assert clean["addressed"][0]["status"] == "addressed"


def test_learning_path_cannot_escape_repository(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside the repository"):
        record_learning(
            {
                **_blocked_state(tmp_path),
                "acceptance_contract": {
                    "self_improvement_log_path": "../outside.md"
                },
            },
            repo=tmp_path,
        )
