"""Schema-backed seat and tier-alias resolution."""

from __future__ import annotations

import json
import inspect
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .schema import schema_root


class UnknownAliasError(LookupError):
    """Raised when a friendly tier alias cannot be resolved."""


class SeatUnavailable(RuntimeError):
    """Raised when a requested seat is not available to the selected runtime."""

    def __init__(self, seat: "SeatModel", alternatives: Iterable[str] = ()):
        self.seat = seat
        self.alternatives = tuple(str(item) for item in alternatives)
        super().__init__(self._message())

    def _message(self) -> str:
        alternatives = ", ".join(self.alternatives) or "none reported"
        return (
            f"requested seat {self.seat.qualified!r} is unavailable; "
            f"available alternatives: {alternatives}. "
            "Set BM_SKIP_MODEL_CHECK=1 only when the runtime will verify the "
            "seat itself."
        )


@dataclass(frozen=True)
class SeatModel:
    """A resolved provider/model pair and its optional Beastmode vocabulary."""

    alias: str
    provider: str
    model: str
    tier: str | None = None
    family: str | None = None
    resolved: bool = True
    chat_model: Any | None = None
    run_dir: Path | None = None
    child_id: str | None = None

    @property
    def qualified(self) -> str:
        return f"{self.provider}/{self.model}"

    @property
    def requested_model(self) -> str:
        """The fully qualified model id recorded in child provenance."""
        return self.qualified

    def with_chat_model(
        self,
        chat_model: Any,
        *,
        run_dir: Path | None = None,
        child_id: str | None = None,
    ) -> "SeatModel":
        """Bind an already-configured chat model without importing its SDK."""
        return SeatModel(
            alias=self.alias,
            provider=self.provider,
            model=self.model,
            tier=self.tier,
            family=self.family,
            resolved=self.resolved,
            chat_model=chat_model,
            run_dir=run_dir,
            child_id=child_id,
        )

    def as_chat_model(self) -> Any:
        """Return the optional LangChain wrapper around this seat.

        The import stays behind the method boundary so ``beastmode.core``
        remains usable on machines that intentionally have no LangGraph or
        LangChain installation.
        """
        from beastmode.langgraph.models import SeatChatModel

        return SeatChatModel(seat=self)

    def invoke(
        self,
        value: Any,
        *,
        run_dir: Path | None = None,
        child_id: str | None = None,
        files_changed: Iterable[str] = (),
        commands_run: Iterable[str] = (),
        verify: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Invoke the bound model and write a canonical child meta when asked."""
        if self.chat_model is None:
            raise SeatUnavailable(self)
        response = self.chat_model.invoke(value, **kwargs)
        self._record_response(
            response,
            run_dir=run_dir,
            child_id=child_id,
            files_changed=files_changed,
            commands_run=commands_run,
            verify=verify,
        )
        return response

    async def ainvoke(
        self,
        value: Any,
        *,
        run_dir: Path | None = None,
        child_id: str | None = None,
        files_changed: Iterable[str] = (),
        commands_run: Iterable[str] = (),
        verify: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Async counterpart used by LangGraph's primary execution path."""
        if self.chat_model is None:
            raise SeatUnavailable(self)
        method = getattr(self.chat_model, "ainvoke", None)
        if method is None:
            response = self.chat_model.invoke(value, **kwargs)
        else:
            response = method(value, **kwargs)
            if inspect.isawaitable(response):
                response = await response
        self._record_response(
            response,
            run_dir=run_dir,
            child_id=child_id,
            files_changed=files_changed,
            commands_run=commands_run,
            verify=verify,
        )
        return response

    def child_meta(
        self,
        response: Any,
        *,
        child_id: str | None = None,
        files_changed: Iterable[str] = (),
        commands_run: Iterable[str] = (),
        verify: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Derive canonical metadata, failing closed when the provider is silent."""
        response_metadata = _response_mapping(response, "response_metadata")
        usage_metadata = _response_mapping(response, "usage_metadata")
        actual = _observed_model(response_metadata, usage_metadata)
        if actual is not None and "/" not in actual:
            actual = f"{self.provider}/{actual}"
        stop_reason = _first_value(
            response_metadata,
            "stop_reason",
            "finish_reason",
            "finishReason",
        )
        return {
            "id": child_id or self.child_id or self.alias,
            "requested_model": self.requested_model,
            # None is intentional: acn_meta classifies a missing/empty actual
            # id as UNVERIFIABLE instead of allowing a silent provider pass.
            "actual_model": actual,
            "stop_reason": stop_reason or "unavailable",
            "usage": dict(usage_metadata),
            "files_changed": list(files_changed),
            "commands_run": list(commands_run),
            "verify": dict(verify or {}),
        }

    def _record_response(
        self,
        response: Any,
        *,
        run_dir: Path | None,
        child_id: str | None,
        files_changed: Iterable[str],
        commands_run: Iterable[str],
        verify: Mapping[str, Any] | None,
    ) -> None:
        destination_dir = run_dir or self.run_dir
        if destination_dir is None:
            return
        meta = self.child_meta(
            response,
            child_id=child_id,
            files_changed=files_changed,
            commands_run=commands_run,
            verify=verify,
        )
        write_child_meta(destination_dir, meta)


def preflight_seat(
    seat: SeatModel,
    *,
    available_models: Iterable[str] | None = None,
) -> SeatModel:
    """Validate a seat before graph compilation when a runtime can list models.

    Provider SDKs do not expose one portable model-listing API.  Callers that
    have one pass its results; callers that do not still get alias validation
    from :func:`resolve_alias` and must rely on the provider call plus the
    fail-closed provenance gate.  The explicit bypass mirrors the shell
    preflight and is intentionally visible in the exception text.
    """
    if os.environ.get("BM_SKIP_MODEL_CHECK") == "1":
        return seat
    if not seat.resolved:
        raise SeatUnavailable(seat, available_models or ())
    if available_models is None:
        return seat
    available = {str(model) for model in available_models}
    candidates = {seat.alias, seat.model, seat.qualified}
    if not candidates.intersection(available):
        raise SeatUnavailable(seat, sorted(available))
    return seat


def write_child_meta(run_dir: Path, meta: Mapping[str, Any]) -> Path:
    """Atomically write one canonical ``meta.json`` into a child run dir."""
    destination_dir = Path(run_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / "meta.json"
    fd, temporary_name = tempfile.mkstemp(
        prefix=".meta.", suffix=".tmp", dir=destination_dir
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(meta), handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return destination


def _response_mapping(response: Any, attribute: str) -> dict[str, Any]:
    value = response.get(attribute) if isinstance(response, Mapping) else getattr(response, attribute, {})
    return dict(value) if isinstance(value, Mapping) else {}


def _first_value(mapping: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", "unavailable", "unknown"):
            return str(value)
    return None


def _observed_model(
    response_metadata: Mapping[str, Any],
    usage_metadata: Mapping[str, Any],
) -> str | None:
    for mapping in (response_metadata, usage_metadata):
        value = _first_value(
            mapping,
            "model_name",
            "model",
            "model_id",
            "served_model",
            "model_used",
        )
        if value is not None:
            return value
    return None


def _candidate_files(repo: Path, home: Path) -> Iterable[Path]:
    # This is intentionally the same precedence as scripts/bm.
    yield repo / ".beastmode" / "tier-aliases.json"
    yield home / ".beastmode" / "tier-aliases.json"
    try:
        yield schema_root(repo).parent / "scripts" / "tier-aliases.json"
    except OSError:
        return


def _read_alias_file(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_alias(
    alias: str,
    *,
    repo: Path | None = None,
    home: Path | None = None,
) -> SeatModel:
    """Resolve a friendly alias using project, user, then shipped config."""
    if "/" in alias:
        provider, model = alias.split("/", 1)
        return SeatModel(alias, provider, model)

    repo_path = (repo or Path.cwd()).resolve()
    home_path = (home or Path.home()).resolve()
    for path in _candidate_files(repo_path, home_path):
        entry = _read_alias_file(path).get(alias)
        if not isinstance(entry, dict):
            continue
        provider = entry.get("provider")
        model = entry.get("model")
        if not isinstance(provider, str) or not isinstance(model, str):
            raise ValueError(f"alias {alias!r} in {path} lacks provider/model")
        return SeatModel(
            alias=alias,
            provider=provider,
            model=model,
            tier=entry.get("tier"),
            family=entry.get("family"),
        )
    raise UnknownAliasError(f"unknown Beastmode tier alias: {alias}")


def resolve_many(
    aliases: Iterable[str],
    *,
    repo: Path | None = None,
    home: Path | None = None,
) -> tuple[SeatModel, ...]:
    """Resolve several aliases while preserving input order."""
    return tuple(resolve_alias(alias, repo=repo, home=home) for alias in aliases)
