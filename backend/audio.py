"""Shared user-selected PipeWire/PulseAudio input source."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("maya.audio")
CONFIG_PATH = Path.home() / ".config" / "maya" / "audio.json"


def _load() -> dict:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def default_source() -> str:
    try:
        result = subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True, timeout=3)
        return result.stdout.strip() or "default"
    except (OSError, subprocess.TimeoutExpired):
        return "default"


def input_sources() -> list[str]:
    try:
        result = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return []
    sources = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and ".monitor" not in fields[1]:
            sources.append(fields[1])
    return sources


def configured_source() -> str:
    return str(_load().get("input_source", "")).strip()


def selected_source() -> str:
    configured = configured_source()
    available = input_sources()
    if configured:
        if not available or configured in available:
            return configured
        fallback = default_source()
        log.warning("Configured microphone source unavailable: %s; falling back to %s", configured, fallback)
        return fallback
    return default_source()


def save_source(source: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"input_source": source}, indent=2) + "\n", encoding="utf-8")
