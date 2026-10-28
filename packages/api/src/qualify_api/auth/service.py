"""Registration and login resolution (QUA-66).

`register_business` is the founder ruling made code: **registering assigns a
`tenant_id` automatically**. One signup creates the identity-provider user (with the
tenant stamped in `app_metadata`) and the whole local half — `tenants`, `users`,
`tenant_members` owner seat, and the initial `brands` row — in one `admin_session`
transaction (creating a tenant is inherently cross-tenant, same as the seed).

Ordering and idempotency. The tenant id is generated FIRST, then the identity user is
created carrying it, then the local rows. A crash between the last two steps leaves an
identity user whose local half is missing; `resolve_login` detects exactly that
(`IncompleteRegistration`) and refuses, and re-running the signup with the same
credentials completes the missing half instead of duplicating — every local write is
upsert-by-existence, the same discipline as `qualify_api.seed`.

`resolve_login` is the deterministic credential→tenant resolution (hygiene criterion
6): the tenant comes from the provider's `app_metadata` stamp, never from guessing
across tenants by email — no cross-tenant read happens on the login path at all. The
local `users` row is then loaded through `tenant_session(tenant_id)`, RLS-scoped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from qualify_api.auth.drafts import adoptable_draft, claim_draft
from qualify_api.auth.invites import AltaPlanChoice, alta_plan_of, lock_invite, mark_invite_used
from qualify_api.auth.provider import (
    AuthProvider,
    AuthSession,
    EmailAlreadyRegistered,
    InvalidCredentials,
)
from qualify_api.tenancy.models import Brand, BrandKitDraft, Tenant, TenantMember, User

_MIN_PASSWORD_LENGTH = 8

logger = logging.getLogger("qualify_api.auth.service")


class RegistrationInvalid(Exception):
    """Bad signup input. `message` is safe to show to the operator."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class IncompleteRegistration(Exception):
    """The identity provider knows this user but the local half is missing or
    unstamped. The fix is re-running the signup with the same credentials — the UI
    says so instead of guessing a tenant."""


@dataclass(frozen=True)
class RegisteredBusiness:
    tenant_id: UUID
    auth_user_id: UUID
    email: str
    business_name: str


@dataclass(frozen=True)
class LoginResult:
    """A verified login: provider session + the local user it maps to."""

    tenant_id: UUID
    auth_user_id: UUID
    user_id: UUID
    email: str
    display_name: str
    access_token: str


def _validate_signup(
    business_name: str, email: str, password: str, *, new_password: bool = True
) -> None:
    if not business_name.strip():
        raise RegistrationInvalid("El nombre del negocio no puede estar vacío.")
    # Literal email handling (criterion 6): no lowercasing, no stripping of `+…` —
    # the alias IS the disambiguation. Only surrounding whitespace would be junk,
    # and rather than silently trimming we refuse it.
    if email != email.strip() or "@" not in email or email.count("@") != 1:
        raise RegistrationInvalid("El email no es válido.")
    if new_password and len(password) < _MIN_PASSWORD_LENGTH:
        raise RegistrationInvalid(
            f"La contraseña debe tener al menos {_MIN_PASSWORD_LENGTH} caracteres."
        )


def _resolve_identity_for_signup(
    provider: AuthProvider,
    email: str,
    password: str,
    new_tenant_id: UUID,
    *,
    is_add_business: bool = False,
) -> tuple[UUID, UUID]:
    """Create the identity user, or — on a retry — recover the existing one.

    Returns `(auth_user_id, tenant_id)`. On the retry path the tenant id comes from
    the EXISTING stamp, so a re-run completes the original registration rather than
    minting a second tenant for the same credential. When `is_add_business` is True,
    sign in with the existing credential to get auth_user_id and use the new tenant_id.
    """
    if is_add_business:
        try:
            auth_session = provider.sign_in(email, password)
        except InvalidCredentials:
            raise RegistrationInvalid("Esa contraseña no coincide. Inténtalo otra vez.") from None
        return auth_session.auth_user_id, new_tenant_id
    try:
        return provider.admin_create_user(email, password, new_tenant_id), new_tenant_id
    except EmailAlreadyRegistered:
        try:
            session = provider.sign_in(email, password)
        except InvalidCredentials:
            raise RegistrationInvalid(
                "Ese email ya está registrado. Inicia sesión, o si el registro quedó a "
                "medias, reintenta con la misma contraseña."
            ) from None
        if session.tenant_id is None:
            raise RegistrationInvalid(
                "Ese email ya existe en el proveedor de identidad sin negocio asociado. "
                "Contacta al administrador."
            ) from None
        return session.auth_user_id, session.tenant_id


