"""Where a support request goes after it is saved (QUA-202).

One notifier, one webhook. The payload carries BOTH `text` (Slack / Zoho Cliq incoming
webhooks) and `msg_type` + `content.text` (Lark custom bots), so the same env var works
for whichever channel the team is on — Qualify is moving from Cliq to Lark (2026-10-12)
and this must not care. Nothing credential-adjacent is ever in the message: a business
name, a contact email, a topic, an outcome code and two counts.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from qualify_api.support.webhook import TextWebhook

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupportNotification:
    """What the channel is told. `reference` is the short id the operator also sees, so
    the person who picks it up and the person who asked talk about the same ticket."""

    reference: str
    business_name: str
    contact_email: str
    contact_whatsapp: str
    topic: str
    message: str
    context: dict[str, Any]

    def as_text(self) -> str:
        lines = [
            f"🆘 Nueva solicitud de ayuda 1:1 · #{self.reference}",
            f"Negocio: {self.business_name}",
            f"Correo: {self.contact_email}",
        ]
        if self.contact_whatsapp:
            lines.append(f"WhatsApp: {self.contact_whatsapp}")
        lines.append(f"Tema: {self.topic}")
        if self.context:
            detail = ", ".join(f"{key}={value}" for key, value in sorted(self.context.items()))
            lines.append(f"Contexto: {detail}")
        if self.message:
            lines.append(f"Mensaje: {self.message}")
        return "\n".join(lines)


class SupportNotifier(Protocol):
    def notify(self, notification: SupportNotification) -> bool:
        """True when the channel accepted it. Never raises: a channel that is down must
        not turn a saved ticket into an error on the operator's screen."""
        ...


class NullSupportNotifier:
    """No channel configured. The ticket is saved; the UI says so honestly."""

    def notify(self, notification: SupportNotification) -> bool:
        _LOGGER.warning(
            "support request #%s saved but no channel is configured "
            "(set QUALIFY_SUPPORT_WEBHOOK_URL)",
            notification.reference,
        )
        return False


class WebhookSupportNotifier:
    def __init__(
        self,
        url: str,
        *,
        secret: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._webhook = TextWebhook(url, secret=secret, transport=transport)

    def notify(self, notification: SupportNotification) -> bool:
        return self._webhook.send(notification.as_text())


def production_support_notifier() -> SupportNotifier:
    url = os.environ.get("QUALIFY_SUPPORT_WEBHOOK_URL", "").strip()
    secret = os.environ.get("QUALIFY_SUPPORT_WEBHOOK_SECRET", "").strip()
    return WebhookSupportNotifier(url, secret=secret) if url else NullSupportNotifier()
