from beastmode.core.prompts import (
    bm_gate_prompt,
    bm_model_failure_prompt,
    bm_phase_prompt,
)


def test_prompts_are_rendered_from_the_canonical_shell_library() -> None:
    assert "MODEL DRIFT" in bm_phase_prompt()
    assert "safe workaround" in bm_model_failure_prompt("high")
    assert "STOP and return control" in bm_gate_prompt("medium")
