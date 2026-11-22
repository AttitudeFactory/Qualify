"""DB: the investment profile (0176) — upsert, idempotent re-save, provenance, RLS."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.investment_profile import (
    BRAND_GONE,
    InvestmentProfileUnavailable,
    default_currency,
    load_investment_profile,
    save_investment_profile,
)
from qualify_api.tenancy.acting import acting_login
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db

ANSWERS = {
    "average_ticket_minor": 2_500_000,
    "margin_percent": "35,5",
    "weekly_new_clients": 20,
    "monthly_cap_minor": 50_000_000,
    "objective": "messages",
}


def _business() -> tuple[UUID, UUID, UUID]:
    tenant, user, brand, login = uuid4(), uuid4(), uuid4(), uuid4()
    with admin_session() as s:
        s.add(
            Tenant(id=tenant, name="inv", country="CO", timezone="America/Bogota", currency="COP")
        )
        s.flush()
        s.add(
            User(
                id=user,
                tenant_id=tenant,
                email=f"{user}@test.invalid",
                display_name="O",
                auth_user_id=login,
            )
        )
        s.add(Brand(id=brand, tenant_id=tenant, name="Marca"))
        s.flush()
        s.add(TenantMember(tenant_id=tenant, user_id=user, role="owner"))
    return tenant, brand, login


def test_save_read_idempotent_resave_and_edit() -> None:
    tenant, brand, login = _business()
    with acting_login(login):
        assert load_investment_profile(tenant_id=tenant, brand_id=brand) is None
        assert default_currency(tenant_id=tenant, brand_id=brand) == "COP"
        first = save_investment_profile(tenant_id=tenant, brand_id=brand, **ANSWERS)
        assert (first.currency, first.margin_basis_points, first.updated_by) == ("COP", 3550, login)
        assert first.max_cost_per_client_minor == 887_500
        again = save_investment_profile(tenant_id=tenant, brand_id=brand, **ANSWERS)
        assert again == first  # same answers: same row, same updated_at
        edited = save_investment_profile(
            tenant_id=tenant, brand_id=brand, **{**ANSWERS, "objective": "visits"}
        )
        assert edited.objective == "visits" and edited.updated_at > first.updated_at
        assert edited.created_at == first.created_at
        assert load_investment_profile(tenant_id=tenant, brand_id=brand) == edited
    with admin_session() as s:
        assert (
            s.execute(
                text("SELECT count(*) FROM ad_investment_profiles WHERE tenant_id=:t"),
                {"t": tenant},
            ).scalar_one()
            == 1
        )


def test_another_tenant_cannot_read_or_write_it() -> None:
    tenant, brand, login = _business()
    other, other_brand, other_login = _business()
    with acting_login(login):
        save_investment_profile(tenant_id=tenant, brand_id=brand, **ANSWERS)
    with tenant_session(other) as s:
        assert s.execute(text("SELECT count(*) FROM ad_investment_profiles")).scalar_one() == 0
        updated = s.execute(
            text("UPDATE ad_investment_profiles SET objective='visits' WHERE brand_id=:b"),
            {"b": brand},
        ).rowcount
    assert updated == 0
    with acting_login(other_login):
        assert load_investment_profile(tenant_id=other, brand_id=brand) is None
        with pytest.raises(InvestmentProfileUnavailable, match=BRAND_GONE):
            save_investment_profile(tenant_id=other, brand_id=brand, **ANSWERS)
    with acting_login(login):
        assert load_investment_profile(tenant_id=tenant, brand_id=brand).objective == "messages"
        assert load_investment_profile(tenant_id=tenant, brand_id=other_brand) is None
