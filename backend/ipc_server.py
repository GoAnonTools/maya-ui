"""Threaded Unix-domain socket listener for Maya state events."""

import json
import logging
import os
import socket
import stat
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .ipc_protocol import socket_path

log = logging.getLogger("maya-ui.ipc")


class IpcServer(QObject):
    """Accept newline-delimited JSON without blocking Qt's GUI thread."""

    messageReceived = Signal(object)

    def __init__(self, path: Path | None = None):
        super().__init__()
        self.path = Path(path or socket_path())
        self._listener = None
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._remove_stale_socket()
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(self.path))
            os.chmod(self.path, 0o600)
            listener.listen(8)
            listener.settimeout(0.25)
            self._listener = listener
        except OSError as exc:
            log.error("Could not listen on %s: %s", self.path, exc)
            # Never unlink a path we did not bind. In particular, an active
            # Maya instance must remain untouched when a second one starts.
            if self._listener is not None:
                self._cleanup_socket()
            return False

        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="maya-ipc", daemon=True)
        self._thread.start()
        log.info("Listening for Maya state events on %s", self.path)
        return True

    def stop(self) -> None:
        self._stop.set()
        listener = self._listener
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._listener = None
        self._cleanup_socket()

    def _remove_stale_socket(self) -> None:
        try:
            mode = os.lstat(self.path).st_mode
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(mode):
            raise OSError(f"refusing to replace non-socket path: {self.path}")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            if probe.connect_ex(str(self.path)) == 0:
                raise OSError(f"socket already in use: {self.path}")
        finally:
            probe.close()
        self.path.unlink()

    def _cleanup_socket(self) -> None:
        try:
            if stat.S_ISSOCK(os.lstat(self.path).st_mode):
                self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Could not remove socket %s: %s", self.path, exc)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self._stop.is_set():
                    log.warning("Maya IPC listener stopped unexpectedly")
                break
            with connection:
                self._read_connection(connection)

    def _read_connection(self, connection: socket.socket) -> None:
        buffer = b""
        try:
            while not self._stop.is_set():
                chunk = connection.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > 65536:
                    log.warning("Ignoring oversized Maya IPC payload")
                    return
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._parse_line(line)
        except OSError as exc:
            log.debug("Maya IPC client disconnected: %s", exc)

    def _parse_line(self, line: bytes) -> None:
        if not line.strip():
            return
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            log.warning("Ignoring malformed Maya IPC JSON: %s", exc)
            return
        if not isinstance(message, dict):
            log.warning("Ignoring non-object Maya IPC message")
            return
        self.messageReceived.emit(message)
