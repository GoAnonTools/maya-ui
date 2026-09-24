"""Piper subprocess provider with cancellable PipeWire playback."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from .base import PlaybackCallbacks, Voice


VOICE_ROOT = Path.home() / ".local" / "share" / "maya" / "voices"
PIPER = Path.home() / ".local" / "share" / "maya" / "piper-venv" / "bin" / "piper"


class PiperProvider:
    name = "piper"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._piper_process: subprocess.Popen[bytes] | None = None
        self._play_process: subprocess.Popen[bytes] | None = None
        self._temp_path: Path | None = None

    def voices(self) -> list[Voice]:
        result: list[Voice] = []
        if not VOICE_ROOT.is_dir():
            return result
        for config_path in sorted(VOICE_ROOT.glob("*/*.onnx.json")):
            model_path = config_path.with_suffix("")
            if not model_path.exists():
                continue
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            name = model_path.stem
            language = str(config.get("language", name.split("-")[0]))
            gender = str(config.get("gender", "unknown"))
            result.append(Voice(name, self.name, language, gender, str(model_path)))
        return result

    def speak(self, text: str, voice: Voice, rate: float, callbacks: PlaybackCallbacks) -> None:
        self.stop()
        with self._lock:
            self._generation += 1
            generation = self._generation
        thread = threading.Thread(
            target=self._run,
            args=(generation, text, voice, rate, callbacks),
            name="maya-piper-tts",
            daemon=True,
        )
        thread.start()

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            processes = (self._play_process, self._piper_process)
            self._play_process = None
            self._piper_process = None
            temp_path = self._temp_path
            self._temp_path = None
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
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    def _current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _run(self, generation: int, text: str, voice: Voice, rate: float, callbacks: PlaybackCallbacks) -> None:
        temp_path: Path | None = None
        try:
            if not PIPER.exists():
                raise RuntimeError(f"Piper runtime not found: {PIPER}")
            fd, raw_path = tempfile.mkstemp(prefix="maya-tts-", suffix=".wav")
            os.close(fd)
            temp_path = Path(raw_path)
            with self._lock:
                if generation != self._generation:
                    return
                self._temp_path = temp_path
            length_scale = max(0.25, min(4.0, 1.0 / max(0.25, rate)))
            process = subprocess.Popen(
                [str(PIPER), "-m", voice.model_path, "-f", str(temp_path),
                 "--length-scale", f"{length_scale:.4f}", "--sentence-silence", "0.05"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            with self._lock:
                self._piper_process = process
            _stdout, stderr = process.communicate(text.encode("utf-8"))
            if process.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace").strip() if stderr else ""
                raise RuntimeError(detail or "Piper synthesis failed")
            if not self._current(generation):
                return
            play = subprocess.Popen(["pw-play", str(temp_path)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            with self._lock:
                self._play_process = play
            callbacks.started()
            callbacks.level(1.0)
            play.wait()
            callbacks.level(0.0)
            if self._current(generation):
                callbacks.finished()
        except (OSError, RuntimeError) as exc:
            if self._current(generation):
                callbacks.failed(str(exc))
        finally:
            with self._lock:
                if self._piper_process is not None and self._piper_process.poll() is not None:
                    self._piper_process = None
                if self._play_process is not None and self._play_process.poll() is not None:
                    self._play_process = None
                if self._temp_path == temp_path:
                    self._temp_path = None
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
