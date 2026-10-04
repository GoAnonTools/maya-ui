"""Provider-neutral wire schemas for the Maya Core HTTP/SSE API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..llm.base import (
    LLMCompleted,
    LLMConversation,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    LLMState,
    LLMSession,
    LLMTextDelta,
    LLMToolCall,
    LLMToolCallDelta,
    LLMUsage,
)

MAYA_CORE_PROTOCOL_VERSION = 1


def _tool_call_payload(call: LLMToolCall) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}


def _message_payload(message: LLMMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.name is not None:
        payload["name"] = message.name
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [_tool_call_payload(call) for call in message.tool_calls]
    return payload


@dataclass(frozen=True)
class MayaCoreRequest:
    """Complete request sent to Maya Core.

    ``message`` remains present for older localhost Core deployments that only
    understand the original single-message request shape.
    """

    messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...] = ()
    tool_choice: str = "auto"
    temperature: float | None = None
    max_tokens: int | None = None
    conversation_id: str | int | None = None
    session_id: str | None = None
    message: str = ""
    protocol_version: int = MAYA_CORE_PROTOCOL_VERSION

    @classmethod
    def from_llm_request(cls, request: LLMRequest, *, session_id: str | None = None) -> "MayaCoreRequest":
        latest_user_message = next(
            (item.content for item in reversed(request.messages) if item.role == "user"),
            "",
        )
        return cls(
            messages=tuple(_message_payload(message) for message in request.messages),
            tools=tuple(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                }
                for tool in request.tools
            ),
            tool_choice=request.tool_choice,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            conversation_id=request.conversation_id,
            session_id=request.session_id or session_id,
            message=latest_user_message,
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "message": self.message,
            "messages": list(self.messages),
            "tools": list(self.tools),
            "tool_choice": self.tool_choice,
        }
        for key, value in (
            ("temperature", self.temperature),
            ("max_tokens", self.max_tokens),
            ("conversation_id", self.conversation_id),
            ("session_id", self.session_id),
        ):
            if value is not None:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class MayaCoreTextDelta:
    text: str
    replace: bool = False
    event_type: str = "text_delta"


@dataclass(frozen=True)
class MayaCoreToolCallDelta:
    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""
    event_type: str = "tool_call_delta"


@dataclass(frozen=True)
class MayaCoreUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    event_type: str = "usage"


@dataclass(frozen=True)
class MayaCoreCompleted:
    finish_reason: str | None = None
    event_type: str = "completed"


@dataclass(frozen=True)
class MayaCoreConversation:
    conversation_id: str | int
    event_type: str = "conversation"


@dataclass(frozen=True)
class MayaCoreSession:
    session_id: str
    event_type: str = "session"


@dataclass(frozen=True)
class MayaCoreState:
    state: str
    detail: str = ""
    event_type: str = "state"


MayaCoreResponseEvent = (
    MayaCoreTextDelta
    | MayaCoreToolCallDelta
    | MayaCoreUsage
    | MayaCoreCompleted
    | MayaCoreConversation
    | MayaCoreSession
    | MayaCoreState
)


def _event_data(payload: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    event_type = payload.get("type", payload.get("event"))
    data = payload.get("data")
    if isinstance(data, Mapping):
        body = data
    else:
        body = payload
    if not isinstance(event_type, str) or not event_type:
        event_type = str(body.get("type", body.get("event", "")))
    return event_type, body


def decode_maya_core_event(payload: Mapping[str, Any]) -> MayaCoreResponseEvent | LLMProviderError:
    """Decode one structured Core event into a provider-neutral event/error."""
    event_type, data = _event_data(payload)
    if event_type in {"text", "text_delta", "delta"}:
        return MayaCoreTextDelta(str(data.get("text", "")), bool(data.get("replace", False)))
    if event_type in {"tool_call", "tool_call_delta"}:
        return MayaCoreToolCallDelta(
            index=int(data.get("index", 0)),
            id=data.get("id") if isinstance(data.get("id"), str) else None,
            name=data.get("name") if isinstance(data.get("name"), str) else None,
            arguments_delta=str(data.get("arguments_delta", data.get("arguments", ""))),
        )
    if event_type == "usage":
        return MayaCoreUsage(data.get("input_tokens"), data.get("output_tokens"))
    if event_type in {"completed", "done"}:
        reason = data.get("finish_reason")
        return MayaCoreCompleted(reason if isinstance(reason, str) else None)
    if event_type == "conversation":
        if "conversation_id" not in data:
            raise ValueError("conversation event is missing conversation_id")
        return MayaCoreConversation(data["conversation_id"])
    if event_type == "session":
        if not isinstance(data.get("session_id"), str):
            raise ValueError("session event is missing session_id")
        return MayaCoreSession(data["session_id"])
    if event_type == "state":
        return MayaCoreState(str(data.get("state", "")), str(data.get("detail", "")))
    if event_type == "error":
        return LLMProviderError(
            "provider",
            "Maya Core returned an error",
            provider="maya_core",
            retryable=bool(data.get("retryable", False)),
        )
    raise ValueError(f"Unknown Maya Core event type: {event_type or '<missing>'}")


def to_llm_event(event: MayaCoreResponseEvent):
    if isinstance(event, MayaCoreTextDelta):
        return LLMTextDelta(event.text, replace=event.replace)
    if isinstance(event, MayaCoreToolCallDelta):
        return LLMToolCallDelta(event.index, event.id, event.name, event.arguments_delta)
    if isinstance(event, MayaCoreUsage):
        return LLMUsage(event.input_tokens, event.output_tokens)
    if isinstance(event, MayaCoreCompleted):
        return LLMCompleted(event.finish_reason)
    if isinstance(event, MayaCoreConversation):
        return LLMConversation(event.conversation_id)
    if isinstance(event, MayaCoreSession):
        return LLMSession(event.session_id)
    if isinstance(event, MayaCoreState):
        return LLMState(event.state, event.detail)
    raise TypeError(f"Unsupported Maya Core event: {type(event)!r}")
