"""`db`-marked tests of the Galería's business media (m-24955918, CM-1; ADR 47 and the
ADR 39 amendment) against the compose Postgres: schema CHECKs and RLS of 0133, the
service (photos, video jobs, «Quitar», limits, idempotency), `media-worker` (claim,
lease, crash recovery, failure cleanup) and the reconciler — with a REAL `ObjectGate`
over an in-memory store, so «no orphan object» is asserted by listing
`gallery/{tenant}/` after every path. No FFmpeg: the normalizer is a fake."""

from __future__ import annotations

import asyncio
import io
import os
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO
from uuid import UUID, uuid4

import pytest
from PIL import Image
from qualify_creative.video.business import NormalizedBusinessVideo, UnreadableVideo
from qualify_shared.db.admin import admin_session
from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.session import tenant_session
from qualify_shared.db.webhook import webhook_worker_session
from qualify_shared.objects.gate import ObjectGate, StoredObject
from qualify_shared.objects.keys import gallery_root
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.catalog.business_media import (
    CUTTING_TEXT,
    GALLERY_FULL_TEXT,
    MAX_BUSINESS_MEDIA,
    VIDEOS_WAITING_TEXT,
    BusinessMediaService,
)
from qualify_api.catalog.business_media_models import BusinessMedia, GalleryJob
from qualify_api.catalog.business_media_staging import staging_dir
from qualify_api.catalog.media_worker import (
    MediaJobRunner,
    ScopedTenants,
    cut_part_media_id,
    ingest_media_id,
    jobs_pass,
)
from qualify_api.catalog.read import DbProductCatalog
from qualify_api.catalog.service import CatalogError, CatalogService
from qualify_api.connections.purge import _PROTECTED_KEYS
from qualify_api.creative.media import LocalMediaStore
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

TENANT_A = UUID("a0000000-0000-4000-8000-0000000000e1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000e2")
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


# -- fixtures ------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


