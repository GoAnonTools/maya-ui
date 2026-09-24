"""Presentation state boundary for Maya, ready for a future IPC adapter."""
import json
import logging
import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot, Qt

from .behaviour_policy import classify_intent, policy_instruction
from .mcp_client import MCPStdioClient
from .local_skills import local_skill_response
from .llm import LLMConversation, LLMCompleted, LLMMessage, LLMRequest, LLMState, LLMTextDelta
from .llm.defaults import create_default_provider_manager
from .llm.manager import ProviderManager
from .llm.runner import LLMStreamWorker
from .memory.models import MemoryCategory
from .memory.service import MemoryService
from .prompt_builder import build_prompt
from .stt import STTManager
from .tts import TTSManager
from .wake import WakeManager

log = logging.getLogger("maya-ui.controller")

_LANGUAGE_HINTS = {
    "es": {"el", "la", "los", "las", "que", "qué", "por", "para", "una", "cómo", "como", "hora", "es"},
    "fr": {"le", "la", "les", "des", "que", "quoi", "pour", "avec", "une", "comment", "heure", "est"},
    "de": {"der", "die", "das", "den", "und", "für", "mit", "eine", "wie", "ist", "uhr"},
    "it": {"il", "lo", "la", "gli", "che", "per", "con", "una", "come", "dove", "ora"},
    "pt": {"o", "a", "os", "as", "que", "para", "com", "uma", "como", "não", "hora", "é"},
}


def detect_spoken_language(text: str) -> tuple[str, float]:
    """Conservatively identify common spoken languages; uncertain means English."""
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "zh", 0.98
    if any("\u3040" <= char <= "\u30ff" for char in text):
        return "ja", 0.98
    if any("\u0900" <= char <= "\u097f" for char in text):
        return "hi", 0.98
    words = set(re.findall(r"[\wÀ-ÿ]+", text.casefold(), flags=re.UNICODE))
    language, score = max(((lang, len(words & hints)) for lang, hints in _LANGUAGE_HINTS.items()), key=lambda item: item[1])
    if score >= 2:
        return language, min(0.95, 0.55 + score * 0.1)
    return "en", 0.35


def language_prompt(text: str, language: str) -> str:
    names = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese", "ja": "Japanese", "zh": "Chinese", "hi": "Hindi"}
    return f"[Language policy: answer in {names.get(language, 'English')}. Use natural, concise spoken language.]\n\n{text}"


RECOVERY_NOTICE = "My conversation memory became too large, so I refreshed my short-term context while keeping the important things."


