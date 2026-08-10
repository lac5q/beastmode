from __future__ import annotations

import io
import json
from pathlib import Path
import sys

from beastmode.acp import ACPServer


def _messages(writer: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in writer.getvalue().splitlines()]


def _initialize(server: ACPServer) -> None:
    server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": 1},
        }
    )


def _new_session(server: ACPServer, cwd: Path) -> str:
    server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {"cwd": str(cwd), "mcpServers": []},
        }
    )
    response = _messages(server.writer)[-1]  # type: ignore[arg-type]
    return response["result"]["sessionId"]


def test_initialize_and_new_session_advertise_editor_controls(tmp_path: Path) -> None:
    writer = io.StringIO()
    server = ACPServer(writer=writer)

    _initialize(server)
    session_id = _new_session(server, tmp_path)

    messages = _messages(writer)
    init = messages[0]["result"]
    session = messages[1]["result"]
    assert init["protocolVersion"] == 1
    assert init["authMethods"][0]["id"] == "beastmode-local-backend"
    assert session["sessionId"] == session_id
    assert session["modes"]["currentModeId"] == "medium"
    assert session["configOptions"][0]["id"] == "beastmode-autonomy"


def test_prompt_forwards_argv_and_streams_output(tmp_path: Path, monkeypatch) -> None:
    backend = tmp_path / "backend.py"
    backend.write_text(
        "import sys\nprint('backend output: ' + sys.argv[1], flush=True)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "BEASTMODE_ACP_BACKEND_JSON",
        json.dumps([sys.executable, str(backend), "{goal}"]),
    )
    writer = io.StringIO()
    server = ACPServer(writer=writer)
    _initialize(server)
    session_id = _new_session(server, tmp_path)

    server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/prompt",
            "params": {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "ship the editor goal"}],
            },
        }
    )
    session = server._sessions[session_id]
    assert session.thread is not None
    session.thread.join(timeout=5)
    assert not session.thread.is_alive()

    messages = _messages(writer)
    chunks = [
        item["params"]["update"]["content"]["text"]
        for item in messages
        if item.get("method") == "session/update"
        and item["params"]["update"].get("sessionUpdate") == "agent_message_chunk"
    ]
    response = next(item for item in messages if item.get("id") == 3)
    assert any("backend output: ship the editor goal" in chunk for chunk in chunks)
    assert response["result"]["stopReason"] == "end_turn"
    assert response["result"]["_meta"]["beastmode"]["status"] == "completed"


def test_failed_backend_maps_to_refusal_and_redacts_error(tmp_path: Path, monkeypatch) -> None:
    backend = tmp_path / "backend.py"
    backend.write_text(
        "import sys\nprint('token=secret-value', file=sys.stderr, flush=True)\nsys.exit(3)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "BEASTMODE_ACP_BACKEND_JSON",
        json.dumps([sys.executable, str(backend), "{goal}"]),
    )
    writer = io.StringIO()
    server = ACPServer(writer=writer)
    _initialize(server)
    session_id = _new_session(server, tmp_path)
    server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/prompt",
            "params": {
                "sessionId": session_id,
                "prompt": [{"type": "resource_link", "uri": "file:///tmp/goal.md"}],
            },
        }
    )
    session = server._sessions[session_id]
    assert session.thread is not None
    session.thread.join(timeout=5)

    messages = _messages(writer)
    response = next(item for item in messages if item.get("id") == 3)
    output = writer.getvalue()
    assert response["result"]["stopReason"] == "refusal"
    assert response["result"]["_meta"]["beastmode"]["status"] == "blocked"
    assert "secret-value" not in output
    assert "[REDACTED]" in output


def test_modes_config_and_auth_validation(tmp_path: Path, monkeypatch) -> None:
    backend = tmp_path / "backend.py"
    backend.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv(
        "BEASTMODE_ACP_BACKEND_JSON", json.dumps([sys.executable, str(backend)])
    )
    writer = io.StringIO()
    server = ACPServer(writer=writer)
    _initialize(server)
    session_id = _new_session(server, tmp_path)
    server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "session/set_mode",
            "params": {"sessionId": session_id, "modeId": "high"},
        }
    )
    server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "session/set_config_option",
            "params": {
                "sessionId": session_id,
                "configId": "beastmode-autonomy",
                "value": "low",
            },
        }
    )
    server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "authenticate",
            "params": {"methodId": "beastmode-local-backend"},
        }
    )
    messages = _messages(writer)
    assert messages[-1]["id"] == 6
    assert messages[-1]["result"] == {}
    assert server._sessions[session_id].autonomy == "low"
