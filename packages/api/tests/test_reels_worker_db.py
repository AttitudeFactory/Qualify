"""The reels-worker over the live schema of 0124 (ADR 42 R8, m-24854855): its door
(`qualify_reels_worker`, SELECT of a few columns through role-scoped policies), the
activity table under RLS, the fenced writes of the run's lifecycle, and the worker's
pass against real SQL. Scoped to the tenants each test creates; the vendor and Claude
are never called (a run here has no brief, or a recording fake stands in for it)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.reels_worker import reels_worker_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_queue import PostgresReelQueue
from qualify_api.referentes.reel_store import (
    STATUS_CHECK_FAILED,
    STATUS_ERROR,
    STATUS_QUEUED,
    STATUS_RUNNING,
    NewIdea,
    PostgresReelRunStore,
)
from qualify_api.referentes.reel_worker import ReelsWorker
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

#: Monday 2026-11-09 06:00 in Bogotá.
SIX_AM = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)
MONDAY = date(2026, 11, 9)
HOUR = timedelta(hours=1)


def _business(timezone: str = "America/Bogota", brands: int = 1) -> tuple[UUID, list[UUID]]:
    tenant, ids = uuid4(), [uuid4() for _ in range(brands)]
    with admin_session() as session:
        session.add(Tenant(id=tenant, name="R8", country="CO", timezone=timezone, currency="COP"))
        session.flush()
        for brand in ids:
            session.add(Brand(id=brand, tenant_id=tenant, name="R8 brand"))
    return tenant, ids


@pytest.fixture
def store() -> PostgresReelRunStore:
    return PostgresReelRunStore()


def _epoch(moment: datetime) -> float:
    return moment.timestamp()


# --------------------------------------------------------------------------------------
# brand_reel_activity
# --------------------------------------------------------------------------------------


def test_activity_is_per_tenant_and_only_moves_forward_once_an_hour(
    store: PostgresReelRunStore,
) -> None:
    (a, [brand]), (b, _) = _business(), _business()
    store.mark_opened(a, brand, now=SIX_AM, every=HOUR)
    store.mark_opened(a, brand, now=SIX_AM + timedelta(minutes=59), every=HOUR)  # too soon
    store.mark_opened(a, brand, now=SIX_AM - timedelta(days=3), every=HOUR)  # backwards

    def opened(tenant: UUID) -> list[datetime]:
        with tenant_session(tenant) as session:
            return list(
                session.scalars(
                    text("SELECT last_opened_at FROM brand_reel_activity WHERE brand_id = :b"),
                    {"b": brand},
                )
            )

    assert opened(a) == [SIX_AM] and opened(b) == []  # B cannot see A's row
    store.mark_opened(a, brand, now=SIX_AM + HOUR, every=HOUR)
    assert opened(a) == [SIX_AM + HOUR]
    with pytest.raises(ProgrammingError), tenant_session(b) as session:
        session.execute(
            text(
                "INSERT INTO brand_reel_activity (tenant_id, brand_id, last_opened_at) "
                "VALUES (:t, :b, now())"
            ),
            {"t": a, "b": brand},
        )


def test_mark_opened_and_ensure_first_run_reach_postgres(
    store: PostgresReelRunStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, [brand] = _business("America/Montevideo")
    rr.mark_opened(tenant, brand, store=store)
    with tenant_session(tenant) as session:
        assert session.scalar(text("SELECT count(*) FROM brand_reel_activity")) == 1
    monkeypatch.setattr(rr.brief_builder, "brand_brief", lambda t, b: object())
    monkeypatch.setattr(rr.reels, "brand_referentes", lambda t, b: ["@cuenta"])
    assert rr.ensure_first_run(tenant, brand, store=store) is True
    record = store.latest_run(tenant, brand)
    assert record is not None and record.trigger == "weekly" and record.attempts == 0
    assert record.run_date.weekday() == 0  # a Monday, in Montevideo's calendar
    assert rr.ensure_first_run(tenant, brand, store=store) is False


# --------------------------------------------------------------------------------------
# the door
# --------------------------------------------------------------------------------------


def test_the_door_reads_only_what_decides_the_next_run(store: PostgresReelRunStore) -> None:
    (a, [brand_a]), (b, [brand_b]) = _business(), _business("America/Caracas")
    store.mark_opened(a, brand_a, now=SIX_AM, every=HOUR)
    rr.enqueue_run(b, brand_b, "manual", store=store, clock=lambda: _epoch(SIX_AM))
    with reels_worker_session() as session:
        runs = session.execute(
            text(
                "SELECT id, tenant_id, brand_id, trigger, run_date, status, queued_at, "
                "started_at, attempts FROM brand_reel_runs WHERE tenant_id = ANY(:t)"
            ),
            {"t": [a, b]},
        ).all()
        zones = dict(
            session.execute(
                text("SELECT id, timezone FROM tenants WHERE id = ANY(:t)"), {"t": [a, b]}
            ).all()
        )
        activity = session.execute(
            text(
                "SELECT tenant_id, brand_id, last_opened_at FROM brand_reel_activity "
                "WHERE tenant_id = ANY(:t)"
            ),
            {"t": [a, b]},
        ).all()
    assert [(r.tenant_id, r.status) for r in runs] == [(b, STATUS_QUEUED)]  # any tenant's
    assert zones == {a: "America/Bogota", b: "America/Caracas"}
    assert [(r.tenant_id, r.brand_id) for r in activity] == [(a, brand_a)]
    refused = (
        "SELECT credits FROM brand_reel_runs",
        "SELECT cost_usd FROM brand_reel_runs",
        "SELECT name FROM tenants",
        "SELECT id FROM brands",
        "SELECT id FROM brand_reel_ideas",
        "UPDATE brand_reel_runs SET status = 'error'",
        "DELETE FROM brand_reel_activity",
        "INSERT INTO brand_reel_activity (tenant_id, brand_id, last_opened_at) "
        "VALUES (gen_random_uuid(), gen_random_uuid(), now())",
    )
    for statement in refused:
        with pytest.raises(ProgrammingError), reels_worker_session() as session:
            session.execute(text(statement))


def test_the_role_cannot_bypass_rls() -> None:
    with admin_session() as session:
        bypass = session.scalar(
            text("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'qualify_reels_worker'")
        )
    assert bypass is False


# --------------------------------------------------------------------------------------
# the run's lifecycle: attempts and the fence
# --------------------------------------------------------------------------------------


def test_the_claim_counts_attempts_and_every_write_is_fenced(store: PostgresReelRunStore) -> None:
    tenant, [brand] = _business()
    run = rr.enqueue_run(tenant, brand, "manual", store=store, clock=lambda: _epoch(SIX_AM))
    assert run.attempts == 0
    first = store.claim(tenant, run.id, now=SIX_AM)
    assert first is not None and first.attempts == 1 and first.started_at == SIX_AM
    assert store.release(tenant, run.id, started_at=SIX_AM)
    later = SIX_AM + timedelta(minutes=31)
    second = store.claim(tenant, run.id, now=later)
    assert second is not None and second.attempts == 2
    stale = {"started_at": SIX_AM}
    assert not store.progress(tenant, run.id, accounts_total=3, accounts_done=3, **stale)
    assert not store.finish(
        tenant,
        run.id,
        status="ok",
        now=later,
        credits=9,
        cost_usd=Decimal("1"),
        brief_hash=None,
        **stale,
    )
    assert not store.release(tenant, run.id, **stale)
    assert not store.abandon(tenant, run.id, now=later, **stale)
    record = store.get_run(tenant, run.id)
    assert record is not None and (record.status, record.credits) == (STATUS_RUNNING, 0)
    assert store.abandon(tenant, run.id, started_at=later, now=later)
    assert store.get_run(tenant, run.id).status == STATUS_ERROR
    retried = rr.enqueue_run(
        tenant, brand, "manual", store=store, clock=lambda: _epoch(later), retry=True
    )
    assert retried.status == STATUS_QUEUED and retried.attempts == 0


def test_ideas_are_fenced_and_replace_an_earlier_attempts(store: PostgresReelRunStore) -> None:
    """Review of R8: an attempt that died after saving its ideas but before `finish` is
    done again under the same id: its ideas are replaced, never merged (duplicate ranks),
    and the old attempt can no longer write them."""
    tenant, [brand] = _business()
    run = rr.enqueue_run(tenant, brand, "manual", store=store, clock=lambda: _epoch(SIX_AM))
    assert store.claim(tenant, run.id, now=SIX_AM) is not None
    token = uuid4().hex[:8]
    first = [
        NewIdea("instagram", f"{token}a", 1, 7, None),
        NewIdea("instagram", f"{token}b", 2, 30, None),
    ]
    assert store.save_ideas(tenant, brand, run.id, first, started_at=SIX_AM)
    assert store.release(tenant, run.id, started_at=SIX_AM)
    later = SIX_AM + timedelta(minutes=31)
    assert store.claim(tenant, run.id, now=later) is not None
    assert not store.save_ideas(tenant, brand, run.id, first, started_at=SIX_AM)
    second = [NewIdea("instagram", f"{token}c", 1, 7, None)]
    assert store.save_ideas(tenant, brand, run.id, second, started_at=later)
    with tenant_session(tenant) as session:
        rows = session.execute(
            text("SELECT reel_id, rank FROM brand_reel_ideas WHERE run_id = :r ORDER BY rank"),
            {"r": run.id},
        ).all()
    assert [(r.reel_id, r.rank) for r in rows] == [(f"{token}c", 1)]


# --------------------------------------------------------------------------------------
# the worker's pass over Postgres
# --------------------------------------------------------------------------------------


def _ready(tenant_id: UUID, brand_id: UUID) -> bool:
    """These tests are about the SQL of scheduling: every brand has its brief and accounts
    (the readiness rule itself is `test_referentes_reels_worker.py`)."""
    return True


class Runs:
    def __init__(self) -> None:
        self.started: list[UUID] = []

    def __call__(self, tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        self.started.append(run_id)
        return rr.RunOutcome(run_id=run_id, status=STATUS_QUEUED, ran=False)


def test_a_pass_at_monday_six_enqueues_once_per_active_brand(store: PostgresReelRunStore) -> None:
    (a, [active, inactive]), (b, [other]) = _business(brands=2), _business()
    store.mark_opened(a, active, now=SIX_AM - timedelta(days=2), every=HOUR)
    store.mark_opened(a, inactive, now=SIX_AM - timedelta(days=14, hours=12), every=HOUR)
    store.mark_opened(b, other, now=SIX_AM - timedelta(days=1), every=HOUR)
    clock = {"now": SIX_AM}
    worker = ReelsWorker(
        PostgresReelQueue(tenants=[a]),  # scoped: B's brand is never even read
        store,
        run=Runs(),
        ready=_ready,
        clock=lambda: clock["now"],
    )
    first = worker.pass_once()
    clock["now"] += timedelta(minutes=20)
    second = worker.pass_once()
    assert [d.brand_id for d in first.enqueued] == [active] and second.enqueued == []
    with tenant_session(a) as session:
        rows = session.execute(
            text("SELECT brand_id, run_date FROM brand_reel_runs WHERE trigger = 'weekly'")
        ).all()
    assert [(r.brand_id, r.run_date) for r in rows] == [(active, MONDAY)]
    with tenant_session(b) as session:
        assert session.scalar(text("SELECT count(*) FROM brand_reel_runs")) == 0


def test_a_brand_marked_opened_three_days_before_monday_six_gets_its_weekly_run(
    store: PostgresReelRunStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end on the ONE activity signal: `reel_runs.mark_opened` writes
    `brand_reel_activity` through `tenant_session`, the worker's door reads it. A brand
    without that row gets nothing, whatever else it has (here, an earlier run)."""
    tenant, [opened, never_opened] = _business(brands=2)
    three_days_before = _epoch(SIX_AM - timedelta(days=3))
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=lambda: three_days_before))
    rr.mark_opened(tenant, opened, store=store)
    rr.enqueue_run(tenant, never_opened, "manual", store=store, clock=lambda: three_days_before)

    worker = ReelsWorker(
        PostgresReelQueue(tenants=[tenant]), store, run=Runs(), ready=_ready, clock=lambda: SIX_AM
    )
    report = worker.pass_once()
    assert [(d.brand_id, d.run_date) for d in report.enqueued] == [(opened, MONDAY)]
    with tenant_session(tenant) as session:
        rows = session.execute(
            text("SELECT brand_id, run_date FROM brand_reel_runs WHERE trigger = 'weekly'")
        ).all()
    assert [(r.brand_id, r.run_date) for r in rows] == [(opened, MONDAY)]


