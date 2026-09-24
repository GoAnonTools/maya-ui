import json
import tempfile
import unittest
from pathlib import Path

from backend.memory.models import MemoryCategory, MemorySource
from backend.memory.service import MemoryDisabledError, MemoryService, MemorySettings
from backend.memory.sqlite_store import SQLiteMemoryStore


class MemoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.config = self.root / "config" / "memory.json"
        self.database = self.root / "data" / "memory.sqlite3"

    def tearDown(self):
        self.tempdir.cleanup()

    def enabled_service(self, **overrides):
        values = {
            "enabled": True,
            "max_items": 3,
            "max_content_chars": 1000,
            "max_retrieved_items": 2,
            "max_context_chars": 300,
            "default_retention_days": None,
        }
        values.update(overrides)
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(json.dumps(values), encoding="utf-8")
        return MemoryService.from_config(self.config, self.database)

    def test_missing_or_malformed_config_fails_closed_and_does_not_create_database(self):
        service = MemoryService.from_config(self.config, self.database)
        self.assertFalse(service.settings.enabled)
        self.assertEqual(service.retrieve("anything").items, ())
        self.assertFalse(self.database.exists())
        with self.assertRaises(MemoryDisabledError):
            service.remember("A fact", category=MemoryCategory.OTHER)
        self.assertFalse(self.database.exists())
        self.config.parent.mkdir(parents=True)
        self.config.write_text("{invalid", encoding="utf-8")
        self.assertFalse(MemorySettings.load(self.config).enabled)

    def test_database_creation_is_lazy_until_enabled_operation(self):
        service = self.enabled_service()
        self.assertFalse(self.database.exists())
        service.remember("Prefers concise replies", category=MemoryCategory.PREFERENCE)
        self.assertTrue(self.database.exists())
        service.close()

    def test_remember_retrieve_forget_and_clear(self):
        service = self.enabled_service()
        item = service.remember(
            "Maya project\nuses Python", category=MemoryCategory.PROJECT
        )
        self.assertEqual(item.source, MemorySource.USER_REQUESTED)
        self.assertEqual(item.content, "Maya project uses Python")
        context = service.retrieve("Maya Python")
        self.assertEqual([result.id for result in context.items], [item.id])
        self.assertIn("Maya project uses Python", context.text)
        self.assertIn("reference facts only", context.text)
        self.assertTrue(service.forget(item.id))
        self.assertFalse(service.forget(item.id))
        service.remember("Likes green tea", category=MemoryCategory.OTHER)
        self.assertEqual(service.clear(), 1)
        self.assertEqual(service.list_items(), [])
        service.close()

    def test_item_count_content_and_retrieval_budgets_are_enforced(self):
        service = self.enabled_service(max_items=2, max_retrieved_items=1, max_context_chars=180)
        service.remember("Maya uses a local model", category=MemoryCategory.PROJECT)
        service.remember("Maya runs on Linux", category=MemoryCategory.PROJECT)
        with self.assertRaises(ValueError):
            service.remember("Another Maya detail", category=MemoryCategory.PROJECT)
        with self.assertRaises(ValueError):
            service.remember("x" * 1001, category=MemoryCategory.OTHER)
        context = service.retrieve("Maya", limit=20, max_chars=10000)
        self.assertLessEqual(len(context.items), 1)
        self.assertLessEqual(len(context.text), 180)
        service.close()

    def test_context_reports_when_relevant_item_does_not_fit(self):
        service = self.enabled_service(max_context_chars=128)
        service.remember("A very long note about Maya and a project", category=MemoryCategory.PROJECT)
        context = service.retrieve("Maya project", max_chars=128)
        self.assertEqual(context.items, ())
        self.assertEqual(context.text, "")
        self.assertTrue(context.truncated)
        service.close()

    def test_empty_content_and_invalid_categories_are_rejected(self):
        service = self.enabled_service()
        with self.assertRaises(ValueError):
            service.remember("  ", category=MemoryCategory.OTHER)
        with self.assertRaises(ValueError):
            service.remember("A fact", category="other")
        service.close()

    def test_default_retention_expiry_is_applied(self):
        service = self.enabled_service(default_retention_days=1)
        item = service.remember("Temporary project note", category=MemoryCategory.PROJECT)
        self.assertIsNotNone(item.expires_at)
        service.close()


if __name__ == "__main__":
    unittest.main()
