"""The weekly hashtag read as a one-business pilot inside the reels worker (m-25026378,
D3 of `docs/epica-etiquetas-publicaciones.md`): `hashtags.pilot` and the daily chore of
`ReelsWorker` (step 7). Offline: a fake ScrapeCreators (`httpx.MockTransport`), the
in-memory ledger the conftest installs, memory doors — nothing reaches a vendor or a
database."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.hashtags import MemoryHashtagRepository, pilot, weekly
from qualify_api.referentes import worker as cli
from qualify_api.referentes.reel_queue import MemoryReelQueue
from qualify_api.referentes.reel_schedule import ScheduledBrand
from qualify_api.referentes.reel_store import MemoryReelRunStore
from qualify_api.referentes.reel_worker import ReelsWorker

from .test_hashtag_weekly import Vendor, _ledger
from .test_referentes_reels_worker import SIX_AM, Clock, Runs, _opened, _ready

ON = {weekly.SWITCH_ENV: "1"}
PILOT = UUID("c0000000-0000-4000-8000-0000000000c3")
OTHER = UUID("d0000000-0000-4000-8000-0000000000d4")


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(weekly.API_KEY_ENV, "test-key-not-real")


class _NoQueue:
    """The reels worker's activity read: never consulted for an explicit list."""

    def __init__(self, active: Sequence[UUID] = ()) -> None:
        self.active = list(active)
        self.calls = 0

    def opened_brands(self, *, since: datetime) -> list[ScheduledBrand]:
        self.calls += 1
        return [ScheduledBrand(t, uuid4(), "America/Bogota", SIX_AM) for t in self.active]


class _Source(weekly.PostgresRubroSource):
    """Production's `businesses` (the explicit list as given, the activity gate only for
    None) over memory rubros instead of `tenant_session`."""

    def __init__(self, queue: _NoQueue, rubros: dict[UUID, weekly.BusinessRubro]) -> None:
        super().__init__(queue=queue)
        self.rubros = rubros
        self.reads = 0

    def rubro(self, tenant_id: UUID) -> weekly.BusinessRubro:
        self.reads += 1
        return self.rubros.get(tenant_id, weekly.BusinessRubro(tenant_id, ()))


def _rubro(tenant: UUID, *tags: str) -> weekly.BusinessRubro:
    return weekly.BusinessRubro(tenant, tags, "CO", uuid4())