class R2Double:
    """In-memory store with the methods `ObjectGate` needs, dating each PUT by `clock`
    and able to fail on demand."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.objects: dict[str, tuple[bytes, datetime]] = {}
        self.down = False

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        if self.down:
            raise ConnectionError("R2 down")
        self.objects[key] = (fileobj.read(), self.clock())

    def open(self, key: str) -> IO[bytes]:
        return io.BytesIO(self.objects[key][0])

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        if self.down:
            raise ConnectionError("R2 down")
        return [
            StoredObject(key=k, size=len(d), last_modified=t)
            for k, (d, t) in sorted(self.objects.items())
            if k.startswith(prefix)
        ]

    def delete_keys(self, keys: list[str]) -> None:
        if self.down:
            raise ConnectionError("R2 down")
        for key in keys:
            self.objects.pop(key, None)

    def gallery(self, tenant: UUID) -> set[str]:
        return {k for k in self.objects if k.startswith(gallery_root(tenant))}


class FakeNormalizer:
    def __init__(self, *, has_audio: bool = True, source_ms: int = 42_000) -> None:
        self.has_audio = has_audio
        self.source_ms = source_ms
        self.fail_with: Exception | None = None
        self.calls = 0

    def normalize_file(self, source: Path, *, out_dir: Path) -> NormalizedBusinessVideo:
        self.calls += 1
        assert source.is_file()
        if self.fail_with is not None:
            raise self.fail_with
        video, poster = out_dir / "video.mp4", out_dir / "poster.jpg"
        video.write_bytes(b"\0\0\0\x18ftypisom" + source.read_bytes()[:64])
        poster.write_bytes(b"\xff\xd8poster")
        return NormalizedBusinessVideo(
            video_path=video,
            poster_path=poster,
            width=1080,
            height=1920,
            duration_ms=min(self.source_ms, 60_000),
            has_audio=self.has_audio,
            source_duration_ms=self.source_ms,
        )


@dataclass
class World:
    tenant: UUID
    brand: UUID
    other_tenant: UUID
    other_brand: UUID
    clock: Clock
    r2: R2Double
    service: BusinessMediaService
    runner: MediaJobRunner
    normalizer: FakeNormalizer
    root: Path


def _clean(tenant_id: UUID) -> None:
    with tenant_session(tenant_id) as session:
        session.execute(text("DELETE FROM gallery_jobs WHERE tenant_id = :t"), {"t": tenant_id})
        session.execute(text("DELETE FROM business_media WHERE tenant_id = :t"), {"t": tenant_id})


@pytest.fixture
def world(tmp_path: Path) -> World:
    with admin_session() as session:
        brands: dict[UUID, UUID] = {}
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"gallery-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
            brand = session.scalar(select(Brand).where(Brand.tenant_id == tid))
            if brand is None:
                brand = Brand(tenant_id=tid, name=f"gallery-brand-{name}")
                session.add(brand)
                session.flush()
            brands[tid] = brand.id
    _clean(TENANT_A)
    _clean(TENANT_B)
    clock = Clock()
    r2 = R2Double(clock)
    gate = ObjectGate(r2)
    normalizer = FakeNormalizer()
    return World(
        tenant=TENANT_A,
        brand=brands[TENANT_A],
        other_tenant=TENANT_B,
        other_brand=brands[TENANT_B],
        clock=clock,
        r2=r2,
        service=BusinessMediaService(gate=gate, staging_root=tmp_path, clock=clock),
        runner=MediaJobRunner(gate=gate, staging_root=tmp_path, normalizer=normalizer, clock=clock),
        normalizer=normalizer,
        root=tmp_path,
    )


@dataclass
class Chunk:
    filename: str
    data: bytes
    offset: int = 0


async def _aiter(chunks: Iterable[Chunk]) -> AsyncIterator[Chunk]:
    for chunk in chunks:
        yield chunk


def _upload(w: World, *files: tuple[str, bytes], tenant: UUID | None = None, brand=None):
    chunks = [Chunk(name, data) for name, data in files]
    return asyncio.run(
        w.service.add_business_media(
            tenant_id=tenant or w.tenant, brand_id=brand or w.brand, chunks=_aiter(chunks)
        )
    )


def _jpeg(color: tuple[int, int, int] = (200, 80, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (640, 480), color).save(out, format="JPEG")
    return out.getvalue()


def _staging(w: World, tenant: UUID | None = None) -> list[Path]:
    folder = staging_dir(w.root, tenant or w.tenant)
    return sorted(folder.iterdir()) if folder.exists() else []


def _live_folders(w: World, tenant: UUID | None = None) -> set[str]:
    tid = tenant or w.tenant
    with tenant_session(tid) as session:
        ids = session.scalars(select(BusinessMedia.id).where(BusinessMedia.deleted_at.is_(None)))
        return {f"{gallery_root(tid)}{i}/" for i in ids}


def _assert_no_orphans(w: World, tenant: UUID | None = None) -> None:
    """Every object under `gallery/{tenant}/` belongs to a live medium's folder."""
    tid = tenant or w.tenant
    folders = _live_folders(w, tid)
    assert all(any(k.startswith(f) for f in folders) for k in w.r2.gallery(tid)), (
        w.r2.gallery(tid),
        folders,
    )


# -- schema: CHECKs, RLS, grants -----------------------------------------------------------


def _row(tenant: UUID, brand: UUID, **over: object) -> BusinessMedia:
    media_id = over.pop("id", None) or uuid4()
    values: dict[str, object] = dict(
        id=media_id,
        tenant_id=tenant,
        brand_id=brand,
        media_type="video",
        object_key=f"gallery/{tenant}/{media_id}/video.mp4",
        poster_key=f"gallery/{tenant}/{media_id}/poster.jpg",
        content_type="video/mp4",
        duration_ms=10_000,
        has_audio=True,
        pipeline_version="gallery-ingest-v1",
    )
    values.update(over)
    return BusinessMedia(**values)


