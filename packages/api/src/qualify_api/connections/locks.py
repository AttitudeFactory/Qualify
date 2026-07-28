"""Distributed refresh lock (C-03.4). Instagram long-lived tokens refresh onto
themselves; two concurrent refreshes can invalidate the token and silently disconnect
the client. So exactly ONE refresh is in flight per connection, guarded by a Redis lock
namespaced by tenant AND connection (§1.3).

The lock is `SET key token NX EX ttl` (atomic acquire) plus a compare-and-delete release
(a Lua script that deletes only if the value still matches our token) so a slow holder
whose TTL already expired cannot delete a lock a second worker now owns.

Holding the lock is not enough on its own (my QUA-15 finding): two SERIAL contenders would
both refresh. The caller must double-check inside the lock — re-read the credential and
skip if it was already refreshed. `run_refresh` wires that in.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol
from uuid import UUID, uuid4

# Delete the key only if it still holds our token (release must not stomp a re-acquired lock).
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class RedisLike(Protocol):
    """The subset of redis-py used here (the real `redis.Redis` satisfies it)."""

    def set(
        self, name: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None: ...

    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object: ...


class RefreshLock:
    def __init__(self, redis: RedisLike, *, ttl_seconds: int = 30) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(tenant_id: UUID, connection_id: UUID) -> str:
        return f"refresh:{tenant_id}:{connection_id}"

    @contextmanager
    def acquire(self, tenant_id: UUID, connection_id: UUID) -> Iterator[bool]:
        """Yield True iff the lock was obtained. Always releases (compare-and-delete) on
        exit if it was ours. A contender that does not get the lock yields False and must
        not refresh."""
        key = self._key(tenant_id, connection_id)
        token = uuid4().hex
        acquired = bool(self._redis.set(key, token, nx=True, ex=self._ttl))
        try:
            yield acquired
        finally:
            if acquired:
                self._redis.eval(_RELEASE_SCRIPT, 1, key, token)


def run_refresh(
    lock: RefreshLock,
    *,
    tenant_id: UUID,
    connection_id: UUID,
    already_fresh: Callable[[], bool],
    do_refresh: Callable[[], None],
) -> bool:
    """Double-checked refresh: take the lock, re-check freshness INSIDE it, and refresh
    only if still stale. Returns True if a refresh ran, False if it was skipped (lock not
    obtained, or a concurrent worker already refreshed)."""
    with lock.acquire(tenant_id, connection_id) as got:
        if not got:
            return False
        if already_fresh():
            return False
        do_refresh()
        return True
