"""User configuration and lifecycle manager for Maya wake detection."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .sherpa_provider import SherpaProvider

log = logging.getLogger("maya.wake.manager")

CONFIG_PATH = Path.home() / ".config" / "maya" / "wake.json"


class _Callbacks:
    def __init__(self, manager: "WakeManager") -> None:
        self.manager = manager

    def detected(self) -> None:
        self.manager.detected.emit()

    def command_ready(self, path: str) -> None:
        self.manager._armed = False
        self.manager.commandReady.emit(path)

    def failed(self, message: str) -> None:
        self.manager._set_lifecycle("error", message)
        self.manager.failed.emit(message)

    def level(self, value: float) -> None:
        self.manager._capture_level(value)
        self.manager.levelChanged.emit(value)


class WakeManager(QObject):
    detected = Signal()
    commandReady = Signal(str)
    failed = Signal(str)
    levelChanged = Signal(float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = self._load_config()
        self._provider = SherpaProvider()
        self._armed = False
        self._lifecycle_lock = threading.Lock()
        self._lifecycle = "stopped"

    @property
    def lifecycle(self) -> str:
        with self._lifecycle_lock:
            return self._lifecycle

    def _set_lifecycle(self, state: str, detail: str = "") -> None:
        with self._lifecycle_lock:
            self._lifecycle = state
        suffix = f": {detail}" if detail else ""
        log.info("Wake lifecycle -> %s%s", state, suffix)

    def _capture_level(self, value: float) -> None:
        if self.lifecycle == "starting":
            self._set_lifecycle("listening")

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("enabled", True))

    @property
    def sensitivity(self) -> float:
        return float(self._config.get("sensitivity", 0.6))

    def start(self) -> None:
        if not self.enabled:
            self.stop("disabled")
            return
        if self._armed and self._provider.resume():
            self._set_lifecycle("listening", "resume requested")
            log.info("Wake resume reason=state returned to idle/speaking")
            return
        if self._armed:
            self._set_lifecycle("restarting", "capture was no longer alive")
            log.warning("Wake resume could not restore capture; restarting detector")
        else:
            self._set_lifecycle("starting", "startup or idle transition")
        self._armed = True
        self._provider.start(self.sensitivity, _Callbacks(self))

    def stop(self, reason: str = "requested") -> None:
        log.info("Wake stop reason=%s", reason)
        self._armed = False
        self._set_lifecycle("stopped", reason)
        self._provider.stop(reason)

    def set_mode(self, state: str) -> None:
        if state in {"idle", "speaking"}:
            self.start()
        else:
            log.info("Wake pause reason=maya state '%s'", state)
            command_active = self._provider.pause(f"maya state '{state}'")
            if command_active:
                self._set_lifecycle("listening", "continuing post-wake command capture")
            else:
                self._armed = False
                self._set_lifecycle("paused", state)

    def release_command(self, path: str) -> None:
        self._provider.release_command(path)

    def disable_runtime(self) -> None:
        self.stop("runtime disabled")

    @staticmethod
    def _load_config() -> dict:
        defaults = {"enabled": True, "provider": "sherpa-onnx", "phrase": "maya", "sensitivity": 0.6}
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except (OSError, ValueError):
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")
        return defaults

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self._config, indent=2) + "\n", encoding="utf-8")

    def set_enabled(self, value: bool) -> None:
        self._config["enabled"] = bool(value)
        self.save()
        if value:
            self.start()
        else:
            self.stop("disabled by configuration")

    def set_sensitivity(self, value: float) -> None:
        self._config["sensitivity"] = max(0.0, min(1.0, float(value)))
        self.save()
        if self._armed:
            self.stop("sensitivity changed")
            self.start()
