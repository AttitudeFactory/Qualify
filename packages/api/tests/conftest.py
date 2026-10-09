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


class FakeAsyncRedis:
    """In-memory stand-in for the `redis.asyncio` surface `inbox/sync_guard.py` uses —
    `set` (NX/PX/EX), `get`, and `eval` of its two compare-and-* scripts — with real
    expiry against a clock the test controls. Offline: CI's `test` job has no Redis."""

    def __init__(self) -> None:
        self.now = 0.0  # seconds; advance it to expire keys
        self._data: dict[str, tuple[str, float | None]] = {}
        self.fail_with: Exception | None = None  # set to make every call raise

    def _live(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and self.now >= expires_at:
            del self._data[key]
            return None
        return value

    def _check(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    async def set(
        self,
        name: str,
        value: str,
        *,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool | None:
        self._check()
        if nx and self._live(name) is not None:
            return None
        ttl = px / 1000 if px is not None else ex
        self._data[name] = (value, self.now + ttl if ttl is not None else None)
        return True

    async def get(self, name: str) -> str | None:
        self._check()
        return self._live(name)

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object:
        self._check()
        key, token, *rest = keys_and_args
        if self._live(key) != token:
            return 0
        if "pexpire" in script:
            self._data[key] = (token, self.now + int(rest[0]) / 1000)
            return 1
        del self._data[key]
        return 1

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_async_redis() -> FakeAsyncRedis:
    return FakeAsyncRedis()
