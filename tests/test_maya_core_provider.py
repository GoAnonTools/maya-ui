import json
import unittest

from backend.llm import (
    LLMCompleted,
    LLMConversation,
    LLMMessage,
    LLMRequest,
    LLMSession,
    LLMState,
    LLMTextDelta,
    LLMToolCallDelta,
    LLMUsage,
)
from backend.llm.maya_core_provider import MayaCoreProvider


class FakeResponse:
    def __init__(self, lines):
        self.lines = [line.encode("utf-8") for line in lines]
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def __iter__(self):
        return iter(self.lines)


def sse(payload):
    return "data: " + json.dumps(payload, separators=(",", ":")) + "\n\n"


class MayaCoreProviderTests(unittest.TestCase):
    def test_sends_full_request_and_decodes_structured_stream(self):
        response = FakeResponse(
            [
                sse({"type": "session", "session_id": "session-1"}),
                sse({"type": "conversation", "conversation_id": "conversation-1"}),
                sse({"type": "state", "state": "thinking", "detail": "Generating"}),
                sse({"type": "text_delta", "text": "Hello"}),
                sse({"type": "tool_call_delta", "index": 0, "id": "call-1", "name": "lookup", "arguments_delta": "{"}),
                sse({"type": "usage", "input_tokens": 5, "output_tokens": 2}),
                sse({"type": "completed", "finish_reason": "stop"}),
                "data: [DONE]\n\n",
            ]
        )
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return response

        provider = MayaCoreProvider(
            base_url="http://localhost:8080",
            session_id="session-default",
            opener=opener,
        )
        request = LLMRequest(
            messages=(LLMMessage(role="user", content="Hello"),),
            conversation_id="conversation-0",
            session_id="session-request",
        )

        events = list(provider.stream(request))
        payload = json.loads(captured["request"].data)

        self.assertEqual(events, [
            LLMSession("session-1"),
            LLMConversation("conversation-1"),
            LLMState("thinking", "Generating"),
            LLMTextDelta("Hello"),
            LLMToolCallDelta(0, "call-1", "lookup", "{"),
            LLMUsage(5, 2),
            LLMCompleted("stop"),
        ])
        self.assertEqual(payload["message"], "Hello")
        self.assertEqual(payload["conversation_id"], "conversation-0")
        self.assertEqual(payload["session_id"], "session-request")
        self.assertTrue(response.closed)

    def test_legacy_raw_text_stream_remains_supported(self):
        response = FakeResponse(["data: Hello\n\n", "data: [DONE]\n\n"])
        provider = MayaCoreProvider(opener=lambda *_args, **_kwargs: response)

        events = list(provider.stream(LLMRequest(messages=(LLMMessage(role="user", content="Hi"),))))

        self.assertEqual(events, [LLMTextDelta("Hello"), LLMCompleted()])

    def test_sse_event_field_can_identify_plain_text(self):
        response = FakeResponse(["event: text_delta\n", "data: Hello\n\n", "data: [DONE]\n\n"])
        provider = MayaCoreProvider(opener=lambda *_args, **_kwargs: response)

        events = list(provider.stream(LLMRequest(messages=(LLMMessage(role="user", content="Hi"),))))

        self.assertEqual(events, [LLMTextDelta("Hello"), LLMCompleted()])


if __name__ == "__main__":
    unittest.main()
