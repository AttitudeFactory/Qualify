"""`db`-marked tests of the Galería cut (m-24955923, CM-3; ADR 39 amendment rules 3-5)
against the compose Postgres, with a REAL `ObjectGate` over an in-memory store so «no
orphan object» is asserted by listing `t/{tenant}/gallery/` after every path: success,
a failure at each step, retries, a killed worker, and the hand-off to the reconciler.
FFmpeg is faked here (its accuracy is measured in `test_video_business_cut.py`)."""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO
from uuid import UUID, uuid4

import pytest
from PIL import Image
from qualify_creative.video.business import NormalizedBusinessVideo, UnreadableVideo
from qualify_creative.video.business_cut import CutBusinessPart
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate, StoredObject
from qualify_shared.objects.keys import gallery_media_prefix, gallery_root
from sqlalchemy import select, text

from qualify_api.catalog.business_media import (
    ALREADY_CUTTING_TEXT,
    CUT_GALLERY_FULL_TEXT,
    CUTTING_TEXT,
    NO_PART_KEPT_TEXT,
    NOTHING_CUT_TEXT,
    ONLY_VIDEOS_TEXT,
    PART_TOO_SHORT_TEXT,
    BusinessMediaService,
    CutSpan,
    UnknownBusinessMedia,
)
from qualify_api.catalog.business_media_models import BusinessMedia, GalleryJob
from qualify_api.catalog.media_worker import (
    MediaJobRunner,
    ScopedTenants,
    cut_part_media_id,
    ingest_media_id,
    jobs_pass,
)
from qualify_api.catalog.service import CatalogError
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

TENANT_A = UUID("a0000000-0000-4000-8000-0000000c3001")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000c3002")
T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
SOURCE_MS = 20_000
#: keep 0-4 s, remove 4-9 s, keep 9-20 s.
SPANS = (CutSpan(0, 4_000, True), CutSpan(4_000, 9_000, False), CutSpan(9_000, 20_000, True))


# -- doubles -------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


