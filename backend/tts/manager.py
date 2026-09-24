"""User configuration and lifecycle manager for Maya TTS."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
import threading
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .base import PlaybackCallbacks, Voice
from .piper_provider import PiperProvider
from .kokoro_provider import KokoroProvider
from ..newelle_client import speech_text


CONFIG_PATH = Path.home() / ".config" / "maya" / "voice.json"
log = logging.getLogger("maya.tts.manager")


def sanitize_tts_text(text: str) -> str:
    """Make speech natural without changing the UI's original assistant text."""
    clean = speech_text(text)
    clean = re.sub(r"[#>|]", " ", clean)
    clean = "".join(" " if unicodedata.category(char).startswith(("S", "C")) else char for char in clean)
    return re.sub(r"\s+", " ", clean).strip()


class _Callbacks(PlaybackCallbacks):
    def __init__(self, manager: "TTSManager", generation: int) -> None:
        self.manager = manager
        self.generation = generation

    def started(self) -> None:
        self.manager._provider_started(self.generation)

    def finished(self) -> None:
        self.manager._provider_finished(self.generation)

    def failed(self, message: str) -> None:
        self.manager._provider_failed(self.generation, message)

    def level(self, value: float) -> None:
        if self.manager._valid(self.generation):
            self.manager.levelChanged.emit(value)


