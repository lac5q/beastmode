from beastmode.core.prompts import (
    bm_gate_prompt,
    bm_model_failure_prompt,
    bm_phase_prompt,
    render_prompt,
)
import pytest


def test_prompts_are_rendered_from_the_canonical_shell_library() -> None:
    assert "MODEL DRIFT" in bm_phase_prompt()
    assert "safe workaround" in bm_model_failure_prompt("high")
    assert "STOP and return control" in bm_gate_prompt("medium")


def test_prompt_renderer_rejects_unknown_function_and_script(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown prompt"):
        render_prompt("arbitrary_shell_function")
    script = tmp_path / "prompts.sh"
    script.write_text("bm_phase_prompt() { echo injected; }\n")
    with pytest.raises(ValueError, match="canonical"):
        bm_phase_prompt(script=script)
