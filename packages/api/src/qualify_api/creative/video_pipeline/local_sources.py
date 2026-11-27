"""The local assembly only ever decodes a source of at most 4K 8 bits (m-25042483,
founder's decision «Bajarlos a 4K 8 bits»; the rule is `qualify_creative.video.
source_limits`). A bigger or 10-bit video stretch is normalized BEFOREHAND by the
`media-worker` (a `normalize_local` job in `gallery_jobs`, migration 0171) — silently and
at cost 0: the piece just waits.

`LocalSources` is what `render_local_part` asks for each video stretch's file:

1. `open` (before any stretch is fetched): ONE read of the `normalize_local` jobs of the
   part's files. A file with a job `done` is read as its normalized copy; a job queued or
   running → `LocalSourceNormalizing` at once, before anything is downloaded — unless it
   has waited longer than `MAX_NORMALIZE_WAIT`: then the piece fails
   (`code="normalize_timeout"`, a WARNING); a job `failed` for a reason of the FILE
   (`PERMANENT_FAILURES`: unreadable, missing, still over the limit, too large to keep) →
   the piece fails with `LOCAL_SOURCE_FAILED_TEXT` (`code="normalize_failed"`); failed
   for a reason of the MACHINE (attempts exhausted by kills, R2, a deploy) → a new job is
   queued and the piece waits, up to `MAX_TRANSIENT_FAILURES` such failed jobs per file,
   then it fails too. Never a charge;
2. `fetch` (one stretch): the file to disk through the tenant-checking door, then its
   container HEADER is read (`read_header`: size, pixel format — no frame decoded). Over
   the limit → a `normalize_local` job for that file (`INSERT … ON CONFLICT DO NOTHING`:
   the same file is never normalized twice), the part's remaining unchecked files are
   checked the same way (so they queue together), and `LocalSourceNormalizing`.

`LocalSourceNormalizing` is a `LocalVideoWait` (a `CheckpointError`): the creative worker
releases the preparation NOT done, logs it at INFO, and tries it again no sooner than
`retry_after_s` (a minute, `heavy_video.hold`) — meanwhile the draft is left out of the
worker's pass, so a waiting piece never takes another piece's turn; nothing is read past
the header, written, charged or told to the owner.

The WHOLE file is normalized, not only the stretch the part uses: the copy is keyed by the
file alone, so every stretch of it — in this part, another part or another piece — reads
the same copy and the file is encoded once. The cost is the media-worker's time: a minute
of 5K HEVC takes 10–20 min on its 1 vCPU (a longer file proportionally more, up to the
normalizer's 3 h timeout), one job at a time, after the Galería's own jobs. Galería files
(`gallery/…`) are already ≤ 1080×1920 8-bit (`FfmpegBusinessVideoNormalizer`): never looked
up nor checked.

The normalized copy lives at `t/{tenant}/normalized/{uuid5(version:source)}/video.mp4`
(write-once under the bucket's `t/` lock: a retry finds it and does not encode again).
Provenance: each video stretch of the asset records its original key, the copy's key and
the normalizer's version (`provenance`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

from qualify_creative.enums import FailureReason
from qualify_creative.video.local_normalize import (
    LEASE_MARGIN_SECONDS,
    NORMALIZE_LOCAL_VERSION,
    TIMEOUT_MAX_SECONDS,
)
from qualify_creative.video.source_limits import SOURCE_LIMITS_VERSION, SourceHeader

from qualify_api.creative.heavy_video import LocalVideoWait

logger = logging.getLogger(__name__)

JOB_KIND = "normalize_local"
#: The namespace of the normalized copies' folder ids (`uuid5(namespace, version:source)`).
NORMALIZED_NAMESPACE = UUID("6b0f3c52-5d1e-4c55-9a3e-25042483f001")
NORMALIZED_FILE = "video.mp4"
_GALLERY_ROOT = "gallery/"
#: A job's failure that is the FILE's: retrying cannot help, the piece fails.
PERMANENT_FAILURES = frozenset(
    {
        "unreadable",
        "source_missing",
        "normalized_over_limit",
        "normalized_too_large",
        "payload_invalid",
    }
)
#: Failed jobs of the MACHINE's (attempts exhausted, killed, R2, a deploy) a file may
#: have before its piece fails instead of queueing yet another one.
MAX_TRANSIENT_FAILURES = 2
#: The media-worker's attempts at one job (`media_worker.MAX_ATTEMPTS`, copied: importing
#: the worker here would pull its whole runner into the creative worker).
JOB_ATTEMPTS = 3
#: How long a piece waits for one job queued or running before it fails. The worst real
#: case is every attempt of the job running to the normalizer's own timeout (3 h, a long
#: 5K file on 1 vCPU) plus the lease margin a killed attempt waits out before it is
#: claimed again, plus two hours queued behind other jobs: 3 × 3 h 05 + 2 h = 11 h 15. A
#: media-worker that is down fails the piece then (no charge; the job still finishes).
MAX_NORMALIZE_WAIT = JOB_ATTEMPTS * timedelta(
    seconds=TIMEOUT_MAX_SECONDS + LEASE_MARGIN_SECONDS
) + timedelta(hours=2)
#: A waiting piece is tried again no sooner than this.
RETRY_AFTER_SECONDS = 60.0


class LocalSourceNormalizing(LocalVideoWait):
    """A video stretch's file is being brought down to 4K 8 bits by the media-worker: the
    local video waits for it (made on a later pass, never a failed preparation). The worker
    leaves the draft out of its passes for `retry_after_s`."""

    retry_after_s = RETRY_AFTER_SECONDS


def normalize_job_key(source_key: str, version: str = NORMALIZE_LOCAL_VERSION) -> str:
    """The job's idempotency key: one job per file and normalizer version."""
    return f"{JOB_KIND}:{version}:{source_key}"


