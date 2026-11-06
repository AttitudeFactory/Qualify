"""The Galería's business media door (m-24955918, CM-1 of epic m-24955913; ADR 47).

Photos and videos of the business that are not a product's. Rules this module upholds
(`docs/epica-galeria-medios-negocio.md` §2 and §4):

- **Files in R2** under `t/{tenant}/gallery/{media_id}/` through `ObjectGate.put_media`;
  the only thing written to the local volume is the staged upload (`business_media_staging`).
- **Photos** are normalized here, in the caller's process (seconds), exactly like product
  photos (JPEG for Instagram). **Videos never are:** a staged video becomes an `ingest`
  job that `media-worker` transcodes (H.264 + AAC, first 60 s — D1/D2).
- **Idempotency:** the same file twice at once, or a file already live, gives one medium
  (`ingest:{brand}:{sha256}` among active jobs + the live digest index); after «Quitar»
  it comes back as a new one. Cut parts carry no upload digest, so they never match.
- **«Quitar»** = tombstone → `delete_gallery_media` → delete the row; refused while the
  video has an active `cut` job (the «en corte» mark lives in `gallery_jobs`). If R2 fails
  the tombstone stays and the reconciler finishes.
- **Limits:** 60 media per business (live rows + pending ingest jobs + the extra parts
  of cuts in flight) and at most 3 videos waiting, checked before an upload is accepted.
- **Cut** (m-24955923, CM-3): `start_cut` validates the owner's spans, creates ONE `cut`
  job (`cut:{source}:{sha256 of the kept spans}:{version}`) and returns at once;
  `media-worker` encodes only the kept spans. Repeating the same request gives the same
  job (also after it finished); another cut of the same video while one runs is refused.

Everything tenant-scoped goes through `tenant_session`. Product reads are untouched:
`product_media` and its readers never see this table.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from collections.abc import AsyncIterable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from qualify_creative.photo.normalize import export_for_instagram, load_normalized
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.keys import gallery_media_prefix
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from qualify_api.catalog.business_media_models import (
    ACTIVE_STATUSES,
    CUT_PIPELINE_VERSION,
    INGEST_PIPELINE_VERSION,
    JOB_CUT,
    JOB_INGEST,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PARTS_SAVED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    BusinessMedia,
    GalleryJob,
)
from qualify_api.catalog.business_media_staging import (
    OUTCOME_EMPTY,
    OUTCOME_FULL,
    OUTCOME_NO_SLOT,
    OUTCOME_STAGED,
    OUTCOME_TOO_LARGE,
    ChunkLike,
    StagedFile,
    discard_staged,
    resolve_staged,
    stage_chunks,
)
from qualify_api.catalog.models import MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO
from qualify_api.catalog.service import PHOTO_UNREADABLE_TEXT, CatalogError, UnknownBrand
from qualify_api.tenancy.models import Brand

logger = logging.getLogger(__name__)

MAX_BUSINESS_MEDIA = 60  # [H] epic §5 CM-1
MAX_WAITING_VIDEOS = 3
#: A staged PHOTO is read whole to normalize it (in the caller's process): bounded.
MAX_PHOTO_BYTES = 50_000_000
PHOTO_KEY = "photo.jpg"
VIDEO_KEY = "video.mp4"
POSTER_KEY = "poster.jpg"
#: How long a finished ingest job stays readable, so the screen can say «guardamos solo
#: el primer minuto» after a reload.
RECENT_JOB_WINDOW = timedelta(days=1)

#: What the owner reads (qualify-copy-es; CM-2 shows `CatalogError.args[0]` as is).
GALLERY_FULL_TEXT = (
    f"Tu Galería guarda hasta {MAX_BUSINESS_MEDIA} fotos y videos de tu negocio. "
    "Quita alguno o sube menos a la vez."
)
VIDEOS_WAITING_TEXT = (
    f"Ya estamos preparando {MAX_WAITING_VIDEOS} videos. Cuando termine uno, "
    "podrás subir el siguiente."
)
VIDEO_TOO_HEAVY_TEXT = "Ese video es muy pesado. Prueba con uno más corto."
PHOTO_TOO_HEAVY_TEXT = "Esa foto es muy pesada. Prueba con otra."
EMPTY_FILE_TEXT = "No nos llegó nada de ese archivo. Vuelve a elegirlo o prueba con otro."
CUTTING_TEXT = "Estamos cortando este video. Podrás quitarlo cuando termine."

#: The cut (CM-3). The first two are CM-4's exact texts.
MIN_PART_MS = 3_000  # [H] epic §5 CM-3: what Instagram accepts in a video
PART_TOO_SHORT_TEXT = "Cada parte debe durar al menos 3 segundos."
NO_PART_KEPT_TEXT = "Deja al menos una parte o cancela."
CUT_INVALID_TEXT = (
    "No pudimos leer los cortes de tu video. Vuelve a marcarlos e inténtalo otra vez."
)
ONLY_VIDEOS_TEXT = "Solo se pueden cortar videos."
NOTHING_CUT_TEXT = "No marcaste ningún corte. Corta el video o cancela."
ALREADY_CUTTING_TEXT = (
    "Ya estamos cortando este video. Espera a que termine para volver a cortarlo."
)
CUT_GALLERY_FULL_TEXT = (
    f"Con estas partes tu Galería pasaría de {MAX_BUSINESS_MEDIA} fotos y videos. "
    "Quita alguno antes de cortar."
)
#: For the screen when a cut job ends `failed` (the original is untouched).
CUT_FAILED_TEXT = "No pudimos cortar tu video. Quedó como estaba; inténtalo otra vez."


class UnknownBusinessMedia(KeyError):
    """A medium (or job) this tenant's door does not see."""


