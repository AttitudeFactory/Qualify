"""m-24852158 against Postgres: the timings table (0094) — stamps written once, tenant
isolation by RLS, and the team's cross-tenant read through `admin_session`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.creative.vendor_queue_report import build_report, read_timings
from qualify_api.creative.vendor_tasks import DraftVendorTasks, PostgresVendorTaskStore

pytestmark = pytest.mark.db

MODEL = "dreamina-seedance-2-5-260628"
T0 = datetime(2026, 10, 26, 14, 0, tzinfo=UTC)


def _tenant(name: str) -> UUID:
    from qualify_shared.db.admin import admin_session

    from qualify_api.tenancy.models import Tenant

    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=name,
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
    return tenant_id


def _rows(tenant_id: UUID) -> list[object]:
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    from qualify_api.creative.models import CreativeVendorTaskTiming

    with tenant_session(tenant_id) as session:
        rows = session.scalars(select(CreativeVendorTaskTiming)).all()
        session.expunge_all()
        return list(rows)


class Ticker:
    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> datetime:
        return T0 + timedelta(seconds=self.seconds)


def test_a_task_is_stamped_once_and_only_its_tenant_sees_it() -> None:
    tenant_a, tenant_b = _tenant("timings-a"), _tenant("timings-b")
    store = PostgresVendorTaskStore()
    clock = Ticker()
    task_id = f"cgt-{uuid4().hex[:10]}"
    draft_id = uuid4()  # no FK on purpose: a measurement outlives its piece
    binding = DraftVendorTasks(
        _NoTasks(),
        tenant_id=tenant_a,
        draft_id=draft_id,
        revision=1,
        pipeline_version="creative-v9",
        context={},
        heartbeat=None,
        clock=store,
        now=clock,
    )
    observer = binding.observer("seedance-1", "seedance", MODEL)
    observer.created(task_id)
    observer.created(task_id)  # a re-record never makes a second row
    clock.seconds = 5
    observer.polled(task_id, "queued")
    clock.seconds = 40
    observer.polled(task_id, "running")
    clock.seconds = 45
    observer.polled(task_id, "running")
    clock.seconds = 120
    observer.polled(task_id, "succeeded")
    clock.seconds = 125
    observer.polled(task_id, "failed")  # a later answer changes nothing

    (row,) = _rows(tenant_a)
    assert row.vendor_task_id == task_id and row.phase == "draft"
    assert row.submitted_at == T0
    assert row.running_at == T0 + timedelta(seconds=40)
    assert row.finished_at == T0 + timedelta(seconds=120)
    assert row.final_status == "succeeded" and row.finished_late is False
    assert row.draft_id == draft_id and row.pipeline_version == "creative-v9"

    # tenant B neither sees it nor can stamp it
    assert _rows(tenant_b) == []
    store.mark_running(tenant_id=tenant_b, vendor_task_id=task_id, at=T0)
    store.mark_finished(
        tenant_id=tenant_b, vendor_task_id=task_id, status="failed", at=T0, late=True
    )
    (row,) = _rows(tenant_a)
    assert row.running_at == T0 + timedelta(seconds=40) and row.final_status == "succeeded"


def test_the_team_reads_every_tenant_through_admin_and_the_report_counts_them() -> None:
    tenant_a, tenant_b = _tenant("timings-c"), _tenant("timings-d")
    store = PostgresVendorTaskStore()
    base = datetime.now(UTC) - timedelta(hours=2)
    ids = []
    for offset, tenant in ((0, tenant_a), (10, tenant_b)):
        task_id = f"cgt-{uuid4().hex[:10]}"
        ids.append(task_id)
        start = base + timedelta(seconds=offset)
        store.mark_submitted(
            tenant_id=tenant,
            provider="seedance",
            model_id=MODEL,
            vendor_task_id=task_id,
            draft_id=None,
            revision=1,
            slot="seedance-1",
            pipeline_version=None,
            at=start,
        )
        running = start + timedelta(seconds=3)
        store.mark_running(tenant_id=tenant, vendor_task_id=task_id, at=running)
        store.mark_finished(
            tenant_id=tenant,
            vendor_task_id=task_id,
            status="succeeded",
            at=start + timedelta(seconds=90),
            late=False,
        )

    since = base - timedelta(minutes=1)
    rows = read_timings(since=since, tenant_ids=[tenant_a, tenant_b])
    assert {r.tenant_id for r in rows} == {tenant_a, tenant_b}
    report = build_report(rows, since=since, now=datetime.now(UTC))
    assert report.tasks == 2
    assert report.overall[0].at_once.max == 2  # both tenants share BytePlus's 10
    assert report.overall[0].wait_seconds.max == 3


def test_the_app_role_cannot_delete_timings() -> None:
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError

    tenant = _tenant("timings-e")
    PostgresVendorTaskStore().mark_submitted(
        tenant_id=tenant,
        provider="seedance",
        model_id=MODEL,
        vendor_task_id=f"cgt-{uuid4().hex[:10]}",
        draft_id=None,
        revision=None,
        slot="final:x",
        pipeline_version=None,
        at=T0,
    )
    with pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(text("DELETE FROM creative_vendor_task_timings"))
    (row,) = _rows(tenant)
    assert row.phase == "final"


class _NoTasks:
    """The 0090 store is not under test here: its rows need a real draft."""

    def record(self, **_: object) -> None:
        return None

    def tasks(self, **_: object) -> tuple[()]:
        return ()

    def settle(self, **_: object) -> None:
        return None

    def waiting(self, **_: object) -> frozenset[UUID]:
        return frozenset()
