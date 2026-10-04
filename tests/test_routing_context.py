import unittest
from dataclasses import FrozenInstanceError

from backend.core.routing.context import (
    NetworkPolicy,
    PrivacyMode,
    RoutingContext,
    ToolPolicy,
)


class RoutingContextTests(unittest.TestCase):
    def test_context_stores_provider_neutral_metadata(self):
        context = RoutingContext(
            request_id="request-1",
            session_id="session-1",
            conversation_id="conversation-1",
            intent_classification="repository_analysis",
            required_capabilities={"coding", "repository_access"},
            privacy_mode=PrivacyMode.SENSITIVE,
            network_policy=NetworkPolicy.ALLOWED,
            tool_policy=ToolPolicy.APPROVAL_REQUIRED,
            user_preference_mode="balanced",
            external_processing_allowed=True,
            offline_processing_allowed=False,
        )

        self.assertEqual(context.required_capabilities, frozenset({"coding", "repository_access"}))
        self.assertEqual(context.intent_classification, "repository_analysis")
        self.assertEqual(context.privacy_mode, PrivacyMode.SENSITIVE)
        self.assertEqual(context.network_policy, NetworkPolicy.ALLOWED)
        self.assertEqual(context.tool_policy, ToolPolicy.APPROVAL_REQUIRED)
        self.assertTrue(context.external_processing_allowed)
        self.assertFalse(context.offline_processing_allowed)

    def test_context_is_immutable(self):
        context = RoutingContext(
            request_id="request-1",
            session_id="session-1",
            conversation_id=None,
            intent_classification="conversation",
        )

        with self.assertRaises(FrozenInstanceError):
            context.intent_classification = "coding"

    def test_defaults_are_provider_independent(self):
        context = RoutingContext(
            request_id="request-1",
            session_id="session-1",
            conversation_id=42,
            intent_classification="conversation",
        )

        self.assertEqual(context.privacy_mode, PrivacyMode.STANDARD)
        self.assertEqual(context.network_policy, NetworkPolicy.ALLOWED)
        self.assertEqual(context.tool_policy, ToolPolicy.DISALLOWED)
        self.assertEqual(context.user_preference_mode, "default")
        self.assertTrue(context.external_processing_allowed)
        self.assertTrue(context.offline_processing_allowed)

    def test_empty_identifiers_and_classification_are_rejected(self):
        base = {
            "request_id": "request-1",
            "session_id": "session-1",
            "conversation_id": None,
            "intent_classification": "conversation",
        }
        for field_name in ("request_id", "session_id", "intent_classification"):
            values = dict(base)
            values[field_name] = ""
            with self.subTest(field_name=field_name):
                with self.assertRaises(ValueError):
                    RoutingContext(**values)


if __name__ == "__main__":
    unittest.main()
