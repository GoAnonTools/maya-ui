import unittest
from datetime import datetime, timezone

from backend.local_skills import local_skill_response


class FakeMCPClient:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"ok": self.ok}


class LocalSkillsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 23, 5, 52, tzinfo=timezone.utc)

    def test_matches_clear_time_and_date_requests(self):
        cases = (
            ("what time is it?", "It's 5:52 AM."),
            ("what date is it?", "Today is Wednesday, September 23rd."),
            ("what day is today?", "Today is Wednesday, September 23rd."),
        )
        for request, expected in cases:
            with self.subTest(request=request):
                self.assertEqual(local_skill_response(request, now=self.now), expected)

    def test_matches_maya_and_greeting_prefixed_requests(self):
        cases = (
            ("maya, what time is it?", "It's 5:52 AM."),
            ("Good morning, what time is it?", "It's 5:52 AM."),
            ("Hello Maya, what date is it?", "Today is Wednesday, September 23rd."),
        )
        for request, expected in cases:
            with self.subTest(request=request):
                self.assertEqual(local_skill_response(request, now=self.now), expected)

    def test_formats_midnight_noon_and_exact_hours_naturally(self):
        cases = (
            (datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc), "It's 12 AM."),
            (datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc), "It's 12 PM."),
            (datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc), "It's 5 PM."),
        )
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(local_skill_response("what time is it", now=now), expected)

    def test_non_matching_requests_fall_through(self):
        for request in (
            "",
            "How do I tell the time?",
            "Can you explain what time it is?",
            "What time is it in Tokyo?",
            "What is the date format?",
            "The date is important.",
        ):
            with self.subTest(request=request):
                self.assertIsNone(local_skill_response(request, now=self.now))

    def test_folder_requests_route_through_mcp_and_confirm_success(self):
        cases = (
            ("Maya, open my Downloads folder", "Downloads"),
            ("Open my download folder", "Downloads"),
            ("Open my downloads folder", "Downloads"),
            ("Open the download folder", "Downloads"),
            ("Open the downloads folder", "Downloads"),
            ("Open download folder", "Downloads"),
            ("Open downloads folder", "Downloads"),
            ("open my Downloads folder", "Downloads"),
            ("open Downloads folder", "Downloads"),
            ("open my Documents folder", "Documents"),
            ("open my Pictures folder", "Pictures"),
            ("Show me my Downloads folder", "Downloads"),
            ("Open Documents", "Documents"),
            ("Please open my Downloads folder please", "Downloads"),
        )
        for request, folder in cases:
            with self.subTest(request=request):
                client = FakeMCPClient()
                reply = local_skill_response(request, mcp_client=client)
                self.assertEqual(reply, f"Done, I opened your {folder} folder.")
                self.assertEqual(client.calls, [("open_folder", {"folder": folder})])

    def test_application_requests_route_by_friendly_name(self):
        cases = (
            ("Launch Firefox", "Firefox", "Opening Firefox."),
            ("Open Dolphin", "Dolphin", "Opening Dolphin."),
            ("Start VS Code", "VS Code", "Opening VS Code."),
            ("Open Visual Studio Code", "VS Code", "Opening VS Code."),
        )
        for request, app, reply in cases:
            with self.subTest(request=request):
                client = FakeMCPClient()
                self.assertEqual(local_skill_response(request, mcp_client=client), reply)
                self.assertEqual(client.calls, [("open_application", {"name": app})])

    def test_failed_action_is_handled_locally(self):
        client = FakeMCPClient(ok=False)
        self.assertEqual(
            local_skill_response("Open my Downloads folder", mcp_client=client),
            "I couldn't open your Downloads folder.",
        )


if __name__ == "__main__":
    unittest.main()
