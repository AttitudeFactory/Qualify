"""`media-worker` — the Galería's job runner and daily reconciler (m-24955918, ADR 47 §4.3,
ADR 39 amendment; founder approved the service 2026-11-05, D8).

    python -m qualify_api.catalog.media_worker --tenant <uuid> [--tenant <uuid> ...] [--once]
    python -m qualify_api.catalog.media_worker --all-tenants [--once] [--interval 5]
    python -m qualify_api.catalog.media_worker --tenant <uuid> --reconcile

Scope is MANDATORY and explicit, like every `*-worker`: `--tenant` locally (the dev
database holds test tenants), `--all-tenants` only in production. Discovery reads tenant
ids only, through `admin_session`; everything else runs under `tenant_session`.

**Jobs** (`gallery_jobs`): one at a time in the whole process (the container runs one
process: 1 CPU, 768 MB). A job is claimed with `FOR UPDATE SKIP LOCKED` and a 10 min
lease; a job whose worker died (a deploy restarts the container) is reclaimed once its
lease expires; after 3 attempts it fails for good. `ingest` (this story):

1. the staged upload (`uploads/{tenant}/gallery-staging/{id}`) → `FfmpegBusinessVideoNormalizer`
   (H.264 + AAC 128 kbps, ≤ 1080×1920, first 60 s, poster) in a temp dir;
2. `video.mp4` + `poster.jpg` → R2 at `t/{tenant}/gallery/{uuid5(job, "ingest")}/` (a retry
   overwrites the same keys);
3. one transaction: the `business_media` row (`ON CONFLICT DO NOTHING`; if the same file
   went live meanwhile, the job points at that one) + the job `done`, with `trimmed` in
   its result when the source was longer than a minute;
4. the staged file is deleted (a crash before that leaves it to the reconciler).

A failure keeps nothing half-done: a permanent one (unreadable video, missing staged
file) or the third transient one marks the job `failed`, deletes the staged file and the
job's R2 folder.

`cut` (m-24955923, CM-3; ADR 39 amendment rule 4 — write → confirm in the DB → delete):

1. (the service) `start_cut` created the job: the original is «en corte» while the job
   is active (`queued`/`running`/`parts_saved`), so «Quitar» and another cut are refused;
2. the original `video.mp4` is read from R2 into a temp dir and ONLY the kept spans are
   encoded (`FfmpegBusinessVideoCutter`, accurate to ≤ 0.1 s, sound kept); each part goes
   to `t/{tenant}/gallery/{uuid5(job, i)}/` (a retry overwrites the same keys);
3. **one transaction** — the point of no return: the parts' rows (provenance
   `source_media_id` + `cut_start_ms`/`cut_end_ms` + `job_id` + `gallery-cut-v1`,
   `upload_sha256 = NULL`) in the original's place, the original's tombstone, the job
   `parts_saved` with the part ids;
4. `delete_gallery_media(original)`;
5. one transaction: the original's row deleted, the job `done`.

A failure before 3 leaves the original untouched and visible; a final one deletes the
`uuid5(job, i)` folders (enumerated, never listed) and marks the job `failed`, which lifts
the «en corte» mark. A failure between 3 and 5 is retried (both steps are idempotent);
when the attempts run out the job is closed `done` with `original_left_to_reconciler`,
and the reconciler's tombstone rule (b) finishes it — a saved cut is never undone.

**Reconciler** (at start, then every 24 h — rule 5 of the ADR 39 amendment), per tenant:
(a) R2 folders under `t/{tenant}/gallery/` with no row (live or tombstoned) and no active
job expecting them, older than 24 h → deleted (an upload cut between the PUT and the row);
(b) tombstones older than 1 h → folder deleted, then the row; (c) staged files older than
24 h no active job points at → deleted (an upload abandoned half-way). It logs how many
folders, objects and bytes it removed. It runs over EVERY tenant id (not only those with
Galería rows), so a folder whose first row never got written is still found.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import socket
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

from qualify_creative.video.business import BusinessVideoNormalizer, UnreadableVideo
from qualify_creative.video.business_cut import BusinessVideoCutter, CutBusinessPart
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectNotFound
from qualify_shared.objects.keys import gallery_media_prefix
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from qualify_api.catalog.business_media import (
    POSTER_KEY,
    VIDEO_KEY,
    _live_by_digest,
    _lock_gallery,
    _next_position,
)
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
    discard_staged,
    resolve_staged,
    staging_dir,
    staging_relpath,
)
from qualify_api.catalog.models import MEDIA_TYPE_VIDEO

logger = logging.getLogger("qualify_api.catalog.media_worker")

LEASE = timedelta(minutes=10)
MAX_ATTEMPTS = 3
#: A transient failure waits `RETRY_BACKOFF × attempts` before the next claim.
RETRY_BACKOFF = timedelta(minutes=1)
DEFAULT_INTERVAL_SECONDS = 5
MIN_INTERVAL_SECONDS = 1
DEFAULT_JOBS_PER_TENANT = 5
RECONCILE_EVERY_SECONDS = 24 * 60 * 60
ORPHAN_AGE = timedelta(hours=24)
TOMBSTONE_AGE = timedelta(hours=1)
STAGING_AGE = timedelta(hours=24)


def ingest_media_id(job_id: UUID) -> UUID:
    """The deterministic id of the medium an `ingest` job produces (its R2 folder)."""
    return uuid5(job_id, "ingest")


def cut_part_media_id(job_id: UUID, index: int) -> UUID:
    """The deterministic id of part `index` of a `cut` job (ADR 39 amendment, rule 1;
    CM-3 writes them, the reconciler and a failed cut enumerate them)."""
    return uuid5(job_id, str(index))


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


class GalleryObjects(Protocol):
    """The `ObjectGate` methods this worker uses."""

    def put_media(
        self, tenant_id: UUID, object_key: str, fileobj: Any, content_type: str
    ) -> None: ...

    def open_object(self, tenant_id: UUID, object_key: str) -> Any: ...

    def delete_gallery_media(self, tenant_id: UUID, media_id: UUID) -> Any: ...

    def list_gallery_media(self, tenant_id: UUID) -> list[Any]: ...


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    tenant_id: UUID
    brand_id: UUID
    kind: str
    staged_path: str | None
    filename: str
    upload_sha256: str | None
    attempts: int
    #: The status the job was claimed in: a `cut` claimed in `parts_saved` only has
    #: steps 4 and 5 left.
    status: str = STATUS_RUNNING
    source_media_id: UUID | None = None
    #: A `cut` job's kept spans, in order: part `i` is `(start_ms, end_ms)`.
    segments: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class JobOutcome:
    job_id: UUID
    status: str  # done | failed | retry | lost_lease
    error_code: str = ""
    media_id: UUID | None = None


@dataclass
class ReconcileReport:
    tenant_id: UUID
    folders: int = 0
    objects: int = 0
    bytes: int = 0
    tombstones: int = 0
    staging_files: int = 0
    undated: int = 0
    errors: list[str] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


class MediaJobRunner:
    def __init__(
        self,
        *,
        gate: GalleryObjects,
        staging_root: Path,
        normalizer: BusinessVideoNormalizer,
        cutter: BusinessVideoCutter | None = None,
        clock: Callable[[], datetime] = _now,
        lease: timedelta = LEASE,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._gate = gate
        self._root = staging_root
        self._normalizer = normalizer
        self._cutter = cutter
        self._clock = clock
        self._lease = lease
        self._max_attempts = max_attempts

    # -- claim -------------------------------------------------------------------------

    def claim(self, tenant_id: UUID) -> ClaimedJob | None:
        """The oldest claimable job of the tenant (`ingest` or `cut`), leased to this
        worker. A job already at the attempt ceiling whose lease expired (its worker kept
        dying) is failed here instead of being run a fourth time — except a cut already
        past its point of no return (`parts_saved`), which is closed for the reconciler
        instead: a saved cut is never undone."""
        while True:
            exhausted: ClaimedJob | None = None
            now = self._clock()
            expired = or_(GalleryJob.lease_until.is_(None), GalleryJob.lease_until <= now)
            with tenant_session(tenant_id) as session:
                job = session.scalar(
                    select(GalleryJob)
                    .where(
                        GalleryJob.kind.in_((JOB_INGEST, JOB_CUT)),
                        or_(
                            and_(GalleryJob.status == STATUS_QUEUED, expired),
                            and_(GalleryJob.status == STATUS_RUNNING, GalleryJob.lease_until < now),
                            and_(
                                GalleryJob.kind == JOB_CUT,
                                GalleryJob.status == STATUS_PARTS_SAVED,
                                expired,
                            ),
                        ),
                    )
                    .order_by(GalleryJob.created_at, GalleryJob.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if job is None:
                    return None
                # A saved cut whose worker died gets one more try at steps 4-5 (cheap: one
                # R2 delete) before the reconciler is left to finish it.
                ceiling = self._max_attempts + (job.status == STATUS_PARTS_SAVED)
                if job.attempts >= ceiling:
                    if job.status == STATUS_PARTS_SAVED:
                        _hand_off_to_reconciler(job, "attempts_exhausted", now)
                        continue
                    _settle_failed(job, "attempts_exhausted", now)
                    exhausted = _claimed(job)
                else:
                    if job.status != STATUS_PARTS_SAVED:
                        job.status = STATUS_RUNNING
                    job.attempts += 1
                    job.lease_until = now + self._lease
                    job.updated_at = now
                    session.flush()
                    return _claimed(job)
            self._cleanup_failed(exhausted)

    # -- run ---------------------------------------------------------------------------

    def run_tenant(
        self, tenant_id: UUID, *, limit: int = DEFAULT_JOBS_PER_TENANT
    ) -> list[JobOutcome]:
        outcomes: list[JobOutcome] = []
        for _ in range(limit):
            job = self.claim(tenant_id)
            if job is None:
                break
            outcomes.append(self.process(job))
        return outcomes

    def process(self, job: ClaimedJob) -> JobOutcome:
        if job.kind == JOB_INGEST:
            return self._process_ingest(job)
        if job.kind == JOB_CUT:
            return self._process_cut(job)
        return self._fail(job, "unsupported_kind", permanent=True)

    # -- cut (CM-3) --------------------------------------------------------------------

    def _process_cut(self, job: ClaimedJob) -> JobOutcome:
        if job.status == STATUS_PARTS_SAVED:  # reclaimed past the point of no return
            return self._finish_cut(job)
        if self._cutter is None:
            return self._fail(job, "cutter_unavailable", permanent=False)
        if job.source_media_id is None or not job.segments:
            return self._fail(job, "cut_invalid", permanent=True)
        with tenant_session(job.tenant_id) as session:
            source = session.get(BusinessMedia, job.source_media_id)
            if source is None or source.deleted_at is not None:
                source_key, duration_ms = None, 0
            else:
                source_key, duration_ms = source.object_key, int(source.duration_ms or 0)
        if source_key is None:
            return self._fail(job, "source_missing", permanent=True)
        if job.segments[-1][1] > duration_ms:
            return self._fail(job, "cut_invalid", permanent=True)
        with tempfile.TemporaryDirectory(prefix="qualify-gallery-cut-") as tmp:
            original = Path(tmp) / "original.mp4"
            try:
                self._download(job.tenant_id, source_key, original)
            except ObjectNotFound:
                return self._fail(job, "source_missing", permanent=True)
            except Exception as exc:  # noqa: BLE001 — R2 hiccup: retry
                return self._fail(job, f"r2_read:{type(exc).__name__}", permanent=False)
            parts: list[CutBusinessPart] = []
            for index, (start_ms, end_ms) in enumerate(job.segments):
                try:
                    part = self._cutter.cut_file(
                        original,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        out_dir=Path(tmp) / f"part-{index}",
                    )
                except UnreadableVideo:
                    return self._fail(job, "unreadable", permanent=True)
                except Exception as exc:  # noqa: BLE001 — timeouts, OOM kills: retry
                    return self._fail(job, f"cut:{type(exc).__name__}", permanent=False)
                if not self._renew_lease(job):  # reclaimed meanwhile: not ours any more
                    return JobOutcome(job.id, "lost_lease")
                parts.append(part)
            sizes: list[int] = []
            try:
                for index, part in enumerate(parts):
                    prefix = gallery_media_prefix(job.tenant_id, cut_part_media_id(job.id, index))
                    with part.video_path.open("rb") as fh:
                        self._gate.put_media(
                            job.tenant_id, prefix + VIDEO_KEY, fh, part.content_type
                        )
                    with part.poster_path.open("rb") as fh:
                        self._gate.put_media(
                            job.tenant_id, prefix + POSTER_KEY, fh, part.poster_content_type
                        )
                    sizes.append(part.video_path.stat().st_size)
            except Exception as exc:  # noqa: BLE001 — retry onto the same keys
                return self._fail(job, f"r2_write:{type(exc).__name__}", permanent=False)
        try:
            saved = self._save_parts(job, parts, sizes)
        except Exception as exc:  # noqa: BLE001 — the transaction rolled back as a whole
            return self._fail(job, f"settle:{type(exc).__name__}", permanent=False)
        if saved is not None:
            return saved
        return self._finish_cut(job)

    def _download(self, tenant_id: UUID, object_key: str, target: Path) -> None:
        stream = self._gate.open_object(tenant_id, object_key)
        try:
            with target.open("wb") as out:
                shutil.copyfileobj(stream, out, 1024 * 1024)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()

    def _save_parts(
        self, job: ClaimedJob, parts: Sequence[CutBusinessPart], sizes: Sequence[int]
    ) -> JobOutcome | None:
        """Step 3, ONE transaction: the parts' rows in the original's place, the
        original's tombstone and the job `parts_saved`. None when it committed; an
        outcome when it did not (lease lost, or the original vanished)."""
        now = self._clock()
        part_ids = [cut_part_media_id(job.id, i) for i in range(len(parts))]
        with tenant_session(job.tenant_id) as session:
            row = session.get(GalleryJob, job.id, with_for_update=True)
            if row is None or row.status != STATUS_RUNNING or row.attempts != job.attempts:
                return JobOutcome(job.id, "lost_lease")
            _lock_gallery(session, job.brand_id)
            source = session.get(BusinessMedia, job.source_media_id, with_for_update=True)
            if source is None or source.deleted_at is not None:
                missing = True
            else:
                missing = False
                if len(parts) > 1:  # make room right after the original, keep the order
                    session.execute(
                        update(BusinessMedia)
                        .where(
                            BusinessMedia.brand_id == job.brand_id,
                            BusinessMedia.deleted_at.is_(None),
                            BusinessMedia.position > source.position,
                            BusinessMedia.id != source.id,
                        )
                        .values(position=BusinessMedia.position + (len(parts) - 1))
                    )
                base_name = (source.filename or "")[:180]
                for index, (part, size) in enumerate(zip(parts, sizes, strict=True)):
                    prefix = gallery_media_prefix(job.tenant_id, part_ids[index])
                    session.execute(
                        insert(BusinessMedia)
                        .values(
                            id=part_ids[index],
                            tenant_id=job.tenant_id,
                            brand_id=job.brand_id,
                            media_type=MEDIA_TYPE_VIDEO,
                            object_key=prefix + VIDEO_KEY,
                            poster_key=prefix + POSTER_KEY,
                            content_type=part.content_type,
                            width=part.width,
                            height=part.height,
                            duration_ms=min(max(int(part.duration_ms), 1), 60_000),
                            bytes=size,
                            has_audio=bool(part.has_audio),
                            position=source.position + index,
                            filename=f"{base_name} (parte {index + 1})".strip(),
                            upload_sha256=None,
                            source_media_id=source.id,
                            cut_start_ms=part.start_ms,
                            cut_end_ms=part.end_ms,
                            job_id=job.id,
                            pipeline_version=CUT_PIPELINE_VERSION,
                        )
                        .on_conflict_do_nothing(index_elements=["id"])
                    )
                source.deleted_at = now
                row.status = STATUS_PARTS_SAVED
                row.lease_until = now + self._lease
                row.updated_at = now
                row.last_error_code = None
                row.result = {
                    **(row.result or {}),
                    "part_ids": [str(p) for p in part_ids],
                    "parts_bytes": sum(sizes),
                    "worker": worker_id(),
                }
        if missing:
            return self._fail(job, "source_missing", permanent=True)
        return None

    def _finish_cut(self, job: ClaimedJob) -> JobOutcome:
        """Steps 4 and 5, both idempotent: the original's folder, then its row and the
        job `done`. A failure keeps the job `parts_saved` for a retry."""
        assert job.source_media_id is not None
        try:
            deleted = self._gate.delete_gallery_media(job.tenant_id, job.source_media_id)
        except Exception as exc:  # noqa: BLE001 — R2 hiccup: retry steps 4 and 5
            return self._retry_finish(job, f"r2_delete:{type(exc).__name__}")
        now = self._clock()
        with tenant_session(job.tenant_id) as session:
            row = session.get(GalleryJob, job.id, with_for_update=True)
            if row is None or row.status != STATUS_PARTS_SAVED or row.attempts != job.attempts:
                return JobOutcome(job.id, "lost_lease")
            session.execute(
                delete(BusinessMedia).where(
                    BusinessMedia.id == job.source_media_id, BusinessMedia.deleted_at.is_not(None)
                )
            )
            row.status = STATUS_DONE
            row.lease_until = None
            row.updated_at = now
            row.finished_at = now
            row.last_error_code = None
            row.result = {
                **(row.result or {}),
                "deleted_objects": deleted.objects,
                "deleted_bytes": deleted.bytes,
            }
        return JobOutcome(job.id, STATUS_DONE)

    def _retry_finish(self, job: ClaimedJob, code: str) -> JobOutcome:
        now = self._clock()
        with tenant_session(job.tenant_id) as session:
            row = session.get(GalleryJob, job.id, with_for_update=True)
            if row is None or row.status != STATUS_PARTS_SAVED or row.attempts != job.attempts:
                return JobOutcome(job.id, "lost_lease", code)
            if row.attempts >= self._max_attempts:
                _hand_off_to_reconciler(row, code, now)
                handed_off = True
            else:
                row.lease_until = now + RETRY_BACKOFF * row.attempts
                row.last_error_code = code
                row.updated_at = now
                handed_off = False
        logger.warning(
            "media_worker.cut_finish_failed tenant=%s job=%s code=%s handed_off=%s",
            job.tenant_id,
            job.id,
            code,
            handed_off,
        )
        return JobOutcome(job.id, STATUS_DONE if handed_off else "retry", code)

    def _process_ingest(self, job: ClaimedJob) -> JobOutcome:
        media_id = ingest_media_id(job.id)
        try:
            source = resolve_staged(self._root, job.tenant_id, job.staged_path or "")
        except ValueError:
            return self._fail(job, "staging_invalid", permanent=True)
        if not source.is_file():
            return self._fail(job, "staging_missing", permanent=True)
        with tempfile.TemporaryDirectory(prefix="qualify-gallery-") as tmp:
            try:
                video = self._normalizer.normalize_file(source, out_dir=Path(tmp))
            except UnreadableVideo:
                return self._fail(job, "unreadable", permanent=True)
            except Exception as exc:  # noqa: BLE001 — timeouts, OOM kills: retry
                return self._fail(job, f"normalize:{type(exc).__name__}", permanent=False)
            prefix = gallery_media_prefix(job.tenant_id, media_id)
            if not self._renew_lease(job):  # reclaimed while transcoding: not ours any more
                return JobOutcome(job.id, "lost_lease")
            try:
                with video.video_path.open("rb") as fh:
                    self._gate.put_media(job.tenant_id, prefix + VIDEO_KEY, fh, video.content_type)
                with video.poster_path.open("rb") as fh:
                    self._gate.put_media(
                        job.tenant_id, prefix + POSTER_KEY, fh, video.poster_content_type
                    )
                size = video.video_path.stat().st_size
            except Exception as exc:  # noqa: BLE001 — R2 hiccup: retry onto the same keys
                return self._fail(job, f"r2_write:{type(exc).__name__}", permanent=False)
        try:
            outcome = self._settle_done(job, media_id, video, size)
        except Exception as exc:  # noqa: BLE001
            return self._fail(job, f"settle:{type(exc).__name__}", permanent=False)
        if outcome.status == STATUS_DONE:
            discard_staged(self._root, job.tenant_id, job.staged_path or "")
            if outcome.media_id != media_id:  # the same file went live meanwhile
                self._forget(job.tenant_id, media_id)
        return outcome

    def _renew_lease(self, job: ClaimedJob) -> bool:
        """Extend the lease before the R2 upload, if the job is still this worker's."""
        now = self._clock()
        with tenant_session(job.tenant_id) as session:
            row = session.get(GalleryJob, job.id, with_for_update=True)
            if row is None or row.status != STATUS_RUNNING or row.attempts != job.attempts:
                return False
            row.lease_until = now + self._lease
            row.updated_at = now
        return True

    def _settle_done(self, job: ClaimedJob, media_id: UUID, video: Any, size: int) -> JobOutcome:
        now = self._clock()
        prefix = gallery_media_prefix(job.tenant_id, media_id)
        with tenant_session(job.tenant_id) as session:
            row = session.get(GalleryJob, job.id, with_for_update=True)
            if row is None or row.status != STATUS_RUNNING or row.attempts != job.attempts:
                return JobOutcome(job.id, "lost_lease")
            _lock_gallery(session, job.brand_id)
            final_id = media_id
            existing = _live_by_digest(session, job.brand_id, job.upload_sha256 or "")
            if existing is not None and existing.id != media_id:
                final_id = existing.id
            elif existing is None:
                session.execute(
                    insert(BusinessMedia)
                    .values(
                        id=media_id,
                        tenant_id=job.tenant_id,
                        brand_id=job.brand_id,
                        media_type=MEDIA_TYPE_VIDEO,
                        object_key=prefix + VIDEO_KEY,
                        poster_key=prefix + POSTER_KEY,
                        content_type=video.content_type,
                        width=video.width,
                        height=video.height,
                        duration_ms=min(max(int(video.duration_ms), 1), 60_000),
                        bytes=size,
                        has_audio=bool(video.has_audio),
                        position=_next_position(session, job.brand_id),
                        filename=job.filename[:200],
                        upload_sha256=job.upload_sha256,
                        job_id=job.id,
                        pipeline_version=INGEST_PIPELINE_VERSION,
                    )
                    .on_conflict_do_nothing()
                )
            row.status = STATUS_DONE
            row.lease_until = None
            row.updated_at = now
            row.finished_at = now
            row.last_error_code = None
            row.result = {
                "media_id": str(final_id),
                "trimmed": bool(video.trimmed),
                "source_duration_ms": video.source_duration_ms,
                "duration_ms": int(video.duration_ms),
                "has_audio": bool(video.has_audio),
                "bytes": size,
                "duplicate_of_live": final_id != media_id,
                "worker": worker_id(),
            }
        return JobOutcome(job.id, STATUS_DONE, media_id=final_id)

    def _fail(self, job: ClaimedJob, code: str, *, permanent: bool) -> JobOutcome:
        now = self._clock()
        with tenant_session(job.tenant_id) as session:
            row = session.get(GalleryJob, job.id, with_for_update=True)
            if row is None or row.status != STATUS_RUNNING or row.attempts != job.attempts:
                return JobOutcome(job.id, "lost_lease", code)
            final = permanent or row.attempts >= self._max_attempts
            if final:
                _settle_failed(row, code, now)
            else:
                row.status = STATUS_QUEUED
                row.lease_until = now + RETRY_BACKOFF * row.attempts
                row.last_error_code = code
                row.updated_at = now
        logger.warning(
            "media_worker.job_failed tenant=%s job=%s code=%s final=%s",
            job.tenant_id,
            job.id,
            code,
            final,
        )
        if final:
            self._cleanup_failed(job)
            return JobOutcome(job.id, STATUS_FAILED, code)
        return JobOutcome(job.id, "retry", code)

    def _cleanup_failed(self, job: ClaimedJob | None) -> None:
        """A failed job leaves nothing behind: an ingest's staged file and R2 folder; a
        cut's part folders `uuid5(job, i)`, enumerated from its spans without listing the
        bucket (it only ever fails BEFORE its parts were saved, so no row points there,
        and the original was never touched)."""
        if job is None:
            return
        if job.staged_path:
            discard_staged(self._root, job.tenant_id, job.staged_path)
        if job.kind == JOB_INGEST:
            self._forget(job.tenant_id, ingest_media_id(job.id))
        elif job.kind == JOB_CUT:
            for index in range(len(job.segments)):
                self._forget(job.tenant_id, cut_part_media_id(job.id, index))

    def _forget(self, tenant_id: UUID, media_id: UUID) -> None:
        try:
            self._gate.delete_gallery_media(tenant_id, media_id)
        except Exception as exc:  # noqa: BLE001 — the reconciler deletes it after 24 h
            logger.warning("media_worker.forget_failed error=%s", type(exc).__name__)

    # -- reconciler --------------------------------------------------------------------

    def reconcile_tenant(self, tenant_id: UUID) -> ReconcileReport:
        now = self._clock()
        report = ReconcileReport(tenant_id=tenant_id)
        with tenant_session(tenant_id) as session:
            rows = session.execute(select(BusinessMedia.id, BusinessMedia.deleted_at)).all()
            jobs = session.execute(
                select(
                    GalleryJob.id, GalleryJob.kind, GalleryJob.staged_path, GalleryJob.segments
                ).where(GalleryJob.status.in_(ACTIVE_STATUSES))
            ).all()
        known = {r.id for r in rows}
        expected: set[UUID] = set()
        staged_in_use: set[str] = set()
        for j in jobs:
            if j.kind == JOB_INGEST:
                expected.add(ingest_media_id(j.id))
            elif j.kind == JOB_CUT:
                expected.update(cut_part_media_id(j.id, i) for i in range(len(j.segments or [])))
            if j.staged_path:
                staged_in_use.add(j.staged_path)

        # (a) folders with no row, no tombstone and no active job, older than 24 h.
        try:
            listed = self._gate.list_gallery_media(tenant_id)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"list:{type(exc).__name__}")
            listed = []
        newest: dict[UUID, datetime | None] = {}
        for obj in listed:
            if obj.media_id is None:
                continue
            seen = newest.get(obj.media_id, datetime.min.replace(tzinfo=UTC))
            if obj.last_modified is None or seen is None:
                newest[obj.media_id] = None
            else:
                newest[obj.media_id] = max(seen, obj.last_modified)
        for media_id, modified in sorted(newest.items(), key=lambda kv: str(kv[0])):
            if media_id in known or media_id in expected:
                continue
            if modified is None:
                report.undated += 1
                continue
            if now - modified <= ORPHAN_AGE:
                continue
            self._delete_folder(tenant_id, media_id, report, count_folder=True)

        # (b) tombstones older than 1 h: folder, then row.
        for r in rows:
            if r.deleted_at is None or now - r.deleted_at <= TOMBSTONE_AGE:
                continue
            if not self._delete_folder(tenant_id, r.id, report, count_folder=False):
                continue
            with tenant_session(tenant_id) as session:
                session.execute(
                    delete(BusinessMedia).where(
                        BusinessMedia.id == r.id, BusinessMedia.deleted_at.is_not(None)
                    )
                )
            report.tombstones += 1

        # (c) staged files older than 24 h that no active job points at.
        folder = staging_dir(self._root, tenant_id)
        if folder.is_dir():
            for path in folder.iterdir():
                try:
                    relpath = staging_relpath(tenant_id, UUID(path.name))
                except ValueError:
                    continue
                if relpath in staged_in_use or not path.is_file():
                    continue
                age = now - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                if age > STAGING_AGE:
                    path.unlink(missing_ok=True)
                    report.staging_files += 1
        return report

    def _delete_folder(
        self, tenant_id: UUID, media_id: UUID, report: ReconcileReport, *, count_folder: bool
    ) -> bool:
        try:
            deleted = self._gate.delete_gallery_media(tenant_id, media_id)
        except Exception as exc:  # noqa: BLE001 — next run tries again
            report.errors.append(f"delete:{type(exc).__name__}")
            return False
        report.objects += deleted.objects
        report.bytes += deleted.bytes
        if count_folder or deleted.objects:
            report.folders += 1
        return True


