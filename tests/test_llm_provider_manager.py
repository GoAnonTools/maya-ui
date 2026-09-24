import unittest
import json
from collections.abc import Iterator
from threading import Event, Thread
from backend.llm import (
    LLMCapabilities,
    LLMEvent,
    LLMProviderError,
    LLMRequest,
    LLMTextDelta,
    ProviderManager,
    ProviderRegistry,
)
from backend.llm.defaults import create_default_provider_manager
from backend.llm.dev_provider_test import list_provider_status, run_provider_test
from backend.llm.newelle_provider import NewelleProvider


class FakeProvider:
    def __init__(self, name, text, capabilities=None):
        self.name = name
        self.text = text
        self.capabilities = capabilities or LLMCapabilities(streaming=True, tool_calls=False)
        self.requests = []
        self.closed = False

    def stream(self, request: LLMRequest) -> Iterator[LLMEvent]:
        self.requests.append(request)
        yield LLMTextDelta(self.text)

    def close(self):
        self.closed = True


class ProviderManagerTests(unittest.TestCase):
    def test_default_provider_selection_uses_newelle(self):
        manager = create_default_provider_manager(credential_resolver=lambda _ref: None)

        self.assertEqual(manager.current_provider_name, "newelle")
        self.assertIsInstance(manager.registry.get("newelle"), NewelleProvider)
        self.assertTrue(manager.availability().available)
        self.assertTrue(manager.capabilities.streaming)
        self.assertTrue(manager.capabilities.tool_calls)

    def test_development_path_lists_and_selects_ministral_then_restores_default(self):
        manager = create_default_provider_manager(credential_resolver=lambda _ref: "test-secret")

        self.assertEqual(manager.current_provider_name, "newelle")
        statuses = {name: available for name, available, _reason in list_provider_status(manager)}
        self.assertTrue(statuses["ministral_14b"])
        manager.select("ministral_14b")
        self.assertEqual(manager.current_provider_name, "ministral_14b")
        manager.select("newelle")
        self.assertEqual(manager.current_provider_name, "newelle")

    def test_switching_registered_providers_forwards_requests(self):
        local = FakeProvider("local", "local response")
        remote = FakeProvider("remote", "remote response", LLMCapabilities(streaming=True, tool_calls=True))
        registry = ProviderRegistry()
        registry.register(local)
        registry.register(remote)
        manager = ProviderManager(registry, "local")
        request = LLMRequest(messages=())

        self.assertEqual(list(manager.stream(request)), [LLMTextDelta("local response")])
        manager.select("remote")
        self.assertEqual(manager.current_provider_name, "remote")
        self.assertTrue(manager.capabilities.tool_calls)
        self.assertEqual(list(manager.submit(request)), [LLMTextDelta("remote response")])
        self.assertEqual(local.requests, [request])
        self.assertEqual(remote.requests, [request])

    def test_unavailable_provider_cannot_be_selected_or_streamed(self):
        active = FakeProvider("active", "active response")
        unavailable = FakeProvider("offline", "offline response")
        registry = ProviderRegistry()
        registry.register(active)
        registry.register(unavailable, available=False, reason="not configured")
        manager = ProviderManager(registry, "active")

        status = manager.availability("offline")
        self.assertFalse(status.available)
        self.assertEqual(status.reason, "not configured")
        with self.assertRaises(LLMProviderError):
            manager.select("offline")
        self.assertEqual(manager.current_provider_name, "active")
        self.assertEqual(list(manager.stream(LLMRequest(messages=()))), [LLMTextDelta("active response")])

        registry.set_available("active", False, "temporarily disabled")
        self.assertFalse(manager.available)
        with self.assertRaises(LLMProviderError):
            list(manager.stream(LLMRequest(messages=())))
        self.assertEqual(len(active.requests), 1)

    def test_unknown_provider_is_reported_without_changing_selection(self):
        provider = FakeProvider("only", "response")
        registry = ProviderRegistry()
        registry.register(provider)
        manager = ProviderManager(registry, "only")

        with self.assertRaises(LLMProviderError):
            manager.select("missing")
        self.assertEqual(manager.current_provider_name, "only")

    def test_registry_rejects_duplicate_names(self):
        registry = ProviderRegistry()
        registry.register(FakeProvider("duplicate", "first"))

        with self.assertRaises(ValueError):
            registry.register(FakeProvider("duplicate", "second"))

    def test_switching_during_active_stream_does_not_change_that_request(self):
        started = Event()
        release = Event()

        class PausingProvider(FakeProvider):
            def stream(self, request):
                self.requests.append(request)
                started.set()
                release.wait(timeout=2)
                yield LLMTextDelta("from original provider")

        original = PausingProvider("original", "unused")
        other = FakeProvider("other", "next provider")
        registry = ProviderRegistry()
        registry.register(original)
        registry.register(other)
        manager = ProviderManager(registry, "original")
        result = []
        thread = Thread(target=lambda: result.extend(manager.submit(LLMRequest(messages=()))))
        thread.start()
        self.assertTrue(started.wait(timeout=2))
        manager.select("other")
        release.set()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [LLMTextDelta("from original provider")])
        self.assertEqual(list(manager.submit(LLMRequest(messages=()))), [LLMTextDelta("next provider")])

    def test_smoke_test_normalized_events_can_be_delivered_to_controller(self):
        from test_memory_controller import FakeMemory, make_controller
        from backend.llm import LLMCompleted

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def __iter__(self):
                for payload in (
                    {"choices": [{"delta": {"content": "Ministral "}, "finish_reason": None}]},
                    {"choices": [{"delta": {"content": "response"}, "finish_reason": "stop"}]},
                ):
                    yield f"data: {json.dumps(payload)}\n\n".encode()
                yield b"data: [DONE]\n\n"

        manager = create_default_provider_manager(credential_resolver=lambda _ref: "test-secret")
        provider = manager.registry.get("ministral_14b")
        provider._opener = lambda _request, timeout: FakeResponse()
        controller = make_controller(FakeMemory(enabled=False))
        controller._provider_manager = manager
        controller._request_active = True

        received = run_provider_test(
            manager,
            "ministral_14b",
            "Reply briefly to this provider smoke test.",
            event_handler=controller._on_llm_event,
        )

        self.assertEqual(received, (LLMTextDelta("Ministral "), LLMTextDelta("response"), LLMCompleted("stop")))
        self.assertEqual(controller._assistant_text, "Ministral response")
        self.assertEqual(manager.current_provider_name, "newelle")


if __name__ == "__main__":
    unittest.main()
