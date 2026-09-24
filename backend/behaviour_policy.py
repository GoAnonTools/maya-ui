"""Deterministic, LLM-independent response intent policy for Maya.

This module only classifies request text and provides bounded guidance. It has
no runtime integrations and performs no I/O.
"""

from __future__ import annotations

import re
from enum import Enum


class IntentCategory(str, Enum):
    FACTUAL = "simple_factual_question"
    ACTION = "action_or_tool_request"
    CONFIRMATION = "pending_confirmation"
    EXPLANATION = "explanation"
    CONVERSATION = "conversation"
    CREATIVE = "creative_request"
    UNCERTAIN = "uncertain"


MAX_POLICY_INSTRUCTION_CHARS = 420

_POLICY_INSTRUCTIONS = {
    IntentCategory.FACTUAL: (
        "Answer first, usually in one or two sentences. Avoid unnecessary "
        "background; state uncertainty instead of guessing."
    ),
    IntentCategory.ACTION: (
        "Carry out the requested action using available authorized tools when "
        "needed. Ask a concise question if ambiguity could change the target "
        "or outcome. Confirm the result briefly; do not explain the tool or "
        "process unless asked."
    ),
    IntentCategory.CONFIRMATION: (
        "Apply this response only to the currently pending confirmation. "
        "Honor a clear yes or no for that action only; never treat it as "
        "approval for a different action. If no confirmation is pending, "
        "do not infer authorization."
    ),
    IntentCategory.EXPLANATION: (
        "Provide useful detail when the user asks how or why. Use steps or an "
        "example when helpful, and avoid unrelated background."
    ),
    IntentCategory.CONVERSATION: (
        "Respond naturally and proportionately. Do not force a structured "
        "answer, list, or action into casual conversation."
    ),
    IntentCategory.CREATIVE: (
        "Create the requested material directly and follow the requested "
        "format, style, and constraints. Ask only when a missing choice "
        "materially affects the result."
    ),
    IntentCategory.UNCERTAIN: (
        "Be concise and answer the apparent request. If important ambiguity "
        "prevents a reliable answer or action, ask one focused clarification."
    ),
}

_ACTION_VERBS = frozenset(
    {
        "open", "launch", "start", "close", "quit", "focus", "switch",
        "show", "hide", "find", "search", "list", "read", "save", "move",
        "copy", "delete", "create", "rename", "install", "run", "execute",
        "set", "change", "turn", "play", "pause", "stop", "send", "email",
        "schedule", "remind", "remember", "forget",
    }
)
_EXPLANATION_START = re.compile(
    r"^(?:please\s+)?(?:explain|describe|teach(?:\s+me)?|tell\s+me\s+about|"
    r"why\b|how\s+(?:does|do|did|is|are|can|could|would|should)\b|"
    r"what\s+does\b|what\s+is\s+the\s+difference\s+between)\b",
    re.IGNORECASE,
)
_CREATIVE_VERBS = frozenset(
    {"write", "compose", "draft", "invent", "brainstorm", "design", "imagine", "create"}
)
_LEADING_GREETING = re.compile(
    r"^(?:good morning|good afternoon|good evening|thank you|thanks|hello|hi|hey|goodbye|bye)"
    r"(?:\s+maya)?(?:[\s,!.:;–—-]+|$)",
    re.IGNORECASE,
)
_CASUAL_PHRASE = re.compile(
    r"^(?:how are you(?: doing)?|hello|hi|hey|good morning|good afternoon|good evening|"
    r"thanks|thank you|goodbye|bye)[.!?\s]*$",
    re.IGNORECASE,
)
_AFFIRMATIVE = frozenset({"yes", "yeah", "yep", "sure", "confirm", "confirmed", "do it"})
_NEGATIVE = frozenset({"no", "nope", "cancel", "never mind", "nevermind"})
_CREATE_TARGETS = frozenset(
    {"file", "folder", "directory", "document", "spreadsheet", "presentation", "note", "shortcut"}
)


def classify_intent(text: str, *, pending_confirmation: bool = False) -> IntentCategory:
    """Classify common English desktop-assistant requests without model calls.

    A standalone yes/no is a confirmation only when the caller says one is
    pending. The flag supplies context for classification; it does not perform
    or authorize the pending operation. Unfamiliar or underspecified text
    returns ``UNCERTAIN`` rather than inferring an action.
    """
    if not isinstance(text, str) or not text.strip():
        return IntentCategory.UNCERTAIN

    value = text.strip().casefold()
    normalized = re.sub(r"[.!?]+$", "", value).strip()
    if pending_confirmation and normalized in _AFFIRMATIVE | _NEGATIVE:
        return IntentCategory.CONFIRMATION

    # A salutation is context, not the request. Remove one leading greeting
    # before classifying so "Good morning, what time is it?" stays factual.
    value = _LEADING_GREETING.sub("", value, count=1).strip()
    if not value or _CASUAL_PHRASE.fullmatch(value):
        return IntentCategory.CONVERSATION

    words = re.findall(r"[\w']+", value, flags=re.UNICODE)
    if not words:
        return IntentCategory.UNCERTAIN

    if re.match(r"^how are you(?: doing)?[.!?\s]*$", value):
        return IntentCategory.CONVERSATION

    if _EXPLANATION_START.match(value):
        return IntentCategory.EXPLANATION

    # Handle polite/inverted requests such as "could you open Firefox".
    # "Create" is shared by file actions and creative requests, so require a
    # concrete file-system-like target to treat it as an action.
    action_index = next((index for index, word in enumerate(words[:4]) if word in _ACTION_VERBS), None)
    is_action = action_index is not None
    if is_action and words[action_index] == "create":
        is_action = bool(set(words[action_index + 1:]) & _CREATE_TARGETS)
    if is_action:
        return IntentCategory.ACTION

    first = words[0]
    if first in _CREATIVE_VERBS:
        return IntentCategory.CREATIVE

    if value.endswith("?") or first in {"who", "what", "when", "where", "which", "whose", "is", "are", "does", "do", "did", "can", "could"}:
        return IntentCategory.FACTUAL

    return IntentCategory.UNCERTAIN


def policy_instruction(
    intent: IntentCategory | str,
    *,
    max_chars: int = MAX_POLICY_INSTRUCTION_CHARS,
) -> str:
    """Return fixed response guidance, capped at a caller-selected safe length."""
    try:
        category = intent if isinstance(intent, IntentCategory) else IntentCategory(intent)
    except (TypeError, ValueError):
        category = IntentCategory.UNCERTAIN

    limit = max(0, min(int(max_chars), MAX_POLICY_INSTRUCTION_CHARS))
    return _POLICY_INSTRUCTIONS[category][:limit]
