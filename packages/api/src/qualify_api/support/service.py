"""Create a support request for a tenant (QUA-202).

Order of operations, and why: the row is committed FIRST, through `tenant_session` (RLS
scopes it to the tenant even though nothing here says `WHERE tenant_id`); only then is the
channel told. A channel that is down loses nothing — the ticket exists, `notified_at`
stays NULL, and the operator's screen says "quedó registrada" instead of promising a
callback. The reverse order would let a webhook hiccup swallow a real cry for help.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.support.models import SupportRequest
from qualify_api.support.notify import (
    SupportNotification,
    SupportNotifier,
    production_support_notifier,
)
from qualify_api.tenancy.models import Tenant, User

TOPICS = ("connect_accounts", "other")
_MAX_MESSAGE = 2000
_MAX_CONTACT = 120
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# What `context` may carry: the outcome code and the two R9(e.1) counts. A closed list,
# so nothing a future caller is tempted to add (a Page id, a username) gets there by
# accident — the notification prints every key it receives.
CONTEXT_KEYS = frozenset({"outcome", "pages", "linked", "screen"})


class InvalidSupportRequest(ValueError):
    """The operator's input cannot become a ticket (bad email, unknown topic...)."""


@dataclass(frozen=True)
class SupportTicket:
    id: UUID
    reference: str  # the short form the operator sees: "#A1B2C3"
    notified: bool  # whether the global channel accepted it


def _reference(ticket_id: UUID) -> str:
    return ticket_id.hex[:6].upper()


def _clean(
    *, topic: str, contact_email: str, contact_whatsapp: str, message: str, context: dict
) -> tuple[str, str, str, str, dict[str, Any]]:
    if topic not in TOPICS:
        raise InvalidSupportRequest(f"topic must be one of {TOPICS}")
    email = contact_email.strip()
    if not email or len(email) > _MAX_CONTACT or not _EMAIL.match(email):
        raise InvalidSupportRequest("a valid contact email is required")
    whatsapp = contact_whatsapp.strip()[:_MAX_CONTACT]
    text = message.strip()[:_MAX_MESSAGE]
    unexpected = set(context) - CONTEXT_KEYS
    if unexpected:
        raise InvalidSupportRequest(f"context carries keys it must not: {sorted(unexpected)}")
    safe_context = {key: value for key, value in context.items() if isinstance(value, str | int)}
    return topic, email, whatsapp, text, safe_context


def create_support_request(
    *,
    tenant_id: UUID,
    topic: str,
    contact_email: str,
    contact_whatsapp: str = "",
    message: str = "",
    context: dict[str, Any] | None = None,
    notifier: SupportNotifier | None = None,
) -> SupportTicket:
    """Save the request, then tell the channel. Blocking (Postgres + one HTTP call) —
    call it off the event loop. Raises `InvalidSupportRequest` before writing anything."""
    topic, email, whatsapp, text, safe_context = _clean(
        topic=topic,
        contact_email=contact_email,
        contact_whatsapp=contact_whatsapp,
        message=message,
        context=context or {},
    )
    with tenant_session(tenant_id) as session:
        business_name = session.scalar(select(Tenant.name).where(Tenant.id == tenant_id)) or ""
        # The row is attributed to the tenant's user with that email when there is one;
        # a request typed with another address is still saved, just unattributed.
        user_id = session.scalar(select(User.id).where(User.email == email))
        row = SupportRequest(
            tenant_id=tenant_id,
            requested_by_user_id=user_id,
            topic=topic,
            contact_email=email,
            contact_whatsapp=whatsapp,
            message=text,
            context=safe_context,
        )
        session.add(row)
        session.flush()
        ticket_id = row.id
        session.commit()

    reference = _reference(ticket_id)
    accepted = (notifier or production_support_notifier()).notify(
        SupportNotification(
            reference=reference,
            business_name=business_name,
            contact_email=email,
            contact_whatsapp=whatsapp,
            topic=topic,
            message=text,
            context=safe_context,
        )
    )
    if accepted:
        with tenant_session(tenant_id) as session:
            saved = session.get(SupportRequest, ticket_id)
            if saved is not None:
                saved.notified_at = datetime.now(UTC)
                session.commit()
    return SupportTicket(id=ticket_id, reference=reference, notified=accepted)
