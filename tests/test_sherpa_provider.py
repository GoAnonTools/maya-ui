import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from backend.wake.sherpa_provider import SherpaProvider, decoder_result_details


class DecoderResultDetailsTest(unittest.TestCase):
    def test_plain_string_result(self):
        self.assertEqual(decoder_result_details("HEY_MAYA"), ("HEY_MAYA", [], []))

    def test_structured_result(self):
        result = SimpleNamespace(keyword="HEY MAYA", tokens=["HEY", "MAYA"], timestamps=[0.1, 0.2])
        self.assertEqual(decoder_result_details(result), ("HEY MAYA", ["HEY", "MAYA"], [0.1, 0.2]))


class SherpaProviderEOFTest(unittest.TestCase):
    @patch("backend.wake.sherpa_provider.selected_source", return_value="default")
    @patch("subprocess.Popen")
    @patch("pathlib.Path.exists", return_value=True)
    def test_unexpected_eof_triggers_failure_callback(self, mock_exists, mock_popen, mock_source):
        provider = SherpaProvider()
        callbacks = MagicMock()
        provider._generation = 1
        provider._paused = False

        # Mock Popen stdout.read to return EOF immediately
        mock_process = MagicMock()
        mock_process.stdout.read.return_value = b""
        mock_process.poll.return_value = 0
        mock_popen.return_value = mock_process

        mock_kws = MagicMock()
        mock_kws.create_stream.return_value = MagicMock()

        with patch.dict("sys.modules", {"sherpa_onnx": MagicMock(KeywordSpotter=MagicMock(return_value=mock_kws))}):
            provider._run(generation=1, sensitivity=0.6, callbacks=callbacks)

        callbacks.failed.assert_called_once_with("audio capture stream closed unexpectedly")
        self.assertEqual(provider.state, "error")

    @patch("backend.wake.sherpa_provider.selected_source", return_value="default")
    @patch("subprocess.Popen")
    @patch("pathlib.Path.exists", return_value=True)
    def test_intentional_stop_does_not_trigger_failure(self, mock_exists, mock_popen, mock_source):
        provider = SherpaProvider()
        callbacks = MagicMock()
        provider._generation = 1
        provider._paused = False

        mock_process = MagicMock()
        mock_process.stdout.read.return_value = b""
        mock_process.poll.return_value = 0
        mock_popen.return_value = mock_process

        # Simulate stop being called before EOF occurs (generation mismatch)
        provider.stop("test intentional stop")

        mock_kws = MagicMock()
        mock_kws.create_stream.return_value = MagicMock()

        with patch.dict("sys.modules", {"sherpa_onnx": MagicMock(KeywordSpotter=MagicMock(return_value=mock_kws))}):
            provider._run(generation=1, sensitivity=0.6, callbacks=callbacks)

        callbacks.failed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
