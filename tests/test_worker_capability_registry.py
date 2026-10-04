import unittest

from backend.core.routing import ProviderRole, WorkerCapability
from backend.core.routing.registry import WorkerCapabilityRegistry


class WorkerCapabilityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = WorkerCapabilityRegistry()
        self.conversational = WorkerCapability(
            provider_id="ministral_14b",
            role=ProviderRole.CONVERSATIONAL,
            display_name="Ministral",
        )
        self.specialist = WorkerCapability(
            provider_id="lightning_hermes",
            role=ProviderRole.SPECIALIST,
            display_name="Lightning/Hermes",
            available=False,
            unavailable_reason="not configured",
        )

    def test_register_and_retrieve_by_provider_id(self):
        self.registry.register(self.conversational)

        self.assertIs(self.registry.get("ministral_14b"), self.conversational)
        self.assertIsNone(self.registry.get("missing"))

    def test_duplicate_provider_id_is_rejected(self):
        self.registry.register(self.conversational)

        with self.assertRaises(ValueError):
            self.registry.register(
                WorkerCapability(
                    provider_id="ministral_14b",
                    role=ProviderRole.CONVERSATIONAL,
                    display_name="Another worker",
                )
            )

    def test_list_available_excludes_unavailable_workers(self):
        self.registry.register(self.conversational)
        self.registry.register(self.specialist)

        self.assertEqual(self.registry.list_available(), (self.conversational,))

    def test_update_availability_replaces_immutable_snapshot(self):
        self.registry.register(self.conversational)

        unavailable = self.registry.update_availability(
            "ministral_14b",
            False,
            unavailable_reason="health check failed",
        )

        self.assertFalse(unavailable.available)
        self.assertEqual(unavailable.unavailable_reason, "health check failed")
        self.assertIsNot(unavailable, self.conversational)
        self.assertEqual(self.registry.list_available(), ())

        recovered = self.registry.update_availability("ministral_14b", True)
        self.assertTrue(recovered.available)
        self.assertIsNone(recovered.unavailable_reason)
        self.assertEqual(self.registry.list_available(), (recovered,))

    def test_update_unknown_provider_id_is_rejected(self):
        with self.assertRaises(KeyError):
            self.registry.update_availability("missing", False)


if __name__ == "__main__":
    unittest.main()
