"""Default Maya LLM provider setup."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import QObject

from .manager import ProviderManager
from .newelle_provider import NewelleProvider
from .credentials import CredentialResolver as MayaCredentialResolver, create_default_credential_resolver
from .openai_compatible_provider import CredentialResolver as CredentialLookup, OpenAICompatibleProvider
from .registry import ProviderRegistry

log = logging.getLogger("maya.llm.defaults")
PROVIDER_CONFIG_PATH = Path(__file__).with_name("providers.json")


def create_default_provider_manager(
    parent: QObject | None = None,
    *,
    credential_resolver: CredentialLookup | None = None,
) -> ProviderManager:
    """Register configured providers while keeping Newelle as the default."""
    if credential_resolver is None:
        credential_resolver = create_default_credential_resolver()
    provider = NewelleProvider(parent)
    registry = ProviderRegistry()
    registry.register(provider)

    for config in _load_provider_configs():
        if config.get("provider_type") != "openai_compatible":
            log.warning("Skipping unsupported LLM provider type in provider catalog")
            continue
        credential_ref = config.get("credential_ref")
        available, reason = _credential_status(credential_ref, credential_resolver)
        register_openai_compatible_provider(
            registry,
            base_url=str(config.get("base_url", "")),
            model=str(config.get("model_name", "")),
            credential_ref=credential_ref if isinstance(credential_ref, str) else None,
            credential_resolver=credential_resolver,
            provider_name=str(config.get("id", "openai_compatible")),
            display_name=str(config.get("friendly_name", config.get("id", "OpenAI-compatible"))),
            available=available,
            unavailable_reason=reason,
        )
    return ProviderManager(registry, default_provider_name=provider.name)


def _load_provider_configs() -> list[dict]:
    try:
        config = json.loads(PROVIDER_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.exception("Could not read Maya provider catalog; continuing with Newelle only")
        return []
    if not isinstance(config, list):
        log.error("Maya provider catalog must contain a list")
        return []
    return [entry for entry in config if isinstance(entry, dict)]


def _credential_status(
    credential_ref: object,
    credential_resolver: CredentialLookup | None,
) -> tuple[bool, str | None]:
    if not isinstance(credential_ref, str) or not credential_ref:
        return False, "credential reference is missing"
    if credential_resolver is None:
        return False, "credential resolver is not configured"
    try:
        available = bool(credential_resolver(credential_ref))
    except Exception:
        return False, "credential lookup failed"
    if not available:
        return False, "credential is unavailable"
    return True, None


def register_openai_compatible_provider(
    registry: ProviderRegistry,
    *,
    base_url: str,
    model: str,
    credential_ref: str | None = None,
    credential_resolver: CredentialLookup | None = None,
    provider_name: str | None = None,
    display_name: str | None = None,
    available: bool = True,
    unavailable_reason: str | None = None,
) -> OpenAICompatibleProvider:
    """Register the optional adapter without changing the active provider."""
    provider = OpenAICompatibleProvider(
        base_url=base_url,
        model=model,
        credential_ref=credential_ref,
        credential_resolver=credential_resolver,
        provider_name=provider_name,
        display_name=display_name,
    )
    registry.register(provider, available=available, reason=unavailable_reason)
    return provider
