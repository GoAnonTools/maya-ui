import unittest
from dataclasses import FrozenInstanceError

from backend.core.routing import (
    DelegationEvent,
    DelegationEventType,
    DelegationRequest,
    FallbackPolicy,
    ProviderRole,
    RoutingDecision,
    WorkerCapability,
)


class RoutingModelTests(unittest.TestCase):
    def test_worker_capability_is_immutable_and_normalizes_capabilities(self):
        capability = WorkerCapability(
            provider_id="ministral_14b",
            role=ProviderRole.CONVERSATIONAL,
            display_name="Ministral",
            capabilities={"conversation", "streaming"},
        )

        self.assertEqual(capability.capabilities, frozenset({"conversation", "streaming"}))
        with self.assertRaises(FrozenInstanceError):
            capability.available = False

    def test_routing_decision_contains_policy_and_selection(self):
        policy = FallbackPolicy(
            ordered_roles=(ProviderRole.OFFLINE_FALLBACK, ProviderRole.LEGACY_COMPATIBILITY),
            required_capabilities={"conversation"},
        )
        decision = RoutingDecision(
            schema_version=1,
            request_id="request-1",
            session_id="session-1",
            conversation_id="conversation-1",
            intent="conversation",
            required_capabilities={"conversation", "streaming"},
            privacy_mode="standard",
            network_policy="allowed",
            tool_policy="none",
            preferred_role=ProviderRole.CONVERSATIONAL,
            selected_role=ProviderRole.CONVERSATIONAL,
            selected_provider_id="ministral_14b",
            reason_code="normal_conversation",
            fallback_policy=policy,
        )

        self.assertEqual(decision.selected_provider_id, "ministral_14b")
        self.assertEqual(decision.fallback_policy.ordered_roles[0], ProviderRole.OFFLINE_FALLBACK)

    def test_delegation_request_normalizes_scope(self):
        request = DelegationRequest(
            delegation_id="delegation-1",
            parent_request_id="request-1",
            session_id="session-1",
            conversation_id="conversation-1",
            worker_role=ProviderRole.SPECIALIST,
            worker_id="lightning_hermes",
            task_summary="Analyze the repository",
            required_capabilities={"repository_access", "coding"},
            allowed_operations={"read", "write"},
        )

        self.assertEqual(request.required_capabilities, frozenset({"repository_access", "coding"}))
        self.assertEqual(request.allowed_operations, frozenset({"read", "write"}))
        self.assertTrue(request.approval_required)

    def test_delegation_event_payload_is_snapshot_and_event_type_is_typed(self):
        payload = {"percent": 25}
        event = DelegationEvent(
            schema_version=1,
            event_id="event-1",
            event_type=DelegationEventType.PROGRESS,
            request_id="request-1",
            session_id="session-1",
            conversation_id=None,
            delegation_id="delegation-1",
            sequence=1,
            timestamp="2026-10-04T12:00:00Z",
            payload=payload,
        )
        payload["percent"] = 100

        self.assertEqual(event.event_type.value, "delegation.progress")
        self.assertEqual(event.payload["percent"], 25)
        with self.assertRaises(TypeError):
            event.payload["status"] = "done"


if __name__ == "__main__":
    unittest.main()
