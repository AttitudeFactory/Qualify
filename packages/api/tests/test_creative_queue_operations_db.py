"""m-24852167: SQL percentiles and metadata through the real restricted DB roles."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from sqlalchemy import create_engine, text

from qualify_api.creative import job_queue as q
from qualify_api.creative.worker.operations import read_snapshot
from qualify_api.tenancy.models import Brand, Tenant

from .test_creative_jobs_db import _enqueue

pytestmark = pytest.mark.db


@pytest.fixture
def operations_tenant() -> Iterator[UUID]:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name="queue-test",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        session.add(Brand(tenant_id=tenant_id, name="queue-test"))
    yield tenant_id
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM vendor_slots WHERE vendor_model = :p"),
            {"p": f"operations:{tenant_id}"},
        )
        for table in (
            "creative_jobs",
            "creative_vendor_task_timings",
            "content_drafts",
            "content_briefs",
            "brands",
        ):
            conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    engine.dispose()


def test_report_exact_percentiles_scope_and_expired_lease(operations_tenant: UUID) -> None:
    tenant_id = operations_tenant
    now = datetime.now(UTC)
    pool = f"operations:{tenant_id}"
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    ids = [_enqueue(tenant_id, pool) for _ in range(5)]
    for index, job in enumerate(ids):
        submitted = now - timedelta(minutes=5 if index < 4 else 120)
        wait = index * 100 if index < 4 else 1000
        with engine.begin() as conn:
            conn.execute(
                text("""
                UPDATE creative_jobs SET status = 'submitted', submitted_at = :submitted,
                    queued_at = :queued, lease_until = :lease WHERE id = :id
                """),
                {
                    "submitted": submitted,
                    "queued": submitted - timedelta(seconds=wait),
                    "lease": now - timedelta(seconds=1),
                    "id": job,
                },
            )
    _enqueue(tenant_id, pool, kind=q.KIND_FINAL, deadline=now + timedelta(hours=23))
    with engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO vendor_slots (vendor_model, slot_no, holder_job_id, lease_until)
            VALUES (:p, 1, :id, :expired), (:p, 2, NULL, NULL)
        """),
            {"p": pool, "id": ids[0], "expired": now - timedelta(seconds=1)},
        )
    snapshot = read_snapshot(now=now, tenant_ids=[tenant_id], include_slots=True)
    slot = next(row for row in snapshot.slots if row["vendor_model"] == pool)
    assert slot == {"vendor_model": pool, "provisioned": 2, "occupied": 1, "expired": 1}
    waits = {r["window"]: r for r in snapshot.waits}
    assert waits["hour"]["p50"] == pytest.approx(150)
    assert waits["hour"]["p95"] == pytest.approx(285)
    assert waits["day"]["p50"] == pytest.approx(200)
    assert waits["day"]["p95"] == pytest.approx(860)
    assert waits["hour"]["samples"] == 4
    assert snapshot.expired_leases == 5
    assert snapshot.urgent_finals == 1
    assert snapshot.top_tenants == ({"tenant_id": tenant_id, "jobs": 1},)
    other = read_snapshot(now=now, tenant_ids=[uuid4()])
    assert not other.counts
    assert not other.top_tenants
    assert all(r["samples"] == 0 for r in other.waits)
    engine.dispose()


def test_concurrency_sweep_counts_simultaneous_submissions_and_model_versions(
    operations_tenant: UUID,
) -> None:
    now = datetime.now(UTC)
    model = f"test-model-{uuid4()}"
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with engine.begin() as conn:
        for index in range(6):
            conn.execute(
                text("""
                INSERT INTO creative_vendor_task_timings
                    (tenant_id, provider, model_id, vendor_task_id, phase, submitted_at,
                     finished_at, final_status)
                VALUES (:t, 'byteplus', :model, :task, 'draft', :started, :ended, 'succeeded')
                """),
                {
                    "t": operations_tenant,
                    "model": f"{model}-{260101 + index}",
                    "task": str(uuid4()),
                    "started": now - timedelta(minutes=2),
                    "ended": now - timedelta(minutes=1),
                },
            )
    snapshot = read_snapshot(now=now, tenant_ids=[operations_tenant], include_slots=True)
    assert len(snapshot.weekly_capacity) == 1
    assert snapshot.weekly_capacity[0]["vendor_model"] == f"byteplus:{model}"
    assert snapshot.weekly_capacity[0]["p95"] == 6
    assert "capacity" in snapshot.conditions()
    assert any(row["provisioned"] >= 10 for row in snapshot.slots)
    engine.dispose()
