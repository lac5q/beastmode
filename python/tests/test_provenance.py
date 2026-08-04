from __future__ import annotations

import subprocess
from pathlib import Path

from beastmode.core.provenance import check_provenance


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "acn-meta"


def _bash_verdict(directory: Path, *extra: str) -> tuple[int, str]:
    completed = subprocess.run(
        [str(ROOT / "scripts" / "enforce-models"), "--check-meta", str(directory), *extra],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout + completed.stderr


def test_python_gate_matches_bash_gate_for_every_fixture() -> None:
    expected = {
        "match": 0,
        "drift": 1,
        "legacy": 1,
        "empty": 1,
    }
    for name, exit_code in expected.items():
        directory = FIXTURES / name
        python_result = check_provenance(directory, repo=ROOT)
        bash_code, bash_output = _bash_verdict(directory)
        assert python_result.exit_code == bash_code == exit_code
        assert (python_result.verdict == "ok") is (exit_code == 0)
        if exit_code:
            assert python_result.messages
            assert "UNVERIFIABLE" in bash_output or "MODEL DRIFT" in bash_output


def test_python_gate_catches_missing_expected_child(tmp_path: Path) -> None:
    result = check_provenance(FIXTURES / "match", expect=["a", "ghost"], repo=ROOT)
    assert result.exit_code == 1
    assert result.verdict == "unverifiable"
    assert any("ghost" in message for message in result.messages)


def test_python_gate_does_not_turn_silent_provider_metadata_into_a_pass(tmp_path: Path) -> None:
    meta_dir = tmp_path / "run"
    meta_dir.mkdir()
    (meta_dir / "meta.json").write_text(
        '{"id":"silent","requested_model":"minimax/MiniMax-M3",'
        '"actual_model":null,"stop_reason":"end_turn","usage":{},'
        '"files_changed":[],"commands_run":[],"verify":{}}',
        encoding="utf-8",
    )
    result = check_provenance(meta_dir, repo=ROOT)
    assert result.exit_code == 1
    assert result.verdict == "unverifiable"
