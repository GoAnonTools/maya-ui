"""Typed values used by Maya's local memory layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MemoryCategory(str, Enum):
    PREFERENCE = "preference"
    PROFILE = "profile"
    PROJECT = "project"
    OTHER = "other"


class MemorySource(str, Enum):
    USER_REQUESTED = "user_requested"
    USER_CONFIRMED = "user_confirmed"


@dataclass(frozen=True, slots=True)
class MemoryItem:
    id: str
    category: MemoryCategory
    content: str
    source: MemorySource
    created_at: str
    updated_at: str
    expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryContext:
    """Bounded memory selected for a future assistant request."""

    items: tuple[MemoryItem, ...] = ()
    text: str = ""
    truncated: bool = False

    @classmethod
    def empty(cls) -> "MemoryContext":
        return cls()
