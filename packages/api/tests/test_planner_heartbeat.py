"""The calendar worker heartbeat (QUA-118): the Planificador shows automatic publishing
as available when SOME worker process — the embedded one or the production
`calendar-worker` container — beats for the tenant, not only the one in its own process."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID

from qualify_api.planner import worker
from qualify_api.planner.embedded import EmbeddedCalendarWorker, EmbeddedWorkerConfig, WorkerMode
from qualify_api.planner.heartbeat import (
    GRACE_SECONDS,
    STALE_AFTER_INTERVALS,
    Heartbeat,
    MemoryHeartbeatStore,
    RedisHeartbeatStore,
    record_beat,
    worker_covers,
)
from qualify_api.planner.tick import TickReport

T1 = UUID("f7000000-0000-4000-8000-000000000001")
T2 = UUID("f7000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 10, 6, 22, 0, tzinfo=UTC)


def _beat(*, all_tenants: bool = False, ids=(T1,), age: float = 0, error: str = "") -> Heartbeat:
    return Heartbeat("host:1", all_tenants, tuple(ids), 60, NOW - timedelta(seconds=age), error)


# --- one beat ---------------------------------------------------------------------


def test_a_fresh_scoped_beat_covers_only_its_tenants() -> None:
    beat = _beat()
    assert beat.covers(T1, NOW) and not beat.covers(T2, NOW)


def test_an_all_tenants_beat_covers_every_tenant() -> None:
    assert _beat(all_tenants=True, ids=()).covers(T2, NOW)


def test_a_slow_tick_keeps_it_fresh_a_dead_worker_does_not() -> None:
    limit = 60 * STALE_AFTER_INTERVALS + GRACE_SECONDS
    assert _beat(age=limit).covers(T1, NOW)
    assert not _beat(age=limit + 1).covers(T1, NOW)


def test_a_tick_that_failed_as_a_whole_does_not_cover() -> None:
    assert not _beat(error="tenant_listing_failed").covers(T1, NOW)


def test_json_round_trip_and_garbage_is_ignored() -> None:
    for beat in (_beat(), _beat(all_tenants=True, ids=())):
        assert Heartbeat.from_json(beat.worker_id, beat.to_json()) == beat
    assert Heartbeat.from_json("x", "not json") is None
    assert Heartbeat.from_json("x", '{"scope": "all", "interval": 60}') is None


# --- reading / writing -------------------------------------------------------------


def test_any_live_worker_covers_and_none_means_unavailable() -> None:
    store = MemoryHeartbeatStore()
    assert not worker_covers(store, T1, NOW)
    record_beat(store, all_tenants=False, tenant_ids=(T1,), interval=60, error="", now=NOW)
    assert worker_covers(store, T1, NOW) and not worker_covers(store, T2, NOW)
    assert not worker_covers(store, T1, NOW + timedelta(hours=1))
    assert not worker_covers(None, T1, NOW)


class BrokenStore:
    def write(self, beat: Heartbeat) -> None:
        raise ConnectionError("redis down")

    def read_all(self) -> list[Heartbeat]:
        raise ConnectionError("redis down")


def test_a_redis_failure_never_raises() -> None:
    record_beat(BrokenStore(), all_tenants=True, tenant_ids=(), interval=60, error="")
    assert not worker_covers(BrokenStore(), T1, NOW)


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttl: dict[str, int] = {}

    def pipeline(self) -> FakeRedis:
        return self

    def execute(self) -> None:
        return None

    def hset(self, key: str, field: str, value: str) -> None:
        self.hashes.setdefault(key, {})[field] = value

    def expire(self, key: str, seconds: int) -> None:
        self.ttl[key] = seconds

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    def hdel(self, key: str, *fields: str) -> None:
        for field in fields:
            self.hashes.get(key, {}).pop(field, None)


def test_redis_store_keeps_one_field_per_worker_and_prunes_long_dead_ones() -> None:
    client = FakeRedis()
    store = RedisHeartbeatStore(client, key="k")
    old = Heartbeat("old:7", True, (), 60, NOW - timedelta(days=2))
    client.hset("k", old.worker_id, old.to_json())
    store.write(_beat())
    store.write(Heartbeat("other:2", False, (T2,), 60, NOW))
    assert set(client.hashes["k"]) == {"host:1", "other:2"}
    assert client.ttl["k"] > 0
    assert worker_covers(store, T1, NOW) and worker_covers(store, T2, NOW)


# --- the two workers beat ----------------------------------------------------------


class FakeRunner:
    def __init__(self) -> None:
        self.ticked = threading.Event()

    async def run_once(self) -> TickReport:
        self.ticked.set()
        return TickReport(started_at=datetime.now(UTC))


def test_the_embedded_worker_beats_on_every_tick() -> None:
    store = MemoryHeartbeatStore()
    runner = FakeRunner()
    embedded = EmbeddedCalendarWorker(
        EmbeddedWorkerConfig(WorkerMode.EMBEDDED, tenant_ids=(T1,), interval=30),
        make_runner=lambda: runner,
        heartbeat=store,
    )
    embedded.start()
    try:
        assert runner.ticked.wait(5)
        deadline = datetime.now(UTC) + timedelta(seconds=5)
        while not store.beats and datetime.now(UTC) < deadline:
            threading.Event().wait(0.01)
    finally:
        embedded.stop(timeout=5)
    assert worker_covers(store, T1) and not worker_covers(store, T2)


def test_the_cli_worker_beats_with_its_scope() -> None:
    store = MemoryHeartbeatStore()
    code = worker.main(
        ["--tenant", str(T1), "--once"],
        scoped=lambda _ids: FakeRunner(),
        production=lambda: FakeRunner(),
        heartbeat=store,
    )
    assert code == 0
    (beat,) = store.beats.values()
    assert beat.tenant_ids == (T1,) and not beat.all_tenants and beat.interval == 60


def test_the_cli_all_tenants_worker_covers_everyone() -> None:
    store = MemoryHeartbeatStore()
    worker.main(
        ["--all-tenants", "--once"],
        scoped=lambda _ids: FakeRunner(),
        production=lambda: FakeRunner(),
        heartbeat=store,
    )
    assert worker_covers(store, T2)
