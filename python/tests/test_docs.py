from __future__ import annotations

import json
from pathlib import Path

from beastmode.langgraph.studio import studio_pipeline


ROOT = Path(__file__).resolve().parents[2]


def test_studio_factory_and_templates_are_importable() -> None:
    graph = studio_pipeline()
    assert "gate_provenance" in graph.get_graph().draw_mermaid()
    templates = (ROOT / "references" / "langgraph-templates.md").read_text()
    for phrase in ("provenance_gate", "build_pipeline", "PipelineDependencies", "run_pipeline"):
        assert phrase in templates


def test_langgraph_manifest_points_to_the_zero_arg_factory() -> None:
    manifest = json.loads((ROOT / "langgraph.json").read_text())
    assert manifest["graphs"]["pipeline"] == "beastmode.langgraph.studio:studio_pipeline"
