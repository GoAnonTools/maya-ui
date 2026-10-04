"""Provider-neutral context data for future routing policy evaluation.

These types only carry request metadata.  They intentionally do not evaluate
the metadata or make execution, tool, privacy, or worker-selection decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PrivacyMode(StrEnum):
    """User-selected privacy posture carried into routing policy."""

    STANDARD = "standard"
    SENSITIVE = "sensitive"
    LOCAL_ONLY = "local_only"


class NetworkPolicy(StrEnum):
    """Network preference or constraint supplied for a request."""

    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    REQUIRED = "required"


class ToolPolicy(StrEnum):
    """Tool-use posture supplied for a request."""

    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True, slots=True)
class RoutingContext:
    """Immutable metadata envelope for a future routing-policy evaluation."""

    request_id: str
    session_id: str
    conversation_id: str | int | None
    intent_classification: str
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    privacy_mode: PrivacyMode = PrivacyMode.STANDARD
    network_policy: NetworkPolicy = NetworkPolicy.ALLOWED
    tool_policy: ToolPolicy = ToolPolicy.DISALLOWED
    user_preference_mode: str = "default"
    external_processing_allowed: bool = True
    offline_processing_allowed: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "session_id",
            "intent_classification",
            "user_preference_mode",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must not be empty")
        if not isinstance(self.privacy_mode, PrivacyMode):
            raise TypeError("privacy_mode must be a PrivacyMode")
        if not isinstance(self.network_policy, NetworkPolicy):
            raise TypeError("network_policy must be a NetworkPolicy")
        if not isinstance(self.tool_policy, ToolPolicy):
            raise TypeError("tool_policy must be a ToolPolicy")
        object.__setattr__(
            self,
            "required_capabilities",
            frozenset(self.required_capabilities),
        )


__all__ = ["NetworkPolicy", "PrivacyMode", "RoutingContext", "ToolPolicy"]