@pytest.mark.parametrize(
    "over",
    [
        {"duration_ms": 60_001},  # D2: never more than a minute
        {"duration_ms": None},
        {"poster_key": None},  # a video always has its poster
        {"object_key": "gallery/other/x/video.mp4"},
        {"object_key_suffix": "a/b.mp4"},
        {"old_root": True},
        {"media_type": "image", "poster_key": None, "duration_ms": None},  # photo with audio
        {"source_media_id": uuid4()},  # cut fields: all or none
        {"source_media_id": uuid4(), "cut_start_ms": 5000, "cut_end_ms": 5000},
        {
            "source_media_id": uuid4(),
            "cut_start_ms": 0,
            "cut_end_ms": 3000,
            "upload_sha256": "a" * 64,  # a cut part carries no upload digest
        },
        {"upload_sha256": "not-a-digest"},
    ],
)
def test_checks_refuse_malformed_rows(world: World, over: dict) -> None:
    media_id = uuid4()
    if "old_root" in over:  # 0136 (m-24971181): the old `t/…/gallery/` shape is refused
        over = {"object_key": f"t/{world.tenant}/gallery/{media_id}/video.mp4"}
    if "object_key_suffix" in over:
        over = {"object_key": f"gallery/{world.tenant}/{media_id}/{over['object_key_suffix']}"}
    with pytest.raises(IntegrityError):
        with tenant_session(world.tenant) as session:
            session.add(_row(world.tenant, world.brand, id=media_id, **over))
            session.flush()


def test_a_valid_cut_part_and_photo_are_accepted(world: World) -> None:
    with tenant_session(world.tenant) as session:
        session.add(
            _row(
                world.tenant,
                world.brand,
                source_media_id=uuid4(),
                cut_start_ms=0,
                cut_end_ms=3000,
                job_id=uuid4(),
                pipeline_version="gallery-cut-v1",
            )
        )
        photo_id = uuid4()
        session.add(
            _row(
                world.tenant,
                world.brand,
                id=photo_id,
                media_type="image",
                object_key=f"gallery/{world.tenant}/{photo_id}/photo.jpg",
                poster_key=None,
                duration_ms=None,
                has_audio=False,
                content_type="image/jpeg",
            )
        )


def test_rls_isolates_both_tables_and_refuses_cross_tenant_writes(world: World) -> None:
    with tenant_session(world.tenant) as session:
        session.add(_row(world.tenant, world.brand))
        session.add(
            GalleryJob(
                tenant_id=world.tenant,
                brand_id=world.brand,
                kind="ingest",
                idempotency_key="ingest:x:" + "a" * 64,
                staged_path="uploads/x",
                upload_sha256="a" * 64,
                pipeline_version="gallery-ingest-v1",
            )
        )
    with tenant_session(world.other_tenant) as session:
        assert session.scalars(select(BusinessMedia)).all() == []
        assert session.scalars(select(GalleryJob)).all() == []
    with pytest.raises(DBAPIError):
        with tenant_session(world.other_tenant) as session:
            session.add(_row(world.tenant, world.brand))
            session.flush()
    # Another tenant's brand cannot be named (composite FK to brands (id, tenant_id)).
    with pytest.raises(DBAPIError):
        with tenant_session(world.tenant) as session:
            session.add(_row(world.tenant, world.other_brand))
            session.flush()


def test_one_active_cut_per_video_and_active_keys_are_unique(world: World) -> None:
    source = uuid4()

    def cut(key: str) -> GalleryJob:
        return GalleryJob(
            tenant_id=world.tenant,
            brand_id=world.brand,
            kind="cut",
            idempotency_key=key,
            source_media_id=source,
            segments=[[0, 3000]],
            pipeline_version="gallery-cut-v1",
        )

    with tenant_session(world.tenant) as session:
        session.add(cut("cut:a"))
    with pytest.raises(IntegrityError):
        with tenant_session(world.tenant) as session:
            session.add(cut("cut:b"))  # a different cut of the same video, while one runs
            session.flush()
    with tenant_session(world.tenant) as session:
        session.execute(
            text("UPDATE gallery_jobs SET status = 'done' WHERE tenant_id = :t"),
            {"t": world.tenant},
        )
        session.add(cut("cut:a"))  # terminal jobs free both the key and the video


