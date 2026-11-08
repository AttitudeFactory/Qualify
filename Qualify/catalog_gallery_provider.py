"""The seam between «Fotos y videos de tu negocio» and the Galería service (CM-2,
m-24955919; backend CM-1, m-24955918, ADR 47).

Thin, by design: every rule (R2 under `gallery/{tenant}/{id}/`, the 60-media and
3-waiting limits, idempotency, «Quitar» = tombstone → delete the folder → delete the row,
videos prepared in `media-worker`) lives in `qualify_api.catalog.business_media`. This
module only wires the production service and turns its records into
`catalog_gallery_vm` shapes, minting the short-lived `/r2media/<token>` path of each
thumbnail and video under the viewing tenant's own prefix (`r2_media.issue_view_path`).

The upload is the service's own `add_business_media`, taken apart so nothing blocking
runs on the event loop: the limits (`free_places`, a DB read) and each saved file
(`add_staged`: a photo is normalized with Pillow and PUT to R2) go to a thread; only
`stage_chunks` — which writes the chunks to the waiting room as they arrive — stays on
the loop, because it consumes Reflex's `UploadChunkIterator` there.

Blocking functions are marked; callers on the event loop run them with
`asyncio.to_thread`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from dataclasses import dataclass
from functools import cache
from uuid import UUID

from qualify_api.catalog.business_media import (
    BusinessMediaService,
    CutSpan,
    production_business_media_service,
)
from qualify_api.catalog.business_media_models import ACTIVE_STATUSES, JOB_CUT
from qualify_api.catalog.business_media_staging import (
    ChunkLike,
    StagedFile,
    discard_staged,
    stage_chunks,
)
from qualify_api.catalog.service import CatalogError
from qualify_api.creative.composition import media_root

from .catalog_gallery_vm import (
    CutCardVM,
    GalleryItemVM,
    OutcomeRow,
    build_cut_cards,
    build_gallery_items,
    retry_spans,
    trimmed_job_ids,
    videos_waiting,
)
from .r2_media import issue_view_path

logger = logging.getLogger(__name__)

__all__ = [
    "CatalogError",
    "GallerySnapshot",
    "add_staged",
    "check_upload",
    "discard_staged_files",
    "dismiss_job",
    "free_places",
    "load_gallery",
    "remove_media",
    "retry_cut",
    "start_cut",
    "stage_upload",
]


@cache
def _service() -> BusinessMediaService:
    """One per process: R2 through `ObjectGate`, the waiting room on `media_root()`."""
    return production_business_media_service()


@dataclass(frozen=True)
class GallerySnapshot:
    items: tuple[GalleryItemVM, ...]
    #: Active `ingest` jobs (0..3): the «3 waiting» rule, and whether to keep watching.
    waiting: int
    #: A cut is running too (CM-3): keep watching until it ends.
    busy: bool
    #: Finished uploads over a minute long, for «guardamos solo el primero».
    trimmed_ids: tuple[str, ...] = ()
    #: CM-4: the cuts of the last day — (job id, status, number of parts saved).
    cuts: tuple[tuple[str, str, int], ...] = ()
    #: m-24976806: the same cuts as cards (newest first); the state picks which show.
    cut_cards: tuple[CutCardVM, ...] = ()
    #: A cut is queued, running or saving: the section re-reads a little more often.
    cutting: bool = False


def _url_for(tenant_id: UUID):
    def mint(key: str, kind: str) -> str:
        try:
            return issue_view_path(tenant_id, key, kind)
        except Exception as exc:  # noqa: BLE001 — a thumbnail is not worth the section
            logger.warning("gallery view token not issued: %s", type(exc).__name__)
            return ""

    return mint


def load_gallery(tenant_id: UUID, brand_id: UUID) -> GallerySnapshot:
    """Blocking (DB + Redis): the section as the service has it now."""
    service = _service()
    media = service.list_business_media(tenant_id=tenant_id, brand_id=brand_id)
    jobs = service.list_gallery_jobs(tenant_id=tenant_id, brand_id=brand_id)
    cuts = service.list_cut_jobs(tenant_id=tenant_id, brand_id=brand_id)
    mint = _url_for(tenant_id)
    items = build_gallery_items(media, jobs, mint)
    waiting = videos_waiting(jobs)
    cutting = any(j.status in ACTIVE_STATUSES for j in cuts)
    return GallerySnapshot(
        items=tuple(items),
        waiting=waiting,
        # keep watching while anything is pending — a cut whose parts are already saved
        # (the original gone from the tiles) is still running until it is `done`
        busy=waiting > 0 or cutting,
        trimmed_ids=tuple(trimmed_job_ids(jobs)),
        cuts=tuple((str(j.id), j.status, len(j.part_ids)) for j in cuts),
        cut_cards=tuple(build_cut_cards(cuts, media, mint)),
        cutting=cutting,
    )


def check_upload(tenant_id: UUID, brand_id: UUID, videos: int) -> None:
    """Blocking (DB): BEFORE any byte is accepted — `CatalogError` with the owner's
    sentence when the Galería is full or 3 videos are already being prepared."""
    _service().check_can_upload(tenant_id=tenant_id, brand_id=brand_id, videos=videos)


def free_places(tenant_id: UUID, brand_id: UUID) -> tuple[int, int]:
    """Blocking (DB): (videos that may still wait, media the Galería still holds)."""
    return _service().free_places(tenant_id=tenant_id, brand_id=brand_id)


async def stage_upload(
    chunks: AsyncIterable[ChunkLike], tenant_id: UUID, *, max_videos: int, max_files: int
) -> list[StagedFile]:
    """The chunks to the waiting room, 1 MiB at a time, cut past 500 MB. A failure
    mid-stream deletes what it wrote and re-raises (`stage_chunks`)."""
    return await stage_chunks(
        chunks,
        root=media_root(),
        tenant_id=tenant_id,
        max_videos=max_videos,
        max_files=max_files,
    )


def add_staged(tenant_id: UUID, brand_id: UUID, staged: StagedFile) -> OutcomeRow:
    """Blocking (DB, Pillow, R2): a photo saved, a video queued for `media-worker`, or the
    service's refusal in its own words. Never raises a `CatalogError`."""
    outcome = _service().add_staged(tenant_id=tenant_id, brand_id=brand_id, staged=staged)
    return OutcomeRow(
        filename=outcome.filename,
        error_text=outcome.error_text,
        duplicate=outcome.duplicate,
        is_video=staged.is_video,
    )


