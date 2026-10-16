"""Transactional email (2026-10-07): Qualify's own messages, sent through Resend.

Buy, don't build: Resend's free tier (3,000/month, 100/day) covers invitations, and the
same account doubles as Supabase Auth's custom SMTP for recovery emails. House style for
external APIs — a thin typed client over httpx, no SDK.

Configuration, read from the environment:

    QUALIFY_RESEND_API_KEY   the Resend API key (secret)
    QUALIFY_MAIL_FROM        sender, e.g. "Herwin de Qualify <no-reply@send.qualify.la>"
    QUALIFY_MAIL_REPLY_TO    optional: where replies go (a mailbox a person reads)
    QUALIFY_MAIL_FAKE=1      dev/test: log the message instead of sending it

An unconfigured environment raises `MailNotConfigured` at send time — loud, never a silent
drop. Callers that can degrade (the invite CLI prints the link anyway) catch it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT_SECONDS = 15.0


class MailNotConfigured(RuntimeError):
    """No sender configured (missing API key or From address)."""


class MailError(RuntimeError):
    """The provider refused or could not be reached."""


@dataclass(frozen=True)
class OutgoingMail:
    to: str
    subject: str
    html: str
    text: str


class Mailer(Protocol):
    def send(self, mail: OutgoingMail) -> None: ...


class ResendMailer:
    def __init__(self, api_key: str, sender: str, reply_to: str = "") -> None:
        self._api_key = api_key
        self._sender = sender
        self._reply_to = reply_to

    def send(self, mail: OutgoingMail) -> None:
        payload: dict = {
            "from": self._sender,
            "to": [mail.to],
            "subject": mail.subject,
            "html": mail.html,
            "text": mail.text,
        }
        if self._reply_to:
            payload["reply_to"] = self._reply_to
        try:
            response = httpx.post(
                _RESEND_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            logger.error("resend transport failure: %s", type(exc).__name__)
            raise MailError("could not reach the mail provider") from exc
        if response.status_code not in (200, 201, 202):
            # The body names the cause (unverified domain, bad key, quota); it carries
            # no secret, and without it a 4xx is undebuggable.
            logger.error("resend answered %s: %s", response.status_code, response.text[:300])
            raise MailError(f"mail provider answered {response.status_code}")


class FakeMailer:
    """Records and logs instead of sending (`QUALIFY_MAIL_FAKE=1`, and tests)."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMail] = []

    def send(self, mail: OutgoingMail) -> None:
        self.sent.append(mail)
        logger.warning("fake mail to %s: %s\n%s", mail.to, mail.subject, mail.text)


_mailer: Mailer | None = None


def mail_reply_to() -> str:
    """The Reply-To address, if any — templates only promise "reply to this email"
    when a person actually reads where replies go."""
    return os.environ.get("QUALIFY_MAIL_REPLY_TO", "").strip()


def default_mailer() -> Mailer:
    global _mailer
    if _mailer is None:
        if os.environ.get("QUALIFY_MAIL_FAKE", "") == "1":
            _mailer = FakeMailer()
        else:
            api_key = os.environ.get("QUALIFY_RESEND_API_KEY", "")
            sender = os.environ.get("QUALIFY_MAIL_FROM", "")
            if not api_key or not sender:
                raise MailNotConfigured("QUALIFY_RESEND_API_KEY / QUALIFY_MAIL_FROM are not set")
            _mailer = ResendMailer(api_key, sender, mail_reply_to())
    return _mailer


def reset_default_mailer() -> None:
    """Test hook: forget the singleton so env changes take effect."""
    global _mailer
    _mailer = None


__all__ = [
    "FakeMailer",
    "MailError",
    "MailNotConfigured",
    "Mailer",
    "OutgoingMail",
    "ResendMailer",
    "default_mailer",
    "mail_reply_to",
    "reset_default_mailer",
]
