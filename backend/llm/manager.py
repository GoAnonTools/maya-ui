"""Maya-owned active provider selection and request forwarding."""

from __future__ import annotations

from collections.abc import Iterator
from threading import RLock

from .base import LLMCapabilities, LLMEvent, LLMProviderError, LLMRequest
from .registry import ProviderRegistry, ProviderStatus


class ProviderManager:
    """Selects a registered provider and forwards requests to it."""

    def __init__(self, registry: ProviderRegistry, default_provider_name: str):
        self._registry = registry
        self._lock = RLock()
        self._active_provider_name: str | None = None
        self.select(default_provider_name)

    @property
    def registry(self) -> ProviderRegistry:
        return self._registry

    @property
    def current_provider_name(self) -> str:
        with self._lock:
            assert self._active_provider_name is not None
            return self._active_provider_name

    @property
    def name(self) -> str:
        """Expose the active provider name for generic LLM worker logging."""
        return self.current_provider_name

    @property
    def current_provider_display_name(self) -> str:
        return self._registry.status(self.current_provider_name).display_name or self.current_provider_name

    @property
    def capabilities(self) -> LLMCapabilities:
        return self._registry.get(self.current_provider_name).capabilities

    @property
    def available(self) -> bool:
        return self.availability().available

    @property
    def provider_names(self) -> tuple[str, ...]:
        return self._registry.names()

    def availability(self, name: str | None = None) -> ProviderStatus:
        return self._registry.status(name if name is not None else self.current_provider_name)

    def select(self, name: str) -> None:
        if not self._registry.contains(name):
            raise LLMProviderError("provider", f"Unknown provider: {name}", provider=name)
        status = self._registry.status(name)
        if not status.available:
            detail = f": {status.reason}" if status.reason else ""
            raise LLMProviderError("provider", f"Provider unavailable: {name}{detail}", provider=name)
        with self._lock:
            self._active_provider_name = name

    def stream(self, request: LLMRequest) -> Iterator[LLMEvent]:
        _, provider = self._selected_provider()
        yield from provider.stream(request)

    def submit(self, request: LLMRequest) -> Iterator[LLMEvent]:
        """Alias for stream, for callers that name model work as submission."""
        return self.stream(request)

    def close(self) -> None:
        seen: set[int] = set()
        for name in self._registry.names():
            provider = self._registry.get(name)
            if id(provider) not in seen:
                seen.add(id(provider))
                provider.close()

    def _selected_provider(self):
        with self._lock:
            name = self._active_provider_name
        if name is None:
            raise LLMProviderError("provider", "No active provider selected")
        status = self._registry.status(name)
        if not status.available:
            detail = f": {status.reason}" if status.reason else ""
            raise LLMProviderError("provider", f"Provider unavailable: {name}{detail}", provider=name)
        return name, self._registry.get(name)
