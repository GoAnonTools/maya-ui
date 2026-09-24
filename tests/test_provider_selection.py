import unittest
from unittest.mock import MagicMock, patch

from backend.maya_controller import MayaController
from backend.llm.defaults import create_default_provider_manager
from backend.llm.registry import ProviderRegistry
from backend.llm.base import LLMProvider, LLMRequest, LLMTextDelta


class DummyProvider(LLMProvider):
    def __init__(self, name: str, display_name: str):
        self.name = name
        self.display_name = display_name

    def stream(self, request: LLMRequest):
        yield LLMTextDelta(f"Response from {self.name}")


class ProviderSelectionTest(unittest.TestCase):
    def setUp(self):
        self.registry = ProviderRegistry()
        self.p1 = DummyProvider("newelle", "Newelle Local")
        self.p2 = DummyProvider("ministral_14b", "Ministral 14B")
        self.registry.register(self.p1)
        self.registry.register(self.p2)

        from backend.llm.manager import ProviderManager
        self.manager = ProviderManager(self.registry, default_provider_name="newelle")

        self.memory_service = MagicMock()
        self.memory_service.settings.enabled = False

        self.controller = MayaController(memory_service=self.memory_service, provider_manager=self.manager)

    def tearDown(self):
        if hasattr(self, "controller"):
            self.controller._wake.stop()
            self.controller._tts.stop()

    def test_initial_provider_properties(self):
        self.assertEqual(self.controller.currentProviderName, "newelle")
        self.assertEqual(self.controller.currentProviderDisplayName, "Newelle Local")
        available = self.controller.availableProviders
        self.assertEqual(len(available), 2)
        self.assertEqual(available[0]["id"], "newelle")
        self.assertEqual(available[1]["id"], "ministral_14b")

    def test_select_provider_updates_state_and_emits_signal(self):
        signal_emitted = False

        def on_provider_changed():
            nonlocal signal_emitted
            signal_emitted = True

        self.controller.providerChanged.connect(on_provider_changed)

        self.controller.select_provider("ministral_14b")

        self.assertTrue(signal_emitted)
        self.assertEqual(self.controller.currentProviderName, "ministral_14b")
        self.assertEqual(self.controller.currentProviderDisplayName, "Ministral 14B")

    def test_select_unknown_provider_handled_safely(self):
        signal_emitted = False

        def on_provider_changed():
            nonlocal signal_emitted
            signal_emitted = True

        self.controller.providerChanged.connect(on_provider_changed)

        self.controller.select_provider("non_existent_provider")

        self.assertFalse(signal_emitted)
        self.assertEqual(self.controller.currentProviderName, "newelle")

    def test_chat_id_remains_unchanged_after_provider_switch(self):
        self.controller._chat_id = 42

        self.controller.select_provider("ministral_14b")

        self.assertEqual(self.controller._chat_id, 42)
        self.assertEqual(self.controller.currentProviderName, "ministral_14b")

    def test_next_request_uses_selected_provider(self):
        self.controller.select_provider("ministral_14b")

        with patch.object(self.controller, "_start_provider_request") as mock_start:
            mock_start.return_value = True
            self.controller._submit_request("Hello", "", chat_id=123, language="en", source="typed")

            mock_start.assert_called_once()
            self.assertEqual(self.manager.current_provider_name, "ministral_14b")


if __name__ == "__main__":
    unittest.main()
