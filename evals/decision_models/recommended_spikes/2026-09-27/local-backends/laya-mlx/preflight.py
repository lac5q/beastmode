#!/usr/bin/env python3
"""Record Laya-MLX platform/import status and run pure-Python contracts only."""

from __future__ import annotations

import importlib.util
import json
import platform
import sys
import sysconfig
import types
from pathlib import Path


PIN = "0a859518634112655cb97c745dbf04f5191aaf13"
REPO = Path("/tmp/beastmode-local-repos-20260927/laya-mlx").resolve()


def pure_python_contracts() -> dict:
    # Import modules without executing laya_mlx/__init__.py, which imports MLX
    # through Agent. This is deliberately a pure-Python utility-only path.
    for name in list(sys.modules):
        if name == "laya_mlx" or name.startswith("laya_mlx."):
            del sys.modules[name]
    package = types.ModuleType("laya_mlx")
    package.__path__ = [str(REPO / "laya_mlx")]
    sys.modules["laya_mlx"] = package

    from laya_mlx.common import clamp_temperature, temp_bucket
    from laya_mlx.email import email_state
    from laya_mlx.lang import analyse, detect_script, is_english
    from laya_mlx.presets import triage_questions
    from laya_mlx.router import Router, normalise_name

    assert clamp_temperature(0.1) == 0.5
    assert clamp_temperature(99) == 5.0
    assert temp_bucket(0, 13) == "choice:11+"
    assert detect_script("客户被重复扣款要求退款") == "han"
    assert is_english("Please refund the duplicate charge") is True
    assert analyse("Müşteriden iki kez ücret alındı ve para iadesi istiyor")["language_undecided"] is True
    assert normalise_name("ML") == "multilingual"
    router = Router()
    assert router.route("I was charged twice and want a refund").model == "english"
    assert router.route("你好").model == "multilingual"
    assert "customer" in str(email_state("Hi", "Customer charged twice")).lower()
    assert isinstance(triage_questions(), dict)
    return {
        "status": "pass",
        "scope": "pure Python utilities only; no MLX or model inference",
        "checks": [
            "temperature_clamp_and_bucket",
            "script_and_language_detection",
            "router_alias_and_language_route",
            "email_state",
            "question_preset",
        ],
    }


def main() -> None:
    info = {
        "status": "preflight",
        "source_pin": PIN,
        "repo": str(REPO),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "python_implementation": platform.python_implementation(),
        "mlx_spec_found": importlib.util.find_spec("mlx") is not None,
        "model_load": {"attempted": False, "reason": "MLX backend unavailable on Linux x86_64"},
    }
    try:
        import laya_mlx  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - preserve the exact platform blocker.
        info["package_import"] = {
            "status": "blocked",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    else:
        info["package_import"] = {"status": "pass"}
    try:
        info["pure_python_contracts"] = pure_python_contracts()
    except Exception as exc:  # noqa: BLE001 - receipt should preserve test failure.
        info["pure_python_contracts"] = {
            "status": "fail",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        raise
    print(json.dumps(info, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
