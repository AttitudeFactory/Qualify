"""`db`-marked tests for the pre-login Brand Kit (§ request 2026-10-02, migration 0037).

What only the real database proves: that the email on the first view provisions a whole
tenant (owner seat without a login + brand), that the same email resumes it, and that
the signup with that email adopts the tenant — one user, one brand, the login resolving
to it — instead of minting a second one."""

from __future__ import annotations

from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from sqlalchemy import select

from qualify_api.auth import (
    DraftEmailInvalid,
    EmailHasAccount,
    FakeAuthProvider,
    register_business,
    resolve_login,
    start_brand_kit_draft,
)
from qualify_api.auth.drafts import DRAFT_BRAND_NAME
from qualify_api.tenancy.models import Brand, BrandKitDraft, Tenant, TenantMember, User

pytestmark = pytest.mark.db

_DEFAULTS = {"country": "VE", "timezone": "America/Caracas", "currency": "USD"}


def _fresh_email() -> str:
    return f"hlrd1993+draft-{uuid4().hex[:8]}@gmail.com"


def _register(provider: FakeAuthProvider, email: str):
    return register_business(
        provider,
        business_name="Polette",
        email=email,
        password="correct-horse-9",
        country="CO",
        timezone="America/Bogota",
        currency="COP",
    )


def test_email_provisions_a_draft_tenant_with_a_login_less_owner() -> None:
    email = _fresh_email()
    draft = start_brand_kit_draft(email, **_DEFAULTS)
    assert draft.resumed is False
    with admin_session() as session:
        assert session.get(Tenant, draft.tenant_id) is not None
        user = session.scalar(select(User).where(User.tenant_id == draft.tenant_id))
        assert user is not None and user.email == email and user.auth_user_id is None
        member = session.scalar(
            select(TenantMember).where(TenantMember.tenant_id == draft.tenant_id)
        )
        assert member is not None and member.role == "owner" and member.user_id == user.id
        brand = session.scalar(select(Brand).where(Brand.tenant_id == draft.tenant_id))
        assert brand is not None and brand.name == DRAFT_BRAND_NAME


def test_same_email_resumes_the_draft_case_insensitively() -> None:
    email = _fresh_email()
    first = start_brand_kit_draft(email, **_DEFAULTS)
    again = start_brand_kit_draft(f"  {email.upper()} ", **_DEFAULTS)
    assert again.resumed is True
    assert again.tenant_id == first.tenant_id


def test_signup_adopts_the_draft_tenant() -> None:
    provider = FakeAuthProvider()
    email = _fresh_email()
    draft = start_brand_kit_draft(email, **_DEFAULTS)

    registered = _register(provider, email)
    assert registered.tenant_id == draft.tenant_id

    with admin_session() as session:
        tenant = session.get(Tenant, draft.tenant_id)
        assert tenant is not None
        assert (tenant.name, tenant.country, tenant.currency) == ("Polette", "CO", "COP")
        users = session.scalars(select(User).where(User.tenant_id == draft.tenant_id)).all()
        assert len(users) == 1 and users[0].auth_user_id == registered.auth_user_id
        brands = session.scalars(select(Brand).where(Brand.tenant_id == draft.tenant_id)).all()
        assert [b.name for b in brands] == ["Polette"]
        row = session.scalar(
            select(BrandKitDraft).where(BrandKitDraft.tenant_id == draft.tenant_id)
        )
        assert row is not None and row.claimed_at is not None

    login = resolve_login(provider, email, "correct-horse-9")
    assert login.tenant_id == draft.tenant_id


def test_a_claimed_draft_is_an_account_not_a_draft() -> None:
    provider = FakeAuthProvider()
    email = _fresh_email()
    start_brand_kit_draft(email, **_DEFAULTS)
    _register(provider, email)
    with pytest.raises(EmailHasAccount):
        start_brand_kit_draft(email, **_DEFAULTS)


def test_an_email_with_an_account_cannot_start_a_draft() -> None:
    email = _fresh_email()
    _register(FakeAuthProvider(), email)
    with pytest.raises(EmailHasAccount):
        start_brand_kit_draft(email, **_DEFAULTS)


def test_signup_without_a_draft_still_mints_a_fresh_tenant() -> None:
    provider = FakeAuthProvider()
    other = start_brand_kit_draft(_fresh_email(), **_DEFAULTS)
    registered = _register(provider, _fresh_email())
    assert registered.tenant_id != other.tenant_id


@pytest.mark.parametrize("bad", ["", "sin-arroba", "a@b", "a b@c.co", "@c.co", "a@@c.co"])
def test_bad_emails_are_refused(bad: str) -> None:
    with pytest.raises(DraftEmailInvalid):
        start_brand_kit_draft(bad, **_DEFAULTS)