def test_purge_protects_gallery_keys_and_whatsapp_cannot_read_them(world: World) -> None:
    assert _PROTECTED_KEYS["business_media"] == ("object_key", "poster_key")
    with tenant_session(world.tenant) as session:
        session.add(_row(world.tenant, world.brand))
    with connection_purge_session(world.tenant) as session:
        keys = session.execute(
            text("SELECT object_key, poster_key FROM business_media WHERE tenant_id = :t"),
            {"t": world.tenant},
        ).all()
    assert len(keys) == 1
    # The WhatsApp menu's reader role has no grant at all on the Galería.
    with pytest.raises(DBAPIError):
        with webhook_worker_session() as session:
            session.execute(text("SELECT id FROM business_media LIMIT 1")).all()


# -- photos --------------------------------------------------------------------------------


def test_photo_goes_to_r2_and_is_isolated(world: World) -> None:
    [outcome] = _upload(world, ("local.jpg", _jpeg()))
    assert outcome.media is not None and not outcome.error_text
    media = outcome.media
    assert media.object_key == f"gallery/{world.tenant}/{media.id}/photo.jpg"
    assert media.media_type == "image" and not media.has_audio and media.duration_ms is None
    assert world.r2.gallery(world.tenant) == {media.object_key}
    assert _staging(world) == []  # nothing of the business stays on the volume
    listed = world.service.list_business_media(tenant_id=world.tenant, brand_id=world.brand)
    assert [m.id for m in listed] == [media.id]
    assert (
        world.service.list_business_media(tenant_id=world.other_tenant, brand_id=world.brand) == ()
    )
    # Another tenant cannot remove it.
    world.service.remove_business_media(tenant_id=world.other_tenant, media_id=media.id)
    assert world.r2.gallery(world.tenant) == {media.object_key}
    # Same photo again: the same medium.
    [again] = _upload(world, ("otra-vez.jpg", _jpeg()))
    assert again.duplicate and again.media and again.media.id == media.id
    _assert_no_orphans(world)


def test_an_unreadable_photo_is_refused_in_spanish(world: World) -> None:
    [outcome] = _upload(world, ("roto.jpg", b"not an image"))
    assert outcome.error_text.startswith("No pudimos abrir esta foto")
    assert world.r2.gallery(world.tenant) == set() and _staging(world) == []


def test_business_media_never_reach_product_reads(world: World, tmp_path: Path) -> None:
    catalog = CatalogService(store=LocalMediaStore(tmp_path / "local"), gallery=world.service)
    product_id = catalog.create_product(
        tenant_id=world.tenant,
        brand_id=world.brand,
        user_id=None,
        name=f"Shawarma {uuid4().hex[:6]}",
    )
    _upload(world, ("local.jpg", _jpeg()))
    assert catalog.list_business_media(tenant_id=world.tenant, brand_id=world.brand)
    products = catalog.list_products(tenant_id=world.tenant, brand_id=world.brand)
    assert all(m.object_key.find("/gallery/") < 0 for p in products for m in p.media)
    product = catalog.get_product(tenant_id=world.tenant, product_id=product_id)
    assert product.media == ()
    facts = DbProductCatalog().products_for(
        tenant_id=world.tenant, brand_id=world.brand, product_ref=product.name
    )
    assert facts
    assert all("/gallery/" not in str(f) for f in facts)


# -- videos: queue, worker, idempotency ----------------------------------------------------


