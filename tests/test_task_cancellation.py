"""Unit tests for internal LLM task cancellation infrastructure."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from backend.llm.base import LLMCapabilities, LLMEvent, LLMProvider, LLMRequest, LLMTextDelta
from backend.llm.runner import LLMStreamWorker
from backend.maya_controller import MayaController


class DummyProvider(LLMProvider):
    name = "dummy"
    capabilities = LLMCapabilities(streaming=True)

    def __init__(self, events: list[LLMEvent]):
        self._events = events
        self.cancel_called = False

    def stream(self, request: LLMRequest):
        for ev in self._events:
            yield ev

    def close(self) -> None:
        pass

    def cancel(self) -> None:
        self.cancel_called = True


class TestLLMStreamWorkerCancellation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QCoreApplication.instance():
            cls._app = QCoreApplication([])

    def test_worker_cancel_flag(self):
        provider = DummyProvider([LLMTextDelta("hello"), LLMTextDelta(" world")])
        request = LLMRequest(messages=())
        worker = LLMStreamWorker(provider, request)

        self.assertFalse(worker.is_cancelled())
        worker.cancel()
        self.assertTrue(worker.is_cancelled())
        self.assertTrue(provider.cancel_called)

    def test_worker_suppresses_signals_when_cancelled_before_run(self):
        provider = DummyProvider([LLMTextDelta("hello")])
        request = LLMRequest(messages=())
        worker = LLMStreamWorker(provider, request)

        events = []
        ended = []
        failed = []

        worker.eventReady.connect(events.append)
        worker.streamEnded.connect(lambda: ended.append(True))
        worker.failed.connect(failed.append)

        worker.cancel()
        worker.run()

        self.assertEqual(events, [])
        self.assertEqual(ended, [])
        self.assertEqual(failed, [])

    def test_worker_emits_signals_when_not_cancelled(self):
        delta = LLMTextDelta("hello")
        provider = DummyProvider([delta])
        request = LLMRequest(messages=())
        worker = LLMStreamWorker(provider, request)

        events = []
        ended = []
        failed = []

        worker.eventReady.connect(events.append)
        worker.streamEnded.connect(lambda: ended.append(True))
        worker.failed.connect(failed.append)

        worker.run()

        self.assertEqual(events, [delta])
        self.assertEqual(ended, [True])
        self.assertEqual(failed, [])


class TestMayaControllerCancellation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QCoreApplication.instance():
            cls._app = QCoreApplication([])

    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_cancel_active_task_resets_state_and_preserves_chat_id(self, mock_mem, mock_tts, mock_stt, mock_wake):
        controller = MayaController(memory_service=mock_mem.return_value)
        controller._chat_id = 12345
        controller._request_active = True
        controller.set_state("thinking")

        mock_worker = MagicMock()
        controller._llm_worker = mock_worker

        controller.cancel_active_task()

        mock_worker.cancel.assert_called_once()
        controller._tts.stop.assert_called_once()
        controller._stt.cancel.assert_called_once()
        self.assertFalse(controller._request_active)
        self.assertEqual(controller.state, "idle")
        self.assertEqual(controller._chat_id, 12345)


if __name__ == "__main__":
    unittest.main()
