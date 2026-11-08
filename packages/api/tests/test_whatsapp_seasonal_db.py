"""m-24976891 against the compose Postgres (migration 0142): the seasonal library's RLS,
its unique slot (planning twice writes nothing new), the job written with each new row
and its `payload` (SQL NULL or an object, required for `seasonal_media`), the file key
CHECK, the worker door, and the Galería's job list ignoring seasonal jobs."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from packages.api.tests.test_creative_retention_db import (
    TENANT_A,
    TENANT_B,
    _piece,
    _provision,
)
from qualify_shared.db.session import tenant_session
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


def test_another_tenant_never_sees_the_library() -> None:
    brand, user, _ = _provision(TENANT_A, "A")
    _provision(TENANT_B, "B")
    _service(TENANT_A, brand, []).plan_batch(TENANT_A, brand, _season(), "Navidad", "free", user)
    with tenant_session(TENANT_B) as session:
        assert session.scalars(select(BrandSeasonalMedia)).all() == []
    assert approved_for_worker(TENANT_B, brand) == []


def test_the_file_key_and_the_ready_file_are_checked_by_the_database() -> None:
    brand, user, _ = _provision(TENANT_A, "A")
    (media, *_) = _service(TENANT_A, brand, []).plan_batch(
        TENANT_A, brand, _season(), "Navidad", "free", user
    )
    for values in (
        {"object_key": f"seasonal/{TENANT_B}/{brand}/{media.season_key}/x-1.webp"},
        {"object_key": f"seasonal/{TENANT_A}/{brand}/{media.season_key}/x-2.webp"},  # attempt
        {"attempt": 4},
        {"status": "ready"},  # no file
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