def _real_tick(vendor: Vendor, source: weekly.RubroSource) -> pilot.Tick:
    """`weekly.run_tick` over memory doors and the fake vendor."""
    log = weekly.MemoryReadLog(_ledger())
    repo = MemoryHashtagRepository()
    claims = weekly.MemoryClaims()

    def tick(
        tenant_ids: Sequence[UUID] | None,
        *,
        now: datetime | None = None,
        env: Any = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> weekly.TickReport:
        return weekly.run_tick(
            tenant_ids,
            source=source,
            log=log,
            repository=repo,
            claims=claims,
            client_factory=vendor.client,
            now=now,
            env=env,
            should_stop=should_stop,
        )

    return tick


def _never(*_: Any, **__: Any) -> weekly.TickReport:
    raise AssertionError("the weekly pass must not run")


def _no_stop() -> bool:
    return False


# -- the allowlist ------------------------------------------------------------------------


def test_switch_off_reads_nothing_even_with_a_listed_business() -> None:
    for env in ({}, {weekly.SWITCH_ENV: "0"}, {pilot.TENANTS_ENV: str(PILOT)}):
        report = pilot.run_pilot(SIX_AM, should_stop=_no_stop, env=env, tick=_never)
        assert report.stopped == "switch_off" and report.outcomes == []


@pytest.mark.parametrize("listed", [None, "", " , ,", "not-a-uuid"])
def test_an_empty_allowlist_reads_nobody_with_the_switch_on(listed: str | None) -> None:
    env = dict(ON) if listed is None else {**ON, pilot.TENANTS_ENV: listed}
    report = pilot.run_pilot(SIX_AM, should_stop=_no_stop, env=env, tick=_never)
    assert report.stopped == pilot.NO_PILOT_TENANTS and report.outcomes == []


def test_invalid_entries_are_skipped_and_logged_without_their_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = f" {PILOT} , oops-typo, {PILOT}, {OTHER.hex.upper()} ,"
    with caplog.at_level(logging.WARNING, logger="qualify_api.hashtags.pilot"):
        assert pilot.pilot_tenants({pilot.TENANTS_ENV: raw}) == [PILOT, OTHER]
    assert "ignored 1 entries" in caplog.text and "oops-typo" not in caplog.text


def test_a_listed_business_the_reels_gate_calls_inactive_is_still_read() -> None:
    vendor = Vendor()
    queue = _NoQueue(active=[])  # nobody opened «Ideas para tus reels»
    source = _Source(queue, {PILOT: _rubro(PILOT, "shawarma", "falafel")})
    env = {**ON, pilot.TENANTS_ENV: str(PILOT)}
    report = pilot.run_pilot(SIX_AM, should_stop=_no_stop, env=env, tick=_real_tick(vendor, source))
    (outcome,) = report.outcomes
    assert outcome.tenant_id == PILOT and outcome.read == ["shawarma", "falafel"]
    assert vendor.tags() == ["shawarma", "falafel"] and queue.calls == 0


def test_an_active_business_not_listed_is_not_read() -> None:
    vendor = Vendor()
    queue = _NoQueue(active=[OTHER])  # active by the reels gate, but not in the pilot
    source = _Source(queue, {PILOT: _rubro(PILOT, "shawarma"), OTHER: _rubro(OTHER, "heladeria")})
    env = {**ON, pilot.TENANTS_ENV: str(PILOT)}
    report = pilot.run_pilot(SIX_AM, should_stop=_no_stop, env=env, tick=_real_tick(vendor, source))
    assert [o.tenant_id for o in report.outcomes] == [PILOT]
    assert vendor.tags() == ["shawarma"] and queue.calls == 0
    assert _ledger().of(OTHER) == []


# -- the stop signal ------------------------------------------------------------------------


def test_the_stop_signal_ends_the_pass_between_hashtags() -> None:
    vendor = Vendor()
    source = _Source(_NoQueue(), {PILOT: _rubro(PILOT, "uno", "dos", "tres")})
    stop = {"now": False}

    answer = vendor.handler

    def handler_then_stop(request: httpx.Request) -> httpx.Response:
        stop["now"] = True  # a SIGTERM lands while the first read is in flight
        return answer(request)

    vendor.handler = handler_then_stop  # type: ignore[method-assign]
    env = {**ON, pilot.TENANTS_ENV: str(PILOT)}
    report = pilot.run_pilot(
        SIX_AM, should_stop=lambda: stop["now"], env=env, tick=_real_tick(vendor, source)
    )
    assert vendor.tags() == ["uno"]  # the read in flight finishes, the rest wait
    assert report.stopped == weekly.STOPPING
    (outcome,) = report.outcomes
    assert outcome.read == ["uno"] and outcome.reason == weekly.STOPPING


def test_the_stop_signal_ends_the_pass_between_businesses() -> None:
    vendor = Vendor()
    second = uuid4()
    source = _Source(_NoQueue(), {PILOT: _rubro(PILOT, "uno"), second: _rubro(second, "dos")})
    calls = {"n": 0}

    def stop_after_first_business() -> bool:
        calls["n"] += 1
        return calls["n"] > 2  # before business 1, before its tag; then stop

    env = {**ON, pilot.TENANTS_ENV: f"{PILOT},{second}"}
    report = pilot.run_pilot(
        SIX_AM, should_stop=stop_after_first_business, env=env, tick=_real_tick(vendor, source)
    )
    assert vendor.tags() == ["uno"] and report.stopped == weekly.STOPPING
    assert [o.tenant_id for o in report.outcomes] == [PILOT] and source.reads == 1


# -- the daily chore inside the reels worker ------------------------------------------------


class _Chore:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[datetime] = []
        self.fail = fail

    def __call__(self, now: datetime) -> weekly.TickReport:
        self.calls.append(now)
        if self.fail:
            raise RuntimeError("database away")
        return weekly.TickReport()


def _worker(
    clock: Clock,
    chore: Callable[[datetime], Any] | None,
    *,
    runs: Runs | None = None,
    should_stop: Callable[[], bool] = _no_stop,
) -> tuple[ReelsWorker, MemoryReelRunStore]:
    store = MemoryReelRunStore()
    worker = ReelsWorker(
        MemoryReelQueue(store),
        store,
        run=runs or Runs(),
        ready=_ready,
        clock=clock,
        hashtags=chore,
        should_stop=should_stop,
    )
    return worker, store


def test_the_chore_runs_at_start_then_once_a_day() -> None:
    clock, chore = Clock(), _Chore()
    worker, _ = _worker(clock, chore)
    worker.pass_once(force_schedule=True)
    for minutes in (1, 60, 23 * 60 + 59):
        clock.now = SIX_AM + timedelta(minutes=minutes)
        assert worker.pass_once().hashtags is None
    assert chore.calls == [SIX_AM]
    clock.now = SIX_AM + timedelta(hours=24)
    assert worker.pass_once().hashtags is not None
    assert chore.calls == [SIX_AM, SIX_AM + timedelta(hours=24)]


def test_a_failing_chore_leaves_the_reels_loop_running() -> None:
    clock, chore, runs = Clock(), _Chore(fail=True), Runs()
    worker, store = _worker(clock, chore, runs=runs)
    _opened(store, UUID("a0000000-0000-4000-8000-0000000000a1"), days_ago=2)
    report = worker.pass_once(force_schedule=True)
    assert report.errors == ["hashtags:RuntimeError"]
    assert len(report.enqueued) == 1 and len(runs.started) == 1  # the reels pass went on
    clock.now = SIX_AM + timedelta(minutes=1)
    assert worker.pass_once().errors == [] and len(chore.calls) == 1  # tomorrow, not now


def test_a_failing_chore_does_not_stop_the_cli_loop() -> None:
    clock, chore = Clock(), _Chore(fail=True)
    worker, _ = _worker(clock, chore)
    passes = {"n": 0}

    class Stop:
        def is_set(self) -> bool:
            return False

        def wait(self, timeout: float | None = None) -> bool:
            passes["n"] += 1
            clock.now += timedelta(hours=25)  # the next pass is a new day: the chore again
            return passes["n"] >= 3

    assert cli.run_loop(worker, once=False, interval=5, stop=Stop()) == 0  # type: ignore[arg-type]
    assert len(chore.calls) == 3


def test_no_chore_once_a_stop_was_requested() -> None:
    clock, chore = Clock(), _Chore()
    worker, _ = _worker(clock, chore, should_stop=lambda: True)
    assert worker.pass_once(force_schedule=True).hashtags is None
    assert chore.calls == []


def test_with_the_switch_off_the_chore_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(weekly.SWITCH_ENV, raising=False)
    monkeypatch.setenv(pilot.TENANTS_ENV, str(PILOT))

    def no_db(*_: Any, **__: Any) -> Any:
        raise AssertionError("no database read with the switch off")

    monkeypatch.setattr(weekly, "tenant_session", no_db)
    clock = Clock()
    worker, _ = _worker(clock, cli._hashtag_chore(_no_stop))
    report = worker.pass_once(force_schedule=True)
    assert report.errors == [] and report.hashtags.stopped == "switch_off"


def test_only_the_all_tenants_service_runs_the_chore() -> None:
    def build(tenants: list[UUID] | None) -> ReelsWorker:
        return cli.production_worker(
            tenants, batch=1, schedule_every=timedelta(minutes=15), should_stop=_no_stop
        )

    assert build([PILOT])._hashtags is None
    assert build(None)._hashtags is not None