def discard_staged_files(tenant_id: UUID, staged: list[StagedFile]) -> None:
    """Blocking (disk): the staged files an interrupted upload never handed to
    `add_staged` (the daily reconciler would delete them after 24 h anyway)."""
    for item in staged:
        if item.relpath:
            discard_staged(media_root(), tenant_id, item.relpath)


def remove_media(tenant_id: UUID, media_id: UUID) -> None:
    """Blocking (DB + R2): «Quitar». `CatalogError` while the video is being cut."""
    _service().remove_business_media(tenant_id=tenant_id, media_id=media_id)


def start_cut(tenant_id: UUID, media_id: UUID, spans: list[CutSpan]) -> str:
    """Blocking (DB): «Guardar» (CM-4) — queue ONE `cut` job for media-worker and return
    its id. `CatalogError` with the owner's sentence (a part under 3 s, none kept, a cut
    already running, the Galería full); `UnknownBusinessMedia` (a `KeyError`) for a
    video that is gone."""
    job = _service().start_cut(tenant_id=tenant_id, media_id=media_id, spans=spans)
    return str(job.id)


def retry_cut(tenant_id: UUID, job_id: UUID) -> str:
    """Blocking (DB): «Intentar de nuevo» on a failed cut (m-24976806) — the same kept
    spans of the same video, queued again as a new job (the failed one is not active,
    so the service lets it). `KeyError` when the job or the video is gone;
    `CatalogError` with the owner's sentence otherwise (as `start_cut`)."""
    service = _service()
    job = service.get_gallery_job(tenant_id=tenant_id, job_id=job_id)
    if job.kind != JOB_CUT or job.source_media_id is None or not job.segments:
        raise KeyError(str(job_id))
    spans = [
        CutSpan(start_ms, end_ms, keep)
        for start_ms, end_ms, keep in retry_spans(job.segments, job.source_duration_ms)
    ]
    return start_cut(tenant_id, job.source_media_id, spans)


def dismiss_job(tenant_id: UUID, job_id: UUID) -> None:
    """Blocking (DB): «Quitar» on a video that failed, or «Entendido» on a finished one.
    An active job raises `UnknownBusinessMedia` (a `KeyError`)."""
    _service().dismiss_gallery_job(tenant_id=tenant_id, job_id=job_id)
