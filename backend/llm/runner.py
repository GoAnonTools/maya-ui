"""Qt worker for consuming the provider-neutral streaming interface."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from .base import LLMProvider, LLMProviderError, LLMRequest

log = logging.getLogger("maya.llm.runner")


class LLMStreamWorker(QObject):
    eventReady = Signal(object)
    streamEnded = Signal()
    failed = Signal(str)
    # Emitted unconditionally when run() exits, including on cancellation.
    # streamEnded and failed are suppressed by the cancellation guard, so
    # thread teardown must be wired to this signal, not to those two.
    runCompleted = Signal()

    def __init__(self, provider: LLMProvider, request: LLMRequest) -> None:
        super().__init__()
        self._provider = provider
        self._request = request
        self._cancelled = False
        self._lock = threading.Lock()

    @Slot()
    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
        log.info("LLMStreamWorker cancellation requested provider=%s", getattr(self._provider, "name", "unknown"))
        if hasattr(self._provider, "cancel") and callable(getattr(self._provider, "cancel")):
            try:
                self._provider.cancel()
            except Exception:
                log.exception("Error calling provider.cancel()")

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @Slot()
    def run(self) -> None:
        # runCompleted is emitted in the finally block so it always fires,
        # including when an early return exits due to cancellation.  The
        # try/except/else block below suppresses streamEnded/failed on
        # cancellation (correct), but that made thread.quit() unreachable
        # when wired to those signals.  Wire thread teardown to runCompleted
        # instead (see MayaController._start_provider_request).
        try:
            try:
                for event in self._provider.stream(self._request):
                    if self.is_cancelled():
                        log.info("LLMStreamWorker loop stopped due to cancellation")
                        return
                    self.eventReady.emit(event)
                if self.is_cancelled():
                    log.info("LLMStreamWorker stream finished but cancelled before completion signal")
                    return
            except LLMProviderError as exc:
                if not self.is_cancelled():
                    self.failed.emit(str(exc))
            except Exception:
                if not self.is_cancelled():
                    log.exception("Unexpected LLM provider failure provider=%s", getattr(self._provider, "name", "unknown"))
                    self.failed.emit("Assistant failed")
            else:
                if not self.is_cancelled():
                    self.streamEnded.emit()
        finally:
            log.info("LLMStreamWorker run() exiting cancelled=%s", self.is_cancelled())
            self.runCompleted.emit()
