"""Tests for multi-tenant auth (S1, m-24849188, ADR 43):
- A single login (auth_user_id) belonging to multiple tenants.
- `memberships_for(auth_user_id)` returns all memberships correctly.
- RLS isolation between tenants sharing an auth_user_id (tenant A
  cannot see tenant B's data via tenant_session).
- Backward compatibility for single-business flows.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.auth import (
    FakeAuthProvider,
    memberships_for,
    register_business,
    resolve_login,
)
from qualify_api.tenancy.models import Tenant, TenantMember, User

pytestmark = pytest.mark.db


def test_single_login_multiple_tenants_and_memberships_for() -> None:
    provider = FakeAuthProvider()
    email = f"owner-{uuid4().hex[:6]}@attitudefactory.co"
    password = "correct-horse-9"

    # Register first business (Bianki)
    bianki = register_business(
        provider,
        business_name="Bianki",
        email=email,
        password=password,
        country="VE",
        timezone="America/Caracas",
        currency="USD",
    )

    # For the second business (Polette), create tenant and link login to it
    polette_tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=polette_tenant_id,
                name="Polette",
                country="VE",
                timezone="America/Caracas",
                currency="USD",
            )
        )
        session.flush()

        # Create user row for polette tenant with same auth_user_id
        polette_user = User(
            tenant_id=polette_tenant_id,
            email=email,
            display_name="Polette",
            auth_user_id=bianki.auth_user_id,
        )
        session.add(polette_user)
        session.flush()

        session.add(
            TenantMember(
                tenant_id=polette_tenant_id,
                user_id=polette_user.id,
                role="owner",
            )
        )
        session.flush()

    # Test memberships_for returns both memberships
    mems = memberships_for(bianki.auth_user_id)
    assert len(mems) == 2
    tenant_ids = {m.tenant_id for m in mems}
    assert tenant_ids == {bianki.tenant_id, polette_tenant_id}

    names = {m.name for m in mems}
    assert names == {"Bianki", "Polette"}

    roles = {m.role for m in mems}
    assert roles == {"owner"}


def test_rls_isolation_between_tenants_sharing_auth_user_id() -> None:
    provider = FakeAuthProvider()
    email = f"multi-{uuid4().hex[:6]}@attitudefactory.co"
    password = "correct-horse-9"

    t1 = register_business(
        provider,
        business_name="Tenant One",
        email=email,
        password=password,
        country="CO",
        timezone="America/Bogota",
        currency="COP",
    )

    t2_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=t2_id,
                name="Tenant Two",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        u2 = User(
            tenant_id=t2_id,
            email=email,
            display_name="User Two",
            auth_user_id=t1.auth_user_id,
        )
        session.add(u2)
        session.flush()
        session.add(
            TenantMember(
                tenant_id=t2_id,
                user_id=u2.id,
                role="admin",
            )
        )
        session.flush()

    # Verify RLS via tenant_session(t1.tenant_id): cannot see t2's user or tenant
    with tenant_session(t1.tenant_id) as db:
        users_in_t1 = db.scalars(select(User)).all()
        assert all(u.tenant_id == t1.tenant_id for u in users_in_t1)
        assert not any(u.tenant_id == t2_id for u in users_in_t1)

    # Verify RLS via tenant_session(t2_id): cannot see t1's user or tenant
    with tenant_session(t2_id) as db:
        users_in_t2 = db.scalars(select(User)).all()
        assert all(u.tenant_id == t2_id for u in users_in_t2)
        assert not any(u.tenant_id == t1.tenant_id for u in users_in_t2)


def test_backward_compatibility_single_business() -> None:
    provider = FakeAuthProvider()
    email = f"single-{uuid4().hex[:6]}@attitudefactory.co"
    res = register_business(
        provider,
        business_name="Single Biz",
        email=email,
        password="correct-horse-9",
        country="CO",
        timezone="America/Bogota",
        currency="COP",
    )
    login = resolve_login(provider, email, "correct-horse-9")
    assert login.tenant_id == res.tenant_id
    assert login.auth_user_id == res.auth_user_id
    mems = memberships_for(res.auth_user_id)
    assert len(mems) == 1
    assert mems[0].tenant_id == res.tenant_id
    assert mems[0].name == "Single Biz"
    assert mems[0].role == "owner"