@dataclass(frozen=True)
class CutSpan:
    """One span of the owner's timeline (CM-4): `[start_ms, end_ms)` of the video, and
    whether it stays (`keep`) or is removed. Removed spans are never encoded."""

    start_ms: int
    end_ms: int
    keep: bool


def validate_cut_spans(
    spans: Sequence[CutSpan], duration_ms: int | None
) -> tuple[tuple[int, int], ...]:
    """The kept spans `(start_ms, end_ms)` in order, or `CatalogError` with the text the
    owner reads: spans inside `[0, duration_ms]` (no upper bound when None), ordered and
    not overlapping, at least one kept, every kept one at least 3 s."""
    if not spans:
        raise CatalogError(NO_PART_KEPT_TEXT)
    previous_end = 0
    for span in spans:
        ints = all(
            isinstance(v, int) and not isinstance(v, bool) for v in (span.start_ms, span.end_ms)
        )
        if not ints or not isinstance(span.keep, bool):
            raise CatalogError(CUT_INVALID_TEXT)
        if span.start_ms < previous_end or span.end_ms <= span.start_ms:
            raise CatalogError(CUT_INVALID_TEXT)
        if duration_ms is not None and span.end_ms > duration_ms:
            raise CatalogError(CUT_INVALID_TEXT)
        previous_end = span.end_ms
    kept = tuple((s.start_ms, s.end_ms) for s in spans if s.keep)
    if not kept:
        raise CatalogError(NO_PART_KEPT_TEXT)
    if any(end - start < MIN_PART_MS for start, end in kept):
        raise CatalogError(PART_TOO_SHORT_TEXT)
    return kept


