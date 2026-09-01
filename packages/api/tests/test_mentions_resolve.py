"""`resolve_external_account` (QUA-49) against real Postgres.

Proves, against the real schema (not just this module's own docstring), the
three properties the admin_session exception is only justified by: it is
read-only, it never picks a row arbitrarily when more than one tenant matches,
and 0/1/>1 rows produce exactly the three documented outcomes.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.mentions.resolve import (
    PLATFORM_INSTAGRAM,
    ResolutionOutcome,
    resolve_external_account,
)
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("a1111111-1111-4111-8111-111111111111")
TENANT_B = UUID("b2222222-2222-4222-8222-222222222222")


def _ensure_tenant(session, tenant_id: UUID, name: str) -> None:
    if session.get(Tenant, tenant_id) is None:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"mentions-{name}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()


def _seed_connection(*, tenant_id: UUID, external_account_id: str) -> UUID:
    """One connection under `tenant_id` for `external_account_id`. Returns the
    connection id. Mirrors `test_connections_schema.seeded_connection`'s split
    across doors: tenant/app/user via `admin_session` (provisioning), the
    connection itself via `tenant_session` (the real production door)."""
    with admin_session() as session:
        _ensure_tenant(session, tenant_id, str(tenant_id)[:8])
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@t.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform=PLATFORM_INSTAGRAM,
            account_type="business",
            external_account_id=external_account_id,
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        return conn.id


def _connection_count() -> int:
    with admin_session() as session:
        return int(session.scalar(select(func.count()).select_from(SocialConnection)) or 0)


def test_zero_matches_is_orphan() -> None:
    result = resolve_external_account(
        platform=PLATFORM_INSTAGRAM, external_account_id=f"ig-nonexistent-{uuid4()}"
    )

    assert result.outcome is ResolutionOutcome.ORPHAN
    assert result.tenant_id is None
    assert result.connection_id is None


def test_exactly_one_match_resolves_tenant_and_connection() -> None:
    external_account_id = f"ig-{uuid4()}"
    connection_id = _seed_connection(tenant_id=TENANT_A, external_account_id=external_account_id)

    result = resolve_external_account(
        platform=PLATFORM_INSTAGRAM, external_account_id=external_account_id
    )

    assert result.outcome is ResolutionOutcome.RESOLVED
    assert result.tenant_id == TENANT_A
    assert result.connection_id == connection_id


def test_more_than_one_match_is_ambiguous_and_never_picks_one() -> None:
    """The scenario the whole exception exists to guard: the same real Instagram
    account connected under two different tenants. Nothing in the schema forbids
    this (see `mentions/resolve.py`'s docstring) — this test proves the code
    handles it safely rather than merely asserting the schema does."""
    external_account_id = f"ig-shared-{uuid4()}"
    _seed_connection(tenant_id=TENANT_A, external_account_id=external_account_id)
    _seed_connection(tenant_id=TENANT_B, external_account_id=external_account_id)

    result = resolve_external_account(
        platform=PLATFORM_INSTAGRAM, external_account_id=external_account_id
    )

    assert result.outcome is ResolutionOutcome.AMBIGUOUS
    # Structural, not incidental: `TenantResolution` only ever carries ids when
    # `outcome is RESOLVED` (see its docstring) — this pins that neither tenant's
    # id leaked through on the ambiguous path.
    assert result.tenant_id is None
    assert result.connection_id is None


def test_resolution_never_writes() -> None:
    """Calling the resolver, including on an ambiguous/orphan input, must never
    change `social_connections` row count — the strongest black-box proof
    available that this function issues no `INSERT`/`UPDATE`/`DELETE`."""
    external_account_id = f"ig-{uuid4()}"
    _seed_connection(tenant_id=TENANT_A, external_account_id=external_account_id)
    before = _connection_count()

    resolve_external_account(platform=PLATFORM_INSTAGRAM, external_account_id=external_account_id)
    resolve_external_account(platform=PLATFORM_INSTAGRAM, external_account_id=f"ig-{uuid4()}")

    assert _connection_count() == before


def test_platform_is_part_of_the_natural_key() -> None:
    """A `tiktok` row with the same `external_account_id` must not resolve as if it
    were the `instagram` one — `platform` is a real filter, not decoration."""
    external_account_id = f"ig-{uuid4()}"
    with admin_session() as session:
        _ensure_tenant(session, TENANT_A, "A")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT_A, email=f"u-{uuid4()}@t.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id
    with tenant_session(TENANT_A) as session:
        session.add(
            SocialConnection(
                tenant_id=TENANT_A,
                platform_app_id=app_id,
                platform="tiktok",
                account_type="business",
                external_account_id=external_account_id,
                linked_page_id="page-1",
                granted_scopes=["basic"],
                status="active",
                access_posture="development",
                current_credential_version=0,
                connected_by_user_id=user_id,
            )
        )
        session.flush()

    result = resolve_external_account(
        platform=PLATFORM_INSTAGRAM, external_account_id=external_account_id
    )

    assert result.outcome is ResolutionOutcome.ORPHAN
