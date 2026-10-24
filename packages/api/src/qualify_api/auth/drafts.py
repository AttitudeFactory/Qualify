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
That accepted risk covers `web` drafts only — the ones the visitor typed themselves.

Drafts prepared for a Meegle «Alta de cliente» are reserved (PB-0, m-24852193, migration
0091; `docs/epica-prellenado-brand-kit-alta.md` §2.8). `start_alta_brand_kit_draft` creates
them with `origin = 'alta'` and the item id, idempotently per item. They open only with the
Alta's own invitation:

- The public first view never sees them. `start_brand_kit_draft` without an invite looks
  up `web` drafts only, so typing the email of a reserved draft provisions a separate,
  empty `web` draft — the same answer as "nothing here" (`resumed=False`), never an error
  that would reveal the reserved one exists.
- `start_brand_kit_draft(..., invite_token=...)` resumes the reserved draft when the token
  is a usable invite for that same email and that same Meegle item.
- The signup adopts it (`adoptable_draft`, called by `register_business`) only with a valid
  invite of the same item; otherwise the signup adopts the `web` draft of that email, if
  any, exactly as before, or mints a fresh tenant. A reserved draft that was not adopted
  stays unclaimed and unreachable (its tenant is login-less).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from qualify_shared.db.admin import admin_session
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qualify_api.auth.invites import lookup_invite
from qualify_api.tenancy.models import Brand, BrandKitDraft, Tenant, TenantMember, User

#: The brand's name until the signup names the business.
DRAFT_BRAND_NAME = "Mi marca"

#: `brand_kit_drafts.origin` (migration 0091).
ORIGIN_WEB = "web"
ORIGIN_ALTA = "alta"

#: The tenant fields an Alta draft starts with — the web signup's defaults. The signup
#: overwrites all three with what the client chooses (`claim_draft`).
ALTA_DRAFT_DEFAULTS = {"country": "VE", "timezone": "America/Caracas", "currency": "USD"}


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
    """The unclaimed `web` draft started with this email, if any — never a reserved Alta
    draft. Needs `admin_session`."""
    return session.scalar(
        select(BrandKitDraft).where(
            BrandKitDraft.email_key == draft_email_key(email),
            BrandKitDraft.origin == ORIGIN_WEB,
            BrandKitDraft.claimed_at.is_(None),
        )
    )


def _alta_draft(session: Session, meegle_work_item_id: int) -> BrandKitDraft | None:
    """The Alta draft of that Meegle item, claimed or not (one per item)."""
    return session.scalar(
        select(BrandKitDraft).where(
            BrandKitDraft.origin == ORIGIN_ALTA,
            BrandKitDraft.meegle_work_item_id == meegle_work_item_id,
        )
    )


def find_open_alta_draft(
    session: Session, email: str, meegle_work_item_id: int
) -> BrandKitDraft | None:
    """The unclaimed Alta draft of that Meegle item, when it was prepared for this email.
    Callers must already hold proof of the invitation (an invite of that item for that
    email): this lookup alone authorizes nothing. Needs `admin_session`."""
    draft = _alta_draft(session, meegle_work_item_id)
    if draft is None or draft.claimed_at is not None:
        return None
    if draft.email_key != draft_email_key(email):
        return None
    return draft


def adoptable_draft(
    session: Session, email: str, *, meegle_work_item_id: int | None
) -> BrandKitDraft | None:
    """The draft a signup with this email adopts. `meegle_work_item_id` is the item of the
    signup's VALID invite (`signup_invites.meegle_work_item_id`, already locked and
    re-checked by the caller), None without an invite or for one not made from Meegle.
    That item's reserved draft wins; otherwise the email's `web` draft, as before 0091."""
    if meegle_work_item_id is not None:
        draft = find_open_alta_draft(session, email, meegle_work_item_id)
        if draft is not None:
            return draft
    return find_open_draft(session, email)


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
    session: Session,
    *,
    email: str,
    key: str,
    country: str,
    timezone: str,
    currency: str,
    origin: str = ORIGIN_WEB,
    meegle_work_item_id: int | None = None,
) -> UUID:
    tenant = Tenant(name=DRAFT_BRAND_NAME, country=country, timezone=timezone, currency=currency)
    session.add(tenant)
    session.flush()
    user = User(tenant_id=tenant.id, email=email, display_name=email, auth_user_id=None)
    session.add(user)
    session.flush()
    session.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role="owner"))
    session.add(Brand(tenant_id=tenant.id, name=DRAFT_BRAND_NAME))
    session.add(
        BrandKitDraft(
            tenant_id=tenant.id,
            email=email,
            email_key=key,
            origin=origin,
            meegle_work_item_id=meegle_work_item_id,
        )
    )
    session.flush()
    return tenant.id


