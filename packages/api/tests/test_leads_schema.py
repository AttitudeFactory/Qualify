"""`db`-marked tests for migration 0005: RLS isolation of the two leads tables and the
Postgres upsert semantics the memory double mirrors. Same discipline as
`test_tenant_isolation` — assertions run as `qualify_app`, subject to RLS."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.leads.composition import upsert_form_settings
from qualify_api.leads.models import Lead, LeadFormSettings
from qualify_api.leads.repository import LeadRecord, PostgresLeadRepository

pytestmark = pytest.mark.db

PHONE = "+573009990011"


@pytest.fixture
def provisioned_a(seeded_ab: tuple[UUID, UUID]) -> tuple[UUID, UUID]:
    tenant_a, tenant_b = seeded_ab
    # Idempotent (ON CONFLICT on the per-tenant unique), so `just test-db` re-runs clean.
    upsert_form_settings(
        tenant_id=tenant_a,
        business_name="negocio-A",
        whatsapp_phone="+573001112233",
        consent_text="Acepto.",
        consent_policy_version="v1",
        promo_text="promo-A",
        interest_options=["x", "y"],
        custom_fields=[{"key": "zona", "label": "Zona"}],
    )
    return tenant_a, tenant_b


def test_settings_do_not_leak_across_tenants(provisioned_a: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = provisioned_a
    repo = PostgresLeadRepository()
    assert repo.get_active_settings(tenant_id=tenant_a) is not None
    # The read that matters: B's scope sees zero rows, same as a tenant that never
    # provisioned — which is exactly what makes the public 404 non-enumerating.
    assert repo.get_active_settings(tenant_id=tenant_b) is None


def test_inactive_form_reads_as_absent(provisioned_a: tuple[UUID, UUID]) -> None:
    tenant_a, _ = provisioned_a
    repo = PostgresLeadRepository()
    try:
        upsert_form_settings(
            tenant_id=tenant_a,
            business_name="negocio-A",
            whatsapp_phone="+573001112233",
            consent_text="Acepto.",
            consent_policy_version="v1",
            active=False,
        )
        assert repo.get_active_settings(tenant_id=tenant_a) is None
    finally:
        upsert_form_settings(
            tenant_id=tenant_a,
            business_name="negocio-A",
            whatsapp_phone="+573001112233",
            consent_text="Acepto.",
            consent_policy_version="v1",
            promo_text="promo-A",
            interest_options=["x", "y"],
            custom_fields=[{"key": "zona", "label": "Zona"}],
        )


def _record(**overrides: object) -> LeadRecord:
    base: dict = {
        "full_name": "Ana",
        "whatsapp_phone": PHONE,
        "consent_at": datetime.now(UTC),
        "consent_policy_version": "v1",
    }
    base.update(overrides)
    return LeadRecord(**base)


def test_upsert_is_idempotent_and_merges_optionals(provisioned_a: tuple[UUID, UUID]) -> None:
    tenant_a, _ = provisioned_a
    repo = PostgresLeadRepository()
    first = repo.upsert_lead(
        tenant_id=tenant_a, record=_record(email="ana@x.co", extra={"zona": "oeste"})
    )
    second = repo.upsert_lead(
        tenant_id=tenant_a,
        record=_record(full_name="Ana María", interest="arepas", extra={"turno": "tarde"}),
    )
    assert first == second  # one person, one row
    with tenant_session(tenant_a) as session:
        row = session.scalar(select(Lead).where(Lead.whatsapp_phone == PHONE))
        assert row is not None
        assert row.full_name == "Ana María"  # identity overwrites
        assert row.email == "ana@x.co"  # omitted optional survives the second submit
        assert row.interest == "arepas"
        assert row.extra == {"zona": "oeste", "turno": "tarde"}  # jsonb merge, not replace


def test_leads_do_not_leak_across_tenants(provisioned_a: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = provisioned_a
    repo = PostgresLeadRepository()
    repo.upsert_lead(tenant_id=tenant_a, record=_record())
    with tenant_session(tenant_b) as session:
        # No explicit WHERE — RLS is the only thing scoping this.
        assert session.scalars(select(Lead)).all() == []
        assert session.scalars(select(LeadFormSettings)).all() == []


def test_cross_tenant_write_is_rejected_by_with_check(
    provisioned_a: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = provisioned_a
    with pytest.raises(Exception, match="row-level security"):
        with tenant_session(tenant_a) as session:
            session.add(
                Lead(
                    tenant_id=tenant_b,  # scoped as A, writing B — WITH CHECK must veto
                    full_name="Mallory",
                    whatsapp_phone="+573000000001",
                    consent_at=datetime.now(UTC),
                    consent_policy_version="v1",
                )
            )
            session.flush()
