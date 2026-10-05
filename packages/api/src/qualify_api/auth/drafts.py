"""The Brand Kit before an account exists (§ request 2026-10-02, migration 0037).

The first view of the Brand Kit asks for an email and `start_brand_kit_draft`
provisions a tenant for it right away — `tenants`, a login-less owner `users` row, its
`tenant_members` seat and a `brands` row, all in one `admin_session` transaction like
`register_business` (creating a tenant is cross-tenant by nature). From then on the
wizard writes through `tenant_session(draft tenant)`, so every Brand Kit table keeps its
RLS and nothing downstream knows the difference.

The same email typed again resumes the draft. The signup with that email adopts the
draft's tenant (`claim_draft`, called from `register_business`): the identity user is
stamped with the draft tenant id, the login-less user gains the login (the same "link,
don't duplicate" path the seed's users take) and the brand takes the business name — so
the account opens with the Brand Kit already in it.

Known limit, accepted for the pre-login funnel: nothing verifies the email (neither does
signup — `admin_create_user` sends `email_confirm: True`), so whoever types an email with
an unclaimed draft can resume it. A claimed draft is an account and never resumes by email.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from qualify_shared.db.admin import admin_session
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qualify_api.tenancy.models import Brand, BrandKitDraft, Tenant, TenantMember, User

#: The brand's name until the signup names the business.
DRAFT_BRAND_NAME = "Mi marca"


class DraftEmailInvalid(Exception):
    """Bad email on the first view. `message` is safe to show."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EmailHasAccount(Exception):
    """The email already belongs to an account: the operator should log in instead."""


@dataclass(frozen=True)
class BrandKitDraftResult:
    tenant_id: UUID
    email: str
    resumed: bool


def draft_email_key(email: str) -> str:
    """The lookup key: trimmed and lowercased (the typed form is kept apart)."""
    return email.strip().lower()


def _validate(email: str) -> str:
    cleaned = email.strip()
    local, _, domain = cleaned.partition("@")
    if (
        cleaned.count("@") != 1
        or not local
        or "." not in domain
        or domain.startswith(".")
        or domain.endswith(".")
        or any(ch.isspace() for ch in cleaned)
    ):
        raise DraftEmailInvalid("Escribe un correo válido, por ejemplo tu@negocio.com.")
    return cleaned


def find_open_draft(session: Session, email: str) -> BrandKitDraft | None:
    """The unclaimed draft started with this email, if any. Needs `admin_session`."""
    return session.scalar(
        select(BrandKitDraft).where(
            BrandKitDraft.email_key == draft_email_key(email),
            BrandKitDraft.claimed_at.is_(None),
        )
    )


def _email_has_account(session: Session, key: str) -> bool:
    if session.scalar(
        select(BrandKitDraft.id).where(
            BrandKitDraft.email_key == key, BrandKitDraft.claimed_at.is_not(None)
        )
    ):
        return True
    return (
        session.scalar(
            select(User.id).where(func.lower(User.email) == key, User.auth_user_id.is_not(None))
        )
        is not None
    )


def _provision(
    session: Session, *, email: str, key: str, country: str, timezone: str, currency: str
) -> UUID:
    tenant = Tenant(name=DRAFT_BRAND_NAME, country=country, timezone=timezone, currency=currency)
    session.add(tenant)
    session.flush()
    user = User(tenant_id=tenant.id, email=email, display_name=email, auth_user_id=None)
    session.add(user)
    session.flush()
    session.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role="owner"))
    session.add(Brand(tenant_id=tenant.id, name=DRAFT_BRAND_NAME))
    session.add(BrandKitDraft(tenant_id=tenant.id, email=email, email_key=key))
    session.flush()
    return tenant.id


def start_brand_kit_draft(
    email: str, *, country: str, timezone: str, currency: str
) -> BrandKitDraftResult:
    """Resume the unclaimed draft for this email, or provision a new one. Raises
    `DraftEmailInvalid` or `EmailHasAccount`."""
    cleaned = _validate(email)
    key = draft_email_key(cleaned)
    with admin_session() as session:
        if _email_has_account(session, key):
            raise EmailHasAccount()
        draft = find_open_draft(session, cleaned)
        if draft is not None:
            return BrandKitDraftResult(tenant_id=draft.tenant_id, email=draft.email, resumed=True)
    try:
        with admin_session() as session:
            tenant_id = _provision(
                session,
                email=cleaned,
                key=key,
                country=country,
                timezone=timezone,
                currency=currency,
            )
    except IntegrityError:
        # Two tabs typing the same email at once: the other one won, resume it.
        with admin_session() as session:
            draft = find_open_draft(session, cleaned)
            if draft is None:
                raise
            return BrandKitDraftResult(tenant_id=draft.tenant_id, email=draft.email, resumed=True)
    return BrandKitDraftResult(tenant_id=tenant_id, email=cleaned, resumed=False)


def claim_draft(
    session: Session,
    draft: BrandKitDraft,
    *,
    email: str,
    business_name: str,
    country: str,
    timezone: str,
    currency: str,
    display_name: str,
) -> None:
    """Turn the draft's tenant into the signing-up business, in the caller's
    `admin_session`, BEFORE `_upsert_local_half` runs over it: the tenant takes the
    signup's fields, the login-less owner takes the email exactly as signed up with (so
    the upsert links it instead of adding a second user), and the draft brand takes the
    business name (so the upsert finds it instead of adding a second brand)."""
    tenant = session.get(Tenant, draft.tenant_id)
    if tenant is not None:
        tenant.name = business_name
        tenant.country = country
        tenant.timezone = timezone
        tenant.currency = currency
    owner = session.scalar(
        select(User)
        .where(
            User.tenant_id == draft.tenant_id,
            User.auth_user_id.is_(None),
            func.lower(User.email) == draft.email_key,
        )
        .order_by(User.created_at)
    )
    if owner is not None:
        owner.email = email
        owner.display_name = display_name
    brand = session.scalar(
        select(Brand).where(Brand.tenant_id == draft.tenant_id).order_by(Brand.created_at)
    )
    if brand is not None and brand.name == DRAFT_BRAND_NAME:
        brand.name = business_name
    draft.claimed_at = datetime.now(UTC)
    session.flush()
