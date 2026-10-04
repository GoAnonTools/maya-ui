"""Provider-neutral conversation/session request coordination."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from ..llm import LLMMessage, LLMRequest, LLMToolDefinition
from ..prompt_builder import build_prompt


class ConversationCoordinator:
    """Own conversation identifiers and assemble provider-neutral requests.

    Memory retrieval remains outside this class. Callers provide the already
    retrieved memory context, while this class owns prompt composition and the
    request/session identifiers shared by all providers.
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        conversation_id: str | int | None = None,
        prompt_builder: Callable[[str, str, str | object | None, str], str] = build_prompt,
    ) -> None:
        self._session_id = session_id or str(uuid4())
        self._conversation_id = conversation_id
        self._prompt_builder = prompt_builder

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def conversation_id(self) -> str | int | None:
        return self._conversation_id

    def set_session_id(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        self._session_id = session_id

    def set_conversation_id(self, conversation_id: str | int | None) -> None:
        if conversation_id is not None and not isinstance(conversation_id, (str, int)):
            raise ValueError("conversation_id must be a string, integer, or None")
        self._conversation_id = conversation_id

    def reset_conversation(self) -> None:
        """Start a new Core conversation while retaining the UI session."""
        self._conversation_id = None

    def build_prompt(
        self,
        behaviour_instruction: str,
        language_instruction: str,
        memory_context: str | object | None,
        user_text: str,
    ) -> str:
        return self._prompt_builder(behaviour_instruction, language_instruction, memory_context, user_text)

    def create_request(
        self,
        prompt: str,
        *,
        conversation_id: str | int | None = None,
        tools: tuple[LLMToolDefinition, ...] = (),
        tool_choice: Literal["auto", "none", "required"] = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMRequest:
        if conversation_id is not None or self._conversation_id is None:
            self._conversation_id = conversation_id
        return LLMRequest(
            messages=(LLMMessage(role="user", content=prompt),),
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            conversation_id=self._conversation_id,
            session_id=self._session_id,
        )

    def prepare_request(
        self,
        *,
        behaviour_instruction: str,
        language_instruction: str,
        memory_context: str | object | None,
        user_text: str,
        conversation_id: str | int | None = None,
        tools: tuple[LLMToolDefinition, ...] = (),
        tool_choice: Literal["auto", "none", "required"] = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, LLMRequest]:
        prompt = self.build_prompt(behaviour_instruction, language_instruction, memory_context, user_text)
        return prompt, self.create_request(
            prompt,
            conversation_id=conversation_id,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
        )
