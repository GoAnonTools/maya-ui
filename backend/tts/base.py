"""Stable provider contract used by Maya's TTS manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class Voice:
    name: str
    provider: str
    language: str
    gender: str
    model_path: str


class PlaybackCallbacks(Protocol):
    def started(self) -> None: ...
    def finished(self) -> None: ...
    def failed(self, message: str) -> None: ...
    def level(self, value: float) -> None: ...


class TTSProvider(Protocol):
    name: str

    def voices(self) -> list[Voice]: ...
    def speak(self, text: str, voice: Voice, rate: float, callbacks: PlaybackCallbacks) -> None: ...
    def stop(self) -> None: ...
