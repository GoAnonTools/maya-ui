"""CPU sherpa-onnx KWS with same-stream post-wake command capture."""

from __future__ import annotations

import os
import logging
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
import sys

WAKE_ROOT = Path.home() / ".local" / "share" / "maya" / "wake"
KWS_SITE = WAKE_ROOT / "venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if str(KWS_SITE) not in sys.path:
    sys.path.insert(0, str(KWS_SITE))

import numpy as np
from ..audio import selected_source

MODEL_ROOT = WAKE_ROOT / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
RUNTIME = WAKE_ROOT / "venv" / "bin" / "python"
KEYWORDS = WAKE_ROOT / "keywords.txt"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "maya-wake"
SAMPLE_RATE = 16000
FRAME_SAMPLES = 1600  # 100 ms
SILENCE_SECONDS = 0.9
MAX_COMMAND_SECONDS = 20.0
log = logging.getLogger("maya.wake")


def decoder_result_details(result) -> tuple[str, object, object]:
    """Normalize sherpa-onnx string and structured decoder results."""
    if isinstance(result, str):
        return result, [], []
    keyword = str(getattr(result, "keyword", ""))
    tokens = getattr(result, "tokens", [])
    timestamps = getattr(result, "timestamps", [])
    return keyword, tokens, timestamps