def _claimed(job: GalleryJob) -> ClaimedJob:
    return ClaimedJob(
        id=job.id,
        tenant_id=job.tenant_id,
        brand_id=job.brand_id,
        kind=job.kind,
        staged_path=job.staged_path,
        filename=job.filename,
        upload_sha256=job.upload_sha256,
        attempts=job.attempts,
        status=job.status,
        source_media_id=job.source_media_id,
        segments=_spans(job.segments),
    )


def _spans(segments: Any) -> tuple[tuple[int, int], ...]:
    """A cut job's stored spans (`[{"start_ms", "end_ms"}, …]`) as tuples; anything
    malformed gives () and the job fails as `cut_invalid`."""
    if not isinstance(segments, list):
        return ()
    spans: list[tuple[int, int]] = []
    for item in segments:
        try:
            spans.append((int(item["start_ms"]), int(item["end_ms"])))
        except (KeyError, TypeError, ValueError):
            return ()
    return tuple(spans)


def _settle_failed(job: GalleryJob, code: str, now: datetime) -> None:
    job.status = STATUS_FAILED
    job.lease_until = None
    job.last_error_code = code
    job.updated_at = now
    job.finished_at = now


def _hand_off_to_reconciler(job: GalleryJob, code: str, now: datetime) -> None:
    """A cut whose parts are saved but whose original could not be deleted after every
    attempt: the parts stay (never undone), the original is a tombstone the daily
    reconciler finishes (rule b). The job ends `done` so the video's mark is lifted."""
    job.status = STATUS_DONE
    job.lease_until = None
    job.last_error_code = code
    job.updated_at = now
    job.finished_at = now
    job.result = {**(job.result or {}), "original_left_to_reconciler": True}


