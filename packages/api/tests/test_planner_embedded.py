"""QUA-111 follow-up: the calendar worker embedded in the app process.

No DB, no Meta: the runner is a fake. Pinned here: the scope is still mandatory (no
default means "everyone"), `off` never starts, the thread ticks immediately, keeps
ticking, survives a failing tick, stops promptly, and reports whether a tenant is covered.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import UUID

import pytest

from qualify_api.planner.embedded import (
    ENV_INTERVAL,
    ENV_MODE,
    ENV_TENANTS,
    EmbeddedCalendarWorker,
    EmbeddedWorkerConfig,
    WorkerMode,
)
from qualify_api.planner.tick import TickReport

T1 = UUID("f7000000-0000-4000-8000-000000000001")
T2 = UUID("f7000000-0000-4000-8000-000000000002")


# --- configuration ------------------------------------------------------------------


@pytest.mark.parametrize("env", [{}, {ENV_TENANTS: ""}, {ENV_TENANTS: "all"}])
def test_the_default_is_every_connected_tenant_with_nothing_configured(
    env: dict[str, str],
) -> None:
    config = EmbeddedWorkerConfig.from_env(env)
    assert config.mode is WorkerMode.EMBEDDED and config.startable
    assert config.all_tenants and config.tenant_ids == ()
    assert config.covers(UUID(int=42))  # any tenant, including one created later


def test_off_mode_never_starts() -> None:
    config = EmbeddedWorkerConfig.from_env({ENV_MODE: "off", ENV_TENANTS: "all"})
    assert config.mode is WorkerMode.OFF and not config.startable
    assert not config.covers(T1)


def test_a_tenant_list_is_an_explicit_restriction() -> None:
    config = EmbeddedWorkerConfig.from_env({ENV_TENANTS: f" {T1} , {T2},{T1}"})
    assert config.startable and config.tenant_ids == (T1, T2)
    assert config.covers(T1) and config.covers(T2)
    assert not config.covers(UUID(int=7))


def test_all_tenants_scope() -> None:
    config = EmbeddedWorkerConfig.from_env({ENV_TENANTS: "ALL"})
    assert config.startable and config.all_tenants and config.covers(UUID(int=7))


@pytest.mark.parametrize(
    "env",
    [
        {ENV_TENANTS: "not-a-uuid"},
        {ENV_TENANTS: " , "},
        {ENV_MODE: "sometimes", ENV_TENANTS: "all"},
        {ENV_TENANTS: "all", ENV_INTERVAL: "5"},
        {ENV_TENANTS: "all", ENV_INTERVAL: "soon"},
    ],
)
def test_invalid_configs_refuse_to_start(env: dict[str, str]) -> None:
    config = EmbeddedWorkerConfig.from_env(env)
    assert not config.startable and config.problem


def test_interval_override() -> None:
    assert EmbeddedWorkerConfig.from_env({ENV_TENANTS: "all", ENV_INTERVAL: "30"}).interval == 30


# --- the thread ---------------------------------------------------------------------


class FakeRunner:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.ticks = 0
        self.ticked = threading.Event()
        self._fail_first = fail_first

    async def run_once(self) -> TickReport:
        self.ticks += 1
        self.ticked.set()
        if self._fail_first and self.ticks == 1:
            raise RuntimeError("tick blew up")
        return TickReport(started_at=datetime.now(UTC))


def _config(**overrides) -> EmbeddedWorkerConfig:
    base = {ENV_TENANTS: str(T1), ENV_INTERVAL: "30"}
    return EmbeddedWorkerConfig.from_env({**base, **overrides})


def test_start_ticks_immediately_and_stop_is_prompt() -> None:
    runner = FakeRunner()
    worker = EmbeddedCalendarWorker(_config(), make_runner=lambda: runner)
    assert worker.start()
    assert runner.ticked.wait(5), "the first tick runs at startup, not after an interval"
    status = worker.status()
    assert status.running and status.covers(T1) and not status.covers(T2)
    assert status.last_tick_at is not None and status.last_tick_error == ""

    started = datetime.now(UTC)
    worker.stop(timeout=5)
    # The worker was sleeping a 30 s interval: stop wakes it instead of waiting it out.
    assert (datetime.now(UTC) - started).total_seconds() < 5
    assert not worker.status().running and not worker.status().covers(T1)


def test_a_failing_tick_is_recorded_and_the_loop_keeps_going() -> None:
    runner = FakeRunner(fail_first=True)
    worker = EmbeddedCalendarWorker(
        EmbeddedWorkerConfig(WorkerMode.EMBEDDED, tenant_ids=(T1,), interval=0),
        make_runner=lambda: runner,
    )
    worker.start()
    try:
        deadline = datetime.now(UTC).timestamp() + 5
        while runner.ticks < 3 and datetime.now(UTC).timestamp() < deadline:
            threading.Event().wait(0.01)
        assert runner.ticks >= 3
        assert worker.status().running
    finally:
        worker.stop(timeout=5)


def test_start_is_idempotent_and_restartable() -> None:
    runner = FakeRunner()
    worker = EmbeddedCalendarWorker(_config(), make_runner=lambda: runner)
    assert worker.start() and worker.start()
    runner.ticked.wait(5)
    worker.stop(timeout=5)
    runner.ticked.clear()
    assert worker.start(), "a restart (app reload) starts a fresh loop"
    assert runner.ticked.wait(5)
    worker.stop(timeout=5)


@pytest.mark.parametrize("env", [{ENV_MODE: "off"}, {ENV_TENANTS: "not-a-uuid"}])
def test_a_worker_that_may_not_start_does_not(env: dict[str, str]) -> None:
    runner = FakeRunner()
    worker = EmbeddedCalendarWorker(_config(**env), make_runner=lambda: runner)
    assert not worker.start()
    assert not worker.status().running and not worker.status().covers(T1)
    assert runner.ticks == 0