def test_a_failed_check_goes_back_to_the_queue_after_fifteen_minutes(
    store: PostgresReelRunStore,
) -> None:
    """Founder, 2026-11-04: the door lists the `check_failed` runs with attempts left; the
    fenced UPDATE (through `tenant_session`) requeues one only 15 min after it ended."""
    tenant, [brand] = _business()
    queue = PostgresReelQueue(tenants=[tenant])
    run = rr.enqueue_run(tenant, brand, "manual", store=store, clock=lambda: _epoch(SIX_AM))
    assert store.claim(tenant, run.id, now=SIX_AM) is not None
    assert store.finish(
        tenant,
        run.id,
        status=STATUS_CHECK_FAILED,
        now=SIX_AM,
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash=None,
        started_at=SIX_AM,
    )
    window = SIX_AM - timedelta(hours=25)
    assert [r.run_id for r in queue.failed_checks(max_attempts=3, started_after=window)] == [run.id]
    assert queue.failed_checks(max_attempts=3, started_after=SIX_AM) == []  # started before
    after = SIX_AM - timedelta(hours=1)
    early = SIX_AM + timedelta(minutes=14) - rr.CHECK_RETRY_AFTER
    assert not store.retry_check(
        tenant, run.id, finished_before=early, finished_after=after, max_attempts=3
    )
    due = SIX_AM + timedelta(minutes=15) - rr.CHECK_RETRY_AFTER
    # N1: ended at or before `finished_after` (more than 24 h ago) is never retried
    assert not store.retry_check(
        tenant, run.id, finished_before=due, finished_after=SIX_AM, max_attempts=3
    )
    assert store.retry_check(
        tenant, run.id, finished_before=due, finished_after=after, max_attempts=3
    )
    record = store.get_run(tenant, run.id)
    assert record is not None
    assert (record.status, record.attempts, record.finished_at) == (STATUS_QUEUED, 1, None)
    assert queue.failed_checks(max_attempts=3, started_after=window) == []
    # a run that spent its attempts is not even listed
    assert store.claim(tenant, run.id, now=SIX_AM + HOUR) is not None
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE brand_reel_runs SET status = 'check_failed', finished_at = :t, "
                "attempts = 3 WHERE id = :id"
            ),
            {"t": SIX_AM + HOUR, "id": run.id},
        )
    assert queue.failed_checks(max_attempts=3, started_after=window) == []
    assert not store.retry_check(
        tenant, run.id, finished_before=SIX_AM + 2 * HOUR, finished_after=after, max_attempts=3
    )