# --- which tenants ------------------------------------------------------------------------


class TenantSource(Protocol):
    def with_jobs(self) -> list[UUID]: ...

    def for_reconcile(self) -> list[UUID]: ...


class ScopedTenants:
    """A fixed, non-empty set of tenants: no cross-tenant read ever happens."""

    def __init__(self, tenant_ids: Iterable[UUID]) -> None:
        self._ids = list(dict.fromkeys(tenant_ids))
        if not self._ids:
            raise ValueError("a scoped pass needs at least one tenant id")

    def with_jobs(self) -> list[UUID]:
        return list(self._ids)

    def for_reconcile(self) -> list[UUID]:
        return list(self._ids)


class DiscoveredTenants:
    """Production discovery through `admin_session` — tenant ids only."""

    def with_jobs(self) -> list[UUID]:
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415

        with admin_session() as session:
            return list(
                session.scalars(
                    select(GalleryJob.tenant_id)
                    .where(GalleryJob.status.in_(ACTIVE_STATUSES))
                    .distinct()
                    .order_by(GalleryJob.tenant_id)
                )
            )

    def for_reconcile(self) -> list[UUID]:
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415

        from qualify_api.tenancy.models import Tenant  # noqa: PLC0415

        with admin_session() as session:
            return list(session.scalars(select(Tenant.id).order_by(Tenant.id)))


