"""WA-08 — the WhatsApp worker (`whatsapp/worker.py`): WHEN and FOR WHOM passes run.

No DB, no Meta: the sender is a fake that counts passes. Pinned here: scope is mandatory
and explicit, `--once`, a start-to-start cadence, one tenant's failure never stops the
others, and the two production declarations (`justfile`, `docker-compose.prod.yml`) —
the worker must be always-on in production and always `--tenant` locally.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qualify_api.whatsapp import worker
from qualify_api.whatsapp.outbox import DEFAULT_BATCH, SendReport

TENANT = UUID("f8000000-0000-4000-8000-000000000001")
OTHER = UUID("f8000000-0000-4000-8000-000000000002")
REPO_ROOT = Path(__file__).resolve().parents[3]


class FakeSender:
    def __init__(self, *, fail_for: set[UUID] | None = None) -> None:
        self.calls: list[tuple[UUID, int]] = []
        self._fail_for = fail_for or set()

    async def run_once(self, tenant_id: UUID, *, limit: int = DEFAULT_BATCH) -> SendReport:
        self.calls.append((tenant_id, limit))
        if tenant_id in self._fail_for:
            raise RuntimeError("tenant blew up")
        return SendReport(tenant_id=tenant_id, claimed=1, sent=1)


class FakeRunner:
    def __init__(self, *, fails: list[bool] | None = None, tick_error: str = "") -> None:
        self.ticks = 0
        self._fails = list(fails or [])
        self._tick_error = tick_error

    async def run_once(self) -> worker.TickReport:
        self.ticks += 1
        if self._fails and self._fails.pop(0):
            raise RuntimeError("pass blew up")
        return worker.TickReport(started_at=datetime.now(UTC), error=self._tick_error)


class FakeClock:
    def __init__(self, tick_seconds: float = 0.5) -> None:
        self.now = 0.0
        self.tick_seconds = tick_seconds
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class ExplodingTenants:
    def tenants(self, *, now: datetime) -> list[UUID]:
        raise ConnectionError("no database")


# --- scope is mandatory ------------------------------------------------------------------


def test_a_scope_is_required() -> None:
    with pytest.raises(SystemExit):
        worker.build_parser().parse_args([])


def test_tenant_and_all_tenants_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        worker.build_parser().parse_args(["--tenant", str(TENANT), "--all-tenants"])


def test_an_interval_below_the_minimum_is_refused() -> None:
    with pytest.raises(SystemExit):
        worker.main(["--tenant", str(TENANT), "--interval", "0"])


def test_a_limit_below_one_is_refused() -> None:
    with pytest.raises(SystemExit):
        worker.main(["--tenant", str(TENANT), "--limit", "0"])


def test_defaults_are_a_five_second_cadence_and_the_senders_batch() -> None:
    args = worker.build_parser().parse_args(["--all-tenants"])
    assert (args.interval, args.limit, args.once) == (5, DEFAULT_BATCH, False)


def test_tenant_scope_builds_the_scoped_runner_with_exactly_those_tenants() -> None:
    seen: list[list[UUID]] = []

    def scoped(tenant_ids):
        seen.append(list(tenant_ids))
        return FakeRunner()

    def production():
        raise AssertionError("the production discovery must not be built for --tenant")

    code = worker.main(
        ["--tenant", str(TENANT), "--tenant", str(OTHER), "--tenant", str(TENANT), "--once"],
        scoped=scoped,
        production=production,
    )
    assert code == 0
    assert seen == [[TENANT, OTHER]]


def test_all_tenants_builds_the_production_runner() -> None:
    built: list[FakeRunner] = []

    def production():
        built.append(FakeRunner())
        return built[-1]

    def scoped(_):
        raise AssertionError("--all-tenants must not build a scoped runner")

    assert worker.main(["--all-tenants", "--once"], scoped=scoped, production=production) == 0
    assert len(built) == 1 and built[0].ticks == 1


def test_scoped_tenants_refuse_an_empty_scope_and_dedupe() -> None:
    with pytest.raises(ValueError):
        worker.ScopedTenants([])
    source = worker.ScopedTenants([TENANT, OTHER, TENANT])
    assert source.tenants(now=datetime.now(UTC)) == [TENANT, OTHER]


# --- one pass ----------------------------------------------------------------------------


async def test_a_pass_runs_every_tenant_in_scope_with_the_limit() -> None:
    sender = FakeSender()
    tick = worker.OutboxTick(tenants=worker.ScopedTenants([TENANT, OTHER]), sender=sender, limit=7)
    report = await tick.run_once()
    assert sender.calls == [(TENANT, 7), (OTHER, 7)]
    assert [t.tenant_id for t in report.tenants] == [TENANT, OTHER]
    assert report.error == ""


async def test_one_tenants_failure_is_reported_and_the_next_tenant_still_runs() -> None:
    sender = FakeSender(fail_for={TENANT})
    tick = worker.OutboxTick(tenants=worker.ScopedTenants([TENANT, OTHER]), sender=sender)
    report = await tick.run_once()
    assert [c[0] for c in sender.calls] == [TENANT, OTHER]
    failed, ok = report.tenants
    assert failed.tenant_id == TENANT and failed.errors == ["RuntimeError"] and failed.sent == 0
    assert ok.tenant_id == OTHER and ok.sent == 1
    assert report.error == ""  # the pass itself ran


async def test_a_pass_that_cannot_list_tenants_is_the_only_pass_level_error() -> None:
    sender = FakeSender()
    report = await worker.OutboxTick(tenants=ExplodingTenants(), sender=sender).run_once()
    assert report.error == "ConnectionError" and report.tenants == [] and sender.calls == []


# --- --once and the loop ------------------------------------------------------------------


async def test_once_runs_exactly_one_pass_and_never_sleeps() -> None:
    runner, clock = FakeRunner(), FakeClock()
    code = await worker.run_worker(lambda: runner, once=True, sleep=clock.sleep, clock=clock)
    assert code == 0 and runner.ticks == 1 and clock.sleeps == []


async def test_once_exits_1_when_the_pass_could_not_list_its_tenants() -> None:
    assert await worker.run_worker(lambda: FakeRunner(tick_error="ConnectionError"), once=True) == 1


async def test_once_exits_1_when_the_pass_raised() -> None:
    assert await worker.run_worker(lambda: FakeRunner(fails=[True]), once=True) == 1


async def test_the_loop_waits_start_to_start_and_survives_a_failing_pass() -> None:
    runner, clock = FakeRunner(fails=[False, True, False]), FakeClock()

    def ticking_clock() -> float:
        return clock.now

    async def sleep(seconds: float) -> None:
        await clock.sleep(seconds)

    original = runner.run_once

    async def run_once() -> worker.TickReport:
        clock.now += clock.tick_seconds  # the pass takes 0.5 s
        return await original()

    runner.run_once = run_once  # type: ignore[method-assign]
    code = await worker.run_worker(
        lambda: runner, once=False, interval=5, sleep=sleep, clock=ticking_clock, max_ticks=3
    )
    assert code == 0 and runner.ticks == 3
    assert clock.sleeps == [4.5, 4.5]  # interval minus the pass's own duration


async def test_the_loop_stops_between_passes_when_asked() -> None:
    runner, clock = FakeRunner(), FakeClock()
    stops = iter([False, True])
    code = await worker.run_worker(
        lambda: runner,
        once=False,
        interval=5,
        sleep=clock.sleep,
        clock=clock,
        should_stop=lambda: next(stops),
    )
    assert code == 0 and runner.ticks == 1


def test_worker_id_names_host_and_process() -> None:
    assert re.fullmatch(r".+:\d+", worker.worker_id())


# --- the production declarations --------------------------------------------------------


def test_justfile_has_tick_and_worker_recipes_with_the_scope_warning() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    assert "whatsapp-tick *args:" in justfile
    assert "whatsapp-worker *args:" in justfile
    assert "python -m qualify_api.whatsapp.worker --once {{args}}" in justfile
    assert "python -m qualify_api.whatsapp.worker {{args}}" in justfile
    # The same warning calendar-worker carries: locally, always --tenant.
    block = justfile[justfile.index("# WA-08") :]
    assert "SENDS" in block and "FOR REAL" in block and "--tenant <uuid>" in block


def test_prod_compose_runs_the_whatsapp_worker_always_on_over_all_tenants() -> None:
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load(
        (REPO_ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    service = compose["services"]["whatsapp-worker"]
    assert "profiles" not in service  # always on, like webhook-worker
    assert service["restart"] == "unless-stopped"
    command = service["command"]
    assert command[:3] == ["python", "-m", "qualify_api.whatsapp.worker"]
    assert "--all-tenants" in command and "--interval" in command and "--once" not in command
    assert "ports" not in service and "volumes" not in service
    assert service["depends_on"]["postgres"]["condition"] == "service_healthy"
    # Adding it did not move the publisher out from behind its profile.
    assert compose["services"]["calendar-worker"]["profiles"] == ["calendar-worker"]


def test_claude_md_documents_both_recipes() -> None:
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "just whatsapp-tick --tenant <uuid>" in text
    assert "just whatsapp-worker --tenant <uuid>" in text


def test_a_stray_uuid_is_not_accepted_as_a_scope() -> None:
    with pytest.raises(SystemExit):
        worker.build_parser().parse_args(["--tenant", "not-a-uuid"])
    assert worker.build_parser().parse_args(["--tenant", str(uuid4())]).tenants
