"""Controlled local MCP tool server for Maya.

The server speaks MCP JSON-RPC over stdio and deliberately avoids shell
interpretation.  It is intended to be launched by an MCP host, not by the
Maya UI response thread.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import secrets
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


CONFIG_PATH = Path.home() / ".config" / "maya" / "tools.json"
ALLOWED_ROOTS = tuple(Path.home() / name for name in ("Documents", "Downloads", "Pictures", "Projects"))
SUPPORTED_FOLDERS = {name.casefold(): name for name in ("Downloads", "Documents", "Pictures", "Projects")}
APPLICATION_ALIASES = {
    "firefox": ("firefox", "org.mozilla.firefox"),
    "dolphin": ("org.kde.dolphin", "dolphin"),
    "vs code": ("code", "com.visualstudio.code"),
    "visual studio code": ("code", "com.visualstudio.code"),
}
LOG = logging.getLogger("maya.mcp")
MAX_READ_BYTES = 1_000_000
CONFIRMATIONS: dict[str, str] = {}


def _configure_logging() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _config() -> dict[str, bool]:
    defaults = {"system": False, "applications": False, "filesystem": False, "terminal": False}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in defaults:
                defaults[key] = data.get(key) is True
    except (OSError, ValueError):
        pass
    return defaults


def _result(ok: bool, **data: Any) -> dict[str, Any]:
    return {"ok": ok, **data}


def _guard(category: str) -> dict[str, Any] | None:
    if not _config().get(category, False):
        return _result(False, error="tool_category_disabled", category=category)
    return None


def _path(value: str) -> Path:
    candidate = Path(value).expanduser()
    resolved = candidate.resolve(strict=False)
    if not any(resolved == root or root in resolved.parents for root in ALLOWED_ROOTS):
        raise ValueError("path must be inside an allowed Maya folder")
    return resolved


def _log(action: str, **details: Any) -> None:
    LOG.info("tool action=%s details=%s", action, json.dumps(details, ensure_ascii=False, default=str))


def get_current_time() -> dict[str, Any]:
    guard = _guard("system")
    if guard: return guard
    value = datetime.now().astimezone()
    _log("get_current_time")
    return _result(True, iso8601=value.isoformat(), timezone=value.tzname())


def get_system_info() -> dict[str, Any]:
    guard = _guard("system")
    if guard: return guard
    _log("get_system_info")
    return _result(True, system=platform.system(), release=platform.release(), machine=platform.machine(), hostname=platform.node(), python=platform.python_version())


def _processes() -> list[dict[str, Any]]:
    result = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit(): continue
        try:
            pid = int(entry.name)
            name = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            if name:
                result.append({"pid": pid, "name": name, "command": cmdline[:300]})
        except (OSError, ValueError):
            continue
    return result


def list_open_applications() -> dict[str, Any]:
    guard = _guard("applications")
    if guard: return guard
    apps = _processes()
    _log("list_open_applications", count=len(apps))
    return _result(True, applications=apps)


def _desktop_id(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("application must name an installed desktop entry")
    value = name.strip()
    aliases = APPLICATION_ALIASES.get(value.casefold())
    candidates = list(aliases) if aliases else [Path(value).name.removesuffix(".desktop")]
    for directory in _application_dirs():
        for candidate in candidates:
            if (directory / f"{candidate}.desktop").is_file(): return candidate
    raise ValueError("application must name an installed desktop entry")


def _application_dirs() -> tuple[Path, Path]:
    return Path("/usr/share/applications"), Path.home() / ".local/share/applications"


def open_application(name: str) -> dict[str, Any]:
    guard = _guard("applications")
    if guard: return guard
    desktop = _desktop_id(name)
    process = subprocess.Popen(["gtk-launch", desktop], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    _log("open_application", application=desktop, pid=process.pid)
    return _result(True, application=desktop, started=True, pid=process.pid)


def _matching_pids(name: str) -> list[int]:
    needle = name.casefold()
    return [item["pid"] for item in _processes() if needle in item["name"].casefold() or needle in item["command"].casefold()]


def focus_application(name: str) -> dict[str, Any]:
    guard = _guard("applications")
    if guard: return guard
    pids = _matching_pids(name)
    _log("focus_application", application=name, pids=pids)
    return _result(False, error="window_focus_unavailable", detail="Wayland window focus requires a compositor integration", pids=pids)


def close_application(name: str) -> dict[str, Any]:
    guard = _guard("applications")
    if guard: return guard
    pids = _matching_pids(name)
    for pid in pids:
        if pid != os.getpid():
            try: os.kill(pid, signal.SIGTERM)
            except ProcessLookupError: pass
            except PermissionError: pass
    _log("close_application", application=name, pids=pids)
    return _result(True, application=name, signaled_pids=pids)


def list_files(path: str = "~/Projects") -> dict[str, Any]:
    guard = _guard("filesystem")
    if guard: return guard
    root = _path(path)
    if not root.is_dir(): return _result(False, error="not_a_directory", path=str(root))
    entries = [{"name": item.name, "path": str(item), "directory": item.is_dir()} for item in sorted(root.iterdir(), key=lambda p: p.name.casefold())]
    _log("list_files", path=str(root), count=len(entries))
    return _result(True, path=str(root), entries=entries)


def read_file(path: str) -> dict[str, Any]:
    guard = _guard("filesystem")
    if guard: return guard
    target = _path(path)
    if not target.is_file(): return _result(False, error="not_a_file", path=str(target))
    size = target.stat().st_size
    if size > MAX_READ_BYTES: return _result(False, error="file_too_large", max_bytes=MAX_READ_BYTES, bytes=size)
    text = target.read_text(encoding="utf-8")
    _log("read_file", path=str(target), bytes=size)
    return _result(True, path=str(target), bytes=size, content=text)


def open_file(path: str) -> dict[str, Any]:
    guard = _guard("filesystem")
    if guard: return guard
    target = _path(path)
    if not target.is_file(): return _result(False, error="not_a_file", path=str(target))
    process = subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    _log("open_file", path=str(target), pid=process.pid)
    return _result(True, path=str(target), started=True, pid=process.pid)


def open_folder(folder: str) -> dict[str, Any]:
    """Open one fixed, allowlisted user folder using the desktop handler."""
    guard = _guard("filesystem")
    if guard: return guard
    if not isinstance(folder, str) or folder.casefold() not in SUPPORTED_FOLDERS:
        return _result(False, error="folder_not_allowed")
    canonical = SUPPORTED_FOLDERS[folder.casefold()]
    try:
        target = _path(str(Path.home() / canonical))
    except (OSError, ValueError):
        return _result(False, error="folder_not_allowed")
    if not target.is_dir():
        return _result(False, error="folder_unavailable", folder=canonical)
    try:
        process = subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return _result(False, error="open_failed", folder=canonical)
    _log("open_folder", folder=canonical)
    return _result(True, folder=canonical)


def execute_command(command: str, confirmation_token: str | None = None) -> dict[str, Any]:
    guard = _guard("terminal")
    if guard: return guard
    if not isinstance(command, str) or not command.strip(): return _result(False, error="empty_command")
    token = confirmation_token or ""
    if CONFIRMATIONS.get(token) != command:
        new_token = secrets.token_urlsafe(18)
        CONFIRMATIONS[new_token] = command
        _log("terminal_confirmation_required", command=command)
        return _result(False, error="confirmation_required", confirmation_token=new_token, command=command)
    CONFIRMATIONS.pop(token, None)
    process = subprocess.run(["bash", "-lc", command], capture_output=True, text=True, timeout=30, check=False)
    _log("execute_command", command=command, returncode=process.returncode)
    return _result(True, returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)


_EMPTY_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}

TOOLS = {
    "get_current_time": (
        "system",
        get_current_time,
        _EMPTY_ARGS,
        "Get the current local time and timezone. Use to answer questions about the time now.",
    ),
    "get_system_info": (
        "system",
        get_system_info,
        _EMPTY_ARGS,
        "Get basic information about this computer's operating system and hardware platform.",
    ),
    "list_open_applications": (
        "applications",
        list_open_applications,
        _EMPTY_ARGS,
        "List running processes. Results include process names and command lines; this is not a list of window titles.",
    ),
    "open_application": (
        "applications",
        open_application,
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Installed desktop entry name or ID, such as 'firefox' or 'firefox.desktop'.",
                }
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "Launch one installed desktop application by its desktop entry name or ID.",
    ),
    "focus_application": (
        "applications",
        focus_application,
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Application name to match against running process names and command lines.",
                }
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "Request focus for an application. Window focusing is currently unavailable on Wayland, so this tool may return window_focus_unavailable.",
    ),
    "close_application": (
        "applications",
        close_application,
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Distinctive text matched against running process names and command lines; it may match multiple processes.",
                }
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "Send a graceful termination signal to processes matching the supplied name. Use only when the user explicitly asks to close an application; a broad match can affect multiple processes.",
    ),
    "list_files": (
        "filesystem",
        list_files,
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to list, inside ~/Documents, ~/Downloads, ~/Pictures, or ~/Projects. Defaults to ~/Projects.",
                    "default": "~/Projects",
                }
            },
            "additionalProperties": False,
        },
        "List entries in one directory inside ~/Documents, ~/Downloads, ~/Pictures, or ~/Projects. Use a path returned by this tool with read_file or open_file.",
    ),
    "read_file": (
        "filesystem",
        read_file,
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Text file path inside ~/Documents, ~/Downloads, ~/Pictures, or ~/Projects. Files larger than 1,000,000 bytes are rejected.",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "Read a UTF-8 text file inside ~/Documents, ~/Downloads, ~/Pictures, or ~/Projects. Use only when the user asks about the file's contents.",
    ),
    "open_file": (
        "filesystem",
        open_file,
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Existing file path inside ~/Documents, ~/Downloads, ~/Pictures, or ~/Projects.",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "Open an existing file inside ~/Documents, ~/Downloads, ~/Pictures, or ~/Projects with the desktop's default application.",
    ),
    "open_folder": (
        "filesystem",
        open_folder,
        {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "enum": ["Downloads", "Documents", "Pictures", "Projects"],
                    "description": "One supported user folder: Downloads, Documents, Pictures, or Projects.",
                }
            },
            "required": ["folder"],
            "additionalProperties": False,
        },
        "Open one supported user folder in the desktop file manager. Only Downloads, Documents, Pictures, and Projects are allowed.",
    ),
    "execute_command": (
        "terminal",
        execute_command,
        {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run. Execution requires the user's separate confirmation.",
                },
                "confirmation_token": {
                    "type": "string",
                    "description": "Confirmation token returned after the user approves this exact command.",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        "Run a shell command only after the user approves it and provides the confirmation token. This tool is disabled unless terminal tools are enabled in Maya configuration.",
    ),
}


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOLS: return _result(False, error="unknown_tool", tool=name)
    try:
        value = TOOLS[name][1](**arguments)
        return value if isinstance(value, dict) else _result(True, value=value)
    except Exception as exc:
        LOG.exception("tool failure name=%s", name)
        return _result(False, error=type(exc).__name__, detail=str(exc))


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized": return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "maya-local-tools", "version": "1.0.0"}}}
    if method == "tools/list":
        enabled = _config()
        tools = [
            {"name": name, "description": description, "inputSchema": schema}
            for name, (category, _, schema, description) in TOOLS.items()
            if enabled.get(category, False)
        ]
        LOG.info("tool discovery enabled_categories=%s tools=%s", [key for key, value in enabled.items() if value], [tool["name"] for tool in tools])
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
    if method == "tools/call":
        params = request.get("params") or {}
        name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        LOG.info("tool call request id=%s name=%s arguments=%s", request_id, name, json.dumps(arguments, ensure_ascii=False, default=str))
        value = _call_tool(name, arguments)
        LOG.info("tool call response id=%s name=%s ok=%s", request_id, name, value.get("ok", False))
        return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "isError": not value.get("ok", False)}}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}}


def _read_request() -> dict[str, Any] | None:
    """Read one MCP JSON-RPC request from newline or legacy framed stdin."""
    while True:
        header = sys.stdin.buffer.readline()
        if not header:
            return None

        stripped = header.strip()
        if not stripped:
            continue

        # Current MCP stdio transport: one JSON-RPC object per line.
        if stripped.startswith(b"{"):
            return json.loads(stripped.decode("utf-8"))

        # Backward compatibility for the previous Content-Length transport.
        if header.lower().startswith(b"content-length:"):
            try:
                length = int(header.split(b":", 1)[1].strip())
            except (IndexError, ValueError) as exc:
                raise ValueError("invalid Content-Length header") from exc

            while True:
                line = sys.stdin.buffer.readline()
                if not line:
                    return None
                if not line.strip():
                    break

            payload = sys.stdin.buffer.read(length)
            if len(payload) != length:
                raise ValueError("incomplete Content-Length payload")
            return json.loads(payload.decode("utf-8"))

        LOG.warning("Ignoring unsupported MCP stdin framing: %r", header[:120])


def _write_response(response: dict[str, Any]) -> None:
    """Write one standard newline-delimited MCP JSON-RPC response."""
    payload = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()


def main() -> None:
    _configure_logging()
    LOG.info("Maya MCP server started config=%s", CONFIG_PATH)
    while True:
        try:
            request = _read_request()
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            LOG.exception("Invalid MCP stdin message")
            continue
        if request is None:
            break
        response = _handle(request)
        if response is not None:
            _write_response(response)


if __name__ == "__main__":
    main()
