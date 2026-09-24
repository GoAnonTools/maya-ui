import unittest
from unittest.mock import MagicMock, patch

from backend.wake.manager import WakeManager, _Callbacks


class WakeManagerRecoveryTest(unittest.TestCase):
    @patch.object(WakeManager, "_load_config", return_value={"enabled": True, "sensitivity": 0.6})
    def test_armed_failure_schedules_recovery(self, mock_cfg):
        manager = WakeManager()
        manager._armed = True
        manager._provider = MagicMock()

        callbacks = _Callbacks(manager)

        with patch.object(manager, "_schedule_recovery") as mock_schedule:
            callbacks.failed("test error")

            self.assertEqual(manager._retry_count, 1)
            self.assertTrue(manager.lifecycle.startswith("restarting"))
            mock_schedule.assert_called_once_with(1.0)  # Base delay 1.0s

    @patch.object(WakeManager, "_load_config", return_value={"enabled": True, "sensitivity": 0.6})
    def test_recovery_exponential_backoff_and_rate_limiting(self, mock_cfg):
        manager = WakeManager()
        manager._armed = True
        manager._provider = MagicMock()
        callbacks = _Callbacks(manager)

        delays = []
        def capture_schedule(delay):
            delays.append(delay)

        with patch.object(manager, "_schedule_recovery", side_effect=capture_schedule):
            for i in range(5):
                callbacks.failed(f"error {i}")

            # Delays: 1.0, 2.0, 4.0, 8.0, 16.0
            self.assertEqual(delays, [1.0, 2.0, 4.0, 8.0, 16.0])
            self.assertEqual(manager._retry_count, 5)

            # 6th failure exceeds max retries
            callbacks.failed("error 6")
            self.assertEqual(len(delays), 5)
            self.assertEqual(manager.lifecycle, "error")

    @patch.object(WakeManager, "_load_config", return_value={"enabled": True, "sensitivity": 0.6})
    def test_unarmed_failure_does_not_schedule_recovery(self, mock_cfg):
        manager = WakeManager()
        manager._armed = False
        manager._provider = MagicMock()
        callbacks = _Callbacks(manager)

        with patch.object(manager, "_schedule_recovery") as mock_schedule:
            callbacks.failed("unarmed error")

            self.assertEqual(manager._retry_count, 0)
            mock_schedule.assert_not_called()
            self.assertEqual(manager.lifecycle, "error")

    @patch.object(WakeManager, "_load_config", return_value={"enabled": True, "sensitivity": 0.6})
    def test_stop_clears_recovery_and_retry_count(self, mock_cfg):
        manager = WakeManager()
        manager._armed = True
        manager._retry_count = 3
        manager._recovery_timer = MagicMock()
        manager._provider = MagicMock()

        manager.stop("user request")

        self.assertFalse(manager._armed)
        self.assertEqual(manager._retry_count, 0)
        self.assertIsNone(manager._recovery_timer)
        self.assertEqual(manager.lifecycle, "stopped")

    @patch.object(WakeManager, "_load_config", return_value={"enabled": True, "sensitivity": 0.6})
    def test_execute_recovery_restarts_provider_if_armed(self, mock_cfg):
        manager = WakeManager()
        manager._armed = True
        manager._provider = MagicMock()

        manager._execute_recovery()

        manager._provider.start.assert_called_once()

    @patch.object(WakeManager, "_load_config", return_value={"enabled": True, "sensitivity": 0.6})
    def test_execute_recovery_skipped_if_disarmed(self, mock_cfg):
        manager = WakeManager()
        manager._armed = False
        manager._provider = MagicMock()

        manager._execute_recovery()

        manager._provider.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
