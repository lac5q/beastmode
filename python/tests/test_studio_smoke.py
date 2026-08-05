from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]


def _load_studio_smoke():
    path = ROOT / "python" / "scripts" / "studio-smoke.py"
    spec = importlib.util.spec_from_file_location("studio_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_live_process(pid: int) -> bool:
    status = Path(f"/proc/{pid}/status")
    if not status.exists():
        return False
    return "State:\tZ" not in status.read_text()


def test_cleanup_kills_term_resistant_descendant() -> None:
    module = _load_studio_smoke()
    child_code = (
        "import signal,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(60)"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        "print(p.pid, flush=True); time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert process.stdout is not None
    descendant = int(process.stdout.readline())
    assert _is_live_process(descendant)

    module._terminate_process_group(process, grace_seconds=0.2)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and _is_live_process(descendant):
        time.sleep(0.05)
    assert not _is_live_process(descendant)
