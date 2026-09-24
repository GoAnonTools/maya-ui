import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.mcp_client import MCPStdioClient


ROOT = Path(__file__).resolve().parents[1]


def run_server(payload: bytes, command=None) -> tuple[list[dict], bytes, bytes]:
    env = os.environ.copy()
    process = subprocess.run(
        command or [sys.executable, "-m", "backend.mcp_server"],
        cwd=ROOT,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=True,
        timeout=5,
    )
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    return [json.loads(line) for line in lines], process.stderr, process.stdout


def initialize_request(request_id=1):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }


class MCPServerTransportTests(unittest.TestCase):
    def test_newline_initialize_handshake(self):
        responses, _, _ = run_server((json.dumps(initialize_request()) + "\n").encode())
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "maya-local-tools")

    def test_existing_maya_launcher_uses_newline_transport(self):
        responses, _, raw_stdout = run_server(
            (json.dumps(initialize_request(7)) + "\n").encode(),
            command=[str(ROOT / "tools" / "maya-mcp")],
        )
        self.assertEqual(responses[0]["id"], 7)
        self.assertNotIn(b"Content-Length:", raw_stdout)

    def test_newline_tools_list(self):
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        responses, _, _ = run_server((json.dumps(request) + "\n").encode())
        names = {tool["name"] for tool in responses[0]["result"]["tools"]}
        self.assertIn("get_current_time", names)
        self.assertIn("open_file", names)

    def test_newline_tools_call(self):
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_current_time", "arguments": {}},
        }
        responses, _, _ = run_server((json.dumps(request) + "\n").encode())
        self.assertEqual(responses[0]["id"], 3)
        self.assertFalse(responses[0]["result"]["isError"])

    def test_legacy_content_length_input(self):
        request = json.dumps(initialize_request(4), separators=(",", ":")).encode()
        payload = b"Content-Length: " + str(len(request)).encode() + b"\r\n\r\n" + request + b"\n"
        responses, _, _ = run_server(payload)
        self.assertEqual(responses[0]["id"], 4)

    def test_stdout_contains_only_newline_jsonrpc_messages(self):
        requests = [initialize_request(5), {"jsonrpc": "2.0", "id": 6, "method": "tools/list"}]
        payload = b"".join((json.dumps(request) + "\n").encode() for request in requests)
        responses, _, raw_stdout = run_server(payload)
        self.assertEqual([response["id"] for response in responses], [5, 6])
        self.assertNotIn(b"Content-Length:", raw_stdout)

    @patch("backend.mcp_client.subprocess.run")
    def test_stdio_client_calls_existing_mcp_tool_transport(self, run):
        payload_result = json.dumps({"ok": True, "folder": "Downloads"})
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n" + json.dumps({
                "jsonrpc": "2.0", "id": 2,
                "result": {"content": [{"type": "text", "text": payload_result}], "isError": False},
            }) + "\n",
            stderr="",
        )

        result = MCPStdioClient(ROOT / "tools" / "maya-mcp").call_tool("open_folder", {"folder": "Downloads"})

        self.assertEqual(result, {"ok": True, "folder": "Downloads"})
        requests = [json.loads(line) for line in run.call_args.kwargs["input"].splitlines()]
        self.assertEqual(requests[0]["method"], "initialize")
        self.assertEqual(requests[1]["method"], "notifications/initialized")
        self.assertEqual(requests[2]["method"], "tools/call")
        self.assertEqual(requests[2]["params"], {"name": "open_folder", "arguments": {"folder": "Downloads"}})


if __name__ == "__main__":
    unittest.main()
