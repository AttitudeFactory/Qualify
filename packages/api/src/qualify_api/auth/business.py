"""Opening one of the login's businesses (ADR 43 §2.1, S1 m-24849188).

A login may belong to several tenants (`users` row per `(tenant_id, auth_user_id)`,
migration 0104). `resolve_login` lists them (`LoginResult.memberships`); the UI then
**opens** one with `open_business`, and only its result may be written into the
session's active tenant (`AuthState.session_tenant_id`). Every page then reaches
`tenant_session` exactly as before, from that one server-side value.

Rules this module enforces:

- The membership check is **fresh** (no cache) and runs through
  `tenant_session(tenant_id)`: RLS confines the read to the business being opened,
  so a tenant the login does not belong to simply has no row → `NotAMember`.
- `auth_user_id` comes from the server-side session (the verified `LoginResult`),
  never from a browser argument. `tenant_id` may come from the selector's click — it
  is exactly what is being verified.
- Nothing is persisted here; the audit of each opening is S5 (m-24849192), in
  `qualify_api.auth.membership`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.auth.service import NoBusinessAccess
from qualify_api.tenancy.models import Tenant, TenantMember, User

#: Shown when the login is no longer (or never was) a member of the business. The
#: same text as `NoBusinessAccess` (epic copy table, «S5 · acceso retirado»).
NOT_A_MEMBER_MESSAGE = NoBusinessAccess.message


class NotAMember(Exception):
    """The login has no `users` + `tenant_members` row in that business. The UI shows
    `message` and sends the session back to /login (ADR 43 A15)."""

    message = NOT_A_MEMBER_MESSAGE

    def __init__(self) -> None:
        super().__init__(NOT_A_MEMBER_MESSAGE)


@dataclass(frozen=True)
class ActiveBusiness:
    """What the session needs to work in one business — the local user it maps to."""

    tenant_id: UUID
    business_name: str
    user_id: UUID
    email: str
    display_name: str
    role: str


def open_business(auth_user_id: UUID, tenant_id: UUID) -> ActiveBusiness:
    """Verify, without cache, that `auth_user_id` is a member of `tenant_id` and return
    the local user of that business. Raises `NotAMember` otherwise.

    Used after the login selector (S3), by the business switch (S4) and, fresh, right
    before anything is published or sent (S5). The selector and the switch call
    `qualify_api.auth.membership.open_business_audited` instead, which runs this same
    check and writes the audit row in one transaction."""
    with tenant_session(tenant_id) as db:
        return member_of(db, auth_user_id, tenant_id)


def member_of(db: Session, auth_user_id: UUID, tenant_id: UUID) -> ActiveBusiness:
    """The membership query of `open_business`, on a session already scoped (RLS) to
    `tenant_id`. Raises `NotAMember`."""
    row = db.execute(
        select(
            Tenant.name,
            User.id,
            User.email,
            User.display_name,
            TenantMember.role,
        )
        .join(User, User.tenant_id == Tenant.id)
        .join(
            TenantMember,
            (TenantMember.user_id == User.id) & (TenantMember.tenant_id == Tenant.id),
        )
        .where(Tenant.id == tenant_id, User.auth_user_id == auth_user_id)
    ).one_or_none()
    if row is None:
        raise NotAMember()
    business_name, user_id, email, display_name, role = row
    return ActiveBusiness(
        tenant_id=tenant_id,
        business_name=business_name,
        user_id=user_id,
        email=email,
        display_name=display_name,
        role=role,
    )
