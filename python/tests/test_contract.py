from beastmode.core.contract import AcceptanceContract


def test_contract_normalizes_scalar_and_sequence_values() -> None:
    contract = AcceptanceContract.from_mapping(
        {
            "goal": "ship",
            "non_goals": "rewrite",
            "verification_commands": ["pytest", "bash tests/run-all.sh"],
        }
    )
    assert contract.goal == "ship"
    assert contract.non_goals == ("rewrite",)
    assert contract.verification_commands == ("pytest", "bash tests/run-all.sh")
    assert contract.to_mapping()["self_improvement_log_path"] == ".learnings/BEASTMODE.md"