def _upsert_local_half(
    session: Session,
    *,
    tenant_id: UUID,
    auth_user_id: UUID,
    email: str,
    business_name: str,
    country: str,
    timezone: str,
    currency: str,
    display_name: str,
) -> None:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        session.add(
            Tenant(
                id=tenant_id,
                name=business_name,
                country=country,
                timezone=timezone,
                currency=currency,
            )
        )
        session.flush()

    user = session.scalar(select(User).where(User.tenant_id == tenant_id, User.email == email))
    if user is None:
        user = User(
            tenant_id=tenant_id,
            email=email,
            display_name=display_name,
            auth_user_id=auth_user_id,
        )
        session.add(user)
        session.flush()
    elif user.auth_user_id is None:
        # A seeded/pre-auth user gaining a login: link, don't duplicate.
        user.auth_user_id = auth_user_id
        session.flush()

    member = session.scalar(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id, TenantMember.user_id == user.id
        )
    )
    if member is None:
        session.add(TenantMember(tenant_id=tenant_id, user_id=user.id, role="owner"))
        session.flush()

    brand = session.scalar(
        select(Brand).where(Brand.tenant_id == tenant_id, Brand.name == business_name)
    )
    if brand is None:
        session.add(Brand(tenant_id=tenant_id, name=business_name))
        session.flush()


def _open_draft_tenant_id(email: str) -> UUID | None:
    """The tenant of the unclaimed `web` pre-login Brand Kit started with this email — the
    only kind a signup without an invite may adopt (reserved Alta drafts need theirs)."""
    with admin_session() as session:
        draft = adoptable_draft(session, email, meegle_work_item_id=None)
        return draft.tenant_id if draft is not None else None


