"""Who may register a business (2026-10-07): a shared code, or an emailed invitation.

Two keys, either one opens `/signup`:

- **Shared code** — `QUALIFY_SIGNUP_CODE`. Unset means signup is open (dev); production
  sets it (see `deploy/.env.prod.example`). Compared in constant time.
- **Invitation** — `create_invite` stores the SHA-256 of a random token (migration
  0056) and `send_invite_email` mails the link `/signup?invite=<token>`. The invite opens
  signup only for ITS email, once, until it expires. Because the link reaches only that
  inbox, an invited signup also proves the email is the registrant's — something the
  shared code does not.

`authorize_signup` decides before the identity user is created; `consume_invite` marks
the invite used inside `register_business`'s transaction, with a row lock, so two tabs
racing on one link make one account.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from qualify_shared.db.admin import admin_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.mail import Mailer, OutgoingMail
from qualify_api.tenancy.models import SignupInvite

DEFAULT_INVITE_DAYS = 7
SIGNUP_ROUTE = "/signup"


class SignupNotAllowed(Exception):
    """Signup refused by the gate. `message` is safe to show to the operator."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class CreatedInvite:
    email: str
    token: str  # the raw token: only ever in the link, never stored
    expires_at: datetime

    def link(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}{SIGNUP_ROUTE}?invite={self.token}"


@dataclass(frozen=True)
class InviteView:
    """A valid invite, as the signup screen may see it."""

    id: UUID
    email: str
    expires_at: datetime


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def signup_code() -> str:
    return os.environ.get("QUALIFY_SIGNUP_CODE", "").strip()


def signup_code_required() -> bool:
    return bool(signup_code())


def _valid_email(email: str) -> bool:
    local, _, domain = email.partition("@")
    return (
        email.count("@") == 1
        and bool(local)
        and "." in domain
        and not domain.startswith(".")
        and not domain.endswith(".")
        and not any(ch.isspace() for ch in email)
    )


def create_invite(
    email: str, *, days: int = DEFAULT_INVITE_DAYS, invited_by: str | None = None
) -> CreatedInvite:
    """Store a new invite for `email` (literal, like every login email — the `+alias`
    is the business). Earlier unused invites for the same email stay valid."""
    email = email.strip()
    if not _valid_email(email):
        raise SignupNotAllowed("El email no es válido.")
    if days < 1:
        raise SignupNotAllowed("La invitación debe durar al menos un día.")
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(days=days)
    with admin_session() as session:
        session.add(
            SignupInvite(
                email=email,
                token_hash=_hash(token),
                invited_by=invited_by,
                expires_at=expires_at,
            )
        )
    return CreatedInvite(email=email, token=token, expires_at=expires_at)


def _usable(invite: SignupInvite | None) -> bool:
    return invite is not None and invite.used_at is None and invite.expires_at > _now()


def lookup_invite(token: str) -> InviteView | None:
    """The invite behind a link, if it is still usable; None otherwise (unknown, used
    or expired all look the same to the screen)."""
    if not token:
        return None
    with admin_session() as session:
        invite = session.scalar(select(SignupInvite).where(SignupInvite.token_hash == _hash(token)))
        if not _usable(invite):
            return None
        assert invite is not None
        return InviteView(id=invite.id, email=invite.email, expires_at=invite.expires_at)


def authorize_signup(email: str, invite_token: str | None, code: str | None) -> UUID | None:
    """Decide whether this signup may proceed. Returns the invite id to consume (None
    when the shared code or an open signup let it through). Raises `SignupNotAllowed`."""
    if invite_token:
        invite = lookup_invite(invite_token)
        if invite is None:
            raise SignupNotAllowed(
                "La invitación venció o ya se usó. Pide una nueva a quien te invitó."
            )
        if invite.email != email:
            raise SignupNotAllowed(
                f"Esta invitación es para {invite.email}. Regístrate con ese correo."
            )
        return invite.id
    expected = signup_code()
    if not expected:
        return None  # open signup (no code configured)
    if not code or not hmac.compare_digest(code.strip().encode(), expected.encode()):
        raise SignupNotAllowed("El código de invitación no es correcto.")
    return None


