"""Pure routing-domain contracts for Maya Core.

These models describe routing decisions and delegation state. They intentionally
contain no provider, Qt, controller, transport, or execution logic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ProviderRole(StrEnum):
    """The policy role a worker is intended to perform."""

    CONVERSATIONAL = "conversational"
    SPECIALIST = "specialist"
    OFFLINE_FALLBACK = "offline_fallback"
    LEGACY_COMPATIBILITY = "legacy_compatibility"


@dataclass(frozen=True, slots=True)
class WorkerCapability:
    """Advertised capabilities and execution constraints for one worker."""

    provider_id: str
    role: ProviderRole
    display_name: str
    available: bool = True
    unavailable_reason: str | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)
    max_context_tokens: int | None = None
    latency_class: str = "normal"
    cost_class: str = "unknown"
    privacy_class: str = "unknown"

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider_id must not be empty")
        if not self.display_name:
            raise ValueError("display_name must not be empty")
        if not isinstance(self.role, ProviderRole):
            raise TypeError("role must be a ProviderRole")
        if self.max_context_tokens is not None and self.max_context_tokens <= 0:
            raise ValueError("max_context_tokens must be positive when provided")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))


@dataclass(frozen=True, slots=True)
class FallbackPolicy:
    """Permitted fallback roles for a classified request."""

    ordered_roles: tuple[ProviderRole, ...] = ()
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    preserve_capabilities: bool = True
    allow_downgrade: bool = False
    allow_external_processing: bool = True
    allow_offline_processing: bool = True
    require_user_approval: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordered_roles", tuple(self.ordered_roles))
        object.__setattr__(self, "required_capabilities", frozenset(self.required_capabilities))
        if any(not isinstance(role, ProviderRole) for role in self.ordered_roles):
            raise TypeError("ordered_roles must contain ProviderRole values")


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """The Core decision describing how one request should be executed."""

    schema_version: int
    request_id: str
    session_id: str
    conversation_id: str | int | None
    intent: str
    required_capabilities: frozenset[str]
    privacy_mode: str
    network_policy: str
    tool_policy: str
    preferred_role: ProviderRole
    selected_role: ProviderRole
    selected_provider_id: str
    reason_code: str
    fallback_policy: FallbackPolicy
    delegation_request_id: str | None = None
    user_visible: bool = False

    def __post_init__(self) -> None:
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        for field_name in ("request_id", "session_id", "intent", "privacy_mode", "network_policy", "tool_policy", "selected_provider_id", "reason_code"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must not be empty")
        if not isinstance(self.preferred_role, ProviderRole) or not isinstance(self.selected_role, ProviderRole):
            raise TypeError("preferred_role and selected_role must be ProviderRole values")
        object.__setattr__(self, "required_capabilities", frozenset(self.required_capabilities))


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """Scoped request for work by a specialist worker."""

    delegation_id: str
    parent_request_id: str
    session_id: str
    conversation_id: str | int | None
    worker_role: ProviderRole
    worker_id: str
    task_summary: str
    required_capabilities: frozenset[str]
    workspace: str | None = None
    allowed_operations: frozenset[str] = field(default_factory=frozenset)
    network_allowed: bool = False
    approval_required: bool = True

    def __post_init__(self) -> None:
        for field_name in ("delegation_id", "parent_request_id", "session_id", "worker_id", "task_summary"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must not be empty")
        if not isinstance(self.worker_role, ProviderRole):
            raise TypeError("worker_role must be a ProviderRole")
        object.__setattr__(self, "required_capabilities", frozenset(self.required_capabilities))
        object.__setattr__(self, "allowed_operations", frozenset(self.allowed_operations))


class DelegationEventType(StrEnum):
    """Lifecycle events emitted for one specialist delegation."""

    PROPOSED = "delegation.proposed"
    APPROVAL_REQUIRED = "delegation.approval_required"
    APPROVED = "delegation.approved"
    REJECTED = "delegation.rejected"
    STARTED = "delegation.started"
    PROGRESS = "delegation.progress"
    TOOL_REQUEST = "delegation.tool_request"
    TOOL_RESULT = "delegation.tool_result"
    COMPLETED = "delegation.completed"
    FAILED = "delegation.failed"
    CANCELLED = "delegation.cancelled"


@dataclass(frozen=True, slots=True)
class DelegationEvent:
    """Ordered event envelope for one delegation lifecycle."""

    schema_version: int
    event_id: str
    event_type: DelegationEventType
    request_id: str
    session_id: str
    conversation_id: str | int | None
    delegation_id: str
    sequence: int
    timestamp: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        for field_name in ("event_id", "request_id", "session_id", "delegation_id", "timestamp"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must not be empty")
        if not isinstance(self.event_type, DelegationEventType):
            raise TypeError("event_type must be a DelegationEventType")
        if self.sequence < 0:
            raise ValueError("sequence must not be negative")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
