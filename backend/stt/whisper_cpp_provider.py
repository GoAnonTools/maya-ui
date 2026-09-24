"""CPU-only whisper.cpp provider using PipeWire WAV capture."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import logging
import wave
from pathlib import Path

from .base import AudioDevice, STTCallbacks

log = logging.getLogger("maya.stt")


STT_ROOT = Path.home() / ".local" / "share" / "maya" / "stt"
RUNTIME_ROOT = STT_ROOT / "runtime"
WHISPER = RUNTIME_ROOT / "usr" / "bin" / "whisper-cli"
RUNTIME_LIBS = RUNTIME_ROOT / "usr" / "lib"
RUNTIME_BACKENDS = RUNTIME_LIBS / "ggml"
# The generic x64 plugin in the Arch package crashes during device discovery
# on this Ryzen host; Haswell is the compatible AVX2 CPU backend and works on
# Zen 3 while remaining CPU-only.
CPU_BACKEND = RUNTIME_BACKENDS / "libggml-cpu-haswell.so"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "maya-stt"


class WhisperCppProvider:
    name = "whisper.cpp"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._record_process: subprocess.Popen[bytes] | None = None
        self._transcribe_process: subprocess.Popen[bytes] | None = None
        self._audio_path: Path | None = None

    def list_devices(self) -> list[AudioDevice]:
        devices = [AudioDevice("default", "Default PipeWire microphone")]
        try:
            result = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            return devices
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) >= 2 and ".monitor" not in fields[1]:
                devices.append(AudioDevice(fields[1], fields[1]))
        return devices

    def start(self, device: str, language: str, model: str, callbacks: STTCallbacks) -> None:
        self.cancel()
        with self._lock:
            self._generation += 1
            generation = self._generation
        thread = threading.Thread(
            target=self._record,
            args=(generation, device, language, model, callbacks),
            name="maya-pw-record",
            daemon=True,
        )
        thread.start()

    def stop(self) -> None:
        """Finish capture and transcribe the recorded segment."""
        with self._lock:
            process = self._record_process
        if process is not None and process.poll() is None:
            process.terminate()

    def cancel(self) -> None:
        with self._lock:
            self._generation += 1
            processes = (self._record_process, self._transcribe_process)
            self._record_process = None
            self._transcribe_process = None
            audio_path = self._audio_path
            self._audio_path = None
        for process in processes:
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)

    def transcribe_file(self, path: str, language: str, model: str, callbacks: STTCallbacks) -> None:
        """Transcribe an externally captured WAV using the normal Whisper path."""
        self.cancel()
        with self._lock:
            self._generation += 1
            generation = self._generation
        log.warning("WAKE_DEBUG STT provider transcribe_file entry path=%s generation=%d model=%s language=%s", path, generation, model, language)
        thread = threading.Thread(
            target=self._transcribe_file,
            args=(generation, Path(path), language, model, callbacks),
            name="maya-whisper-file",
            daemon=True,
        )
        thread.start()
        log.warning("WAKE_DEBUG STT provider transcription thread started name=%s generation=%d", thread.name, generation)

    def _transcribe_file(self, generation: int, audio_path: Path, language: str, model: str, callbacks: STTCallbacks) -> None:
        try:
            log.warning("WAKE_DEBUG STT worker entry generation=%d path=%s", generation, audio_path)
            if not audio_path.exists():
                log.warning(
                    "WAKE_DEBUG STT WAV unavailable path=%s exists=False parent_exists=%s",
                    audio_path, audio_path.parent.exists(),
                )
                raise RuntimeError("Captured audio is missing")
            stat = audio_path.stat()
            log.warning("WAKE_DEBUG STT WAV present path=%s bytes=%d", audio_path, stat.st_size)
            if stat.st_size == 0:
                log.warning("WAKE_DEBUG STT WAV invalid reason=zero_bytes path=%s", audio_path)
                raise RuntimeError("Captured audio is empty")
            try:
                with wave.open(str(audio_path), "rb") as wav:
                    frames = wav.getnframes()
                    rate = wav.getframerate()
                    log.warning(
                        "WAKE_DEBUG STT WAV loaded channels=%d width=%d rate=%d frames=%d duration=%.3fs",
                        wav.getnchannels(), wav.getsampwidth(), rate, frames,
                        frames / rate if rate else 0.0,
                    )
                    if frames == 0:
                        log.warning("WAKE_DEBUG STT WAV invalid reason=zero_frames path=%s", audio_path)
                        raise RuntimeError("Captured audio has zero frames")
            except wave.Error as exc:
                log.warning("WAKE_DEBUG STT WAV invalid reason=invalid_format path=%s error=%s", audio_path, exc)
                raise RuntimeError(f"Captured audio is not a valid WAV: {exc}") from exc
            callbacks.transcribing()
            log.warning("WAKE_DEBUG STT transcription start generation=%d", generation)
            self._transcribe(generation, audio_path, language, model, callbacks)
        except Exception as exc:
            log.exception("WAKE_DEBUG STT worker failed generation=%d path=%s", generation, audio_path)
            if self._current(generation):
                callbacks.failed(str(exc))

    def _current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _record(self, generation: int, device: str, language: str, model: str, callbacks: STTCallbacks) -> None:
        audio_path: Path | None = None
        try:
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            fd, raw_path = tempfile.mkstemp(prefix="maya-", suffix=".wav", dir=RUNTIME_DIR)
            os.close(fd)
            audio_path = Path(raw_path)
            with self._lock:
                if generation != self._generation:
                    return
                self._audio_path = audio_path
            command = ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", "--media-category", "Capture"]
            if device and device != "default":
                command += ["--target", device]
            command.append(str(audio_path))
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            with self._lock:
                self._record_process = process
            log.warning("WAKE_DEBUG STT recording started pid=%d generation=%d", process.pid, generation)
            callbacks.started()
            callbacks.level(0.35)
            process.wait()
            if not self._current(generation):
                return
            if not audio_path.exists() or audio_path.stat().st_size <= 44 + 1600:
                callbacks.failed("No speech detected")
                return
            callbacks.transcribing()
            self._transcribe(generation, audio_path, language, model, callbacks)
        except (OSError, RuntimeError) as exc:
            if self._current(generation):
                callbacks.failed(str(exc))
        finally:
            with self._lock:
                if self._record_process is not None and self._record_process.poll() is not None:
                    self._record_process = None
                if self._transcribe_process is not None and self._transcribe_process.poll() is not None:
                    self._transcribe_process = None
                if self._audio_path == audio_path:
                    self._audio_path = None
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)

    def _transcribe(self, generation: int, audio_path: Path, language: str, model: str, callbacks: STTCallbacks) -> None:
        model_path = STT_ROOT / f"ggml-{model}.bin"
        log.warning("WAKE_DEBUG STT model check runtime=%s exists=%s model=%s exists=%s", WHISPER, WHISPER.exists(), model_path, model_path.exists())
        if not WHISPER.exists() or not model_path.exists():
            raise RuntimeError("whisper.cpp runtime or model is missing")
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = f"{RUNTIME_LIBS}:{RUNTIME_BACKENDS}:" + env.get("LD_LIBRARY_PATH", "")
        # The Arch package defaults to /usr/lib/ggml; keep the extracted
        # user-owned runtime self-contained and select its CPU backend.
        env["GGML_BACKEND_PATH"] = str(CPU_BACKEND)
        command = [str(WHISPER), "-m", str(model_path), "-f", str(audio_path), "-l", language or "auto", "--no-gpu", "-nt", "-np"]
        log.warning("WAKE_DEBUG STT launching whisper generation=%d command=%r", generation, command)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        with self._lock:
            self._transcribe_process = process
        log.warning("WAKE_DEBUG STT whisper started pid=%d generation=%d", process.pid, generation)
        stdout, stderr = process.communicate()
        log.warning("WAKE_DEBUG STT whisper finished pid=%d generation=%d returncode=%s stdout_bytes=%d stderr_bytes=%d", process.pid, generation, process.returncode, len(stdout), len(stderr))
        if not self._current(generation):
            return
        if process.returncode != 0:
            raise RuntimeError(stderr.strip() or "whisper.cpp transcription failed")
        text = re.sub(r"\[(?:BLANK_AUDIO|NO_SPEECH)\]", "", stdout, flags=re.IGNORECASE)
        text = re.sub(r"<\|[^>]+\|>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text or len(re.sub(r"[^\wÀ-ÿ]", "", text, flags=re.UNICODE)) < 2:
            callbacks.failed("No intelligible speech detected")
            return
        log.warning("WAKE_DEBUG STT transcription result generation=%d text=%r", generation, text)
        callbacks.level(0.0)
        callbacks.transcript(text)
