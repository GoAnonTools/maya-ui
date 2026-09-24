"""User configuration and lifecycle manager for local STT."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .base import AudioDevice, STTCallbacks
from .whisper_cpp_provider import WhisperCppProvider
from ..audio import selected_source


CONFIG_PATH = Path.home() / ".config" / "maya" / "stt.json"
log = logging.getLogger("maya.stt.manager")


class _Callbacks(STTCallbacks):
    def __init__(self, manager: "STTManager", generation: int) -> None:
        self.manager = manager
        self.generation = generation

    def started(self) -> None:
        if self.manager._valid(self.generation):
            self.manager.started.emit(self.generation)

    def transcribing(self) -> None:
        log.warning("WAKE_DEBUG STTManager transcribing callback generation=%d valid=%s", self.generation, self.manager._valid(self.generation))
        if self.manager._valid(self.generation):
            self.manager.transcribing.emit(self.generation)

    def transcript(self, text: str) -> None:
        log.warning("WAKE_DEBUG STTManager transcript callback generation=%d valid=%s text=%r", self.generation, self.manager._valid(self.generation), text)
        if self.manager._valid(self.generation):
            self.manager._set_listening(False)
            self.manager.transcriptReady.emit(self.generation, text)

    def failed(self, message: str) -> None:
        log.warning("WAKE_DEBUG STTManager failure callback generation=%d valid=%s detail=%r", self.generation, self.manager._valid(self.generation), message)
        if self.manager._valid(self.generation):
            self.manager._set_listening(False)
            self.manager.failed.emit(self.generation, message)

    def level(self, value: float) -> None:
        if self.manager._valid(self.generation):
            self.manager.levelChanged.emit(value)


class STTManager(QObject):
    started = Signal(int)
    transcribing = Signal(int)
    transcriptReady = Signal(int, str)
    failed = Signal(int, str)
    levelChanged = Signal(float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._generation = 0
        self._listening = False
        self._config = self._load_config()
        self._provider = WhisperCppProvider()

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("enabled", True))

    @property
    def is_listening(self) -> bool:
        with self._lock:
            return self._listening

    def start(self) -> int | None:
        if not self.enabled:
            return None
        self.cancel()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._listening = True
        device = selected_source()
        language = str(self._config.get("language", "auto"))
        model = str(self._config.get("model", "base"))
        self._provider.start(device, language, model, _Callbacks(self, generation))
        return generation

    def stop(self) -> None:
        self._provider.stop()

    def cancel(self) -> None:
        with self._lock:
            self._generation += 1
            self._listening = False
        self._provider.cancel()
        self.levelChanged.emit(0.0)

    def transcribe_file(self, path: str) -> int | None:
        if not self.enabled:
            log.warning("WAKE_DEBUG STTManager transcribe_file skipped: STT disabled path=%s", path)
            return None
        self.cancel()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._listening = True
        language = str(self._config.get("language", "auto"))
        model = str(self._config.get("model", "base"))
        log.warning("WAKE_DEBUG STTManager transcribe_file entry path=%s generation=%d model=%s language=%s", path, generation, model, language)
        self._provider.transcribe_file(path, language, model, _Callbacks(self, generation))
        log.warning("WAKE_DEBUG STTManager transcribe_file worker started generation=%d", generation)
        return generation

    def list_devices(self) -> list[AudioDevice]:
        return self._provider.list_devices()

    def _valid(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _set_listening(self, value: bool) -> None:
        with self._lock:
            self._listening = value

    @staticmethod
    def _load_config() -> dict:
        defaults = {"enabled": True, "provider": "whisper.cpp", "model": "base", "device": "default", "language": "auto"}
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except (OSError, ValueError):
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")
        return defaults
