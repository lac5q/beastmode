"""Optional LangChain model adapters for framework-neutral Beastmode seats."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from beastmode.core.seats import SeatModel


class SeatChatModel(BaseChatModel):
    """Expose a :class:`SeatModel` as a normal LangChain chat model.

    The wrapped provider model remains responsible for its own response
    metadata.  Beastmode records that response through ``SeatModel`` before
    returning it, so the adapter cannot accidentally turn an unproven model
    into a passing provenance record.
    """

    seat: SeatModel

    model_config = {"arbitrary_types_allowed": True, "extra": "forbid"}

    @property
    def _llm_type(self) -> str:
        return "beastmode-seat"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"requested_model": self.seat.requested_model, "tier": self.seat.tier}

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        response = self.seat.invoke(messages, stop=stop, **kwargs)
        message = _as_message(response)
        return ChatResult(
            generations=[ChatGeneration(message=message)],
            llm_output=dict(getattr(response, "response_metadata", {}) or {}),
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        response = await self.seat.ainvoke(messages, stop=stop, **kwargs)
        message = _as_message(response)
        return ChatResult(
            generations=[ChatGeneration(message=message)],
            llm_output=dict(getattr(response, "response_metadata", {}) or {}),
        )


def _as_message(response: Any) -> BaseMessage:
    if isinstance(response, BaseMessage):
        return response
    response_metadata = dict(getattr(response, "response_metadata", {}) or {})
    usage_metadata = _usage_metadata(getattr(response, "usage_metadata", None))
    content = getattr(response, "content", None)
    if content is None:
        content = str(response)
    return AIMessage(
        content=content,
        response_metadata=response_metadata,
        usage_metadata=usage_metadata,
    )


def _usage_metadata(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    normalized = dict(value)
    if "total_tokens" not in normalized:
        input_tokens = normalized.get("input_tokens")
        output_tokens = normalized.get("output_tokens")
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            normalized["total_tokens"] = input_tokens + output_tokens
    required = {"input_tokens", "output_tokens", "total_tokens"}
    return normalized if required.issubset(normalized) else None
