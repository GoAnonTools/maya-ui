"""Unit tests for internal LLM task cancellation infrastructure."""

import os
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from backend.llm.base import LLMCapabilities, LLMEvent, LLMProvider, LLMRequest, LLMState, LLMTextDelta
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

    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_stop_command_cancels_active_task_and_enters_5s_listening(self, mock_mem, mock_tts, mock_stt, mock_wake):

        controller = MayaController(memory_service=mock_mem.return_value)
        controller._chat_id = 999
        controller._request_active = True
        controller.set_state("thinking")

        mock_worker = MagicMock()
        controller._llm_worker = mock_worker

        with patch.object(controller, "_start_provider_request") as mock_start_req:
            for phrase in ["maya stop", "stop", "please cancel", "MAYA CANCEL!", "shut up"]:
                controller._request_active = True
                controller.set_state("thinking")

                controller.submit(phrase)

                mock_worker.cancel.assert_called()
                controller._tts.stop.assert_called()
                self.assertFalse(controller._request_active)
                self.assertEqual(controller.state, "listening")
                self.assertTrue(controller._wake_timeout_timer.isActive())
                self.assertEqual(controller._chat_id, 999)
                mock_start_req.assert_not_called()

            # Timeout after 5 seconds returns to idle
            controller._on_wake_timeout()
            self.assertEqual(controller.state, "idle")

    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_normal_request_reaches_llm(self, mock_mem, mock_tts, mock_stt, mock_wake):
        controller = MayaController(memory_service=mock_mem.return_value)
        controller._chat_id = 555

        with patch.object(controller, "_start_provider_request", return_value=True) as mock_start_req:
            controller.submit("What is the capital of France?")

            mock_start_req.assert_called_once()
            self.assertEqual(controller._chat_id, 555)


    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_wake_detected_allowed_in_thinking_idle_and_speaking_states(self, mock_mem, mock_tts, mock_stt, mock_wake):
        controller = MayaController(memory_service=mock_mem.return_value)

        for initial_state in ["idle", "thinking", "speaking"]:
            controller.set_state(initial_state)
            controller._on_wake_detected()
            self.assertEqual(controller.state, "listening")

    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_stale_llm_state_event_ignored_after_wake_interruption(self, mock_mem, mock_tts, mock_stt, mock_wake):
        controller = MayaController(memory_service=mock_mem.return_value)
        controller._request_active = True
        controller.set_state("thinking")

        mock_worker = MagicMock()
        controller._llm_worker = mock_worker

        # User wake interruption occurs
        controller._on_wake_detected()
        self.assertEqual(controller.state, "listening")
        self.assertFalse(controller._request_active)
        mock_worker.cancel.assert_called_once()

        # Emit delayed/stale LLMState events from the cancelled task
        controller._on_llm_event(LLMState(state="thinking", detail="Late thinking event"))
        self.assertEqual(controller.state, "listening")

        controller._on_llm_event(LLMState(state="tool", detail="Late tool event"))
        self.assertEqual(controller.state, "listening")

    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_normal_llm_state_transition_works(self, mock_mem, mock_tts, mock_stt, mock_wake):
        controller = MayaController(memory_service=mock_mem.return_value)
        controller._request_active = True
        controller.set_state("thinking")

        # Emit LLMState while request is active
        controller._on_llm_event(LLMState(state="tool", detail="Running tool..."))
        self.assertEqual(controller.state, "tool")
        self.assertEqual(controller.detail, "Running tool...")

    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_stale_llm_text_delta_ignored_after_cancellation(self, mock_mem, mock_tts, mock_stt, mock_wake):
        controller = MayaController(memory_service=mock_mem.return_value)
        controller._request_active = True
        controller._assistant_text = "Initial text"
        controller.set_state("thinking")

        mock_worker = MagicMock()
        controller._llm_worker = mock_worker

        # Cancel the request
        controller.cancel_active_task()
        self.assertEqual(controller.state, "idle")
        self.assertFalse(controller._request_active)

        # Reset TTS mock calls from cancel_active_task
        controller._tts.feed_response.reset_mock()

        # Simulate a late LLMTextDelta event
        controller._on_llm_event(LLMTextDelta(" additional stale text"))

        # Verify assistant text is not modified, state is unchanged, and TTS is not fed
        self.assertEqual(controller._assistant_text, "Initial text")
        self.assertEqual(controller.state, "idle")
        controller._tts.feed_response.assert_not_called()

    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_wake_command_pending_lifecycle_and_timeout_reprieve(self, mock_mem, mock_tts, mock_stt, mock_wake):
        controller = MayaController(memory_service=mock_mem.return_value)
        
        # 1. Wake detected: sets _wake_command_pending = True and token = 1
        controller._on_wake_detected()
        self.assertTrue(controller._wake_command_pending)
        self.assertEqual(controller._wake_generation, 1)
        self.assertEqual(controller._wake_timeout_token, 1)
        self.assertEqual(controller.state, "listening")

        # 2. Timeout 1 expires while command is in flight:
        # Reads _wake_command_pending (True), grants reprieve, sets _wake_command_pending = False, re-arms
        controller._on_wake_timeout()
        self.assertFalse(controller._wake_command_pending)
        self.assertEqual(controller.state, "listening")

        # 3. Timeout 2 expires (reprieve consumed):
        # Reads _wake_command_pending (False), transitions listening -> idle
        controller._on_wake_timeout()
        self.assertEqual(controller.state, "idle")

        # 4. _cancel_wake_timeout clears _wake_command_pending
        controller._wake_command_pending = True
        controller._cancel_wake_timeout("test")
        self.assertFalse(controller._wake_command_pending)

    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_wake_detected_tts_stop_conditional(self, mock_mem, mock_tts, mock_stt, mock_wake):
        controller = MayaController(memory_service=mock_mem.return_value)

        # Idle state: _tts.stop() should NOT be called
        controller.set_state("idle")
        type(controller._tts).is_speaking = PropertyMock(return_value=False)
        controller._tts.stop.reset_mock()
        controller._on_wake_detected()
        controller._tts.stop.assert_not_called()

        # Speaking state: _tts.stop() SHOULD be called
        controller.set_state("speaking")
        type(controller._tts).is_speaking = PropertyMock(return_value=True)
        controller._tts.stop.reset_mock()
        controller._on_wake_detected()
        controller._tts.stop.assert_called_once()

    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_stt_transcript_submits_regardless_of_state(self, mock_mem, mock_tts, mock_stt, mock_wake):
        controller = MayaController(memory_service=mock_mem.return_value)
        controller._stt_generation = 10

        # State moved on to idle (e.g. timeout occurred)
        controller.set_state("idle")

        with patch.object(controller, "_submit_request") as mock_submit:
            controller._on_stt_transcript(10, "Late transcript test")
            mock_submit.assert_called_once()
            self.assertEqual(mock_submit.call_args[0][0], "Late transcript test")


    @patch("backend.maya_controller.WakeManager")
    @patch("backend.maya_controller.STTManager")
    @patch("backend.maya_controller.TTSManager")
    @patch("backend.maya_controller.MemoryService")
    def test_llm_watchdog_timer_lifecycle_and_timeout(self, mock_mem, mock_tts, mock_stt, mock_wake):
        controller = MayaController(memory_service=mock_mem.return_value)
        controller._request_active = True
        controller.set_state("thinking")

        mock_worker = MagicMock()
        controller._llm_worker = mock_worker

        # Start watchdog
        controller._start_llm_watchdog(10.0)
        self.assertTrue(controller._llm_watchdog_timer.isActive())

        # Timeout fires
        controller._on_llm_watchdog_timeout()

        # Watchdog cancelled worker, set request_active = False, moved state to idle, and stopped timer
        mock_worker.cancel.assert_called_once()
        self.assertFalse(controller._request_active)
        self.assertEqual(controller.state, "idle")
        self.assertFalse(controller._llm_watchdog_timer.isActive())


if __name__ == "__main__":
    unittest.main()