def _lock_signup_email(session: Session, email: str) -> None:
    """Serialize registrations across distinct invites for the same identity.

    The lock spans the provider call and local commit. Otherwise another invite
    could see an existing identity before its local account has committed and
    mistake that in-flight registration for an incomplete signup to recover.
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"qualify:signup:{email.strip().casefold()}"},
    )


def _persist_business(
    session: Session,
    *,
    draft_tenant_id: UUID | None,
    tenant_id: UUID,
    auth_user_id: UUID,
    email: str,
    business_name: str,
    country: str,
    timezone: str,
    currency: str,
    display_name: str,
) -> None:
    """The local half of a signup: adopt the pre-login draft when it belongs to this
    tenant, then tenant/user/membership/brand. `draft_tenant_id` was chosen by
    `adoptable_draft` (which already applied the Alta reservation)."""
    draft = (
        session.scalar(
            select(BrandKitDraft).where(
                BrandKitDraft.tenant_id == draft_tenant_id, BrandKitDraft.claimed_at.is_(None)
            )
        )
        if draft_tenant_id is not None
        else None
    )
    # On the retry path the identity may already be stamped to another tenant: the
    # draft is only adopted by the tenant it was provisioned as.
    if draft is not None and draft.tenant_id == tenant_id:
        claim_draft(
            session,
            draft,
            email=email,
            business_name=business_name,
            country=country,
            timezone=timezone,
            currency=currency,
            display_name=display_name,
        )
    _upsert_local_half(
        session,
        tenant_id=tenant_id,
        auth_user_id=auth_user_id,
        email=email,
        business_name=business_name,
        country=country,
        timezone=timezone,
        currency=currency,
        display_name=display_name,
    )


def register_business(
    provider: AuthProvider,
    *,
    business_name: str,
    email: str,
    password: str,
    country: str,
    timezone: str,
    currency: str,
    display_name: str | None = None,
    invite_id: UUID | None = None,
) -> RegisteredBusiness:
    """Signup: assigns a fresh `tenant_id` automatically and builds both halves — unless
    a Brand Kit was started before login with this email (§ request 2026-10-02): then
    the signup adopts that draft's tenant, so the account opens with its Brand Kit.
    A draft an Alta prepared (PB-0, `auth.drafts`) is adopted only when the invite comes
    from that same Meegle item; any other signup with the email ignores it.

    With an `invite_id` (from `invites.authorize_signup`) the invite is locked and
    re-checked in the same transaction as the local half, BEFORE the identity user is
    created, and spent only once the business exists. Order matters: the identity
    provider is outside our transaction, so a signup that lost the race on the invite
    must learn it before it creates a user there (an orphan identity would block that
    email). A transaction advisory lock on the normalized email also serializes
    different invitations for the same identity, through the provider call and local
    commit, so a concurrent signup cannot masquerade as an incomplete registration.
    Without an invite (dev/tests, `QUALIFY_SIGNUP_OPEN=1`)
    nothing is locked and every refusal still fires before the database is touched."""
    if invite_id is None:
        _validate_signup(business_name, email, password)
    local = dict(
        email=email,
        business_name=business_name.strip(),
        country=country,
        timezone=timezone,
        currency=currency,
        display_name=display_name or business_name.strip(),
    )
    if invite_id is None:
        draft_tenant_id = _open_draft_tenant_id(email)
        auth_user_id, tenant_id = _resolve_identity_for_signup(
            provider, email, password, draft_tenant_id or uuid4()
        )
        with admin_session() as session:
            _persist_business(
                session,
                draft_tenant_id=draft_tenant_id,
                tenant_id=tenant_id,
                auth_user_id=auth_user_id,
                **local,
            )
    else:
        with admin_session() as session:
            _lock_signup_email(session, email)
            invite = lock_invite(session, invite_id, email)
            if invite.is_add_business:
                email = invite.email
                business_name = invite.business_name or business_name
                local.update(
                    email=email,
                    business_name=business_name.strip(),
                    display_name=display_name or business_name.strip(),
                )
            _validate_signup(
                business_name, email, password, new_password=not invite.is_add_business
            )
            if (
                not invite.is_add_business
                and session.scalar(
                    select(User.id)
                    .where(func.lower(User.email) == email.lower(), User.auth_user_id.is_not(None))
                    .limit(1)
                )
                is not None
            ):
                raise RegistrationInvalid(
                    "Ese correo ya tiene cuenta en Qualify. "
                    "Pide una invitación para agregar el negocio a tu cuenta."
                )
            meegle_work_item_id = invite.meegle_work_item_id
            alta_plan = alta_plan_of(invite)
            # Chosen only now, with the invite locked and re-checked: its Meegle item is
            # what unlocks that Alta's reserved draft.
            draft = adoptable_draft(session, email, meegle_work_item_id=meegle_work_item_id)
            draft_tenant_id = draft.tenant_id if draft is not None else None
            auth_user_id, tenant_id = _resolve_identity_for_signup(
                provider,
                email,
                password,
                draft_tenant_id or uuid4(),
                is_add_business=invite.is_add_business,
            )
            # A normal invite may recover an identity-only incomplete signup, but
            # must never attach another Alta's business to a completed account.
            existing_user = session.scalar(
                select(User.id).where(User.auth_user_id == auth_user_id).limit(1)
            )
            if not invite.is_add_business and existing_user is not None:
                raise RegistrationInvalid(
                    "Ese correo ya tiene cuenta en Qualify. "
                    "Pide una invitación para agregar el negocio a tu cuenta."
                )
            if invite.is_add_business and existing_user is None:
                raise RegistrationInvalid(
                    "Ese correo no tiene una cuenta en Qualify. Pide una nueva invitación."
                )
            _persist_business(
                session,
                draft_tenant_id=draft_tenant_id,
                tenant_id=tenant_id,
                auth_user_id=auth_user_id,
                **local,
            )
            mark_invite_used(session, invite, tenant_id)
        if meegle_work_item_id is not None:
            # Outside the transaction, best-effort: the business exists whatever Meegle says.
            _notify_meegle_registered(meegle_work_item_id, tenant_id)
            if alta_plan is not None:
                # m-24852131: the plan/pack the Alta chose, now that the business exists.
                _apply_alta_plan(meegle_work_item_id, tenant_id, alta_plan)
    return RegisteredBusiness(
        tenant_id=tenant_id,
        auth_user_id=auth_user_id,
        email=email,
        business_name=business_name.strip(),
    )


def notify_meegle_registered(work_item_id: int, tenant_id: UUID) -> None:
    """Complete **Registrada** on the Meegle item the invite came from (plan M1 §2, node 3).
    Module-level so tests can replace it; production resolves the engine lazily."""
    from qualify_api.meegle.handlers import production_engine  # noqa: PLC0415

    production_engine().mark_registered(work_item_id, tenant_id)


def _notify_meegle_registered(work_item_id: int, tenant_id: UUID) -> None:
    try:
        notify_meegle_registered(work_item_id, tenant_id)
    except Exception as exc:  # noqa: BLE001 — never fail a signup over the write-back
        logger.warning(
            "meegle write-back skipped for work_item=%s tenant=%s (%s)",
            work_item_id,
            tenant_id,
            type(exc).__name__,
        )


def apply_alta_plan_on_register(work_item_id: int, tenant_id: UUID, choice: AltaPlanChoice) -> None:
    """Apply the plan/pack an Alta chose (m-24852131) and tell its Meegle item.
    Module-level so tests can replace it; `apply_on_registration` never raises."""
    from qualify_api.meegle.plan_request import apply_on_registration  # noqa: PLC0415

    apply_on_registration(work_item_id, tenant_id, choice)


def _apply_alta_plan(work_item_id: int, tenant_id: UUID, choice: AltaPlanChoice) -> None:
    try:
        apply_alta_plan_on_register(work_item_id, tenant_id, choice)
    except Exception as exc:  # noqa: BLE001 — never fail a signup over the plan
        logger.warning(
            "alta plan skipped for work_item=%s tenant=%s (%s)",
            work_item_id,
            tenant_id,
            type(exc).__name__,
        )


def link_login_to_tenant(
    provider: AuthProvider,
    *,
    tenant_id: UUID,
    email: str,
    password: str,
    display_name: str | None = None,
) -> RegisteredBusiness:
    """Give an EXISTING tenant (e.g. the seeded ones) a login. Same machinery as
    `register_business`, minus tenant creation — the tenant must already exist."""
    _validate_signup("existing-tenant", email, password)
    with admin_session() as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            raise RegistrationInvalid("Ese tenant no existe.")
        business_name = tenant.name
    auth_user_id, stamped_tenant_id = _resolve_identity_for_signup(
        provider, email, password, tenant_id
    )
    if stamped_tenant_id != tenant_id:
        raise RegistrationInvalid(
            "Ese email ya pertenece a otro negocio; usa un alias distinto por negocio."
        )
    with admin_session() as session:
        tenant = session.get(Tenant, tenant_id)
        assert tenant is not None  # checked above; admin_session sees all tenants
        _upsert_local_half(
            session,
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            email=email,
            business_name=business_name,
            country=tenant.country,
            timezone=tenant.timezone,
            currency=tenant.currency,
            display_name=display_name or email,
        )
    return RegisteredBusiness(
        tenant_id=tenant_id,
        auth_user_id=auth_user_id,
        email=email,
        business_name=business_name,
    )


@dataclass(frozen=True)
class UserMembership:
    tenant_id: UUID
    tenant_name: str
    name: str
    role: str
    user_id: UUID
    email: str
    display_name: str


def memberships_for(auth_user_id: UUID) -> list[UserMembership]:
    """Return all tenant memberships for a given Supabase auth user id,
    queried via admin_session across tenants (ADR 43 §2.1).
    """
    with admin_session() as session:
        stmt = (
            select(
                Tenant.id,
                Tenant.name,
                TenantMember.role,
                User.id,
                User.email,
                User.display_name,
            )
            .join(User, User.tenant_id == Tenant.id)
            .join(TenantMember, TenantMember.user_id == User.id)
            .where(User.auth_user_id == auth_user_id)
        )
        rows = session.execute(stmt).all()
        return [
            UserMembership(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                name=tenant_name,
                role=role,
                user_id=user_id,
                email=email,
                display_name=display_name,
            )
            for tenant_id, tenant_name, role, user_id, email, display_name in rows
        ]


def resolve_login(provider: AuthProvider, email: str, password: str) -> LoginResult:
    """Sign in and resolve the session to a verified local user. Raises
    `InvalidCredentials` (generic, on purpose) or `IncompleteRegistration`."""
    session_dto: AuthSession = provider.sign_in(email, password)
    if session_dto.tenant_id is None:
        raise IncompleteRegistration()
    with tenant_session(session_dto.tenant_id) as db:
        user = db.scalar(select(User).where(User.auth_user_id == session_dto.auth_user_id))
        if user is None:
            raise IncompleteRegistration()
        user_id, display_name = user.id, user.display_name
    return LoginResult(
        tenant_id=session_dto.tenant_id,
        auth_user_id=session_dto.auth_user_id,
        user_id=user_id,
        email=session_dto.email,
        display_name=display_name,
        access_token=session_dto.access_token,
    )
