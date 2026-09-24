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
        # Set True when wake is detected and armed the timeout, cleared once
        # _on_wake_command runs. Used by _on_wake_timeout to grant a one-time
        # grace reprieve if the timeout fires in the same Qt tick as
        # commandReady — without it, the timeout would race ahead of the
        # queued _on_wake_command slot and silently discard a command the
        # user did finish speaking (audit P2).
        self._wake_command_pending = False
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

    def _release_wake_command(self, reason: str) -> None:
        """Release the pending wake-command temp WAV (if any) and clear the path.

        The wake provider's release_command is idempotent (unlink(missing_ok=True)),
        so this is safe to call even when the path has already been released.

        Every code path that invalidates self._stt_generation (or overwrites
        self._wake_command_path with a new path) MUST call this first. Without it,
        the stale STT callback that would normally release the path (in
        _on_stt_transcript / _on_stt_failed) is silently dropped because
        generation != self._stt_generation, and the temp WAV leaks on disk
        with self._wake_command_path left pointing at a file that no longer
        exists (audit P1).
        """
        if self._wake_command_path is not None:
            log.warning("WAKE_DEBUG releasing stale wake command path=%s reason=%s", self._wake_command_path, reason)
            try:
                self._wake.release_command(self._wake_command_path)
            except Exception:
                log.exception("Failed to release wake command path=%s", self._wake_command_path)
            self._wake_command_path = None

    def _start_wake_timeout(self, duration: float | None = None) -> None:
        self._cancel_wake_timeout("restart")
        if duration is None:
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
            # Race guard: if a wake command was detected (arming this timer)
            # but _on_wake_command hasn't run yet, the command audio might
            # still be in flight from the wake engine's background thread.
            # Rather than silently dropping the command by transitioning to
            # idle, grant a one-time grace reprieve so the queued
            # _on_wake_command slot gets a chance to run on the next event
            # loop iteration. The flag is cleared here so the next timeout
            # fires unconditionally (audit P2).
            if self._wake_command_pending:
                log.warning("WAKE_DEBUG wake command timeout grace reprieve granted — command may still be in flight")
                self._wake_command_pending = False
                self._start_wake_timeout(1.0)
                return
            log.warning("WAKE_DEBUG wake command timeout transitioning state listening -> idle")
            # Stop STT if it was armed for the post-stop 5-second follow-up
            # window (by _handle_stop_command). Without this, transitioning
            # to "idle" would resume the wake engine via set_mode("idle") ->
            # wake.start() while STT still holds the mic, causing both to
            # compete for the audio device. Safe to call unconditionally:
            # cancel() just bumps the generation if STT isn't running
            # (audit P1).
            self._stt.cancel()
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
        # Release any pending wake-command WAV before bumping the STT
        # generation — transcribe_file's eventual callback will be stale
        # and silently drop the path otherwise (audit P1).
        self._release_wake_command("cancel_active_task")
        self._stt.cancel()
        self._request_active = False
        self.set_state("idle")

    @Slot()
    def shutdown(self):
        """Teardown every voice subsystem for clean process exit.

        Without this, an abrupt quit while any of pw-record / whisper-cli /
        piper / kokoro / sherpa-wake is active can orphan the subprocess
        holding the microphone/audio device, surfacing as "mic busy" on the
        next launch. Each manager's stop()/cancel() already terminates its
        subprocesses; this method just calls them all in the right order
        and tolerates partial failure (audit P2).

        Order:
          1. Cancel the LLM worker (no new TTS/STT callbacks fire during teardown)
          2. Quit and wait for the LLM QThread
          3. Stop TTS (kill piper/kokoro playback)
          4. Cancel STT (kill pw-record + whisper-cli, drop pending callbacks)
          5. Stop the wake engine (kill sherpa wake-capture)
          6. Release any pending wake-command temp WAV
          7. Cancel the wake timeout timer
        """
        log.info("Maya shutdown starting state=%s request_active=%s", self._state, self._request_active)

        # 1. Cancel any in-flight LLM worker so its eventReady signals stop
        # arriving during teardown. runner.py's runCompleted signal already
        # wires thread.quit(); we just need to trigger it.
        if self._llm_worker is not None:
            try:
                self._llm_worker.cancel()
            except Exception:
                log.exception("shutdown: LLM worker cancel failed")

        # 2. Quit and wait for the LLM QThread so we don't try to delete a
        # running thread. runCompleted is wired to thread.quit(); if the
        # worker already exited (normal/error), thread.quit() is a no-op.
        thread = self._llm_thread
        if thread is not None:
            try:
                thread.quit()
                thread.wait(2000)  # 2s grace
            except Exception:
                log.exception("shutdown: LLM thread quit/wait failed")

        # 3. Stop TTS — kills any active piper/kokoro playback subprocess.
        try:
            self._tts.stop()
        except Exception:
            log.exception("shutdown: TTS stop failed")

        # 4. Cancel STT — kills pw-record AND whisper-cli subprocesses and
        # bumps the generation so any in-flight callbacks are dropped. Use
        # cancel() (not stop()) because stop() only terminates the record
        # process and still tries to transcribe the partial WAV.
        # Release any pending wake-command WAV first so its temp file is
        # unlinked before its STT callback becomes stale (Round 2 fix).
        try:
            self._release_wake_command("shutdown")
        except Exception:
            log.exception("shutdown: wake command release failed")
        try:
            self._stt.cancel()
        except Exception:
            log.exception("shutdown: STT cancel failed")

        # 5. Stop the wake engine — kills the sherpa wake-capture subprocess
        # that owns the mic in idle/speaking states. Use stop() (not
        # disable_runtime()) so the user's enabled/sensitivity config is
        # preserved across restarts.
        try:
            self._wake.stop("shutdown")
        except Exception:
            log.exception("shutdown: wake stop failed")

        # 6. Cancel the wake timeout timer so it doesn't fire after teardown.
        try:
            self._cancel_wake_timeout("shutdown")
        except Exception:
            log.exception("shutdown: wake timeout cancel failed")

        self._request_active = False
        log.info("Maya shutdown complete")


    @Slot(str)
    def submit(self, text):
        text = text.strip()
        if not text:
            return
        if self._request_active:
            # Allow explicit stop/cancel commands through so the user can
            # interrupt the in-flight request via typed input. Anything else
            # would tear down the in-flight TTS/streaming context before
            # discovering whether the LLM thread is free, leaving the orphan
            # stream running and its eventReady signals landing out of sync
            # (audit P1 #3).
            if not self._is_stop_command(text):
                log.info("submit ignored because request already active state=%s text=%r", self._state, text)
                return
        # Release any pending wake-command WAV before _stt.cancel() bumps the
        # STT generation — transcribe_file's eventual callback will be stale
        # and silently drop the path otherwise (audit P1).
        self._release_wake_command("submit")
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
            if self._llm_worker is not None:
                self._llm_worker.cancel()
            self._tts.stop()
            # Release any pending wake-command WAV before bumping the STT
            # generation — transcribe_file's eventual callback will be stale
            # and silently drop the path otherwise (audit P1).
            self._release_wake_command("stop_command")
            self._stt.cancel()
            self._request_active = False
            self.set_state("listening")
            # Arm STT so the 5-second follow-up window actually listens on
            # the mic. set_state("listening") above called wake.set_mode(
            # "listening"), which in turn called provider.pause() — and since
            # this is a stop command (not a wake detection), command_mode is
            # False, so the wake engine tore down its mic capture. Without
            # arming STT here, the 5s window would be silent: no STT, no wake
            # capture, and even a repeated wake word would be ignored because
            # _on_wake_detected excludes "listening". Mirrors start_ptt()
            # (audit P1).
            stt_generation = self._stt.start()
            if stt_generation is not None:
                self._stt_generation = stt_generation
            # Clear the race-guard flag: the post-stop 5s window doesn't expect
            # a wake command (the wake engine is paused in "listening" mode
            # outside command_mode), so the timeout must not grant a grace
            # reprieve if it fires. Without this, a stale True from a previous
            # wake detection could cause the 5s window to extend by 1s for
            # no reason (audit P2 defensive clear).
            self._wake_command_pending = False
            self._start_wake_timeout(5.0)
            return True
        return False


    def _submit_request(self, user_text, language_instruction, chat_id, language, source):
        """Route explicit memory actions locally, otherwise submit with bounded context."""
        # Explicit stop commands must always be allowed — they tear down the
        # in-flight request via worker.cancel() + _request_active=False (audit
        # P0 #2 mirror in _handle_stop_command).
        if self._handle_stop_command(user_text):
            return

        # Guard against dispatching while a request is already in flight.
        # submit() refuses new typed input while _request_active is True
        # (audit P1 #3) but still allows stop commands through, and the retry
        # path in _on_failed clears _request_active before invoking us. This
        # catches any other caller — e.g. an STT transcript arriving while a
        # previous request is still active — and also prevents memory input
        # and local skill responses from tearing down the in-flight TTS
        # context via _present_local_reply (which stops TTS and bumps
        # _tts_generation before checking whether the LLM thread is free).
        if self._request_active:
            log.warning("submit_request ignored because request already active source=%s state=%s", source, getattr(self, "_state", "idle"))
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
        # runCompleted fires on every exit of LLMStreamWorker.run(): normal
        # completion, exception, and early return due to cancellation. The
        # inner streamEnded/failed signals are deliberately suppressed on
        # cancellation, so wiring thread.quit()/deleteLater to them alone
        # leaves the QThread spinning forever after the first cancel (audit
        # P0). runCompleted is the only guaranteed terminal signal.
        worker.runCompleted.connect(thread.quit)
        worker.runCompleted.connect(worker.deleteLater)
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
        if not self._request_active:
            log.debug("Ignoring stale LLM event after cancellation")
            return
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
        match = re.fullmatch(r"(?:maya[, ]+)?(?:please\s+)?clear(?:\s+all)?\s+memor(?:y|ies)", value, re.IGNORECASE)
        if match:
            return "clear_all", None
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
                log.exception("Failed to prepare remember action")
                self._present_local_reply("I could not prepare that memory request.")
            return True
        if kind == "forget":
            return self._handle_forget_input(value)
        if kind == "clear_all":
            self._set_pending_memory_action("clear_all", None)
            self._present_local_reply("Should I clear all saved Maya memories? This cannot be undone. Please say yes or no.")
            return True
        return False

    def _handle_forget_input(self, value: str) -> bool:
        items = []
        try:
            search_term = value.casefold().strip()
            items = [item for item in self._memory.list_items() if search_term in item.content.casefold()]
        except Exception:
            log.exception("Memory search failed during forget")
            self._present_local_reply("I could not access saved memories. Nothing was deleted.")
            return True
        if not items:
            self._present_local_reply("I could not find a saved memory matching that. Nothing was deleted.")
            return True
        if len(items) == 1:
            self._set_pending_memory_action("forget", {"id": items[0].id, "content": items[0].content})
            self._present_local_reply(f"Should I forget this saved memory: {items[0].content}? Please say yes or no.")
            return True
        if len(items) <= 5:
            lines = [f"{idx + 1}. {item.content}" for idx, item in enumerate(items)]
            self._set_pending_memory_action(
                "forget_select",
                {"items": [{"id": i.id, "content": i.content} for i in items]}
            )
            self._present_local_reply(
                "I found several possible memories. Reply with a number to choose:\n" + "\n".join(lines)
            )
            return True
        self._present_local_reply("I found too many matching memories. Please be more specific.")
        return True

    def _set_pending_memory_action(self, kind: str, payload) -> None:
        self._pending_memory_action = {
            "kind": kind,
            "payload": payload,
            "expires": time.monotonic() + 60.0,
        }

    def _handle_memory_confirmation(self, text: str, pending: dict) -> bool:
        affirmative = {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "do it", "please"}
        negative = {"no", "n", "nope", "cancel", "stop", "never mind", "don't", "dont"}
        normalized = text.strip().casefold()
        normalized = re.sub(r"^(?:maya[, ]+)?(?:please\s+)?", "", normalized).strip()
        normalized = re.sub(r"[.!?]+$", "", normalized).strip()

        if pending["kind"] == "forget_select":
            if normalized in negative:
                self._pending_memory_action = None
                self._present_local_reply("Okay. No memory was changed.")
                return True
            try:
                choice = int(normalized) - 1
                items = pending["payload"]["items"]
                if choice < 0 or choice >= len(items):
                    self._present_local_reply("That number is not one of the listed choices. Please choose again or cancel.")
                    return True
                selected = items[choice]
                self._set_pending_memory_action("forget", {"id": selected["id"], "content": selected["content"]})
                self._present_local_reply(f"Should I forget this saved memory: {selected['content']}? Please say yes or no.")
                return True
            except ValueError:
                return False

        if normalized in negative:
            self._present_local_reply("Okay. No memory was changed.")
            return True
        if normalized not in affirmative:
            return False
        try:
            kind = pending["kind"]
            payload = pending["payload"]
            if kind == "remember":
                self._memory.remember(payload["content"], category=MemoryCategory.OTHER)
                self._present_local_reply("Okay, I'll remember that.")
            elif kind == "forget":
                self._memory.forget(payload["id"])
                self._present_local_reply(f"Okay. I forgot: {payload['content']}")
            elif kind == "clear_all":
                self._memory.clear()
                self._present_local_reply("Okay. All saved memories have been cleared.")
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
        # Release any pending wake-command WAV before _stt.start() bumps the
        # STT generation — transcribe_file's eventual callback will be stale
        # and silently drop the path otherwise (audit P1).
        self._release_wake_command("start_ptt")
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
        if self._state not in {"idle", "thinking", "speaking"}:
            log.warning("WAKE_DEBUG wake event ignored because controller state=%s", self._state)
            return

        # Cancel any in-flight LLM worker so its eventReady signals stop
        # arriving. Without this, a stream started during "thinking" keeps
        # running in the background while the controller moves to "listening",
        # and its stale output (LLMTextDelta, LLMState) lands out of sync with
        # whatever the user is doing by then. Mirrors _handle_stop_command /
        # cancel_active_task (audit P0 #2).
        if self._llm_worker is not None:
            self._llm_worker.cancel()
        # _request_active must be cleared here, not just by _on_completed /
        # _on_failed, because cancellation suppresses both of those signals —
        # leaving _request_active stuck True would refuse every future typed
        # submit (audit P1 #3).
        self._request_active = False

        # Invalidate controller-side callbacks as well as the TTS provider's
        # generation. This covers queued Qt signals from the interrupted audio.
        self._tts.stop()
        self._tts_generation += 1
        log.warning("WAKE_DEBUG controller setting listening state after wake detection")
        self.set_state("listening")
        # Mark that a wake command is expected — _on_wake_timeout will grant
        # a one-time grace reprieve if it fires before _on_wake_command runs,
        # so we don't silently discard a command the user finished speaking
        # (audit P2).
        self._wake_command_pending = True
        self._start_wake_timeout()

    @Slot(str)
    def _on_wake_command(self, path):
        log.warning("WAKE_DEBUG controller received wake command path=%s state=%s", path, self._state)
        # Clear the race-guard flag: the command audio has arrived, so any
        # subsequent wake timeout firing is a real no-speech timeout, not a
        # race-ahead of this slot (audit P2).
        self._wake_command_pending = False
        # If a previous wake command is still pending (its transcription hasn't
        # completed yet), release its temp WAV before overwriting the reference.
        # Without this, the previous file would be orphaned on disk and
        # _wake_command_path would point at a file that was never released
        # (audit P1).
        self._release_wake_command("wake_command_overwrite")
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
