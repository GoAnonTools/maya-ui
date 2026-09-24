import json
import unittest
import urllib.error

from backend.llm import (
    LLMCapabilities,
    LLMCompleted,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMTextDelta,
    LLMToolCallDelta,
    LLMToolDefinition,
    LLMUsage,
    ProviderRegistry,
)
from backend.llm.defaults import create_default_provider_manager, register_openai_compatible_provider
from backend.llm.openai_compatible_provider import OpenAICompatibleProvider


class FakeResponse:
    def __init__(self, lines):
        self.lines = [line.encode("utf-8") if isinstance(line, str) else line for line in lines]
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def __iter__(self):
        return iter(self.lines)


def sse(payload):
    return "data: " + json.dumps(payload, separators=(",", ":")) + "\n\n"


class OpenAICompatibleProviderTests(unittest.TestCase):
    def make_provider(self, *, lines, **kwargs):
        response = FakeResponse(lines)
        opener = lambda request, timeout: self._capture(response, request, timeout)
        provider = OpenAICompatibleProvider(
            "http://localhost:1234/v1",
            "test-model",
            opener=opener,
            **kwargs,
        )
        return provider, response

    def _capture(self, response, request, timeout):
        self.request = request
        self.timeout = timeout
        return response

    def test_normal_completion_converts_final_chunk_and_done_marker(self):
        provider, response = self.make_provider(
            lines=[
                sse({"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}),
                sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                "data: [DONE]\n\n",
            ]
        )

        events = list(provider.stream(LLMRequest(messages=(LLMMessage(role="user", content="Hi"),))))

        self.assertEqual(events, [LLMTextDelta("Hello"), LLMCompleted("stop")])
        self.assertTrue(response.closed)
        self.assertIsInstance(provider, LLMProvider)

    def test_streaming_chunks_and_usage_are_normalized(self):
        provider, _ = self.make_provider(
            lines=[
                sse({"choices": [{"delta": {"content": "Good "}, "finish_reason": None}]}),
                sse({"choices": [{"delta": {"content": "morning."}, "finish_reason": None}]}),
                sse({
                    "choices": [],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                }),
                sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                "data: [DONE]\n\n",
            ]
        )

        events = list(provider.stream(LLMRequest(messages=(LLMMessage(role="user", content="Greet me"),))))

        self.assertEqual(events, [
            LLMTextDelta("Good "),
            LLMTextDelta("morning."),
            LLMUsage(input_tokens=12, output_tokens=3),
            LLMCompleted("stop"),
        ])

    def test_tool_call_chunks_are_normalized_and_request_schema_is_sent(self):
        tool = LLMToolDefinition(
            name="open_application",
            description="Open an application",
            parameters={"type": "object", "properties": {"name": {"type": "string"}}},
        )
        provider, _ = self.make_provider(
            lines=[
                sse({
                    "choices": [{
                        "delta": {
                            "tool_calls": [{
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "open_application", "arguments": "{\"name\":"},
                            }]
                        },
                        "finish_reason": None,
                    }]
                }),
                sse({
                    "choices": [{
                        "delta": {
                            "tool_calls": [{
                                "index": 0,
                                "function": {"arguments": "\"Firefox\"}"},
                            }]
                        },
                        "finish_reason": "tool_calls",
                    }]
                }),
                "data: [DONE]\n\n",
            ]
        )

        events = list(provider.stream(LLMRequest(
            messages=(LLMMessage(role="user", content="Open Firefox"),),
            tools=(tool,),
            tool_choice="required",
        )))
        body = json.loads(self.request.data)

        self.assertEqual(events[0], LLMToolCallDelta(0, "call-1", "open_application", "{\"name\":"))
        self.assertEqual(events[1], LLMToolCallDelta(0, None, None, "\"Firefox\"}"))
        self.assertEqual(events[-1], LLMCompleted("tool_calls"))
        self.assertEqual(body["tools"][0]["function"]["name"], "open_application")
        self.assertEqual(body["tool_choice"], "required")

    def test_provider_and_http_errors_are_normalized(self):
        provider, _ = self.make_provider(lines=[sse({"error": {"message": "private server detail"}})])

        with self.assertRaises(LLMProviderError) as caught:
            list(provider.stream(LLMRequest(messages=(LLMMessage(role="user", content="Hi"),))))

        self.assertEqual(caught.exception.code, "provider")
        self.assertEqual(str(caught.exception), "OpenAI-compatible provider returned an error")
        self.assertNotIn("private server detail", str(caught.exception))

        http_error = urllib.error.HTTPError(
            "http://localhost/v1/chat/completions",
            401,
            "Unauthorized",
            hdrs=None,
            fp=None,
        )
        provider = OpenAICompatibleProvider(
            "http://localhost/v1",
            "test-model",
            opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(http_error),
        )
        with self.assertRaises(LLMProviderError) as caught:
            list(provider.stream(LLMRequest(messages=(LLMMessage(role="user", content="Hi"),))))
        self.assertEqual(caught.exception.code, "authentication")
        self.assertFalse(caught.exception.retryable)

    def test_credential_reference_is_resolved_for_request_not_stored_as_key(self):
        provider, _ = self.make_provider(
            lines=["data: [DONE]\n\n"],
            credential_ref="maya-provider-key",
            credential_resolver=lambda reference: "test-secret" if reference == "maya-provider-key" else None,
        )

        list(provider.stream(LLMRequest(messages=(LLMMessage(role="user", content="Hi"),))))

        self.assertEqual(self.request.get_header("Authorization"), "Bearer test-secret")
        self.assertEqual(provider.credential_ref, "maya-provider-key")
        self.assertFalse(hasattr(provider, "api_key"))

    def test_missing_credential_reference_fails_without_http_request(self):
        provider = OpenAICompatibleProvider(
            "http://localhost/v1",
            "test-model",
            credential_ref="external-secret",
        )

        with self.assertRaises(LLMProviderError) as caught:
            list(provider.stream(LLMRequest(messages=(LLMMessage(role="user", content="Hi"),))))

        self.assertEqual(caught.exception.code, "authentication")

    def test_capabilities_and_endpoint_configuration(self):
        provider = OpenAICompatibleProvider("http://localhost:9000", "qwen")

        self.assertEqual(provider.name, "openai_compatible")
        self.assertEqual(provider.capabilities, LLMCapabilities(streaming=True, tool_calls=True))
        self.assertEqual(provider._endpoint(), "http://localhost:9000/v1/chat/completions")
        self.assertEqual(OpenAICompatibleProvider("http://host/api/v1/", "model")._endpoint(), "http://host/api/v1/chat/completions")

    def test_registration_does_not_change_newelle_default(self):
        manager = create_default_provider_manager(credential_resolver=lambda _ref: None)
        provider = register_openai_compatible_provider(
            manager.registry,
            base_url="http://localhost:9000/v1",
            model="qwen",
            available=False,
            unavailable_reason="awaiting credentials",
        )

        self.assertEqual(manager.current_provider_name, "newelle")
        self.assertEqual(manager.registry.get("openai_compatible"), provider)
        self.assertFalse(manager.availability("openai_compatible").available)
        self.assertEqual(manager.provider_names, ("newelle", "ministral_14b", "openai_compatible"))


if __name__ == "__main__":
    unittest.main()
