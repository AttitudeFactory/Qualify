"""Wiring for the leads module — same shape as `connections.composition`.

`production_leads_service` is what the HTTP layer binds to. `upsert_form_settings` is
the published provisioning seam for the operator (Reflex UI or a REPL): it writes
through `tenant_session`, so RLS's WITH CHECK — not this function — is what stops a
settings row being written into someone else's tenant.
"""

from __future__ import annotations

from functools import cache
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from qualify_api.config import redis_url
from qualify_api.leads.models import LeadFormSettings
from qualify_api.leads.rate_limit import RedisFixedWindowLimiter
from qualify_api.leads.repository import PostgresLeadRepository, normalize_phone
from qualify_api.leads.service import LeadIntakeService

# Per (tenant, client-ip) per minute. Bounds junk-row volume, not a billing quota, so
# the number only needs to be generous for a human and stingy for a loop.
_INTAKE_LIMIT = 8
_INTAKE_WINDOW_SECONDS = 60


@cache
def production_leads_service() -> LeadIntakeService:
    """Cached for the same reason as `production_connect_service`: FastAPI resolves the
    dependency per request, and each fresh limiter would mean a fresh Redis pool.
    `redis` is imported inside so importing this module never requires a Redis."""
    import redis

    return LeadIntakeService(
        repository=PostgresLeadRepository(),
        limiter=RedisFixedWindowLimiter(
            redis.Redis.from_url(redis_url(), decode_responses=True),
            limit=_INTAKE_LIMIT,
            window_seconds=_INTAKE_WINDOW_SECONDS,
        ),
    )


def upsert_form_settings(
    *,
    tenant_id: UUID,
    business_name: str,
    whatsapp_phone: str,
    consent_text: str,
    consent_policy_version: str,
    whatsapp_greeting: str | None = None,
    promo_text: str | None = None,
    interest_options: list[str] | None = None,
    custom_fields: list[dict] | None = None,
    active: bool = True,
) -> UUID:
    """Create or update the tenant's single public form. Idempotent on the
    `uq_lead_form_settings_tenant` constraint. Keyword-only: too many same-typed
    strings in a row for positional calls to be safe."""
    stmt = insert(LeadFormSettings).values(
        tenant_id=tenant_id,
        business_name=business_name,
        whatsapp_phone=normalize_phone(whatsapp_phone),
        whatsapp_greeting=whatsapp_greeting,
        promo_text=promo_text,
        interest_options=interest_options or [],
        consent_text=consent_text,
        consent_policy_version=consent_policy_version,
        custom_fields=custom_fields or [],
        active=active,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_lead_form_settings_tenant",
        set_={
            "business_name": stmt.excluded.business_name,
            "whatsapp_phone": stmt.excluded.whatsapp_phone,
            "whatsapp_greeting": stmt.excluded.whatsapp_greeting,
            "promo_text": stmt.excluded.promo_text,
            "interest_options": stmt.excluded.interest_options,
            "consent_text": stmt.excluded.consent_text,
            "consent_policy_version": stmt.excluded.consent_policy_version,
            "custom_fields": stmt.excluded.custom_fields,
            "active": stmt.excluded.active,
            "updated_at": func.now(),
        },
    ).returning(LeadFormSettings.id)
    with tenant_session(tenant_id) as session:
        return session.execute(stmt).scalar_one()
