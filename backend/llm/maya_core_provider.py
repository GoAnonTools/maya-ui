"""Maya Core provider adapter."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from typing import Any, Callable

from ..core.maya_core_protocol import (
    MayaCoreRequest,
    MayaCoreTextDelta,
    decode_maya_core_event,
    to_llm_event,
)
from .base import (
    LLMCapabilities,
    LLMCompleted,
    LLMEvent,
    LLMProviderError,
    LLMRequest,
    LLMTextDelta,
)


class MayaCoreProvider:
    """Connect Maya UI to Maya Core streaming API."""

    name = "maya_core"
    capabilities = LLMCapabilities(
        streaming=True,
        tool_calls=False,
    )

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: float = 120.0,
        *,
        session_id: str | None = None,
        opener: Callable[..., Any] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session_id = session_id
        self._opener = opener or urllib.request.urlopen

    def stream(
        self,
        request: LLMRequest,
    ) -> Iterator[LLMEvent]:

        message = self._extract_user_message(request)

        payload = json.dumps(
            MayaCoreRequest.from_llm_request(request, session_id=self.session_id).to_payload()
        ).encode("utf-8")

        http_request = urllib.request.Request(
            f"{self.base_url}/chat/stream",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )

        try:
            response = self._opener(
                http_request,
                timeout=self.timeout,
            )

            with response:
                completed = False
                event_name = None
                for raw_line in response:
                    line = raw_line.decode(
                        "utf-8",
                        errors="replace",
                    ).strip()

                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue

                    data = line[5:].strip()

                    if data == "[DONE]":
                        if not completed:
                            yield LLMCompleted()
                        break

                    event = self._decode_event(data, event_name)
                    event_name = None
                    if isinstance(event, LLMProviderError):
                        raise event
                    normalized = to_llm_event(event)
                    if isinstance(normalized, LLMCompleted):
                        completed = True
                    yield normalized

        except Exception as exc:
            raise LLMProviderError(
                "connection",
                "Maya Core unavailable",
                provider=self.name,
                retryable=True,
            ) from exc

    def close(self) -> None:
        pass

    @staticmethod
    def _decode_event(data: str, event_name: str | None):
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            if event_name in {"text", "text_delta", "delta"}:
                payload = {"type": "text_delta", "text": data}
            else:
                # Preserve compatibility with the original raw-text SSE
                # response emitted by early localhost Maya Core builds.
                return MayaCoreTextDelta(data)
        if not isinstance(payload, dict):
            raise ValueError("Maya Core SSE event must be a JSON object")
        if event_name and "type" not in payload and "event" not in payload:
            payload = {"type": event_name, **payload}
        return decode_maya_core_event(payload)

    @staticmethod
    def _extract_user_message(
        request: LLMRequest,
    ) -> str:
        for message in reversed(request.messages):
            if message.role == "user":
                return message.content

        raise LLMProviderError(
            "invalid_request",
            "No user message provided",
            provider="maya_core",
        )
