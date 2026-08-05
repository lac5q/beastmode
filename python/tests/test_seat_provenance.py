from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from beastmode.core.provenance import check_provenance, sign_attestation
from beastmode.core.seats import SeatUnavailable, preflight_seat, resolve_alias
from beastmode.langgraph.models import as_chat_model


ROOT = Path(__file__).resolve().parents[2]


class _Response:
    response_metadata = {"model_name": "MiniMax-M3", "finish_reason": "stop"}
    usage_metadata = {"input_tokens": 2, "output_tokens": 3}


class _SilentResponse:
    response_metadata = {"finish_reason": "stop"}
    usage_metadata = {"input_tokens": 2, "output_tokens": 3}


class _OversizedResponse:
    response_metadata = {"model_name": {"nested": ["x"] * 10_000}}
    usage_metadata = {"nested": ["x"] * 10_000}


class _Model:
    def invoke(self, value, **kwargs):
        assert value == "hello"
        return _Response()

    async def ainvoke(self, value, **kwargs):
        return _Response()


class _SilentModel:
    def invoke(self, value, **kwargs):
        return _SilentResponse()


class _ChatResponse(_Response):
    content = "hello back"


class _ChatModel:
    def invoke(self, value, **kwargs):
        assert isinstance(value, list)
        return _ChatResponse()

    async def ainvoke(self, value, **kwargs):
        return _ChatResponse()


def test_seat_metadata_requires_independent_provider_attestation(tmp_path: Path) -> None:
    seat = resolve_alias("minimax/MiniMax-M3", repo=tmp_path, home=tmp_path / "home")
    seat = seat.with_chat_model(_Model())
    response = seat.invoke("hello", run_dir=tmp_path / "child", child_id="child-1")
    assert isinstance(response, _Response)
    meta = json.loads((tmp_path / "child" / "meta.json").read_text())
    assert meta["requested_model"] == "minimax/MiniMax-M3"
    assert meta["actual_model"] == "minimax/MiniMax-M3"
    assert check_provenance(tmp_path / "child", repo=ROOT).exit_code == 1
    attestation = tmp_path / "provider-attestation.json"
    attestation_key = bytes(32)
    attestation_run_id = "seat-fixture-run"
    record = {
        "id": "child-1",
        "requested_model": meta["requested_model"],
        "actual_model": meta["actual_model"],
        "source": "provider-response",
        "run_id": attestation_run_id,
        "result_digest": hashlib.sha256(
            (tmp_path / "child" / "meta.json").read_bytes()
        ).hexdigest(),
    }
    record["signature"] = sign_attestation(record, attestation_key)
    attestation.write_text(
        json.dumps(record),
        encoding="utf-8",
    )
    assert (
        check_provenance(
            tmp_path / "child",
            repo=ROOT,
            attestations=attestation,
            attestation_key=attestation_key,
            attestation_run_id=attestation_run_id,
        ).exit_code
        == 0
    )


def test_silent_provider_is_unverifiable_and_async_path_writes(tmp_path: Path) -> None:
    seat = resolve_alias("minimax/MiniMax-M3", repo=tmp_path, home=tmp_path / "home")
    seat = seat.with_chat_model(_SilentModel())
    asyncio.run(seat.ainvoke("hello", run_dir=tmp_path / "child", child_id="silent"))
    meta = json.loads((tmp_path / "child" / "meta.json").read_text())
    assert meta["actual_model"] is None
    assert check_provenance(tmp_path / "child", repo=ROOT).exit_code == 1


def test_provider_metadata_is_bounded_before_child_serialization(tmp_path: Path) -> None:
    seat = resolve_alias("minimax/MiniMax-M3", repo=tmp_path, home=tmp_path / "home")
    seat = seat.with_chat_model(_Model())
    with pytest.raises(ValueError, match="provider metadata"):
        seat.child_meta(_OversizedResponse(), child_id="oversized")
    assert not (tmp_path / "child" / "meta.json").exists()


def test_preflight_reports_alternatives_and_supports_explicit_bypass(monkeypatch) -> None:
    seat = resolve_alias("minimax/MiniMax-M3")
    with pytest.raises(SeatUnavailable, match="available alternatives"):
        preflight_seat(seat, available_models=["qwen/qwen3.7-plus"])
    monkeypatch.setenv("BM_SKIP_MODEL_CHECK", "1")
    assert preflight_seat(seat, available_models=[]).qualified == "minimax/MiniMax-M3"


def test_seat_can_be_used_as_a_langchain_base_chat_model(tmp_path: Path) -> None:
    seat = resolve_alias("minimax/MiniMax-M3", repo=tmp_path, home=tmp_path / "home")
    seat = seat.with_chat_model(_ChatModel(), run_dir=tmp_path / "child", child_id="wrapped")
    response = as_chat_model(seat).invoke([HumanMessage(content="hello")])
    assert response.content == "hello back"
    meta = json.loads((tmp_path / "child" / "meta.json").read_text())
    assert meta["id"] == "wrapped"
    assert meta["actual_model"] == "minimax/MiniMax-M3"
