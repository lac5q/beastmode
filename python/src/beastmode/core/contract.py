"""The framework-neutral acceptance contract used by every harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class AcceptanceContract:
    """A typed form of the universal Beastmode acceptance-contract template."""

    goal: str
    non_goals: tuple[str, ...] = field(default_factory=tuple)
    user_visible_acceptance: tuple[str, ...] = field(default_factory=tuple)
    files_likely_touched: tuple[str, ...] = field(default_factory=tuple)
    verification_commands: tuple[str, ...] = field(default_factory=tuple)
    manual_qa: tuple[str, ...] = field(default_factory=tuple)
    escalation_triggers: tuple[str, ...] = field(default_factory=tuple)
    self_improvement_log_path: str = ".learnings/BEASTMODE.md"

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "AcceptanceContract":
        """Build a contract from JSON/YAML-like values."""
        sequence_fields = (
            "non_goals",
            "user_visible_acceptance",
            "files_likely_touched",
            "verification_commands",
            "manual_qa",
            "escalation_triggers",
        )
        normalized = dict(values)
        for name in sequence_fields:
            value = normalized.get(name, ())
            if isinstance(value, str):
                value = (value,)
            normalized[name] = tuple(str(item) for item in value)
        return cls(**normalized)

    def to_mapping(self) -> dict[str, Any]:
        """Return a serializable mapping suitable for graph state."""
        return asdict(self)
