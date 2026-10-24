"""Read/write seam between the leads plane and the Reflex UI.

Same discipline as `connections_provider`: the UI never touches ORM rows — `LeadVM` is
a whitelist of plain strings, because every Reflex var is serialized to the browser.
Every access goes through `tenant_session` (RLS-scoped); blocking, so the state calls
this off the event loop. Words and links come from the pure `leads_vm`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.leads.models import Lead, LeadFormSettings
from qualify_api.tenancy.models import Tenant
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .leads_vm import (
    contact_label,
    contact_tone,
    contacted_note,
    extra_summary,
    form_url,
    question_labels,
    registered_label,
    wa_href,
    zone_for,
)

# One screen of recent leads. Pagination arrives when a real tenant outgrows this.
_PAGE_SIZE = 200

#: m-24842992: the public form's address, `{tenant_id}` replaced per business. Unset →
#: the empty state gives no link (there is no page in this repo that renders the form).
LEAD_FORM_URL_ENV = "QUALIFY_LEAD_FORM_URL"


@dataclass(frozen=True)
class LeadVM:
    id: str
    full_name: str
    whatsapp_phone: str
    wa_href: str  # wa.me needs the number without the leading '+'
    interest: str  # "" when not given
    source: str  # declared source, falling back to utm_source
    extra_summary: str  # "zona: oeste · turno: tarde"
    registered_at: str  # «Te dejó sus datos el 14 ago.»
    contacted: bool
    status_label: str  # «Pendiente» / «Ya le escribiste»
    status_tone: str  # warn / ok
    contacted_note: str  # «Le escribiste el 23 oct.» or ""


@dataclass(frozen=True)
class LeadsScreen:
    leads: list[LeadVM]
    form_link: str  # "" when there is no form to share


def _lead_vm(row: Lead, zone_name: str, labels: dict[str, str] | None = None) -> LeadVM:
    zone = zone_for(zone_name)
    return LeadVM(
        id=str(row.id),
        full_name=row.full_name,
        whatsapp_phone=row.whatsapp_phone,
        wa_href=wa_href(row.whatsapp_phone),
        interest=row.interest or "",
        source=row.source_declared or row.utm_source or "",
        extra_summary=extra_summary(row.extra or {}, labels),
        registered_at=registered_label(row.created_at, zone),
        contacted=row.contacted_at is not None,
        status_label=contact_label(row.contacted_at),
        status_tone=contact_tone(row.contacted_at),
        contacted_note=contacted_note(row.contacted_at, zone),
    )


def _zone_name(session: Session, tenant_id: UUID) -> str:
    return session.scalar(select(Tenant.timezone).where(Tenant.id == tenant_id)) or "UTC"


def _active_form(session: Session) -> LeadFormSettings | None:
    return session.scalar(select(LeadFormSettings).where(LeadFormSettings.active.is_(True)))


def _labels(form: LeadFormSettings | None) -> dict[str, str]:
    return question_labels(form.custom_fields if form is not None else None)


def leads_screen_for(tenant_id: UUID) -> LeadsScreen:
    """The tenant's latest leads — the ones still waiting for a message first, newest
    first within each group — plus the form link for the empty state. The order is only
    applied on load, so a card never jumps while the owner taps it.
    Hits Postgres — call off-thread."""
    with tenant_session(tenant_id) as session:
        zone_name = _zone_name(session, tenant_id)
        rows = session.scalars(
            select(Lead)
            .order_by(Lead.contacted_at.is_not(None), Lead.created_at.desc())
            .limit(_PAGE_SIZE)
        ).all()
        form = _active_form(session)
        labels = _labels(form)
        leads = [_lead_vm(row, zone_name, labels) for row in rows]
    link = form_url(
        os.environ.get(LEAD_FORM_URL_ENV, ""), str(tenant_id), form_active=form is not None
    )
    return LeadsScreen(leads=leads, form_link=link)


def set_contacted(tenant_id: UUID, lead_id: UUID, *, contacted: bool) -> LeadVM | None:
    """Mark (or unmark) «Ya le escribiste». Marking twice keeps the first date: the
    owner wrote on that day. Returns the refreshed card, None when the lead is not this
    tenant's (RLS hides it). Hits Postgres — call off-thread."""
    with tenant_session(tenant_id) as session:
        stmt = update(Lead).where(Lead.id == lead_id)
        if contacted:
            stmt = stmt.where(Lead.contacted_at.is_(None)).values(
                contacted_at=datetime.now(UTC), updated_at=datetime.now(UTC)
            )
        else:
            stmt = stmt.values(contacted_at=None, updated_at=datetime.now(UTC))
        session.execute(stmt)
        row = session.scalar(select(Lead).where(Lead.id == lead_id))
        if row is None:
            return None
        return _lead_vm(row, _zone_name(session, tenant_id), _labels(_active_form(session)))
