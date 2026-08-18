"""Offline tests for `SupabaseAuthProvider` — httpx is stubbed at the module seam, so
these prove the STATUS-CODE CONTRACT (which codes mean what), not Supabase itself."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from qualify_api.auth import (
    AuthProviderError,
    EmailAlreadyRegistered,
    InvalidCredentials,
    SupabaseSettings,
)
from qualify_api.auth.config import AuthNotConfigured
from qualify_api.auth.supabase import SupabaseAuthProvider

SETTINGS = SupabaseSettings(
    url="https://project.supabase.co",
    publishable_key="sb_publishable_test",
    secret_key="sb_secret_test",
)


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return json.loads(json.dumps(self._payload))


def _post_stub(monkeypatch: pytest.MonkeyPatch, response: _Response, captured: dict) -> None:
    def fake_post(url: str, **kwargs) -> _Response:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return response

    monkeypatch.setattr("qualify_api.auth.supabase.httpx.post", fake_post)


def test_sign_in_parses_session_and_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_user_id, tenant_id = uuid4(), uuid4()
    captured: dict = {}
    _post_stub(
        monkeypatch,
        _Response(
            200,
            {
                "access_token": "at",
                "refresh_token": "rt",
                "user": {
                    "id": str(auth_user_id),
                    "email": "a@b.co",
                    "app_metadata": {"tenant_id": str(tenant_id)},
                },
            },
        ),
        captured,
    )
    session = SupabaseAuthProvider(SETTINGS).sign_in("a@b.co", "password-123")
    assert session.auth_user_id == auth_user_id
    assert session.tenant_id == tenant_id
    assert session.access_token == "at"
    # The sign-in must use the PUBLISHABLE key, never the secret.
    assert captured["kwargs"]["headers"]["apikey"] == "sb_publishable_test"
    assert captured["url"].endswith("/auth/v1/token")


def test_sign_in_400_is_invalid_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _post_stub(monkeypatch, _Response(400, {"error": "invalid_grant"}), {})
    with pytest.raises(InvalidCredentials):
        SupabaseAuthProvider(SETTINGS).sign_in("a@b.co", "wrong")


def test_sign_in_5xx_is_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _post_stub(monkeypatch, _Response(503), {})
    with pytest.raises(AuthProviderError):
        SupabaseAuthProvider(SETTINGS).sign_in("a@b.co", "password-123")


def test_malformed_tenant_stamp_reads_as_unstamped(monkeypatch: pytest.MonkeyPatch) -> None:
    _post_stub(
        monkeypatch,
        _Response(
            200,
            {
                "access_token": "at",
                "refresh_token": "rt",
                "user": {
                    "id": str(uuid4()),
                    "email": "a@b.co",
                    "app_metadata": {"tenant_id": "not-a-uuid"},
                },
            },
        ),
        {},
    )
    assert SupabaseAuthProvider(SETTINGS).sign_in("a@b.co", "password-123").tenant_id is None


def test_admin_create_user_conflict_maps_to_already_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for status in (409, 422):
        _post_stub(monkeypatch, _Response(status), {})
        with pytest.raises(EmailAlreadyRegistered):
            SupabaseAuthProvider(SETTINGS).admin_create_user("a@b.co", "password-123", uuid4())


def test_admin_create_user_stamps_app_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    created = uuid4()
    captured: dict = {}
    _post_stub(monkeypatch, _Response(201, {"id": str(created)}), captured)
    result = SupabaseAuthProvider(SETTINGS).admin_create_user("a@b.co", "password-123", tenant_id)
    assert result == created
    body = captured["kwargs"]["json"]
    assert body["app_metadata"] == {"tenant_id": str(tenant_id)}
    assert body["email_confirm"] is True
    # The admin call runs on the SECRET key.
    assert captured["kwargs"]["headers"]["apikey"] == "sb_secret_test"


def test_admin_create_user_without_secret_key_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SupabaseSettings(
        url="https://project.supabase.co", publishable_key="sb_publishable_test", secret_key=None
    )
    with pytest.raises(AuthNotConfigured):
        SupabaseAuthProvider(settings).admin_create_user("a@b.co", "password-123", uuid4())


def test_sign_out_swallows_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def dead_post(url: str, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("qualify_api.auth.supabase.httpx.post", dead_post)
    SupabaseAuthProvider(SETTINGS).sign_out("at")  # must not raise


def test_sign_in_transport_failure_is_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def dead_post(url: str, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("qualify_api.auth.supabase.httpx.post", dead_post)
    with pytest.raises(AuthProviderError):
        SupabaseAuthProvider(SETTINGS).sign_in("a@b.co", "password-123")
