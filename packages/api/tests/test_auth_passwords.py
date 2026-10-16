"""Offline tests for the password lifecycle (2026-10-06): recovery link, reset, change,
the per-email throttle, and the Supabase status-code contract of the new endpoints."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from qualify_api.auth import (
    AttemptThrottle,
    FakeAuthProvider,
    InvalidCredentials,
    LoginResult,
    PasswordChangeInvalid,
    PasswordRejected,
    RateLimited,
    SessionExpired,
    SupabaseSettings,
    change_password,
    complete_password_reset,
    request_password_reset,
)
from qualify_api.auth import passwords as passwords_module
from qualify_api.auth.supabase import SupabaseAuthProvider

_RESET_URL = "https://app.example/reset"
_TENANT = UUID("a0000000-0000-4000-8000-000000000001")


def _recovery_token(provider: FakeAuthProvider, email: str) -> str:
    request_password_reset(provider, email, _RESET_URL)
    _, link = provider.sent_resets[-1]
    assert link.startswith(_RESET_URL + "#")
    return link.split("access_token=")[1].split("&")[0]


@pytest.fixture
def provider() -> FakeAuthProvider:
    fake = FakeAuthProvider()
    fake.seed_user("hlrd1993+polet@gmail.com", "old-password", tenant_id=_TENANT)
    return fake


# --------------------------------------------------------------------------------------
# Recovery
# --------------------------------------------------------------------------------------


def test_reset_link_is_silent_for_an_unknown_email(provider: FakeAuthProvider) -> None:
    request_password_reset(provider, "nobody@b.co", _RESET_URL)  # no error, no hint
    assert provider.sent_resets == []


def test_reset_sets_the_password_revokes_sessions_and_signs_in(
    provider: FakeAuthProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = "hlrd1993+polet@gmail.com"
    stale_session = provider.sign_in(email, "old-password").access_token
    token = _recovery_token(provider, email)
    logins: list[tuple[str, str]] = []

    def fake_resolve_login(prov, e: str, p: str) -> LoginResult:
        prov.sign_in(e, p)  # the new password really works
        logins.append((e, p))
        return LoginResult(_TENANT, uuid4(), uuid4(), e, "Polet", "tok")

    monkeypatch.setattr(passwords_module, "resolve_login", fake_resolve_login)
    result = complete_password_reset(provider, token, "new-password", "new-password")

    assert result.tenant_id == _TENANT
    assert logins == [(email, "new-password")]  # the literal alias, never normalized
    assert not provider.token_is_live(stale_session)  # sessions before the reset die
    assert not provider.token_is_live(token)  # the link is single-use
    with pytest.raises(InvalidCredentials):
        provider.sign_in(email, "old-password")


def test_a_used_or_unknown_recovery_token_is_expired(provider: FakeAuthProvider) -> None:
    with pytest.raises(SessionExpired):
        complete_password_reset(provider, "fake-recovery-bogus", "new-password", "new-password")


@pytest.mark.parametrize(
    ("new", "confirm"),
    [("short", "short"), ("new-password", "other-password")],
)
def test_reset_refuses_a_short_or_mismatched_password(
    provider: FakeAuthProvider, new: str, confirm: str
) -> None:
    token = _recovery_token(provider, "hlrd1993+polet@gmail.com")
    with pytest.raises(PasswordChangeInvalid):
        complete_password_reset(provider, token, new, confirm)
    assert provider.token_is_live(token)  # nothing was spent on bad input


# --------------------------------------------------------------------------------------
# Change while logged in
# --------------------------------------------------------------------------------------


def test_change_password_rechecks_the_current_one(provider: FakeAuthProvider) -> None:
    with pytest.raises(InvalidCredentials):  # raw, so the UI can count it as a failure
        change_password(
            provider, "hlrd1993+polet@gmail.com", "wrong", "new-password", "new-password"
        )


def test_change_password_refuses_the_same_password(provider: FakeAuthProvider) -> None:
    with pytest.raises(PasswordChangeInvalid):
        change_password(
            provider, "hlrd1993+polet@gmail.com", "old-password", "old-password", "old-password"
        )


def test_change_password_swaps_it_and_returns_a_live_token(provider: FakeAuthProvider) -> None:
    email = "hlrd1993+polet@gmail.com"
    token = change_password(provider, email, "old-password", "new-password", "new-password")
    assert provider.token_is_live(token)
    provider.sign_in(email, "new-password")
    with pytest.raises(InvalidCredentials):
        provider.sign_in(email, "old-password")


# --------------------------------------------------------------------------------------
# Throttle
# --------------------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_throttle_locks_after_the_limit_and_frees_as_attempts_age() -> None:
    clock = _Clock()
    throttle = AttemptThrottle(max_attempts=3, window_seconds=60, clock=clock)
    for _ in range(3):
        assert throttle.retry_after("a@b.co") == 0
        throttle.note("a@b.co")
        clock.now += 10
    assert throttle.retry_after("a@b.co") == 30  # oldest attempt (t=1000) frees at 1060
    assert throttle.retry_after("other@b.co") == 0  # per key, never global
    clock.now += 30
    assert throttle.retry_after("a@b.co") == 0


def test_throttle_clear_forgets_the_key() -> None:
    throttle = AttemptThrottle(max_attempts=1, window_seconds=60, clock=_Clock())
    throttle.note("a@b.co")
    assert throttle.retry_after("a@b.co") > 0
    throttle.clear("a@b.co")
    assert throttle.retry_after("a@b.co") == 0


# --------------------------------------------------------------------------------------
# Supabase status-code contract for the new endpoints
# --------------------------------------------------------------------------------------

SETTINGS = SupabaseSettings(
    url="https://project.supabase.co", publishable_key="sb_publishable_test", secret_key=None
)


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return json.loads(json.dumps(self._payload))


def _stub(monkeypatch: pytest.MonkeyPatch, verb: str, response: _Response) -> dict:
    captured: dict = {}

    def fake(url: str, **kwargs) -> _Response:
        captured["url"], captured["kwargs"] = url, kwargs
        return response

    monkeypatch.setattr(f"qualify_api.auth.supabase.httpx.{verb}", fake)
    return captured


def test_recover_posts_email_and_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _stub(monkeypatch, "post", _Response(200))
    SupabaseAuthProvider(SETTINGS).send_password_reset("a+x@b.co", _RESET_URL)
    assert captured["url"].endswith("/auth/v1/recover")
    assert captured["kwargs"]["params"] == {"redirect_to": _RESET_URL}
    assert captured["kwargs"]["json"] == {"email": "a+x@b.co"}


def test_recover_4xx_is_silent_and_429_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, "post", _Response(400))
    SupabaseAuthProvider(SETTINGS).send_password_reset("a@b.co", _RESET_URL)
    _stub(monkeypatch, "post", _Response(429))
    with pytest.raises(RateLimited):
        SupabaseAuthProvider(SETTINGS).send_password_reset("a@b.co", _RESET_URL)


def test_sign_in_429_is_rate_limited_not_bad_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, "post", _Response(429))
    with pytest.raises(RateLimited):
        SupabaseAuthProvider(SETTINGS).sign_in("a@b.co", "x" * 8)


def test_update_password_uses_the_user_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _stub(monkeypatch, "put", _Response(200))
    SupabaseAuthProvider(SETTINGS).update_password("user-token", "new-password")
    assert captured["url"].endswith("/auth/v1/user")
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer user-token"
    assert captured["kwargs"]["json"] == {"password": "new-password"}


@pytest.mark.parametrize(
    ("status", "payload", "error"),
    [
        (401, {}, SessionExpired),
        (403, {}, SessionExpired),
        (422, {"error_code": "reauthentication_needed"}, SessionExpired),
        (422, {"error_code": "same_password"}, PasswordRejected),
        (422, {"error_code": "weak_password"}, PasswordRejected),
        (429, {}, RateLimited),
    ],
)
def test_update_password_status_contract(
    monkeypatch: pytest.MonkeyPatch, status: int, payload: dict, error: type[Exception]
) -> None:
    _stub(monkeypatch, "put", _Response(status, payload))
    with pytest.raises(error):
        SupabaseAuthProvider(SETTINGS).update_password("user-token", "new-password")


def test_same_password_rejection_is_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, "put", _Response(422, {"error_code": "same_password"}))
    with pytest.raises(PasswordRejected) as exc:
        SupabaseAuthProvider(SETTINGS).update_password("user-token", "new-password")
    assert "distinta" in exc.value.message


def test_user_email_reads_the_token_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, "get", _Response(200, {"email": "a+x@b.co"}))
    assert SupabaseAuthProvider(SETTINGS).user_email("user-token") == "a+x@b.co"
    _stub(monkeypatch, "get", _Response(401))
    with pytest.raises(SessionExpired):
        SupabaseAuthProvider(SETTINGS).user_email("user-token")
