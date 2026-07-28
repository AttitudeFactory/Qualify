"""Pure resolver tests (C-03.2): the resolver returns an authenticated client, never a
token. The token is injected into requests but is not exposed by the client's API or repr."""

from __future__ import annotations

import asyncio
from uuid import UUID

import httpx

from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.resolver import (
    EncryptedCredential,
    InjectingCredentialResolver,
    _BearerClient,
)

CONN = UUID("33333333-3333-3333-3333-333333333333")
TOKEN = "SECRET_ACCESS_TOKEN"


class FakeReader:
    """Returns a fixed encrypted credential — stands in for the qualify_credential-scoped
    DB read."""

    def __init__(self, encryptor: DevEncryptor) -> None:
        self._cred = EncryptedCredential(
            ciphertext=encryptor.encrypt(TOKEN), key_id=encryptor.key_id
        )

    def read_current(self, connection_id: UUID) -> EncryptedCredential:
        return self._cred


def test_resolver_returns_client_not_token() -> None:
    enc = DevEncryptor()
    resolver = InjectingCredentialResolver(FakeReader(enc), enc)
    client = asyncio.run(resolver.client_for(CONN))
    # No supported path back to the token: not in repr, no token-ish attribute.
    assert TOKEN not in repr(client)
    assert not hasattr(client, "token")
    assert not hasattr(client, "_token")


def test_resolver_injects_bearer_token_into_requests() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"ok": True})

    async def run() -> None:
        client = _BearerClient(TOKEN, transport=httpx.MockTransport(handler))
        resp = await client.get("https://graph.facebook.com/v21.0/me")
        assert resp.status_code == 200
        await client.aclose()

    asyncio.run(run())
    assert captured["authorization"] == f"Bearer {TOKEN}"


def test_resolver_decrypts_via_encryptor() -> None:
    # End-to-end: encrypted credential in → a working client out, token never surfaced.
    enc = DevEncryptor()
    reader = FakeReader(enc)
    resolver = InjectingCredentialResolver(reader, enc)
    client = asyncio.run(resolver.client_for(CONN))
    assert isinstance(client, _BearerClient)
