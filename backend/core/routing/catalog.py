"""Static worker capability catalog.

The catalog describes workers without importing or constructing providers.  It
is deliberately separate from both routing policy and runtime availability;
callers may populate a registry and update availability independently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .models import ProviderRole, WorkerCapability
from .registry import WorkerCapabilityRegistry


DEFAULT_PROVIDER_IDS = MappingProxyType(
    {
        "conversational": "ministral_14b",
        "specialist": "lightning_hermes",
        "offline_fallback": "local_qwen",
        "legacy_compatibility": "newelle",
    }
)


@dataclass(frozen=True, slots=True)
class WorkerCatalog:
    """Metadata catalog that can populate a worker capability registry."""

    provider_ids: Mapping[str, str] = field(
        default_factory=lambda: DEFAULT_PROVIDER_IDS
    )

    def __post_init__(self) -> None:
        provider_ids = dict(self.provider_ids)
        missing = set(DEFAULT_PROVIDER_IDS) - provider_ids.keys()
        if missing:
            missing_names = ", ".join(sorted(missing))
            raise ValueError(f"missing provider ID mappings: {missing_names}")
        if any(not provider_id for provider_id in provider_ids.values()):
            raise ValueError("provider IDs must not be empty")
        if len(set(provider_ids.values())) != len(provider_ids):
            raise ValueError("provider IDs must be unique")
        object.__setattr__(self, "provider_ids", MappingProxyType(provider_ids))

    def workers(self) -> tuple[WorkerCapability, ...]:
        """Return immutable worker metadata in stable catalog order."""

        ids = self.provider_ids
        return (
            WorkerCapability(
                provider_id=ids["conversational"],
                role=ProviderRole.CONVERSATIONAL,
                display_name="Ministral",
                capabilities=frozenset({"conversation", "streaming"}),
                latency_class="normal",
                cost_class="external",
                privacy_class="external",
            ),
            WorkerCapability(
                provider_id=ids["specialist"],
                role=ProviderRole.SPECIALIST,
                display_name="Lightning/Hermes",
                capabilities=frozenset(
                    {"coding", "repository_access", "long_reasoning", "tool_use"}
                ),
                latency_class="long_running",
                cost_class="external",
                privacy_class="external",
            ),
            WorkerCapability(
                provider_id=ids["offline_fallback"],
                role=ProviderRole.OFFLINE_FALLBACK,
                display_name="Local Qwen",
                capabilities=frozenset({"conversation", "offline", "streaming"}),
                latency_class="local",
                cost_class="local",
                privacy_class="local",
            ),
            WorkerCapability(
                provider_id=ids["legacy_compatibility"],
                role=ProviderRole.LEGACY_COMPATIBILITY,
                display_name="Newelle",
                capabilities=frozenset({"conversation", "streaming"}),
                latency_class="normal",
                cost_class="unknown",
                privacy_class="unknown",
            ),
        )

    def populate(self, registry: WorkerCapabilityRegistry) -> None:
        """Register catalog metadata in ``registry`` without runtime actions."""

        if not isinstance(registry, WorkerCapabilityRegistry):
            raise TypeError("registry must be a WorkerCapabilityRegistry")
        for worker in self.workers():
            registry.register(worker)


__all__ = ["DEFAULT_PROVIDER_IDS", "WorkerCatalog"]

