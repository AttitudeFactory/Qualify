"""Seed the two real Sprint-1 tenants (the reason the seat model exists).

Run via `python -m qualify_api.seed` (or `just seed`). Uses `admin_session`
(`qualify_admin`, BYPASSRLS) because creating a tenant is inherently cross-tenant —
there is no "current tenant" when the `tenants` row is born.

- PuntoServis (Cúcuta, CO): 1 `owner` (the founder), 1 brand — the shared-core test bench.
- Inmobiliaria (UY): 1 `owner` + N `agent`s (QUALIFY_SEED_AGENTS, default 3), 1 brand —
  the reason a multi-seat model exists.

Idempotent: fixed tenant ids, and every row is upserted-by-existence, so re-running is a
no-op. Does NOT create real social connections (that needs live OAuth). After seeding, a
smoke check opens `tenant_session(PuntoServis)` and asserts it cannot see the
inmobiliaria's rows — exercising the C-01 isolation guarantee at startup.
"""

from __future__ import annotations

import os
from uuid import UUID

from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.models import PlatformApp
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

PUNTOSERVIS_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
INMOBILIARIA_TENANT_ID = UUID("b0000000-0000-4000-8000-000000000002")


def _get_or_create_tenant(
    session: Session,
    *,
    tenant_id: UUID,
    name: str,
    country: str,
    timezone: str,
    currency: str,
) -> Tenant:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(
            id=tenant_id, name=name, country=country, timezone=timezone, currency=currency
        )
        session.add(tenant)
        session.flush()
    return tenant


def _get_or_create_user(
    session: Session, *, tenant_id: UUID, email: str, display_name: str
) -> User:
    user = session.scalar(select(User).where(User.tenant_id == tenant_id, User.email == email))
    if user is None:
        user = User(tenant_id=tenant_id, email=email, display_name=display_name)
        session.add(user)
        session.flush()
    return user


def _ensure_member(session: Session, *, tenant_id: UUID, user_id: UUID, role: str) -> None:
    existing = session.scalar(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id
        )
    )
    if existing is None:
        session.add(TenantMember(tenant_id=tenant_id, user_id=user_id, role=role))
        session.flush()


def _ensure_brand(session: Session, *, tenant_id: UUID, name: str) -> None:
    existing = session.scalar(select(Brand).where(Brand.tenant_id == tenant_id, Brand.name == name))
    if existing is None:
        session.add(Brand(tenant_id=tenant_id, name=name))
        session.flush()


def _ensure_platform_app(session: Session) -> None:
    """The global `platform_apps` row (R1) the connect flow resolves by `app_id`.

    Global, not tenant-scoped: this registers QUALIFY's own Meta app — the secret is ours,
    and every tenant connects through the same row. It is seeded here because `qualify_app`
    holds only SELECT on the table, so the request path cannot create it; a missing row
    surfaces as `PlatformAppMissing` at connect time rather than a silent insert.

    Only a REFERENCE to the secret is stored (`secret_ref`), never the secret itself.
    """
    settings = MetaOAuthSettings.from_env()
    existing = session.scalar(select(PlatformApp).where(PlatformApp.app_id == settings.app_id))
    if existing is None:
        session.add(
            PlatformApp(
                app_id=settings.app_id,
                secret_ref="env:QUALIFY_META_APP_SECRET",
                api_version=settings.api_version,
            )
        )
        session.flush()
    elif existing.api_version != settings.api_version:
        # Graph versions are deprecated on a calendar; keep the row current so the
        # provenance recorded against new connections is not a stale string.
        existing.api_version = settings.api_version
        session.flush()


def _seed_puntoservis(session: Session) -> None:
    _get_or_create_tenant(
        session,
        tenant_id=PUNTOSERVIS_TENANT_ID,
        name="PuntoServis",
        country="CO",
        timezone="America/Bogota",
        currency="COP",
    )
    owner = _get_or_create_user(
        session,
        tenant_id=PUNTOSERVIS_TENANT_ID,
        email="founder@puntoservis.co",
        display_name="PuntoServis Owner",
    )
    _ensure_member(session, tenant_id=PUNTOSERVIS_TENANT_ID, user_id=owner.id, role="owner")
    _ensure_brand(session, tenant_id=PUNTOSERVIS_TENANT_ID, name="PuntoServis")


def _seed_inmobiliaria(session: Session, *, agent_count: int) -> None:
    _get_or_create_tenant(
        session,
        tenant_id=INMOBILIARIA_TENANT_ID,
        name="Inmobiliaria UY",
        country="UY",
        timezone="America/Montevideo",
        currency="UYU",
    )
    owner = _get_or_create_user(
        session,
        tenant_id=INMOBILIARIA_TENANT_ID,
        email="owner@inmobiliaria.uy",
        display_name="Inmobiliaria Owner",
    )
    _ensure_member(session, tenant_id=INMOBILIARIA_TENANT_ID, user_id=owner.id, role="owner")
    for i in range(1, agent_count + 1):
        agent = _get_or_create_user(
            session,
            tenant_id=INMOBILIARIA_TENANT_ID,
            email=f"agent{i}@inmobiliaria.uy",
            display_name=f"Inmobiliaria Agent {i}",
        )
        _ensure_member(session, tenant_id=INMOBILIARIA_TENANT_ID, user_id=agent.id, role="agent")
    _ensure_brand(session, tenant_id=INMOBILIARIA_TENANT_ID, name="Inmobiliaria UY")


def seed(agent_count: int | None = None) -> None:
    """Create/refresh the two tenants, then run the isolation smoke check."""
    if agent_count is None:
        agent_count = int(os.environ.get("QUALIFY_SEED_AGENTS", "3"))
    with admin_session() as session:
        _seed_puntoservis(session)
        _seed_inmobiliaria(session, agent_count=agent_count)
        _ensure_platform_app(session)
    _smoke_check_isolation()


def _smoke_check_isolation() -> None:
    """Exercise C-01.5 at startup: as `qualify_app` scoped to PuntoServis, every visible
    brand must belong to PuntoServis — the inmobiliaria's rows are invisible."""
    with tenant_session(PUNTOSERVIS_TENANT_ID) as session:
        tenant_ids = {brand.tenant_id for brand in session.scalars(select(Brand)).all()}
    assert tenant_ids <= {PUNTOSERVIS_TENANT_ID}, (
        f"tenant isolation breached at seed: PuntoServis session saw {tenant_ids}"
    )


if __name__ == "__main__":
    seed()
    print("seeded PuntoServis + Inmobiliaria; isolation smoke check passed")