class TTSManager(QObject):
    started = Signal(int)
    finished = Signal(int)
    failed = Signal(int, str)
    levelChanged = Signal(float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._generation = 0
        self._speaking = False
        self._config = self._load_config()
        self._providers = {"piper": PiperProvider(), "kokoro": KokoroProvider()}
        self._streaming = False
        self._stream_done = False
        self._stream_started = False
        self._stream_source = ""
        self._stream_pending = ""
        self._stream_committed = ""
        self._stream_speech_blocked = False
        self._queue: deque[str] = deque()
        self._chunk_active = False
        self._response_language = "en"

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("enabled", True))

    @property
    def is_speaking(self) -> bool:
        with self._lock:
            return self._speaking

    @property
    def response_active(self) -> bool:
        """Whether a streamed response still owns the speech lifecycle."""
        with self._lock:
            return self._streaming

    def speak(self, text: str) -> int | None:
        text = text.strip()
        log.warning("WAKE_DEBUG TTS speak called text=%r enabled=%s", text, self.enabled)
        if not self.enabled or not text:
            return None
        provider = self._selected_provider()
        voice = self._voice(provider)
        log.warning("WAKE_DEBUG TTS selected provider=%s voice=%r", provider.name, voice.name if voice else None)
        if voice is None:
            self.failed.emit(self._generation, f"No installed {provider.name} voice selected")
            return None
        self.stop()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._speaking = False
            self._streaming = False
        rate = float(self._config.get("rate", 1.0))
        provider.speak(text, voice, rate, _Callbacks(self, generation))
        return generation

    def start_response(self, language: str = "en") -> int:
        """Start a streamed response; chunks are queued through feed_response."""
        self.stop()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._streaming = True
            self._stream_done = False
            self._stream_started = False
            self._stream_source = ""
            self._stream_pending = ""
            self._stream_committed = ""
            self._stream_speech_blocked = False
            self._queue.clear()
            self._chunk_active = False
            self._response_language = language if language in {"en", "es", "fr", "de", "it", "pt", "ja", "zh", "hi"} else "en"
        log.warning("WAKE_DEBUG TTS response started generation=%d language=%s provider=%s", generation, self._response_language, self._selected_provider().name)
        return generation

    def feed_response(self, text: str, *, replace: bool = False) -> None:
        """Feed cumulative response text, optionally marking a provider rewrite."""
        clean = sanitize_tts_text(text)
        log.warning("WAKE_DEBUG TTS sanitization original=%r cleaned=%r", text, clean)
        with self._lock:
            if not self._streaming:
                log.warning("WAKE_DEBUG TTS response feed skipped: streaming=False text=%r", clean)
                return
            if replace:
                if clean.startswith(self._stream_committed):
                    # Previously queued/generated text remains a known prefix.
                    # Discard any ungenerated old suffix and continue only with
                    # the replacement's genuinely new text.
                    # Keep already extracted sentence chunks. They are valid
                    # future speech and clearing them truncates long answers.
                    # Only the replacement suffix below is deduplicated.
                    self._stream_source = clean
                    self._stream_pending = clean[len(self._stream_committed):]
                    pending_before = self._stream_pending
                    chunks = self._extract_chunks(final=False)
                    consumed = len(pending_before) - len(self._stream_pending)
                    self._stream_committed += pending_before[:consumed]
                    self._queue.extend(chunks)
                    log.warning(
                        "WAKE_DEBUG TTS replacement accepted generation=%d committed_chars=%d new_chunks=%d",
                        self._generation,
                        len(self._stream_committed),
                        len(chunks),
                    )
                else:
                    # The model revised already queued/spoken content. We can't
                    # safely identify a suffix, so suppress the rest of speech
                    # for this response rather than replaying a whole answer.
                    # Drop only this revision. Keep the last known safe source
                    # so a later cumulative update can resume from it.
                    self._stream_source = self._stream_committed
                    self._stream_pending = ""
                    log.warning("WAKE_DEBUG TTS replacement ambiguous; update discarded generation=%d", self._generation)
                    return
            else:
                if clean == self._stream_source:
                    log.warning("WAKE_DEBUG TTS response feed skipped: duplicate text=%r", clean)
                    return
                if clean.startswith(self._stream_source):
                    delta = clean[len(self._stream_source):]
                else:
                    # Non-prefix changes must be explicitly marked as replace;
                    # otherwise treating them as a fresh answer could repeat it.
                    self._stream_pending = ""
                    log.warning("WAKE_DEBUG TTS non-prefix update discarded generation=%d", self._generation)
                    return
                self._stream_source = clean
                pending_before = self._stream_pending + delta
                self._stream_pending = pending_before
                chunks = self._extract_chunks(final=False)
                consumed = len(pending_before) - len(self._stream_pending)
                self._stream_committed += pending_before[:consumed]
                self._queue.extend(chunks)
            log.warning("WAKE_DEBUG TTS response feed source_length=%d clean_length=%d queued=%r pending_length=%d", len(text), len(clean), chunks, len(self._stream_pending))
        self._pump()

    def finish_response(self) -> None:
        """Flush the last partial phrase and finish after queued audio."""
        with self._lock:
            if not self._streaming:
                return
            self._stream_done = True
            final_chunks = self._extract_chunks(final=True)
            self._queue.extend(final_chunks)
            log.warning("WAKE_DEBUG TTS response finished queued_final=%r queue_length=%d", final_chunks, len(self._queue))
        self._pump()
        self._maybe_finish_stream()

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            self._speaking = False
            self._streaming = False
            self._stream_done = False
            self._stream_started = False
            self._stream_source = ""
            self._stream_pending = ""
            self._stream_committed = ""
            self._stream_speech_blocked = False
            self._queue.clear()
            self._chunk_active = False
        for provider in self._providers.values():
            provider.stop()
        self.levelChanged.emit(0.0)

    def _extract_chunks(self, final: bool) -> list[str]:
        chunks: list[str] = []
        while self._stream_pending:
            text = self._stream_pending
            boundary = None
            # Sentence punctuation is preferred, including a short complete
            # sentence. Do not wait for an arbitrary minimum in that case.
            for match in re.finditer(r"[.!?](?=\s|$)", text):
                if match.end() >= 35 or match.end() == len(text):
                    boundary = match.end()
                    break
            if boundary is None and len(text) >= 80:
                for match in re.finditer(r"[;:](?=\s|$)", text):
                    if match.end() >= 55:
                        boundary = match.end()
                        break
            if boundary is None and len(text) >= 160:
                limit = min(len(text), 220)
                spaces = [m.end() for m in re.finditer(r"\s+", text[:limit])]
                if spaces:
                    boundary = max((point for point in spaces if point <= limit), default=None)
            if boundary is None and not final:
                break
            if boundary is None:
                boundary = len(text)
            chunk = text[:boundary].strip()
            self._stream_pending = text[boundary:].lstrip()
            if chunk:
                chunks.append(chunk)
        return chunks

    def _provider_started(self, generation: int) -> None:
        if not self._valid(generation):
            return
        with self._lock:
            first = not self._stream_started
            self._stream_started = True
            self._speaking = True
        if first:
            log.warning("WAKE_DEBUG TTS playback started generation=%d", generation)
            self.started.emit(generation)

    def _provider_finished(self, generation: int) -> None:
        if not self._valid(generation):
            return
        log.warning("WAKE_DEBUG TTS synthesis/playback success generation=%d", generation)
        with self._lock:
            self._chunk_active = False
            streaming = self._streaming
            done = self._stream_done
        if streaming and not done:
            log.warning("WAKE_DEBUG TTS chunk finished generation=%d more_pending=True", generation)
            self._pump()
            return
        if streaming:
            self._pump()
            self._maybe_finish_stream()
        else:
            self._set_speaking(False)
            self.finished.emit(generation)

    def _provider_failed(self, generation: int, message: str) -> None:
        log.warning("WAKE_DEBUG TTS provider failed generation=%d detail=%r", generation, message)
        if not self._valid(generation):
            return
        with self._lock:
            self._chunk_active = False
            self._streaming = False
            self._speaking = False
        self.failed.emit(generation, message)

    def _pump(self) -> None:
        with self._lock:
            if not self._streaming or self._chunk_active or not self._queue:
                return
            chunk = self._queue.popleft()
            self._chunk_active = True
            generation = self._generation
        provider = self._selected_provider()
        voice = self._voice(provider, self._response_language)
        log.warning("WAKE_DEBUG TTS function called provider=%s generation=%d chunk=%r voice=%r", provider.name, generation, chunk, voice.name if voice else None)
        if voice is None:
            self._provider_failed(generation, f"No installed {provider.name} voice selected")
            return
        rate = float(self._config.get("rate", 1.0))
        provider.speak(chunk, voice, rate, _Callbacks(self, generation))

    def _maybe_finish_stream(self) -> None:
        with self._lock:
            complete = self._streaming and self._stream_done and not self._chunk_active and not self._queue
            generation = self._generation
            if complete:
                self._streaming = False
                self._speaking = False
        if complete:
            self.finished.emit(generation)

    def list_voices(self) -> list[Voice]:
        return self._selected_provider().voices()

    def set_voice(self, name: str) -> None:
        if not any(voice.name == name for voice in self.list_voices()):
            raise ValueError(f"Voice is not installed: {name}")
        self._config["voice"] = name
        self._save_config()

    def _valid(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _set_speaking(self, value: bool) -> None:
        with self._lock:
            self._speaking = value

    def _selected_provider(self):
        provider_name = str(self._config.get("provider", "piper"))
        return self._providers.get(provider_name) or self._providers["piper"]

    def _voice(self, provider, language: str | None = None) -> Voice | None:
        selected = str(self._config.get("voice", "en_US-lessac-medium"))
        voices = provider.voices()
        configured = next((voice for voice in voices if voice.name == selected), None)
        if language is None or language == "en":
            return configured
        prefixes = {"es": ("e",), "fr": ("f",), "de": (), "it": ("i",), "pt": ("p",), "ja": ("j",), "zh": ("z",), "hi": ("h",)}
        matches = [voice for voice in voices if voice.name[:1] in prefixes.get(language, ())]
        return matches[0] if matches else configured

    @staticmethod
    def _load_config() -> dict:
        defaults = {"enabled": True, "provider": "piper", "voice": "en_US-amy-medium", "rate": 1.0}
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except (OSError, ValueError):
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")
        return defaults

    def _save_config(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self._config, indent=2) + "\n", encoding="utf-8")
