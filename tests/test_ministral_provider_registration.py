import json
import unittest

from backend.llm.defaults import PROVIDER_CONFIG_PATH, create_default_provider_manager
from backend.llm.openai_compatible_provider import OpenAICompatibleProvider
from backend.llm.base import LLMProviderError


class MinistralProviderRegistrationTests(unittest.TestCase):
    def test_configuration_entry_has_required_non_secret_fields(self):
        entries = json.loads(PROVIDER_CONFIG_PATH.read_text(encoding="utf-8"))
        ministral = next(entry for entry in entries if entry["id"] == "ministral_14b")

        self.assertEqual(ministral["friendly_name"], "Ministral 14B")
        self.assertEqual(ministral["provider_type"], "openai_compatible")
        self.assertEqual(ministral["model_name"], "ministral-14b-latest")
        self.assertEqual(ministral["base_url"], "https://api.mistral.ai/v1")
        self.assertEqual(ministral["credential_ref"], "maya.provider.ministral_14b.api_key")
        self.assertFalse(any("key" in key.lower() and key != "credential_ref" for key in ministral))

    def test_registered_ministral_can_be_selected_and_switched_back(self):
        lookup = {"maya.provider.ministral_14b.api_key": "test-secret"}
        manager = create_default_provider_manager(credential_resolver=lookup.get)

        self.assertEqual(manager.current_provider_name, "newelle")
        self.assertIn("ministral_14b", manager.provider_names)
        status = manager.availability("ministral_14b")
        self.assertTrue(status.available)
        self.assertEqual(status.display_name, "Ministral 14B")

        provider = manager.registry.get("ministral_14b")
        self.assertIsInstance(provider, OpenAICompatibleProvider)
        self.assertEqual(provider.model, "ministral-14b-latest")
        self.assertEqual(provider.base_url, "https://api.mistral.ai/v1")
        self.assertEqual(provider.credential_ref, "maya.provider.ministral_14b.api_key")
        self.assertEqual(provider.capabilities.streaming, True)
        self.assertEqual(provider.capabilities.tool_calls, True)

        manager.select("ministral_14b")
        self.assertEqual(manager.current_provider_name, "ministral_14b")
        self.assertEqual(manager.current_provider_display_name, "Ministral 14B")
        manager.select("newelle")
        self.assertEqual(manager.current_provider_name, "newelle")

    def test_missing_credential_marks_provider_unavailable_without_changing_default(self):
        manager = create_default_provider_manager(credential_resolver=lambda _ref: None)

        self.assertEqual(manager.current_provider_name, "newelle")
        status = manager.availability("ministral_14b")
        self.assertFalse(status.available)
        self.assertEqual(status.reason, "credential is unavailable")
        with self.assertRaises(LLMProviderError):
            manager.select("ministral_14b")
        self.assertEqual(manager.current_provider_name, "newelle")

    def test_unresolved_credential_marks_provider_unavailable(self):
        manager = create_default_provider_manager(credential_resolver=lambda _ref: None)

        status = manager.availability("ministral_14b")
        self.assertFalse(status.available)
        self.assertEqual(status.reason, "credential is unavailable")


if __name__ == "__main__":
    unittest.main()
