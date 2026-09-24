"""Small local protocol shared by the Maya server and test sender."""

import json
import os
import socket
from pathlib import Path


def socket_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "maya-ui.sock"
    return Path.home() / ".cache" / "maya" / "maya-ui.sock"


def send_message(message: dict, path: Path | None = None) -> None:
    payload = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
    target = str(path or socket_path())
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(target)
        client.sendall(payload)
