"""`inbox/sync_guard.py` — one comment sync per connection, offline against the in-memory
Redis in `conftest.py`. What is pinned here is the property the CRM relies on to clear a
leftover `is_syncing`: a lease disappears only when its holder stops renewing it."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from qualify_api.inbox.sync_guard import SyncAlreadyRunning, SyncGuard

TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT = UUID("22222222-2222-4222-8222-222222222222")
CONNECTION = UUID("33333333-3333-4333-8333-333333333333")
IDS = {"tenant_id": TENANT, "connection_id": CONNECTION}


@pytest.mark.asyncio
async def test_a_second_run_cannot_take_a_held_lease(fake_async_redis) -> None:
    guard = SyncGuard(fake_async_redis)
    lease = await guard.acquire(**IDS, token="run-a")
    with pytest.raises(SyncAlreadyRunning):
        await guard.acquire(**IDS, token="run-b")
    await lease.release()


@pytest.mark.asyncio
async def test_release_frees_the_lease_and_only_its_own(fake_async_redis) -> None:
    guard = SyncGuard(fake_async_redis)
    lease = await guard.acquire(**IDS, token="run-a")
    await lease.release()
    assert not await guard.is_running(**IDS, token="run-a")

    # A run whose lease lapsed and was re-taken by another must not delete the new one.
    stale = await guard.acquire(**IDS, token="run-a")
    fake_async_redis.now += 60  # run-a stopped renewing (its heartbeat is cancelled below)
    stale._heartbeat.cancel()
    fresh = await guard.acquire(**IDS, token="run-b")
    await stale.release()
    assert await guard.is_running(**IDS, token="run-b")
    await fresh.release()


@pytest.mark.asyncio
async def test_is_running_names_the_holder_only(fake_async_redis) -> None:
    guard = SyncGuard(fake_async_redis)
    lease = await guard.acquire(**IDS, token="run-a")
    assert await guard.is_running(**IDS, token="run-a")
    assert not await guard.is_running(**IDS, token="run-b")
    await lease.release()


@pytest.mark.asyncio
async def test_a_dead_holder_frees_the_lease_by_expiry(fake_async_redis) -> None:
    """No renewals = a crashed process: the lease expires and a new run may take it."""
    guard = SyncGuard(fake_async_redis, ttl_ms=30_000)
    lease = await guard.acquire(**IDS, token="run-a")
    lease._heartbeat.cancel()  # the process died: nobody renews any more
    fake_async_redis.now += 31
    assert not await guard.is_running(**IDS, token="run-a")
    await (await guard.acquire(**IDS, token="run-b")).release()


@pytest.mark.asyncio
async def test_a_live_holder_keeps_its_lease_past_the_ttl(fake_async_redis) -> None:
    """The heartbeat is what separates "slow" from "dead": a run still executing renews
    its lease, so it is never reclaimable by age."""
    guard = SyncGuard(fake_async_redis, ttl_ms=30)  # renews every 10 ms
    lease = await guard.acquire(**IDS, token="run-a")
    for _ in range(5):  # 5 x 20 ms of "work", well past the 30 ms TTL
        await asyncio.sleep(0.02)
        fake_async_redis.now += 0.02
    assert await guard.is_running(**IDS, token="run-a")
    await lease.release()


@pytest.mark.asyncio
async def test_leases_are_per_tenant_and_connection(fake_async_redis) -> None:
    guard = SyncGuard(fake_async_redis)
    lease = await guard.acquire(**IDS, token="run-a")
    other = await guard.acquire(tenant_id=OTHER_TENANT, connection_id=CONNECTION, token="run-b")
    await other.release()
    await lease.release()


@pytest.mark.asyncio
async def test_last_finished_age(fake_async_redis) -> None:
    guard = SyncGuard(fake_async_redis)
    assert await guard.seconds_since_last_finished(**IDS, now=1_000.0) is None
    await guard.mark_finished(**IDS, now=1_000.0)
    assert await guard.seconds_since_last_finished(**IDS, now=1_042.5) == 42.5
