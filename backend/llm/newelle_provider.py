"""Newelle GUI API adapter for Maya's provider-neutral LLM interface."""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator

from PySide6.QtCore import QObject, Signal, Slot

from .base import (
    LLMCapabilities,
    LLMCompleted,
    LLMConversation,
    LLMEvent,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    LLMState,
    LLMTextDelta,
)
from ..newelle_client import NewelleClient


_END = object()


class NewelleProvider(QObject):
    """Adapts NewelleClient signals to Maya's synchronous event stream.

    ``stream`` is consumed by ``LLMStreamWorker``. It waits on a thread-safe
    queue while NewelleClient and its Qt signals continue on the controller's
    Qt thread.
    """

    _start_requested = Signal(str, object, object)

    name = "newelle"
    capabilities = LLMCapabilities(streaming=True, tool_calls=True)

    def __init__(self, parent: QObject | None = None, *, client: NewelleClient | None = None):
        super().__init__(parent)
        self._client = client or NewelleClient(self)
        self._events_lock = threading.Lock()
        self._active_events: queue.Queue | None = None
        self._last_text = ""
        self._closed = False
        self._start_requested.connect(self._start_transport)
        self._client.chatReady.connect(self._on_chat_ready)
        self._client.stateEvent.connect(self._on_state_event)
        self._client.textChanged.connect(self._on_text_changed)
        self._client.completed.connect(self._on_completed)
        self._client.failed.connect(self._on_failed)

    def stream(self, request: LLMRequest) -> Iterator[LLMEvent]:
        if self._closed:
            raise LLMProviderError("provider", "Newelle unavailable", provider=self.name)
        prompt = self._latest_user_message(request.messages)
        events: queue.Queue = queue.Queue()
        with self._events_lock:
            if self._active_events is not None:
                raise LLMProviderError("provider", "Assistant busy", provider=self.name, retryable=True)
            self._active_events = events
            self._last_text = ""

        self._start_requested.emit(prompt, request.conversation_id, events)
        try:
            while True:
                item = events.get()
                if item is _END:
                    break
                if isinstance(item, LLMProviderError):
                    raise item
                yield item
        finally:
            with self._events_lock:
                if self._active_events is events:
                    self._active_events = None

    @staticmethod
    def _latest_user_message(messages: tuple[LLMMessage, ...]) -> str:
        for message in reversed(messages):
            if message.role == "user":
                return message.content
        raise LLMProviderError("invalid_request", "Newelle requires a user message", provider="newelle")

    @Slot(str, object, object)
    def _start_transport(self, prompt: str, conversation_id, events: queue.Queue) -> None:
        if self._closed:
            events.put(LLMProviderError("provider", "Newelle unavailable", provider=self.name))
            events.put(_END)
            return
        chat_id = conversation_id
        if isinstance(chat_id, str) and chat_id.isdecimal():
            chat_id = int(chat_id)
        if not self._client.submit(prompt, chat_id):
            events.put(LLMProviderError("provider", "Assistant busy", provider=self.name, retryable=True))
            events.put(_END)

    def _queue_event(self, event: LLMEvent) -> None:
        with self._events_lock:
            events = self._active_events
        if events is not None:
            events.put(event)

    @Slot(int)
    def _on_chat_ready(self, chat_id: int) -> None:
        self._queue_event(LLMConversation(chat_id))

    @Slot(str, str)
    def _on_state_event(self, state: str, detail: str) -> None:
        self._queue_event(LLMState(state, detail))

    @Slot(str)
    def _on_text_changed(self, text: str) -> None:
        if text == self._last_text:
            return
        replace = not text.startswith(self._last_text)
        delta = text if replace else text[len(self._last_text):]
        self._last_text = text
        if delta or replace:
            self._queue_event(LLMTextDelta(delta, replace=replace))

    @Slot()
    def _on_completed(self) -> None:
        with self._events_lock:
            events = self._active_events
        if events is not None:
            events.put(LLMCompleted("stop"))
            events.put(_END)

    @Slot(str)
    def _on_failed(self, detail: str) -> None:
        code = "connection" if detail == "Newelle unavailable" else "provider"
        error = LLMProviderError(code, detail, provider=self.name, retryable=(code == "connection"))
        with self._events_lock:
            events = self._active_events
        if events is not None:
            events.put(error)
            events.put(_END)

    def close(self) -> None:
        self._closed = True
