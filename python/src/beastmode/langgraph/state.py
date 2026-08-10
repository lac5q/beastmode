"""Typed state vocabulary for the optional LangGraph binding."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from beastmode.core.schema import required_meta_fields


CHILD_META_FIELDS = required_meta_fields()
BEASTMODE_STATE_KEY_PREFIX = "beastmode_"

# TypedDict's functional form lets the schema remain the source of truth.  A
# provider may legitimately leave ``actual_model`` empty; the canonical gate
# then returns ``unverifiable`` rather than treating an unknown value as a pass.
ChildMeta = TypedDict(
    "ChildMeta",
    {field: Any for field in CHILD_META_FIELDS},
    total=True,
)


class BeastmodeState(TypedDict, total=False):
    """State keys reserved by the Beastmode graph binding.

    ``child_meta`` uses list concatenation so Send-style fan-out results are
    accumulated rather than overwritten.  Foreign graphs may add unrelated
    keys freely; the binding only reads/writes these names.
    """

    goal: str
    goal_id: str
    repo: str
    autonomy: str
    batch: dict[str, Any]
    director_model: str
    executor_model: str
    watcher_model: str
    requested_seats: dict[str, Any]
    concurrency: int
    phase: str
    acceptance_contract: dict[str, Any]
    preflight_report: dict[str, Any]
    preflight_ok: bool
    challenge_report: dict[str, Any]
    child_meta: Annotated[list[ChildMeta], operator.add]
    trace_records: Annotated[list[dict[str, Any]], operator.add]
    provenance_verdict: str
    phase_report: dict[str, Any]
    validation_report: dict[str, Any]
    gate_decision: str
    phase_gate_decision: str
    retry_count: int
    run_dir: str
    tasks: list[dict[str, Any]]
    expected_child_ids: list[str]
    provenance_messages: list[str]
    provenance_exit_code: int
    provenance_retry_count: int
    execution_status: str
    review_report: dict[str, Any]
    merge_decision: Any
    merge_report: dict[str, Any]
    status: str
    self_improvement: str
    lane_batches: list[list[dict[str, Any]]]
    lane_index: int
    task: dict[str, Any]
    task_results: Annotated[list[dict[str, Any]], operator.add]
    learning_report: dict[str, Any]
    learning_resolutions: dict[str, str]
