"""Storage contract and storage-specific errors for Maya memory."""

from __future__ import annotations

from typing import Protocol

from .models import MemoryCategory, MemoryItem, MemorySource


class MemoryStoreError(RuntimeError):
    """Base exception for local memory storage failures."""


class UnsupportedSchemaVersionError(MemoryStoreError):
    """Raised when a database was created by a newer memory implementation."""


class MemoryStore(Protocol):
    def add(self, item: MemoryItem) -> MemoryItem: ...

    def get(self, memory_id: str) -> MemoryItem | None: ...

    def search(self, query: str, *, limit: int) -> list[MemoryItem]: ...

    def list_items(self) -> list[MemoryItem]: ...

    def delete(self, memory_id: str) -> bool: ...

    def delete_all(self) -> int: ...

    def purge_expired(self, *, now: str) -> int: ...

    def close(self) -> None: ...
