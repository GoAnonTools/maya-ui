import unittest

from backend.memory.models import MemoryCategory, MemoryContext, MemoryItem, MemorySource


class MemoryModelTests(unittest.TestCase):
    def test_memory_item_is_immutable_and_typed(self):
        item = MemoryItem(
            id="item-1",
            category=MemoryCategory.PREFERENCE,
            content="Prefers concise answers",
            source=MemorySource.USER_REQUESTED,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        self.assertEqual(item.category.value, "preference")
        with self.assertRaises((AttributeError, TypeError)):
            item.content = "changed"

    def test_empty_context(self):
        context = MemoryContext.empty()
        self.assertEqual(context.items, ())
        self.assertEqual(context.text, "")
        self.assertFalse(context.truncated)


if __name__ == "__main__":
    unittest.main()
