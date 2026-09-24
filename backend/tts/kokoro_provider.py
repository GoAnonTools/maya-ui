"""Kokoro-82M INT8 ONNX provider with cancellable PipeWire playback."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import wave
import logging
from pathlib import Path

KOKORO_ROOT = Path.home() / ".local" / "share" / "maya" / "tts" / "kokoro"
KOKORO_VENV = KOKORO_ROOT / "venv"
KOKORO_SITE = KOKORO_VENV / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if str(KOKORO_SITE) not in sys.path:
    sys.path.insert(0, str(KOKORO_SITE))

import numpy as np
from kokoro_onnx import Kokoro, MAX_PHONEME_LENGTH, SAMPLE_RATE

from .base import PlaybackCallbacks, Voice

log = logging.getLogger("maya.tts.kokoro")


MODEL = KOKORO_ROOT / "kokoro-v1.0.int8.onnx"
VOICES = KOKORO_ROOT / "voices-v1.0.bin"


def _create_audio_compatible(self, phonemes, voice, speed):
    """Use float speed for both v1.0 and newer Kokoro ONNX exports."""
    phonemes = phonemes[:MAX_PHONEME_LENGTH]
    tokens = np.array(self.tokenizer.tokenize(phonemes), dtype=np.int64)
    voice = voice[len(tokens)]
    tokens = [[0, *tokens, 0]]
    names = [item.name for item in self.sess.get_inputs()]
    if "input_ids" in names:
        inputs = {
            "input_ids": tokens,
            "style": np.array(voice, dtype=np.float32),
            "speed": np.ones(1, dtype=np.float32) * speed,
        }
    else:
        inputs = {
            "tokens": tokens,
            "style": np.array(voice, dtype=np.float32),
            "speed": np.ones(1, dtype=np.float32) * speed,
        }
    audio = self.sess.run(None, inputs)[0]
    return audio, SAMPLE_RATE


Kokoro._create_audio = _create_audio_compatible


class KokoroProvider:
    name = "kokoro"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._play_process: subprocess.Popen[bytes] | None = None
        self._temp_path: Path | None = None
        self._engine: Kokoro | None = None

    def voices(self) -> list[Voice]:
        if not VOICES.exists():
            return []
        try:
            names = sorted(np.load(VOICES).files)
        except (OSError, ValueError):
            return []
        result = []
        for name in names:
            language = {
                "a": "en-us", "b": "en-gb", "e": "es", "f": "fr-fr",
                "h": "hi", "i": "it", "j": "ja", "p": "pt-br", "z": "zh",
            }.get(name[:1], "en-us")
            gender = "female" if name[1:2] == "f" else "male"
            result.append(Voice(name, self.name, language, gender, str(MODEL)))
        return result

    def speak(self, text: str, voice: Voice, rate: float, callbacks: PlaybackCallbacks) -> None:
        self.stop()
        with self._lock:
            self._generation += 1
            generation = self._generation
        thread = threading.Thread(
            target=self._run,
            args=(generation, text, voice, rate, callbacks),
            name="maya-kokoro-tts",
            daemon=True,
        )
        thread.start()

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            process = self._play_process
            self._play_process = None
            temp_path = self._temp_path
            self._temp_path = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    def _current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _run(self, generation: int, text: str, voice: Voice, rate: float, callbacks: PlaybackCallbacks) -> None:
        temp_path: Path | None = None
        try:
            if not MODEL.exists() or not VOICES.exists():
                raise RuntimeError("Kokoro model or voice pack is missing")
            log.warning("WAKE_DEBUG TTS synthesis start generation=%d text=%r voice=%s model_exists=%s voices_exists=%s", generation, text, voice.name, MODEL.exists(), VOICES.exists())
            if self._engine is None:
                self._engine = Kokoro(str(MODEL), str(VOICES))
                log.warning("WAKE_DEBUG TTS Kokoro model loaded generation=%d", generation)
            speed = max(0.5, min(2.0, rate))
            audio, sample_rate = self._engine.create(text, voice.name, speed=speed, lang=voice.language)
            if not self._current(generation):
                return
            fd, raw_path = tempfile.mkstemp(prefix="maya-kokoro-", suffix=".wav")
            os.close(fd)
            temp_path = Path(raw_path)
            pcm = np.clip(audio, -1.0, 1.0)
            pcm = (pcm * 32767.0).astype(np.int16)
            with wave.open(str(temp_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate or SAMPLE_RATE)
                wav.writeframes(pcm.tobytes())
            log.warning("WAKE_DEBUG TTS audio file generated generation=%d path=%s samples=%d rate=%d bytes=%d", generation, temp_path, len(pcm), sample_rate or SAMPLE_RATE, temp_path.stat().st_size)
            with self._lock:
                if generation != self._generation:
                    return
                self._temp_path = temp_path
            # paplay is the existing PulseAudio-compatible PipeWire client and
            # provides reliable EOF/exit completion for Kokoro's 24 kHz WAVs.
            play = subprocess.Popen(["paplay", str(temp_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self._lock:
                self._play_process = play
            callbacks.started()
            log.warning("WAKE_DEBUG TTS playback process started generation=%d pid=%d path=%s", generation, play.pid, temp_path)
            callbacks.level(1.0)
            actual_rate = sample_rate or SAMPLE_RATE
            duration_sec = len(pcm) / float(actual_rate) if actual_rate > 0 else 5.0
            playback_timeout = max(10.0, duration_sec + 5.0)
            try:
                play.wait(timeout=playback_timeout)
            except subprocess.TimeoutExpired:
                try:
                    play.kill()
                    play.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                raise RuntimeError("Kokoro playback timed out")
            if play.returncode == 0:
                log.warning("WAKE_DEBUG TTS playback success generation=%d pid=%d", generation, play.pid)
            else:
                log.error("WAKE_DEBUG TTS playback failure generation=%d pid=%d returncode=%s", generation, play.pid, play.returncode)
            callbacks.level(0.0)
            if self._current(generation):
                callbacks.finished()
        except (OSError, RuntimeError, ValueError) as exc:
            log.exception("WAKE_DEBUG TTS Kokoro failed generation=%d", generation)
            if self._current(generation):
                callbacks.failed(str(exc))
        finally:
            with self._lock:
                if self._play_process is not None and self._play_process.poll() is not None:
                    self._play_process = None
                if self._temp_path == temp_path:
                    self._temp_path = None
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
