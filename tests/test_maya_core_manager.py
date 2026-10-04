import unittest

from backend.core.maya_core_manager import MayaCoreLifecycleManager
from backend.llm import LLMCapabilities, ProviderManager, ProviderRegistry


class FakeProvider:
    capabilities = LLMCapabilities(streaming=True, tool_calls=False)

    def __init__(self, name):
        self.name = name

    def stream(self, _request):
        yield from ()

    def close(self):
        pass


class MayaCoreLifecycleTests(unittest.TestCase):
    def make_manager(self):
        registry = ProviderRegistry()
        registry.register(FakeProvider("maya_core"))
        registry.register(FakeProvider("newelle"))
        return ProviderManager(registry, "maya_core")

    def make_lifecycle(self, manager, is_request_active=lambda: False):
        return MayaCoreLifecycleManager(
            manager,
            is_request_active=is_request_active,
            auto_start=False,
        )

    def test_maya_core_available_at_startup_stays_active(self):
        manager = self.make_manager()
        lifecycle = self.make_lifecycle(manager)

        lifecycle.handle_health_result(True)

        self.assertEqual(manager.current_provider_name, "maya_core")
        self.assertTrue(manager.availability("maya_core").available)

    def test_unavailable_maya_core_falls_back_to_newelle(self):
        manager = self.make_manager()
        lifecycle = self.make_lifecycle(manager)
        changed = []
        lifecycle.providerChanged.connect(lambda: changed.append(manager.current_provider_name))

        lifecycle.handle_health_result(False, "connection refused")

        self.assertEqual(manager.current_provider_name, "newelle")
        self.assertFalse(manager.availability("maya_core").available)
        self.assertEqual(changed, ["newelle"])

    def test_maya_core_returns_after_failure_and_is_restored(self):
        manager = self.make_manager()
        lifecycle = self.make_lifecycle(manager)

        lifecycle.handle_health_result(False, "connection refused")
        lifecycle.handle_health_result(True)

        self.assertEqual(manager.current_provider_name, "maya_core")
        self.assertTrue(manager.availability("maya_core").available)

    def test_active_request_is_not_interrupted_during_recovery(self):
        active = True
        manager = self.make_manager()
        lifecycle = self.make_lifecycle(manager, is_request_active=lambda: active)

        lifecycle.handle_health_result(False, "connection refused")
        lifecycle.handle_health_result(True)

        self.assertEqual(manager.current_provider_name, "maya_core")
        active = False
        lifecycle.request_finished()
        self.assertEqual(manager.current_provider_name, "maya_core")


if __name__ == "__main__":
    unittest.main()
