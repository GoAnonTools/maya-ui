import unittest
from collections.abc import Iterator

from backend.llm import (
    LLMCapabilities,
    LLMCompleted,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMTextDelta,
    LLMToolCall,
    LLMToolCallDelta,
    LLMToolDefinition,
    LLMUsage,
)


class _ExampleProvider:
    name = "example"
    capabilities = LLMCapabilities(streaming=True, tool_calls=True)

    def stream(self, request: LLMRequest) -> Iterator[LLMTextDelta | LLMCompleted]:
        yield LLMTextDelta("Hello")
        yield LLMCompleted("stop")

    def close(self) -> None:
        pass


class LLMProviderContractTests(unittest.TestCase):
    def test_request_models_messages_tools_and_generation_options(self):
        tool = LLMToolDefinition(
            name="open_application",
            description="Open a desktop application.",
            parameters={"type": "object", "properties": {"name": {"type": "string"}}},
        )
        request = LLMRequest(
            messages=(LLMMessage(role="user", content="Open Firefox"),),
            tools=(tool,),
            tool_choice="auto",
            temperature=0.2,
            max_tokens=128,
        )

        self.assertEqual(request.messages[0].role, "user")
        self.assertEqual(request.tools[0].name, "open_application")
        self.assertEqual(request.temperature, 0.2)
        self.assertEqual(request.max_tokens, 128)

    def test_assistant_tool_calls_and_tool_result_messages_are_representable(self):
        call = LLMToolCall(id="call-1", name="open_application", arguments={"name": "Firefox"})
        assistant = LLMMessage(role="assistant", content="", tool_calls=(call,))
        result = LLMMessage(role="tool", content="Opened Firefox", name="open_application", tool_call_id="call-1")

        self.assertEqual(assistant.tool_calls[0].arguments["name"], "Firefox")
        self.assertEqual(result.tool_call_id, "call-1")

    def test_stream_events_cover_text_tool_usage_and_completion(self):
        events = (
            LLMTextDelta("Opening"),
            LLMToolCallDelta(index=0, id="call-1", name="open_application", arguments_delta='{"name":'),
            LLMUsage(input_tokens=10, output_tokens=4),
            LLMCompleted("tool_calls"),
        )

        self.assertEqual(events[1].index, 0)
        self.assertEqual(events[2].input_tokens, 10)
        self.assertEqual(events[3].finish_reason, "tool_calls")

    def test_provider_protocol_is_structurally_implementable(self):
        provider = _ExampleProvider()

        self.assertIsInstance(provider, LLMProvider)
        self.assertEqual(list(provider.stream(LLMRequest(messages=()))), [LLMTextDelta("Hello"), LLMCompleted("stop")])

    def test_provider_error_exposes_normalized_handling_fields(self):
        error = LLMProviderError("timeout", "Request timed out", provider="local_qwen", retryable=True)

        self.assertEqual(str(error), "Request timed out")
        self.assertEqual(error.code, "timeout")
        self.assertEqual(error.provider, "local_qwen")
        self.assertTrue(error.retryable)


if __name__ == "__main__":
    unittest.main()