class SherpaProvider:
    name = "sherpa-onnx"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._paused = True
        self._command_path: Path | None = None
        self._command_mode = False
        self._state = "stopped"

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def _set_state(self, state: str, detail: str = "") -> None:
        with self._lock:
            self._state = state
        suffix = f": {detail}" if detail else ""
        log.info("Sherpa wake provider -> %s%s", state, suffix)

    def start(self, sensitivity: float, callbacks) -> None:
        self.stop("restart before start")
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._paused = False
            self._state = "starting"
        log.info("Wake start generation=%d sensitivity=%.3f", generation, sensitivity)
        thread = threading.Thread(target=self._run, args=(generation, sensitivity, callbacks), name="maya-wake-capture", daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()

    def stop(self, reason: str = "requested") -> None:
        with self._lock:
            self._generation += 1
            process = self._process
            thread = self._thread
            self._process = None
            self._paused = True
            self._command_mode = False
            # The controller owns cleanup for any command WAV already handed to STT.
            self._command_path = None
            self._state = "stopped"
        log.info("Wake stop reason=%s pid=%s", reason, process.pid if process is not None else "none")
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            if self._thread is thread:
                self._thread = None
    def pause(self, reason: str = "requested") -> bool:
        with self._lock:
            command_mode = self._command_mode
            process = self._process
        log.info(
            "Wake pause reason=%s command_mode=%s pid=%s",
            reason,
            command_mode,
            process.pid if process is not None else "none",
        )
        if not command_mode:
            self.stop(reason)
            self._set_state("paused", reason)
        return command_mode

    def resume(self) -> bool:
        with self._lock:
            process = self._process
            thread = self._thread
            alive = process is not None and process.poll() is None and thread is not None and thread.is_alive()
            if not alive:
                log.warning(
                    "Wake resume failed: capture is not alive pid=%s thread_alive=%s",
                    process.pid if process is not None else "none",
                    thread.is_alive() if thread is not None else False,
                )
                return False
            self._paused = False
            self._state = "listening"
        log.info("Wake resume reason=existing capture still alive pid=%s", process.pid)
        return True

    def release_command(self, path: str) -> None:
        with self._lock:
            if self._command_path == Path(path):
                self._command_path = None
        Path(path).unlink(missing_ok=True)

    def _current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _run(self, generation: int, sensitivity: float, callbacks) -> None:
        process = None
        try:
            from sherpa_onnx import KeywordSpotter

            encoder = MODEL_ROOT / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
            decoder = MODEL_ROOT / "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
            joiner = MODEL_ROOT / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
            if not all(path.exists() for path in (encoder, decoder, joiner, KEYWORDS)):
                raise RuntimeError("sherpa-onnx wake model is missing")
            # Higher sensitivity means a lower sherpa trigger threshold.
            threshold = max(0.10, min(0.80, 0.85 - float(sensitivity) * 0.60))
            input_source = selected_source()
            kws = KeywordSpotter(
                tokens=str(MODEL_ROOT / "tokens.txt"), encoder=str(encoder), decoder=str(decoder),
                joiner=str(joiner), keywords_file=str(KEYWORDS), num_threads=1,
                sample_rate=SAMPLE_RATE, keywords_score=1.5,
                keywords_threshold=threshold, provider="cpu",
            )
            stream = kws.create_stream()
            command_frames: list[np.ndarray] = []
            speech_seen = False
            silence_frames = 0
            command_started_at = 0.0
            import time

            command_mode = False
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            command = ["pw-record", "--target", input_source, "--raw", "--rate", str(SAMPLE_RATE), "--channels", "1", "--format", "f32", "--media-category", "Capture", "-"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            with self._lock:
                if generation != self._generation:
                    process.terminate()
                    return
                self._process = process
                self._state = "listening"
            log.info("Wake capture process started pid=%d generation=%d", process.pid, generation)
            callbacks.level(0.0)
            while self._current(generation) and process.stdout is not None:
                raw = process.stdout.read(FRAME_SAMPLES * 4)
                if not raw:
                    with self._lock:
                        paused = self._paused
                    if self._current(generation) and not paused:
                        raise RuntimeError("audio capture stream closed unexpectedly")
                    break
                audio = np.frombuffer(raw, dtype=np.float32)
                if audio.size != FRAME_SAMPLES:
                    continue
                now = time.monotonic()
                # The selected microphone carries a large hardware DC offset.
                # Remove it per frame and apply bounded normalization so the
                # wake model receives centered, safely scaled float32 audio.
                raw_mean = float(np.mean(audio))
                centered = audio - raw_mean
                centered_peak = float(np.max(np.abs(centered)))
                gain = 1.0 if centered_peak < 1.0e-6 else min(4.0, 0.5 / centered_peak)
                audio = np.clip(centered * gain, -1.0, 1.0).astype(np.float32, copy=False)
                with self._lock:
                    paused = self._paused
                if paused and not command_mode:
                    continue
                if not command_mode:
                    stream.accept_waveform(SAMPLE_RATE, audio)
                    while kws.is_ready(stream):
                        kws.decode_stream(stream)
                    result = kws.get_result(stream)
                    if result:
                        keyword, _, _ = decoder_result_details(result)
                        normalized_keyword = keyword.strip().upper()
                        kws.reset_stream(stream)
                        command_mode = True
                        with self._lock:
                            self._command_mode = True
                        command_frames = []
                        speech_seen = False
                        silence_frames = 0
                        command_started_at = time.monotonic()
                        callbacks.detected()
                    continue

                rms = float(np.sqrt(np.mean(np.square(audio))))
                threshold = 0.018
                if not speech_seen:
                    if rms >= threshold:
                        speech_seen = True
                        command_frames.append(audio.copy())
                        silence_frames = 0
                    elif time.monotonic() - command_started_at > 5.0:
                        command_mode = False
                        with self._lock:
                            self._command_mode = False
                    continue
                command_frames.append(audio.copy())
                if rms < threshold:
                    silence_frames += 1
                else:
                    silence_frames = 0
                elapsed = time.monotonic() - command_started_at
                if silence_frames >= int(SILENCE_SECONDS * 10) or elapsed >= MAX_COMMAND_SECONDS:
                    path = self._write_command(command_frames)
                    with self._lock:
                        self._command_path = path
                    # End the single wake-owned capture before handing the
                    # WAV to STT; commandReady must never overlap pw-record.
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=1)
                    callbacks.command_ready(str(path))
                    command_mode = False
                    with self._lock:
                        self._command_mode = False
                    command_frames = []
                    speech_seen = False
                    silence_frames = 0
                    break
            
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            log.error("Wake capture failed generation=%d: %s", generation, exc)
            self._set_state("error", str(exc))
            if self._current(generation):
                callbacks.failed(str(exc))
        finally:
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
            with self._lock:
                self._command_mode = False
                if self._process is process:
                    self._process = None
                if self._thread is threading.current_thread():
                    self._thread = None
                if self._state != "error":
                    self._state = "stopped"
            log.info("Wake capture thread exited generation=%d pid=%s", generation, process.pid if process is not None else "none")

    def _write_command(self, frames: list[np.ndarray]) -> Path:
        fd, raw_path = tempfile.mkstemp(prefix="maya-wake-", suffix=".wav", dir=RUNTIME_DIR)
        os.close(fd)
        path = Path(raw_path)
        audio = np.concatenate(frames) if frames else np.zeros(1, dtype=np.float32)
        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype(np.int16)
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)
            out.writeframes(pcm.tobytes())
        return path