def normalized_key(tenant_id: UUID, source_key: str, version: str = NORMALIZE_LOCAL_VERSION) -> str:
    """The deterministic key of `source_key`'s normalized copy, under the tenant's `t/`."""
    folder = uuid5(NORMALIZED_NAMESPACE, f"{version}:{source_key}")
    return f"t/{tenant_id}/normalized/{folder}/{NORMALIZED_FILE}"


def needs_check(key: str) -> bool:
    """Whether a video stretch's file is looked up and checked: everything but the
    Galería's, which its own normalizer already made ≤ 1080×1920 8-bit."""
    return not key.startswith(_GALLERY_ROOT)


@dataclass(frozen=True)
class NormalizeJob:
    """The latest `normalize_local` job of one file, as the assembly reads it."""

    status: str  # queued | running | done | failed
    normalized_key: str
    version: str
    error_code: str | None = None
    #: When this job was queued (its wait is measured from it); None when unknown.
    created_at: datetime | None = None
    #: How many of this file's jobs (this one included) failed for a reason of the
    #: machine — `MAX_TRANSIENT_FAILURES` caps the re-queueing.
    transient_failures: int = 0

    @property
    def failed_for_good(self) -> bool:
        return self.status == "failed" and (
            (self.error_code or "") in PERMANENT_FAILURES
            or self.transient_failures >= MAX_TRANSIENT_FAILURES
        )


def is_transient(status: str, error_code: str | None) -> bool:
    """A failed job whose failure was the machine's, not the file's."""
    return status == "failed" and (error_code or "") not in PERMANENT_FAILURES


class LocalSourceJobs(Protocol):
    """The `normalize_local` jobs, as the creative worker sees them (a test's double)."""

    def lookup(self, tenant_id: UUID, source_keys: Sequence[str]) -> dict[str, NormalizeJob]: ...

    def enqueue(
        self, tenant_id: UUID, source_key: str, *, draft_id: UUID | None, brand_id: UUID | None
    ) -> None: ...


