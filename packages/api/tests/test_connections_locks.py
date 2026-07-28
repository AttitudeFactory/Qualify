"""Pure refresh-lock tests (C-03.4) against a minimal fake Redis: single holder, compare-
and-delete release, and double-checked refresh (serial contenders don't both refresh)."""

from __future__ import annotations

from uuid import UUID

from qualify_api.connections.locks import RefreshLock, run_refresh

TENANT = UUID("22222222-2222-2222-2222-222222222222")
CONN = UUID("33333333-3333-3333-3333-333333333333")


class FakeRedis:
    """Implements just the surface RefreshLock uses: SET NX EX and the compare-and-delete
    Lua eval. TTL is ignored (tests are synchronous)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, name: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True

    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> int:
        # Only the release script: del key iff its value equals the caller's token.
        key = keys_and_args[0]
        token = keys_and_args[1]
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


def test_single_holder_blocks_second_contender() -> None:
    redis = FakeRedis()
    lock = RefreshLock(redis)
    with lock.acquire(TENANT, CONN) as first:
        assert first is True
        with lock.acquire(TENANT, CONN) as second:
            assert second is False  # already held
    # Released on exit → re-acquirable.
    with lock.acquire(TENANT, CONN) as third:
        assert third is True


def test_release_is_compare_and_delete() -> None:
    redis = FakeRedis()
    lock = RefreshLock(redis)
    key = f"refresh:{TENANT}:{CONN}"
    with lock.acquire(TENANT, CONN):
        # Simulate the TTL expiring and another worker taking the lock under a new token.
        redis.store[key] = "someone-elses-token"
    # Our release must NOT have deleted the other worker's lock.
    assert redis.store.get(key) == "someone-elses-token"


def test_double_checked_refresh_skips_when_already_fresh() -> None:
    redis = FakeRedis()
    lock = RefreshLock(redis)
    calls: list[str] = []
    ran = run_refresh(
        lock,
        tenant_id=TENANT,
        connection_id=CONN,
        already_fresh=lambda: True,  # a concurrent worker already refreshed
        do_refresh=lambda: calls.append("refresh"),
    )
    assert ran is False
    assert calls == []


def test_double_checked_refresh_runs_when_stale() -> None:
    redis = FakeRedis()
    lock = RefreshLock(redis)
    calls: list[str] = []
    ran = run_refresh(
        lock,
        tenant_id=TENANT,
        connection_id=CONN,
        already_fresh=lambda: False,
        do_refresh=lambda: calls.append("refresh"),
    )
    assert ran is True
    assert calls == ["refresh"]