# --- the loop -----------------------------------------------------------------------------


@dataclass
class PassReport:
    tenants: int = 0
    outcomes: list[JobOutcome] = field(default_factory=list)
    error: str = ""


def jobs_pass(runner: MediaJobRunner, tenants: TenantSource, *, limit: int) -> PassReport:
    report = PassReport()
    try:
        tenant_ids = tenants.with_jobs()
    except Exception as exc:  # noqa: BLE001
        logger.exception("media_worker.discovery_failed")
        report.error = type(exc).__name__
        return report
    report.tenants = len(tenant_ids)
    for tenant_id in tenant_ids:
        try:
            report.outcomes.extend(runner.run_tenant(tenant_id, limit=limit))
        except Exception:  # noqa: BLE001 — one tenant must not stop the others
            logger.exception("media_worker.tenant_failed tenant=%s", tenant_id)
    for outcome in report.outcomes:
        logger.info(
            "media_worker.job job=%s status=%s code=%s",
            outcome.job_id,
            outcome.status,
            outcome.error_code or "none",
        )
    return report


def reconcile_pass(runner: MediaJobRunner, tenants: TenantSource) -> list[ReconcileReport]:
    try:
        tenant_ids = tenants.for_reconcile()
    except Exception:  # noqa: BLE001
        logger.exception("media_worker.reconcile_discovery_failed")
        return []
    reports: list[ReconcileReport] = []
    for tenant_id in tenant_ids:
        try:
            report = runner.reconcile_tenant(tenant_id)
        except Exception:  # noqa: BLE001
            logger.exception("media_worker.reconcile_tenant_failed tenant=%s", tenant_id)
            continue
        if report.folders or report.tombstones or report.staging_files or report.errors:
            logger.info(
                "media_worker.reconcile tenant=%s folders=%d objects=%d bytes=%d "
                "tombstones=%d staging_files=%d undated=%d errors=%s",
                tenant_id,
                report.folders,
                report.objects,
                report.bytes,
                report.tombstones,
                report.staging_files,
                report.undated,
                ",".join(report.errors) or "none",
            )
        reports.append(report)
    return reports


