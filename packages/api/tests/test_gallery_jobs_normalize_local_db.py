"""`db`-marked tests of migration 0171 (m-25042483 «Bajarlos a 4K 8 bits»): the
`normalize_local` kind of `gallery_jobs` through the creative worker's door
(`tenant_session`, `qualify_app`) — one job per file (never normalized twice), RLS keeps
another tenant's jobs out of reach, a failed job frees the key, and the payload CHECK."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from qualify_api.catalog.business_media_models import (
    JOB_NORMALIZE_LOCAL,
    STATUS_DONE,
    STATUS_FAILED,
    GalleryJob,
)
from qualify_api.creative.video_pipeline.local_sources import (
    PostgresLocalSourceJobs,
    normalize_job_key,
    normalized_key,
)
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

TENANT_A = UUID("a0000000-0000-4000-8000-0000000c4171")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000c4172")


def _brand(session, tenant: UUID, name: str) -> UUID:  # noqa: ANN001
    brand = session.scalar(select(Brand).where(Brand.tenant_id == tenant, Brand.name == name))
    if brand is None:
        brand = Brand(tenant_id=tenant, name=name)
        session.add(brand)
        session.flush()
    return brand.id


@pytest.fixture
def brands() -> dict[UUID, UUID]:
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"m25042483-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        out = {tid: _brand(session, tid, f"m25042483-{tid}") for tid in (TENANT_A, TENANT_B)}
    for tid in (TENANT_A, TENANT_B):
        with tenant_session(tid) as session:
            session.execute(text("DELETE FROM gallery_jobs WHERE tenant_id = :t"), {"t": tid})
    return out


def _source(tenant: UUID) -> str:
    return f"t/{tenant}/uploads/{uuid4()}/iphone.mov"


def _rows(tenant: UUID, key: str) -> list[GalleryJob]:
    with tenant_session(tenant) as session:
        rows = session.scalars(
            select(GalleryJob).where(GalleryJob.idempotency_key == normalize_job_key(key))
        ).all()
        session.expunge_all()
    return list(rows)


def test_one_job_per_file_even_when_asked_twice(brands: dict[UUID, UUID]) -> None:
    jobs, key = PostgresLocalSourceJobs(), _source(TENANT_A)
    for _ in range(2):  # a retried pass, or a second piece with the same file
        jobs.enqueue(TENANT_A, key, draft_id=None, brand_id=brands[TENANT_A])
    (row,) = _rows(TENANT_A, key)
    assert row.kind == JOB_NORMALIZE_LOCAL and row.status == "queued"
    assert row.payload == {
        "source_key": key,
        "normalized_key": normalized_key(TENANT_A, key),
        "version": "local-source-v2",
        "draft_id": None,
    }
    found = jobs.lookup(TENANT_A, [key])
    assert found[key].status == "queued"
    assert found[key].normalized_key == normalized_key(TENANT_A, key)


def test_a_done_job_still_holds_its_file_and_a_failed_one_frees_it(
    brands: dict[UUID, UUID],
) -> None:
    jobs, key = PostgresLocalSourceJobs(), _source(TENANT_A)
    jobs.enqueue(TENANT_A, key, draft_id=None, brand_id=brands[TENANT_A])
    with tenant_session(TENANT_A) as session:
        session.execute(
            update(GalleryJob)
            .where(GalleryJob.idempotency_key == normalize_job_key(key))
            .values(status=STATUS_DONE, result={"normalized_key": "n", "version": "v"})
        )
    jobs.enqueue(TENANT_A, key, draft_id=None, brand_id=brands[TENANT_A])
    assert len(_rows(TENANT_A, key)) == 1  # never normalized twice
    found = jobs.lookup(TENANT_A, [key])[key]
    assert (found.status, found.normalized_key, found.version) == ("done", "n", "v")
    with tenant_session(TENANT_A) as session:
        session.execute(
            update(GalleryJob)
            .where(GalleryJob.idempotency_key == normalize_job_key(key))
            .values(status=STATUS_FAILED, last_error_code="unreadable")
        )
    assert jobs.lookup(TENANT_A, [key])[key].status == "failed"
    jobs.enqueue(TENANT_A, key, draft_id=None, brand_id=brands[TENANT_A])
    assert sorted(r.status for r in _rows(TENANT_A, key)) == ["failed", "queued"]


def _fail_active(tenant: UUID, key: str, code: str) -> None:
    with tenant_session(tenant) as session:
        session.execute(
            update(GalleryJob)
            .where(
                GalleryJob.idempotency_key == normalize_job_key(key),
                GalleryJob.status != STATUS_FAILED,
            )
            .values(status=STATUS_FAILED, last_error_code=code)
        )


def test_transient_failures_are_counted_across_the_files_jobs(brands: dict[UUID, UUID]) -> None:
    """Review 2: the machine's failures add up over every job of the file (the SQL, not the
    in-memory double); a permanent one is not counted; the latest job is the status."""
    jobs, key = PostgresLocalSourceJobs(), _source(TENANT_A)
    jobs.enqueue(TENANT_A, key, draft_id=None, brand_id=brands[TENANT_A])
    _fail_active(TENANT_A, key, "attempts_exhausted")
    jobs.enqueue(TENANT_A, key, draft_id=None, brand_id=brands[TENANT_A])  # re-queued
    found = jobs.lookup(TENANT_A, [key])[key]
    assert (found.status, found.transient_failures) == ("queued", 1)
    _fail_active(TENANT_A, key, "r2_unavailable")
    found = jobs.lookup(TENANT_A, [key])[key]
    assert (found.status, found.transient_failures) == ("failed", 2)
    other = _source(TENANT_A)
    jobs.enqueue(TENANT_A, other, draft_id=None, brand_id=brands[TENANT_A])
    _fail_active(TENANT_A, other, "unreadable")
    assert jobs.lookup(TENANT_A, [other])[other].transient_failures == 0


def test_another_tenants_jobs_are_out_of_reach(brands: dict[UUID, UUID]) -> None:
    jobs, key = PostgresLocalSourceJobs(), _source(TENANT_A)
    jobs.enqueue(TENANT_A, key, draft_id=None, brand_id=brands[TENANT_A])
    assert jobs.lookup(TENANT_B, [key]) == {}
    assert _rows(TENANT_B, key) == []


def test_a_normalize_local_job_needs_its_payload(brands: dict[UUID, UUID]) -> None:
    with pytest.raises(IntegrityError), tenant_session(TENANT_A) as session:
        session.add(
            GalleryJob(
                tenant_id=TENANT_A,
                brand_id=brands[TENANT_A],
                kind=JOB_NORMALIZE_LOCAL,
                idempotency_key=normalize_job_key(_source(TENANT_A)),
                pipeline_version="local-source-v2",
                payload={"source_key": "x"},
            )
        )
        session.flush()
