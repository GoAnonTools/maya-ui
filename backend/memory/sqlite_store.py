"""SQLite-backed local memory store with deterministic lexical retrieval."""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .models import MemoryCategory, MemoryItem, MemorySource
from .store import MemoryStoreError, UnsupportedSchemaVersionError


SCHEMA_VERSION = 1
_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(value) if token}


class SQLiteMemoryStore:
    """Small local store. Calls on one instance are serialized by a lock."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        try:
            self._connection = sqlite3.connect(self.path, timeout=5.0)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA journal_mode = WAL")
            if self.path.exists():
                os.chmod(self.path, 0o600)
            self._initialize_schema()
        except (OSError, sqlite3.Error, UnsupportedSchemaVersionError) as exc:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            if isinstance(exc, UnsupportedSchemaVersionError):
                raise
            raise MemoryStoreError(f"could not initialize memory database: {exc}") from exc

    def _initialize_schema(self) -> None:
        with self._lock:
            version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise UnsupportedSchemaVersionError(
                    f"memory database version {version} is newer than supported version {SCHEMA_VERSION}"
                )
            if version == SCHEMA_VERSION:
                return
            self._connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE memory_items (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL CHECK (
                        category IN ('preference', 'profile', 'project', 'other')
                    ),
                    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 1000),
                    source TEXT NOT NULL CHECK (
                        source IN ('user_requested', 'user_confirmed')
                    ),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                );
                CREATE INDEX memory_items_category_idx ON memory_items(category);
                CREATE INDEX memory_items_expiry_idx ON memory_items(expires_at);
                PRAGMA user_version = 1;
                COMMIT;
                """
            )
            os.chmod(self.path, 0o600)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            category=MemoryCategory(row["category"]),
            content=row["content"],
            source=MemorySource(row["source"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
        )

    def add(self, item: MemoryItem) -> MemoryItem:
        with self._lock:
            try:
                self._connection.execute(
                    """INSERT INTO memory_items
                       (id, category, content, source, created_at, updated_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item.id,
                        item.category.value,
                        item.content,
                        item.source.value,
                        item.created_at,
                        item.updated_at,
                        item.expires_at,
                    ),
                )
                self._connection.commit()
                return item
            except sqlite3.Error as exc:
                self._connection.rollback()
                raise MemoryStoreError(f"could not add memory item: {exc}") from exc

    def get(self, memory_id: str) -> MemoryItem | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM memory_items WHERE id = ?", (memory_id,)
            ).fetchone()
            return None if row is None else self._from_row(row)

    def search(self, query: str, *, limit: int) -> list[MemoryItem]:
        if limit <= 0:
            return []
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        now = utc_now()
        with self._lock:
            rows = self._connection.execute(
                """SELECT * FROM memory_items
                   WHERE expires_at IS NULL OR expires_at > ?""",
                (now,),
            ).fetchall()
        ranked: list[tuple[int, str, MemoryItem]] = []
        for row in rows:
            item = self._from_row(row)
            item_tokens = _tokens(f"{item.category.value} {item.content}")
            overlap = len(query_tokens & item_tokens)
            if overlap:
                ranked.append((overlap, item.updated_at, item))
        ranked.sort(key=lambda match: match[2].id)
        ranked.sort(key=lambda match: match[1], reverse=True)
        ranked.sort(key=lambda match: match[0], reverse=True)
        return [item for _, _, item in ranked[:limit]]

    def list_items(self) -> list[MemoryItem]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM memory_items ORDER BY updated_at DESC, id ASC"
            ).fetchall()
            return [self._from_row(row) for row in rows]

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM memory_items WHERE id = ?", (memory_id,)
            )
            self._connection.commit()
            return cursor.rowcount > 0

    def delete_all(self) -> int:
        with self._lock:
            cursor = self._connection.execute("DELETE FROM memory_items")
            self._connection.commit()
            return cursor.rowcount

    def purge_expired(self, *, now: str) -> int:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM memory_items WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            )
            self._connection.commit()
            return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            self._connection.close()