class R2Double:
    """In-memory store with what `ObjectGate` needs, dating each PUT, failing on demand:
    every call (`down`), PUTs of keys containing `fail_put` or deletes (`fail_delete`)."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.objects: dict[str, tuple[bytes, datetime]] = {}
        self.down = False
        self.fail_put: str | None = None
        self.fail_delete = False

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        if self.down or (self.fail_put is not None and self.fail_put in key):
            raise ConnectionError("R2 down")
        self.objects[key] = (fileobj.read(), self.clock())

    def open(self, key: str) -> IO[bytes]:
        if self.down:
            raise ConnectionError("R2 down")
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
        if self.down or self.fail_delete:
            raise ConnectionError("R2 down")
        for key in keys:
            self.objects.pop(key, None)

    def folder(self, tenant: UUID, media_id: UUID) -> set[str]:
        prefix = gallery_media_prefix(tenant, media_id)
        return {k for k in self.objects if k.startswith(prefix)}

    def gallery(self, tenant: UUID) -> set[str]:
        return {k for k in self.objects if k.startswith(gallery_root(tenant))}


class FakeNormalizer:
    def normalize_file(self, source: Path, *, out_dir: Path) -> NormalizedBusinessVideo:
        video, poster = out_dir / "video.mp4", out_dir / "poster.jpg"
        video.write_bytes(b"\0\0\0\x18ftypisom" + source.read_bytes()[:64])
        poster.write_bytes(b"\xff\xd8poster")
        return NormalizedBusinessVideo(
            video_path=video,
            poster_path=poster,
            width=1080,
            height=1920,
            duration_ms=SOURCE_MS,
            has_audio=True,
            source_duration_ms=SOURCE_MS,
        )


class Killed(BaseException):
    """The container dying mid-job (a deploy, the OOM killer): nothing catches it."""


class FakeCutter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.sources: list[bytes] = []
        self.fail_with: BaseException | None = None

    def cut_file(
        self, source: Path, *, start_ms: int, end_ms: int, out_dir: Path
    ) -> CutBusinessPart:
        self.sources.append(source.read_bytes())
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append((start_ms, end_ms))
        out_dir.mkdir(parents=True, exist_ok=True)
        video, poster = out_dir / "video.mp4", out_dir / "poster.jpg"
        video.write_bytes(f"part {start_ms}-{end_ms}".encode())
        poster.write_bytes(b"\xff\xd8part")
        return CutBusinessPart(
            video_path=video,
            poster_path=poster,
            start_ms=start_ms,
            end_ms=end_ms,
            width=1080,
            height=1920,
            duration_ms=end_ms - start_ms,
            has_audio=True,
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
    cutter: FakeCutter
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
                        name=f"gallery-cut-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
            brand = session.scalar(select(Brand).where(Brand.tenant_id == tid))
            if brand is None:
                brand = Brand(tenant_id=tid, name=f"gallery-cut-brand-{name}")
                session.add(brand)
                session.flush()
            brands[tid] = brand.id
    _clean(TENANT_A)
    _clean(TENANT_B)
    clock = Clock()
    r2 = R2Double(clock)
    gate = ObjectGate(r2)
    cutter = FakeCutter()
    return World(
        tenant=TENANT_A,
        brand=brands[TENANT_A],
        other_tenant=TENANT_B,
        other_brand=brands[TENANT_B],
        clock=clock,
        r2=r2,
        service=BusinessMediaService(gate=gate, staging_root=tmp_path, clock=clock),
        runner=MediaJobRunner(
            gate=gate,
            staging_root=tmp_path,
            normalizer=FakeNormalizer(),
            cutter=cutter,
            clock=clock,
        ),
        cutter=cutter,
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


def _jpeg(color: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(out, format="JPEG")
    return out.getvalue()


def _upload(w: World, name: str, data: bytes, *, tenant: UUID | None = None):
    tid = tenant or w.tenant
    brand = w.brand if tid == w.tenant else w.other_brand
    [outcome] = asyncio.run(
        w.service.add_business_media(
            tenant_id=tid, brand_id=brand, chunks=_aiter([Chunk(name, data)])
        )
    )
    return outcome


def _video(w: World, name: str = "local.mov", *, tenant: UUID | None = None) -> UUID:
    """A live 20 s business video, through the real ingest path."""
    tid = tenant or w.tenant
    outcome = _upload(w, name, f"video {name} {uuid4()}".encode(), tenant=tid)
    assert outcome.job is not None, outcome
    _pass(w, tid)
    return ingest_media_id(outcome.job.id)


def _pass(w: World, tenant: UUID | None = None):
    return jobs_pass(w.runner, ScopedTenants([tenant or w.tenant]), limit=5).outcomes


def _job(w: World, job_id: UUID) -> GalleryJob:
    with tenant_session(w.tenant) as session:
        job = session.get(GalleryJob, job_id)
        assert job is not None
        session.expunge(job)
        return job


def _row(w: World, media_id: UUID) -> BusinessMedia | None:
    with tenant_session(w.tenant) as session:
        row = session.get(BusinessMedia, media_id)
        if row is not None:
            session.expunge(row)
        return row


def _live_ids(w: World) -> list[UUID]:
    return [m.id for m in w.service.list_business_media(tenant_id=w.tenant, brand_id=w.brand)]


def _cut_jobs(w: World) -> int:
    with tenant_session(w.tenant) as session:
        return len(session.scalars(select(GalleryJob.id).where(GalleryJob.kind == "cut")).all())


def _assert_no_orphans(w: World) -> None:
    """Every object under `t/{tenant}/gallery/` sits in a LIVE medium's folder."""
    folders = {gallery_media_prefix(w.tenant, i) for i in _live_ids(w)}
    stray = {k for k in w.r2.gallery(w.tenant) if not any(k.startswith(f) for f in folders)}
    assert not stray, stray


