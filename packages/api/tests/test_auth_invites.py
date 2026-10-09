"""Offline tests for the signup gate (2026-10-07): shared code, invite decisions, the
invitation email, and the Resend client's status contract. The database half (create,
look up, consume once) is in `test_auth_invites_db.py`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qualify_api.auth import CreatedInvite, InviteView, SignupNotAllowed, authorize_signup
from qualify_api.auth import invites as invites_module
from qualify_api.mail import (
    FakeMailer,
    MailError,
    MailNotConfigured,
    ResendMailer,
    default_mailer,
    reset_default_mailer,
)

_EXPIRES = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_SIGNUP_CODE", raising=False)


def _invite_for(monkeypatch: pytest.MonkeyPatch, email: str | None) -> None:
    view = InviteView(id=uuid4(), email=email, expires_at=_EXPIRES) if email else None
    monkeypatch.setattr(invites_module, "lookup_invite", lambda token: view)


# --------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------


def test_without_a_code_configured_signup_is_open() -> None:
    assert authorize_signup("a@b.co", None, None) is None


def test_the_shared_code_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_SIGNUP_CODE", "polet-2026")
    with pytest.raises(SignupNotAllowed):
        authorize_signup("a@b.co", None, None)
    with pytest.raises(SignupNotAllowed):
        authorize_signup("a@b.co", None, "wrong")
    assert authorize_signup("a@b.co", None, " polet-2026 ") is None  # pasted with spaces


def test_a_valid_invite_opens_signup_for_its_email_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_SIGNUP_CODE", "polet-2026")  # the invite needs no code
    _invite_for(monkeypatch, "cliente+polet@negocio.com")
    assert authorize_signup("cliente+polet@negocio.com", "tok", None) is not None
    with pytest.raises(SignupNotAllowed) as exc:
        authorize_signup("otro@negocio.com", "tok", None)
    assert "cliente+polet@negocio.com" in exc.value.message
    with pytest.raises(SignupNotAllowed):  # literal: the +alias is the business
        authorize_signup("cliente@negocio.com", "tok", None)


def test_a_dead_invite_is_refused_even_with_signup_open(monkeypatch: pytest.MonkeyPatch) -> None:
    _invite_for(monkeypatch, None)
    with pytest.raises(SignupNotAllowed):
        authorize_signup("a@b.co", "used-or-unknown", None)


@pytest.mark.parametrize("email", ["", "no-at", "a@b", "a b@c.co"])
def test_create_invite_refuses_a_bad_email_before_touching_the_db(email: str) -> None:
    with pytest.raises(SignupNotAllowed):
        invites_module.create_invite(email)


# --------------------------------------------------------------------------------------
# The email
# --------------------------------------------------------------------------------------


def test_invite_email_carries_the_link_and_escapes_the_address() -> None:
    invite = CreatedInvite(email='a+"x"<b>@negocio.com', token="tok123", expires_at=_EXPIRES)
    mail = invites_module.invite_email(invite, "https://qualify.example/")
    assert mail.to == invite.email
    assert "https://qualify.example/signup?invite=tok123" in mail.text
    assert "https://qualify.example/signup?invite=tok123" in mail.html
    assert "<b>@negocio" not in mail.html  # escaped, not markup
    assert "14/10/2026" in mail.text


def test_send_invite_email_goes_through_the_mailer() -> None:
    mailer = FakeMailer()
    invite = CreatedInvite(email="a@b.co", token="tok", expires_at=_EXPIRES)
    invites_module.send_invite_email(mailer, invite, "http://localhost:3100")
    assert [m.to for m in mailer.sent] == ["a@b.co"]


# --------------------------------------------------------------------------------------
# Resend client
# --------------------------------------------------------------------------------------


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload


def test_resend_posts_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_post(url: str, **kwargs) -> _Response:
        captured["url"], captured["kwargs"] = url, kwargs
        return _Response(200, {"id": "x"})

    monkeypatch.setattr("qualify_api.mail.httpx.post", fake_post)
    invite = CreatedInvite(email="a@b.co", token="tok", expires_at=_EXPIRES)
    ResendMailer("re_test", "Qualify <no-reply@send.example>").send(
        invites_module.invite_email(invite, "http://x")
    )
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer re_test"
    body = captured["kwargs"]["json"]
    assert body["to"] == ["a@b.co"] and body["from"] == "Qualify <no-reply@send.example>"
    assert body["html"] and body["text"]


def test_resend_refusal_is_a_mail_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "qualify_api.mail.httpx.post", lambda url, **kw: _Response(403, {"message": "domain"})
    )
    with pytest.raises(MailError):
        ResendMailer("re_test", "x@y.co").send(
            invites_module.invite_email(
                CreatedInvite(email="a@b.co", token="t", expires_at=_EXPIRES), "http://x"
            )
        )


def test_unconfigured_mail_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("QUALIFY_RESEND_API_KEY", "QUALIFY_MAIL_FROM", "QUALIFY_MAIL_FAKE"):
        monkeypatch.delenv(var, raising=False)
    reset_default_mailer()
    try:
        with pytest.raises(MailNotConfigured):
            default_mailer()
    finally:
        reset_default_mailer()
