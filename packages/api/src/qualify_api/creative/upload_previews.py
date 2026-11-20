"""The light 480p copy of a video the owner uploads to the generator (ED-09, m-25026643;
ADR 50 D-E2) — the door the screens use: ask for it right after the upload, read where it
is when the editor opens again.

1. `request_preview` (right after `save_upload` returned the video's key): ONE
   `upload_preview` job in `gallery_jobs` (migration 0175), `INSERT … ON CONFLICT DO
   NOTHING` on `uq_gallery_jobs_upload_preview` — asking twice, or a retried upload
   handler, never makes a second copy. A file whose earlier job failed for a reason of
   the FILE (unreadable, missing) is not asked again; one whose jobs failed for a reason
   of the MACHINE is re-queued up to `MAX_TRANSIENT_FAILURES` times.
2. The `media-worker` makes it (`qualify_creative.video.upload_preview`: whole length,
   upright, short side ≤ 480, silent, 8-bit H.264) and writes it ONCE to its deterministic
   key `t/{tenant}/uploads/previews/{uuid5(version:source)}/video.mp4`, then marks the job
   `done` with the key, the version, both headers, the size and `cost_usd = 0.00`
   (provenance).
3. `previews_for` / `preview_play_key` (when the editor shows the video again): the copy's
   key once its job is `done`, else the original's — the screen never waits for the copy.
   Only for SHOWING: the copy is silent and 480p, never a source of a piece.

**Where the copy lives.** Next to the original, under the tenant's own
`t/{tenant}/uploads/`, so `/_upload/<key>` (`Qualify/upload_route.py`) serves it exactly
as it serves the original — no new exposure: a key nobody can guess without the
original's own `uuid4` key — and it shares the original's fate in the bucket (`t/` is
write-once: neither is deleted by the app; ADR 39's retention covers both alike). Its
job row goes with the business (`gallery_jobs.brand_id` ON DELETE CASCADE).

**Tenancy.** Every key is checked with `owned_by` before anything is queued or returned:
a key of another business is refused, never looked up. The jobs are read and written
through `tenant_session` (`qualify_app`, RLS: this tenant's rows only).

**ED-11b (m-25029110, the frame strip).** It wants to read the video once with this copy:
it will be a second output of the same job (a new `UPLOAD_PREVIEW_VERSION`, a new key in
the payload and the result), not a second job that downloads and decodes the file again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid5

from qualify_creative.video.upload_preview import UPLOAD_PREVIEW_VERSION

JOB_KIND = "upload_preview"
#: The namespace of the copies' folder ids (`uuid5(namespace, version:source)`).
PREVIEW_NAMESPACE = UUID("8e1d6a43-2f6b-4b6e-9c51-25026643e009")
PREVIEW_FOLDER = "previews"
PREVIEW_FILE = "video.mp4"
#: A job's failure that is the FILE's: asking again cannot help.
PERMANENT_FAILURES = frozenset(
    {
        "unreadable",
        "source_missing",
        "preview_over_limit",
        "preview_too_large",
        "preview_timeout",
        "payload_invalid",
    }
)
#: Failed jobs of the MACHINE's (attempts exhausted, killed, R2, a deploy) a file may have
#: before it is not queued again (the editor keeps playing the original).
MAX_TRANSIENT_FAILURES = 2

STATUS_NONE = "none"


class NotPreviewable(ValueError):
    """The key is not one of this tenant's uploaded videos: nothing is queued."""


def preview_job_key(source_key: str, version: str = UPLOAD_PREVIEW_VERSION) -> str:
    """The job's idempotency key: one copy per file and previewer version."""
    return f"{JOB_KIND}:{version}:{source_key}"


def preview_key(tenant_id: UUID, source_key: str, version: str = UPLOAD_PREVIEW_VERSION) -> str:
    """The deterministic key of `source_key`'s 480p copy, under the tenant's uploads."""
    folder = uuid5(PREVIEW_NAMESPACE, f"{version}:{source_key}")
    return f"t/{tenant_id}/uploads/{PREVIEW_FOLDER}/{folder}/{PREVIEW_FILE}"


