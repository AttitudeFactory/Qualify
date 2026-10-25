"""«Pedir más a Qualify» (m-24852129): the owner's one way to get more creations, videos
or vistas previas — a `more_creations` support request a person answers (never
automatic), with what ran out, the plan in force and how to reach the owner.

Request path only (`tenant_session`): it reads the business's plan projection, its
WhatsApp number and its own requests; it never sees a price or creates a unit.

- **Contact:** the business's connected WhatsApp number when it has one, else only the
  account's email (D13). The screen tells the owner which one the team will use.
- **Once:** a request still open this month (business's zone) that no pack or plan
  change has answered yet is «Pedido enviado»: a second tap creates nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qualify_api.plans.models import BusinessPlan, CreationPack
from qualify_api.plans.read import plan_in_session
from qualify_api.support.models import SupportRequest
from qualify_api.support.notify import SupportNotifier
from qualify_api.support.service import SupportTicket, create_support_request
from qualify_api.tenancy.models import Tenant
from qualify_api.whatsapp.models import WhatsAppPhoneNumber

TOPIC = "more_creations"

#: What ran out, as the team reads it in the request (`context.exhausted`).
EXHAUSTED_LABELS: dict[str, str] = {
    "creations": "creaciones",
    "videos": "videos",
    "previews": "vistas previas",
    "settings": "desde Configuración",
}


class InvalidAskMore(ValueError):
    pass


@dataclass(frozen=True)
class AskMoreResult:
    #: True when the team will write by WhatsApp; False = to the account's email.
    by_whatsapp: bool
    #: False when an open request already existed: nothing new was created.
    created: bool
    ticket: SupportTicket | None = None


def _local(now: datetime, zone: str) -> datetime:
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return now.astimezone(tz)


def _month_start_utc(now: datetime, zone: str) -> datetime:
    """The instant the business's current month began, in UTC."""
    local = _local(now, zone)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _local_month(now: datetime, zone: str) -> date:
    """The first day of the business's current month (the ledger's `period`)."""
    local = _local(now, zone)
    return date(local.year, local.month, 1)


def _zone(session: Session, tenant_id: UUID) -> str:
    zone = session.scalar(select(Tenant.timezone).where(Tenant.id == tenant_id))
    return zone or "UTC"


def business_whatsapp(session: Session, tenant_id: UUID) -> str:
    """The business's connected WhatsApp number ("" when it has none)."""
    number = session.scalar(
        select(WhatsAppPhoneNumber.display_phone_number)
        .where(WhatsAppPhoneNumber.tenant_id == tenant_id)
        .order_by(WhatsAppPhoneNumber.created_at)
        .limit(1)
    )
    return (number or "").strip()


def pending_in_session(session: Session, tenant_id: UUID, now: datetime) -> bool:
    """An open «Pedir más» of this month that no pack or plan change answered since."""
    since = _month_start_utc(now, _zone(session, tenant_id))
    answered = [
        session.scalar(
            select(func.max(CreationPack.granted_at)).where(CreationPack.tenant_id == tenant_id)
        ),
        session.scalar(select(BusinessPlan.updated_at).where(BusinessPlan.tenant_id == tenant_id)),
    ]
    for moment in answered:
        if moment is not None and moment > since:
            since = moment
    found = session.scalar(
        select(SupportRequest.id)
        .where(
            SupportRequest.tenant_id == tenant_id,
            SupportRequest.topic == TOPIC,
            SupportRequest.status.in_(("open", "contacted")),
            SupportRequest.created_at > since,
        )
        .limit(1)
    )
    return found is not None


@dataclass(frozen=True)
class AskMoreStatus:
    pending: bool
    by_whatsapp: bool


def ask_more_status(tenant_id: UUID, now: datetime | None = None) -> AskMoreStatus:
    """Whether the button already reads «Pedido enviado», and which contact the team
    would use (blocking: off the event loop)."""
    with tenant_session(tenant_id) as session:
        return AskMoreStatus(
            pending=pending_in_session(session, tenant_id, now or datetime.now(UTC)),
            by_whatsapp=bool(business_whatsapp(session, tenant_id)),
        )


def request_more(
    tenant_id: UUID,
    *,
    email: str,
    exhausted: str,
    now: datetime | None = None,
    notifier: SupportNotifier | None = None,
) -> AskMoreResult:
    """Save the «Pedir más» request and tell the team channel — unless one is already
    waiting this month. Raises `InvalidAskMore` for an unknown `exhausted`."""
    if exhausted not in EXHAUSTED_LABELS:
        raise InvalidAskMore(f"exhausted must be one of {tuple(EXHAUSTED_LABELS)}")
    moment = now or datetime.now(UTC)
    with tenant_session(tenant_id) as session:
        whatsapp = business_whatsapp(session, tenant_id)
        if pending_in_session(session, tenant_id, moment):
            return AskMoreResult(by_whatsapp=bool(whatsapp), created=False)
        period = _local_month(moment, _zone(session, tenant_id))
        plan = plan_in_session(session, tenant_id, period)
    ticket = create_support_request(
        tenant_id=tenant_id,
        topic=TOPIC,
        contact_email=email,
        contact_whatsapp=whatsapp,
        context={
            "screen": "settings" if exhausted == "settings" else "crear",
            "plan": plan.code,
            "exhausted": EXHAUSTED_LABELS[exhausted],
        },
        notifier=notifier,
    )
    return AskMoreResult(by_whatsapp=bool(whatsapp), created=True, ticket=ticket)


__all__ = [
    "EXHAUSTED_LABELS",
    "TOPIC",
    "AskMoreResult",
    "AskMoreStatus",
    "InvalidAskMore",
    "ask_more_status",
    "business_whatsapp",
    "pending_in_session",
    "request_more",
]
