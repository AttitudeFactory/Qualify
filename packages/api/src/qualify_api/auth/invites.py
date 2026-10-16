"""Who may register a business: an emailed invitation (founder decision, 2026-10-14).

The MVP is **invite-only**. `create_invite` stores the SHA-256 of a random token
(migration 0063) together with who it is for — the person's name, the business and an
optional personal note from whoever invites — and `send_invite_email` mails the link
`/signup?invite=<token>` (template: `invite_email`). The invite opens signup only for ITS
email, once, until it expires. Because the link reaches only that inbox, an invited
signup also proves the email is the registrant's.

Without an invite, signup is closed. `QUALIFY_SIGNUP_OPEN=1` reopens it for local
development and tests only; the production compose forces it empty. (A shared signup code
existed briefly on this branch and went to the backlog with the same decision.)

`authorize_signup` decides before anything is created. Inside `register_business`'s
transaction, `lock_invite` takes the row lock and re-checks the invite BEFORE the identity
user is created, and `mark_invite_used` spends it once the business exists — so two tabs
racing on one link make one account and the loser creates nothing, not even an identity
user (an orphan there would block its email until an administrator deleted it).

The invite's email is compared case-insensitively (GoTrue treats `A@b.co` and `a@b.co` as
one account); the `+alias` stays literal, it IS the business.

Since M1 of `docs/plan-altas-meegle.md` an invite may come from a Meegle "Alta de cliente"
item (`meegle_work_item_id`, migration 0064): terminating the item expires its unused
invites (`expire_invites_for_work_item`), and the signup that consumes it writes back to
the item (`auth.service`). `send_invite_email` keeps the Resend email id
(`resend_email_id`) so M2 can match delivery webhooks to the invite.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from qualify_shared.db.admin import admin_session
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from qualify_api.auth.invite_email import invite_email
from qualify_api.mail import Mailer
from qualify_api.tenancy.models import SignupInvite

DEFAULT_INVITE_DAYS = 7
SIGNUP_ROUTE = "/signup"
_NOTE_MAX = 600
_NAME_MAX = 120

_INVITE_DEAD = "La invitación venció o ya se usó. Pide una nueva a quien te invitó."
_INVITE_ONLY = "Qualify es solo por invitación. Si recibiste una, abre el enlace desde el correo."


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
    recipient_name: str = ""
    business_name: str = ""
    note: str = ""
    id: UUID | None = None  # the row's id (`signup_invites.id`), minted on create

    def link(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}{SIGNUP_ROUTE}?invite={self.token}"


@dataclass(frozen=True)
class InviteView:
    """A valid invite, as the signup screen may see it."""

    id: UUID
    email: str
    expires_at: datetime
    business_name: str = ""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def signup_base_url() -> str:
    """Where the invite link points: the public app URL, then Reflex's deploy URL,
    then the local dev port."""
    return (
        os.environ.get("QUALIFY_PUBLIC_URL")
        or os.environ.get("REFLEX_DEPLOY_URL")
        or "http://localhost:3100"
    )


def signup_open() -> bool:
    """Dev/test escape hatch: signup without an invite. Never set in production."""
    return os.environ.get("QUALIFY_SIGNUP_OPEN", "") == "1"


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


def _clean(text: str | None, limit: int) -> str:
    """Collapse surrounding whitespace; refuse rather than silently truncate."""
    cleaned = (text or "").strip()
    if len(cleaned) > limit:
        raise SignupNotAllowed(f"El texto es demasiado largo (máximo {limit} caracteres).")
    return cleaned


def create_invite(
    email: str,
    *,
    days: int = DEFAULT_INVITE_DAYS,
    invited_by: str | None = None,
    recipient_name: str | None = None,
    business_name: str | None = None,
    note: str | None = None,
    meegle_work_item_id: int | None = None,
) -> CreatedInvite:
    """Store a new invite for `email` (literal, like every login email — the `+alias`
    is the business). Earlier unused invites for the same email stay valid.
    `meegle_work_item_id` links it to the "Alta de cliente" item that asked for it."""
    email = email.strip()
    if not _valid_email(email):
        raise SignupNotAllowed("El email no es válido.")
    if days < 1:
        raise SignupNotAllowed("La invitación debe durar al menos un día.")
    recipient_name = _clean(recipient_name, _NAME_MAX)
    business_name = _clean(business_name, _NAME_MAX)
    note = _clean(note, _NOTE_MAX)
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(days=days)
    invite_id = uuid4()
    with admin_session() as session:
        session.add(
            SignupInvite(
                id=invite_id,
                email=email,
                token_hash=_hash(token),
                invited_by=invited_by,
                recipient_name=recipient_name or None,
                business_name=business_name or None,
                note=note or None,
                expires_at=expires_at,
                meegle_work_item_id=meegle_work_item_id,
            )
        )
    return CreatedInvite(
        email=email,
        token=token,
        expires_at=expires_at,
        recipient_name=recipient_name,
        business_name=business_name,
        note=note,
        id=invite_id,
    )


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
        return InviteView(
            id=invite.id,
            email=invite.email,
            expires_at=invite.expires_at,
            business_name=invite.business_name or "",
        )


def authorize_signup(email: str, invite_token: str | None) -> UUID | None:
    """Decide whether this signup may proceed. Returns the invite id to consume (None
    only when `QUALIFY_SIGNUP_OPEN=1` lets an uninvited signup through). Raises
    `SignupNotAllowed`."""
    if invite_token:
        invite = lookup_invite(invite_token)
        if invite is None:
            raise SignupNotAllowed(_INVITE_DEAD)
        if not _same_email(invite.email, email):
            raise SignupNotAllowed(
                f"Esta invitación es para {invite.email}. Regístrate con ese correo."
            )
        return invite.id
    if signup_open():
        return None
    raise SignupNotAllowed(_INVITE_ONLY)


def _same_email(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def lock_invite(session: Session, invite_id: UUID, email: str) -> SignupInvite:
    """Take the invite's row lock and re-check it, inside the transaction that will
    create the business and BEFORE the identity user exists. A second, concurrent
    signup with the same link waits here and then fails: it never reaches the provider."""
    invite = session.scalar(
        select(SignupInvite).where(SignupInvite.id == invite_id).with_for_update()
    )
    if not _usable(invite) or invite is None or not _same_email(invite.email, email):
        raise SignupNotAllowed(_INVITE_DEAD)
    return invite


def mark_invite_used(session: Session, invite: SignupInvite) -> None:
    """Spend a locked invite — called once the business really exists."""
    invite.used_at = _now()
    session.flush()


def consume_invite(session: Session, invite_id: UUID, email: str) -> None:
    """`lock_invite` + `mark_invite_used` in one step, for callers with nothing to do in
    between."""
    mark_invite_used(session, lock_invite(session, invite_id, email))


def expire_invites_for_work_item(work_item_id: int) -> int:
    """Expire now every unused, unexpired invite created from that Meegle item (the item
    was terminated). Returns how many were expired; idempotent."""
    now = _now()
    with admin_session() as session:
        return session.execute(
            update(SignupInvite)
            .where(
                SignupInvite.meegle_work_item_id == work_item_id,
                SignupInvite.used_at.is_(None),
                SignupInvite.expires_at > now,
            )
            .values(expires_at=now)
        ).rowcount


def send_invite_email(
    mailer: Mailer,
    invite: CreatedInvite,
    base_url: str,
    *,
    signer: str = "",
    can_reply: bool = False,
) -> str | None:
    """Send the invitation. Returns the provider's email id (Resend's `id`) and stores it
    on the invite row when both exist, so a delivery webhook can be matched later (M2)."""
    email_id = mailer.send(invite_email(invite, base_url, signer=signer, can_reply=can_reply))
    if email_id and invite.id is not None:
        with admin_session() as session:
            session.execute(
                update(SignupInvite)
                .where(SignupInvite.id == invite.id)
                .values(resend_email_id=email_id)
            )
    return email_id
