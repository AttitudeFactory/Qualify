"""The brand's own account in Postgres with a time to live (2026-10-01, "no quiero más
json"), per tenant, through `qualify_api.referentes.profile_cache` (here its memory
twin). The search's profile reads live in the shared pool: `test_creator_pool_provider`."""

from __future__ import annotations

import time
from uuid import UUID

from qualify_api.referentes.profile_cache import SNAPSHOT_TTL, MemoryProfileCacheRepository

from . import creator_cache_provider as cache
from .scrapecreators_client import SNAPSHOT_SCHEMA

TENANT = UUID("a0000000-0000-4000-8000-0000000000d1")
OTHER = UUID("a0000000-0000-4000-8000-0000000000d2")


def test_the_brands_account_is_remembered_per_tenant_for_a_week() -> None:
    repo = MemoryProfileCacheRepository()
    now = time.time()
    profile = {"username": "nibbles", "followers": 10, "fetchedAt": now}
    cache.remember_snapshot(TENANT, "tiktok", "@Nibbles", profile, repository=repo)
    assert cache.cached_snapshot(TENANT, "tiktok", "nibbles", repository=repo) == profile
    assert cache.cached_snapshot(OTHER, "tiktok", "nibbles", repository=repo) is None
    entry = repo.entries[(TENANT, "tiktok", "nibbles", "snapshot")]
    assert entry.expires_at - entry.fetched_at == SNAPSHOT_TTL
    assert entry.document["schema"] == SNAPSHOT_SCHEMA
    # past its time to live: a miss
    assert repo.get(TENANT, "tiktok", "nibbles", "snapshot", now=now + 8 * 86_400) is None
    # written by an older normalizer: a miss too
    repo.put(TENANT, "tiktok", "old", "snapshot", {"schema": SNAPSHOT_SCHEMA - 1, "profile": {}})
    assert cache.cached_snapshot(TENANT, "tiktok", "old", repository=repo) is None
