import unittest

from backend.delegation_observability import DelegationObservabilityClient


class DelegationObservabilityClientTest(unittest.TestCase):
    def test_lifecycle_payloads_are_exposed_for_dashboard(self):
        client = DelegationObservabilityClient(base_url="http://example.invalid")
        client._apply_status({"status": "WAITING_APPROVAL", "pending_approval": {"message": "Review"}})
        client._apply_event({"status": "RUNNING", "message": "Started"})
        client._apply_event({"status": "COMPLETED", "result": {"answer": "safe"}})

        self.assertEqual(client.delegationStatus, "COMPLETED")
        self.assertEqual(client.delegationApproval["message"], "Review")
        self.assertEqual(client.delegationResult, '{\n  "answer": "safe"\n}')
        self.assertEqual(len(client.delegationTimeline), 2)

    def test_empty_watch_is_user_facing_validation(self):
        client = DelegationObservabilityClient()
        client.watch("")
        self.assertEqual(client.delegationError, "Enter a delegation ID to observe.")


if __name__ == "__main__":
    unittest.main()
