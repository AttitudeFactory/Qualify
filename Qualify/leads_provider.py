"""Read seam between the leads plane and the Reflex UI.

Same discipline as `connections_provider`: the UI never touches ORM rows — `LeadVM` is
a whitelist of plain strings, because every Reflex var is serialized to the browser.
Reads go through `tenant_session` (RLS-scoped); blocking, so the state calls this off
the event loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_api.leads.models import Lead
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

# One screen of recent leads. Pagination arrives when a real tenant outgrows this.
_PAGE_SIZE = 200


@dataclass(frozen=True)
class LeadVM:
    id: str
    full_name: str
    whatsapp_phone: str
    wa_href: str  # wa.me needs the number without the leading '+'
    interest: str  # "" when not given
    source: str  # declared source, falling back to utm_source
    extra_summary: str  # "zona: oeste · turno: tarde"
    registered_at: str  # "2026-08-14 18:03"


def leads_for(tenant_id: UUID) -> list[LeadVM]:
    """The tenant's latest leads, newest first. Hits Postgres — call off-thread."""
    with tenant_session(tenant_id) as session:
        rows = session.scalars(
            select(Lead).order_by(Lead.created_at.desc()).limit(_PAGE_SIZE)
        ).all()
        return [
            LeadVM(
                id=str(row.id),
                full_name=row.full_name,
                whatsapp_phone=row.whatsapp_phone,
                wa_href=f"https://wa.me/{row.whatsapp_phone.lstrip('+')}",
                interest=row.interest or "",
                source=row.source_declared or row.utm_source or "",
                extra_summary=" · ".join(f"{k}: {v}" for k, v in sorted(row.extra.items())),
                registered_at=row.created_at.strftime("%Y-%m-%d %H:%M"),
            )
            for row in rows
        ]