class PostgresLocalSourceJobs:
    """`gallery_jobs` through `tenant_session` (`qualify_app`, RLS: this tenant only)."""

    def lookup(self, tenant_id: UUID, source_keys: Sequence[str]) -> dict[str, NormalizeJob]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.catalog.business_media_models import GalleryJob  # noqa: PLC0415

        by_job_key = {normalize_job_key(key): key for key in source_keys}
        if not by_job_key:
            return {}
        found: dict[str, NormalizeJob] = {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(
                    GalleryJob.idempotency_key,
                    GalleryJob.status,
                    GalleryJob.payload,
                    GalleryJob.result,
                    GalleryJob.last_error_code,
                    GalleryJob.pipeline_version,
                    GalleryJob.created_at,
                )
                .where(
                    GalleryJob.kind == JOB_KIND,
                    GalleryJob.idempotency_key.in_(list(by_job_key)),
                )
                # the newest first: a failed job is superseded by a later one
                .order_by(GalleryJob.created_at.desc(), GalleryJob.id)
            ).all()
        transient: dict[str, int] = {}
        for row in rows:
            source = by_job_key[row.idempotency_key]
            if is_transient(row.status, row.last_error_code):
                transient[source] = transient.get(source, 0) + 1
            if source in found:
                continue
            result = row.result or {}
            payload = row.payload or {}
            found[source] = NormalizeJob(
                status=row.status,
                normalized_key=str(
                    result.get("normalized_key")
                    or payload.get("normalized_key")
                    or normalized_key(tenant_id, source)
                ),
                version=str(result.get("version") or row.pipeline_version),
                error_code=row.last_error_code,
                created_at=row.created_at,
            )
        return {
            source: replace(job, transient_failures=transient.get(source, 0))
            for source, job in found.items()
        }

    def enqueue(
        self, tenant_id: UUID, source_key: str, *, draft_id: UUID | None, brand_id: UUID | None
    ) -> None:
        """One `normalize_local` job for `source_key` — or none when one that did not
        fail already holds its key (`uq_gallery_jobs_normalize_local`, ON CONFLICT DO
        NOTHING). The business is the draft's (the job row needs one)."""
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        from qualify_api.catalog.business_media_models import GalleryJob  # noqa: PLC0415
        from qualify_api.creative.models import ContentDraft  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            brand = brand_id
            if draft_id is not None:
                brand = (
                    session.scalar(select(ContentDraft.brand_id).where(ContentDraft.id == draft_id))
                    or brand
                )
            if brand is None:
                raise ValueError("a normalize_local job needs the draft's business")
            session.execute(
                insert(GalleryJob)
                .values(
                    tenant_id=tenant_id,
                    brand_id=brand,
                    kind=JOB_KIND,
                    idempotency_key=normalize_job_key(source_key),
                    pipeline_version=NORMALIZE_LOCAL_VERSION,
                    payload={
                        "source_key": source_key,
                        "normalized_key": normalized_key(tenant_id, source_key),
                        "version": NORMALIZE_LOCAL_VERSION,
                        "draft_id": str(draft_id) if draft_id else None,
                    },
                )
                .on_conflict_do_nothing()
            )


class InMemoryLocalSourceJobs:
    """The jobs door in memory (offline tests, scripts): `enqueue` keeps ONE job per file
    unless the last one failed, like `uq_gallery_jobs_normalize_local`."""

    def __init__(self, jobs: dict[str, NormalizeJob] | None = None) -> None:
        self.jobs: dict[str, NormalizeJob] = dict(jobs or {})
        self.enqueued: list[str] = []
        #: Earlier failed jobs of the machine's, superseded by a newer one, per file.
        self.past_transient: dict[str, int] = {}

    def lookup(self, tenant_id: UUID, source_keys: Sequence[str]) -> dict[str, NormalizeJob]:
        found: dict[str, NormalizeJob] = {}
        for key in source_keys:
            job = self.jobs.get(key)
            if job is None:
                continue
            count = self.past_transient.get(key, 0) + is_transient(job.status, job.error_code)
            found[key] = replace(job, transient_failures=count)
        return found

    def enqueue(
        self, tenant_id: UUID, source_key: str, *, draft_id: UUID | None, brand_id: UUID | None
    ) -> None:
        held = self.jobs.get(source_key)
        if held is not None and held.status != "failed":
            return
        if held is not None and is_transient(held.status, held.error_code):
            self.past_transient[source_key] = self.past_transient.get(source_key, 0) + 1
        self.enqueued.append(source_key)
        self.jobs[source_key] = NormalizeJob(
            status="queued",
            normalized_key=normalized_key(tenant_id, source_key),
            version=NORMALIZE_LOCAL_VERSION,
        )


