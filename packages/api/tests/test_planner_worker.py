"""QUA-111: the calendar worker (`planner.worker`) — when ticks run, not what they do.

No DB, no Meta: the runner is a fake that counts ticks. What is pinned here is the
runtime contract — explicit scope, `--once`, a start-to-start cadence that never sleeps
inside a tick, errors that never stop the loop, Ctrl+C that exits cleanly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qualify_api.planner import worker
from qualify_api.planner.tick import TenantReport, TickReport

TENANT = UUID("f6000000-0000-4000-8000-000000000001")


class FakeRunner:
    def __init__(self, *, fails: list[bool] | None = None, tick_error: str = "") -> None:
        self.ticks = 0
        self._fails = list(fails or [])
        self._tick_error = tick_error

    async def run_once(self) -> TickReport:
        self.ticks += 1
        if self._fails and self._fails.pop(0):
            raise RuntimeError("tick blew up")
        report = TickReport(started_at=datetime.now(UTC), error=self._tick_error)
        report.tenants.append(TenantReport(tenant_id=TENANT))
        return report


class FakeClock:
    """Each tick 'takes' `tick_seconds`; sleeps advance the clock and are recorded."""

    def __init__(self, tick_seconds: float = 5.0) -> None:
        self.now = 0.0
        self.tick_seconds = tick_seconds
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# --- scope is mandatory -----------------------------------------------------------


def test_a_scope_is_required() -> None:
    with pytest.raises(SystemExit):
        worker.build_parser().parse_args([])


def test_tenant_and_all_tenants_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        worker.build_parser().parse_args(["--tenant", str(TENANT), "--all-tenants"])


def test_an_interval_below_the_minimum_is_refused() -> None:
    with pytest.raises(SystemExit):
        worker.main(["--tenant", str(TENANT), "--interval", "5"])


def test_tenant_scope_builds_the_scoped_runner_with_exactly_those_tenants() -> None:
    seen: list[list[UUID]] = []
    other = uuid4()

    def scoped(tenant_ids):
        seen.append(list(tenant_ids))
        return FakeRunner()

    def production():
        raise AssertionError("the production discovery must not be built for --tenant")

    code = worker.main(
        ["--tenant", str(TENANT), "--tenant", str(other), "--tenant", str(TENANT), "--once"],
        scoped=scoped,
        production=production,
    )
    assert code == 0
    assert seen == [[TENANT, other]]


def test_all_tenants_builds_the_production_runner() -> None:
    built: list[FakeRunner] = []

    def production():
        built.append(FakeRunner())
        return built[-1]

    def scoped(_):
        raise AssertionError("--all-tenants must not build a scoped runner")

    assert worker.main(["--all-tenants", "--once"], scoped=scoped, production=production) == 0
    assert len(built) == 1 and built[0].ticks == 1


# --- --once --------------------------------------------------------------------------


async def test_once_runs_exactly_one_tick_and_never_sleeps() -> None:
    runner, clock = FakeRunner(), FakeClock()
    code = await worker.run_worker(lambda: runner, once=True, sleep=clock.sleep, clock=clock)
    assert code == 0 and runner.ticks == 1 and clock.sleeps == []


async def test_once_exits_1_when_the_tick_could_not_list_its_tenants() -> None:
    runner = FakeRunner(tick_error="RuntimeError")
    assert await worker.run_worker(lambda: runner, once=True) == 1


async def test_once_exits_1_when_the_tick_raised() -> None:
    runner = FakeRunner(fails=[True])
    assert await worker.run_worker(lambda: runner, once=True) == 1


# --- the loop --------------------------------------------------------------------------


async def test_the_loop_ticks_start_to_start_at_the_interval() -> None:
    runner, clock = FakeRunner(), FakeClock()

    async def run_once_taking_time():
        clock.now += 12  # this tick took 12 s of wall time
        return await FakeRunner.run_once(runner)

    runner.run_once = run_once_taking_time  # type: ignore[method-assign]
    code = await worker.run_worker(
        lambda: runner, once=False, interval=60, sleep=clock.sleep, clock=clock, max_ticks=3
    )
    assert code == 0 and runner.ticks == 3
    assert clock.sleeps == [48, 48]  # 60 − 12, between ticks only


async def test_a_tick_longer_than_the_interval_does_not_sleep_negative() -> None:
    runner, clock = FakeRunner(), FakeClock()

    async def slow_tick():
        clock.now += 90
        return await FakeRunner.run_once(runner)

    runner.run_once = slow_tick  # type: ignore[method-assign]
    await worker.run_worker(
        lambda: runner, once=False, interval=60, sleep=clock.sleep, clock=clock, max_ticks=2
    )
    assert clock.sleeps == [0.0]


async def test_a_failing_tick_never_stops_the_loop() -> None:
    runner, clock = FakeRunner(fails=[True, False, True]), FakeClock()
    code = await worker.run_worker(
        lambda: runner, once=False, interval=60, sleep=clock.sleep, clock=clock, max_ticks=3
    )
    assert code == 0 and runner.ticks == 3


async def test_the_runner_is_built_once_for_the_whole_loop() -> None:
    builds: list[FakeRunner] = []

    def make():
        builds.append(FakeRunner())
        return builds[-1]

    clock = FakeClock()
    await worker.run_worker(
        make, once=False, interval=60, sleep=clock.sleep, clock=clock, max_ticks=3
    )
    assert len(builds) == 1 and builds[0].ticks == 3


def test_ctrl_c_exits_cleanly(monkeypatch) -> None:
    def interrupted(coro):
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(worker.asyncio, "run", interrupted)
    code = worker.main(
        ["--tenant", str(TENANT)], scoped=lambda _: FakeRunner(), production=FakeRunner
    )
    assert code == 0


def test_ctrl_c_builds_the_daily_chore_without_running_it(monkeypatch) -> None:
    """The default chore is built at start (no R2 needed until it runs)."""

    def interrupted(coro):
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(worker.asyncio, "run", interrupted)
    assert worker.main(["--all-tenants"], scoped=lambda _: FakeRunner(), production=FakeRunner) == 0


# --- piece retention chore (m-24828907) ------------------------------------------------


async def test_the_chore_runs_first_and_then_once_a_day_never_blocking_ticks() -> None:
    runner, clock = FakeRunner(), FakeClock()
    runs: list[float] = []
    code = await worker.run_worker(
        lambda: runner,
        once=False,
        interval=60,
        sleep=clock.sleep,
        clock=clock,
        max_ticks=4,
        chore=lambda: runs.append(clock.now),
        chore_every=120,
    )
    assert code == 0 and runner.ticks == 4
    assert runs == [0.0, 120.0]  # at start, then after `chore_every`


async def test_a_failing_chore_never_stops_the_ticks() -> None:
    runner, clock = FakeRunner(), FakeClock()

    def boom() -> None:
        raise RuntimeError("R2 not configured")

    code = await worker.run_worker(
        lambda: runner,
        once=False,
        interval=60,
        sleep=clock.sleep,
        clock=clock,
        max_ticks=2,
        chore=boom,
    )
    assert code == 0 and runner.ticks == 2


async def test_once_never_runs_the_chore() -> None:
    runs: list[int] = []
    await worker.run_worker(lambda: FakeRunner(), once=True, chore=lambda: runs.append(1))
    assert runs == []


def test_purge_pieces_runs_once_for_the_scope_without_ticking() -> None:
    calls: list[tuple[list[UUID] | None, bool]] = []

    def never(*_):
        raise AssertionError("--purge-pieces must not build a tick runner")

    code = worker.main(
        ["--tenant", str(TENANT), "--purge-pieces"],
        scoped=never,
        production=never,
        purge=lambda ids, execute: calls.append((ids, execute)),
    )
    assert code == 0 and calls == [([TENANT], False)]
    assert (
        worker.main(
            ["--all-tenants", "--purge-pieces", "--execute"],
            scoped=never,
            production=never,
            purge=lambda ids, execute: calls.append((ids, execute)),
        )
        == 0
    )
    assert calls[-1] == (None, True)


def test_a_failing_purge_exits_1() -> None:
    def boom(*_):
        raise RuntimeError("R2 down")

    assert worker.main(["--tenant", str(TENANT), "--purge-pieces"], purge=boom) == 1


def test_execute_without_purge_pieces_is_refused() -> None:
    with pytest.raises(SystemExit):
        worker.main(["--tenant", str(TENANT), "--once", "--execute"])


async def test_should_stop_ends_the_loop_between_ticks() -> None:
    runner = FakeRunner()
    clock = FakeClock()
    code = await worker.run_worker(
        lambda: runner,
        once=False,
        interval=60,
        sleep=clock.sleep,
        clock=clock,
        should_stop=lambda: runner.ticks >= 2,
    )
    assert code == 0 and runner.ticks == 2
