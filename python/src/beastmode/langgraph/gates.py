"""Interrupt-backed, fail-closed gate nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from beastmode.core.provenance import check_provenance
from beastmode.core.observability import redact_value, trace_metadata

from .context import BeastmodeContext
from .limits import MAX_TASKS


def _autonomy(runtime: Runtime[BeastmodeContext], state: Mapping[str, Any]) -> str:
    context = runtime.context
    value = getattr(context, "autonomy", None)
    return value if value in {"low", "medium", "high"} else "medium"


def _is_approved(decision: Any) -> bool:
    """Accept only the explicit approval values supported by the public API."""
    if decision is True or decision == "approved":
        return True
    return isinstance(decision, Mapping) and dict(decision) == {"approved": True}


def _require_approved(decision: Any, gate: str) -> None:
    if not _is_approved(decision):
        raise PermissionError(f"{gate} gate requires an explicit approved decision")


def gate_provenance(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    """Strict pipeline provenance gate with preflight/validation prerequisites."""
    decision = interrupt({"gate": "provenance", "phase": state.get("phase", "execute")}) if _autonomy(runtime, state) != "high" else "approved"
    _require_approved(decision, "provenance")
    return _run_provenance_gate(
        state,
        runtime,
        decision=decision,
        require_pipeline_prerequisites=True,
    )


def provenance_gate(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    """Composable provenance node; trusted target/expected ids live in context."""
    decision = interrupt({"gate": "provenance", "phase": state.get("phase", "execute")}) if _autonomy(runtime, state) != "high" else "approved"
    _require_approved(decision, "provenance")
    return _run_provenance_gate(
        state,
        runtime,
        decision=decision,
        require_pipeline_prerequisites=False,
    )


def _run_provenance_gate(
    state: Mapping[str, Any],
    runtime: Runtime[BeastmodeContext],
    *,
    decision: Any,
    require_pipeline_prerequisites: bool,
) -> dict[str, Any]:
    if require_pipeline_prerequisites:
        if state.get("preflight_ok") is not True:
            raise PermissionError("provenance gate requires a successful preflight")
        validation = state.get("validation_report")
        if not isinstance(validation, Mapping) or validation.get("passed") is not True:
            raise PermissionError("provenance gate requires successful mechanical validation")
    target = getattr(runtime.context, "run_dir", None)
    if target is None:
        return {
            "provenance_verdict": "unverifiable",
            "provenance_messages": ["no run_dir supplied; child provenance cannot be proven"],
            "gate_decision": decision,
            "provenance_retry_count": int(state.get("provenance_retry_count", 0)) + 1,
        }
    context_expected = getattr(runtime.context, "expected_child_ids", None)
    if context_expected is not None:
        expected = [str(item) for item in context_expected]
    elif require_pipeline_prerequisites:
        pipeline_expected = state.get("expected_child_ids")
        expected = (
            [str(item) for item in pipeline_expected]
            if isinstance(pipeline_expected, list)
            else []
        )
    else:
        expected = []
    if (
        not expected
        or len(expected) > MAX_TASKS
        or any(not item or len(item) > 128 for item in expected)
    ):
        return {
            "provenance_verdict": "unverifiable",
            "provenance_messages": ["trusted expected child ids are missing or out of bounds"],
            "gate_decision": decision,
            "provenance_retry_count": int(state.get("provenance_retry_count", 0)) + 1,
        }
    target_path = Path(target).resolve()
    attestations = getattr(runtime.context, "attestations", None)
    attestation_path = (
        Path(attestations).expanduser().absolute()
        if attestations is not None
        else None
    )
    if attestation_path is not None and (
        attestation_path == target_path or target_path in attestation_path.parents
    ):
        return {
            "provenance_verdict": "unverifiable",
            "provenance_messages": [
                "attestations must be outside the worker-writable run_dir"
            ],
            "provenance_exit_code": 1,
            "gate_decision": decision,
            "provenance_retry_count": int(
                state.get("provenance_retry_count", 0)
            )
            + 1,
        }
    result = check_provenance(
        target_path,
        expect=expected,
        attestations=attestation_path,
        attestation_key=getattr(runtime.context, "attestation_key", None),
        attestation_run_id=getattr(runtime.context, "attestation_run_id", None),
    )
    _stream(runtime, {"event": "provenance_gate", "verdict": result.verdict})
    trace = trace_metadata(
        {
            "goal_id": state.get("goal_id") or getattr(runtime.context, "goal_id", None),
            "phase": "provenance",
            "autonomy": _autonomy(runtime, state),
            "executor_model": state.get("executor_model"),
        },
        {"provenance_verdict": result.verdict},
        tags=() if result.verdict == "ok" else (result.verdict,),
    )
    return {
        "provenance_verdict": result.verdict,
        "provenance_messages": [redact_value(message) for message in result.messages],
        "provenance_exit_code": result.exit_code,
        "gate_decision": decision,
        "provenance_retry_count": int(state.get("provenance_retry_count", 0)) + 1,
        "trace_records": [trace],
    }


def gate_merge(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    """Pause for merge approval below high; no side effects precede the pause."""
    decision = interrupt({"gate": "merge", "phase": state.get("phase", "review")}) if _autonomy(runtime, state) != "high" else "approved"
    _require_approved(decision, "merge")
    report = state.get("review_report")
    if not isinstance(report, Mapping) or report.get("approved") is not True:
        raise PermissionError("merge gate requires explicit reviewer approval")
    _stream(runtime, {"event": "merge_gate", "decision": decision})
    return {"merge_decision": decision}


def autonomy_gate(node):
    """Wrap any user node with Beastmode's below-high approval pause."""

    def wrapped(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]):
        decision = interrupt({"gate": "autonomy", "node": getattr(node, "__name__", "node")}) if _autonomy(runtime, state) != "high" else "approved"
        _require_approved(decision, "autonomy")
        update = dict(node(state, runtime))
        update["gate_decision"] = decision
        return update

    wrapped.__name__ = f"autonomy_gate_{getattr(node, '__name__', 'node')}"
    return wrapped


def phase_gate(node, *, phase: str | None = None):
    """Pause at every phase boundary for low-autonomy runs.

    The interrupt is deliberately the first executable statement in the
    wrapper.  LangGraph may replay the wrapper when a command resumes; the
    wrapped node therefore runs only after the operator has approved that
    phase, and a replay cannot duplicate work performed before the gate.
    Medium autonomy keeps the two load-bearing provenance/merge gates, while
    high autonomy remains non-interactive.
    """

    def wrapped(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]):
        decision = interrupt({"gate": "phase", "phase": phase or getattr(node, "__name__", "node")}) if _autonomy(runtime, state) == "low" else "approved"
        _require_approved(decision, "phase")
        update = dict(node(state, runtime))
        update["phase_gate_decision"] = decision
        _stream(runtime, {"event": "phase", "phase": phase or update.get("phase")})
        return update

    wrapped.__name__ = f"phase_gate_{getattr(node, '__name__', 'node')}"
    return wrapped


def _stream(runtime: Runtime[BeastmodeContext], event: Mapping[str, Any]) -> None:
    """Emit custom progress without making stream delivery load-bearing."""
    try:
        runtime.stream_writer(redact_value(dict(event)))
    except Exception:
        pass