def test_only_the_brands_latest_failed_check_is_retried(store: PostgresReelRunStore) -> None:
    """N1 over Postgres: a newer run of the same brand supersedes the failed check (the
    order of `latest_run`, the one the screen shows)."""
    tenant, [brand] = _business()
    run = rr.enqueue_run(tenant, brand, "manual", store=store, clock=lambda: _epoch(SIX_AM))
    assert store.claim(tenant, run.id, now=SIX_AM) is not None
    assert store.finish(
        tenant,
        run.id,
        status=STATUS_CHECK_FAILED,
        now=SIX_AM,
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash=None,
        started_at=SIX_AM,
    )
    newer = rr.enqueue_run(
        tenant,
        brand,
        "weekly",
        run_date=MONDAY + timedelta(days=7),
        store=store,
        clock=lambda: _epoch(SIX_AM + timedelta(minutes=1)),
    )
    latest = store.latest_run(tenant, brand)
    assert latest is not None and latest.id == newer.id
    assert not store.retry_check(
        tenant,
        run.id,
        finished_before=SIX_AM + HOUR,
        finished_after=SIX_AM - HOUR,
        max_attempts=3,
    )
    record = store.get_run(tenant, run.id)
    assert record is not None and record.status == STATUS_CHECK_FAILED