# -- the happy path ------------------------------------------------------------------------


def test_cut_keeps_only_the_parts_with_provenance_in_the_originals_place(world: World) -> None:
    w = world
    first = _upload(w, "a.jpg", _jpeg((10, 20, 30))).media
    video = _video(w)
    last = _upload(w, "b.jpg", _jpeg((200, 20, 30))).media
    assert _live_ids(w) == [first.id, video, last.id]

    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    # Confirming only queues: nothing is encoded in the request.
    assert job.kind == "cut" and job.status == "queued" and job.source_media_id == video
    assert w.cutter.calls == []
    listed = w.service.list_gallery_jobs(tenant_id=w.tenant, brand_id=w.brand)
    assert job.id in {j.id for j in listed if j.active}  # «Cortando tu video…» survives a reload

    [outcome] = _pass(w)
    assert outcome.status == "done"
    # Only the kept spans were encoded, from the original's bytes in R2.
    assert w.cutter.calls == [(0, 4_000), (9_000, 20_000)]
    assert w.cutter.sources[0].startswith(b"\0\0\0\x18ftyp")

    parts = [cut_part_media_id(job.id, 0), cut_part_media_id(job.id, 1)]
    assert _live_ids(w) == [first.id, *parts, last.id]  # in order, where the video was
    assert _row(w, video) is None and not w.r2.folder(w.tenant, video)
    for index, (part_id, (start, end)) in enumerate(zip(parts, [(0, 4_000), (9_000, 20_000)])):
        row = _row(w, part_id)
        assert row is not None
        assert (row.source_media_id, row.cut_start_ms, row.cut_end_ms) == (video, start, end)
        assert row.job_id == job.id and row.pipeline_version == "gallery-cut-v1"
        assert row.upload_sha256 is None and row.has_audio and row.duration_ms == end - start
        assert row.filename == f"local.mov (parte {index + 1})"
        assert w.r2.folder(w.tenant, part_id) == {
            row.object_key,
            row.poster_key,
        }
    status = w.service.get_gallery_job(tenant_id=w.tenant, job_id=job.id)
    assert status.status == "done" and status.part_ids == tuple(parts)
    assert [j.id for j in w.service.list_cut_jobs(tenant_id=w.tenant, brand_id=w.brand)] == [job.id]
    _assert_no_orphans(w)


def test_the_same_request_gives_the_same_job_before_and_after_it_ran(world: World) -> None:
    w = world
    video = _video(w)
    one = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    two = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    assert one.id == two.id and _cut_jobs(w) == 1
    _pass(w)
    three = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    assert three.id == one.id and three.status == "done" and _cut_jobs(w) == 1
    assert len(_live_ids(w)) == 2  # no second set of parts
    with pytest.raises(UnknownBusinessMedia):  # a different cut of a video that is gone
        w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=[CutSpan(0, 5_000, True)])


def test_a_second_cut_and_quitar_are_refused_while_one_runs(world: World) -> None:
    w = world
    video = _video(w)
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    with pytest.raises(CatalogError) as caught:
        w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=[CutSpan(0, 5_000, True)])
    assert caught.value.args[0] == ALREADY_CUTTING_TEXT
    with pytest.raises(CatalogError) as removing:
        w.service.remove_business_media(tenant_id=w.tenant, media_id=video)
    assert removing.value.args[0] == CUTTING_TEXT
    assert _job(w, job.id).status == "queued" and _row(w, video) is not None


