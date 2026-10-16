"""The seam between `/whatsapp` → Contactos (WA-19, QUA-218) and the real backend.

Writes go through `qualify_api.whatsapp.optins.OptInService` (the monotonic consent rule
lives there, not here). The list reads `whatsapp_opt_ins` directly through
`tenant_session(tenant_id)` — the only sanctioned door, RLS-scoped — because the service
only lists ACTIVE opt-ins and the screen also shows who revoked (and when). No Graph call
in this tab.

Opt-ins are tenant-wide (one row per `(tenant_id, phone_e164)`), not per number: the
same list shows under every number of the tenant. Blocking functions — callers on the
event loop run them off-thread.
"""

from __future__ import annotations

from uuid import UUID

from qualify_api.leads.models import LeadFormSettings
from qualify_api.tenancy.models import Brand
from qualify_api.whatsapp.models import WhatsAppOptIn
from qualify_api.whatsapp.optins import (
    SOURCE_MANUAL,
    ImportReport,
    OptInService,
    PostgresOptInRepository,
    RecordResult,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .whatsapp_contacts_vm import OptInVM, build_opt_in_vm

MAX_LISTED = 500


def production_opt_in_service() -> OptInService:
    return OptInService(PostgresOptInRepository())


def list_opt_ins(tenant_id: UUID, *, include_revoked: bool) -> list[OptInVM]:
    """Newest capture first, at most `MAX_LISTED` rows."""
    with tenant_session(tenant_id) as session:
        query = (
            select(WhatsAppOptIn, Brand.name)
            .outerjoin(Brand, WhatsAppOptIn.brand_id == Brand.id)
            .order_by(WhatsAppOptIn.captured_at.desc(), WhatsAppOptIn.id)
            .limit(MAX_LISTED)
        )
        if not include_revoked:
            query = query.where(WhatsAppOptIn.revoked_at.is_(None))
        rows = session.execute(query).all()
        return [
            build_opt_in_vm(
                phone_e164=row.phone_e164,
                source=row.source,
                captured_at=row.captured_at,
                revoked_at=row.revoked_at,
                revoke_reason=row.revoke_reason,
                consent_text=row.consent_text,
                brand=brand_name,
            )
            for row, brand_name in rows
        ]


def lead_form_consent_text(tenant_id: UUID) -> str:
    """The lead form's CURRENT consent text ("" when the tenant has no form) — shown in
    the import confirmation so the operator checks the condition against the real text."""
    with tenant_session(tenant_id) as session:
        text = session.scalar(select(LeadFormSettings.consent_text))
    return text or ""


def record_manual(
    tenant_id: UUID,
    phone: str,
    consent_text: str,
    *,
    service: OptInService | None = None,
) -> RecordResult:
    """Raises `ValueError` for a phone that is not E.164 or a blank consent text."""
    svc = service or production_opt_in_service()
    return svc.record(
        tenant_id=tenant_id,
        phone=phone,
        source=SOURCE_MANUAL,
        consent_text=consent_text.strip(),
        proof={"captured_via": "qualify_ui_manual"},
    )


def revoke(tenant_id: UUID, phone: str, *, service: OptInService | None = None) -> bool:
    svc = service or production_opt_in_service()
    return svc.revoke(tenant_id=tenant_id, phone=phone)


def import_from_leads(tenant_id: UUID, *, service: OptInService | None = None) -> ImportReport:
    svc = service or production_opt_in_service()
    return svc.import_from_leads(tenant_id=tenant_id)
