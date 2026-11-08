"""`media-worker` claims and settles `seasonal_media` jobs (m-24976892) against the compose
Postgres: the library's rows and jobs are real (0142), the recipe is a fake and the bucket
is an in-memory store behind the real `ObjectGate` — never R2, no FFmpeg."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from packages.api.tests.test_creative_retention_db import _provision
from PIL import Image
from qualify_creative.seasonal import RecipeOutput
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore
from sqlalchemy import select

from qualify_api.catalog.business_media_models import GalleryJob
from qualify_api.catalog.media_worker import SEASONAL_WAIT_BOUND, MediaJobRunner
from qualify_api.creative.seasonal_job import PostgresSeasonalSources, SeasonalMediaJobHandler
from qualify_api.whatsapp.seasonal import (
    MemorySourceReads,
    PostgresSeasonalRepository,
    SeasonalMediaService,
)

pytestmark = pytest.mark.db

#: A tenant of its own: no other test's seasonal jobs sit in its queue.
TENANT = UUID("c0000000-0000-4000-8000-0000000005e5")


class Sources(PostgresSeasonalSources):
    """The real row read; no Brand Kit lookups (no kit is provisioned): the logo key is
    the one `_world` planned with."""

    def palette(self, tenant_id: UUID, brand_id: UUID) -> list[str]:
        return ["#C81E1E", "#14785A"]

    def heading_font(self, tenant_id: UUID, brand_id: UUID) -> tuple[str | None, str | None]:
        return None, None

    def logo_key(self, tenant_id: UUID, brand_id: UUID) -> str | None:
        return f"t/{tenant_id}/brand/{brand_id}/logo.png"  # the brand kit's, as planned


class NoNormalizer:
    def normalize_file(self, source: Path, *, out_dir: Path) -> Any:  # pragma: no cover
        raise AssertionError("no ingest job here")


def _sticker(recipe: str, *args: Any, **kwargs: Any) -> RecipeOutput:
    """A fake output of the recipe's kind (the batch also holds `b-logo`, a video)."""
    video = recipe.startswith("b-")
    return RecipeOutput(
        data=b"fake-mp4-bytes" if video else b"RIFF-fake-webp",
        kind="video" if video else "sticker",
        recipe=recipe,
        content_type="video/mp4" if video else "image/webp",
        ext="mp4" if video else "webp",
        width=512,
        height=512,
        duration_ms=2000,
        frames=30,
        bytes=14,
        pipeline_version="seasonal-b-1" if video else "seasonal-e-1",
        encoding="fake",
    )


def _world(tmp_path: Path, render: Any = _sticker):  # noqa: ANN202
    brand, user, _ = _provision(TENANT, "S")
    logo_key = f"t/{TENANT}/brand/{brand}/logo.png"
    reads = MemorySourceReads()
    reads.logos[(TENANT, brand)] = logo_key
    service = SeasonalMediaService(PostgresSeasonalRepository(), reads)
    store = MemoryObjectStore()
    buf = io.BytesIO()
    Image.new("RGBA", (64, 64), (200, 30, 30, 255)).save(buf, format="PNG")
    store.objects[logo_key] = buf.getvalue()
    gate = ObjectGate(store)
    handler = SeasonalMediaJobHandler(
        objects=gate, marks=service, sources=Sources(), render=render, tmp_root=tmp_path
    )
    runner = MediaJobRunner(
        gate=gate, staging_root=tmp_path, normalizer=NoNormalizer(), seasonal=handler
    )
    season = f"navidad-{uuid4().hex[:6]}"
    planned = service.plan_batch(TENANT, brand, season, "Navidad", "free", user)
    media = next(m for m in planned if m.recipe == "e-latido")
    return brand, service, store, runner, media


def _job(media_id: UUID, attempt: int) -> GalleryJob:
    with tenant_session(TENANT) as session:
        job = session.scalar(
            select(GalleryJob).where(GalleryJob.idempotency_key == f"seasonal:{media_id}:{attempt}")
        )
        assert job is not None
        session.expunge(job)
        return job


def _drain(runner: MediaJobRunner) -> None:
    for _ in range(10):
        if not runner.run_tenant(TENANT, limit=20):
            return


def test_a_seasonal_job_is_claimed_rendered_stored_and_settled(tmp_path: Path) -> None:
    brand, _service, store, runner, media = _world(tmp_path)
    assert media.status == "pending" and media.attempt == 1
    _drain(runner)
    row = PostgresSeasonalRepository().get(tenant_id=TENANT, media_id=media.id)
    key = f"seasonal/{TENANT}/{brand}/{media.season_key}/{media.id}-1.webp"
    assert row.status == "ready" and row.object_key == key and row.attempt == 1
    assert row.bytes == 14 and (row.width, row.height, row.duration_ms) == (512, 512, 2000)
    assert store.objects[key] == b"RIFF-fake-webp"
    job = _job(media.id, 1)
    assert job.status == "done" and job.lease_until is None and job.finished_at is not None
    assert job.result["attempt"] == 1 and job.result["recipe_version"] == "seasonal-e-1"
    assert list(tmp_path.glob("qualify-seasonal-*")) == []


