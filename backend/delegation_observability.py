"""Lazy, read-only client for Maya Core delegation observability."""
import json
import logging
import os
import threading
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Property, Signal, Slot

log = logging.getLogger("maya-ui.delegation")


class DelegationObservabilityClient(QObject):
    statusChanged = Signal()
    timelineChanged = Signal()
    approvalChanged = Signal()
    resultChanged = Signal()
    errorChanged = Signal()
    watchingChanged = Signal()
    _statusPayload = Signal(object)
    _timelinePayload = Signal(object)
    _eventPayload = Signal(object)
    _createdPayload = Signal(object)
    _restartPayload = Signal(str)
    _errorPayload = Signal(str)

    def __init__(self, base_url=None, timeout=10.0, parent=None):
        super().__init__(parent)
        self._base_url = (base_url or os.environ.get("MAYA_CORE_DELEGATION_URL") or "http://127.0.0.1:8080").rstrip("/")
        self._timeout = timeout
        self._delegation_id = ""
        self._status = ""
        self._timeline = []
        self._approval = {}
        self._result = ""
        self._error = ""
        self._stop_event = threading.Event()
        self._thread = None
        self._statusPayload.connect(self._apply_status)
        self._timelinePayload.connect(self._apply_timeline)
        self._eventPayload.connect(self._apply_event)
        self._createdPayload.connect(self._apply_created)
        self._restartPayload.connect(self.watch)
        self._errorPayload.connect(self._apply_error)

    def _get_delegation_id(self): return self._delegation_id
    def _get_status(self): return self._status
    def _get_timeline(self): return self._timeline
    def _get_approval(self): return self._approval
    def _get_result(self): return self._result
    def _get_error(self): return self._error
    def _get_watching(self): return self._thread is not None and self._thread.is_alive()

    delegationId = Property(str, _get_delegation_id, notify=watchingChanged)
    delegationStatus = Property(str, _get_status, notify=statusChanged)
    delegationTimeline = Property(list, _get_timeline, notify=timelineChanged)
    delegationApproval = Property('QVariantMap', _get_approval, notify=approvalChanged)
    delegationResult = Property(str, _get_result, notify=resultChanged)
    delegationError = Property(str, _get_error, notify=errorChanged)
    delegationWatching = Property(bool, _get_watching, notify=watchingChanged)

    @Slot(str)
    def watch(self, delegation_id):
        delegation_id = (delegation_id or "").strip()
        if not delegation_id:
            self._apply_error("Enter a delegation ID to observe.")
            return
        self.stop()
        self._delegation_id = delegation_id
        self._status = "connecting"
        self._timeline = []
        self._approval = {}
        self._result = ""
        self._error = ""
        self.statusChanged.emit(); self.timelineChanged.emit(); self.approvalChanged.emit()
        self.resultChanged.emit(); self.errorChanged.emit(); self.watchingChanged.emit()
        self._stop_event = threading.Event()
        stop_event = self._stop_event
        delegation_id_snapshot = self._delegation_id
        self._thread = threading.Thread(
            target=self._run, args=(stop_event, delegation_id_snapshot),
            name="maya-delegation-sse", daemon=True,
        )
        self._thread.start()
        self.watchingChanged.emit()

    @Slot()
    def stop(self):
        self._stop_event.set()
        self._thread = None
        self.watchingChanged.emit()

    @Slot()
    def start_repository_analysis(self):
        self._run_action(
            "/delegations/repository-analysis",
            {},
            self._createdPayload,
        )

    @Slot()
    def approve_delegation(self):
        approval_id = str(self._approval.get("approval_id", "")).strip()
        if not self._delegation_id or not approval_id:
            self._apply_error("There is no pending approval to grant.")
            return
        self._run_action(
            f"/delegations/{urllib.parse.quote(self._delegation_id, safe='')}/approve",
            {"approval_id": approval_id},
            self._restartPayload,
            restart_id=self._delegation_id,
        )

    def _run_action(self, path, payload, signal, restart_id=None):
        def action():
            try:
                request = urllib.request.Request(
                    self._base_url + path,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    result = json.loads(response.read().decode("utf-8"))
                if signal is self._restartPayload:
                    signal.emit(restart_id or "")
                else:
                    signal.emit(result)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                log.info("Delegation action failed: %s", exc)
                self._errorPayload.emit(_friendly_action_error(exc))

        threading.Thread(target=action, name="maya-delegation-action", daemon=True).start()

    def _url(self, delegation_id, suffix):
        return f"{self._base_url}/delegations/{urllib.parse.quote(delegation_id, safe='')}/{suffix}"

    def _get_json(self, delegation_id, suffix):
        request = urllib.request.Request(self._url(delegation_id, suffix), headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _run(self, stop_event, delegation_id):
        try:
            self._statusPayload.emit(self._get_json(delegation_id, "status"))
            self._timelinePayload.emit(self._get_json(delegation_id, "timeline"))
            request = urllib.request.Request(self._url(delegation_id, "events"), headers={"Accept": "text/event-stream"})
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = []
                for raw_line in response:
                    if stop_event.is_set(): return
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if not line:
                        if data:
                            try: self._eventPayload.emit(json.loads("\n".join(data)))
                            except json.JSONDecodeError: log.warning("Ignoring malformed delegation SSE payload")
                        data = []
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            if not stop_event.is_set():
                self._errorPayload.emit("Delegation updates are unavailable right now.")
                log.info("Delegation observability request failed: %s", exc)

    @Slot(object)
    def _apply_status(self, payload):
        self._status = str(payload.get("status", "unknown"))
        pending = payload.get("pending_approval")
        self._approval = pending if isinstance(pending, dict) else {}
        self.statusChanged.emit(); self.approvalChanged.emit()

    @Slot(object)
    def _apply_created(self, payload):
        delegation_id = str(payload.get("delegation_id", "")).strip() if isinstance(payload, dict) else ""
        if delegation_id:
            self.watch(delegation_id)
        else:
            self._apply_error("Maya did not return a delegation ID.")

    @Slot(object)
    def _apply_timeline(self, payload):
        self._timeline = payload.get("timeline", []) if isinstance(payload, dict) else []
        self.timelineChanged.emit()

    @Slot(object)
    def _apply_event(self, payload):
        if not isinstance(payload, dict): return
        status = payload.get("status")
        if status: self._status = status; self.statusChanged.emit()
        if payload.get("event_type") in {"approval_required", "delegation.approval_required"} or str(status).casefold() == "waiting_approval":
            self._approval = payload.get("metadata") or {"message": payload.get("message", "Approval required")}
            self.approvalChanged.emit()
        if payload.get("result") is not None:
            value = payload["result"]
            self._result = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
            self.resultChanged.emit()
        self._timeline = [*self._timeline, payload]
        self.timelineChanged.emit()

    @Slot(str)
    def _apply_error(self, message):
        self._error = message
        self.errorChanged.emit()


def _friendly_action_error(exc):
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 503:
        return "Hermes is not enabled. Enable Hermes locally before analyzing a repository."
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 409:
        return "The delegation approval could not be applied. Refresh and try again."
    return "Maya could not start the repository analysis right now."
