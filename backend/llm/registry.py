"""Registry of LLM providers and their selectable availability state."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .base import LLMProvider


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    reason: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class _ProviderEntry:
    provider: LLMProvider
    available: bool
    reason: str | None


class ProviderRegistry:
    """Stores provider implementations without choosing Maya's active one."""

    def __init__(self):
        self._entries: dict[str, _ProviderEntry] = {}
        self._lock = RLock()

    def register(
        self,
        provider: LLMProvider,
        *,
        available: bool = True,
        reason: str | None = None,
    ) -> None:
        name = provider.name
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Provider name must be a non-empty string")
        with self._lock:
            if name in self._entries:
                raise ValueError(f"Provider already registered: {name}")
            self._entries[name] = _ProviderEntry(provider, bool(available), reason)

    def get(self, name: str) -> LLMProvider:
        with self._lock:
            try:
                return self._entries[name].provider
            except KeyError as exc:
                raise KeyError(f"Unknown provider: {name}") from exc

    def contains(self, name: str) -> bool:
        with self._lock:
            return name in self._entries

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._entries)

    def status(self, name: str) -> ProviderStatus:
        with self._lock:
            try:
                entry = self._entries[name]
            except KeyError as exc:
                raise KeyError(f"Unknown provider: {name}") from exc
            return ProviderStatus(
                name,
                entry.available,
                entry.reason,
                getattr(entry.provider, "display_name", name),
            )

    def set_available(self, name: str, available: bool, reason: str | None = None) -> ProviderStatus:
        with self._lock:
            try:
                entry = self._entries[name]
            except KeyError as exc:
                raise KeyError(f"Unknown provider: {name}") from exc
            updated = _ProviderEntry(entry.provider, bool(available), reason if not available else None)
            self._entries[name] = updated
            return ProviderStatus(
                name,
                updated.available,
                updated.reason,
                getattr(updated.provider, "display_name", name),
            )

    def statuses(self) -> tuple[ProviderStatus, ...]:
        with self._lock:
            return tuple(
                ProviderStatus(
                    name,
                    entry.available,
                    entry.reason,
                    getattr(entry.provider, "display_name", name),
                )
                for name, entry in self._entries.items()
            )
