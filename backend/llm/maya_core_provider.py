"""Maya Core provider adapter."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator

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
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def stream(
        self,
        request: LLMRequest,
    ) -> Iterator[LLMEvent]:

        message = self._extract_user_message(request)

        payload = json.dumps(
            {
                "message": message,
            }
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
            response = urllib.request.urlopen(
                http_request,
                timeout=self.timeout,
            )

            with response:
                for raw_line in response:
                    line = raw_line.decode(
                        "utf-8",
                        errors="replace",
                    ).strip()

                    if not line.startswith("data:"):
                        continue

                    data = line[5:].strip()

                    if data == "[DONE]":
                        yield LLMCompleted()
                        break

                    yield LLMTextDelta(
                        data
                    )

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