def _resume_with_invite(cleaned: str, invite_token: str) -> BrandKitDraftResult | None:
    """The reserved draft this invite opens: a usable invite for this same email, made
    from the Meegle item the draft belongs to. None in every other case."""
    invite = lookup_invite(invite_token)
    if invite is None or invite.meegle_work_item_id is None:
        return None
    if invite.email.strip().casefold() != cleaned.casefold():
        return None
    with admin_session() as session:
        draft = find_open_alta_draft(session, cleaned, invite.meegle_work_item_id)
        if draft is None:
            return None
        return BrandKitDraftResult(tenant_id=draft.tenant_id, email=draft.email, resumed=True)


def start_brand_kit_draft(
    email: str,
    *,
    country: str,
    timezone: str,
    currency: str,
    invite_token: str | None = None,
) -> BrandKitDraftResult:
    """Resume the unclaimed `web` draft for this email, or provision a new one. Raises
    `DraftEmailInvalid` or `EmailHasAccount`.

    A reserved Alta draft is resumed only with `invite_token` — the raw token of a usable
    invite for this email from the same Meegle item. Without it (the public first view)
    reserved drafts are invisible: the email gets its own `web` draft, as if none existed."""
    cleaned = _validate(email)
    key = draft_email_key(cleaned)
    with admin_session() as session:
        if _email_has_account(session, key):
            raise EmailHasAccount()
    if invite_token:
        reserved = _resume_with_invite(cleaned, invite_token)
        if reserved is not None:
            return reserved
    with admin_session() as session:
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


def start_alta_brand_kit_draft(
    email: str,
    meegle_work_item_id: int,
    *,
    country: str = ALTA_DRAFT_DEFAULTS["country"],
    timezone: str = ALTA_DRAFT_DEFAULTS["timezone"],
    currency: str = ALTA_DRAFT_DEFAULTS["currency"],
) -> BrandKitDraftResult:
    """Provision the Brand Kit draft an Alta prepares for its client, reserved to that
    Alta's invitation (PB-0). Idempotent per Meegle item: a second call returns the same
    draft (`resumed=True`); if the Alta's email was corrected meanwhile, the unclaimed
    draft and its login-less owner take the new email. Raises `DraftEmailInvalid`, or
    `EmailHasAccount` when the email already has an account or the item's draft was
    already adopted by a signup.

    Called from the webhook-worker after the invitation is sent (PB-4); never from a
    request path a visitor controls."""
    cleaned = _validate(email)
    key = draft_email_key(cleaned)
    with admin_session() as session:
        if _email_has_account(session, key):
            raise EmailHasAccount()
        existing = _alta_draft(session, meegle_work_item_id)
        if existing is not None:
            return _reuse_alta_draft(session, existing, cleaned, key)
    try:
        with admin_session() as session:
            tenant_id = _provision(
                session,
                email=cleaned,
                key=key,
                country=country,
                timezone=timezone,
                currency=currency,
                origin=ORIGIN_ALTA,
                meegle_work_item_id=meegle_work_item_id,
            )
    except IntegrityError:
        # A retried event raced this one for the same item: the other won, reuse it.
        with admin_session() as session:
            existing = _alta_draft(session, meegle_work_item_id)
            if existing is None:
                raise
            return _reuse_alta_draft(session, existing, cleaned, key)
    return BrandKitDraftResult(tenant_id=tenant_id, email=cleaned, resumed=False)


def _reuse_alta_draft(
    session: Session, draft: BrandKitDraft, email: str, key: str
) -> BrandKitDraftResult:
    if draft.claimed_at is not None:
        raise EmailHasAccount()
    if draft.email_key != key:
        owner = session.scalar(
            select(User).where(
                User.tenant_id == draft.tenant_id,
                User.auth_user_id.is_(None),
                func.lower(User.email) == draft.email_key,
            )
        )
        if owner is not None:
            owner.email = email
            owner.display_name = email
        draft.email = email
        draft.email_key = key
        session.flush()
    return BrandKitDraftResult(tenant_id=draft.tenant_id, email=draft.email, resumed=True)


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