def consume_invite(session: Session, invite_id: UUID, email: str) -> None:
    """Mark the invite used, inside the transaction that creates the business. The row
    lock makes a second, concurrent signup with the same link fail here."""
    invite = session.scalar(
        select(SignupInvite).where(SignupInvite.id == invite_id).with_for_update()
    )
    if not _usable(invite) or invite is None or invite.email != email:
        raise SignupNotAllowed(
            "La invitación venció o ya se usó. Pide una nueva a quien te invitó."
        )
    invite.used_at = _now()
    session.flush()


# --------------------------------------------------------------------------------------
# The email
# --------------------------------------------------------------------------------------

_SUBJECT = "Te invitaron a Qualify"

_TEXT = """Hola,

Te invitaron a crear la cuenta de tu negocio en Qualify.

Crea tu cuenta aquí (el enlace es solo para {email} y vence el {expires}):
{link}

Si no esperabas esta invitación, ignora este correo.

— Qualify
"""

# Inline styles (mail clients ignore <style>), kept as constants so the markup reads.
_FONT = "font-family:'IBM Plex Sans',Helvetica,Arial,sans-serif;"
_STYLES = {
    "body": f"margin:0;padding:0;background:#f4f5f6;{_FONT}color:#1c2024;",
    "outer": "background:#f4f5f6;padding:32px 16px;",
    "card": "max-width:480px;background:#ffffff;border:1px solid #e0e1e6;border-radius:12px;",
    "brand": "font-size:20px;font-weight:700;color:#12a594;",
    "h1": "margin:0 0 12px 0;font-size:20px;line-height:1.3;",
    "lead": "margin:0 0 20px 0;font-size:15px;line-height:1.5;color:#60646c;",
    "strong": "color:#1c2024;",
    "button": (
        "display:inline-block;background:#12a594;color:#ffffff;text-decoration:none;"
        "font-weight:600;font-size:15px;padding:12px 22px;border-radius:8px;"
    ),
    "small": "margin:20px 0 0 0;font-size:13px;line-height:1.5;color:#60646c;",
    "link": "color:#0d9b8a;word-break:break-all;",
    "foot": "margin:0;font-size:12px;color:#8b8d98;",
}
_TABLE = 'role="presentation" width="100%" cellpadding="0" cellspacing="0"'

_HTML = """<!doctype html>
<html lang="es">
<body style="{body}">
  <table {table} style="{outer}">
    <tr><td align="center">
      <table {table} style="{card}">
        <tr><td style="padding:32px 32px 8px 32px;"><div style="{brand}">Qualify</div></td></tr>
        <tr><td style="padding:8px 32px 0 32px;">
          <h1 style="{h1}">Te invitaron a crear tu cuenta</h1>
          <p style="{lead}">
            Crea la cuenta de tu negocio en Qualify con el correo
            <strong style="{strong}">{email}</strong>.
          </p>
          <a href="{link}" style="{button}">Crear mi cuenta</a>
          <p style="{small}">
            La invitación sirve una sola vez y vence el {expires}.
            Si el botón no abre, copia este enlace:<br>
            <a href="{link}" style="{link_style}">{link}</a>
          </p>
        </td></tr>
        <tr><td style="padding:24px 32px 32px 32px;">
          <p style="{foot}">Si no esperabas esta invitación, ignora este correo.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def invite_email(invite: CreatedInvite, base_url: str) -> OutgoingMail:
    link = invite.link(base_url)
    expires = invite.expires_at.strftime("%d/%m/%Y")
    return OutgoingMail(
        to=invite.email,
        subject=_SUBJECT,
        text=_TEXT.format(email=invite.email, expires=expires, link=link),
        html=_HTML.format(
            email=html.escape(invite.email),
            expires=html.escape(expires),
            link=html.escape(link, quote=True),
            table=_TABLE,
            link_style=_STYLES["link"],
            **{k: v for k, v in _STYLES.items() if k != "link"},
        ),
    )


def send_invite_email(mailer: Mailer, invite: CreatedInvite, base_url: str) -> None:
    mailer.send(invite_email(invite, base_url))
