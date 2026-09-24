"""Stable, provider-neutral contracts for Maya's language model layer.

These types define an interface only. They do not select or call a provider,
manage conversation history, execute tools, or change Maya's runtime flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Literal, Mapping, Protocol, TypeAlias, runtime_checkable


JsonObject: TypeAlias = Mapping[str, object]
LLMErrorCode: TypeAlias = Literal[
    "connection",
    "timeout",
    "authentication",
    "rate_limit",
    "invalid_request",
    "unsupported_capability",
    "provider",
    "context_overflow",
]


@dataclass(frozen=True)
class LLMToolCall:
    """A complete model-requested tool call; execution belongs to Maya/MCP."""

    id: str
    name: str
    arguments: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class LLMMessage:
    """One provider-neutral conversation message."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()


@dataclass(frozen=True)
class LLMToolDefinition:
    """Tool schema offered to a model; this contract never executes it."""

    name: str
    description: str
    parameters: JsonObject


@dataclass(frozen=True)
class LLMRequest:
    """A single model request assembled by Maya."""

    messages: tuple[LLMMessage, ...]
    tools: tuple[LLMToolDefinition, ...] = ()
    tool_choice: Literal["auto", "none", "required"] = "auto"
    temperature: float | None = None
    max_tokens: int | None = None
    conversation_id: str | int | None = None


@dataclass(frozen=True)
class LLMTextDelta:
    text: str
    replace: bool = False


@dataclass(frozen=True)
class LLMToolCallDelta:
    """Partial tool-call data during streaming; fields may arrive incrementally."""

    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class LLMCompleted:
    """Marks the end of a model response, optionally with a provider-neutral reason."""

    finish_reason: str | None = None


@dataclass(frozen=True)
class LLMConversation:
    """Provider-issued conversation identifier, when a backend owns chat state."""

    conversation_id: str | int


@dataclass(frozen=True)
class LLMState:
    """User-facing provider activity such as thinking or running a tool."""

    state: str
    detail: str = ""


LLMEvent: TypeAlias = (
    LLMTextDelta
    | LLMToolCallDelta
    | LLMUsage
    | LLMCompleted
    | LLMConversation
    | LLMState
)


@dataclass(frozen=True)
class LLMCapabilities:
    streaming: bool = True
    tool_calls: bool = False


class LLMProviderError(Exception):
    """Normalized provider failure suitable for handling by Maya."""

    def __init__(
        self,
        code: LLMErrorCode,
        message: str,
        *,
        provider: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.retryable = retryable


@runtime_checkable
class LLMProvider(Protocol):
    """Synchronous streaming provider contract, consumed by Maya workers."""

    name: str
    capabilities: LLMCapabilities

    def stream(self, request: LLMRequest) -> Iterator[LLMEvent]:
        """Yield normalized response events; raise LLMProviderError on failure."""
        ...

    def close(self) -> None:
        """Release provider resources, if any."""
        ...
