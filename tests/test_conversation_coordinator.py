import unittest

from backend.conversation import ConversationCoordinator
from backend.llm import LLMMessage, LLMRequest, LLMToolDefinition


class ConversationCoordinatorTests(unittest.TestCase):
    def test_creates_stable_session_and_provider_neutral_request(self):
        coordinator = ConversationCoordinator(session_id="session-1", conversation_id="conversation-1")

        prompt, request = coordinator.prepare_request(
            behaviour_instruction="Answer briefly",
            language_instruction="Use English",
            memory_context="A saved fact",
            user_text="What time is it?",
            tools=(LLMToolDefinition("clock", "Read the clock", {"type": "object"}),),
            tool_choice="auto",
            temperature=0.2,
            max_tokens=64,
        )

        self.assertEqual(coordinator.session_id, "session-1")
        self.assertEqual(coordinator.conversation_id, "conversation-1")
        self.assertEqual(request.session_id, "session-1")
        self.assertEqual(request.conversation_id, "conversation-1")
        self.assertEqual(request.messages, (LLMMessage(role="user", content=prompt),))
        self.assertEqual(request.tools[0].name, "clock")
        self.assertEqual(request.temperature, 0.2)
        self.assertEqual(request.max_tokens, 64)
        self.assertIn("What time is it?", prompt)

    def test_session_is_generated_and_conversation_can_be_updated(self):
        coordinator = ConversationCoordinator()
        first_session = coordinator.session_id

        coordinator.set_conversation_id(42)
        request = coordinator.create_request("Hello")
        coordinator.reset_conversation()

        self.assertTrue(first_session)
        self.assertEqual(request.conversation_id, 42)
        self.assertEqual(coordinator.conversation_id, None)
        self.assertEqual(coordinator.session_id, first_session)

    def test_server_identifiers_update_coordinator_state(self):
        coordinator = ConversationCoordinator(session_id="client-session")

        coordinator.set_session_id("server-session")
        coordinator.set_conversation_id("server-conversation")

        request = coordinator.create_request("Continue")

        self.assertEqual(request.session_id, "server-session")
        self.assertEqual(request.conversation_id, "server-conversation")


if __name__ == "__main__":
    unittest.main()