@pytest.mark.parametrize(
    ("spans", "message"),
    [
        ([CutSpan(0, 2_000, True), CutSpan(2_000, 20_000, False)], PART_TOO_SHORT_TEXT),
        ([CutSpan(0, 20_000, False)], NO_PART_KEPT_TEXT),
        ([CutSpan(0, 20_000, True)], NOTHING_CUT_TEXT),  # the whole video, unchanged
    ],
)
def test_a_refused_or_cancelled_cut_writes_nothing(
    world: World, spans: list[CutSpan], message: str
) -> None:
    w = world
    video = _video(w)
    before = set(w.r2.gallery(w.tenant))
    with pytest.raises(CatalogError) as caught:
        w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=spans)
    assert caught.value.args[0] == message
    # «Cancelar» never calls the service at all: either way there is no job and the
    # original is exactly as it was.
    assert _cut_jobs(w) == 0 and _live_ids(w) == [video] and w.r2.gallery(w.tenant) == before


def test_only_videos_are_cut(world: World) -> None:
    w = world
    photo = _upload(w, "a.jpg", _jpeg((1, 2, 3))).media
    with pytest.raises(CatalogError) as caught:
        w.service.start_cut(tenant_id=w.tenant, media_id=photo.id, spans=[CutSpan(0, 3_000, True)])
    assert caught.value.args[0] == ONLY_VIDEOS_TEXT


def test_another_business_cannot_cut_a_video_nor_run_its_cut(world: World) -> None:
    w = world
    video = _video(w)
    with pytest.raises(UnknownBusinessMedia):
        w.service.start_cut(tenant_id=w.other_tenant, media_id=video, spans=SPANS)
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    with pytest.raises(UnknownBusinessMedia):
        w.service.get_gallery_job(tenant_id=w.other_tenant, job_id=job.id)
    assert _pass(w, w.other_tenant) == []
    assert _job(w, job.id).status == "queued" and w.cutter.calls == []


def test_a_cut_that_would_overfill_the_gallery_is_refused(world: World) -> None:
    w = world
    video = _video(w)
    with tenant_session(w.tenant) as session:  # 58 more media: 59 in all
        for index in range(58):
            media_id = uuid4()
            session.add(
                BusinessMedia(
                    id=media_id,
                    tenant_id=w.tenant,
                    brand_id=w.brand,
                    media_type="image",
                    object_key=f"t/{w.tenant}/gallery/{media_id}/photo.jpg",
                    content_type="image/jpeg",
                    position=10 + index,
                    pipeline_version="gallery-ingest-v1",
                )
            )
    three = [CutSpan(0, 5_000, True), CutSpan(5_000, 10_000, True), CutSpan(10_000, 20_000, True)]
    with pytest.raises(CatalogError) as caught:
        w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=three)
    assert caught.value.args[0] == CUT_GALLERY_FULL_TEXT
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)  # 60: fits
    # The extra part already counts: the Galería is full for an upload meanwhile.
    with pytest.raises(CatalogError):
        w.service.check_can_upload(tenant_id=w.tenant, brand_id=w.brand, videos=0)
    assert job.status == "queued"


def test_a_part_can_be_cut_again_and_keeps_its_own_provenance(world: World) -> None:
    w = world
    video = _video(w)
    first = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    _pass(w)
    part_a, part_b = cut_part_media_id(first.id, 0), cut_part_media_id(first.id, 1)
    second = w.service.start_cut(
        tenant_id=w.tenant,
        media_id=part_b,
        spans=[CutSpan(0, 5_000, True), CutSpan(5_000, 11_000, True)],
    )
    _pass(w)
    new = [cut_part_media_id(second.id, 0), cut_part_media_id(second.id, 1)]
    assert _live_ids(w) == [part_a, *new]
    kept = _row(w, part_a)
    assert kept is not None and kept.job_id == first.id and kept.source_media_id == video
    for part_id in new:
        row = _row(w, part_id)
        assert row is not None and row.source_media_id == part_b and row.job_id == second.id
    assert w.cutter.sources[-1] == b"part 9000-20000"  # cut from the part's own file
    _assert_no_orphans(w)


# -- failures before the point of no return ------------------------------------------------


