"""Small threaded client for Newelle's localhost GUI API."""

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot


API_ROOT = "http://127.0.0.1:8081"
log = logging.getLogger("maya.newelle")
_THINK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*$", re.IGNORECASE | re.DOTALL)
_CODE_RE = re.compile(r"```(?:[^\n]*)\n?(.*?)```", re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def clean_user_text(text: str) -> str:
    text = _THINK_RE.sub("", text)
    return _THINK_OPEN_RE.sub("", text).strip()


def speech_text(text: str) -> str:
    """Keep final user-facing content while removing presentation markup."""
    text = clean_user_text(text)
    text = _CODE_RE.sub(r"\1", text)
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def tool_detail(tool_name: str) -> str:
    name = (tool_name or "").lower()
    if name == "open_application":
        return "Opening application…"
    if any(word in name for word in ("search", "grep", "glob", "directory")):
        return "Searching files…"
    if any(word in name for word in ("command", "shell", "terminal")):
        return "Running command…"
    return "Working…"


class NewelleWorker(QObject):
    """Blocking HTTP/SSE work, moved off the Qt GUI thread."""

    chatReady = Signal(int)
    stateEvent = Signal(str, str)
    textChanged = Signal(str)
    completed = Signal()
    failed = Signal(str)

    def __init__(self, prompt: str, chat_id: int | None):
        super().__init__()
        self.prompt = prompt
        self.chat_id = chat_id
        self._failed = False

    def _request(self, path: str, method: str = "GET", payload: Any = None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            API_ROOT + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(request, timeout=20)

    def _prepare_chat(self) -> int:
        chat_id = self.chat_id
        log.warning("WAKE_DEBUG response Newelle prepare request prompt=%r chat_id=%r", self.prompt, chat_id)
        if chat_id is None:
            with self._request("/api/chats", "POST", {"name": "Maya"}) as response:
                chat_id = int(json.load(response)["chat_id"])
            messages = []
        else:
            with self._request(f"/api/chats/{chat_id}") as response:
                data = json.load(response).get("data", {})
            messages = list(data.get("chat", []))

        messages.append({"User": "User", "Message": self.prompt})
        self._request(f"/api/chats/{chat_id}", "PUT", messages).read()
        log.warning("WAKE_DEBUG response Newelle request prepared chat_id=%d", chat_id)
        return chat_id

    def _fail(self, message: str):
        if not self._failed:
            self._failed = True
            log.warning("WAKE_DEBUG response Newelle failure detail=%r", message)
            self.failed.emit(message)

    @Slot()
    def run(self):
        try:
            log.warning("WAKE_DEBUG response LLM request start prompt=%r chat_id=%r", self.prompt, self.chat_id)
            chat_id = self._prepare_chat()
            self.chatReady.emit(chat_id)
            accumulated = ""
            with self._request(f"/api/chats/{chat_id}/stream") as response:
                log.warning("WAKE_DEBUG response Newelle stream opened chat_id=%d", chat_id)
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except (TypeError, ValueError):
                        self._fail("Assistant failed")
                        return

                    name = event.get("event")
                    data = event.get("data")
                    log.warning("WAKE_DEBUG response Newelle event name=%r data_type=%s data=%r", name, type(data).__name__, data)
                    if name == "chunk":
                        if isinstance(data, str):
                            accumulated += data
                            log.warning("WAKE_DEBUG response Newelle chunk accumulated_length=%d", len(accumulated))
                            self.stateEvent.emit("thinking", "")
                            self.textChanged.emit(clean_user_text(accumulated))
                    elif name == "tool":
                        tool_name = data.get("tool", "") if isinstance(data, dict) else ""
                        self.stateEvent.emit("tool", tool_detail(tool_name))
                    elif name == "finished":
                        if isinstance(data, dict) and isinstance(data.get("message"), str):
                            accumulated = data["message"]
                            log.warning("WAKE_DEBUG response Newelle final message length=%d text=%r", len(accumulated), accumulated)
                            self.textChanged.emit(clean_user_text(accumulated))
                    elif name == "error":
                        log.warning("WAKE_DEBUG response LLM error event data=%r accumulated=%r", data, accumulated)
                        self._fail("Assistant failed")
                        return
                    elif name == "done":
                        if not self._failed:
                            log.warning("WAKE_DEBUG response Newelle done final_accumulated=%r", accumulated)
                            self.completed.emit()
                        return
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
            log.exception("WAKE_DEBUG response Newelle integration exception")
            self._fail("Newelle unavailable")
        except Exception:
            log.exception("WAKE_DEBUG response Newelle unexpected exception")
            self._fail("Assistant failed")


class NewelleClient(QObject):
    """Owns one-at-a-time Newelle request workers and their cleanup."""

    chatReady = Signal(int)
    stateEvent = Signal(str, str)
    textChanged = Signal(str)
    completed = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @Slot(str, object)
    def submit(self, prompt: str, chat_id=None):
        if self.active:
            return False
        self._thread = QThread(self)
        self._worker = NewelleWorker(prompt, chat_id)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.chatReady.connect(self.chatReady)
        self._worker.stateEvent.connect(self.stateEvent)
        self._worker.textChanged.connect(self.textChanged)
        self._worker.completed.connect(self.completed)
        self._worker.failed.connect(self.failed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.completed.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_worker)
        self._thread.start()
        return True

    @Slot()
    def _clear_worker(self):
        self._worker = None
        self._thread = None