def test_video_ingest_end_to_end_keeps_sound_and_cleans_staging(world: World) -> None:
    [outcome] = _upload(world, ("cocina.mov", b"video-bytes-1"))
    assert outcome.job is not None and outcome.job.status == "queued"
    assert len(_staging(world)) == 1
    jobs = world.service.list_gallery_jobs(tenant_id=world.tenant, brand_id=world.brand)
    assert [j.id for j in jobs] == [outcome.job.id]  # «Preparando…» survives a reload

    report = jobs_pass(world.runner, ScopedTenants([world.tenant]), limit=5)
    assert [o.status for o in report.outcomes] == ["done"]
    [media] = world.service.list_business_media(tenant_id=world.tenant, brand_id=world.brand)
    assert media.id == ingest_media_id(outcome.job.id)
    assert media.has_audio and media.duration_ms == 42_000 and media.duration_label == "0:42"
    assert media.poster_key == f"gallery/{world.tenant}/{media.id}/poster.jpg"
    assert world.r2.gallery(world.tenant) == {media.object_key, media.poster_key}
    assert _staging(world) == []
    [job] = world.service.list_gallery_jobs(tenant_id=world.tenant, brand_id=world.brand)
    assert job.status == "done" and job.media_id == media.id and not job.trimmed
    with tenant_session(world.tenant) as session:
        row = session.get(BusinessMedia, media.id)
        assert row.job_id == outcome.job.id and row.pipeline_version == "gallery-ingest-v1"
    _assert_no_orphans(world)


def test_a_silent_video_records_no_audio_and_a_long_one_says_trimmed(world: World) -> None:
    world.normalizer.has_audio = False
    world.normalizer.source_ms = 95_000
    [outcome] = _upload(world, ("largo.mp4", b"long-video"))
    jobs_pass(world.runner, ScopedTenants([world.tenant]), limit=5)
    [media] = world.service.list_business_media(tenant_id=world.tenant, brand_id=world.brand)
    assert not media.has_audio and media.duration_ms == 60_000
    [job] = world.service.list_gallery_jobs(tenant_id=world.tenant, brand_id=world.brand)
    assert job.id == outcome.job.id and job.trimmed


def test_same_video_twice_at_once_or_already_live_gives_one_medium(world: World) -> None:
    first, second = _upload(world, ("a.mov", b"same-bytes"), ("b.mov", b"same-bytes"))
    assert first.job and second.job and second.duplicate and second.job.id == first.job.id
    assert len(_staging(world)) == 1  # the duplicate's staged copy is gone
    jobs_pass(world.runner, ScopedTenants([world.tenant]), limit=5)
    [live] = _upload(world, ("c.mov", b"same-bytes"))
    assert live.duplicate and live.media and live.media.id == ingest_media_id(first.job.id)
    assert _staging(world) == []
    assert len(world.service.list_business_media(tenant_id=world.tenant, brand_id=world.brand)) == 1


def test_after_quitar_the_same_video_comes_back_as_a_new_medium(world: World) -> None:
    [first] = _upload(world, ("a.mov", b"bytes-q"))
    jobs_pass(world.runner, ScopedTenants([world.tenant]), limit=5)
    old = ingest_media_id(first.job.id)
    world.service.remove_business_media(tenant_id=world.tenant, media_id=old)
    assert world.r2.gallery(world.tenant) == set()
    [again] = _upload(world, ("a.mov", b"bytes-q"))
    assert again.job and not again.duplicate and again.job.id != first.job.id
    jobs_pass(world.runner, ScopedTenants([world.tenant]), limit=5)
    [media] = world.service.list_business_media(tenant_id=world.tenant, brand_id=world.brand)
    assert media.id != old
    _assert_no_orphans(world)


def test_reuploading_an_original_after_it_was_cut_creates_a_new_original(world: World) -> None:
    """Cut parts carry `upload_sha256 = NULL`: the upload dedup compares originals only."""
    [first] = _upload(world, ("a.mov", b"to-be-cut"))
    jobs_pass(world.runner, ScopedTenants([world.tenant]), limit=5)
    original = ingest_media_id(first.job.id)
    job_id = uuid4()
    part = cut_part_media_id(job_id, 0)
    with tenant_session(world.tenant) as session:  # what CM-3's cut leaves behind
        session.add(
            _row(
                world.tenant,
                world.brand,
                id=part,
                source_media_id=original,
                cut_start_ms=0,
                cut_end_ms=5000,
                job_id=job_id,
                pipeline_version="gallery-cut-v1",
            )
        )
        session.get(BusinessMedia, original).deleted_at = world.clock()
    [again] = _upload(world, ("a.mov", b"to-be-cut"))
    assert again.job and not again.duplicate


