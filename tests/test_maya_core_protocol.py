import json
import unittest

from backend.core.maya_core_protocol import (
    MayaCoreRequest,
    MayaCoreSession,
    MayaCoreTextDelta,
    decode_maya_core_event,
    to_llm_event,
)
from backend.llm import (
    LLMCompleted,
    LLMConversation,
    LLMMessage,
    LLMRequest,
    LLMSession,
    LLMTextDelta,
    LLMToolCall,
    LLMToolDefinition,
)


class MayaCoreProtocolTests(unittest.TestCase):
    def test_request_contains_full_llm_request_and_legacy_message(self):
        request = LLMRequest(
            messages=(
                LLMMessage(role="system", content="Be concise"),
                LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=(LLMToolCall("call-1", "open_application", {"name": "Firefox"}),),
                ),
                LLMMessage(role="user", content="Open Firefox"),
            ),
            tools=(LLMToolDefinition("open_application", "Open an application", {"type": "object"}),),
            tool_choice="required",
            temperature=0.2,
            max_tokens=128,
            conversation_id="conversation-1",
            session_id="session-1",
        )

        payload = MayaCoreRequest.from_llm_request(request).to_payload()

        self.assertEqual(payload["protocol_version"], 1)
        self.assertEqual(payload["message"], "Open Firefox")
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "Be concise"})
        self.assertEqual(payload["messages"][1]["tool_calls"][0]["name"], "open_application")
        self.assertEqual(payload["tools"][0]["name"], "open_application")
        self.assertEqual(payload["tool_choice"], "required")
        self.assertEqual(payload["conversation_id"], "conversation-1")
        self.assertEqual(payload["session_id"], "session-1")

    def test_structured_response_events_map_to_provider_events(self):
        self.assertEqual(
            to_llm_event(decode_maya_core_event({"type": "text_delta", "text": "Hello"})),
            LLMTextDelta("Hello"),
        )
        self.assertEqual(
            to_llm_event(decode_maya_core_event({"type": "conversation", "conversation_id": "c-1"})),
            LLMConversation("c-1"),
        )
        self.assertEqual(
            to_llm_event(decode_maya_core_event({"type": "session", "session_id": "s-1"})),
            LLMSession("s-1"),
        )
        self.assertEqual(
            to_llm_event(decode_maya_core_event({"type": "completed", "finish_reason": "stop"})),
            LLMCompleted("stop"),
        )

    def test_nested_data_envelope_is_supported(self):
        event = decode_maya_core_event({"type": "text_delta", "data": {"text": "Nested"}})

        self.assertEqual(event, MayaCoreTextDelta("Nested"))

    def test_protocol_payload_is_json_serializable(self):
        request = MayaCoreRequest.from_llm_request(
            LLMRequest(messages=(LLMMessage(role="user", content="Hi"),)),
            session_id="session-2",
        )

        self.assertIn('"session_id": "session-2"', json.dumps(request.to_payload()))
        self.assertIsInstance(MayaCoreSession("session-2"), MayaCoreSession)


if __name__ == "__main__":
    unittest.main()