def test_manual_first_and_a_dead_processs_run_recovers(store: PostgresReelRunStore) -> None:
    tenant, [brand_w, brand_m, brand_dead] = _business(brands=3)
    queue = PostgresReelQueue(tenants=[tenant])
    weekly = rr.enqueue_run(
        tenant, brand_w, "weekly", run_date=MONDAY, store=store, clock=lambda: _epoch(SIX_AM)
    )
    manual = rr.enqueue_run(
        tenant, brand_m, "manual", store=store, clock=lambda: _epoch(SIX_AM + HOUR)
    )
    assert queue.next_run().run_id == manual.id  # newer, but someone is waiting for it
    dead = rr.enqueue_run(tenant, brand_dead, "manual", store=store, clock=lambda: _epoch(SIX_AM))
    assert store.claim(tenant, dead.id, now=SIX_AM) is not None  # then the process died
    now = SIX_AM + timedelta(minutes=31)
    assert [s.run_id for s in queue.stale_runs(started_before=now - rr.STALE_AFTER)] == [dead.id]
    assert queue.existing_weekly([]) == set()

    def no_brief_run(tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        return rr.run(
            tenant_id,
            run_id,
            store=store,
            brief=lambda t, b: None,
            clock=lambda: _epoch(now),
        )

    report = ReelsWorker(
        queue, store, run=no_brief_run, ready=_ready, clock=lambda: now, batch=3
    ).pass_once()
    assert [(r.run_id, r.status) for r in report.recovered] == [(dead.id, STATUS_QUEUED)]
    # the dead run is the oldest manual one now: it goes first, then the newer manual, then
    # the weekly run
    assert [o.run_id for o in report.outcomes] == [dead.id, manual.id, weekly.id]
    for run_id, attempts in ((dead.id, 2), (manual.id, 1), (weekly.id, 1)):
        record = store.get_run(tenant, run_id)
        assert record.status == STATUS_CHECK_FAILED and record.attempts == attempts
