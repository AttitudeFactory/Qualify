"""`seasonal_video` jobs against the compose Postgres (m-24976893, migration 0143): the
«Con IA» batch enqueues ONE `creative_jobs` row per medium attempt with no draft, and
every reader of `creative_jobs` copes with it — the job loader reads its subject, the
Seedance pool's snapshot counts it (ADR 41's slot cap), the draft-only readers
(«generation in flight», the nightly final promotion) ignore it."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from packages.api.tests.test_creative_retention_db import _provision
from qualify_creative.seasonal.ai import estimate_ai_video_cost_usd
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import job_queue as q
from qualify_api.creative.final_review import nightly_maintenance
from qualify_api.creative.in_flight import generation_in_flight
from qualify_api.whatsapp.seasonal import (
    MemorySourceReads,
    PostgresSeasonalRepository,
    SeasonalMediaService,
)

pytestmark = pytest.mark.db

TENANT = UUID("c0000000-0000-4000-8000-0000000a1db1")


def _plan():  # noqa: ANN202
    brand, user, _ = _provision(TENANT, "IA")
    reads = MemorySourceReads()
    reads.pieces[(TENANT, brand)] = [uuid4(), uuid4()]
    service = SeasonalMediaService(
        PostgresSeasonalRepository(),
        reads,
        ai_mode=True,
        ai_video_estimate_usd=estimate_ai_video_cost_usd,
    )
    season = f"navidad-{uuid4().hex[:6]}"
    rows = service.plan_batch(
        TENANT, brand, season, "Navidad", "ai", user, accepted_total_usd=Decimal("0.10")
    )
    return service, brand, user, season, rows


def _jobs(media_id: UUID) -> list[q.JobRow]:
    with tenant_session(TENANT) as session:
        ids = session.execute(
            text("SELECT id FROM creative_jobs WHERE seasonal_media_id = :m ORDER BY attempt"),
            {"m": media_id},
        ).scalars()
        return [q.load_job(session, i) for i in ids]


def test_one_job_per_medium_attempt_without_a_draft() -> None:
    service, brand, user, season, rows = _plan()
    assert len(rows) == 2 and {r.recipe for r in rows} == {"ai-seedance"}
    for row in rows:
        (job,) = _jobs(row.id)
        assert job.kind == q.KIND_SEASONAL_VIDEO and job.draft_id is None
        assert job.seasonal_media_id == row.id and job.attempt == 1
        assert job.vendor_model == q.SEEDANCE_POOL and job.status == "queued"
    # planning again writes no second job
    service.plan_batch(
        TENANT, brand, season, "Navidad", "ai", user, accepted_total_usd=Decimal("0.10")
    )
    assert all(len(_jobs(r.id)) == 1 for r in rows)
    # «Pedir otro» enqueues the next attempt
    service.mark_failed(
        tenant_id=TENANT, brand_id=brand, media_id=rows[0].id, attempt=1, reason="x"
    )
    service.request_another(TENANT, brand, rows[0].id, user, accepted_cost_usd=Decimal("0.05"))
    assert [j.attempt for j in _jobs(rows[0].id)] == [1, 2]


def test_the_readers_of_the_queue() -> None:
    _service, _brand, _user, _season, rows = _plan()
    (job,) = _jobs(rows[0].id)
    now = datetime.now(UTC)
    # the Seedance pool's snapshot counts it (ADR 41: the account's slot cap)
    with tenant_session(TENANT) as session:
        waiting, _ = q.queue_snapshot(
            session, vendor_model=q.SEEDANCE_POOL, now=now, now_priority=8, tenant_ids=[TENANT]
        )
    assert job.job_id in {w.job_id for w in waiting}
    # draft-only readers ignore it: no piece is «in flight» because of it …
    assert generation_in_flight(TENANT) is False
    # … and the nightly final promotion skips it even in the nightly lane
    with tenant_session(TENANT) as session:
        session.execute(
            text("UPDATE creative_jobs SET lane = 'nightly' WHERE id = :j"), {"j": job.job_id}
        )
    nightly_maintenance([TENANT], now=datetime(2026, 11, 9, 18, 0, tzinfo=UTC))
    (after,) = _jobs(rows[0].id)
    assert after.lane == "nightly" and after.status == "queued"