def run_loop(
    runner: MediaJobRunner,
    tenants: TenantSource,
    *,
    interval: int,
    limit: int,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    should_stop: Callable[[], bool] = lambda: False,
    max_ticks: int | None = None,
) -> int:
    """Reconcile at start and every 24 h; a jobs pass every `interval` s (start to start)."""
    last_reconcile: float | None = None
    ticks = 0
    while not should_stop():
        started = clock()
        if last_reconcile is None or started - last_reconcile >= RECONCILE_EVERY_SECONDS:
            reconcile_pass(runner, tenants)
            last_reconcile = started
        jobs_pass(runner, tenants, limit=limit)
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            return 0
        sleep(max(0.0, interval - (clock() - started)))
    return 0


# --- production wiring and CLI ------------------------------------------------------------


def production_runner() -> MediaJobRunner:
    from qualify_creative.video.business import FfmpegBusinessVideoNormalizer  # noqa: PLC0415
    from qualify_creative.video.business_cut import FfmpegBusinessVideoCutter  # noqa: PLC0415
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    from qualify_api.creative.composition import media_root  # noqa: PLC0415

    return MediaJobRunner(
        gate=ObjectGate(R2ObjectStore(R2Settings.from_env())),
        staging_root=media_root(),
        normalizer=FfmpegBusinessVideoNormalizer(),
        cutter=FfmpegBusinessVideoCutter(),
    )


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.catalog.media_worker",
        description="Prepare the Galería's videos and reconcile its R2 folders (m-24955918).",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--tenant",
        dest="tenants",
        action="append",
        type=UUID,
        metavar="UUID",
        help="Only this tenant (repeatable). Use this locally.",
    )
    scope.add_argument(
        "--all-tenants", action="store_true", help="Every tenant (production discovery)."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="One jobs pass, then exit.")
    mode.add_argument("--reconcile", action="store_true", help="One reconcile pass, then exit.")
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between jobs passes (default {DEFAULT_INTERVAL_SECONDS}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_JOBS_PER_TENANT,
        help=f"Jobs per tenant per pass (default {DEFAULT_JOBS_PER_TENANT}).",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    make_runner: Callable[[], MediaJobRunner] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.interval < MIN_INTERVAL_SECONDS:
        parser.error(f"--interval must be at least {MIN_INTERVAL_SECONDS} second(s)")
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    tenants: TenantSource = DiscoveredTenants() if args.all_tenants else ScopedTenants(args.tenants)
    runner = (make_runner or production_runner)()
    logger.info(
        "media_worker.start scope=%s mode=%s interval=%ss",
        "all-tenants" if args.all_tenants else ",".join(str(t) for t in args.tenants),
        "once" if args.once else "reconcile" if args.reconcile else "loop",
        args.interval,
    )
    if args.once:
        return 1 if jobs_pass(runner, tenants, limit=args.limit).error else 0
    if args.reconcile:
        reconcile_pass(runner, tenants)
        return 0
    stopping = {"stop": False}

    def _stop(*_: object) -> None:
        stopping["stop"] = True

    signal.signal(signal.SIGTERM, _stop)
    try:
        return run_loop(
            runner,
            tenants,
            interval=args.interval,
            limit=args.limit,
            should_stop=lambda: stopping["stop"],
        )
    except KeyboardInterrupt:
        logger.info("media_worker.stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
