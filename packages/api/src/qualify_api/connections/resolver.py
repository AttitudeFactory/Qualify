"""Credential resolution (C-03.2, R3). The hard rule: workers ask for an already
authenticated HTTP client, NEVER for a token. Decryption happens inside the resolver; the
plaintext lives only long enough to build the client and never crosses this boundary — no
public method returns it, and repr redacts it.

Structurally (R3), only the narrow `qualify_credential` role can read `ciphertext`/`key_id`
(the `qualify_app` grant excludes those columns), so even the resolver's DB reader runs
under that role — and it is RLS-subject, so it only ever decrypts within its own tenant.
The DB-backed `CredentialReader` lands with C-04's wiring; this module defines the seam and
the injecting resolver, tested with fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import httpx

from qualify_api.connections.crypto import Encryptor


@dataclass(frozen=True)
class EncryptedCredential:
    """The ciphertext + the key it was sealed under — the only credential shape that
    leaves the store. Plaintext is produced transiently inside the resolver."""

    ciphertext: bytes
    key_id: str


class CredentialReader(Protocol):
    """Reads the current (highest-version) encrypted credential for a connection. The DB
    implementation runs as `qualify_credential` (the only role granted `ciphertext`)."""

    def read_current(self, connection_id: UUID) -> EncryptedCredential: ...


class AuthenticatedClient(Protocol):
    """An HTTP client with the credential already injected. Exposes request verbs only —
    never the token."""

    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...

    async def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class CredentialResolver(Protocol):
    async def client_for(self, connection_id: UUID) -> AuthenticatedClient: ...


class _BearerClient:
    """Wraps `httpx.AsyncClient`, injecting the token as a Bearer header (kept out of the
    URL, so it does not leak into request logs). The token is NOT stored as an attribute
    and repr redacts it — there is no supported path from this object back to the token."""

    def __init__(self, token: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # The token goes straight into the client's default headers; it is not retained on
        # `self` under any other name.
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, transport=transport
        )

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._client.get(url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._client.post(url, **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()

    def __repr__(self) -> str:
        return "<AuthenticatedClient token=redacted>"


class InjectingCredentialResolver:
    """Reads the encrypted credential, decrypts it in memory, and returns a client with the
    token injected. The token never becomes a return value or an attribute of the resolver."""

    def __init__(self, reader: CredentialReader, encryptor: Encryptor) -> None:
        self._reader = reader
        self._encryptor = encryptor

    async def client_for(self, connection_id: UUID) -> AuthenticatedClient:
        credential = self._reader.read_current(connection_id)
        token = self._encryptor.decrypt(credential.ciphertext, key_id=credential.key_id)
        return _BearerClient(token)