def test_three_videos_waiting_refuse_the_fourth_before_upload(world: World) -> None:
    for i in range(3):
        [o] = _upload(world, (f"v{i}.mov", f"video-{i}".encode()))
        assert o.job
    with pytest.raises(CatalogError) as refused:
        world.service.check_can_upload(tenant_id=world.tenant, brand_id=world.brand)
    assert refused.value.args[0] == VIDEOS_WAITING_TEXT
    [fourth] = _upload(world, ("v3.mov", b"video-3"))
    assert fourth.error_text == VIDEOS_WAITING_TEXT
    assert len(_staging(world)) == 3
    # A photo is still welcome.
    [photo] = _upload(world, ("f.jpg", _jpeg()))
    assert photo.media
    # Another business has its own three.
    world.service.check_can_upload(tenant_id=world.other_tenant, brand_id=world.other_brand)


def test_the_gallery_holds_at_most_sixty(world: World) -> None:
    with tenant_session(world.tenant) as session:
        for _ in range(MAX_BUSINESS_MEDIA - 1):
            session.add(_row(world.tenant, world.brand))
    [o] = _upload(world, ("v.mov", b"the-60th"))  # live 59 + 1 pending = 60
    assert o.job
    [photo] = _upload(world, ("f.jpg", _jpeg()))
    assert photo.error_text == GALLERY_FULL_TEXT
    [video] = _upload(world, ("w.mov", b"the-61st"))  # full, not «3 videos waiting»
    assert video.error_text == GALLERY_FULL_TEXT and _staging(world) != []
    with pytest.raises(CatalogError) as full:
        world.service.check_can_upload(tenant_id=world.tenant, brand_id=world.brand, videos=0)
    assert full.value.args[0] == GALLERY_FULL_TEXT


def test_a_refused_enqueue_deletes_its_staged_file(world: World) -> None:
    from qualify_api.catalog.business_media_staging import stage_chunks
    from qualify_api.catalog.service import UnknownBrand

    [staged] = asyncio.run(
        stage_chunks(
            _aiter([Chunk("x.mov", b"orphan")]),
            root=world.root,
            tenant_id=world.tenant,
            max_videos=3,
        )
    )
    assert len(_staging(world)) == 1
    with pytest.raises(UnknownBrand):  # another tenant's brand is invisible
        world.service.enqueue_video(
            tenant_id=world.tenant, brand_id=world.other_brand, staged=staged
        )
    assert _staging(world) == []


# -- worker: lease, crash, failure ---------------------------------------------------------


def test_a_job_cut_by_a_deploy_is_resumed_after_its_lease(world: World) -> None:
    [o] = _upload(world, ("a.mov", b"crash"))
    claimed = world.runner.claim(world.tenant)
    assert claimed and claimed.id == o.job.id and claimed.attempts == 1
    # The container dies here (deploy). Within the lease nobody else takes it.
    world.clock.advance(minutes=5)
    assert world.runner.claim(world.tenant) is None
    world.clock.advance(minutes=6)
    report = jobs_pass(world.runner, ScopedTenants([world.tenant]), limit=5)
    assert [x.status for x in report.outcomes] == ["done"]
    with tenant_session(world.tenant) as session:
        assert session.get(GalleryJob, o.job.id).attempts == 2
    # The dead worker's late settle is refused (lost lease), nothing duplicates.
    late = world.runner.process(claimed)
    assert late.status in {"lost_lease", "failed"}
    assert len(world.service.list_business_media(tenant_id=world.tenant, brand_id=world.brand)) == 1
    _assert_no_orphans(world)


