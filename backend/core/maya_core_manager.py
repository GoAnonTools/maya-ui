"""Background lifecycle management for the optional local Maya Core service."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from ..llm.manager import ProviderManager

log = logging.getLogger("maya.core.lifecycle")


def _default_config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "maya" / "core.json"


def _read_config(path: Path | None = None) -> dict:
    config_path = path or Path(os.environ.get("MAYA_CORE_CONFIG", _default_config_path()))
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _config_float(config: dict, key: str, default: float) -> float:
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return default


def _configured_launcher(config: dict) -> list[str] | None:
    value = os.environ.get("MAYA_CORE_LAUNCHER")
    if value is None:
        value = config.get("launcher", config.get("command"))
    if isinstance(value, str):
        value = shlex.split(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        command = [str(part) for part in value if str(part)]
        return command or None
    return None


def check_maya_core(url: str, timeout: float = 0.8) -> tuple[bool, str | None]:
    """Perform one small health request; intended to run off the UI thread."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if 200 <= response.status < 300:
                return True, None
            return False, f"health check returned HTTP {response.status}"
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return False, str(exc) or "Maya Core is unavailable"


class _HealthWorker(QObject):
    result = Signal(bool, str)

    def __init__(self, health_url: str, interval_seconds: float, probe: Callable[[str], tuple[bool, str | None]]):
        super().__init__()
        self._health_url = health_url
        self._interval_seconds = max(0.2, interval_seconds)
        self._probe = probe
        self._timer: QTimer | None = None

    @Slot()
    def start(self) -> None:
        self._timer = QTimer(self)
        self._timer.setInterval(round(self._interval_seconds * 1000))
        self._timer.timeout.connect(self.check)
        self._timer.start()
        self.check()

    @Slot()
    def check(self) -> None:
        try:
            available, reason = self._probe(self._health_url)
        except Exception as exc:
            log.exception("Maya Core health probe failed")
            available, reason = False, str(exc) or "health probe failed"
        self.result.emit(bool(available), reason or "")


class MayaCoreLifecycleManager(QObject):
    """Keeps Maya Core availability and active-provider state synchronized.

    Health checks and optional startup happen in a worker thread. Provider
    registry updates and selection happen in the QObject's owning (UI) thread.
    """

    providerChanged = Signal()
    availabilityChanged = Signal(bool)

    def __init__(
        self,
        provider_manager: ProviderManager,
        *,
        parent: QObject | None = None,
        health_url: str = "http://127.0.0.1:8080/health",
        interval_seconds: float = 5.0,
        startup_timeout_seconds: float = 15.0,
        launcher: Sequence[str] | str | None = None,
        config_path: Path | None = None,
        is_request_active: Callable[[], bool] | None = None,
        probe: Callable[[str], tuple[bool, str | None]] = check_maya_core,
        auto_start: bool = True,
    ):
        super().__init__(parent)
        self._provider_manager = provider_manager
        config = _read_config(config_path)
        self._health_url = str(config.get("health_url", health_url))
        self._interval_seconds = _config_float(config, "check_interval_seconds", interval_seconds)
        self._startup_timeout_seconds = max(0.0, _config_float(config, "startup_timeout_seconds", startup_timeout_seconds))
        self._is_request_active = is_request_active or (lambda: False)
        self._probe = probe
        configured = launcher if launcher is not None else _configured_launcher(config)
        if isinstance(configured, str):
            configured = shlex.split(configured)
        self._launcher = [str(part) for part in configured] if configured else None
        self._launcher_process: subprocess.Popen | None = None
        self._launch_attempted = False
        self._pending_fallback = False
        self._auto_recover = False
        self._started = False
        self._thread: QThread | None = None
        self._worker: _HealthWorker | None = None
        self._startup_timer: QTimer | None = None
        if auto_start:
            self.start()

    @property
    def health_url(self) -> str:
        return self._health_url

    @property
    def running(self) -> bool:
        return self._started

    def start(self) -> None:
        if self._started or not self._provider_manager.registry.contains("maya_core"):
            return
        self._started = True
        thread = QThread(self)
        worker = _HealthWorker(self._health_url, self._interval_seconds, self._probe)
        worker.moveToThread(thread)
        thread.started.connect(worker.start)
        worker.result.connect(self._on_health_result)
        thread.finished.connect(worker.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._started = False
        thread.quit()
        thread.wait(1500)
        self._thread = None
        self._worker = None
        self._stop_startup_timer()

    @Slot(bool, str)
    def _on_health_result(self, available: bool, reason: str) -> None:
        self.handle_health_result(available, reason or None)

    @Slot(bool, str)
    def handle_health_result(self, available: bool, reason: str | None = None) -> None:
        """Apply a probe result on the UI thread; public for deterministic tests."""
        registry = self._provider_manager.registry
        if not registry.contains("maya_core"):
            return
        registry.set_available("maya_core", available, reason)
        self.availabilityChanged.emit(available)

        if available:
            self._launch_attempted = False
            self._stop_startup_timer()
            self._pending_fallback = False
            if self._auto_recover and not self._is_request_active() and self._provider_manager.current_provider_name == "newelle":
                self._select_maya_core()
            return

        if not self._launch_attempted:
            self._launch_attempted = True
            self._start_configured_launcher()
            if self._launcher and self._startup_timeout_seconds > 0:
                self._start_startup_timer()

        if self._provider_manager.current_provider_name == "maya_core":
            if self._is_request_active():
                self._pending_fallback = True
            else:
                self._select_newelle()

    def report_provider_failure(self) -> None:
        """Mark Maya Core down after a failed request and switch when safe."""
        if self._provider_manager.current_provider_name != "maya_core":
            return
        self.handle_health_result(False, "Maya Core request failed")
        self.request_finished()

    def request_finished(self) -> None:
        if self._pending_fallback and not self._is_request_active():
            self._pending_fallback = False
            self._select_newelle()

    def _select_newelle(self) -> None:
        if not self._provider_manager.registry.contains("newelle"):
            return
        try:
            self._provider_manager.select("newelle")
        except Exception:
            log.exception("Could not fall back to Newelle")
            return
        self._auto_recover = True
        self.providerChanged.emit()

    def _select_maya_core(self) -> None:
        try:
            self._provider_manager.select("maya_core")
        except Exception:
            log.exception("Could not restore Maya Core after health recovery")
            return
        self._auto_recover = False
        self._pending_fallback = False
        self.providerChanged.emit()

    def _start_configured_launcher(self) -> None:
        if not self._launcher:
            return
        try:
            self._launcher_process = subprocess.Popen(
                self._launcher,
                close_fds=True,
                start_new_session=True,
            )
            log.info("Started configured Maya Core launcher: %s", self._launcher[0])
        except (OSError, ValueError):
            log.exception("Could not start configured Maya Core launcher")

    def _start_startup_timer(self) -> None:
        if self._startup_timer is None:
            self._startup_timer = QTimer(self)
            self._startup_timer.setSingleShot(True)
            self._startup_timer.timeout.connect(self._on_startup_timeout)
        self._startup_timer.start(round(self._startup_timeout_seconds * 1000))

    def _stop_startup_timer(self) -> None:
        if self._startup_timer is not None:
            self._startup_timer.stop()

    @Slot()
    def _on_startup_timeout(self) -> None:
        if self._provider_manager.current_provider_name == "maya_core":
            self._select_newelle()
