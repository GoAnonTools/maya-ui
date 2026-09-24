"""Qt worker for consuming the provider-neutral streaming interface."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from .base import LLMProvider, LLMProviderError, LLMRequest

log = logging.getLogger("maya.llm.runner")


class LLMStreamWorker(QObject):
    eventReady = Signal(object)
    streamEnded = Signal()
    failed = Signal(str)

    def __init__(self, provider: LLMProvider, request: LLMRequest) -> None:
        super().__init__()
        self._provider = provider
        self._request = request

    @Slot()
    def run(self) -> None:
        try:
            for event in self._provider.stream(self._request):
                self.eventReady.emit(event)
        except LLMProviderError as exc:
            self.failed.emit(str(exc))
        except Exception:
            log.exception("Unexpected LLM provider failure provider=%s", self._provider.name)
            self.failed.emit("Assistant failed")
        else:
            self.streamEnded.emit()