def test_a_stale_attempt_is_dropped_and_its_file_deleted(tmp_path: Path) -> None:
    """«Pedir otro» while attempt 1 renders: its mark_ready raises StaleAttempt, the file it
    just wrote is deleted, its job settles; attempt 2's job then makes the medium."""
    state: dict[str, Any] = {}

    def ask_again_mid_render(recipe: str, *args: Any, **kwargs: Any) -> RecipeOutput:
        if recipe == "e-latido" and not state.get("asked"):
            state["asked"] = True
            service: SeasonalMediaService = state["service"]
            media = state["media"]
            service.mark_failed(
                tenant_id=TENANT, brand_id=media.brand_id, media_id=media.id, attempt=1, reason="x"
            )
            service.request_another(TENANT, media.brand_id, media.id, None)
        return _sticker(recipe)

    brand, service, store, runner, media = _world(tmp_path, render=ask_again_mid_render)
    state.update(service=service, media=media)
    first_key = f"seasonal/{TENANT}/{brand}/{media.season_key}/{media.id}-1.webp"
    second_key = f"seasonal/{TENANT}/{brand}/{media.season_key}/{media.id}-2.webp"

    # one claim: only the job of attempt 1 (the oldest) runs
    for _ in range(20):
        outcome = runner.run_tenant(TENANT, limit=1)
        if not outcome or _job(media.id, 1).status == "done":
            break
    first = _job(media.id, 1)
    assert first.status == "done" and first.result["skipped"] == "stale_attempt"
    assert first_key in store.puts and first_key not in store.objects
    row = PostgresSeasonalRepository().get(tenant_id=TENANT, media_id=media.id)
    assert row.attempt == 2 and row.status == "pending"

    _drain(runner)
    row = PostgresSeasonalRepository().get(tenant_id=TENANT, media_id=media.id)
    assert row.status == "ready" and row.object_key == second_key
    assert _job(media.id, 2).status == "done"
    assert first_key not in store.objects


def test_a_payload_mismatch_fails_the_job_and_touches_nothing(tmp_path: Path) -> None:
    brand, _service, store, runner, media = _world(tmp_path)
    job = _job(media.id, 1)
    wrong_key = f"seasonal/{TENANT}/{brand}/otra-temporada/{media.id}-1.webp"
    store.objects[wrong_key] = b"someone else's"
    with tenant_session(TENANT) as session:
        row = session.get(GalleryJob, job.id)
        row.payload = {**row.payload, "season_key": "otra-temporada"}
    _drain(runner)
    job = _job(media.id, 1)
    assert job.status == "failed" and job.last_error_code == "payload_mismatch"
    medium = PostgresSeasonalRepository().get(tenant_id=TENANT, media_id=media.id)
    assert medium.status == "pending" and medium.fail_reason is None
    assert store.objects[wrong_key] == b"someone else's"


ORDER_TENANT = UUID("c0000000-0000-4000-8000-0000000005e6")


def test_galeria_first_but_a_long_waiting_seasonal_job_goes_by_age(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    brand, user, _ = _provision(ORDER_TENANT, "O")
    reads = MemorySourceReads()
    reads.logos[(ORDER_TENANT, brand)] = f"t/{ORDER_TENANT}/brand/{brand}/logo.png"
    service = SeasonalMediaService(PostgresSeasonalRepository(), reads)
    runner = MediaJobRunner(
        gate=ObjectGate(MemoryObjectStore()),
        staging_root=tmp_path,
        normalizer=NoNormalizer(),
        seasonal=SeasonalMediaJobHandler(
            objects=ObjectGate(MemoryObjectStore()),
            marks=service,
            sources=Sources(),
            render=_sticker,
            tmp_root=tmp_path,
        ),
    )
    now = datetime.now(UTC)
    for waited, first in (
        (timedelta(minutes=1), "ingest"),
        (SEASONAL_WAIT_BOUND + timedelta(minutes=1), "seasonal_media"),
    ):
        with tenant_session(ORDER_TENANT) as session:
            session.query(GalleryJob).delete()
        planned = service.plan_batch(
            ORDER_TENANT, brand, f"navidad-{uuid4().hex[:6]}", "Navidad", "free", user
        )
        with tenant_session(ORDER_TENANT) as session:
            for job in session.query(GalleryJob).filter(GalleryJob.kind == "seasonal_media"):
                job.created_at = now - waited
            session.add(
                GalleryJob(
                    tenant_id=ORDER_TENANT,
                    brand_id=brand,
                    kind="ingest",
                    idempotency_key=f"ingest:{uuid4()}",
                    staged_path="staged.mp4",
                    upload_sha256="0" * 64,
                    pipeline_version="test",
                    created_at=now,
                )
            )
        assert planned
        claimed = runner.claim(ORDER_TENANT)
        assert claimed is not None and claimed.kind == first, (waited, claimed)
    with tenant_session(ORDER_TENANT) as session:
        session.query(GalleryJob).delete()