def default_jobs() -> LocalSourceJobs:
    """The production door (tests replace it)."""
    return PostgresLocalSourceJobs()


def _read_header(path: Path) -> SourceHeader:
    from qualify_creative.video.source_limits import read_header  # noqa: PLC0415

    return read_header(path)


@dataclass
class LocalSources:
    """The files of one local part's video stretches (see the module)."""

    tenant_id: UUID
    keys: tuple[str, ...]
    jobs: LocalSourceJobs
    fetch_file: Callable[[str, Path], None]
    draft_id: UUID | None = None
    brand_id: UUID | None = None
    header: Callable[[Path], SourceHeader] = _read_header
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    _ready: dict[str, NormalizeJob] = field(default_factory=dict)
    _checked: dict[str, SourceHeader] = field(default_factory=dict)

    @classmethod
    def open(
        cls,
        part: Any,
        *,
        tenant_id: UUID,
        fetch_file: Callable[[str, Path], None],
        jobs: LocalSourceJobs | None = None,
        draft_id: UUID | None = None,
        brand_id: UUID | None = None,
        header: Callable[[Path], SourceHeader] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> LocalSources:
        """The part's files and their jobs, read ONCE before anything is downloaded:
        raises `LocalSourceNormalizing` (a copy is being made) or `LocalVideoFailed`
        (`normalize_failed`) without reading a byte."""
        keys = tuple(
            dict.fromkeys(s.key for s in part.segments if s.kind == "video" and needs_check(s.key))
        )
        sources = cls(
            tenant_id=tenant_id,
            keys=keys,
            jobs=jobs or (default_jobs() if keys else InMemoryLocalSourceJobs()),
            fetch_file=fetch_file,
            draft_id=draft_id,
            brand_id=brand_id,
            header=header or _read_header,
            now=now or (lambda: datetime.now(UTC)),
        )
        if keys:
            sources._settle(sources.jobs.lookup(tenant_id, keys))
        return sources

    def _settle(self, found: dict[str, NormalizeJob]) -> None:
        waiting: list[str] = []
        now = self.now()
        for key in self.keys:
            job = found.get(key)
            if job is None:
                continue
            if job.status == "done":
                self._ready[key] = job
            elif job.failed_for_good:
                _fail(key, job.error_code)
            elif job.status == "failed":
                # the machine's failure, under the cap: a new job (the partial unique
                # index lets it in) and the piece waits for it
                self.jobs.enqueue(
                    self.tenant_id, key, draft_id=self.draft_id, brand_id=self.brand_id
                )
                logger.info(
                    "creative.local_source.normalize_requeued tenant=%s code=%s failed=%d",
                    self.tenant_id,
                    job.error_code or "unknown",
                    job.transient_failures,
                )
                waiting.append(key)
            elif job.created_at is not None and now - job.created_at > MAX_NORMALIZE_WAIT:
                logger.warning(
                    "creative.local_source.normalize_timeout tenant=%s draft_id=%s "
                    "status=%s waited_s=%d",
                    self.tenant_id,
                    self.draft_id,
                    job.status,
                    int((now - job.created_at).total_seconds()),
                )
                _fail(key, "timeout", code="normalize_timeout")
            else:
                waiting.append(key)
        if waiting:
            raise LocalSourceNormalizing(
                f"{len(waiting)} source(s) of the local video are being normalized"
            )

    def fetch(self, key: str, path: Path) -> None:
        """One video stretch's file to `path`: its normalized copy when there is one; else
        the file itself, its header checked (once per file). Raises
        `LocalSourceNormalizing` after asking for the copies the part needs."""
        job = self._ready.get(key)
        if job is not None:
            self.fetch_file(job.normalized_key, path)
            return
        self.fetch_file(key, path)
        if key not in self.keys or key in self._checked:
            return
        head = self.header(path)
        self._checked[key] = head
        if not head.needs_normalizing():
            return
        path.unlink(missing_ok=True)  # never decoded here
        self._enqueue(key, head)
        self._check_the_rest(path.with_name(path.name + "-header"))
        raise LocalSourceNormalizing("a source of the local video is over 4K 8 bits")

    def _check_the_rest(self, scratch: Path) -> None:
        """The part's other files nobody has checked yet: header only (nothing decoded),
        so every copy the part needs is asked for in the same pass. Each file is still
        downloaded WHOLE to read it — the store has no ranged read here, and a phone's
        MP4/MOV may keep its header (`moov`) at the end — then deleted at once; this
        happens on the first pass only (later passes find the jobs)."""
        for key in self.keys:
            if key in self._checked or key in self._ready:
                continue
            try:
                self.fetch_file(key, scratch)
                head = self.header(scratch)
            finally:
                scratch.unlink(missing_ok=True)
            self._checked[key] = head
            if head.needs_normalizing():
                self._enqueue(key, head)

    def _enqueue(self, key: str, head: SourceHeader) -> None:
        self.jobs.enqueue(self.tenant_id, key, draft_id=self.draft_id, brand_id=self.brand_id)
        logger.info(
            "creative.local_source.normalize_enqueued tenant=%s width=%d height=%d pix_fmt=%s",
            self.tenant_id,
            head.width,
            head.height,
            head.pix_fmt or "unknown",
        )

    def provenance(self, key: str) -> dict[str, Any] | None:
        """What a video stretch's asset records about its file: the original key, the
        normalized copy's key and the normalizer's version — or, read as it is, the
        check's version and the header it passed. None for a file not checked here."""
        job = self._ready.get(key)
        if job is not None:
            return {
                "source_key": key,
                "normalized_key": job.normalized_key,
                "normalizer_version": job.version,
                "limits_version": SOURCE_LIMITS_VERSION,
            }
        head = self._checked.get(key)
        if head is None:
            return None
        return {
            "source_key": key,
            "normalized_key": None,
            "normalizer_version": None,
            "limits_version": SOURCE_LIMITS_VERSION,
            "header": head.to_dict(),
        }


def _fail(key: str, reason: str | None, *, code: str = "normalize_failed") -> None:
    from qualify_api.creative.video_pipeline.local import (  # noqa: PLC0415
        LOCAL_SOURCE_FAILED_TEXT,
        LocalVideoFailed,
    )

    raise LocalVideoFailed(
        FailureReason.INVALID_PARAMETERS.value,
        LOCAL_SOURCE_FAILED_TEXT,
        raw=f"normalize_local {reason or 'unknown'}",
        code=code,
    )


def with_provenance(segments: Iterable[Any], sources: LocalSources | None) -> list[dict[str, Any]]:
    """The recipe's stretches as the asset records them, each video stretch with its
    file's `source` provenance when it was checked here."""
    out: list[dict[str, Any]] = []
    for segment in segments:
        data = segment.model_dump(mode="json")
        source = sources.provenance(segment.key) if sources is not None else None
        if segment.kind == "video" and source is not None:
            data["source"] = source
        out.append(data)
    return out


__all__ = [
    "JOB_KIND",
    "MAX_NORMALIZE_WAIT",
    "MAX_TRANSIENT_FAILURES",
    "PERMANENT_FAILURES",
    "InMemoryLocalSourceJobs",
    "LocalSourceJobs",
    "LocalSourceNormalizing",
    "LocalSources",
    "NormalizeJob",
    "PostgresLocalSourceJobs",
    "default_jobs",
    "needs_check",
    "normalize_job_key",
    "normalized_key",
    "with_provenance",
]
