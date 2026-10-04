import unittest

from backend.core.routing.catalog import WorkerCatalog
from backend.core.routing.context import NetworkPolicy, RoutingContext
from backend.core.routing.models import FallbackPolicy, ProviderRole
from backend.core.routing.policy import RoutingPolicy, RoutingPolicyError
from backend.core.routing.registry import WorkerCapabilityRegistry


class RoutingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.registry = WorkerCapabilityRegistry()
        self.catalog = WorkerCatalog()
        self.catalog.populate(self.registry)
        self.policy = RoutingPolicy(self.catalog)

    def context(self, intent="conversation", **overrides):
        values = {
            "request_id": "request-1",
            "session_id": "session-1",
            "conversation_id": "conversation-1",
            "intent_classification": intent,
        }
        values.update(overrides)
        return RoutingContext(**values)

    def test_conversation_selects_conversational_worker(self):
        decision = self.policy.decide(self.context(), self.registry)

        self.assertEqual(decision.selected_role, ProviderRole.CONVERSATIONAL)
        self.assertEqual(decision.selected_provider_id, "ministral_14b")
        self.assertEqual(decision.reason_code, "preferred_conversational")

    def test_specialist_selects_specialist_worker(self):
        decision = self.policy.decide(
            self.context("repository_analysis", required_capabilities={"coding"}),
            self.registry,
        )

        self.assertEqual(decision.selected_role, ProviderRole.SPECIALIST)
        self.assertEqual(decision.selected_provider_id, "lightning_hermes")

    def test_offline_selects_offline_fallback(self):
        decision = self.policy.decide(
            self.context("conversation", network_policy=NetworkPolicy.DISALLOWED),
            self.registry,
        )

        self.assertEqual(decision.selected_role, ProviderRole.OFFLINE_FALLBACK)
        self.assertEqual(decision.selected_provider_id, "local_qwen")

    def test_unavailable_worker_follows_fallback_policy(self):
        self.registry.update_availability("ministral_14b", False, unavailable_reason="offline")
        fallback = FallbackPolicy(ordered_roles=(ProviderRole.LEGACY_COMPATIBILITY,))

        decision = self.policy.decide(self.context(), self.registry, fallback)

        self.assertEqual(decision.selected_role, ProviderRole.LEGACY_COMPATIBILITY)
        self.assertEqual(decision.selected_provider_id, "newelle")
        self.assertEqual(
            decision.reason_code,
            "fallback_legacy_compatibility_for_conversational",
        )

    def test_capability_mismatch_is_rejected(self):
        with self.assertRaises(RoutingPolicyError):
            self.policy.decide(
                self.context("repository_analysis", required_capabilities={"quantum_computing"}),
                self.registry,
            )

    def test_legacy_requires_explicit_fallback_or_request(self):
        fallback = FallbackPolicy(ordered_roles=(ProviderRole.LEGACY_COMPATIBILITY,))
        decision = self.policy.decide(
            self.context("legacy_compatibility"), self.registry, fallback
        )
        self.assertEqual(decision.selected_role, ProviderRole.LEGACY_COMPATIBILITY)


if __name__ == "__main__":
    unittest.main()
