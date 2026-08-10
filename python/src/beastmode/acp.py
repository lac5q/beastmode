"""Thin Agent Client Protocol adapter for editor-launched Beastmode goals.

This module deliberately owns only the ACP transport/session boundary.  It
forwards each prompt to the existing ``bm`` runner (or an explicitly
configured argv template); Beastmode's orchestration, permission policy,
model routing, and learning loop remain outside this adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading
from typing import Any, IO, Mapping, Sequence
import uuid

from . import __version__
from .core.observability import redact_text


ACP_PROTOCOL_VERSION = 1
MAX_PROMPT_CHARS = 64 * 1024
_BACKEND_ENV = "BEASTMODE_ACP_BACKEND"
_BACKEND_JSON_ENV = "BEASTMODE_ACP_BACKEND_JSON"
_DEFAULT_BACKEND = "bm --autonomy {autonomy}"
_ASYNC = object()


class ACPError(Exception):
    """A JSON-RPC error suitable for an ACP response."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass
class _Session:
    session_id: str
    cwd: Path
    autonomy: str = "medium"
    process: subprocess.Popen[bytes] | None = None
    thread: threading.Thread | None = None
    cancelled: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class ACPServer:
    """Small line-delimited JSON-RPC ACP agent server."""

    def __init__(
        self,
        *,
        reader: IO[str] | None = None,
        writer: IO[str] | None = None,
    ) -> None:
        self.reader = reader or sys.stdin
        self.writer = writer or sys.stdout
        self._write_lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}
        self._initialized = False

    def serve(self) -> int:
        """Read ACP JSON-RPC messages until the editor closes stdin."""
        for line in self.reader:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                self._send_error(None, -32700, "Parse error", str(exc))
                continue
            self.handle_message(message)
        for session in tuple(self._sessions.values()):
            thread = session.thread
            if thread is not None:
                thread.join(timeout=1.0)
        return 0

    def handle_message(self, message: Any) -> None:
        """Dispatch one decoded JSON-RPC message; public for adapter tests."""
        if not isinstance(message, Mapping) or message.get("jsonrpc") != "2.0":
            self._send_error(
                message.get("id") if isinstance(message, Mapping) else None,
                -32600,
                "Invalid Request",
            )
            return
        has_id = "id" in message
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str) or not method:
            if has_id:
                self._send_error(request_id, -32600, "Invalid Request")
            return
        params = message.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, Mapping):
            if has_id:
                self._send_error(request_id, -32602, "params must be an object")
            return
        try:
            result = self._dispatch(method, params, request_id if has_id else None)
        except ACPError as exc:
            if has_id:
                self._send_error(request_id, exc.code, exc.message, exc.data)
            return
        except Exception as exc:  # pragma: no cover - final transport guard
            print(f"beastmode-acp: {type(exc).__name__}: {exc}", file=sys.stderr)
            if has_id:
                self._send_error(request_id, -32603, "Internal error")
            return
        if has_id and result is not _ASYNC:
            self._send_response(request_id, result)

    def _dispatch(
        self, method: str, params: Mapping[str, Any], request_id: Any
    ) -> Any:
        if method == "initialize":
            return self._initialize(params)
        if not self._initialized:
            raise ACPError(-32002, "initialize must be called first")
        if method == "authenticate":
            return self._authenticate(params)
        if method == "session/new":
            return self._new_session(params)
        if method == "session/prompt":
            if request_id is None:
                raise ACPError(-32600, "session/prompt requires a request id")
            return self._prompt(params, request_id)
        if method == "session/cancel":
            self._cancel(params)
            return _ASYNC
        if method == "session/set_mode":
            return self._set_mode(params)
        if method == "session/set_config_option":
            return self._set_config_option(params)
        if method == "session/close":
            return self._close_session(params)
        raise ACPError(-32601, f"Method not found: {method}")

    def _initialize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        version = params.get("protocolVersion")
        if version != ACP_PROTOCOL_VERSION:
            raise ACPError(
                -32602,
                f"unsupported ACP protocolVersion {version!r}; supported version is 1",
            )
        self._initialized = True
        return {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "agentCapabilities": {
                "loadSession": False,
                "promptCapabilities": {
                    "image": False,
                    "audio": False,
                    "embeddedContext": False,
                },
                "mcpCapabilities": {"http": False, "sse": False},
                "sessionCapabilities": {},
                "auth": {},
            },
            # The ACP registry requires an authentication method.  The
            # adapter authenticates the local, already-configured bm backend;
            # it never receives or stores provider credentials itself.
            "authMethods": [
                {
                    "id": "beastmode-local-backend",
                    "name": "Local Beastmode backend",
                    "description": "Use the configured local bm runner.",
                }
            ],
            "agentInfo": {
                "name": "beastmode-acp",
                "title": "Beastmode Goals",
                "version": __version__,
            },
        }

    def _authenticate(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if params.get("methodId") != "beastmode-local-backend":
            raise ACPError(-32602, "unknown authentication method")
        self._backend_executable()
        return {}

    def _new_session(self, params: Mapping[str, Any]) -> dict[str, Any]:
        cwd_value = params.get("cwd")
        if not isinstance(cwd_value, str) or not cwd_value:
            raise ACPError(-32602, "session/new requires cwd")
        cwd = Path(cwd_value).expanduser()
        if not cwd.is_absolute() or not cwd.is_dir():
            raise ACPError(-32602, "session cwd must be an existing absolute directory")
        mcp_servers = params.get("mcpServers")
        if not isinstance(mcp_servers, list):
            raise ACPError(-32602, "session/new requires mcpServers")
        if mcp_servers:
            raise ACPError(-32602, "this thin adapter does not forward MCP servers")
        additional = params.get("additionalDirectories")
        if additional not in (None, []):
            raise ACPError(-32602, "this thin adapter does not support additionalDirectories")
        session = _Session(session_id=f"bm-{uuid.uuid4().hex}", cwd=cwd.resolve())
        self._sessions[session.session_id] = session
        return {
            "sessionId": session.session_id,
            "modes": self._modes(session),
            "configOptions": self._config_options(session),
        }

    def _prompt(self, params: Mapping[str, Any], request_id: Any) -> object:
        session = self._session(params)
        prompt = _prompt_text(params.get("prompt"))
        with session.lock:
            if session.thread is not None and session.thread.is_alive():
                raise ACPError(-32000, "session is already processing a prompt")
            session.cancelled = False
            thread = threading.Thread(
                target=self._run_prompt,
                args=(session, request_id, prompt),
                name=f"beastmode-acp-{session.session_id}",
                daemon=True,
            )
            session.thread = thread
            thread.start()
        return _ASYNC

    def _cancel(self, params: Mapping[str, Any]) -> None:
        session = self._session(params)
        with session.lock:
            session.cancelled = True
            process = session.process
        if process is not None and process.poll() is None:
            process.terminate()

    def _set_mode(self, params: Mapping[str, Any]) -> dict[str, Any]:
        session = self._session(params)
        mode = params.get("modeId")
        if mode not in {"low", "medium", "high"}:
            raise ACPError(-32602, "modeId must be low, medium, or high")
        with session.lock:
            if session.thread is not None and session.thread.is_alive():
                raise ACPError(-32000, "cannot change mode while a prompt is running")
            session.autonomy = str(mode)
        self._send_notification(
            "session/update",
            {
                "sessionId": session.session_id,
                "update": {
                    "sessionUpdate": "current_mode_update",
                    "currentModeId": session.autonomy,
                },
            },
        )
        return self._modes(session)

    def _set_config_option(self, params: Mapping[str, Any]) -> dict[str, Any]:
        session = self._session(params)
        if params.get("configId") != "beastmode-autonomy":
            raise ACPError(-32602, "unknown configuration option")
        value = params.get("value")
        if value not in {"low", "medium", "high"}:
            raise ACPError(-32602, "autonomy option must be low, medium, or high")
        with session.lock:
            session.autonomy = str(value)
        return {"configOptions": self._config_options(session)}

    def _close_session(self, params: Mapping[str, Any]) -> dict[str, Any]:
        session = self._session(params)
        with session.lock:
            session.cancelled = True
            process = session.process
        if process is not None and process.poll() is None:
            process.terminate()
        self._sessions.pop(session.session_id, None)
        return {}

    def _session(self, params: Mapping[str, Any]) -> _Session:
        session_id = params.get("sessionId")
        if not isinstance(session_id, str) or session_id not in self._sessions:
            raise ACPError(-32602, "unknown sessionId")
        return self._sessions[session_id]

    def _run_prompt(self, session: _Session, request_id: Any, prompt: str) -> None:
        message_id = f"bm-msg-{uuid.uuid4().hex}"
        self._send_text(session.session_id, "Beastmode goal accepted; starting the configured runner.\n", message_id)
        process: subprocess.Popen[bytes] | None = None
        stderr: list[str] = []
        try:
            argv = _backend_argv(session, prompt)
            process = subprocess.Popen(
                argv,
                cwd=session.cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "BEASTMODE_ACP_SESSION_ID": session.session_id},
            )
            with session.lock:
                session.process = process
                cancelled_before_start = session.cancelled
            if cancelled_before_start:
                process.terminate()
            assert process.stdout is not None and process.stderr is not None

            def collect_stderr() -> None:
                for chunk in process.stderr:
                    text = chunk.decode(errors="replace")
                    if text:
                        stderr.append(text)

            stderr_thread = threading.Thread(target=collect_stderr, daemon=True)
            stderr_thread.start()
            for chunk in process.stdout:
                text = chunk.decode(errors="replace")
                if text:
                    self._send_text(session.session_id, redact_text(text, limit=16_384), message_id)
            returncode = process.wait()
            stderr_thread.join(timeout=1.0)
            with session.lock:
                cancelled = session.cancelled
            if stderr and returncode != 0:
                self._send_text(
                    session.session_id,
                    redact_text("Backend error:\n" + "".join(stderr), limit=16_384),
                    message_id,
                )
            stop_reason = "cancelled" if cancelled else "end_turn" if returncode == 0 else "refusal"
            self._send_response(
                request_id,
                {
                    "stopReason": stop_reason,
                    "_meta": {
                        "beastmode": {
                            "exitCode": returncode,
                            "status": "cancelled" if cancelled else "completed" if returncode == 0 else "blocked",
                        }
                    },
                },
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._send_text(
                session.session_id,
                redact_text(f"Beastmode ACP backend unavailable: {exc}", limit=16_384),
                message_id,
            )
            self._send_response(
                request_id,
                {
                    "stopReason": "refusal",
                    "_meta": {"beastmode": {"status": "backend_unavailable"}},
                },
            )
        finally:
            with session.lock:
                session.process = None

    def _backend_executable(self) -> str:
        argv = _backend_template()
        executable = argv[0]
        if Path(executable).parent != Path("."):
            if not Path(executable).is_file():
                raise ACPError(-32001, f"configured backend executable is unavailable: {executable}")
            return executable
        resolved = shutil.which(executable)
        if resolved is None:
            raise ACPError(-32001, f"configured backend executable is unavailable: {executable}")
        return resolved

    @staticmethod
    def _modes(session: _Session) -> dict[str, Any]:
        return {
            "currentModeId": session.autonomy,
            "availableModes": [
                {"id": "low", "name": "Low", "description": "Pause at every phase boundary."},
                {"id": "medium", "name": "Medium", "description": "Pause at load-bearing gates."},
                {"id": "high", "name": "High", "description": "Run until a blocking gate or completion."},
            ],
        }

    @staticmethod
    def _config_options(session: _Session) -> list[dict[str, Any]]:
        return [
            {
                "id": "beastmode-autonomy",
                "name": "Beastmode autonomy",
                "description": "Controls Beastmode phase and gate pauses.",
                "category": "mode",
                "type": "select",
                "currentValue": session.autonomy,
                "options": [
                    {"value": "low", "name": "Low"},
                    {"value": "medium", "name": "Medium"},
                    {"value": "high", "name": "High"},
                ],
            }
        ]

    def _send_text(self, session_id: str, text: str, message_id: str) -> None:
        self._send_notification(
            "session/update",
            {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": text},
                    "messageId": message_id,
                },
            },
        )

    def _send_notification(self, method: str, params: Mapping[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    def _send_response(self, request_id: Any, result: Mapping[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "result": dict(result)})

    def _send_error(self, request_id: Any, code: int, message: str, data: Any = None) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        self._write({"jsonrpc": "2.0", "id": request_id, "error": error})

    def _write(self, message: Mapping[str, Any]) -> None:
        encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=True)
        with self._write_lock:
            self.writer.write(encoded + "\n")
            self.writer.flush()


def _prompt_text(value: Any) -> str:
    if not isinstance(value, list) or not value:
        raise ACPError(-32602, "prompt must contain at least one content block")
    chunks: list[str] = []
    for block in value:
        if not isinstance(block, Mapping):
            raise ACPError(-32602, "prompt content blocks must be objects")
        kind = block.get("type")
        if kind == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise ACPError(-32602, "text content requires a string text field")
            chunks.append(text)
        elif kind == "resource_link":
            uri = block.get("uri")
            if not isinstance(uri, str) or not uri:
                raise ACPError(-32602, "resource_link requires a uri")
            name = block.get("name")
            label = f" ({name})" if isinstance(name, str) and name else ""
            chunks.append(f"[Editor resource{label}: {uri}]")
        else:
            raise ACPError(-32602, f"unsupported prompt content type: {kind}")
    prompt = "\n\n".join(chunks).strip()
    if not prompt:
        raise ACPError(-32602, "prompt text cannot be empty")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ACPError(-32602, "prompt exceeds the adapter size limit")
    return prompt


def _backend_template() -> list[str]:
    raw_json = os.environ.get(_BACKEND_JSON_ENV)
    if raw_json:
        value = json.loads(raw_json)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{_BACKEND_JSON_ENV} must be a non-empty JSON argv array")
        return list(value)
    raw = os.environ.get(_BACKEND_ENV, _DEFAULT_BACKEND)
    argv = shlex.split(raw)
    if not argv:
        raise ValueError(f"{_BACKEND_ENV} cannot be empty")
    return argv


def _backend_argv(session: _Session, prompt: str) -> list[str]:
    values = {
        "{autonomy}": session.autonomy,
        "{goal}": prompt,
        "{session_id}": session.session_id,
    }
    template = _backend_template()
    argv: list[str] = []
    goal_in_template = False
    for token in template:
        if "{goal}" in token:
            goal_in_template = True
        rendered = token
        for placeholder, value in values.items():
            rendered = rendered.replace(placeholder, value)
        argv.append(rendered)
    if not goal_in_template:
        # bm treats `--` as the boundary after which editor text is always a
        # goal, preventing a prompt beginning with `--` from becoming a flag.
        argv.extend(("--", prompt))
    return argv


def _setup() -> int:
    print("Beastmode ACP setup")
    print("Set BEASTMODE_ACP_BACKEND to a local argv template (default: bm --autonomy {autonomy}).")
    print("Use {goal}, {autonomy}, and {session_id} placeholders; no shell is evaluated.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the adapter; ``beastmode --acp`` is the registry entry shape."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--setup" in args:
        return _setup()
    if args and args not in (["--acp"], ["acp"]):
        print("usage: beastmode [--acp] | beastmode-acp [--setup]", file=sys.stderr)
        return 2
    return ACPServer().serve()


if __name__ == "__main__":
    raise SystemExit(main())