def test_three_transient_failures_fail_the_job_and_leave_nothing(world: World) -> None:
    [o] = _upload(world, ("a.mov", b"flaky"))
    world.normalizer.fail_with = TimeoutError("ffmpeg too slow")
    outcomes = []
    for _ in range(3):
        outcomes += world.runner.run_tenant(world.tenant)
        world.clock.advance(minutes=5)  # past the retry backoff
    assert [x.status for x in outcomes] == ["retry", "retry", "failed"]
    [job] = world.service.list_gallery_jobs(tenant_id=world.tenant, brand_id=world.brand)
    assert job.status == "failed" and job.last_error_code == "normalize:TimeoutError"
    assert _staging(world) == [] and world.r2.gallery(world.tenant) == set()
    world.service.dismiss_gallery_job(tenant_id=world.tenant, job_id=job.id)
    assert world.service.list_gallery_jobs(tenant_id=world.tenant, brand_id=world.brand) == ()


def test_an_unreadable_video_fails_at_once(world: World) -> None:
    _upload(world, ("a.mov", b"garbage"))
    world.normalizer.fail_with = UnreadableVideo("no video stream")
    [outcome] = world.runner.run_tenant(world.tenant)
    assert outcome.status == "failed" and outcome.error_code == "unreadable"
    assert _staging(world) == []


def test_r2_down_during_ingest_retries_onto_the_same_keys(world: World) -> None:
    [o] = _upload(world, ("a.mov", b"r2-flaky"))
    world.r2.down = True
    [first] = world.runner.run_tenant(world.tenant)
    assert first.status == "retry"
    world.r2.down = False
    world.clock.advance(minutes=2)
    [second] = world.runner.run_tenant(world.tenant)
    assert second.status == "done" and second.media_id == ingest_media_id(o.job.id)
    _assert_no_orphans(world)


def test_the_worker_never_processes_another_tenants_jobs(world: World) -> None:
    _upload(world, ("a.mov", b"tenant-a"))
    assert world.runner.run_tenant(world.other_tenant) == []
    assert world.normalizer.calls == 0


# -- «Quitar» and the reconciler -----------------------------------------------------------


def test_quitar_deletes_folder_and_row(world: World) -> None:
    [o] = _upload(world, ("a.jpg", _jpeg()))
    world.service.remove_business_media(tenant_id=world.tenant, media_id=o.media.id)
    assert world.r2.gallery(world.tenant) == set()
    with tenant_session(world.tenant) as session:
        assert session.get(BusinessMedia, o.media.id) is None
    world.service.remove_business_media(tenant_id=world.tenant, media_id=o.media.id)  # no-op


def test_quitar_is_refused_while_the_video_is_being_cut(world: World) -> None:
    [o] = _upload(world, ("a.mov", b"cut-me"))
    jobs_pass(world.runner, ScopedTenants([world.tenant]), limit=5)
    media_id = ingest_media_id(o.job.id)
    with tenant_session(world.tenant) as session:
        cut = GalleryJob(
            tenant_id=world.tenant,
            brand_id=world.brand,
            kind="cut",
            idempotency_key="cut:x",
            source_media_id=media_id,
            segments=[[0, 3000]],
            pipeline_version="gallery-cut-v1",
        )
        session.add(cut)
        session.flush()
        cut_id = cut.id
    with pytest.raises(CatalogError) as refused:
        world.service.remove_business_media(tenant_id=world.tenant, media_id=media_id)
    assert refused.value.args[0] == CUTTING_TEXT
    with tenant_session(world.tenant) as session:
        session.get(GalleryJob, cut_id).status = "failed"  # a failed cut lifts the mark
    world.service.remove_business_media(tenant_id=world.tenant, media_id=media_id)
    assert world.r2.gallery(world.tenant) == set()


def test_quitar_with_r2_down_leaves_a_tombstone_the_reconciler_finishes(world: World) -> None:
    [o] = _upload(world, ("a.jpg", _jpeg()))
    world.r2.down = True
    world.service.remove_business_media(tenant_id=world.tenant, media_id=o.media.id)
    assert world.service.list_business_media(tenant_id=world.tenant, brand_id=world.brand) == ()
    world.r2.down = False
    report = world.runner.reconcile_tenant(world.tenant)
    assert report.tombstones == 0  # younger than an hour: left alone
    world.clock.advance(hours=1, minutes=1)
    report = world.runner.reconcile_tenant(world.tenant)
    assert report.tombstones == 1 and report.objects == 1
    assert world.r2.gallery(world.tenant) == set()
    with tenant_session(world.tenant) as session:
        assert session.get(BusinessMedia, o.media.id) is None


