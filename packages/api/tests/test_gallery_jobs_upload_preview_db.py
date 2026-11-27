"""`db`-marked tests of migration 0175 (m-25026643, ED-09): the `upload_preview` kind of
`gallery_jobs` through the screens' door (`upload_previews`, `tenant_session`,
`qualify_app`) — one job per uploaded video (never copied twice), RLS keeps another
tenant's jobs out of reach, a failed job of the machine frees the key, the payload CHECK,
and the table's RLS still ENABLE + FORCE."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from qualify_api.catalog.business_media_models import (
    JOB_UPLOAD_PREVIEW,
    STATUS_DONE,
    STATUS_FAILED,
    GalleryJob,
)
from qualify_api.creative.upload_previews import (
    STALE_VERSION,
    preview_job_key,
    preview_key,
    preview_play_key,
    previews_for,
    request_preview,
    strip_key,
)
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

V1 = "upload-preview-480p-v1"
V2 = "upload-preview-480p-strip-v2"

TENANT_A = UUID("a0000000-0000-4000-8000-0000000c4175")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000c4176")


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
                        name=f"m25026643-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        out = {tid: _brand(session, tid, f"m25026643-{tid}") for tid in (TENANT_A, TENANT_B)}
    for tid in (TENANT_A, TENANT_B):
        with tenant_session(tid) as session:
            session.execute(text("DELETE FROM gallery_jobs WHERE tenant_id = :t"), {"t": tid})
    return out


def _source(tenant: UUID) -> str:
    return f"t/{tenant}/uploads/{uuid4().hex}_iphone.mov"


def _rows(tenant: UUID, key: str, version: str = V2) -> list[GalleryJob]:
    with tenant_session(tenant) as session:
        rows = session.scalars(
            select(GalleryJob).where(GalleryJob.idempotency_key == preview_job_key(key, version))
        ).all()
        session.expunge_all()
    return list(rows)


def _set(tenant: UUID, key: str, **values: object) -> None:
    with tenant_session(tenant) as session:
        session.execute(
            update(GalleryJob)
            .where(
                GalleryJob.idempotency_key == preview_job_key(key),
                GalleryJob.status != STATUS_FAILED,
            )
            .values(**values)
        )


def test_one_job_per_upload_even_when_asked_twice(brands: dict[UUID, UUID]) -> None:
    key = _source(TENANT_A)
    for _ in range(2):  # a retried upload handler, or the editor opened twice
        request_preview(TENANT_A, brands[TENANT_A], key)
    (row,) = _rows(TENANT_A, key)
    assert row.kind == JOB_UPLOAD_PREVIEW and row.status == "queued"
    assert row.pipeline_version == V2
    assert row.payload == {  # ED-11b: the copy and its strip in ONE job
        "source_key": key,
        "preview_key": preview_key(TENANT_A, key),
        "strip_key": strip_key(TENANT_A, key),
        "version": V2,
    }
    assert previews_for(TENANT_A, [key])[key].status == "queued"
    assert preview_play_key(TENANT_A, key) == key  # not made yet: the original


def test_a_v2_job_settled_by_an_old_worker_frees_its_key_for_the_strip(
    brands: dict[UUID, UUID],
) -> None:
    """ED-11b review: the stale v2 job (result says v1) is marked failed through
    `tenant_session` and one strip job takes the key; its copy keeps playing."""
    key = _source(TENANT_A)
    request_preview(TENANT_A, brands[TENANT_A], key)
    made = preview_key(TENANT_A, key)
    _set(TENANT_A, key, status=STATUS_DONE, result={"preview_key": made, "version": V1})
    preview = request_preview(TENANT_A, brands[TENANT_A], key)
    assert preview.preview_play_key == made and preview.strip_status == "queued"
    rows = sorted(_rows(TENANT_A, key), key=lambda r: r.status)
    assert [(r.status, r.last_error_code) for r in rows] == [
        ("failed", STALE_VERSION),
        ("queued", None),
    ]
    assert rows[1].payload["preview_key"] == made
    request_preview(TENANT_A, brands[TENANT_A], key)
    assert len(_rows(TENANT_A, key)) == 2


def test_a_v1_copy_gets_its_strip_apart_next_to_it(brands: dict[UUID, UUID]) -> None:
    """ED-11b: a done v1 job and the v2 strip job coexist (each holds its own key in
    `uq_gallery_jobs_upload_preview`); the v1 copy keeps playing; asking twice queues one."""
    key = _source(TENANT_A)
    old_copy = preview_key(TENANT_A, key, V1)
    with tenant_session(TENANT_A) as session:
        session.add(
            GalleryJob(
                tenant_id=TENANT_A,
                brand_id=brands[TENANT_A],
                kind=JOB_UPLOAD_PREVIEW,
                idempotency_key=preview_job_key(key, V1),
                pipeline_version=V1,
                status=STATUS_DONE,
                payload={"source_key": key, "preview_key": old_copy, "version": V1},
                result={"preview_key": old_copy, "version": V1},
            )
        )
    for _ in range(2):
        preview = request_preview(TENANT_A, brands[TENANT_A], key)
    assert preview.preview_play_key == old_copy and preview.strip_status == "queued"
    (strip_job,) = _rows(TENANT_A, key)
    assert strip_job.payload["preview_key"] == old_copy
    assert strip_job.payload["strip_key"] == strip_key(TENANT_A, key)
    assert len(_rows(TENANT_A, key, V1)) == 1


def test_a_done_job_holds_its_upload_and_its_copy_is_what_plays(
    brands: dict[UUID, UUID],
) -> None:
    key = _source(TENANT_A)
    request_preview(TENANT_A, brands[TENANT_A], key)
    made = preview_key(TENANT_A, key)
    _set(TENANT_A, key, status=STATUS_DONE, result={"preview_key": made, "version": V2})
    request_preview(TENANT_A, brands[TENANT_A], key)
    assert len(_rows(TENANT_A, key)) == 1  # never copied twice
    assert preview_play_key(TENANT_A, key) == made


def test_the_unique_index_holds_even_past_the_service(brands: dict[UUID, UUID]) -> None:
    key = _source(TENANT_A)
    request_preview(TENANT_A, brands[TENANT_A], key)
    with pytest.raises(IntegrityError), tenant_session(TENANT_A) as session:
        session.add(
            GalleryJob(
                tenant_id=TENANT_A,
                brand_id=brands[TENANT_A],
                kind=JOB_UPLOAD_PREVIEW,
                idempotency_key=preview_job_key(key),
                pipeline_version="upload-preview-480p-v1",
                status=STATUS_DONE,
                payload={"source_key": key, "preview_key": "p", "version": "v"},
            )
        )
        session.flush()


def test_a_failure_of_the_machine_frees_the_key_and_a_bad_file_does_not_requeue(
    brands: dict[UUID, UUID],
) -> None:
    key = _source(TENANT_A)
    request_preview(TENANT_A, brands[TENANT_A], key)
    _set(TENANT_A, key, status=STATUS_FAILED, last_error_code="attempts_exhausted")
    assert request_preview(TENANT_A, brands[TENANT_A], key).status == "queued"
    assert sorted(r.status for r in _rows(TENANT_A, key)) == ["failed", "queued"]
    other = _source(TENANT_A)
    request_preview(TENANT_A, brands[TENANT_A], other)
    _set(TENANT_A, other, status=STATUS_FAILED, last_error_code="unreadable")
    assert request_preview(TENANT_A, brands[TENANT_A], other).failed_for_good
    assert len(_rows(TENANT_A, other)) == 1


def test_another_tenants_jobs_are_out_of_reach(brands: dict[UUID, UUID]) -> None:
    key = _source(TENANT_A)
    request_preview(TENANT_A, brands[TENANT_A], key)
    assert previews_for(TENANT_B, [key]) == {}  # not B's key: refused before any read
    assert _rows(TENANT_B, key) == []  # and RLS hides the row anyway


def test_a_job_cannot_name_another_tenants_business(brands: dict[UUID, UUID]) -> None:
    with pytest.raises(IntegrityError):
        request_preview(TENANT_A, brands[TENANT_B], _source(TENANT_A))


def test_an_upload_preview_job_needs_its_payload(brands: dict[UUID, UUID]) -> None:
    with pytest.raises(IntegrityError), tenant_session(TENANT_A) as session:
        session.add(
            GalleryJob(
                tenant_id=TENANT_A,
                brand_id=brands[TENANT_A],
                kind=JOB_UPLOAD_PREVIEW,
                idempotency_key=preview_job_key(_source(TENANT_A)),
                pipeline_version="upload-preview-480p-v1",
                payload={"source_key": "x"},
            )
        )
        session.flush()


def test_gallery_jobs_keeps_rls_enabled_and_forced() -> None:
    with admin_session() as session:
        enabled, forced = session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'gallery_jobs'"
            )
        ).one()
        policies = session.scalars(
            text("SELECT qual FROM pg_policies WHERE tablename = 'gallery_jobs'")
        ).all()
    assert enabled and forced
    assert policies and all("NULLIF" in (q or "") for q in policies)
