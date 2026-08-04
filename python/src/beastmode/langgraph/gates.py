"""Interrupt-backed, fail-closed gate nodes."""

from __future__ import annotations

from typing import Any, Mapping

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from beastmode.core.provenance import check_provenance
from beastmode.core.observability import trace_metadata

from .context import BeastmodeContext


def _autonomy(runtime: Runtime[BeastmodeContext], state: Mapping[str, Any]) -> str:
    context = runtime.context
    return getattr(context, "autonomy", None) or str(state.get("autonomy", "medium"))


def gate_provenance(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    """Pause for approval below high, then run the canonical provenance gate."""
    decision = interrupt({"gate": "provenance", "phase": state.get("phase", "execute")}) if _autonomy(runtime, state) != "high" else "approved"
    target = state.get("run_dir")
    if target is None:
        return {
            "provenance_verdict": "unverifiable",
            "provenance_messages": ["no run_dir supplied; child provenance cannot be proven"],
            "gate_decision": decision,
            "provenance_retry_count": int(state.get("provenance_retry_count", 0)) + 1,
        }
    result = check_provenance(target, expect=state.get("expected_child_ids"))
    _stream(runtime, {"event": "provenance_gate", "verdict": result.verdict})
    trace = trace_metadata(
        {
            **dict(state),
            "goal_id": state.get("goal_id") or getattr(runtime.context, "goal_id", None),
            "phase": "provenance",
        },
        {"provenance_verdict": result.verdict},
        tags=() if result.verdict == "ok" else (result.verdict,),
    )
    return {
        "provenance_verdict": result.verdict,
        "provenance_messages": list(result.messages),
        "provenance_exit_code": result.exit_code,
        "gate_decision": decision,
        "provenance_retry_count": int(state.get("provenance_retry_count", 0)) + 1,
        "trace_records": [trace],
    }


def gate_merge(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> dict[str, Any]:
    """Pause for merge approval below high; no side effects precede the pause."""
    decision = interrupt({"gate": "merge", "phase": state.get("phase", "review")}) if _autonomy(runtime, state) != "high" else "approved"
    _stream(runtime, {"event": "merge_gate", "decision": decision})
    return {"merge_decision": decision}


provenance_gate = gate_provenance


def autonomy_gate(node):
    """Wrap any user node with Beastmode's below-high approval pause."""

    def wrapped(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]):
        decision = interrupt({"gate": "autonomy", "node": getattr(node, "__name__", "node")}) if _autonomy(runtime, state) != "high" else "approved"
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
        update = dict(node(state, runtime))
        update["phase_gate_decision"] = decision
        _stream(runtime, {"event": "phase", "phase": phase or update.get("phase")})
        return update

    wrapped.__name__ = f"phase_gate_{getattr(node, '__name__', 'node')}"
    return wrapped


def _stream(runtime: Runtime[BeastmodeContext], event: Mapping[str, Any]) -> None:
    """Emit custom progress without making stream delivery load-bearing."""
    try:
        runtime.stream_writer(dict(event))
    except Exception:
        pass
