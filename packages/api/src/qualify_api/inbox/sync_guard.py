"""One comment sync per connection at a time, across tabs, users and processes.

## Why a Redis lease, not the Reflex `is_syncing` flag

`InboxState.is_syncing` is per browser tab and is persisted with the tab's state
(`.states/`), so it guards nothing between two tabs or two operators, and it survives a
server restart that killed the pass it stood for. It stays as UI state only; the real
mutual exclusion is this lease, keyed by tenant AND connection — same namespacing and
same acquire/release primitives `connections/locks.RefreshLock` already uses:

- acquire: `SET key token NX PX ttl` (atomic);
- release: compare-and-delete (Lua), so a holder whose lease already lapsed can never
  delete a lease another run now owns.

## Why a heartbeat, and why that is what makes a stale lease safe to reclaim

A fixed TTL alone forces a bad choice: short, and a slow-but-alive pass loses its lease
mid-walk (two passes run at once); long, and a crashed pass blocks syncing for minutes.
Instead the holder renews the lease every `ttl/3` while it runs (compare-and-expire, so
it only ever extends its OWN lease). A lease therefore expires only when its holder
stopped renewing — i.e. the process died — never because a live pass is merely slow.
That is the property the UI relies on to clear a leftover `is_syncing`: it asks
`is_running(token)`, and "not running" means no process is still executing that pass.

## What this is not

Not a rate limiter: the Meta call budget stays `InboxService`'s job (QUA-88). This only
removes REDUNDANT passes — two at once on one connection — plus a short cooldown the
automatic triggers consult (`seconds_since_last_finished`) so opening the screen right
after a pass does not immediately repeat it. A manual sync never consults the cooldown.

Nothing here is secret: keys hold a random run token and a timestamp, never a credential.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Final, Protocol
from uuid import UUID

_LOGGER = logging.getLogger(__name__)

# Lease length. A pass renews every `LEASE_TTL_MS / 3`, so a live pass keeps its lease
# with two renewals of slack; a dead one frees it within this long.
LEASE_TTL_MS: Final = 30_000
# How long the "last finished" timestamp is kept — only the recent past matters to a
# cooldown measured in seconds.
_LAST_FINISHED_TTL_S: Final = 3_600

_RELEASE_SCRIPT: Final = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

_RENEW_SCRIPT: Final = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
else
    return 0
end
"""


class AsyncRedisLike(Protocol):
    """The subset of `redis.asyncio.Redis` used here."""

    async def set(
        self,
        name: str,
        value: str,
        *,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool | None: ...

    async def get(self, name: str) -> str | None: ...

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object: ...


class SyncAlreadyRunning(Exception):
    """Another pass holds this connection's lease. Not an error to surface as a failure:
    the comments are being synced right now, just not by this call."""


def _lease_key(tenant_id: UUID, connection_id: UUID) -> str:
    return f"inbox-sync:lease:{tenant_id}:{connection_id}"


def _last_finished_key(tenant_id: UUID, connection_id: UUID) -> str:
    return f"inbox-sync:last:{tenant_id}:{connection_id}"


class Lease:
    """A held lease plus the task renewing it. `release()` stops the renewals and
    deletes the key only if it is still ours."""

    def __init__(
        self, redis: AsyncRedisLike, key: str, token: str, heartbeat: asyncio.Task
    ) -> None:
        self._redis = redis
        self._key = key
        self._token = token
        self._heartbeat = heartbeat

    async def release(self) -> None:
        self._heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._heartbeat
        await self._redis.eval(_RELEASE_SCRIPT, 1, self._key, self._token)


class SyncGuard:
    def __init__(self, redis: AsyncRedisLike, *, ttl_ms: int = LEASE_TTL_MS) -> None:
        self._redis = redis
        self._ttl_ms = ttl_ms

    async def acquire(self, *, tenant_id: UUID, connection_id: UUID, token: str) -> Lease:
        """Take the connection's lease and start renewing it. Raises
        `SyncAlreadyRunning` when another run holds it."""
        key = _lease_key(tenant_id, connection_id)
        if not await self._redis.set(key, token, nx=True, px=self._ttl_ms):
            raise SyncAlreadyRunning(str(connection_id))
        heartbeat = asyncio.create_task(self._renew_until_cancelled(key, token))
        return Lease(self._redis, key, token, heartbeat)

    async def _renew_until_cancelled(self, key: str, token: str) -> None:
        interval = self._ttl_ms / 3 / 1000
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await self._redis.eval(_RENEW_SCRIPT, 1, key, token, str(self._ttl_ms))
            except Exception as exc:  # noqa: BLE001 - a failed renewal must not kill the pass
                _LOGGER.warning("inbox.sync.lease_renew_failed error=%s", type(exc).__name__)
                continue
            if not renewed:
                # Should not happen while renewals keep pace; the pass still finishes
                # (it is idempotent) but another run may now hold the lease.
                _LOGGER.warning("inbox.sync.lease_lost")
                return

    async def is_running(self, *, tenant_id: UUID, connection_id: UUID, token: str) -> bool:
        """Whether the run identified by `token` still holds the lease — i.e. a process
        is still executing it (see the module docstring for why that is exact)."""
        return await self._redis.get(_lease_key(tenant_id, connection_id)) == token

    async def mark_finished(self, *, tenant_id: UUID, connection_id: UUID, now: float) -> None:
        await self._redis.set(
            _last_finished_key(tenant_id, connection_id), repr(now), ex=_LAST_FINISHED_TTL_S
        )

    async def seconds_since_last_finished(
        self, *, tenant_id: UUID, connection_id: UUID, now: float
    ) -> float | None:
        """`None` when no pass finished within the last hour (or the value is unreadable)."""
        raw = await self._redis.get(_last_finished_key(tenant_id, connection_id))
        if raw is None:
            return None
        try:
            return max(0.0, now - float(raw))
        except ValueError:
            return None


def wall_clock() -> float:
    """Epoch seconds — wall clock, not monotonic, because the value is shared across
    processes through Redis."""
    return time.time()
