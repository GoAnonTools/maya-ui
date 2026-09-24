import unittest

from backend.tts.manager import TTSManager


class TTSManagerReplacementTests(unittest.TestCase):
    def make_manager(self):
        manager = TTSManager()
        generated = []

        def pump_without_audio():
            with manager._lock:
                while manager._queue:
                    generated.append(manager._queue.popleft())

        manager._pump = pump_without_audio
        return manager, generated

    def test_cumulative_replacement_speaks_only_the_new_suffix(self):
        manager, generated = self.make_manager()
        initial = "This first sentence is sufficiently long to be spoken. Old second sentence is still being written"
        revised = "This first sentence is sufficiently long to be spoken. New second sentence is ready."

        manager.start_response("en")
        manager.feed_response(initial)
        manager.feed_response(revised, replace=True)
        manager.finish_response()

        self.assertEqual(generated, [
            "This first sentence is sufficiently long to be spoken.",
            "New second sentence is ready.",
        ])

    def test_normal_incremental_cumulative_updates_speak_once_in_chunks(self):
        manager, generated = self.make_manager()
        manager.start_response("en")
        manager.feed_response("A normal incremental response continues")
        manager.feed_response("A normal incremental response continues. It keeps going.")
        manager.finish_response()

        self.assertEqual(generated, [
            "A normal incremental response continues.",
            "It keeps going.",
        ])

    def test_separate_responses_reset_generated_text_tracking(self):
        manager, generated = self.make_manager()
        manager.start_response("en")
        manager.feed_response("The first response is complete.")
        manager.finish_response()

        manager.start_response("en")
        manager.feed_response("The second response is also complete.")
        manager.finish_response()

        self.assertEqual(generated, [
            "The first response is complete.",
            "The second response is also complete.",
        ])

    def test_ambiguous_replacement_suppresses_speech_instead_of_replaying(self):
        manager, generated = self.make_manager()
        manager.start_response("en")
        manager.feed_response("This first sentence is sufficiently long to be spoken. Old tail is still being written")
        manager.feed_response("Entirely revised text with no reliable shared prefix.", replace=True)
        manager.finish_response()

        self.assertEqual(generated, ["This first sentence is sufficiently long to be spoken."])

    def test_later_safe_replacement_resumes_after_ambiguous_update(self):
        manager, generated = self.make_manager()
        manager.start_response("en")
        manager.feed_response("First sentence is long enough to speak. Pending text")
        manager.feed_response("Unrelated replacement with no safe overlap.", replace=True)
        manager.feed_response("First sentence is long enough to speak. New second sentence is ready.", replace=True)
        manager.finish_response()

        self.assertEqual(generated, [
            "First sentence is long enough to speak.",
            "New second sentence is ready.",
        ])

    def test_ambiguous_update_does_not_stop_later_long_response(self):
        manager, generated = self.make_manager()
        manager.start_response("en")
        manager.feed_response("First sentence is long enough to speak. Second sentence is long enough too.")
        manager.feed_response("Temporary unrelated revision.", replace=True)
        manager.feed_response(
            "First sentence is long enough to speak. Second sentence is long enough too. "
            "Third sentence is long enough to continue speaking.",
            replace=True,
        )
        manager.finish_response()

        self.assertEqual(generated, [
            "First sentence is long enough to speak.",
            "Second sentence is long enough too.",
            "Third sentence is long enough to continue speaking.",
        ])

    def test_safe_replacement_preserves_queued_future_chunks(self):
        manager = TTSManager()
        generated = []

        def pump_without_audio():
            # Leave queued chunks in place to model audio already waiting
            # behind a currently speaking sentence.
            return None

        manager._pump = pump_without_audio
        manager.start_response("en")
        manager.feed_response("First sentence is long enough to speak. Old queued sentence is still being written")
        self.assertEqual(list(manager._queue), ["First sentence is long enough to speak."])

        manager.feed_response("First sentence is long enough to speak. New queued sentence.", replace=True)
        with manager._lock:
            generated.extend(manager._queue)

        self.assertEqual(generated, [
            "First sentence is long enough to speak.",
            "New queued sentence.",
        ])

    def test_long_streamed_answer_completes_all_sentences(self):
        manager = TTSManager()
        generated = []

        def pump_without_audio():
            with manager._lock:
                while manager._queue:
                    generated.append(manager._queue.popleft())

        manager._pump = pump_without_audio
        manager.start_response("en")
        manager.feed_response(
            "First sentence is long enough to speak. Second sentence is long enough to speak too. "
            "Third sentence is long enough to remain available."
        )
        manager.feed_response(
            "First sentence is long enough to speak. Second sentence is long enough to speak too. "
            "Third sentence is long enough to remain available. Fourth sentence arrives later too.",
            replace=True,
        )
        manager.finish_response()

        self.assertEqual(generated, [
            "First sentence is long enough to speak.",
            "Second sentence is long enough to speak too.",
            "Third sentence is long enough to remain available.",
            "Fourth sentence arrives later too.",
        ])

    def test_piper_playback_timeout_triggers_failure_callback(self):
        from unittest.mock import MagicMock, patch
        import subprocess
        from backend.tts.piper_provider import PiperProvider
        from backend.tts.base import Voice

        provider = PiperProvider()
        provider._generation = 1
        callbacks = MagicMock()
        voice = Voice("test-voice", "piper", "en", "female", "/tmp/nonexistent.onnx")

        with patch("pathlib.Path.exists", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            mock_piper = MagicMock()
            mock_piper.communicate.return_value = (b"", b"")
            mock_piper.returncode = 0
            mock_play = MagicMock()
            mock_play.wait.side_effect = subprocess.TimeoutExpired(cmd="pw-play", timeout=10.0)
            mock_popen.side_effect = [mock_piper, mock_play]

            provider._run(1, "Hello world", voice, 1.0, callbacks)

            mock_play.kill.assert_called_once()
            callbacks.failed.assert_called_once()
            self.assertIn("timed out", callbacks.failed.call_args[0][0])

    def test_piper_synthesis_timeout_triggers_failure_callback(self):
        from unittest.mock import MagicMock, patch
        import subprocess
        from backend.tts.piper_provider import PiperProvider
        from backend.tts.base import Voice

        provider = PiperProvider()
        provider._generation = 1
        callbacks = MagicMock()
        voice = Voice("test-voice", "piper", "en", "female", "/tmp/nonexistent.onnx")

        with patch("pathlib.Path.exists", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            mock_piper = MagicMock()
            mock_piper.communicate.side_effect = subprocess.TimeoutExpired(cmd="piper", timeout=15.0)
            mock_popen.return_value = mock_piper

            provider._run(1, "Hello world", voice, 1.0, callbacks)

            mock_piper.kill.assert_called_once()
            callbacks.failed.assert_called_once()
            self.assertIn("timed out", callbacks.failed.call_args[0][0])

    def test_kokoro_playback_timeout_triggers_failure_callback(self):
        from unittest.mock import MagicMock, patch
        import subprocess
        from backend.tts.kokoro_provider import KokoroProvider
        from backend.tts.base import Voice

        provider = KokoroProvider()
        provider._generation = 1
        callbacks = MagicMock()
        voice = Voice("af_heart", "kokoro", "en-us", "female", "/tmp/model.onnx")

        with patch("pathlib.Path.exists", return_value=True), \
             patch.object(provider, "_engine", create=True) as mock_engine, \
             patch("tempfile.mkstemp", return_value=(123, "/tmp/maya-test-kokoro.wav")), \
             patch("os.close"), \
             patch("wave.open"), \
             patch("pathlib.Path.stat"), \
             patch("pathlib.Path.unlink"), \
             patch("subprocess.Popen") as mock_popen:
            mock_engine.create.return_value = (([0.1] * 24000), 24000)
            mock_play = MagicMock()
            mock_play.wait.side_effect = subprocess.TimeoutExpired(cmd="paplay", timeout=10.0)
            mock_popen.return_value = mock_play

            provider._run(1, "Hello world", voice, 1.0, callbacks)

            mock_play.kill.assert_called_once()
            callbacks.failed.assert_called_once()
            self.assertIn("timed out", callbacks.failed.call_args[0][0])

    def test_tts_manager_watchdog_timeout_recovers_speaking_state(self):
        manager = TTSManager()
        failed_signals = []
        manager.failed.connect(lambda gen, msg: failed_signals.append((gen, msg)))

        with manager._lock:
            manager._generation = 5
            manager._chunk_active = True
            manager._speaking = True

        manager._on_watchdog_timeout(5)

        self.assertFalse(manager._chunk_active)
        self.assertFalse(manager._speaking)
        self.assertEqual(failed_signals, [(5, "TTS chunk watchdog timeout")])


if __name__ == "__main__":
    unittest.main()