def cut_idempotency_key(source_media_id: UUID, kept: Sequence[tuple[int, int]]) -> str:
    """`cut:{source}:{sha256 of the kept spans, ordered}:{pipeline version}` (§4.3)."""
    canonical = json.dumps(sorted([int(a), int(b)] for a, b in kept), separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"{JOB_CUT}:{source_media_id}:{digest}:{CUT_PIPELINE_VERSION}"


@dataclass(frozen=True)
class BusinessMediaRecord:
    id: UUID
    brand_id: UUID
    media_type: str
    object_key: str
    poster_key: str | None
    content_type: str
    width: int | None
    height: int | None
    duration_ms: int | None
    bytes: int | None
    has_audio: bool
    position: int
    filename: str
    source_media_id: UUID | None
    cut_start_ms: int | None
    cut_end_ms: int | None
    created_at: datetime

    @property
    def thumbnail_key(self) -> str:
        return self.poster_key or self.object_key

    @property
    def duration_label(self) -> str:
        """«0:42» for a video, "" for a photo."""
        if self.duration_ms is None:
            return ""
        seconds = int(round(self.duration_ms / 1000))
        return f"{seconds // 60}:{seconds % 60:02d}"


@dataclass(frozen=True)
class GalleryJobRecord:
    id: UUID
    brand_id: UUID
    kind: str
    status: str
    filename: str
    attempts: int
    last_error_code: str | None
    source_media_id: UUID | None
    media_id: UUID | None
    #: The source video was longer than 60 s and only the first minute was kept (D2).
    trimmed: bool
    created_at: datetime
    #: A `cut` job's parts, in order, once saved (`parts_saved` / `done`).
    part_ids: tuple[UUID, ...] = ()

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATUSES


@dataclass(frozen=True)
class AddOutcome:
    """What one file of an upload became. Exactly one of `media` / `job` / `error_text`
    is meaningful: a photo saved (or already there), a video queued (or already being
    prepared, or already live as `media`), or a refusal the screen shows as is."""

    filename: str
    media: BusinessMediaRecord | None = None
    job: GalleryJobRecord | None = None
    duplicate: bool = False
    error_text: str = ""


def _now() -> datetime:
    return datetime.now(UTC)


class BusinessMediaService:
    def __init__(
        self,
        *,
        gate: ObjectGate,
        staging_root: Path,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._gate = gate
        self._root = staging_root
        self._clock = clock

    # -- read --------------------------------------------------------------------------

    def list_business_media(
        self, *, tenant_id: UUID, brand_id: UUID
    ) -> tuple[BusinessMediaRecord, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(BusinessMedia)
                .where(BusinessMedia.brand_id == brand_id, BusinessMedia.deleted_at.is_(None))
                .order_by(BusinessMedia.position, BusinessMedia.created_at, BusinessMedia.id)
            )
            return tuple(_media_record(m) for m in rows)

    def get_business_media(self, *, tenant_id: UUID, media_id: UUID) -> BusinessMediaRecord:
        with tenant_session(tenant_id) as session:
            row = session.get(BusinessMedia, media_id)
            if row is None or row.deleted_at is not None:
                raise UnknownBusinessMedia(str(media_id))
            return _media_record(row)

    def list_gallery_jobs(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[GalleryJobRecord, ...]:
        """The jobs the screen shows: every active job (ingest «Preparando…», cut
        «Cortando…»), failed ingest jobs until the owner dismisses them, and ingest jobs
        finished in the last day (for the «más de un minuto» notice)."""
        since = self._clock() - RECENT_JOB_WINDOW
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(GalleryJob)
                .where(
                    GalleryJob.brand_id == brand_id,
                    or_(
                        GalleryJob.status.in_(ACTIVE_STATUSES),
                        (GalleryJob.kind == JOB_INGEST) & (GalleryJob.status == STATUS_FAILED),
                        (GalleryJob.kind == JOB_INGEST)
                        & (GalleryJob.status == STATUS_DONE)
                        & (GalleryJob.finished_at >= since),
                    ),
                )
                .order_by(GalleryJob.created_at, GalleryJob.id)
            )
            return tuple(_job_record(j) for j in rows)

    def get_gallery_job(self, *, tenant_id: UUID, job_id: UUID) -> GalleryJobRecord:
        """One job's status (CM-4 polls its cut with this). `UnknownBusinessMedia` for a
        job this tenant does not see."""
        with tenant_session(tenant_id) as session:
            job = session.get(GalleryJob, job_id)
            if job is None:
                raise UnknownBusinessMedia(f"job {job_id}")
            return _job_record(job)

    def list_cut_jobs(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[GalleryJobRecord, ...]:
        """The cuts the screen shows: active ones («Cortando tu video…») and those that
        ended in the last day («Listo: tu video quedó en N partes.», or the failure)."""
        since = self._clock() - RECENT_JOB_WINDOW
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(GalleryJob)
                .where(
                    GalleryJob.brand_id == brand_id,
                    GalleryJob.kind == JOB_CUT,
                    or_(GalleryJob.status.in_(ACTIVE_STATUSES), GalleryJob.finished_at >= since),
                )
                .order_by(GalleryJob.created_at, GalleryJob.id)
            )
            return tuple(_job_record(j) for j in rows)

    def dismiss_gallery_job(self, *, tenant_id: UUID, job_id: UUID) -> None:
        """«Quitar» on a failed video (or acknowledging a finished one): deletes a
        TERMINAL ingest job row. An active job is refused; an unknown one is a no-op."""
        with tenant_session(tenant_id) as session:
            job = session.get(GalleryJob, job_id, with_for_update=True)
            if job is None:
                return
            if job.kind != JOB_INGEST or job.status in ACTIVE_STATUSES:
                raise UnknownBusinessMedia(f"job {job_id} is not a finished upload")
            session.delete(job)

    # -- limits ------------------------------------------------------------------------

    def free_places(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[int, int]:
        """(videos that may still wait, 0..3; media the Galería still holds, 0..60)."""
        with tenant_session(tenant_id) as session:
            _require_brand(session, brand_id)
            live, waiting = _counts(session, brand_id)
        return (
            max(0, MAX_WAITING_VIDEOS - waiting),
            max(0, MAX_BUSINESS_MEDIA - live - waiting),
        )

    def check_can_upload(self, *, tenant_id: UUID, brand_id: UUID, videos: int = 1) -> None:
        """Called BEFORE an upload starts (CM-2): raises `CatalogError` with the text the
        owner reads when the Galería is full or 3 videos are already waiting."""
        with tenant_session(tenant_id) as session:
            _require_brand(session, brand_id)
            live, waiting = _counts(session, brand_id)
        if live + waiting + max(videos, 1) > MAX_BUSINESS_MEDIA:
            raise CatalogError(GALLERY_FULL_TEXT)
        if videos and waiting + videos > MAX_WAITING_VIDEOS:
            raise CatalogError(VIDEOS_WAITING_TEXT)

    # -- write -------------------------------------------------------------------------

    async def add_business_media(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        chunks: AsyncIterable[ChunkLike],
    ) -> list[AddOutcome]:
        """The whole upload path for CM-2's background handler: stage every file of a
        chunked upload (`UploadChunkIterator`), then save each photo and queue each video.
        One outcome per file; a refused file never stops the others."""
        videos, places = self.free_places(tenant_id=tenant_id, brand_id=brand_id)
        staged = await stage_chunks(
            chunks, root=self._root, tenant_id=tenant_id, max_videos=videos, max_files=places
        )
        return [self.add_staged(tenant_id=tenant_id, brand_id=brand_id, staged=s) for s in staged]

    def add_staged(self, *, tenant_id: UUID, brand_id: UUID, staged: StagedFile) -> AddOutcome:
        """Save one staged file: a photo now (R2 + row), a video as an `ingest` job."""
        name = staged.filename
        if staged.outcome == OUTCOME_TOO_LARGE:
            return AddOutcome(
                name, error_text=VIDEO_TOO_HEAVY_TEXT if staged.is_video else PHOTO_TOO_HEAVY_TEXT
            )
        if staged.outcome == OUTCOME_NO_SLOT:
            return AddOutcome(name, error_text=VIDEOS_WAITING_TEXT)
        if staged.outcome == OUTCOME_FULL:
            return AddOutcome(name, error_text=GALLERY_FULL_TEXT)
        if staged.outcome == OUTCOME_EMPTY or staged.outcome != OUTCOME_STAGED:
            return AddOutcome(name, error_text=EMPTY_FILE_TEXT)
        if staged.is_video:
            try:
                return self.enqueue_video(tenant_id=tenant_id, brand_id=brand_id, staged=staged)
            except CatalogError as exc:
                return AddOutcome(name, error_text=str(exc.args[0]))
        try:
            path = resolve_staged(self._root, tenant_id, staged.relpath)
            if staged.bytes > MAX_PHOTO_BYTES:
                return AddOutcome(name, error_text=PHOTO_TOO_HEAVY_TEXT)
            data = path.read_bytes()
        finally:
            discard_staged(self._root, tenant_id, staged.relpath)
        try:
            media, duplicate = self._add_photo(
                tenant_id=tenant_id, brand_id=brand_id, data=data, filename=name
            )
        except CatalogError as exc:
            return AddOutcome(name, error_text=str(exc.args[0]))
        return AddOutcome(name, media=media, duplicate=duplicate)

    def add_business_photo(
        self, *, tenant_id: UUID, brand_id: UUID, data: bytes, filename: str
    ) -> BusinessMediaRecord:
        """A photo already in memory (the short path, like product photos). Raises
        `CatalogError` for an unreadable photo or a full Galería."""
        return self._add_photo(
            tenant_id=tenant_id, brand_id=brand_id, data=data, filename=filename
        )[0]

    def _add_photo(
        self, *, tenant_id: UUID, brand_id: UUID, data: bytes, filename: str
    ) -> tuple[BusinessMediaRecord, bool]:
        digest = hashlib.sha256(data).hexdigest()
        with tenant_session(tenant_id) as session:
            _require_brand(session, brand_id)
            existing = _live_by_digest(session, brand_id, digest)
            if existing is not None:
                return _media_record(existing), True
            live, waiting = _counts(session, brand_id)
            if live + waiting >= MAX_BUSINESS_MEDIA:
                raise CatalogError(GALLERY_FULL_TEXT)
        try:
            image = load_normalized(data)
            payload = export_for_instagram(image)
            from PIL import Image  # noqa: PLC0415

            with Image.open(io.BytesIO(payload)) as exported:
                width, height = exported.size
        except Exception as exc:
            logger.warning("gallery photo normalize failed: %s", type(exc).__name__)
            raise CatalogError(PHOTO_UNREADABLE_TEXT) from exc

        media_id = uuid4()
        key = gallery_media_prefix(tenant_id, media_id) + PHOTO_KEY
        self._gate.put_media(tenant_id, key, io.BytesIO(payload), "image/jpeg")
        try:
            with tenant_session(tenant_id) as session:
                _lock_gallery(session, brand_id)
                existing = _live_by_digest(session, brand_id, digest)
                if existing is not None:
                    record, duplicate = _media_record(existing), True
                else:
                    live, waiting = _counts(session, brand_id)
                    if live + waiting >= MAX_BUSINESS_MEDIA:
                        raise CatalogError(GALLERY_FULL_TEXT)
                    row = BusinessMedia(
                        id=media_id,
                        tenant_id=tenant_id,
                        brand_id=brand_id,
                        media_type=MEDIA_TYPE_IMAGE,
                        object_key=key,
                        poster_key=None,
                        content_type="image/jpeg",
                        width=width,
                        height=height,
                        duration_ms=None,
                        bytes=len(payload),
                        has_audio=False,
                        position=_next_position(session, brand_id),
                        filename=filename[:200],
                        upload_sha256=digest,
                        pipeline_version=INGEST_PIPELINE_VERSION,
                    )
                    session.add(row)
                    session.flush()
                    record, duplicate = _media_record(row), False
        except BaseException:
            self._forget_folder(tenant_id, media_id)
            raise
        if duplicate:
            self._forget_folder(tenant_id, media_id)
        return record, duplicate

    def enqueue_video(self, *, tenant_id: UUID, brand_id: UUID, staged: StagedFile) -> AddOutcome:
        """Queue the `ingest` job of a staged video, idempotently: an active job with the
        same key or a live medium with the same digest is returned instead (and the new
        staged copy deleted). Refusals delete the staged file too."""
        key = f"{JOB_INGEST}:{brand_id}:{staged.sha256}"
        keep_file = False
        try:
            with tenant_session(tenant_id) as session:
                _require_brand(session, brand_id)
                _lock_gallery(session, brand_id)
                existing = _live_by_digest(session, brand_id, staged.sha256)
                if existing is not None:
                    return AddOutcome(
                        staged.filename, media=_media_record(existing), duplicate=True
                    )
                job = _active_job(session, brand_id, key)
                if job is not None:
                    return AddOutcome(staged.filename, job=_job_record(job), duplicate=True)
                live, waiting = _counts(session, brand_id)
                if live + waiting >= MAX_BUSINESS_MEDIA:
                    raise CatalogError(GALLERY_FULL_TEXT)
                if waiting >= MAX_WAITING_VIDEOS:
                    raise CatalogError(VIDEOS_WAITING_TEXT)
                job_id = session.scalar(
                    insert(GalleryJob)
                    .values(
                        tenant_id=tenant_id,
                        brand_id=brand_id,
                        kind=JOB_INGEST,
                        idempotency_key=key,
                        staged_path=staged.relpath,
                        filename=staged.filename[:200],
                        upload_sha256=staged.sha256,
                        bytes=staged.bytes,
                        pipeline_version=INGEST_PIPELINE_VERSION,
                    )
                    .on_conflict_do_nothing()
                    .returning(GalleryJob.id)
                )
                if job_id is None:  # raced past the lock (cannot, but never duplicate)
                    job = _active_job(session, brand_id, key)
                    if job is None:
                        raise RuntimeError("gallery ingest job conflict without an active job")
                    return AddOutcome(staged.filename, job=_job_record(job), duplicate=True)
                keep_file = True
                created = session.get(GalleryJob, job_id)
                assert created is not None
                return AddOutcome(staged.filename, job=_job_record(created))
        finally:
            if not keep_file:
                discard_staged(self._root, tenant_id, staged.relpath)

    def start_cut(
        self, *, tenant_id: UUID, media_id: UUID, spans: Sequence[CutSpan]
    ) -> GalleryJobRecord:
        """«Guardar partes» (CM-4): validate the spans and queue ONE `cut` job, at once —
        `media-worker` does the work, never this call. Until here nothing is written, so
        «Cancelar» needs no undo. Idempotent: the same spans give the same job, also
        when retried after the cut finished (the original is gone by then). Refused with
        `ALREADY_CUTTING_TEXT` while another cut of the video runs, and with
        `CUT_GALLERY_FULL_TEXT` if the parts would pass the Galería's limit.
        `UnknownBusinessMedia` for a medium this tenant does not see."""
        with tenant_session(tenant_id) as session:
            row = session.get(BusinessMedia, media_id)
            if row is not None and row.deleted_at is None:
                # Gallery lock first, then the row FOR UPDATE — the worker's order (it
                # shifts positions under the same lock). The row lock serializes with
                # «Quitar», which locks the row before checking for an active cut: a video
                # is either removed or being cut, never both.
                _lock_gallery(session, row.brand_id)
                session.refresh(row, with_for_update=True)
            if row is None or row.deleted_at is not None:
                kept = validate_cut_spans(spans, None)
                finished = _cut_job_by_key(session, cut_idempotency_key(media_id, kept))
                if finished is None:
                    raise UnknownBusinessMedia(str(media_id))
                return _job_record(finished)
            if row.media_type != MEDIA_TYPE_VIDEO:
                raise CatalogError(ONLY_VIDEOS_TEXT)
            kept = validate_cut_spans(spans, row.duration_ms)
            if kept == ((0, row.duration_ms),):  # nothing cut: re-encoding would only lose
                raise CatalogError(NOTHING_CUT_TEXT)
            key = cut_idempotency_key(media_id, kept)
            brand_id = row.brand_id
            same = _active_job(session, brand_id, key)
            if same is not None:
                return _job_record(same)
            if _active_cut_of(session, media_id) is not None:
                raise CatalogError(ALREADY_CUTTING_TEXT)
            live, waiting = _counts(session, brand_id)
            if live + waiting - 1 + len(kept) > MAX_BUSINESS_MEDIA:
                raise CatalogError(CUT_GALLERY_FULL_TEXT)
            job_id = session.scalar(
                insert(GalleryJob)
                .values(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    kind=JOB_CUT,
                    idempotency_key=key,
                    filename=row.filename,
                    source_media_id=media_id,
                    segments=[{"start_ms": a, "end_ms": b} for a, b in kept],
                    result={"source_duration_ms": row.duration_ms},
                    pipeline_version=CUT_PIPELINE_VERSION,
                )
                .on_conflict_do_nothing()
                .returning(GalleryJob.id)
            )
            if job_id is None:  # raced past the lock (cannot): never a second cut
                same = _active_job(session, brand_id, key)
                if same is None:
                    raise CatalogError(ALREADY_CUTTING_TEXT)
                return _job_record(same)
            created = session.get(GalleryJob, job_id)
            assert created is not None
            return _job_record(created)

    def remove_business_media(self, *, tenant_id: UUID, media_id: UUID) -> None:
        """«Quitar»: tombstone → delete the R2 folder → delete the row (ADR 39 amendment,
        rule 4). Refused with `CUTTING_TEXT` while the video has an active cut job.
        Idempotent: an unknown or already removed medium is a no-op; a tombstoned one is
        finished. If R2 fails the tombstone stays (the medium is gone for the owner) and
        the daily reconciler deletes folder and row."""
        with tenant_session(tenant_id) as session:
            row = session.get(BusinessMedia, media_id, with_for_update=True)
            if row is None:
                return
            if row.deleted_at is None:
                cutting = session.scalar(
                    select(func.count())
                    .select_from(GalleryJob)
                    .where(
                        GalleryJob.kind == JOB_CUT,
                        GalleryJob.source_media_id == media_id,
                        GalleryJob.status.in_(ACTIVE_STATUSES),
                    )
                )
                if cutting:
                    raise CatalogError(CUTTING_TEXT)
                row.deleted_at = self._clock()
        try:
            self._gate.delete_gallery_media(tenant_id, media_id)
        except Exception as exc:  # noqa: BLE001 — the tombstone stays; the reconciler ends it
            logger.warning(
                "gallery.remove.r2_failed tenant=%s media=%s error=%s",
                tenant_id,
                media_id,
                type(exc).__name__,
            )
            return
        with tenant_session(tenant_id) as session:
            session.execute(
                delete(BusinessMedia).where(
                    BusinessMedia.id == media_id, BusinessMedia.deleted_at.is_not(None)
                )
            )

    def _forget_folder(self, tenant_id: UUID, media_id: UUID) -> None:
        try:
            self._gate.delete_gallery_media(tenant_id, media_id)
        except Exception as exc:  # noqa: BLE001 — the reconciler deletes it after 24 h
            logger.warning("gallery.forget_folder_failed error=%s", type(exc).__name__)


def production_business_media_service() -> BusinessMediaService:
    """The real wiring CM-2's screen uses: R2 through `ObjectGate`, the staging room on
    the app's upload volume (`media_root()`, shared with `media-worker`)."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    from qualify_api.creative.composition import media_root  # noqa: PLC0415

    return BusinessMediaService(
        gate=ObjectGate(R2ObjectStore(R2Settings.from_env())), staging_root=media_root()
    )


# -- helpers shared with media_worker ------------------------------------------------------


def _require_brand(session: Any, brand_id: UUID) -> None:
    if session.get(Brand, brand_id) is None:
        raise UnknownBrand(str(brand_id))


def _lock_gallery(session: Any, brand_id: UUID) -> None:
    """Serialize a brand's Galería writes for the transaction (advisory lock: no UPDATE
    grant on `brands` needed), so counts, digests and positions stay consistent."""
    session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"gallery:{brand_id}", 0)))
    )


def _counts(session: Any, brand_id: UUID) -> tuple[int, int]:
    """(media the Galería holds or is about to, active ingest jobs) of a brand. A cut not
    yet saved turns one live video into N parts: its N - 1 extra parts count already."""
    live = session.scalar(
        select(func.count())
        .select_from(BusinessMedia)
        .where(BusinessMedia.brand_id == brand_id, BusinessMedia.deleted_at.is_(None))
    )
    pending_cuts = session.scalars(
        select(GalleryJob.segments).where(
            GalleryJob.brand_id == brand_id,
            GalleryJob.kind == JOB_CUT,
            GalleryJob.status.in_((STATUS_QUEUED, STATUS_RUNNING)),
        )
    )
    extra = sum(max(len(segments or []) - 1, 0) for segments in pending_cuts)
    waiting = session.scalar(
        select(func.count())
        .select_from(GalleryJob)
        .where(
            GalleryJob.brand_id == brand_id,
            GalleryJob.kind == JOB_INGEST,
            GalleryJob.status.in_(ACTIVE_STATUSES),
        )
    )
    return int(live or 0) + extra, int(waiting or 0)


def _live_by_digest(session: Any, brand_id: UUID, digest: str) -> BusinessMedia | None:
    return session.scalar(
        select(BusinessMedia).where(
            BusinessMedia.brand_id == brand_id,
            BusinessMedia.upload_sha256 == digest,
            BusinessMedia.deleted_at.is_(None),
        )
    )


def _active_job(session: Any, brand_id: UUID, key: str) -> GalleryJob | None:
    return session.scalar(
        select(GalleryJob).where(
            GalleryJob.brand_id == brand_id,
            GalleryJob.idempotency_key == key,
            GalleryJob.status.in_(ACTIVE_STATUSES),
        )
    )


def _active_cut_of(session: Any, source_media_id: UUID) -> GalleryJob | None:
    """The «en corte» mark: an active `cut` job of this video (never
    `business_media.job_id`, which is a part's provenance)."""
    return session.scalar(
        select(GalleryJob).where(
            GalleryJob.kind == JOB_CUT,
            GalleryJob.source_media_id == source_media_id,
            GalleryJob.status.in_(ACTIVE_STATUSES),
        )
    )


def _cut_job_by_key(session: Any, key: str) -> GalleryJob | None:
    """The cut that already consumed this exact request (saved or done), newest first."""
    return session.scalar(
        select(GalleryJob)
        .where(
            GalleryJob.kind == JOB_CUT,
            GalleryJob.idempotency_key == key,
            GalleryJob.status.in_((STATUS_PARTS_SAVED, STATUS_DONE)),
        )
        .order_by(GalleryJob.created_at.desc(), GalleryJob.id)
        .limit(1)
    )


def _next_position(session: Any, brand_id: UUID) -> int:
    top = session.scalar(
        select(func.max(BusinessMedia.position)).where(
            BusinessMedia.brand_id == brand_id, BusinessMedia.deleted_at.is_(None)
        )
    )
    return 0 if top is None else int(top) + 1


def _media_record(m: BusinessMedia) -> BusinessMediaRecord:
    return BusinessMediaRecord(
        id=m.id,
        brand_id=m.brand_id,
        media_type=m.media_type,
        object_key=m.object_key,
        poster_key=m.poster_key,
        content_type=m.content_type,
        width=m.width,
        height=m.height,
        duration_ms=m.duration_ms,
        bytes=m.bytes,
        has_audio=m.has_audio,
        position=m.position,
        filename=m.filename,
        source_media_id=m.source_media_id,
        cut_start_ms=m.cut_start_ms,
        cut_end_ms=m.cut_end_ms,
        created_at=m.created_at,
    )


def _job_record(j: GalleryJob) -> GalleryJobRecord:
    result = j.result or {}
    raw_media = result.get("media_id")
    return GalleryJobRecord(
        id=j.id,
        brand_id=j.brand_id,
        kind=j.kind,
        status=j.status,
        filename=j.filename,
        attempts=j.attempts,
        last_error_code=j.last_error_code,
        source_media_id=j.source_media_id,
        media_id=UUID(raw_media) if raw_media else None,
        trimmed=bool(result.get("trimmed")),
        created_at=j.created_at,
        part_ids=tuple(UUID(p) for p in result.get("part_ids") or ()),
    )


__all__ = [
    "MAX_BUSINESS_MEDIA",
    "MAX_WAITING_VIDEOS",
    "MEDIA_TYPE_IMAGE",
    "MEDIA_TYPE_VIDEO",
    "MIN_PART_MS",
    "AddOutcome",
    "BusinessMediaRecord",
    "BusinessMediaService",
    "CutSpan",
    "GalleryJobRecord",
    "UnknownBusinessMedia",
    "cut_idempotency_key",
    "production_business_media_service",
    "validate_cut_spans",
]
