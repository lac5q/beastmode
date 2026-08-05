#!/usr/bin/env python3
"""Start ``langgraph dev`` long enough to prove manifest discovery and health."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _terminate_process_group(
    process: subprocess.Popen[str], *, grace_seconds: float = 10
) -> None:
    """Terminate the Studio session and every descendant it launched."""
    try:
        process_group = os.getpgid(process.pid)
    except ProcessLookupError:
        process.wait(timeout=1)
        return

    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        pass

    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        # The group signal should have handled the direct child too. This is
        # only a final reap fallback for unusual platform behavior.
        process.kill()
        process.wait(timeout=1)


def main() -> int:
    port = _free_local_port()
    cli = Path(sys.executable).with_name("langgraph")
    if not cli.is_file():
        print("langgraph console script is not installed", file=sys.stderr)
        return 2
    command = [
        str(cli),
        "dev",
        "--no-browser",
        "--no-reload",
        "--allow-blocking",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    environment = dict(os.environ)
    environment.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout is not None else ""
                print(output, file=sys.stderr)
                return process.returncode or 1
            try:
                with urlopen(f"http://127.0.0.1:{port}/ok", timeout=0.5) as response:
                    if response.status == 200 and response.read() == b'{"ok":true}':
                        print("LangGraph Studio manifest discovery and health smoke passed")
                        return 0
            except (OSError, URLError):
                time.sleep(0.1)
        print("LangGraph Studio did not become healthy within 30 seconds", file=sys.stderr)
        return 1
    finally:
        _terminate_process_group(process)


if __name__ == "__main__":
    raise SystemExit(main())
