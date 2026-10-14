"""Support requests — "Pedir ayuda 1:1" (QUA-202).

A non-technical operator who cannot get an account connected asks a person for help from
inside the screen, instead of giving up or writing to a mailbox nobody watches. The
request is a row the tenant owns (`support_requests`, standard RLS) plus a best-effort
notification to the global sales/support channel (a webhook — Lark, Slack and Cliq all
accept the payload `notify.py` sends). Saving never depends on the notification: a ticket
without a channel is still a ticket, and the UI tells the operator which of the two
happened.
"""

from __future__ import annotations

from .notify import (
    NullSupportNotifier,
    SupportNotification,
    SupportNotifier,
    WebhookSupportNotifier,
    production_support_notifier,
)
from .service import (
    TOPICS,
    InvalidSupportRequest,
    SupportTicket,
    create_support_request,
)

__all__ = [
    "TOPICS",
    "InvalidSupportRequest",
    "NullSupportNotifier",
    "SupportNotification",
    "SupportNotifier",
    "SupportTicket",
    "WebhookSupportNotifier",
    "create_support_request",
    "production_support_notifier",
]
