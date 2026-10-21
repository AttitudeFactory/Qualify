"""Offline tests for the signup gate (invite-only, 2026-10-14), the invitation email,
and the Resend client's status contract. The database half (create,
look up, consume once) is in `test_auth_invites_db.py`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qualify_api.auth import CreatedInvite, InviteView, SignupNotAllowed, authorize_signup
from qualify_api.auth import invites as invites_module
from qualify_api.auth.invite_email import invite_email
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
def _signup_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_SIGNUP_OPEN", raising=False)


def _invite_for(monkeypatch: pytest.MonkeyPatch, email: str | None) -> None:
    view = InviteView(id=uuid4(), email=email, expires_at=_EXPIRES) if email else None
    monkeypatch.setattr(invites_module, "lookup_invite", lambda token: view)


# --------------------------------------------------------------------------------------
# The gate: invite-only (founder decision 2026-10-14)
# --------------------------------------------------------------------------------------


def test_without_an_invite_signup_is_closed() -> None:
    with pytest.raises(SignupNotAllowed) as exc:
        authorize_signup("a@b.co", None)
    assert "invitación" in exc.value.message


def test_dev_can_open_signup_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_SIGNUP_OPEN", "1")
    assert authorize_signup("a@b.co", None) is None
    monkeypatch.setenv("QUALIFY_SIGNUP_OPEN", "true")  # only the literal "1" opens it
    with pytest.raises(SignupNotAllowed):
        authorize_signup("a@b.co", None)


def test_a_valid_invite_opens_signup_for_its_email_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _invite_for(monkeypatch, "cliente+polet@negocio.com")
    assert authorize_signup("cliente+polet@negocio.com", "tok") is not None
    with pytest.raises(SignupNotAllowed) as exc:
        authorize_signup("otro@negocio.com", "tok")
    assert "cliente+polet@negocio.com" in exc.value.message
    with pytest.raises(SignupNotAllowed):  # literal: the +alias is the business
        authorize_signup("cliente@negocio.com", "tok")
    # Case is not identity (the provider folds it); the alias is.
    assert authorize_signup("Cliente+Polet@Negocio.com", "tok") is not None


def test_a_dead_invite_is_refused_even_with_signup_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_SIGNUP_OPEN", "1")
    _invite_for(monkeypatch, None)
    with pytest.raises(SignupNotAllowed):
        authorize_signup("a@b.co", "used-or-unknown")


@pytest.mark.parametrize("email", ["", "no-at", "a@b", "a b@c.co"])
def test_create_invite_refuses_a_bad_email_before_touching_the_db(email: str) -> None:
    with pytest.raises(SignupNotAllowed):
        invites_module.create_invite(email)


def test_create_invite_refuses_an_overlong_note_before_touching_the_db() -> None:
    with pytest.raises(SignupNotAllowed):
        invites_module.create_invite("a@b.co", note="x" * 601)


# --------------------------------------------------------------------------------------
# The email
# --------------------------------------------------------------------------------------


def _full_invite(**overrides) -> CreatedInvite:
    fields = {
        "email": "maria@arepera.com",
        "token": "tok123",
        "expires_at": _EXPIRES,
        "recipient_name": "María",
        "business_name": "Arepera La Nona",
        "note": "Como hablamos hoy.\nEl viernes revisamos tu campaña.",
    }
    fields.update(overrides)
    return CreatedInvite(**fields)


def test_invite_email_is_personal_when_it_knows_who() -> None:
    mail = invite_email(_full_invite(), "https://qualify.example/", signer="Herwin Rey")
    assert mail.subject == "Herwin te invitó a crear la cuenta de Arepera La Nona en Qualify"
    assert "Hola, María:" in mail.text and "Hola, María:" in mail.html
    assert "Herwin Rey te invitó" in mail.text
    assert "https://qualify.example/registro?invitacion=tok123" in mail.text
    assert 'href="https://qualify.example/registro?invitacion=tok123"' in mail.html
    assert "signup" not in mail.text and "invite=" not in mail.html  # no English path
    assert "El viernes revisamos tu campaña." in mail.text
    assert "Como hablamos hoy.<br>El viernes" in mail.html  # the note keeps its lines
    assert "14 de octubre" in mail.text  # Spanish date, market time (Caracas)
    assert 'src="https://qualify.example/qualify-mark-email.png"' in mail.html


def test_the_invite_link_is_spelled_in_spanish() -> None:
    """Founder rule 2026-10-21: the client reads this path, so no English in it."""
    link = _full_invite().link("https://qualify.example/")
    assert link == "https://qualify.example/registro?invitacion=tok123"
    assert invites_module.LEGACY_SIGNUP_ROUTE == "/signup"  # still served: links already sent


def test_invite_email_degrades_to_qualify_without_names() -> None:
    bare = CreatedInvite(email="a@b.co", token="t", expires_at=_EXPIRES)
    mail = invite_email(bare, "http://x")
    assert mail.subject == "Tu invitación a Qualify"
    assert "Hola:" in mail.text and "Te invitamos a crear la cuenta de tu negocio" in mail.text
    assert "Responde este correo" not in mail.text  # no Reply-To, no promise
    assert "Responde este correo" in invite_email(bare, "http://x", can_reply=True).text


def test_invite_email_escapes_everything_a_person_typed() -> None:
    hostile = _full_invite(
        email='a+"x"<b>@negocio.com',
        recipient_name="<script>alert(1)</script>",
        business_name="Tacos & <b>Co</b>",
        note='<img src=x onerror="alert(1)">',
    )
    html = invite_email(hostile, "http://x", signer="<i>H</i>").html
    for raw in ("<script>", "<b>Co</b>", "<img src=x", "<b>@negocio", "<i>H</i>"):
        assert raw not in html


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
        invite_email(invite, "http://x")
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
            invite_email(CreatedInvite(email="a@b.co", token="t", expires_at=_EXPIRES), "http://x")
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