def preview_root(tenant_id: UUID) -> str:
    """Where every copy of this tenant lives — the worker refuses to write anywhere else."""
    return f"t/{tenant_id}/uploads/{PREVIEW_FOLDER}/"


def is_previewable(tenant_id: UUID, source_key: str) -> bool:
    """Whether `source_key` is a video this tenant uploaded to the generator: its own
    upload (`t/{tenant}/uploads/…`, or an old local `uploads/{tenant}/…` the worker reads
    through the CM-9 key map), a video by its name, and not itself a copy."""
    from qualify_creative.video import is_video_filename  # noqa: PLC0415

    from qualify_api.creative.media import owned_by  # noqa: PLC0415

    if not owned_by(tenant_id, source_key) or not is_video_filename(source_key):
        return False
    if source_key.startswith(preview_root(tenant_id)):
        return False
    return source_key.startswith((f"t/{tenant_id}/uploads/", f"uploads/{tenant_id}/"))


@dataclass(frozen=True)
class UploadPreview:
    """The 480p copy of one uploaded video, as the screens read it."""

    source_key: str
    #: none (never asked) | queued | running | done | failed
    status: str
    #: The copy's key — readable only when `status == "done"`.
    preview_key: str
    version: str = UPLOAD_PREVIEW_VERSION
    error_code: str | None = None
    created_at: datetime | None = None
    #: How many of this file's jobs (this one included) failed for a reason of the machine.
    transient_failures: int = 0
    #: The ORIGINAL's size as it is shown (upright: a 90/270 turn swaps them), from the
    #: done job's `result["source"]` header; 0 when unknown. The editor judges «Cortar»
    #: with these while it shows the 480p copy, never with the copy's own size.
    source_width: int = 0
    source_height: int = 0

    @property
    def ready(self) -> bool:
        return self.status == "done"

    @property
    def failed_for_good(self) -> bool:
        return self.status == "failed" and (
            (self.error_code or "") in PERMANENT_FAILURES
            or self.transient_failures >= MAX_TRANSIENT_FAILURES
        )

    @property
    def preview_play_key(self) -> str:
        """What the editor's preview plays: the copy once it is made, else the original.
        Only to SHOW the video: the copy is silent and 480p, so it is never a source of a
        piece (the assembly always reads `source_key`)."""
        return self.preview_key if self.ready else self.source_key


def upright_size(header: object) -> tuple[int, int]:
    """`(width, height)` of a stored header (`{"width", "height", "rotation"}`) as the
    video is shown: a 90° or 270° turn swaps them. `(0, 0)` for anything unreadable."""
    if not isinstance(header, dict):
        return 0, 0
    try:
        width, height = int(header.get("width") or 0), int(header.get("height") or 0)
        rotation = int(header.get("rotation") or 0)
    except (TypeError, ValueError):
        return 0, 0
    if width < 1 or height < 1:
        return 0, 0
    if rotation % 180 in (90, -90):
        width, height = height, width
    return width, height


def is_transient(status: str, error_code: str | None) -> bool:
    """A failed job whose failure was the machine's, not the file's."""
    return status == "failed" and (error_code or "") not in PERMANENT_FAILURES


