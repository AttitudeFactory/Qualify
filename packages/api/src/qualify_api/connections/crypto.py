"""Encryption seam for credential material (C-03, §2.2).

`Encryptor` is the Protocol the credential store and resolver depend on. `key_id` rides on
every `oauth_credentials` row so a rotated key can decrypt old rows without re-encrypting
everything (envelope-encryption discipline). The dev implementation uses Fernet with a key
from the environment — it is a real cipher, but the master-key custody question (env vs
KMS/Vault, W1-Q3) stays open; only the `key_id` indirection is committed here.

Security note: plaintext lives only in memory for the moment of encrypt/decrypt and is
never logged, stored, or returned across the resolver boundary (see resolver.py).
"""

from __future__ import annotations

import os
from typing import Protocol

from cryptography.fernet import Fernet

# Dev-only default key. Overridden by QUALIFY_DEV_FERNET_KEY in any real environment. A
# committed dev key is acceptable ONLY because dev/CI never hold a real client token.
_DEFAULT_DEV_FERNET_KEY = "3UyletMkWzZYWGxELtFoQSD66gBSPq-j4OkVV69Vir4="


class Encryptor(Protocol):
    @property
    def key_id(self) -> str:
        """Identifier of the key currently used for encryption (stored per row)."""
        ...

    def encrypt(self, plaintext: str) -> bytes: ...

    def decrypt(self, ciphertext: bytes, *, key_id: str) -> str: ...


class DevEncryptor:
    """Fernet-backed encryptor for dev/CI. Holds a small `key_id -> key` map so decryption
    can select the key a row was encrypted under (forward-compatible with rotation)."""

    def __init__(self, key_id: str | None = None, keys: dict[str, str] | None = None) -> None:
        self._key_id = key_id or os.environ.get("QUALIFY_DEV_KEY_ID", "dev-1")
        default_key = os.environ.get("QUALIFY_DEV_FERNET_KEY", _DEFAULT_DEV_FERNET_KEY)
        raw = keys or {self._key_id: default_key}
        self._fernets = {kid: Fernet(key.encode("utf-8")) for kid, key in raw.items()}

    @property
    def key_id(self) -> str:
        return self._key_id

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernets[self._key_id].encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes, *, key_id: str) -> str:
        try:
            fernet = self._fernets[key_id]
        except KeyError:
            raise KeyError(f"no key registered for key_id={key_id!r}") from None
        return fernet.decrypt(ciphertext).decode("utf-8")
