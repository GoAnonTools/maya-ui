"""Explicit, temporary provider smoke test for Maya development.

Run with ``python -m backend.llm.dev_provider_test --list`` or pass
``--provider ministral_14b`` to send the harmless test prompt. This module is
not imported by Maya's runtime path and never displays credential values.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from .base import LLMCompleted, LLMMessage, LLMRequest, LLMTextDelta, LLMToolCallDelta
from .defaults import create_default_provider_manager
from .manager import ProviderManager

DEFAULT_TEST_PROMPT = "Reply with exactly: Maya provider test OK."


def list_provider_status(manager: ProviderManager) -> tuple[tuple[str, bool, str | None], ...]:
    """Return provider IDs, availability, and safe status reasons."""
    return tuple((status.name, status.available, status.reason) for status in manager.registry.statuses())


def run_provider_test(
    manager: ProviderManager,
    provider_name: str,
    prompt: str = DEFAULT_TEST_PROMPT,
    *,
    event_handler: Callable[[object], None] | None = None,
):
    """Select one provider, stream a test request, then restore the selection.

    The handler receives normalized LLM events and can be MayaController's
    existing ``_on_llm_event`` slot in an integration harness.
    """
    previous_provider = manager.current_provider_name
    events = []
    try:
        manager.select(provider_name)
        request = LLMRequest(messages=(LLMMessage(role="user", content=prompt),))
        for event in manager.submit(request):
            events.append(event)
            if event_handler is not None:
                event_handler(event)
        return tuple(events)
    finally:
        if manager.current_provider_name != previous_provider:
            manager.select(previous_provider)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maya development provider smoke test")
    parser.add_argument("--list", action="store_true", help="list providers and availability")
    parser.add_argument("--provider", help="provider ID to explicitly select for one test request")
    parser.add_argument("--prompt", default=DEFAULT_TEST_PROMPT, help="test prompt (never includes credentials)")
    args = parser.parse_args(argv)
    if not args.list and not args.provider:
        parser.error("choose --list or explicitly pass --provider")

    manager = create_default_provider_manager()
    try:
        if args.list:
            for name, available, reason in list_provider_status(manager):
                state = "available" if available else "unavailable"
                suffix = f" ({reason})" if reason else ""
                print(f"{name}: {state}{suffix}")
            if not args.provider:
                return 0

        try:
            events = run_provider_test(manager, args.provider, args.prompt)
        except Exception:
            # Provider errors are deliberately summarized; don't emit arbitrary
            # backend exception text or credential-bearing diagnostics.
            print("Provider test failed. Check Maya's local provider diagnostics.", file=sys.stderr)
            return 1

        for event in events:
            if isinstance(event, LLMTextDelta):
                print(event.text, end="", flush=True)
            elif isinstance(event, LLMToolCallDelta):
                print("[tool call received]", flush=True)
            elif isinstance(event, LLMCompleted):
                print("\n[provider stream completed]", flush=True)
        return 0
    finally:
        manager.close()


if __name__ == "__main__":
    raise SystemExit(_main())