def previews_for(tenant_id: UUID, source_keys: Sequence[str]) -> dict[str, UploadPreview]:
    """The copy of each of `source_keys` (ONE query); a key that is not this tenant's
    uploaded video is left out, one never asked for is `status="none"`."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.catalog.business_media_models import GalleryJob  # noqa: PLC0415

    keys = [key for key in dict.fromkeys(source_keys) if is_previewable(tenant_id, key)]
    if not keys:
        return {}
    by_job_key = {preview_job_key(key): key for key in keys}
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
            .where(GalleryJob.kind == JOB_KIND, GalleryJob.idempotency_key.in_(list(by_job_key)))
            # the newest first: a failed job is superseded by a later one
            .order_by(GalleryJob.created_at.desc(), GalleryJob.id)
        ).all()
    return _fold(tenant_id, keys, by_job_key, rows)


def _fold(
    tenant_id: UUID, keys: Sequence[str], by_job_key: dict[str, str], rows: Sequence[object]
) -> dict[str, UploadPreview]:
    found: dict[str, UploadPreview] = {}
    transient: dict[str, int] = {}
    for row in rows:
        source = by_job_key[row.idempotency_key]  # type: ignore[attr-defined]
        status = str(row.status)  # type: ignore[attr-defined]
        code = row.last_error_code  # type: ignore[attr-defined]
        if is_transient(status, code):
            transient[source] = transient.get(source, 0) + 1
        if source in found:
            continue
        result = row.result or {}  # type: ignore[attr-defined]
        payload = row.payload or {}  # type: ignore[attr-defined]
        target = str(
            result.get("preview_key")
            or payload.get("preview_key")
            or preview_key(tenant_id, source)
        )
        # defence in depth over the payload CHECK: never hand out a key outside the
        # tenant's own copies
        if not target.startswith(preview_root(tenant_id)) or ".." in target:
            target = preview_key(tenant_id, source)
        width, height = upright_size(result.get("source"))
        found[source] = UploadPreview(
            source_key=source,
            status=status,
            preview_key=target,
            version=str(result.get("version") or row.pipeline_version),  # type: ignore[attr-defined]
            error_code=code,
            created_at=row.created_at,  # type: ignore[attr-defined]
            source_width=width,
            source_height=height,
        )
    out: dict[str, UploadPreview] = {}
    for key in keys:
        preview = found.get(key)
        if preview is None:
            out[key] = UploadPreview(
                source_key=key, status=STATUS_NONE, preview_key=preview_key(tenant_id, key)
            )
        else:
            out[key] = replace(preview, transient_failures=transient.get(key, 0))
    return out


def preview_play_key(tenant_id: UUID, source_key: str) -> str:
    """What the editor's preview plays for `source_key`: its 480p copy once made, else the
    original itself (also for a key that is not an uploaded video — the caller's own check
    stands). Only to SHOW it: the copy has no sound and is 480p, so it is never handed to
    the assembly, the brief or a vendor — those always take `source_key`."""
    preview = previews_for(tenant_id, [source_key]).get(source_key)
    return preview.preview_play_key if preview is not None else source_key


def request_preview(tenant_id: UUID, brand_id: UUID, source_key: str) -> UploadPreview:
    """Queue the 480p copy of an uploaded video — or nothing, when one that did not fail
    already holds its key (`uq_gallery_jobs_upload_preview`), when it is already made, or
    when its earlier jobs failed for good. Returns the copy's state after the call. Raises
    `NotPreviewable` for a key that is not this tenant's uploaded video."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

    from qualify_api.catalog.business_media_models import GalleryJob  # noqa: PLC0415

    if not is_previewable(tenant_id, source_key):
        raise NotPreviewable(source_key)
    current = previews_for(tenant_id, [source_key])[source_key]
    if current.status in ("queued", "running", "done") or current.failed_for_good:
        return current
    with tenant_session(tenant_id) as session:
        session.execute(
            insert(GalleryJob)
            .values(
                tenant_id=tenant_id,
                brand_id=brand_id,
                kind=JOB_KIND,
                idempotency_key=preview_job_key(source_key),
                pipeline_version=UPLOAD_PREVIEW_VERSION,
                payload={
                    "source_key": source_key,
                    "preview_key": preview_key(tenant_id, source_key),
                    "version": UPLOAD_PREVIEW_VERSION,
                },
            )
            .on_conflict_do_nothing()
        )
    return previews_for(tenant_id, [source_key])[source_key]


__all__ = [
    "JOB_KIND",
    "MAX_TRANSIENT_FAILURES",
    "PERMANENT_FAILURES",
    "NotPreviewable",
    "UploadPreview",
    "is_previewable",
    "preview_play_key",
    "preview_job_key",
    "preview_key",
    "preview_root",
    "previews_for",
    "request_preview",
    "upright_size",
]
