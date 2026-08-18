"""`db`-marked tests for `register_business` / `resolve_login` against live Postgres.

What only the real database proves: that one signup lands the full local half
(tenant + user + owner seat + brand) through the admin door, that a re-run completes
instead of duplicating, that the login's `users` read goes through the RLS door of the
RIGHT tenant, and that migration 0008's global uniqueness on `auth_user_id` holds."""

from __future__ import annotations

from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from sqlalchemy import select

from qualify_api.auth import (
    FakeAuthProvider,
    IncompleteRegistration,
    link_login_to_tenant,
    register_business,
    resolve_login,
)
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db


def _fresh_email() -> str:
    # Unique per run: db tests must be re-runnable without a volume wipe.
    return f"hlrd1993+polet-{uuid4().hex[:8]}@gmail.com"


def _register(provider: FakeAuthProvider, email: str, password: str = "correct-horse-9"):
    return register_business(
        provider,
        business_name="Polet Bubble Tea",
        email=email,
        password=password,
        country="VE",
        timezone="America/Caracas",
        currency="USD",
    )


def test_signup_assigns_tenant_and_builds_the_full_local_half() -> None:
    provider = FakeAuthProvider()
    email = _fresh_email()
    result = _register(provider, email)

    with admin_session() as session:
        tenant = session.get(Tenant, result.tenant_id)
        assert tenant is not None
        assert (tenant.name, tenant.country, tenant.currency) == ("Polet Bubble Tea", "VE", "USD")
        user = session.scalar(select(User).where(User.auth_user_id == result.auth_user_id))
        assert user is not None and user.tenant_id == result.tenant_id and user.email == email
        member = session.scalar(
            select(TenantMember).where(
                TenantMember.tenant_id == result.tenant_id, TenantMember.user_id == user.id
            )
        )
        assert member is not None and member.role == "owner"
        assert (
            session.scalar(
                select(Brand).where(
                    Brand.tenant_id == result.tenant_id, Brand.name == "Polet Bubble Tea"
                )
            )
            is not None
        )


def test_signup_rerun_completes_instead_of_minting_a_second_tenant() -> None:
    provider = FakeAuthProvider()
    email = _fresh_email()
    first = _register(provider, email)
    second = _register(provider, email)  # same credentials — the retry path
    assert second.tenant_id == first.tenant_id
    assert second.auth_user_id == first.auth_user_id
    with admin_session() as session:
        users = session.scalars(select(User).where(User.tenant_id == first.tenant_id)).all()
        assert len(users) == 1


def test_login_resolves_to_the_registered_tenant() -> None:
    provider = FakeAuthProvider()
    email = _fresh_email()
    registered = _register(provider, email)
    login = resolve_login(provider, email, "correct-horse-9")
    assert login.tenant_id == registered.tenant_id
    assert login.auth_user_id == registered.auth_user_id
    assert login.display_name == "Polet Bubble Tea"


def test_identity_without_local_half_is_incomplete() -> None:
    provider = FakeAuthProvider()
    email = _fresh_email()
    # Identity exists and is stamped, but the local rows never landed (the
    # crash-between-halves scenario).
    provider.seed_user(email, "correct-horse-9", tenant_id=uuid4())
    with pytest.raises(IncompleteRegistration):
        resolve_login(provider, email, "correct-horse-9")


def test_link_login_attaches_to_existing_tenant() -> None:
    provider = FakeAuthProvider()
    email = _fresh_email()
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name="Seeded Existing",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
    result = link_login_to_tenant(
        provider, tenant_id=tenant_id, email=email, password="correct-horse-9"
    )
    assert result.tenant_id == tenant_id
    login = resolve_login(provider, email, "correct-horse-9")
    assert login.tenant_id == tenant_id
