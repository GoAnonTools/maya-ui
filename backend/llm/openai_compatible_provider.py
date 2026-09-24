"""Streaming adapter for OpenAI-compatible chat completion endpoints."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from .base import (
    LLMCapabilities,
    LLMCompleted,
    LLMEvent,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    LLMTextDelta,
    LLMToolCallDelta,
    LLMUsage,
)


CredentialResolver = Callable[[str], str | None]


class OpenAICompatibleProvider:
    """Streaming adapter for Maya's LLMProvider contract.

    credential_ref is an opaque secret-store lookup key. The resolved
    credential is used only in the outgoing Authorization header and is
    never retained on the provider instance.
    """

    name = "openai_compatible"
    capabilities = LLMCapabilities(streaming=True, tool_calls=True)

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        credential_ref: str | None = None,
        credential_resolver: CredentialResolver | None = None,
        timeout: float = 120.0,
        opener=None,
        provider_name: str | None = None,
        display_name: str | None = None,
    ) -> None:
        self.name = provider_name or type(self).name
        self.display_name = display_name or self.name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.credential_ref = credential_ref
        self._credential_resolver = credential_resolver
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def stream(self, request: LLMRequest) -> Iterator[LLMEvent]:
        if not self.base_url:
            raise LLMProviderError("invalid_request", "Provider base URL is not configured", provider=self.name)
        if not self.model:
            raise LLMProviderError("invalid_request", "Provider model is not configured", provider=self.name)

        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        credential = self._resolve_credential()
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        payload = self._payload(request)
        http_request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            response = self._opener(http_request, timeout=self.timeout)
            with response:
                yield from self._read_events(response)
        except urllib.error.HTTPError as exc:
            code, retryable = self._http_error(exc.code)
            raise LLMProviderError(
                code,
                f"OpenAI-compatible request failed (HTTP {exc.code})",
                provider=self.name,
                retryable=retryable,
            ) from exc
        except TimeoutError as exc:
            raise LLMProviderError(
                "timeout",
                "OpenAI-compatible request timed out",
                provider=self.name,
                retryable=True,
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise LLMProviderError(
                    "timeout",
                    "OpenAI-compatible request timed out",
                    provider=self.name,
                    retryable=True,
                ) from exc
            raise LLMProviderError(
                "connection",
                "OpenAI-compatible provider unavailable",
                provider=self.name,
                retryable=True,
            ) from exc
        except OSError as exc:
            raise LLMProviderError(
                "connection",
                "OpenAI-compatible provider unavailable",
                provider=self.name,
                retryable=True,
            ) from exc

    def _resolve_credential(self) -> str | None:
        if self.credential_ref is None:
            return None
        if self._credential_resolver is None:
            raise LLMProviderError(
                "authentication",
                "Provider credential is not available",
                provider=self.name,
            )
        try:
            credential = self._credential_resolver(self.credential_ref)
        except Exception as exc:
            raise LLMProviderError(
                "authentication",
                "Provider credential is not available",
                provider=self.name,
            ) from exc
        if not credential:
            raise LLMProviderError(
                "authentication",
                "Provider credential is not available",
                provider=self.name,
            )
        return credential

    def _endpoint(self) -> str:
        base = self.base_url
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _payload(self, request: LLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message(message) for message in request.messages],
            "stream": True,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = [self._tool(tool) for tool in request.tools]
            payload["tool_choice"] = request.tool_choice
        return payload

    @classmethod
    def _message(cls, message: LLMMessage) -> dict[str, Any]:
        data: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.name is not None:
            data["name"] = message.name
        if message.tool_call_id is not None:
            data["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(cls._plain(call.arguments), separators=(",", ":")),
                    },
                }
                for call in message.tool_calls
            ]
        return data

    @classmethod
    def _tool(cls, tool) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": cls._plain(tool.parameters),
            },
        }

    @classmethod
    def _plain(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {key: cls._plain(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._plain(item) for item in value]
        return value

    def _read_events(self, response) -> Iterator[LLMEvent]:
        finish_reason = None
        completed = False
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
            line = line.rstrip("\r\n")
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                yield LLMCompleted(finish_reason)
                completed = True
                break
            try:
                chunk = json.loads(data)
            except (TypeError, ValueError) as exc:
                raise LLMProviderError(
                    "provider",
                    "Invalid OpenAI-compatible streaming response",
                    provider=self.name,
                ) from exc
            if not isinstance(chunk, dict):
                continue
            if chunk.get("error") is not None:
                raise LLMProviderError(
                    "provider",
                    "OpenAI-compatible provider returned an error",
                    provider=self.name,
                )

            usage = chunk.get("usage")
            if isinstance(usage, dict):
                yield LLMUsage(
                    self._integer(usage.get("prompt_tokens", usage.get("input_tokens"))),
                    self._integer(usage.get("completion_tokens", usage.get("output_tokens"))),
                )

            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta", {})
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str) and content:
                    yield LLMTextDelta(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"]:
                            yield LLMTextDelta(part["text"])
                tool_calls = delta.get("tool_calls")
                if isinstance(tool_calls, list):
                    for fallback_index, tool_call in enumerate(tool_calls):
                        event = self._tool_call_delta(tool_call, fallback_index)
                        if event is not None:
                            yield event
                legacy_call = delta.get("function_call")
                if isinstance(legacy_call, dict):
                    event = self._tool_call_delta({"index": 0, "function": legacy_call}, 0)
                    if event is not None:
                        yield event
            reason = choice.get("finish_reason")
            if isinstance(reason, str):
                finish_reason = reason

        if not completed:
            yield LLMCompleted(finish_reason)

    @staticmethod
    def _tool_call_delta(tool_call, fallback_index: int) -> LLMToolCallDelta | None:
        if not isinstance(tool_call, dict):
            return None
        function = tool_call.get("function")
        if not isinstance(function, dict):
            function = {}
        arguments = function.get("arguments", "")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, separators=(",", ":"))
        index = tool_call.get("index", fallback_index)
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = fallback_index
        call_id = tool_call.get("id")
        name = function.get("name")
        return LLMToolCallDelta(
            index=index,
            id=call_id if isinstance(call_id, str) else None,
            name=name if isinstance(name, str) else None,
            arguments_delta=arguments,
        )

    @staticmethod
    def _integer(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _http_error(status: int) -> tuple[str, bool]:
        if status in (401, 403):
            return "authentication", False
        if status == 429:
            return "rate_limit", True
        if status in (400, 404, 422):
            return "invalid_request", False
        return "provider", status >= 500

    def close(self) -> None:
        """No persistent transport resources are held between requests."""
