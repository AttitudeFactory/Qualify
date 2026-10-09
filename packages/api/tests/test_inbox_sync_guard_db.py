"""`inbox/sync_guard.py` against a REAL Redis (`-m db`, the compose/CI Redis on a non-zero
db): the offline suite's in-memory double imitates the two Lua scripts, this file runs
them. Each test uses its own random connection id, so nothing collides or needs cleanup
beyond what the leases release themselves."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from qualify_api.config import redis_url
from qualify_api.inbox.sync_guard import SyncAlreadyRunning, SyncGuard

pytestmark = pytest.mark.db


@pytest.mark.asyncio
async def test_lease_lifecycle_on_real_redis() -> None:
    client = aioredis.Redis.from_url(redis_url(), decode_responses=True)
    try:
        guard = SyncGuard(client, ttl_ms=300)  # renews every 100 ms
        ids = {"tenant_id": uuid4(), "connection_id": uuid4()}

        lease = await guard.acquire(**ids, token="run-a")
        with pytest.raises(SyncAlreadyRunning):
            await guard.acquire(**ids, token="run-b")

        await asyncio.sleep(0.8)  # well past the 300 ms TTL: only renewals keep it
        assert await guard.is_running(**ids, token="run-a")

        await lease.release()
        assert not await guard.is_running(**ids, token="run-a")
        await (await guard.acquire(**ids, token="run-b")).release()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_dead_holder_expires_and_cannot_delete_its_successor() -> None:
    client = aioredis.Redis.from_url(redis_url(), decode_responses=True)
    try:
        guard = SyncGuard(client, ttl_ms=200)
        ids = {"tenant_id": uuid4(), "connection_id": uuid4()}

        dead = await guard.acquire(**ids, token="run-a")
        dead._heartbeat.cancel()  # the process died: no more renewals
        await asyncio.sleep(0.35)
        assert not await guard.is_running(**ids, token="run-a")

        successor = await guard.acquire(**ids, token="run-b")
        await dead.release()  # compare-and-delete: must not remove run-b's lease
        assert await guard.is_running(**ids, token="run-b")
        await successor.release()
    finally:
        await client.aclose()
