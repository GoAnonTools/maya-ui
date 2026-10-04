import json
import unittest

from backend.core.routing.models import (
    DelegationEvent,
    DelegationEventType,
    DelegationRequest,
    FallbackPolicy,
    ProviderRole,
    RoutingDecision,
    WorkerCapability,
)
from backend.core.routing.serialization import (
    delegation_event_from_dict,
    delegation_event_to_dict,
    delegation_request_from_dict,
    delegation_request_to_dict,
    fallback_policy_from_dict,
    fallback_policy_to_dict,
    routing_decision_from_dict,
    routing_decision_to_dict,
    worker_capability_from_dict,
    worker_capability_to_dict,
)


class RoutingSerializationTests(unittest.TestCase):
    def test_worker_capability_round_trip_preserves_immutable_fields(self):
        worker = WorkerCapability(
            provider_id="worker-1",
            role=ProviderRole.SPECIALIST,
            display_name="Worker",
            available=False,
            unavailable_reason="not configured",
            capabilities={"coding", "streaming"},
            max_context_tokens=4096,
        )

        restored = worker_capability_from_dict(worker_capability_to_dict(worker))

        self.assertEqual(restored, worker)
        self.assertIsInstance(restored.capabilities, frozenset)
        self.assertEqual(restored.role, ProviderRole.SPECIALIST)

    def test_fallback_and_decision_round_trip_preserves_enum_values(self):
        policy = FallbackPolicy(
            ordered_roles=(ProviderRole.OFFLINE_FALLBACK, ProviderRole.LEGACY_COMPATIBILITY),
            required_capabilities={"conversation"},
            require_user_approval=True,
        )
        decision = RoutingDecision(
            schema_version=1,
            request_id="request-1",
            session_id="session-1",
            conversation_id=None,
            intent="conversation",
            required_capabilities={"conversation"},
            privacy_mode="standard",
            network_policy="allowed",
            tool_policy="none",
            preferred_role=ProviderRole.CONVERSATIONAL,
            selected_role=ProviderRole.OFFLINE_FALLBACK,
            selected_provider_id="local_qwen",
            reason_code="fallback_offline",
            fallback_policy=policy,
        )

        restored_policy = fallback_policy_from_dict(fallback_policy_to_dict(policy))
        restored_decision = routing_decision_from_dict(routing_decision_to_dict(decision))

        self.assertEqual(restored_policy, policy)
        self.assertEqual(restored_decision, decision)
        self.assertEqual(restored_decision.selected_role, ProviderRole.OFFLINE_FALLBACK)
        self.assertEqual(
            restored_decision.fallback_policy.ordered_roles[1],
            ProviderRole.LEGACY_COMPATIBILITY,
        )

    def test_delegation_models_round_trip_and_event_payload_is_immutable(self):
        request = DelegationRequest(
            delegation_id="delegation-1",
            parent_request_id="request-1",
            session_id="session-1",
            conversation_id="conversation-1",
            worker_role=ProviderRole.SPECIALIST,
            worker_id="worker-1",
            task_summary="Analyze repository",
            required_capabilities={"coding"},
            allowed_operations={"read"},
        )
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
            payload={"percent": 50},
        )

        restored_request = delegation_request_from_dict(delegation_request_to_dict(request))
        restored_event = delegation_event_from_dict(delegation_event_to_dict(event))

        self.assertEqual(restored_request, request)
        self.assertEqual(restored_event, event)
        self.assertIsInstance(restored_event.payload, type(event.payload))
        self.assertEqual(restored_event.event_type, DelegationEventType.PROGRESS)

    def test_serialized_values_are_json_compatible(self):
        event = DelegationEvent(
            schema_version=1,
            event_id="event-1",
            event_type=DelegationEventType.COMPLETED,
            request_id="request-1",
            session_id="session-1",
            conversation_id=None,
            delegation_id="delegation-1",
            sequence=2,
            timestamp="2026-10-04T12:00:00Z",
            payload={"items": [1, "done"]},
        )

        json.dumps(delegation_event_to_dict(event))

    def test_invalid_payloads_and_missing_required_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            worker_capability_from_dict({"provider_id": "worker-1"})
        with self.assertRaises(ValueError):
            fallback_policy_from_dict({"ordered_roles": ["not-a-role"]})
        with self.assertRaises(ValueError):
            delegation_event_from_dict(
                {
                    "schema_version": 1,
                    "event_id": "event-1",
                    "event_type": "not-an-event",
                    "request_id": "request-1",
                    "session_id": "session-1",
                    "delegation_id": "delegation-1",
                    "sequence": 1,
                    "timestamp": "now",
                }
            )
        with self.assertRaises(ValueError):
            delegation_event_from_dict({"event_id": "event-1"})

    def test_optional_fields_use_model_defaults(self):
        worker = worker_capability_from_dict(
            {
                "provider_id": "worker-1",
                "role": "conversational",
                "display_name": "Worker",
            }
        )
        request = delegation_request_from_dict(
            {
                "delegation_id": "delegation-1",
                "parent_request_id": "request-1",
                "session_id": "session-1",
                "worker_role": "specialist",
                "worker_id": "worker-1",
                "task_summary": "Task",
            }
        )

        self.assertTrue(worker.available)
        self.assertEqual(request.approval_required, True)
        self.assertIsNone(request.workspace)


if __name__ == "__main__":
    unittest.main()
