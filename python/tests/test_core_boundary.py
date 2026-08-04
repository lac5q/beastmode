from __future__ import annotations

import ast
from pathlib import Path


def test_core_has_no_framework_imports() -> None:
    root = Path(__file__).parents[1] / "src" / "beastmode" / "core"
    forbidden = {"langgraph", "langchain", "langchain_core", "crewai"}
    violations: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".", 1)[0] in forbidden:
                    violations.append(f"{path}:{node.lineno}: {name}")
    assert not violations, "framework imports in beastmode.core: " + ", ".join(violations)
