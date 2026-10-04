import unittest

from backend.core.routing import ProviderRole, WorkerCapabilityRegistry
from backend.core.routing.catalog import DEFAULT_PROVIDER_IDS, WorkerCatalog


class WorkerCatalogTests(unittest.TestCase):
    def test_default_catalog_populates_metadata_only(self):
        registry = WorkerCapabilityRegistry()

        WorkerCatalog().populate(registry)

        workers = registry.list_available_workers()
        self.assertEqual(
            [worker.provider_id for worker in workers],
            list(DEFAULT_PROVIDER_IDS.values()),
        )
        self.assertEqual(
            [worker.role for worker in workers],
            [
                ProviderRole.CONVERSATIONAL,
                ProviderRole.SPECIALIST,
                ProviderRole.OFFLINE_FALLBACK,
                ProviderRole.LEGACY_COMPATIBILITY,
            ],
        )
        self.assertEqual(registry.get_worker("ministral_14b").display_name, "Ministral")

    def test_provider_ids_can_be_configured_without_changing_roles(self):
        ids = {
            "conversational": "daily_worker",
            "specialist": "expert_worker",
            "offline_fallback": "local_worker",
            "legacy_compatibility": "compat_worker",
        }
        registry = WorkerCapabilityRegistry()

        WorkerCatalog(provider_ids=ids).populate(registry)

        self.assertIsNone(registry.get_worker("ministral_14b"))
        self.assertEqual(registry.get_worker("daily_worker").role, ProviderRole.CONVERSATIONAL)
        self.assertEqual(registry.get_worker("expert_worker").role, ProviderRole.SPECIALIST)

    def test_catalog_rejects_incomplete_or_duplicate_provider_ids(self):
        with self.assertRaises(ValueError):
            WorkerCatalog(provider_ids={"conversational": "daily_worker"})

        duplicate_ids = dict(DEFAULT_PROVIDER_IDS)
        duplicate_ids["specialist"] = duplicate_ids["conversational"]
        with self.assertRaises(ValueError):
            WorkerCatalog(provider_ids=duplicate_ids)

    def test_populate_rejects_non_registry_objects(self):
        with self.assertRaises(TypeError):
            WorkerCatalog().populate(object())


if __name__ == "__main__":
    unittest.main()
