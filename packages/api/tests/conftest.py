"""Fixtures for the `db`-marked tenancy tests. These need the local Postgres from
docker-compose (migrated + roles created), so they run in CI via service containers,
never as pure unit tests."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import app_dsn
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine

from qualify_api.tenancy.models import Brand, Tenant

TENANT_A = UUID("c0000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("d0000000-0000-4000-8000-00000000000b")


@pytest.fixture
def seeded_ab() -> tuple[UUID, UUID]:
    """Two tenants, each with one brand, inserted via the BYPASSRLS admin door.
    Idempotent so local re-runs of `just test-db` don't accumulate rows."""
    with admin_session() as session:
        for tenant_id, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tenant_id) is None:
                session.add(
                    Tenant(
                        id=tenant_id,
                        name=f"tenant-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
            if session.scalar(select(Brand).where(Brand.tenant_id == tenant_id)) is None:
                session.add(Brand(tenant_id=tenant_id, name=f"brand-{name}"))
                session.flush()
    return TENANT_A, TENANT_B


@pytest.fixture
def app_engine() -> Iterator[Engine]:
    """A raw `qualify_app` engine for tests that must observe RLS behavior WITHOUT the
    `app.tenant_id` GUC set (fail-closed, GUC-bleed). Test code may build engines; the
    C-01 static test only forbids it in `src/`."""
    engine = create_engine(app_dsn())
    try:
        yield engine
    finally:
        engine.dispose()
