"""Small deterministic replies for clear, standalone local requests."""

from __future__ import annotations

import re
from datetime import datetime


_OPENING = re.compile(
    r"^(?:(?:maya|good morning|good afternoon|good evening|hello|hi|hey)"
    r"[\s,!.:;–—-]+)+",
    re.IGNORECASE,
)
_TRAILING_PUNCTUATION = re.compile(r"[\s.!?,;:]+$")

_TIME_REQUESTS = frozenset(
    {
        "what time is it",
        "what time is it now",
        "what is the time",
        "what's the time",
        "tell me the time",
        "current time",
    }
)
_DATE_REQUESTS = frozenset(
    {
        "what date is it",
        "what date is today",
        "what is the date",
        "what's the date",
        "what is today's date",
        "what's today's date",
        "what day is today",
        "what day is it today",
        "what day is it",
    }
)
_FOLDER_REQUEST = re.compile(
    r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
    r"(?:open|show(?:\s+me)?|open\s+up)\s+(?:(?:my|the)\s+)?"
    r"(downloads?|documents|pictures|projects)(?:\s+folder)?(?:\s+please)?$",
    re.IGNORECASE,
)
_APPLICATION_REQUEST = re.compile(
    r"^(?:open|launch|start)\s+(?:the\s+)?"
    r"(visual\s+studio\s+code|vs\s+code|firefox|dolphin)"
    r"(?:\s+(?:app|application))?$",
    re.IGNORECASE,
)
_APP_DISPLAY_NAMES = {
    "firefox": "Firefox",
    "dolphin": "Dolphin",
    "vs code": "VS Code",
    "visual studio code": "VS Code",
}


def _normalize_request(text: str) -> str:
    value = text.strip().casefold()
    value = _OPENING.sub("", value, count=1)
    return _TRAILING_PUNCTUATION.sub("", value).strip()


def _ordinal(day: int) -> str:
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def local_skill_response(text: str, *, now: datetime | None = None, mcp_client=None) -> str | None:
    """Return a deterministic spoken reply, otherwise ``None`` for the LLM.

    Only clear standalone English requests are matched. Desktop actions are
    executed through the supplied MCP client; this module performs no OS calls.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    request = _normalize_request(text)
    if request in _TIME_REQUESTS or request in _DATE_REQUESTS:
        value = now if now is not None else datetime.now().astimezone()
        if value.tzinfo is None:
            value = value.astimezone()
        if request in _TIME_REQUESTS:
            hour = value.strftime("%I").lstrip("0") or "12"
            minute = value.minute
            time_text = hour if minute == 0 else f"{hour}:{minute:02d}"
            return f"It's {time_text} {value.strftime('%p')}."
        return f"Today is {value.strftime('%A')}, {value.strftime('%B')} {_ordinal(value.day)}."

    folder_match = _FOLDER_REQUEST.fullmatch(request)
    if folder_match:
        folder = folder_match.group(1).title()
        if folder.casefold() == "download":
            folder = "Downloads"
        if not _run_mcp_action(mcp_client, "open_folder", {"folder": folder}):
            return f"I couldn't open your {folder} folder."
        return f"Done, I opened your {folder} folder."

    application_match = _APPLICATION_REQUEST.fullmatch(request)
    if application_match:
        alias = " ".join(application_match.group(1).casefold().split())
        app = _APP_DISPLAY_NAMES[alias]
        if not _run_mcp_action(mcp_client, "open_application", {"name": app}):
            return f"I couldn't open {app}."
        return f"Opening {app}."

    return None


def _run_mcp_action(mcp_client, tool_name: str, arguments: dict[str, str]) -> bool:
    if mcp_client is None:
        return False
    try:
        result = mcp_client.call_tool(tool_name, arguments)
    except Exception:
        return False
    return isinstance(result, dict) and result.get("ok") is True
