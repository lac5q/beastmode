from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from beastmode.langgraph.studio import studio_pipeline


ROOT = Path(__file__).resolve().parents[2]


def test_studio_factory_is_importable() -> None:
    graph = studio_pipeline()
    assert "gate_provenance" in graph.get_graph().draw_mermaid()


def _documented_templates() -> dict[str, str]:
    text = (ROOT / "references" / "langgraph-templates.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)
    templates: dict[str, str] = {}
    for block in blocks:
        marker = re.search(r"^# template: ([a-z0-9-]+)$", block, flags=re.MULTILINE)
        if marker:
            templates[marker.group(1)] = block
    return templates


@pytest.mark.parametrize(
    "name",
    [
        "provenance-gate-only",
        "minimal-gated-loop",
        "acn-fanout-only",
        "full-pipeline",
    ],
)
def test_every_documented_template_executes(name: str) -> None:
    templates = _documented_templates()
    assert set(templates) == {
        "provenance-gate-only",
        "minimal-gated-loop",
        "acn-fanout-only",
        "full-pipeline",
    }
    namespace: dict[str, object] = {}
    exec(compile(templates[name], f"langgraph-template:{name}", "exec"), namespace)
    assert callable(namespace.get("smoke"))
    assert namespace["smoke"]() is True


def test_langgraph_manifest_points_to_the_zero_arg_factory() -> None:
    manifest = json.loads((ROOT / "langgraph.json").read_text())
    assert manifest["graphs"]["pipeline"] == "beastmode.langgraph.studio:studio_pipeline"