def test_three_transient_failures_fail_the_cut_and_leave_the_original(world: World) -> None:
    w = world
    video = _video(w)
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    w.cutter.fail_with = RuntimeError("ffmpeg timed out")
    statuses = []
    for _ in range(3):
        statuses += [o.status for o in _pass(w)]
        w.clock.advance(minutes=5)
    assert statuses == ["retry", "retry", "failed"]
    assert _job(w, job.id).status == "failed"
    assert _live_ids(w) == [video] and w.r2.folder(w.tenant, video)  # untouched, visible
    for index in range(2):
        assert not w.r2.folder(w.tenant, cut_part_media_id(job.id, index))
    _assert_no_orphans(w)
    # The «en corte» mark is lifted: the same video can be cut again (a new job).
    w.cutter.fail_with = None
    again = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    assert again.id != job.id and again.status == "queued"
    [outcome] = _pass(w)
    assert outcome.status == "done" and len(_live_ids(w)) == 2
    _assert_no_orphans(w)


def test_a_failed_cut_lifts_the_mark_so_quitar_works(world: World) -> None:
    w = world
    video = _video(w)
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    w.cutter.fail_with = UnreadableVideo("corrupt")
    [outcome] = _pass(w)
    assert outcome.status == "failed" and outcome.error_code == "unreadable"  # at once
    assert _job(w, job.id).status == "failed" and _live_ids(w) == [video]
    w.service.remove_business_media(tenant_id=w.tenant, media_id=video)
    assert _live_ids(w) == [] and not w.r2.gallery(w.tenant)


def test_r2_failing_on_the_second_part_retries_onto_the_same_keys(world: World) -> None:
    w = world
    video = _video(w)
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    w.r2.fail_put = str(cut_part_media_id(job.id, 1))
    [first] = _pass(w)
    assert first.status == "retry" and first.error_code.startswith("r2_write")
    assert _live_ids(w) == [video]  # nothing saved yet
    w.r2.fail_put = None
    w.clock.advance(minutes=5)
    [second] = _pass(w)
    assert second.status == "done"
    assert _live_ids(w) == [cut_part_media_id(job.id, 0), cut_part_media_id(job.id, 1)]
    _assert_no_orphans(w)


