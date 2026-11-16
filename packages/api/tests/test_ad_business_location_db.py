"""DB: saving and reading the business location (0169) and its isolation between tenants."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.business_location import get_business_location, save_business_location
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db


def _business() -> tuple[UUID, UUID]:
    tenant, user = uuid4(), uuid4()
    with admin_session() as s:
        s.add(
            Tenant(id=tenant, name="loc", country="CO", timezone="America/Bogota", currency="COP")
        )
        s.flush()
        s.add(User(id=user, tenant_id=tenant, email=f"{user}@test.invalid", display_name="O"))
    return tenant, user


def test_save_then_read_with_provenance() -> None:
    tenant, user = _business()
    assert get_business_location(tenant) is None
    assert save_business_location(tenant, user, 7.8891234567, -72.505) == (7.889123, -72.505)
    assert get_business_location(tenant) == (7.889123, -72.505)
    save_business_location(tenant, user, 4.6, -74.08)  # a second save replaces the first
    assert get_business_location(tenant) == (4.6, -74.08)
    with admin_session() as s:
        set_by, set_at = s.execute(
            text(
                "SELECT business_location_set_by, business_location_set_at"
                " FROM tenants WHERE id = :id"
            ),
            {"id": tenant},
        ).one()
    assert set_by == user and set_at is not None


def test_another_tenant_cannot_read_or_write_it() -> None:
    tenant, user = _business()
    other, other_user = _business()
    save_business_location(tenant, user, 7.88, -72.5)
    with tenant_session(other) as s:
        assert (
            s.execute(
                text("SELECT business_latitude FROM tenants WHERE id = :id"), {"id": tenant}
            ).all()
            == []
        )
        updated = s.execute(
            text("UPDATE tenants SET business_latitude = 1 WHERE id = :id"), {"id": tenant}
        ).rowcount
    assert updated == 0
    assert get_business_location(other) is None
    with pytest.raises(ValueError):  # a user of another business never signs the point
        save_business_location(tenant, other_user, 1, 1)
    assert get_business_location(tenant) == (7.88, -72.5)


def test_deleting_the_user_keeps_the_point() -> None:
    tenant, user = _business()
    save_business_location(tenant, user, 7.88, -72.5)
    with admin_session() as s:
        s.execute(text("DELETE FROM users WHERE id = :id"), {"id": user})
    assert get_business_location(tenant) == (7.88, -72.5)
