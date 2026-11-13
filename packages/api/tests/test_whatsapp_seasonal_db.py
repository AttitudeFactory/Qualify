"""m-24976891 against the compose Postgres (migration 0145): the seasonal library's RLS,
its unique slot (planning twice writes nothing new), the job written with each new row
and its `payload` (SQL NULL or an object, required for `seasonal_media`), the file key
CHECK, the worker door, and the Galería's job list ignoring seasonal jobs."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from packages.api.tests.test_creative_retention_db import (
    TENANT_A,
    TENANT_B,
    _piece,
    _provision,
)
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.keys import SEASONAL_MAX_ATTEMPTS
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from qualify_api.catalog.business_media import BusinessMediaService
from qualify_api.catalog.business_media_models import GalleryJob
from qualify_api.whatsapp.models import BrandSeasonalMedia
from qualify_api.whatsapp.seasonal import (
    JOB_KIND,
    MemorySourceReads,
    PostgresSeasonalRepository,
    SeasonalMediaService,
    approved_for_worker,
)

pytestmark = pytest.mark.db


def _service(tenant, brand, pieces) -> SeasonalMediaService:
    sources = MemorySourceReads()
    sources.pieces[(tenant, brand)] = pieces
    sources.logos[(tenant, brand)] = f"t/{tenant}/brand/{brand}/logo.png"
    return SeasonalMediaService(PostgresSeasonalRepository(), sources)


def _season() -> str:
    return f"navidad-{uuid4().hex[:6]}"


def test_planning_twice_writes_each_slot_and_job_once() -> None:
    brand, user, _ = _provision(TENANT_A, "A")
    pieces = [_piece(TENANT_A, brand, generated_days_ago=1) for _ in range(3)]
    service = _service(TENANT_A, brand, pieces)
    season = _season()
    first = service.plan_batch(TENANT_A, brand, season, "Navidad", "free", user)
    again = service.plan_batch(TENANT_A, brand, season, "Navidad", "free", user)
    assert {m.id for m in first} == {m.id for m in again}
    with tenant_session(TENANT_A) as session:
        jobs = session.scalars(
            select(GalleryJob).where(GalleryJob.brand_id == brand, GalleryJob.kind == JOB_KIND)
        ).all()
        mine = [j for j in jobs if j.payload["season_key"] == season]
        assert len(mine) == len(first)
        assert {j.payload["media_id"] for j in mine} == {str(m.id) for m in first}


#: A pair of its own (seeded like the shared ones): other db test files plan seasonal rows
#: for the shared TENANT_B, which would make «B sees nothing» fail on B's OWN rows
#: (CI run 42736238417) — this pair keeps the strict assertion meaningful.
ISOLATION_A = UUID("a0000000-0000-4000-8000-00000000150a")
ISOLATION_B = UUID("b0000000-0000-4000-8000-00000000150b")


def test_another_tenant_never_sees_the_library() -> None:
    brand, user, _ = _provision(ISOLATION_A, "A")
    _provision(ISOLATION_B, "B")
    planned = _service(ISOLATION_A, brand, []).plan_batch(
        ISOLATION_A, brand, _season(), "Navidad", "free", user
    )
    assert planned
    with tenant_session(ISOLATION_B) as session:
        assert session.scalars(select(BrandSeasonalMedia)).all() == []
        ids = [m.id for m in planned]
        visible = session.scalars(
            select(BrandSeasonalMedia).where(BrandSeasonalMedia.id.in_(ids))
        ).all()
        assert visible == []  # none of A's media, looked up by id
    assert approved_for_worker(ISOLATION_B, brand) == []


def _key(tenant: UUID, brand: UUID, media, attempt: int) -> str:
    ext = "webp" if media.kind == "sticker" else "mp4"
    return f"seasonal/{tenant}/{brand}/{media.season_key}/{media.id}-{attempt}.{ext}"


def test_attempts_past_three_and_delete_then_replan_hold_in_postgres() -> None:
    """m-25016851 (0153): «Pedir otro» past three, «Eliminar» keeps the row with no file,
    and planning the season again revives the deleted slot with a new job."""
    brand, user, _ = _provision(TENANT_A, "A")
    service = _service(TENANT_A, brand, [])
    season = _season()
    (media, *_) = service.plan_batch(TENANT_A, brand, season, "Navidad", "free", user)
    with tenant_session(TENANT_A) as session:
        row = session.get(BrandSeasonalMedia, media.id)
        row.attempt, row.status = 12, "ready"
        row.object_key = _key(TENANT_A, brand, media, 12)
        row.bytes = 1000
    gone = service.delete(TENANT_A, brand, media.id, user)
    assert (gone.status, gone.object_key, gone.attempt) == ("deleted", None, 12)
    assert media.id not in {m.id for m in service.list_season(TENANT_A, brand, season)}
    again = {m.id: m for m in service.plan_batch(TENANT_A, brand, season, "Navidad", "free", user)}[
        media.id
    ]
    assert (again.status, again.attempt) == ("pending", 13)
    with tenant_session(TENANT_A) as session:
        keys = session.scalars(
            select(GalleryJob.idempotency_key).where(GalleryJob.brand_id == brand)
        ).all()
    assert f"seasonal:{media.id}:13" in keys


def test_the_file_key_and_the_ready_file_are_checked_by_the_database() -> None:
    brand, user, _ = _provision(TENANT_A, "A")
    (media, *_) = _service(TENANT_A, brand, []).plan_batch(
        TENANT_A, brand, _season(), "Navidad", "free", user
    )
    for values in (
        {"object_key": f"seasonal/{TENANT_B}/{brand}/{media.season_key}/x-1.webp"},
        {"object_key": f"seasonal/{TENANT_A}/{brand}/{media.season_key}/x-2.webp"},  # attempt
        {"attempt": SEASONAL_MAX_ATTEMPTS + 1},  # past the technical ceiling (0153)
        {"status": "ready"},  # no file
        # m-25016851: a deleted medium points at no file
        {"status": "deleted", "object_key": _key(TENANT_A, brand, media, 1)},
    ):
        with pytest.raises(DBAPIError), tenant_session(TENANT_A) as session:
            row = session.get(BrandSeasonalMedia, media.id)
            for column, value in values.items():
                setattr(row, column, value)
            session.flush()


def test_a_seasonal_job_needs_an_object_payload() -> None:
    brand, _, _ = _provision(TENANT_A, "A")
    with pytest.raises(DBAPIError), tenant_session(TENANT_A) as session:
        session.add(
            GalleryJob(
                tenant_id=TENANT_A,
                brand_id=brand,
                kind=JOB_KIND,
                idempotency_key=f"seasonal:{uuid4()}",
                pipeline_version="seasonal-v1",
                payload=None,
            )
        )
        session.flush()


def test_the_galleria_job_list_ignores_seasonal_jobs(tmp_path: Path) -> None:
    brand, user, _ = _provision(TENANT_A, "A")
    _service(TENANT_A, brand, []).plan_batch(TENANT_A, brand, _season(), "Navidad", "free", user)
    gallery = BusinessMediaService(gate=None, staging_root=tmp_path)  # type: ignore[arg-type]
    jobs = gallery.list_gallery_jobs(tenant_id=TENANT_A, brand_id=brand)
    assert all(j.kind in ("ingest", "cut") for j in jobs)


def test_asking_for_another_moves_the_same_row_and_enqueues_the_next_attempt() -> None:
    brand, user, _ = _provision(TENANT_A, "A")
    deleted: list[list[str]] = []
    service = _service(TENANT_A, brand, [])
    service._delete_objects = lambda _t, _b, keys: deleted.append(keys)  # no R2 locally
    media = next(
        m
        for m in service.plan_batch(TENANT_A, brand, _season(), "Navidad", "free", user)
        if m.kind == "sticker"
    )
    key = f"seasonal/{TENANT_A}/{brand}/{media.season_key}/{media.id}-1.webp"
    service.mark_ready(
        tenant_id=TENANT_A,
        brand_id=brand,
        media_id=media.id,
        attempt=1,
        object_key=key,
        bytes=10,
        width=512,
        height=512,
        duration_ms=None,
    )
    again = service.request_another(TENANT_A, brand, media.id, user)
    assert (again.attempt, again.status, again.object_key) == (2, "pending", None)
    assert deleted == [[key]]
    with tenant_session(TENANT_A) as session:
        keys = set(
            session.scalars(
                select(GalleryJob.idempotency_key).where(
                    GalleryJob.idempotency_key.like(f"seasonal:{media.id}:%")
                )
            ).all()
        )
    assert keys == {f"seasonal:{media.id}:1", f"seasonal:{media.id}:2"}


def test_save_all_writes_every_row_or_none() -> None:
    from dataclasses import replace

    from qualify_api.whatsapp.seasonal import WrongState

    brand, user, _ = _provision(TENANT_A, "A")
    repo = PostgresSeasonalRepository()
    service = _service(TENANT_A, brand, [])
    season = _season()
    stickers = [
        m
        for m in service.plan_batch(TENANT_A, brand, season, "Navidad", "free", user)
        if m.kind == "sticker"
    ][:2]
    ready = []
    for media in stickers:
        ready.append(
            service.mark_ready(
                tenant_id=TENANT_A,
                brand_id=brand,
                media_id=media.id,
                attempt=1,
                object_key=f"seasonal/{TENANT_A}/{brand}/{season}/{media.id}-1.webp",
                bytes=10,
                width=512,
                height=512,
                duration_ms=None,
            )
        )
    service.reject(TENANT_A, brand, ready[1].id, user)  # changed after the caller read it
    with pytest.raises(WrongState):
        repo.save_all([(replace(m, status="approved"), m) for m in ready])
    assert [repo.get(tenant_id=TENANT_A, media_id=m.id).status for m in ready] == [
        "ready",
        "rejected",
    ]