class MayaController(QObject):
    stateChanged = Signal()
    detailChanged = Signal()
    speechLevelChanged = Signal()
    listeningLevelChanged = Signal()
    userTextChanged = Signal()
    assistantTextChanged = Signal()
    providerChanged = Signal()
    _states = ("idle", "listening", "thinking", "speaking", "tool", "error")
    _details = {"idle": "", "listening": "", "thinking": "", "speaking": "", "tool": "", "error": "Something went wrong"}

    def _get_current_provider_name(self):
        return self._provider_manager.current_provider_name

    def _get_current_provider_display_name(self):
        return self._provider_manager.current_provider_display_name

    def _get_available_providers(self):
        return [
            {
                "id": status.name,
                "displayName": status.display_name or status.name,
                "available": status.available,
                "reason": status.reason,
            }
            for status in self._provider_manager.registry.statuses()
        ]

    currentProviderName = Property(str, _get_current_provider_name, notify=providerChanged)
    currentProviderDisplayName = Property(str, _get_current_provider_display_name, notify=providerChanged)
    availableProviders = Property(list, _get_available_providers, notify=providerChanged)

    @property
    def current_provider_name(self) -> str:
        """Technical ID of the active provider, delegated to ProviderManager."""
        return self._provider_manager.current_provider_name

    @property
    def current_provider_display_name(self) -> str:
        """Friendly active provider label, delegated to ProviderManager."""
        return self._provider_manager.current_provider_display_name

    @Slot(str)
    def select_provider(self, name: str) -> None:
        if not isinstance(name, str):
            return
        target = name.strip()
        if not target or target == self.current_provider_name:
            return
        log.info("Switching active LLM provider requested: current=%s target=%s", self.current_provider_name, target)
        try:
            self._provider_manager.select(target)
            self.providerChanged.emit()
            log.info("LLM provider successfully switched to %s (%s)", self.current_provider_name, self.current_provider_display_name)
        except Exception as exc:
            log.error("Failed to switch LLM provider to %r: %s", target, exc)

    def __init__(self, memory_service=None, provider_manager: ProviderManager | None = None, mcp_client=None):
        super().__init__()
        self._state = "idle"
        self._detail = ""
        self._user_text = ""
        self._assistant_text = ""
        self._chat_id = None
        self._request_active = False
        self._generation = 0
        self._tts_generation = 0
        self._speech_level = 0.0
        self._listening_level = 0.0
        self._stt_generation = 0
        self._wake_command_path = None
        self._wake_command_timeout_seconds = self._load_wake_command_timeout()
        self._context_size = self._load_context_size()
        self._memory = memory_service if memory_service is not None else MemoryService.from_config()
        self._pending_recovery_notice = False
        self._pending_memory_action = None
        self._wake_timeout_started_at = None
        self._wake_timeout_timer = QTimer(self)
        self._wake_timeout_timer.setSingleShot(True)
        self._wake_timeout_timer.timeout.connect(self._on_wake_timeout)
        self._provider_manager = provider_manager or create_default_provider_manager(self)
        self._mcp_client = mcp_client or MCPStdioClient()
        self._llm_thread = None
        self._llm_worker = None
        self._tts = TTSManager(self)
        self._stt = STTManager(self)
        self._wake = WakeManager(self)
        self._tts.started.connect(self._on_speech_started)
        self._tts.finished.connect(self._on_speech_finished)
        self._tts.failed.connect(self._on_speech_failed)
        self._tts.levelChanged.connect(self._on_speech_level)
        self._stt.started.connect(self._on_stt_started)
        self._stt.transcribing.connect(self._on_stt_transcribing)
        self._stt.transcriptReady.connect(self._on_stt_transcript)
        self._stt.failed.connect(self._on_stt_failed)
        self._stt.levelChanged.connect(self._on_listening_level)
        self._wake.detected.connect(self._on_wake_detected, Qt.ConnectionType.QueuedConnection)
        self._wake.commandReady.connect(self._on_wake_command, Qt.ConnectionType.QueuedConnection)
        self._wake.failed.connect(self._on_wake_failed, Qt.ConnectionType.QueuedConnection)
        self._wake.start()

    @staticmethod
    def _load_context_size(config_path: Path | None = None) -> int:
        if config_path is None:
            config_path = Path.home() / ".config" / "maya" / "llm.json"
        default = 8192
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "context_size" in data:
                return max(512, int(data["context_size"]))
            return default
        except (OSError, TypeError, ValueError):
            return default

    @property
    def context_size(self) -> int:
        if not hasattr(self, "_context_size"):
            self._context_size = self._load_context_size()
        return self._context_size

    def estimate_context_usage(
        self, prompt: str, history_messages: list[dict] | tuple | None = None, history_chars: int = 0
    ) -> dict:
        """Estimate current context size and ratio relative to configured limit without calling LLM."""
        prompt_chars = len(prompt or "")
        calc_history_chars = history_chars
        if history_messages is not None:
            calc_history_chars = sum(
                len(msg.get("Message", "")) if isinstance(msg, dict) and isinstance(msg.get("Message"), str) else 0
                for msg in history_messages
            )
        total_chars = prompt_chars + calc_history_chars
        estimated_tokens = (total_chars + 3) // 4  # ~4 characters per token
        max_tokens = self.context_size
        max_chars = max_tokens * 4
        ratio = total_chars / max_chars if max_chars > 0 else 0.0
        return {
            "prompt_chars": prompt_chars,
            "history_chars": calc_history_chars,
            "total_chars": total_chars,
            "estimated_tokens": estimated_tokens,
            "max_context_tokens": max_tokens,
            "max_context_chars": max_chars,
            "usage_ratio": round(ratio, 4),
            "is_approaching_limit": ratio >= 0.75,
        }

    @staticmethod
    def _load_wake_command_timeout() -> float:
        config_path = Path.home() / ".config" / "maya" / "voice.json"
        default = 8.0
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            value = float(data.get("wake_command_timeout_seconds", default)) if isinstance(data, dict) else default
            return max(0.0, value)
        except (OSError, TypeError, ValueError):
            return default

    def _cancel_wake_timeout(self, reason: str) -> None:
        if self._wake_timeout_timer.isActive():
            elapsed = time.monotonic() - self._wake_timeout_started_at if self._wake_timeout_started_at is not None else 0.0
            log.warning("WAKE_DEBUG wake command timeout canceled reason=%s elapsed=%.3fs", reason, elapsed)
            self._wake_timeout_timer.stop()
        self._wake_timeout_started_at = None

    def _start_wake_timeout(self) -> None:
        self._cancel_wake_timeout("restart")
        duration = self._wake_command_timeout_seconds
        if duration <= 0:
            log.warning("WAKE_DEBUG wake command timeout disabled duration=%.3fs", duration)
            return
        self._wake_timeout_started_at = time.monotonic()
        log.warning("WAKE_DEBUG wake command timeout started timestamp=%.6f duration=%.3fs", self._wake_timeout_started_at, duration)
        self._wake_timeout_timer.start(round(duration * 1000))

    @Slot()
    def _on_wake_timeout(self) -> None:
        started_at = self._wake_timeout_started_at
        self._wake_timeout_started_at = None
        elapsed = time.monotonic() - started_at if started_at is not None else 0.0
        log.warning("WAKE_DEBUG wake command timeout expired elapsed=%.3fs state=%s request_active=%s", elapsed, self._state, self._request_active)
        if self._state == "listening" and not self._request_active and self._wake_command_path is None:
            log.warning("WAKE_DEBUG wake command timeout transitioning state listening -> idle")
            self.set_state("idle")

    def _get_state(self):
        return self._state

    def _get_detail(self):
        return self._detail

    state = Property(str, _get_state, notify=stateChanged)
    detail = Property(str, _get_detail, notify=detailChanged)

    def _get_user_text(self):
        return self._user_text

    def _get_assistant_text(self):
        return self._assistant_text

    userText = Property(str, _get_user_text, notify=userTextChanged)
    assistantText = Property(str, _get_assistant_text, notify=assistantTextChanged)

    def _get_speech_level(self):
        return self._speech_level

    speechLevel = Property(float, _get_speech_level, notify=speechLevelChanged)

    def _get_listening_level(self):
        return self._listening_level

    listeningLevel = Property(float, _get_listening_level, notify=listeningLevelChanged)

    @property
    def current_provider_name(self) -> str:
        """Technical ID of the active provider, delegated to ProviderManager."""
        return self._provider_manager.current_provider_name

    @property
    def current_provider_display_name(self) -> str:
        """Friendly active provider label, delegated to ProviderManager."""
        return self._provider_manager.current_provider_display_name

    @Slot(str, str)
    def set_state(self, state, detail=""):
        previous_state = self._state
        # Newelle emits thinking while a streamed answer is still arriving.
        # Once audio has begun, keep the visible state speaking across queued
        # speech chunks until TTSManager reports the response complete.
        if state == "thinking" and self._tts.is_speaking:
            log.warning("WAKE_DEBUG controller state transition suppressed previous=%s requested=thinking reason=tts_already_speaking", self._state)
            return
        if state not in self._states:
            detail = f"Unknown state: {state}"
            state = "error"
        if state != "listening":
            self._cancel_wake_timeout(f"state transition to {state}")
        self._state = state
        self._detail = detail if detail else self._details[state]
        log.warning(
            "WAKE_DEBUG UI state changed source=set_state previous=%s new=%s detail=%r",
            previous_state,
            state,
            self._detail,
        )
        self.stateChanged.emit()
        self.detailChanged.emit()
        self._wake.set_mode(state)

    @Slot(object)
    def apply_message(self, message):
        """Apply one validated IPC object; bad external input never reaches QML."""
        if not isinstance(message, dict):
            return
        state = message.get("state")
        if state not in self._states:
            log.warning("Ignoring unknown Maya state: %r", state)
            return
        detail = message.get("detail", "")
        if not isinstance(detail, str):
            log.warning("Ignoring non-string Maya detail")
            detail = ""
        self.set_state(state, detail[:240])

    @Slot(int)
    def set_demo_state(self, number):
        if not self._request_active and 1 <= number <= len(self._states):
            self.set_state(self._states[number - 1])

    @Slot()
    def reset(self):
        self.set_state("idle")

    @Slot()
    def cancel_active_task(self):
        """Cancel active LLM worker, TTS, and STT safely, restoring controller to idle."""
        log.info("Cancelling active task request_active=%s state=%s", self._request_active, self._state)
        if self._llm_worker is not None:
            self._llm_worker.cancel()
        self._tts.stop()
        self._stt.cancel()
        self._request_active = False
        self.set_state("idle")


    @Slot(str)
    def submit(self, text):
        text = text.strip()
        if not text or self._request_active:
            if not text:
                return
            self._tts.stop()
        self._stt.cancel()
        self._user_text = text
        self._assistant_text = ""
        self.userTextChanged.emit()
        self.assistantTextChanged.emit()
        self._submit_request(text, "", self._chat_id, "en", "typed")

    @staticmethod
    def _is_stop_command(text: str) -> bool:
        """Recognize explicit stop/cancel commands."""
        if not isinstance(text, str) or not text.strip():
            return False
        value = text.strip().casefold()
        value = re.sub(r"^(?:maya[, ]+)?(?:please\s+)?", "", value).strip()
        value = re.sub(r"[.!?]+$", "", value).strip()
        return value in {"stop", "cancel", "quiet", "shut up", "halt"}

    def _handle_stop_command(self, user_text: str) -> bool:
        if self._is_stop_command(user_text):
            log.info("Stop command intercepted user_text=%r", user_text)
            self.cancel_active_task()
            return True
        return False

    def _submit_request(self, user_text, language_instruction, chat_id, language, source):
        """Route explicit memory actions locally, otherwise submit with bounded context."""
        if self._handle_stop_command(user_text):
            return

        if self._handle_memory_input(user_text):
            return


        local_reply = local_skill_response(user_text, mcp_client=self._mcp_client)
        if local_reply is not None:
            self._present_local_reply(local_reply, language=language)
            return

        behaviour = policy_instruction(classify_intent(user_text))
        memory_context = None
        if self._memory.settings.enabled:
            try:
                memory_context = self._memory.retrieve(user_text)
                if memory_context.text:
                    log.info("Memory context added to %s request item_count=%d", source, len(memory_context.items))
            except Exception:
                # Memory is optional: preserve the user's request if local storage fails.
                log.exception("Memory retrieval failed; continuing without memory context")

        prompt = build_prompt(behaviour, language_instruction, memory_context, user_text)
        usage = self.estimate_context_usage(prompt)
        if usage.get("is_approaching_limit"):
            log.warning(
                "CONTEXT_GUARD context limit approaching chat_id=%r total_chars=%d estimated_tokens=%d max_tokens=%d usage_ratio=%.2f",
                chat_id,
                usage["total_chars"],
                usage["estimated_tokens"],
                usage["max_context_tokens"],
                usage["usage_ratio"],
            )
            chat_id = self._perform_context_rollover(user_text, memory_context)

        self._request_active = True
        self._generation += 1
        self._tts.stop()
        self._tts_generation = self._tts.start_response(language)
        self.set_state("thinking")
        log.warning("WAKE_DEBUG response LLM request sent source=%s text=%r prompt_chars=%d chat_id=%r tts_generation=%d", source, user_text, len(prompt), chat_id, self._tts_generation)
        if not self._start_provider_request(prompt, chat_id):
            self._on_failed("Assistant busy")

    def _perform_context_rollover(self, user_text: str, memory_context) -> None:
        """Reset short-term context while preserving long-term memories and attaching recovery notice."""
        log.warning("CONTEXT_ROLLOVER resetting short-term chat context chat_id=%r", self._chat_id)
        self._chat_id = None
        self._pending_recovery_notice = True
        return None

    def _start_provider_request(self, prompt, chat_id) -> bool:
        if self._llm_thread is not None and self._llm_thread.isRunning():
            return False
        request = LLMRequest(
            messages=(LLMMessage(role="user", content=prompt),),
            conversation_id=chat_id,
        )
        thread = QThread(self)
        worker = LLMStreamWorker(self._provider_manager, request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.eventReady.connect(self._on_llm_event)
        worker.streamEnded.connect(self._on_completed)
        worker.failed.connect(self._on_failed)
        worker.streamEnded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.streamEnded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_llm_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._llm_thread = thread
        self._llm_worker = worker
        thread.start()
        return True

    @Slot()
    def _on_llm_thread_finished(self):
        if self.sender() is self._llm_thread:
            self._llm_thread = None
            self._llm_worker = None

    @Slot(object)
    def _on_llm_event(self, event):
        if isinstance(event, LLMConversation):
            try:
                self._on_chat_ready(int(event.conversation_id))
            except (TypeError, ValueError):
                log.warning("Ignoring invalid Newelle conversation ID: %r", event.conversation_id)
        elif isinstance(event, LLMState):
            self.set_state(event.state, event.detail)
        elif isinstance(event, LLMTextDelta):
            prefix = ""
            if getattr(self, "_pending_recovery_notice", False):
                self._pending_recovery_notice = False
                prefix = f"{RECOVERY_NOTICE}\n\n"
            text = (prefix + event.text) if event.replace or not self._assistant_text else (self._assistant_text + event.text)
            self._on_assistant_text(text)
            if self._request_active:
                self._tts.feed_response(text, replace=event.replace)
        elif isinstance(event, (LLMCompleted,)):
            # Stream completion is handled once by LLMStreamWorker.streamEnded.
            return

    @staticmethod
    def _memory_command(text):
        """Recognize only direct, English memory commands; other text stays normal chat."""
        value = text.strip()
        match = re.fullmatch(r"(?:maya[, ]+)?(?:please\s+)?remember(?:\s+that)?\s+(.+)", value, re.IGNORECASE)
        if match:
            return "remember", match.group(1).strip()
        match = re.fullmatch(r"(?:maya[, ]+)?(?:please\s+)?forget(?:\s+(?:that|memory))?\s+(.+)", value, re.IGNORECASE)
        if match:
            return "forget", match.group(1).strip()
        if re.fullmatch(r"(?:maya[, ]+)?(?:please\s+)?clear\s+(?:(?:all|my)\s+)?memory", value, re.IGNORECASE):
            return "clear", ""
        return None

    def _handle_memory_input(self, text):
        pending = self._pending_memory_action
        if pending is not None:
            if time.monotonic() >= pending["expires"]:
                self._pending_memory_action = None
                pending = None
            else:
                if self._handle_memory_confirmation(text, pending):
                    return True
                self._pending_memory_action = None

        command = self._memory_command(text)
        if command is None:
            return False
        if not self._memory.settings.enabled:
            self._present_local_reply("Maya memory is disabled. No memory was changed.")
            return True

        kind, value = command
        if kind == "remember":
            try:
                normalized = " ".join(value.split())
                if not normalized:
                    self._present_local_reply("Tell me what you would like me to remember.")
                elif len(normalized) > self._memory.settings.max_content_chars:
                    self._present_local_reply("That memory is too long to save.")
                else:
                    self._set_pending_memory_action("remember", {"content": normalized})
                    self._present_local_reply(f"Should I remember: {normalized}? Please say yes or no.")
            except Exception:
                log.exception("Could not prepare explicit remember request")
                self._present_local_reply("I could not prepare that memory request.")
            return True
        if kind == "clear":
            self._set_pending_memory_action("clear", {})
            self._present_local_reply("Should I clear all saved Maya memories? This cannot be undone. Please say yes or no.")
            return True
        self._begin_forget(value)
        return True

    def _set_pending_memory_action(self, kind, payload):
        self._pending_memory_action = {
            "kind": kind,
            "payload": payload,
            "expires": time.monotonic() + 90.0,
        }

    def _begin_forget(self, description):
        try:
            items = self._memory.list_items()
            needle = " ".join(re.findall(r"\w+", description.casefold()))
            exact = [item for item in items if " ".join(item.content.casefold().split()) == " ".join(description.casefold().split())]
            if exact:
                candidates = exact
            else:
                terms = set(needle.split())
                scored = [(len(terms & set(re.findall(r"\w+", item.content.casefold()))), item) for item in items]
                best = max((score for score, _item in scored), default=0)
                candidates = [item for score, item in scored if score == best and score > 0]
            if not candidates:
                self._present_local_reply("I could not find a saved memory matching that. Nothing was deleted.")
            elif len(candidates) == 1:
                item = candidates[0]
                self._set_pending_memory_action("forget", {"memory_id": item.id, "content": item.content})
                self._present_local_reply(f"Should I forget this saved memory: {item.content}? Please say yes or no.")
            else:
                choices = candidates[:3]
                self._set_pending_memory_action("forget_choice", {"items": [(item.id, item.content) for item in choices]})
                lines = " ".join(f"{index + 1}: {item.content[:160]}." for index, item in enumerate(choices))
                self._present_local_reply(f"I found several possible memories. Reply with a number to choose: {lines}")
        except Exception:
            log.exception("Could not look up explicit forget request")
            self._present_local_reply("I could not access saved memories. Nothing was deleted.")

    def _handle_memory_confirmation(self, text, pending):
        answer = text.strip().casefold().strip(" .!?")
        if pending["kind"] == "forget_choice":
            if answer in {"cancel", "no", "never mind", "nevermind"}:
                self._pending_memory_action = None
                self._present_local_reply("Okay. Nothing was deleted.")
                return True
            if not re.fullmatch(r"\d+", answer):
                return False
            choices = pending["payload"]["items"]
            index = int(answer) - 1
            if index < 0 or index >= len(choices):
                self._present_local_reply("That number is not one of the listed choices. Please choose again or cancel.")
                return True
            memory_id, content = choices[index]
            self._set_pending_memory_action("forget", {"memory_id": memory_id, "content": content})
            self._present_local_reply(f"Should I forget this saved memory: {content}? Please say yes or no.")
            return True

        if answer in {"no", "cancel", "never mind", "nevermind"}:
            self._pending_memory_action = None
            self._present_local_reply("Okay. No memory was changed.")
            return True
        if answer not in {"yes", "confirm", "confirmed", "do it"}:
            return False

        self._pending_memory_action = None
        try:
            kind = pending["kind"]
            payload = pending["payload"]
            if kind == "remember":
                self._memory.remember(payload["content"], category=MemoryCategory.OTHER)
                message = "I saved that memory."
            elif kind == "forget":
                removed = self._memory.forget(payload["memory_id"])
                message = "I forgot that memory." if removed else "That memory was already gone."
            elif kind == "clear":
                count = self._memory.clear()
                message = f"I cleared {count} saved memories."
            else:
                message = "I could not complete that memory action."
            self._present_local_reply(message)
        except Exception:
            log.exception("Confirmed memory action failed kind=%s", pending["kind"])
            self._present_local_reply("I could not complete that memory action. No success was recorded.")
        return True

    def _present_local_reply(self, text, language="en"):
        self._request_active = False
        self._assistant_text = text
        self.assistantTextChanged.emit()
        self._tts.stop()
        self._tts_generation = self._tts.start_response(language)
        self.set_state("thinking")
        self._tts.feed_response(text)
        self._tts.finish_response()

    @Slot(int)
    def _on_chat_ready(self, chat_id):
        log.warning("WAKE_DEBUG response LLM chat ready chat_id=%d", chat_id)
        self._chat_id = chat_id

    @Slot(str)
    def _on_assistant_text(self, text):
        log.warning("WAKE_DEBUG response assistant text received length=%d text=%r request_active=%s tts_response_active=%s", len(text), text, self._request_active, self._tts.response_active)
        self._assistant_text = text
        self.assistantTextChanged.emit()
        if not self._request_active:
            log.warning("WAKE_DEBUG response skipping TTS: request_active=False")

    @Slot()
    def _on_completed(self):
        log.warning("WAKE_DEBUG response LLM completed assistant_text=%r request_active=%s tts_response_active=%s tts_speaking=%s", self._assistant_text, self._request_active, self._tts.response_active, self._tts.is_speaking)
        self._request_active = False
        self._tts.finish_response()
        if not self._tts.is_speaking and not self._tts.response_active:
            self.set_state("idle")

    @Slot(str)
    def _on_failed(self, detail):
        log.error("WAKE_DEBUG controller error transition source=LLM/Newelle detail=%r", detail)
        if "context" in detail.lower() and "exceeded" in detail.lower():
            if not getattr(self, "_is_overflow_retrying", False):
                log.warning("REACTIVE_RECOVERY context overflow detected, performing context reset and retrying request chat_id=%r", self._chat_id)
                self._is_overflow_retrying = True
                self._chat_id = None
                self._pending_recovery_notice = True
                self._request_active = False
                try:
                    self._submit_request(self._user_text, "", None, "en", "retry")
                finally:
                    self._is_overflow_retrying = False
                return

        log.error("WAKE_DEBUG controller user-facing error detail retained friendly_label=%r", self._details["error"])
        self._request_active = False
        self._tts.stop()
        self.set_state("error", detail)

    @Slot()
    def start_ptt(self):
        if self._request_active:
            return
        self._tts.stop()
        self._wake.set_mode("listening")
        stt_generation = self._stt.start()
        if stt_generation is not None:
            self._stt_generation = stt_generation
            self.set_state("listening")

    @Slot()
    def stop_ptt(self):
        if self._stt.is_listening:
            self._stt.stop()

    @Slot(int)
    def _on_speech_started(self, generation):
        if generation == self._tts_generation:
            self.set_state("speaking")

    @Slot(int)
    def _on_speech_finished(self, generation):
        if generation == self._tts_generation and not self._request_active:
            self.set_state("idle")

    @Slot(int, str)
    def _on_speech_failed(self, generation, _detail):
        log.error("WAKE_DEBUG controller error transition source=TTS generation=%d detail=%r", generation, _detail)
        if generation == self._tts_generation and not self._request_active:
            self.set_state("idle")

    @Slot(float)
    def _on_speech_level(self, value):
        self._speech_level = max(0.0, min(1.0, value))
        self.speechLevelChanged.emit()

    @Slot(int)
    def _on_stt_started(self, generation):
        if generation == self._stt_generation:
            self.set_state("listening")

    @Slot(int)
    def _on_stt_transcribing(self, generation):
        log.warning("WAKE_DEBUG controller STT transcribing callback generation=%d expected=%d", generation, self._stt_generation)
        if generation == self._stt_generation:
            self.set_state("listening", "Transcribing…")

    @Slot(int, str)
    def _on_stt_transcript(self, generation, text):
        log.warning("WAKE_DEBUG controller STT transcript callback generation=%d expected=%d text=%r", generation, self._stt_generation, text)
        if generation != self._stt_generation:
            log.warning("WAKE_DEBUG controller ignoring stale STT transcript generation=%d", generation)
            return
        if self._wake_command_path is not None:
            self._wake.release_command(self._wake_command_path)
            self._wake_command_path = None
        text = text.strip()
        if not text:
            self.set_state("error", "No speech detected")
            return
        self._user_text = text
        self._assistant_text = ""
        self.userTextChanged.emit()
        self.assistantTextChanged.emit()
        language, confidence = detect_spoken_language(text)
        log.warning("WAKE_DEBUG language policy request=%r selected=%s confidence=%.2f", text, language, confidence)
        language_instruction = language_prompt("", language).strip()
        self._submit_request(text, language_instruction, None if self._chat_id is None else self._chat_id, language, "STT")

    @Slot(int, str)
    def _on_stt_failed(self, generation, detail):
        log.warning("WAKE_DEBUG controller STT failure callback generation=%d expected=%d detail=%r", generation, self._stt_generation, detail)
        if generation == self._stt_generation:
            if self._wake_command_path is not None:
                self._wake.release_command(self._wake_command_path)
                self._wake_command_path = None
            self.set_state("error", detail[:120] or "Speech input failed")

    @Slot()
    def _on_wake_detected(self):
        log.warning("WAKE_DEBUG event received by controller: wake detected state=%s", self._state)
        if self._state not in {"idle", "speaking"}:
            log.warning("WAKE_DEBUG wake event ignored because controller state=%s", self._state)
            return
        # Invalidate controller-side callbacks as well as the TTS provider's
        # generation. This covers queued Qt signals from the interrupted audio.
        self._tts.stop()
        self._tts_generation += 1
        log.warning("WAKE_DEBUG controller setting listening state after wake detection")
        self.set_state("listening")
        self._start_wake_timeout()

    @Slot(str)
    def _on_wake_command(self, path):
        log.warning("WAKE_DEBUG controller received wake command path=%s state=%s", path, self._state)
        self._cancel_wake_timeout("command audio ready")
        if self._state != "listening":
            self._wake.release_command(path)
            return
        self.set_state("listening", "Transcribing…")
        log.warning("WAKE_DEBUG controller starting STT from wake command path=%s", path)
        generation = self._stt.transcribe_file(path)
        log.warning("WAKE_DEBUG controller STT transcribe_file returned generation=%r", generation)
        if generation is None:
            self._wake.release_command(path)
            self.set_state("error", "Speech input is disabled")
            return
        self._stt_generation = generation
        log.warning("WAKE_DEBUG controller registered wake STT generation=%d", generation)
        self._wake_command_path = path

    @Slot(str)
    def _on_wake_failed(self, detail):
        log.warning("Wake detector unavailable: %s", detail)

    @Slot(float)
    def _on_listening_level(self, value):
        self._listening_level = max(0.0, min(1.0, value))
        self.listeningLevelChanged.emit()
