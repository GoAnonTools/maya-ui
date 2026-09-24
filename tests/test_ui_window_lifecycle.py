import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl, QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine


class DummyMayaController(QObject):
    stateChanged = Signal()
    detailChanged = Signal()
    userTextChanged = Signal()
    assistantTextChanged = Signal()
    providerChanged = Signal()

    def __init__(self):
        super().__init__()
        self._state = "idle"
        self._detail = ""
        self._user_text = ""
        self._assistant_text = ""
        self._provider_name = "newelle"
        self._provider_display_name = "Newelle Local"
        self._available_providers = [
            {"id": "newelle", "displayName": "Newelle Local", "available": True, "reason": None}
        ]

    def _get_state(self):
        return self._state

    def _get_detail(self):
        return self._detail

    def _get_user_text(self):
        return self._user_text

    def _get_assistant_text(self):
        return self._assistant_text

    def _get_current_provider_name(self):
        return self._provider_name

    def _get_current_provider_display_name(self):
        return self._provider_display_name

    def _get_available_providers(self):
        return self._available_providers

    state = Property(str, _get_state, notify=stateChanged)
    detail = Property(str, _get_detail, notify=detailChanged)
    userText = Property(str, _get_user_text, notify=userTextChanged)
    assistantText = Property(str, _get_assistant_text, notify=assistantTextChanged)
    currentProviderName = Property(str, _get_current_provider_name, notify=providerChanged)
    currentProviderDisplayName = Property(str, _get_current_provider_display_name, notify=providerChanged)
    availableProviders = Property(list, _get_available_providers, notify=providerChanged)

    @Slot(int)
    def set_demo_state(self, num):
        pass

    @Slot()
    def reset(self):
        pass

    @Slot(str)
    def submit(self, text):
        pass

    @Slot()
    def start_ptt(self):
        pass

    @Slot()
    def stop_ptt(self):
        pass

    @Slot(str)
    def select_provider(self, name):
        pass


class WindowLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.controller = DummyMayaController()
        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("mayaController", self.controller)
        qml_path = Path(__file__).parent.parent / "qml" / "Main.qml"
        self.engine.load(QUrl.fromLocalFile(str(qml_path)))
        self.root_objects = self.engine.rootObjects()
        self.assertTrue(len(self.root_objects) > 0, "Failed to load Main.qml")
        self.root = self.root_objects[0]
        self.workspace = self.root.findChild(QObject, "mayaWorkspace")
        self.assertIsNotNone(self.workspace, "mayaWorkspace not found")

    def test_initial_window_states(self):
        # Compact window starts hidden until show() is called
        self.assertFalse(self.workspace.isVisible())

    def test_opening_workspace_hides_compact_root_window(self):
        self.root.setVisible(True)
        self.assertTrue(self.root.isVisible())
        self.assertFalse(self.workspace.isVisible())

        # Open workspace
        self.workspace.openWorkspace()
        self.assertTrue(self.workspace.isVisible())
        self.assertFalse(self.root.isVisible())

    def test_closing_workspace_restores_compact_root_window(self):
        self.root.setVisible(True)
        self.workspace.openWorkspace()
        self.assertTrue(self.workspace.isVisible())
        self.assertFalse(self.root.isVisible())

        # Close workspace
        self.workspace.hide()
        self.assertFalse(self.workspace.isVisible())
        self.assertTrue(self.root.isVisible())

    def test_repeated_open_close_cycles(self):
        self.root.setVisible(True)

        for _ in range(3):
            self.workspace.openWorkspace()
            self.assertTrue(self.workspace.isVisible())
            self.assertFalse(self.root.isVisible())

            self.workspace.hide()
            self.assertFalse(self.workspace.isVisible())
            self.assertTrue(self.root.isVisible())


if __name__ == "__main__":
    unittest.main()