def test_reconciler_deletes_a_folder_left_between_put_and_row(world: World) -> None:
    gate = ObjectGate(world.r2)
    orphan, fresh = uuid4(), uuid4()
    gate.put_gallery_media(world.tenant, orphan, "photo.jpg", io.BytesIO(b"1"), "image/jpeg")
    [kept] = _upload(world, ("a.jpg", _jpeg()))
    [pending] = _upload(world, ("b.mov", b"pending-video"))  # its folder is expected
    world.clock.advance(hours=25)
    gate.put_gallery_media(world.tenant, fresh, "photo.jpg", io.BytesIO(b"2"), "image/jpeg")
    gate.put_gallery_media(
        world.tenant,
        ingest_media_id(pending.job.id),
        "video.mp4",
        io.BytesIO(b"3"),
        "video/mp4",
    )
    world.clock.advance(hours=25)
    gate.put_gallery_media(
        world.tenant,
        uuid4(),
        "photo.jpg",
        io.BytesIO(b"4"),
        "image/jpeg",
    )
    report = world.runner.reconcile_tenant(world.tenant)
    assert report.folders == 2 and report.objects == 2  # orphan + fresh (now > 24 h)
    remaining = world.r2.gallery(world.tenant)
    assert kept.media.object_key in remaining
    assert f"gallery/{world.tenant}/{ingest_media_id(pending.job.id)}/video.mp4" in remaining
    assert not any(str(orphan) in k or str(fresh) in k for k in remaining)
    assert len(remaining) == 3  # kept photo, pending video, the < 24 h one
    # Another tenant's reconcile never touches this tenant.
    assert world.runner.reconcile_tenant(world.other_tenant).objects == 0
    assert world.r2.gallery(world.tenant) == remaining


def test_reconciler_deletes_old_staging_files_no_job_points_at(world: World) -> None:
    [pending] = _upload(world, ("a.mov", b"waiting"))
    folder = staging_dir(world.root, world.tenant)
    abandoned = folder / str(uuid4())
    abandoned.write_bytes(b"half an upload")
    old = (T0 - timedelta(hours=30)).timestamp()
    for path in folder.iterdir():
        os.utime(path, (old, old))
    report = world.runner.reconcile_tenant(world.tenant)
    assert report.staging_files == 1
    assert not abandoned.exists() and len(_staging(world)) == 1  # the job's file stays
    assert pending.job


def test_no_orphans_after_every_path(world: World) -> None:
    """Success, a cut-off upload, «Quitar», and «Quitar» with R2 down — then a reconcile
    a day later: only live media's folders remain."""
    _upload(world, ("ok.jpg", _jpeg((1, 2, 3))))
    [video] = _upload(world, ("ok.mov", b"ok-video"))
    jobs_pass(world.runner, ScopedTenants([world.tenant]), limit=5)
    ObjectGate(world.r2).put_gallery_media(
        world.tenant,
        uuid4(),
        "photo.jpg",
        io.BytesIO(b"x"),
        "image/jpeg",
    )  # an upload cut between the PUT and the row
    [gone] = _upload(world, ("gone.jpg", _jpeg((9, 9, 9))))
    world.service.remove_business_media(tenant_id=world.tenant, media_id=gone.media.id)
    [down] = _upload(world, ("down.jpg", _jpeg((7, 7, 7))))
    world.r2.down = True
    world.service.remove_business_media(tenant_id=world.tenant, media_id=down.media.id)
    world.r2.down = False
    world.clock.advance(hours=25)
    world.runner.reconcile_tenant(world.tenant)
    _assert_no_orphans(world)
    assert len(_live_folders(world)) == 2 and video.job
