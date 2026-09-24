import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend import mcp_server


class MCPDesktopToolTests(unittest.TestCase):
    def test_open_folder_uses_only_fixed_folders_and_desktop_handler(self):
        with tempfile.TemporaryDirectory() as tempdir:
            home = Path(tempdir)
            downloads = home / "Downloads"
            downloads.mkdir()
            with (
                patch.object(mcp_server, "_config", return_value={"filesystem": True}),
                patch.object(mcp_server, "ALLOWED_ROOTS", (downloads,)),
                patch.object(Path, "home", return_value=home),
                patch.object(mcp_server.subprocess, "Popen", return_value=SimpleNamespace(pid=123)) as popen,
            ):
                result = mcp_server.open_folder("Downloads")
                self.assertEqual(result, {"ok": True, "folder": "Downloads"})
                popen.assert_called_once_with(["xdg-open", str(downloads)], stdout=mcp_server.subprocess.DEVNULL, stderr=mcp_server.subprocess.DEVNULL)

                popen.reset_mock()
                invalid = mcp_server.open_folder("../../etc")
                self.assertFalse(invalid["ok"])
                self.assertEqual(invalid["error"], "folder_not_allowed")
                popen.assert_not_called()

    def test_invalid_arbitrary_paths_remain_outside_filesystem_allowlist(self):
        with tempfile.TemporaryDirectory() as tempdir:
            allowed = Path(tempdir) / "Downloads"
            allowed.mkdir()
            with patch.object(mcp_server, "ALLOWED_ROOTS", (allowed,)):
                with self.assertRaises(ValueError):
                    mcp_server._path("/etc")
                with self.assertRaises(ValueError):
                    mcp_server._path(str(allowed.parent / "outside"))

    def test_friendly_application_aliases_resolve_to_installed_desktop_entries(self):
        with tempfile.TemporaryDirectory() as tempdir:
            apps = Path(tempdir)
            for entry in ("firefox.desktop", "org.kde.dolphin.desktop", "code.desktop", "com.visualstudio.code.desktop"):
                (apps / entry).touch()
            with patch.object(mcp_server, "_application_dirs", return_value=(apps, apps)):
                self.assertEqual(mcp_server._desktop_id("Firefox"), "firefox")
                self.assertEqual(mcp_server._desktop_id("Dolphin"), "org.kde.dolphin")
                self.assertEqual(mcp_server._desktop_id("VS Code"), "code")
                self.assertEqual(mcp_server._desktop_id("Visual Studio Code"), "code")

    def test_open_folder_tool_is_config_gated_and_has_enum_schema(self):
        category, _handler, schema, description = mcp_server.TOOLS["open_folder"]
        self.assertEqual(category, "filesystem")
        self.assertEqual(schema["properties"]["folder"]["enum"], ["Downloads", "Documents", "Pictures", "Projects"])
        self.assertIn("Only Downloads", description)
        with patch.object(mcp_server, "_config", return_value={"filesystem": False}):
            self.assertFalse(mcp_server.open_folder("Downloads")["ok"])


if __name__ == "__main__":
    unittest.main()
