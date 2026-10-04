"""JSON-compatible serialization for routing domain objects."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, TypeVar

from .models import (
    DelegationEvent,
    DelegationEventType,
    DelegationRequest,
    FallbackPolicy,
    ProviderRole,
    RoutingDecision,
    WorkerCapability,
)


TEnum = TypeVar("TEnum", bound=StrEnum)


def worker_capability_to_dict(worker: WorkerCapability) -> dict[str, Any]:
    _require_type(worker, WorkerCapability)
    return {
        "provider_id": worker.provider_id,
        "role": worker.role.value,
        "display_name": worker.display_name,
        "available": worker.available,
        "unavailable_reason": worker.unavailable_reason,
        "capabilities": sorted(worker.capabilities),
        "max_context_tokens": worker.max_context_tokens,
        "latency_class": worker.latency_class,
        "cost_class": worker.cost_class,
        "privacy_class": worker.privacy_class,
    }


def worker_capability_from_dict(data: Mapping[str, Any]) -> WorkerCapability:
    data = _payload(data, "WorkerCapability")
    _required(data, "provider_id", "role", "display_name")
    return WorkerCapability(
        provider_id=data["provider_id"],
        role=_enum(ProviderRole, data["role"], "role"),
        display_name=data["display_name"],
        available=data.get("available", True),
        unavailable_reason=data.get("unavailable_reason"),
        capabilities=frozenset(data.get("capabilities", ())),
        max_context_tokens=data.get("max_context_tokens"),
        latency_class=data.get("latency_class", "normal"),
        cost_class=data.get("cost_class", "unknown"),
        privacy_class=data.get("privacy_class", "unknown"),
    )


def fallback_policy_to_dict(policy: FallbackPolicy) -> dict[str, Any]:
    _require_type(policy, FallbackPolicy)
    return {
        "ordered_roles": [role.value for role in policy.ordered_roles],
        "required_capabilities": sorted(policy.required_capabilities),
        "preserve_capabilities": policy.preserve_capabilities,
        "allow_downgrade": policy.allow_downgrade,
        "allow_external_processing": policy.allow_external_processing,
        "allow_offline_processing": policy.allow_offline_processing,
        "require_user_approval": policy.require_user_approval,
    }


def fallback_policy_from_dict(data: Mapping[str, Any]) -> FallbackPolicy:
    data = _payload(data, "FallbackPolicy")
    return FallbackPolicy(
        ordered_roles=tuple(
            _enum(ProviderRole, role, "ordered_roles")
            for role in data.get("ordered_roles", ())
        ),
        required_capabilities=frozenset(data.get("required_capabilities", ())),
        preserve_capabilities=data.get("preserve_capabilities", True),
        allow_downgrade=data.get("allow_downgrade", False),
        allow_external_processing=data.get("allow_external_processing", True),
        allow_offline_processing=data.get("allow_offline_processing", True),
        require_user_approval=data.get("require_user_approval", False),
    )


def routing_decision_to_dict(decision: RoutingDecision) -> dict[str, Any]:
    _require_type(decision, RoutingDecision)
    return {
        "schema_version": decision.schema_version,
        "request_id": decision.request_id,
        "session_id": decision.session_id,
        "conversation_id": decision.conversation_id,
        "intent": decision.intent,
        "required_capabilities": sorted(decision.required_capabilities),
        "privacy_mode": decision.privacy_mode,
        "network_policy": decision.network_policy,
        "tool_policy": decision.tool_policy,
        "preferred_role": decision.preferred_role.value,
        "selected_role": decision.selected_role.value,
        "selected_provider_id": decision.selected_provider_id,
        "reason_code": decision.reason_code,
        "fallback_policy": fallback_policy_to_dict(decision.fallback_policy),
        "delegation_request_id": decision.delegation_request_id,
        "user_visible": decision.user_visible,
    }


def routing_decision_from_dict(data: Mapping[str, Any]) -> RoutingDecision:
    data = _payload(data, "RoutingDecision")
    _required(
        data,
        "schema_version",
        "request_id",
        "session_id",
        "intent",
        "privacy_mode",
        "network_policy",
        "tool_policy",
        "preferred_role",
        "selected_role",
        "selected_provider_id",
        "reason_code",
        "fallback_policy",
    )
    return RoutingDecision(
        schema_version=data["schema_version"],
        request_id=data["request_id"],
        session_id=data["session_id"],
        conversation_id=data.get("conversation_id"),
        intent=data["intent"],
        required_capabilities=frozenset(data.get("required_capabilities", ())),
        privacy_mode=data["privacy_mode"],
        network_policy=data["network_policy"],
        tool_policy=data["tool_policy"],
        preferred_role=_enum(ProviderRole, data["preferred_role"], "preferred_role"),
        selected_role=_enum(ProviderRole, data["selected_role"], "selected_role"),
        selected_provider_id=data["selected_provider_id"],
        reason_code=data["reason_code"],
        fallback_policy=fallback_policy_from_dict(data["fallback_policy"]),
        delegation_request_id=data.get("delegation_request_id"),
        user_visible=data.get("user_visible", False),
    )


def delegation_request_to_dict(request: DelegationRequest) -> dict[str, Any]:
    _require_type(request, DelegationRequest)
    return {
        "delegation_id": request.delegation_id,
        "parent_request_id": request.parent_request_id,
        "session_id": request.session_id,
        "conversation_id": request.conversation_id,
        "worker_role": request.worker_role.value,
        "worker_id": request.worker_id,
        "task_summary": request.task_summary,
        "required_capabilities": sorted(request.required_capabilities),
        "workspace": request.workspace,
        "allowed_operations": sorted(request.allowed_operations),
        "network_allowed": request.network_allowed,
        "approval_required": request.approval_required,
    }


def delegation_request_from_dict(data: Mapping[str, Any]) -> DelegationRequest:
    data = _payload(data, "DelegationRequest")
    _required(
        data,
        "delegation_id",
        "parent_request_id",
        "session_id",
        "worker_role",
        "worker_id",
        "task_summary",
    )
    return DelegationRequest(
        delegation_id=data["delegation_id"],
        parent_request_id=data["parent_request_id"],
        session_id=data["session_id"],
        conversation_id=data.get("conversation_id"),
        worker_role=_enum(ProviderRole, data["worker_role"], "worker_role"),
        worker_id=data["worker_id"],
        task_summary=data["task_summary"],
        required_capabilities=frozenset(data.get("required_capabilities", ())),
        workspace=data.get("workspace"),
        allowed_operations=frozenset(data.get("allowed_operations", ())),
        network_allowed=data.get("network_allowed", False),
        approval_required=data.get("approval_required", True),
    )


def delegation_event_to_dict(event: DelegationEvent) -> dict[str, Any]:
    _require_type(event, DelegationEvent)
    return {
        "schema_version": event.schema_version,
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "request_id": event.request_id,
        "session_id": event.session_id,
        "conversation_id": event.conversation_id,
        "delegation_id": event.delegation_id,
        "sequence": event.sequence,
        "timestamp": event.timestamp,
        "payload": _json_value(event.payload),
    }


def delegation_event_from_dict(data: Mapping[str, Any]) -> DelegationEvent:
    data = _payload(data, "DelegationEvent")
    _required(
        data,
        "schema_version",
        "event_id",
        "event_type",
        "request_id",
        "session_id",
        "delegation_id",
        "sequence",
        "timestamp",
    )
    payload = data.get("payload", {})
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")
    return DelegationEvent(
        schema_version=data["schema_version"],
        event_id=data["event_id"],
        event_type=_enum(DelegationEventType, data["event_type"], "event_type"),
        request_id=data["request_id"],
        session_id=data["session_id"],
        conversation_id=data.get("conversation_id"),
        delegation_id=data["delegation_id"],
        sequence=data["sequence"],
        timestamp=data["timestamp"],
        payload=dict(payload),
    )


def _payload(data: Mapping[str, Any], model_name: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ValueError(f"{model_name} payload must be a mapping")
    return data


def _required(data: Mapping[str, Any], *fields: str) -> None:
    missing = [field for field in fields if field not in data]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")


def _enum(enum_type: type[TEnum], value: Any, field_name: str) -> TEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


def _require_type(value: Any, expected_type: type[Any]) -> None:
    if not isinstance(value, expected_type):
        raise TypeError(f"expected {expected_type.__name__}")


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, frozenset, set)):
        return [_json_value(item) for item in value]
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


__all__ = [
    "delegation_event_from_dict",
    "delegation_event_to_dict",
    "delegation_request_from_dict",
    "delegation_request_to_dict",
    "fallback_policy_from_dict",
    "fallback_policy_to_dict",
    "routing_decision_from_dict",
    "routing_decision_to_dict",
    "worker_capability_from_dict",
    "worker_capability_to_dict",
]

