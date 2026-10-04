"""In-memory registry for worker capability declarations.

This module only stores and exposes worker metadata.  It does not decide which
worker should handle a request and has no dependency on provider execution or
UI code.
"""

from __future__ import annotations

from dataclasses import replace
from threading import RLock

from .models import WorkerCapability


class WorkerCapabilityRegistry:
    """Store worker capabilities independently from provider execution.

    The registry keeps immutable ``WorkerCapability`` snapshots.  Updating
    availability therefore replaces a snapshot and does not mutate a value
    held by a caller.
    """

    def __init__(self) -> None:
        self._workers: dict[str, WorkerCapability] = {}
        self._lock = RLock()

    def register(self, worker: WorkerCapability) -> None:
        """Register a worker under its provider ID.

        Provider IDs are unique registry keys.  Re-registering an existing ID
        is rejected so an accidental configuration collision cannot silently
        replace a worker declaration.
        """

        if not isinstance(worker, WorkerCapability):
            raise TypeError("worker must be a WorkerCapability")

        with self._lock:
            if worker.provider_id in self._workers:
                raise ValueError(f"worker already registered: {worker.provider_id}")
            self._workers[worker.provider_id] = worker

    def get(self, provider_id: str) -> WorkerCapability | None:
        """Return the registered worker for ``provider_id``, if present."""

        with self._lock:
            return self._workers.get(provider_id)

    get_worker = get

    def list_available(self) -> tuple[WorkerCapability, ...]:
        """Return all currently available workers in registration order."""

        with self._lock:
            return tuple(worker for worker in self._workers.values() if worker.available)

    list_available_workers = list_available

    def update_availability(
        self,
        provider_id: str,
        available: bool,
        *,
        unavailable_reason: str | None = None,
    ) -> WorkerCapability:
        """Update availability and return the new worker snapshot.

        A recovered worker has no unavailable reason.  A missing provider ID
        raises ``KeyError`` rather than creating an incomplete registration.
        """

        with self._lock:
            worker = self._workers.get(provider_id)
            if worker is None:
                raise KeyError(provider_id)

            updated = replace(
                worker,
                available=available,
                unavailable_reason=unavailable_reason if not available else None,
            )
            self._workers[provider_id] = updated
            return updated
