from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from beastmode.langgraph import BeastmodeContext, BeastmodeState, autonomy_gate, provenance_gate
import beastmode.langgraph.gates as gates_module
from beastmode.langgraph.graphs.pipeline import build_pipeline
from beastmode.langgraph.nodes import PipelineDependencies


ROOT = Path(__file__).resolve().parents[2]
MATCH_RUN = ROOT / "tests" / "fixtures" / "acn-meta" / "match"
OK_DEPENDENCIES = PipelineDependencies(
    executor=lambda state: {"execution_status": "ok"},
    validator=lambda state: {"validation_report": {"passed": True}},
    reviewer=lambda state: {"review_report": {"approved": True}},
)


@pytest.fixture(autouse=True)
def _trusted_provenance_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep graph-composition tests independent of provider evidence fixtures."""
    monkeypatch.setattr(
        gates_module,
        "check_provenance",
        lambda target, expect, attestations=None: SimpleNamespace(
            verdict="ok", messages=(), exit_code=0
        ),
    )


class ForeignState(TypedDict, total=False):
    user_note: str
    run_dir: str
    expected_child_ids: list[str]
    provenance_verdict: str
    gate_decision: str
    user_value: str


class ParentState(BeastmodeState, total=False):
    user_note: str


def test_foreign_graph_can_drop_in_provenance_and_autonomy_nodes() -> None:
    graph = StateGraph(ForeignState, context_schema=BeastmodeContext)

    def user_node(state, runtime):
        return {"user_value": "kept"}

    graph.add_node("user", autonomy_gate(user_node))
    graph.add_node("provenance", provenance_gate)
    graph.add_edge(START, "user")
    graph.add_edge("user", "provenance")
    graph.add_edge("provenance", END)
    compiled = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "foreign"}}
    first = compiled.invoke(
        {"user_note": "untouched", "run_dir": str(MATCH_RUN), "expected_child_ids": ["a"]},
        config=config,
        context=BeastmodeContext(autonomy="medium", run_dir=MATCH_RUN, expected_child_ids=("a",)),
    )
    assert "__interrupt__" in first
    context = BeastmodeContext(autonomy="medium", run_dir=MATCH_RUN, expected_child_ids=("a",))
    second = compiled.invoke(Command(resume="approved"), config=config, context=context)
    assert "__interrupt__" in second
    done = compiled.invoke(Command(resume="approved"), config=config, context=context)
    assert done["user_note"] == "untouched"
    assert done["user_value"] == "kept"
    assert done["provenance_verdict"] == "ok"


def test_pipeline_accepts_a_foreign_state_schema() -> None:
    # A user's unrelated key stays in the state when the pipeline is built
    # over their schema instead of forcing a replacement state object.
    class CombinedState(ForeignState):
        goal: str
        acceptance_contract: dict
        phase: str
        tasks: list[dict]
        lane_batches: list[list[dict]]
        lane_index: int
        expected_child_ids: list[str]
        run_dir: str
        provenance_retry_count: int
        provenance_messages: list[str]
        provenance_exit_code: int
        merge_decision: object
        status: str
        review_report: dict
        validation_report: dict
        self_improvement: str
        preflight_ok: bool
        provenance_verdict: str
        task_results: list[dict]

    graph = build_pipeline(
        dependencies=OK_DEPENDENCIES,
        state_schema=CombinedState,
        checkpointer=InMemorySaver(),
    )
    result = graph.invoke(
        {
            "goal": "foreign-state",
            "user_note": "preserve me",
            "run_dir": str(MATCH_RUN),
            "tasks": [{"id": "a", "goal": "foreign-state", "allowed_paths": [], "verify_cmds": []}],
        },
        config={"configurable": {"thread_id": "foreign-state"}},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert result["user_note"] == "preserve me"
    assert result["status"] == "ready_to_merge"


def test_pipeline_subgraph_uses_parent_checkpointer_and_preserves_parent_state() -> None:
    subgraph = build_pipeline(dependencies=OK_DEPENDENCIES, state_schema=ParentState)
    parent = StateGraph(ParentState, context_schema=BeastmodeContext)

    def before(state):
        return {"user_note": state.get("user_note", "") + "|before"}

    def after(state):
        return {"user_note": state.get("user_note", "") + "|after"}

    parent.add_node("before", before)
    parent.add_node("beastmode", subgraph)
    parent.add_node("after", after)
    parent.add_edge(START, "before")
    parent.add_edge("before", "beastmode")
    parent.add_edge("beastmode", "after")
    parent.add_edge("after", END)
    compiled = parent.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "subgraph-parent"}}
    initial = {
        "goal": "embedded",
        "user_note": "start",
        "run_dir": str(MATCH_RUN),
        "tasks": [{"id": "a", "goal": "embedded", "allowed_paths": [], "verify_cmds": []}],
    }
    context = BeastmodeContext(autonomy="medium", run_dir=MATCH_RUN)
    paused = compiled.invoke(initial, config=config, context=context)
    assert "__interrupt__" in paused
    paused_again = compiled.invoke(Command(resume="approved"), config=config, context=context)
    assert "__interrupt__" in paused_again
    result = compiled.invoke(Command(resume="approved"), config=config, context=context)
    assert result["status"] == "ready_to_merge"
    assert result["user_note"] == "start|before|after"


def test_standalone_provenance_requires_context_bound_expected_ids() -> None:
    graph = StateGraph(ForeignState, context_schema=BeastmodeContext)
    graph.add_node("provenance", provenance_gate)
    graph.add_edge(START, "provenance")
    graph.add_edge("provenance", END)
    compiled = graph.compile()
    result = compiled.invoke(
        {},
        context=BeastmodeContext(autonomy="high", run_dir=MATCH_RUN),
    )
    assert result["provenance_verdict"] == "unverifiable"
