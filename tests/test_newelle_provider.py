import threading
import time
import unittest

from PySide6.QtCore import QCoreApplication, QObject, Signal

from backend.llm import (
    LLMCompleted,
    LLMConversation,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMState,
    LLMTextDelta,
)
from backend.llm.newelle_provider import NewelleProvider


class FakeNewelleClient(QObject):
    chatReady = Signal(int)
    stateEvent = Signal(str, str)
    textChanged = Signal(str)
    completed = Signal()
    failed = Signal(str)

    def __init__(self, failure=None):
        super().__init__()
        self.failure = failure
        self.requests = []

    def submit(self, prompt, chat_id):
        self.requests.append((prompt, chat_id))
        if self.failure is not None:
            self.failed.emit(self.failure)
            return True
        self.chatReady.emit(42 if chat_id is None else chat_id)
        self.stateEvent.emit("thinking", "")
        self.textChanged.emit("Hel")
        self.stateEvent.emit("tool", "Opening application…")
        self.textChanged.emit("Hello")
        self.textChanged.emit("The final answer")
        self.completed.emit()
        return True


class NewelleProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def collect_stream(self, provider, request):
        result = []
        error = []

        def consume():
            try:
                result.extend(provider.stream(request))
            except Exception as exc:
                error.append(exc)

        thread = threading.Thread(target=consume)
        thread.start()
        deadline = time.monotonic() + 3
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        thread.join(timeout=0.2)
        self.assertFalse(thread.is_alive(), "provider stream did not finish")
        return result, error

    def test_converts_chat_text_tool_status_and_completion_events(self):
        client = FakeNewelleClient()
        provider = NewelleProvider(client=client)
        request = LLMRequest(
            messages=(LLMMessage(role="user", content="Open Firefox"),),
            conversation_id="17",
        )

        events, errors = self.collect_stream(provider, request)

        self.assertEqual(errors, [])
        self.assertEqual(client.requests, [("Open Firefox", 17)])
        self.assertEqual(events[0], LLMConversation(17))
        self.assertIn(LLMTextDelta("Hel"), events)
        self.assertIn(LLMState("tool", "Opening application…"), events)
        self.assertIn(LLMTextDelta("lo"), events)
        self.assertIn(LLMTextDelta("The final answer", replace=True), events)
        self.assertEqual(events[-1], LLMCompleted("stop"))
        self.assertIsInstance(provider, LLMProvider)

    def test_normalizes_newelle_failures_without_changing_message(self):
        provider = NewelleProvider(client=FakeNewelleClient(failure="Newelle unavailable"))
        request = LLMRequest(messages=(LLMMessage(role="user", content="Hello"),))

        events, errors = self.collect_stream(provider, request)

        self.assertEqual(events, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], LLMProviderError)
        self.assertEqual(str(errors[0]), "Newelle unavailable")
        self.assertEqual(errors[0].code, "connection")
        self.assertTrue(errors[0].retryable)

    def test_normalizes_server_error_as_provider_failure(self):
        provider = NewelleProvider(client=FakeNewelleClient(failure="Assistant failed"))
        request = LLMRequest(messages=(LLMMessage(role="user", content="Hello"),))

        _, errors = self.collect_stream(provider, request)

        self.assertEqual(str(errors[0]), "Assistant failed")
        self.assertEqual(errors[0].code, "provider")
        self.assertFalse(errors[0].retryable)

    def test_rejects_requests_without_a_user_message(self):
        provider = NewelleProvider(client=FakeNewelleClient())

        with self.assertRaises(LLMProviderError) as caught:
            list(provider.stream(LLMRequest(messages=(LLMMessage(role="system", content="policy"),))))

        self.assertEqual(caught.exception.code, "invalid_request")


if __name__ == "__main__":
    unittest.main()
