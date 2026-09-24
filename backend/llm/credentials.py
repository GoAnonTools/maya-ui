"""Credential lookup for Maya-owned LLM providers.

Secrets are returned to the caller in memory only. Backends must not persist or
log secret values, and resolver logging deliberately avoids exception details.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Mapping, Protocol
from urllib.parse import unquote, urlsplit

logger = logging.getLogger("maya.credentials")


class CredentialBackend(Protocol):
    """A source capable of resolving one credential reference."""

    def resolve(self, reference: str) -> str | None:
        """Return a secret for ``reference`` or None when it is unavailable."""


_SAFE_ENTRY = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")


def _safe_component(value: str) -> bool:
    return bool(value) and len(value) <= 256 and value not in {".", ".."} and not any(
        char in value for char in ("/", "\\", "\x00")
    ) and not any(ord(char) < 32 for char in value)


class KDEWalletBackend:
    """Resolve KWallet entries through KDE's ``kwallet-query`` utility.

    Plain references name an entry in the configured wallet and folder.
    ``kwallet://wallet/folder/entry`` references can select a specific location.
    """

    def __init__(
        self,
        wallet: str = "kdewallet",
        folder: str = "Maya",
        executable: str = "kwallet-query",
        timeout: float = 3.0,
    ) -> None:
        self.wallet = wallet
        self.folder = folder
        self.executable = executable
        self.timeout = timeout

    def _parse_reference(self, reference: str) -> tuple[str, str, str] | None:
        if not isinstance(reference, str) or not reference:
            return None
        if reference.startswith("kwallet://"):
            try:
                parsed = urlsplit(reference)
                wallet = unquote(parsed.netloc)
                parts = [unquote(part) for part in parsed.path.lstrip("/").split("/")]
                if parsed.scheme != "kwallet" or parsed.query or parsed.fragment or len(parts) != 2:
                    return None
                folder, entry = parts
                if not all(_safe_component(part) for part in (wallet, folder, entry)):
                    return None
                return wallet, folder, entry
            except (ValueError, UnicodeError):
                return None
        if _SAFE_ENTRY.fullmatch(reference):
            if not _safe_component(self.wallet) or not _safe_component(self.folder):
                return None
            return self.wallet, self.folder, reference
        return None

    def resolve(self, reference: str) -> str | None:
        parsed = self._parse_reference(reference)
        if parsed is None:
            return None
        wallet, folder, entry = parsed
        try:
            result = subprocess.run(
                [self.executable, "--read-password", entry, "--folder", folder, wallet],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("KDE Wallet credential lookup failed")
            return None
        if result.returncode != 0:
            return None
        secret = result.stdout.rstrip("\r\n")
        return secret or None


class CredentialResolver:
    """Route credential references to generic secret backends."""

    def __init__(
        self,
        backends: Mapping[str, CredentialBackend],
        default_backend: str = "kwallet",
    ) -> None:
        self._backends = dict(backends)
        self._default_backend = default_backend

    def resolve(self, reference: str) -> str | None:
        if not isinstance(reference, str) or not reference or len(reference) > 1024:
            return None
        backend_name = self._default_backend
        if "://" in reference:
            backend_name = reference.split(":", 1)[0].lower()
        backend = self._backends.get(backend_name)
        if backend is None:
            return None
        try:
            value = backend.resolve(reference)
        except Exception:
            # Exception messages from secret stores are outside our control.
            logger.warning("Credential backend lookup failed")
            return None
        return value if isinstance(value, str) and value else None

    def __call__(self, reference: str) -> str | None:
        return self.resolve(reference)


def create_default_credential_resolver() -> CredentialResolver:
    return CredentialResolver({"kwallet": KDEWalletBackend()})
