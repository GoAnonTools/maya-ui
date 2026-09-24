import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.memory.models import MemoryCategory, MemoryItem, MemorySource
from backend.memory.sqlite_store import SQLiteMemoryStore, utc_now
from backend.memory.store import MemoryStoreError, UnsupportedSchemaVersionError


def make_item(item_id, content, category=MemoryCategory.OTHER, updated_at=None, expires_at=None):
    timestamp = updated_at or utc_now()
    return MemoryItem(
        id=item_id,
        category=category,
        content=content,
        source=MemorySource.USER_REQUESTED,
        created_at=timestamp,
        updated_at=timestamp,
        expires_at=expires_at,
    )


class SQLiteMemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "memory" / "memory.sqlite3"
        self.store = SQLiteMemoryStore(self.path)

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_schema_version_and_private_file_permissions(self):
        self.assertEqual(sqlite3.connect(self.path).execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_add_get_list_delete_and_clear(self):
        item = make_item("a", "Uses a standing desk", MemoryCategory.PREFERENCE)
        self.assertEqual(self.store.add(item), item)
        self.assertEqual(self.store.get("a"), item)
        self.assertEqual(self.store.list_items(), [item])
        self.assertTrue(self.store.delete("a"))
        self.assertFalse(self.store.delete("a"))
        self.store.add(make_item("b", "Current project is Maya"))
        self.store.add(make_item("c", "Likes green tea"))
        self.assertEqual(self.store.delete_all(), 2)
        self.assertEqual(self.store.list_items(), [])

    def test_data_persists_after_reopening(self):
        item = make_item("persisted", "Prefers short responses")
        self.store.add(item)
        self.store.close()
        self.store = SQLiteMemoryStore(self.path)
        self.assertEqual(self.store.get("persisted"), item)

    def test_search_is_lexical_ranked_and_bounded(self):
        self.store.add(make_item("one", "Maya project uses Python", updated_at="2026-01-01T00:00:00+00:00"))
        self.store.add(make_item("two", "Maya project uses Python and SQLite", updated_at="2026-01-02T00:00:00+00:00"))
        self.store.add(make_item("three", "Prefers concise answers", updated_at="2026-01-03T00:00:00+00:00"))
        self.assertEqual([item.id for item in self.store.search("Maya Python SQLite", limit=1)], ["two"])
        self.assertEqual(self.store.search("unrelated", limit=10), [])
        self.assertEqual(self.store.search("Maya", limit=0), [])

    def test_expired_items_are_hidden_and_purged(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(timespec="seconds")
        self.store.add(make_item("expired", "Old fact about Maya", expires_at=past))
        self.store.add(make_item("current", "Current fact about Maya", expires_at=future))
        self.assertEqual([item.id for item in self.store.search("Maya", limit=10)], ["current"])
        self.assertEqual(self.store.purge_expired(now=utc_now()), 1)
        self.assertIsNone(self.store.get("expired"))

    def test_rejects_oversized_content_using_schema_constraint(self):
        item = make_item("large", "x" * 1001)
        with self.assertRaises(MemoryStoreError):
            self.store.add(item)

    def test_rejects_database_from_newer_schema(self):
        self.store.close()
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA user_version = 2")
        connection.close()
        with self.assertRaises(UnsupportedSchemaVersionError):
            SQLiteMemoryStore(self.path)


if __name__ == "__main__":
    unittest.main()
