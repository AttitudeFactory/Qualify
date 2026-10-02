"""The brand's own account cache (migration 0035): per tenant, with a time to live, keyed
by the real handle; the memory twin offline and Postgres (RLS) `db`-marked."""

from __future__ import annotations

import time
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session

from qualify_api.referentes.profile_cache import (
    SNAPSHOT_TTL,
    MemoryProfileCacheRepository,
    PostgresProfileCacheRepository,
)
from qualify_api.tenancy.models import Tenant

TENANT = UUID("a0000000-0000-4000-8000-0000000000e3")
OTHER = UUID("a0000000-0000-4000-8000-0000000000e4")


def test_entries_live_a_week_and_are_keyed_by_the_real_handle() -> None:
    repo = MemoryProfileCacheRepository()
    now = time.time()
    repo.put(TENANT, "instagram", "@Some.One", "snapshot", {"profile": {"f": 5}}, now=now)
    hit = repo.get(TENANT, "instagram", "some.one", "snapshot")
    assert hit is not None and hit.document == {"profile": {"f": 5}} and not hit.missing
    assert hit.expires_at - hit.fetched_at == SNAPSHOT_TTL
    assert repo.get(TENANT, "instagram", "someone", "snapshot") is None  # another account
    later = now + SNAPSHOT_TTL.total_seconds()
    assert repo.get(TENANT, "instagram", "some.one", "snapshot", now=later) is None
    with pytest.raises(ValueError):
        repo.put(TENANT, "youtube", "x", "snapshot", {})
    with pytest.raises(ValueError):
        repo.put(TENANT, "instagram", "x", "facts", {})  # the search's reads live in the pool


@pytest.fixture
def seeded_tenants() -> None:
    with admin_session() as session:
        for tid, name in ((TENANT, "A"), (OTHER, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"profile-cache-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )


@pytest.mark.db
def test_postgres_upserts_per_tenant_and_honours_the_ttl(seeded_tenants: None) -> None:
    repo = PostgresProfileCacheRepository()
    handle = f"c{uuid4().hex[:10]}"
    first = repo.put(TENANT, "instagram", handle, "snapshot", {"followers": 1})
    repo.put(TENANT, "instagram", handle, "snapshot", {"followers": 2})  # the same key: replaced
    hit = repo.get(TENANT, "instagram", handle, "snapshot")
    assert hit is not None and hit.document == {"followers": 2}
    assert hit.expires_at > first.fetched_at
    # the other tenant has its own entry, or none
    assert repo.get(OTHER, "instagram", handle, "snapshot") is None
    repo.put(OTHER, "instagram", handle, "snapshot", None, missing=True)
    assert repo.get(OTHER, "instagram", handle, "snapshot").missing is True  # type: ignore[union-attr]
    assert repo.get(TENANT, "instagram", handle, "snapshot").missing is False  # type: ignore[union-attr]
    # past the TTL nothing is served
    later = time.time() + SNAPSHOT_TTL.total_seconds()
    assert repo.get(TENANT, "instagram", handle, "snapshot", now=later) is None
