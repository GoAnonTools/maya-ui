"""Small stdio MCP client for deterministic Maya local skills.

Calls are sent through the existing Maya MCP server and tool registry; this
client never launches desktop applications or accesses user files itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class MCPStdioClient:
    def __init__(self, server_script: str | Path | None = None, timeout: float = 15.0):
        self.server_script = Path(server_script) if server_script else Path(__file__).resolve().parents[1] / "tools" / "maya-mcp"
        self.timeout = timeout

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call one tool using MCP JSON-RPC over the server's stdio transport."""
        requests = (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "maya-local-skills", "version": "1.0"},
            }},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        )
        payload = "".join(json.dumps(request, separators=(",", ":")) + "\n" for request in requests)
        try:
            completed = subprocess.run(
                [sys.executable, str(self.server_script)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                cwd=self.server_script.resolve().parents[1],
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"ok": False, "error": "mcp_unavailable"}
        if completed.returncode != 0:
            return {"ok": False, "error": "mcp_unavailable"}
        try:
            responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
            response = next(item for item in responses if item.get("id") == 2)
            result = response.get("result", {})
            content = result.get("content", [])
            for item in content:
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    value = json.loads(item["text"])
                    return value if isinstance(value, dict) else {"ok": False, "error": "invalid_mcp_response"}
            return {"ok": False, "error": "invalid_mcp_response"}
        except (StopIteration, TypeError, ValueError, json.JSONDecodeError):
            return {"ok": False, "error": "invalid_mcp_response"}