def test_a_worker_killed_after_writing_the_parts_is_resumed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Killed between step 2 (parts in R2) and step 3 (the transaction): the original
    stays visible, the reconciler leaves the parts' folders alone while the job is
    active (even a day later), and the reclaimed job ends with the same parts."""
    w = world
    video = _video(w)
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    real_save = w.runner._save_parts

    def die(*_: object, **__: object) -> None:
        raise Killed()

    monkeypatch.setattr(w.runner, "_save_parts", die)
    with pytest.raises(Killed):
        w.runner.run_tenant(w.tenant)
    parts = [cut_part_media_id(job.id, 0), cut_part_media_id(job.id, 1)]
    assert all(w.r2.folder(w.tenant, p) for p in parts)
    assert _job(w, job.id).status == "running" and _live_ids(w) == [video]
    assert w.runner.claim(w.tenant) is None  # its lease still holds

    w.clock.advance(hours=25)
    report = w.runner.reconcile_tenant(w.tenant)
    assert report.folders == 0 and all(w.r2.folder(w.tenant, p) for p in parts)

    monkeypatch.setattr(w.runner, "_save_parts", real_save)
    [outcome] = _pass(w)
    assert outcome.status == "done" and _live_ids(w) == parts
    assert _job(w, job.id).attempts == 2
    _assert_no_orphans(w)


# -- after the point of no return ----------------------------------------------------------


def test_r2_failing_after_the_parts_are_saved_is_finished_on_retry(world: World) -> None:
    w = world
    video = _video(w)
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    w.r2.fail_delete = True
    [first] = _pass(w)
    assert first.status == "retry" and first.error_code.startswith("r2_delete")
    parts = [cut_part_media_id(job.id, 0), cut_part_media_id(job.id, 1)]
    saved = _job(w, job.id)
    assert saved.status == "parts_saved"
    # The owner already sees the parts and no longer the original (its tombstone).
    assert _live_ids(w) == parts
    original = _row(w, video)
    assert original is not None and original.deleted_at is not None
    # Repeating the request meanwhile gives the same job.
    assert w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS).id == job.id

    w.r2.fail_delete = False
    assert _pass(w) == []  # backing off
    w.clock.advance(minutes=5)
    [second] = _pass(w)
    assert second.status == "done" and _job(w, job.id).status == "done"
    assert _row(w, video) is None and not w.r2.folder(w.tenant, video)
    assert _live_ids(w) == parts
    _assert_no_orphans(w)


def test_a_saved_cut_that_keeps_failing_is_never_undone(world: World) -> None:
    """Attempts exhausted after step 3: the job closes `done` (lifting the mark), the
    parts stay, and the reconciler's tombstone rule finishes the original."""
    w = world
    video = _video(w)
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)
    w.r2.fail_delete = True
    outcomes = []
    for _ in range(4):
        outcomes += [o.status for o in _pass(w)]
        w.clock.advance(minutes=10)
    closed = _job(w, job.id)
    assert closed.status == "done" and closed.result["original_left_to_reconciler"] is True
    assert outcomes[-1] == "done"
    parts = [cut_part_media_id(job.id, 0), cut_part_media_id(job.id, 1)]
    assert _live_ids(w) == parts and all(w.r2.folder(w.tenant, p) for p in parts)

    w.r2.fail_delete = False
    w.clock.advance(hours=2)
    report = w.runner.reconcile_tenant(w.tenant)
    assert report.tombstones == 1 and report.objects == 2
    assert _row(w, video) is None and not w.r2.folder(w.tenant, video)
    _assert_no_orphans(w)


def test_a_worker_killed_after_the_transaction_finishes_on_reclaim(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world
    video = _video(w)
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)

    def die(*_: object, **__: object) -> None:
        raise Killed()

    real_finish = w.runner._finish_cut
    monkeypatch.setattr(w.runner, "_finish_cut", die)
    with pytest.raises(Killed):
        w.runner.run_tenant(w.tenant)
    assert _job(w, job.id).status == "parts_saved"
    monkeypatch.setattr(w.runner, "_finish_cut", real_finish)
    assert _pass(w) == []  # its lease holds
    w.clock.advance(minutes=11)
    [outcome] = _pass(w)
    assert outcome.status == "done" and _row(w, video) is None
    assert w.cutter.calls == [(0, 4_000), (9_000, 20_000)]  # never encoded twice
    _assert_no_orphans(w)


def test_a_saved_cut_killed_on_its_last_attempt_still_tries_the_delete(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Killed right after step 3 on the third attempt: the reclaim still runs steps 4-5
    once (review) instead of leaving the original's folder to the daily reconciler."""
    w = world
    video = _video(w)
    job = w.service.start_cut(tenant_id=w.tenant, media_id=video, spans=SPANS)

    def die(*_: object, **__: object) -> None:
        raise Killed()

    real_finish = w.runner._finish_cut
    monkeypatch.setattr(w.runner, "_finish_cut", die)
    with pytest.raises(Killed):
        w.runner.run_tenant(w.tenant)
    with tenant_session(w.tenant) as session:  # as if that had been its third attempt
        session.get(GalleryJob, job.id).attempts = 3
    monkeypatch.setattr(w.runner, "_finish_cut", real_finish)
    w.clock.advance(minutes=11)
    [outcome] = _pass(w)
    closed = _job(w, job.id)
    assert outcome.status == "done" and "original_left_to_reconciler" not in closed.result
    assert _row(w, video) is None and not w.r2.folder(w.tenant, video)
    _assert_no_orphans(w)
