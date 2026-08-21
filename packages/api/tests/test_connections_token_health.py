"""`/debug_token` health-check tests (QUA-91), fully offline.

`HttpMetaTokenHealthClient` is driven through a real `httpx.MockTransport` (same posture
`test_publishing_client.py` uses for `HttpPublishClient`) so the actual request
construction is exercised, not just the parse function. `TokenHealthChecker` is tested
against fakes for the reader/encryptor, mirroring `test_connections_auth_error.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.resolver import EncryptedCredential
from qualify_api.connections.token_health import (
    DATA_ACCESS_WARNING_THRESHOLD,
    HttpMetaTokenHealthClient,
    TokenHealthChecker,
    TokenHealthError,
    TokenHealthReport,
)

SETTINGS = MetaOAuthSettings(
    app_id="1670943920870196",
    app_secret="app-secret",
    redirect_uri="https://x/cb",
    state_secret="s",
)
GRAPH = "https://graph.facebook.com/v21.0"
TOKEN = "SUPER_SECRET_PAGE_TOKEN"
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")


def _client(handler) -> HttpMetaTokenHealthClient:
    return HttpMetaTokenHealthClient(SETTINGS, transport=httpx.MockTransport(handler))


def test_debug_token_request_shape() -> None:
    """Verifies the URL, and that the INSPECTED token and the INSPECTING app credential
    never get swapped — the classic way to misuse this endpoint."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "data": {
                    "is_valid": True,
                    "expires_at": 0,
                    "data_access_expires_at": 1795035436,
                    "scopes": ["instagram_basic"],
                }
            },
        )

    _client(handler).debug_token(TOKEN)
    assert str(httpx.URL(seen["url"])).startswith(f"{GRAPH}/debug_token")
    assert f"input_token={TOKEN}" in seen["url"]
    assert f"access_token={SETTINGS.app_id}%7C{SETTINGS.app_secret}" in seen["url"]


def test_parses_a_real_shaped_response() -> None:
    """Exact shape observed live against production, 2026-08-20."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "is_valid": True,
                    "expires_at": 0,
                    "data_access_expires_at": 1795035436,
                    "issued_at": 1787259440,
                    "scopes": ["instagram_basic", "instagram_content_publish"],
                    "user_id": "122097205881433944",
                    "app_id": SETTINGS.app_id,
                }
            },
        )

    report = _client(handler).debug_token(TOKEN)
    assert report == TokenHealthReport(
        is_valid=True,
        expires_at=None,  # 0 -> no calendar expiry, same convention oauth_credentials uses
        data_access_expires_at=datetime.fromtimestamp(1795035436, tz=UTC),
        scopes=("instagram_basic", "instagram_content_publish"),
    )


def test_is_valid_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"is_valid": False, "scopes": []}},
        )

    report = _client(handler).debug_token(TOKEN)
    assert report.is_valid is False


def test_nonzero_expires_at_is_not_swallowed() -> None:
    """Not our production case, but a real one Meta's docs allow — must not silently
    become None the way `0` legitimately does."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"is_valid": True, "expires_at": 1787300000}})

    report = _client(handler).debug_token(TOKEN)
    assert report.expires_at == datetime.fromtimestamp(1787300000, tz=UTC)


def test_non_200_raises_token_health_error_without_leaking_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": TOKEN}})

    with pytest.raises(TokenHealthError) as exc_info:
        _client(handler).debug_token(TOKEN)
    assert TOKEN not in str(exc_info.value)


def test_missing_data_object_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(TokenHealthError):
        _client(handler).debug_token(TOKEN)


def test_missing_is_valid_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"scopes": []}})

    with pytest.raises(TokenHealthError):
        _client(handler).debug_token(TOKEN)


# --- TokenHealthChecker: reader + encryptor + client, no real DB/network -----------------


@dataclass
class FakeReader:
    rows: dict[UUID, EncryptedCredential] = field(default_factory=dict)

    def read_current(self, connection_id: UUID) -> EncryptedCredential:
        return self.rows[connection_id]


@dataclass
class FakeEncryptor:
    """Round-trips via a trivial reversible map, so a test can assert the checker fed
    the client the ACTUAL plaintext, not the ciphertext or something else."""

    key_id: str = "fake-1"

    def encrypt(self, plaintext: str) -> bytes:
        return plaintext.encode("utf-8")[::-1]

    def decrypt(self, ciphertext: bytes, *, key_id: str) -> str:
        assert key_id == self.key_id
        return ciphertext[::-1].decode("utf-8")


@dataclass
class FakeMetaTokenHealthClient:
    report: TokenHealthReport
    seen_tokens: list[str] = field(default_factory=list)

    def debug_token(self, token: str) -> TokenHealthReport:
        self.seen_tokens.append(token)
        return self.report


def _encrypted(encryptor: FakeEncryptor) -> EncryptedCredential:
    return EncryptedCredential(ciphertext=encryptor.encrypt(TOKEN), key_id=encryptor.key_id)


def _valid_report(**overrides: object) -> TokenHealthReport:
    defaults: dict[str, object] = {
        "is_valid": True,
        "expires_at": None,
        "data_access_expires_at": None,
        "scopes": (),
    }
    defaults.update(overrides)
    return TokenHealthReport(**defaults)


def test_checker_decrypts_and_forwards_the_real_token() -> None:
    encryptor = FakeEncryptor()
    reader = FakeReader({CONNECTION: _encrypted(encryptor)})
    client = FakeMetaTokenHealthClient(report=_valid_report())
    checker = TokenHealthChecker(reader=reader, encryptor=encryptor, client=client)

    report = checker.check(CONNECTION)

    assert client.seen_tokens == [TOKEN]
    assert report.is_valid is True


def test_checker_returns_the_client_report_verbatim() -> None:
    expected = _valid_report(is_valid=False, scopes=("instagram_basic",))
    encryptor = FakeEncryptor()
    reader = FakeReader({CONNECTION: _encrypted(encryptor)})
    checker = TokenHealthChecker(
        reader=reader, encryptor=encryptor, client=FakeMetaTokenHealthClient(report=expected)
    )

    assert checker.check(CONNECTION) == expected


def test_checker_propagates_a_lookup_miss() -> None:
    """No swallowing here (unlike `degrade_on_auth_error`) — this is a caller-visible
    infra failure, not a verdict about a token."""
    checker = TokenHealthChecker(
        reader=FakeReader({}),
        encryptor=FakeEncryptor(),
        client=FakeMetaTokenHealthClient(report=_valid_report()),
    )
    with pytest.raises(KeyError):
        checker.check(uuid4())


def test_warning_threshold_is_two_weeks() -> None:
    """Pins the constant so a change is a deliberate diff, not an accidental drift."""
    assert DATA_ACCESS_WARNING_THRESHOLD.days == 14
