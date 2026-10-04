"""Deterministic routing policy contracts for RoutingPolicy v0."""

from __future__ import annotations

from .catalog import WorkerCatalog
from .context import NetworkPolicy, PrivacyMode, RoutingContext
from .models import (
    FallbackPolicy,
    ProviderRole,
    RoutingDecision,
    WorkerCapability,
)
from .registry import WorkerCapabilityRegistry


class RoutingPolicyError(ValueError):
    """Raised when no catalog worker satisfies a routing request."""


_SPECIALIST_INTENTS = frozenset(
    {
        "specialist",
        "coding",
        "repository_analysis",
        "long_reasoning",
        "autonomous_workflow",
    }
)
_OFFLINE_INTENTS = frozenset({"offline", "offline_only", "local_only"})
_LEGACY_INTENTS = frozenset({"legacy", "legacy_compatibility"})


class RoutingPolicy:
    """Select a worker deterministically from routing metadata and state."""

    def __init__(self, catalog: WorkerCatalog) -> None:
        if not isinstance(catalog, WorkerCatalog):
            raise TypeError("catalog must be a WorkerCatalog")
        self._catalog = catalog
        self._catalog_workers = {worker.provider_id: worker for worker in catalog.workers()}

    def decide(
        self,
        context: RoutingContext,
        registry: WorkerCapabilityRegistry,
        fallback_policy: FallbackPolicy | None = None,
    ) -> RoutingDecision:
        """Return an explainable selection without executing any worker."""

        if not isinstance(context, RoutingContext):
            raise TypeError("context must be a RoutingContext")
        if not isinstance(registry, WorkerCapabilityRegistry):
            raise TypeError("registry must be a WorkerCapabilityRegistry")
        if fallback_policy is None:
            fallback_policy = FallbackPolicy()

        preferred_role = self._preferred_role(context)
        selected = self._first_valid(
            registry,
            preferred_role,
            context,
            fallback_policy,
        )
        if selected is None:
            raise RoutingPolicyError(
                f"no available worker satisfies role={preferred_role.value!r} "
                f"and capabilities={sorted(context.required_capabilities)!r}"
            )

        selected_role, worker = selected
        used_fallback = selected_role != preferred_role
        reason_code = (
            f"fallback_{selected_role.value}_for_{preferred_role.value}"
            if used_fallback
            else f"preferred_{preferred_role.value}"
        )
        return RoutingDecision(
            schema_version=1,
            request_id=context.request_id,
            session_id=context.session_id,
            conversation_id=context.conversation_id,
            intent=context.intent_classification,
            required_capabilities=context.required_capabilities,
            privacy_mode=context.privacy_mode.value,
            network_policy=context.network_policy.value,
            tool_policy=context.tool_policy.value,
            preferred_role=preferred_role,
            selected_role=selected_role,
            selected_provider_id=worker.provider_id,
            reason_code=reason_code,
            fallback_policy=fallback_policy,
        )

    def _preferred_role(self, context: RoutingContext) -> ProviderRole:
        """Map an existing classification label to its policy role."""

        intent = context.intent_classification.strip().lower()
        if intent in _LEGACY_INTENTS:
            return ProviderRole.LEGACY_COMPATIBILITY
        if intent in _OFFLINE_INTENTS or self._is_offline_only(context):
            return ProviderRole.OFFLINE_FALLBACK
        if intent in _SPECIALIST_INTENTS:
            return ProviderRole.SPECIALIST
        return ProviderRole.CONVERSATIONAL

    @staticmethod
    def _is_offline_only(context: RoutingContext) -> bool:
        return (
            context.privacy_mode == PrivacyMode.LOCAL_ONLY
            or context.network_policy == NetworkPolicy.DISALLOWED
            or not context.external_processing_allowed
        )

    def _first_valid(
        self,
        registry: WorkerCapabilityRegistry,
        preferred_role: ProviderRole,
        context: RoutingContext,
        fallback_policy: FallbackPolicy,
    ) -> tuple[ProviderRole, WorkerCapability] | None:
        role_order = (preferred_role,) + tuple(
            role for role in fallback_policy.ordered_roles if role != preferred_role
        )

        for role in role_order:
            for provider_id, catalog_worker in self._catalog_workers.items():
                if catalog_worker.role != role:
                    continue
                worker = registry.get_worker(provider_id)
                if worker is not None and self._is_valid(
                    worker, context, fallback_policy
                ):
                    return role, worker
        return None

    @staticmethod
    def _is_valid(
        worker: WorkerCapability,
        context: RoutingContext,
        fallback_policy: FallbackPolicy,
    ) -> bool:
        if not worker.available:
            return False
        required_capabilities = (
            context.required_capabilities | fallback_policy.required_capabilities
        )
        if not required_capabilities.issubset(worker.capabilities):
            return False
        if worker.role == ProviderRole.OFFLINE_FALLBACK:
            if not context.offline_processing_allowed or not fallback_policy.allow_offline_processing:
                return False
        elif not context.external_processing_allowed or not fallback_policy.allow_external_processing:
            return False
        return True


__all__ = ["RoutingPolicy", "RoutingPolicyError"]
