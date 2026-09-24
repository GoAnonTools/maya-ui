import logging
import subprocess
import unittest
from unittest.mock import patch

from backend.llm.credentials import CredentialResolver, KDEWalletBackend
from backend.llm.defaults import create_default_provider_manager
from backend.llm.base import LLMProviderError


class FakeWalletBackend:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.references = []

    def resolve(self, reference):
        self.references.append(reference)
        if self.error:
            raise self.error
        return self.value


class CredentialResolverTests(unittest.TestCase):
    def test_resolves_provider_reference_with_fake_wallet(self):
        wallet = FakeWalletBackend("test-secret")
        resolver = CredentialResolver({"kwallet": wallet})

        self.assertEqual(resolver("maya.provider.ministral_14b.api_key"), "test-secret")
        self.assertEqual(wallet.references, ["maya.provider.ministral_14b.api_key"])

    def test_provider_availability_uses_resolved_credential_and_newelle_stays_default(self):
        resolver = CredentialResolver({"kwallet": FakeWalletBackend("test-secret")})
        manager = create_default_provider_manager(credential_resolver=resolver)

        self.assertTrue(manager.availability("ministral_14b").available)
        self.assertEqual(manager.current_provider_name, "newelle")

    def test_missing_wallet_credential_marks_provider_unavailable(self):
        resolver = CredentialResolver({"kwallet": FakeWalletBackend(None)})
        manager = create_default_provider_manager(credential_resolver=resolver)

        status = manager.availability("ministral_14b")
        self.assertFalse(status.available)
        self.assertEqual(status.reason, "credential is unavailable")
        with self.assertRaises(LLMProviderError):
            manager.select("ministral_14b")
        self.assertEqual(manager.current_provider_name, "newelle")

    def test_invalid_reference_is_rejected_before_backend_call(self):
        wallet = FakeWalletBackend("secret")
        resolver = CredentialResolver({"kwallet": wallet})
        kwallet_backend = KDEWalletBackend()

        with patch("backend.llm.credentials.subprocess.run") as run:
            self.assertIsNone(kwallet_backend.resolve("kwallet://kdewallet/Maya/../api_key"))
        run.assert_not_called()
        self.assertIsNone(resolver("unknown://wallet/folder/entry"))
        self.assertEqual(wallet.references, [])

    def test_secrets_are_not_in_logs_when_backend_raises(self):
        secret = "do-not-log-this-secret"
        resolver = CredentialResolver({"kwallet": FakeWalletBackend(error=RuntimeError(secret))})
        with self.assertLogs("maya.credentials", level=logging.WARNING) as captured:
            self.assertIsNone(resolver("maya.provider.ministral_14b.api_key"))
        self.assertNotIn(secret, "\n".join(captured.output))

    @patch("backend.llm.credentials.subprocess.run")
    def test_kwallet_backend_reads_value_without_logging_it(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="wallet-secret\n", stderr="secret diagnostic"
        )
        backend = KDEWalletBackend()

        self.assertEqual(backend.resolve("maya.provider.ministral_14b.api_key"), "wallet-secret")
        args = run.call_args.args[0]
        self.assertEqual(args, ["kwallet-query", "--read-password", "maya.provider.ministral_14b.api_key", "--folder", "Maya", "kdewallet"])
        self.assertIs(run.call_args.kwargs["stderr"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
