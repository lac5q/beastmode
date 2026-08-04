"""The terminating Beastmode loop as a checkpointable LangGraph DAG."""

from __future__ import annotations

from typing import Any, Mapping

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import RetryPolicy

from ..context import BeastmodeContext
from ..gates import _is_approved, gate_merge, gate_provenance, phase_gate
from ..dispatch import first_lane_sends, next_lane_sends
from ..nodes import PipelineDependencies, blocked, challenge, contract, design, dispatch, dispatch_next, execute, merge, preflight, review, self_improve, validate_mechanical
from ..state import BeastmodeState


def _provenance_route(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> str:
    if _is_approved(state.get("gate_decision")) and state.get("provenance_verdict") == "ok":
        return "review"
    retries = int(state.get("provenance_retry_count", 0))
    limit = int(getattr(runtime.context, "max_provenance_retries", 1))
    return "dispatch" if retries <= limit else "blocked"


def _merge_route(state: Mapping[str, Any], runtime: Runtime[BeastmodeContext]) -> str:
    decision = state.get("merge_decision")
    return "merge" if _is_approved(decision) else "design"


def build_pipeline(
    *,
    dependencies: PipelineDependencies | None = None,
    overrides: Mapping[str, Any] | None = None,
    checkpointer: Any = None,
    state_schema: type = BeastmodeState,
):
    """Compile the pipeline; ``overrides`` replaces non-gate nodes only."""
    dependencies = dependencies or PipelineDependencies()
    overrides = dict(overrides or {})
    protected = {"gate_provenance", "gate_merge"}
    illegal = protected.intersection(overrides)
    if illegal:
        raise ValueError("load-bearing gate nodes cannot be overridden: " + ", ".join(sorted(illegal)))

    graph = StateGraph(state_schema, context_schema=BeastmodeContext)
    nodes = {
        "preflight": lambda state, runtime: preflight(state, runtime),
        "contract": lambda state, runtime: contract(state, runtime),
        "design": lambda state, runtime: design(state, runtime),
        "challenge": lambda state, runtime: challenge(state, runtime, dependencies),
        "dispatch": lambda state, runtime: dispatch(state, runtime),
        "dispatch_next": lambda state, runtime: dispatch_next(state, runtime),
        "execute": lambda state, runtime: execute(state, runtime, dependencies),
        "validate_mechanical": lambda state, runtime: validate_mechanical(state, runtime),
        "gate_provenance": gate_provenance,
        "review": lambda state, runtime: review(state, runtime, dependencies),
        "gate_merge": gate_merge,
        "merge": lambda state, runtime: merge(state, runtime, dependencies),
        "self_improve": self_improve,
        "blocked": blocked,
    }
    nodes.update({name: value for name, value in overrides.items() if name not in protected})
    graph.set_node_defaults(retry_policy=RetryPolicy(max_attempts=2, jitter=False))
    phase_nodes = {
        "preflight",
        "contract",
        "design",
        "challenge",
        "dispatch",
        "dispatch_next",
        "validate_mechanical",
        "review",
        "merge",
        "self_improve",
    }
    for name, action in nodes.items():
        if name in phase_nodes:
            action = phase_gate(action, phase=name)
        graph.add_node(
            name,
            action,
            defer=name == "validate_mechanical",
            retry_policy=RetryPolicy(max_attempts=1, jitter=False)
            if name in {"gate_provenance", "gate_merge"}
            else None,
        )

    graph.add_edge(START, "preflight")
    graph.add_edge("preflight", "contract")
    graph.add_edge("contract", "design")
    graph.add_edge("design", "challenge")
    graph.add_edge("challenge", "dispatch")
    graph.add_conditional_edges(
        "dispatch",
        first_lane_sends,
        {"validate_mechanical": "validate_mechanical"},
    )
    graph.add_edge("execute", "dispatch_next")
    graph.add_conditional_edges(
        "dispatch_next",
        next_lane_sends,
        {"validate_mechanical": "validate_mechanical"},
    )
    graph.add_edge("validate_mechanical", "gate_provenance")
    graph.add_conditional_edges(
        "gate_provenance",
        _provenance_route,
        {"review": "review", "dispatch": "dispatch", "blocked": "blocked"},
    )
    graph.add_edge("review", "gate_merge")
    graph.add_conditional_edges("gate_merge", _merge_route, {"merge": "merge", "design": "design"})
    graph.add_edge("merge", "self_improve")
    graph.add_edge("self_improve", END)
    graph.add_edge("blocked", END)
    return graph.compile(checkpointer=checkpointer, name="beastmode-pipeline")
