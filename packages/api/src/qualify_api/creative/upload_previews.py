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

**The frame strip (ED-11b, m-25029110; ADR 50 D-E1, D-T4).** The editor's timeline shows
one real frame a second of the video, made by the server. It is a second output of the
SAME job (`UPLOAD_PREVIEW_VERSION` v2: the payload and the result gain `strip_key`,
`t/{tenant}/uploads/previews/{uuid5(v2:source)}/strip.jpg`, next to the copy), so the
original is read and decoded once for both; the result's `strip` says where each second's
tile sits (`FrameStrip`). It arrives after the first frame: nothing waits for it.

**Copies made before the strip (v1).** They are not lost nor made again: `previews_for`
still finds a done v1 copy and the editor keeps playing it. Its strip is asked for apart:
`request_preview` on such a video queues ONE v2 job whose `preview_key` is the v1 copy's
own key — the worker finds the copy in place and decodes the original for the strip alone
(no second 480p encode). `UploadPreview.strip_wanted` tells the screen when to ask.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from qualify_creative.video.upload_preview import EARLIER_VERSIONS, UPLOAD_PREVIEW_VERSION

JOB_KIND = "upload_preview"
#: The namespace of the copies' folder ids (`uuid5(namespace, version:source)`).
PREVIEW_NAMESPACE = UUID("8e1d6a43-2f6b-4b6e-9c51-25026643e009")
PREVIEW_FOLDER = "previews"
PREVIEW_FILE = "video.mp4"
STRIP_FILE = "strip.jpg"
#: Every version whose copy is still read, newest first.
READ_VERSIONS: tuple[str, ...] = (UPLOAD_PREVIEW_VERSION, *EARLIER_VERSIONS)
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
#: A v2 job that a worker of another version settled (it made the copy, not the strip):
#: marked failed with this code when its strip is asked for again. Neither the file's
#: fault nor the machine's: it never counts towards `MAX_TRANSIENT_FAILURES`.
STALE_VERSION = "stale_version"


class NotPreviewable(ValueError):
    """The key is not one of this tenant's uploaded videos: nothing is queued."""


def preview_job_key(source_key: str, version: str = UPLOAD_PREVIEW_VERSION) -> str:
    """The job's idempotency key: one copy per file and previewer version."""
    return f"{JOB_KIND}:{version}:{source_key}"


def preview_key(tenant_id: UUID, source_key: str, version: str = UPLOAD_PREVIEW_VERSION) -> str:
    """The deterministic key of `source_key`'s 480p copy, under the tenant's uploads."""
    folder = uuid5(PREVIEW_NAMESPACE, f"{version}:{source_key}")
    return f"t/{tenant_id}/uploads/{PREVIEW_FOLDER}/{folder}/{PREVIEW_FILE}"


def strip_key(tenant_id: UUID, source_key: str, version: str = UPLOAD_PREVIEW_VERSION) -> str:
    """The deterministic key of `source_key`'s frame strip, in its copy's folder."""
    folder = uuid5(PREVIEW_NAMESPACE, f"{version}:{source_key}")
    return f"t/{tenant_id}/uploads/{PREVIEW_FOLDER}/{folder}/{STRIP_FILE}"


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
class FrameStrip:
    """The frame strip of one uploaded video (ED-11b), as the editor's timeline reads it:
    ONE JPEG at `key`, tiles of `tile_width`×`tile_height` px in a grid of `columns` ×
    `rows`. Tile `i` (0 ≤ i < `frames`) is at x = `(i % columns) * tile_width`,
    y = `(i // columns) * tile_height`, and shows the video at second
    `i * interval_s + offset_s` — the middle of the ruler's second `[i, i+1)`."""

    key: str
    frames: int
    columns: int
    rows: int
    tile_width: int
    tile_height: int
    interval_s: int = 1
    offset_s: float = 0.5

    @classmethod
    def from_result(cls, key: str, facts: object) -> FrameStrip | None:
        """The strip a done job's `result["strip"]` describes; None when it is missing or
        does not add up (the timeline then shows no frames, never wrong ones)."""
        if not isinstance(facts, dict):
            return None
        try:
            strip = cls(
                key=key,
                frames=int(facts["frames"]),
                columns=int(facts["columns"]),
                rows=int(facts["rows"]),
                tile_width=int(facts["tile_width"]),
                tile_height=int(facts["tile_height"]),
                interval_s=int(facts.get("interval_s") or 1),
                offset_s=float(facts.get("offset_s", 0.5)),
            )
        except (KeyError, TypeError, ValueError):
            return None
        sane = (
            strip.frames > 0
            and 0 < strip.columns <= strip.frames
            and strip.rows * strip.columns >= strip.frames
            and strip.tile_width > 0
            and strip.tile_height > 0
            and strip.interval_s > 0
        )
        return strip if sane else None


@dataclass(frozen=True)
class UploadPreview:
    """The 480p copy of one uploaded video, and its frame strip, as the screens read it."""

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
    #: ED-11b: the frame strip, once made (None until then, and for a video with none).
    strip: FrameStrip | None = None
    #: The state of the job that makes the strip (a job of `UPLOAD_PREVIEW_VERSION`):
    #: none | queued | running | done | failed. A v1 copy has a copy and `none` here.
    strip_status: str = STATUS_NONE
    strip_error_code: str | None = None

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
    def strip_key(self) -> str:
        """The strip's key, or "" while there is none to show."""
        return self.strip.key if self.strip is not None else ""

    @property
    def strip_failed_for_good(self) -> bool:
        return self.strip_status == "failed" and (
            (self.strip_error_code or "") in PERMANENT_FAILURES
            or self.transient_failures >= MAX_TRANSIENT_FAILURES
        )

    @property
    def strip_wanted(self) -> bool:
        """The copy is made but its strip was never asked for (a v1 copy) or its last
        failure is worth a retry: `request_preview` queues the strip alone."""
        if not self.ready or self.strip is not None:
            return False
        if self.strip_status == STATUS_NONE:
            return True
        return self.strip_status == "failed" and not self.strip_failed_for_good

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
    return (
        status == "failed"
        and (error_code or "") not in PERMANENT_FAILURES
        and error_code != STALE_VERSION
    )


def previews_for(tenant_id: UUID, source_keys: Sequence[str]) -> dict[str, UploadPreview]:
    """The copy of each of `source_keys` (ONE query); a key that is not this tenant's
    uploaded video is left out, one never asked for is `status="none"`."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.catalog.business_media_models import GalleryJob  # noqa: PLC0415

    keys = [key for key in dict.fromkeys(source_keys) if is_previewable(tenant_id, key)]
    if not keys:
        return {}
    by_job_key = {
        preview_job_key(key, version): (key, version) for key in keys for version in READ_VERSIONS
    }
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


def _own_key(tenant_id: UUID, key: object, fallback: str) -> str:
    """`key` when it is one of the tenant's own copies (defence in depth over the payload
    CHECK and the worker's: never hand out a key outside them), else `fallback`."""
    text = str(key or "")
    if not text.startswith(preview_root(tenant_id)) or ".." in text:
        return fallback
    return text


def _fold(
    tenant_id: UUID,
    keys: Sequence[str],
    by_job_key: dict[str, tuple[str, str]],
    rows: Sequence[object],
) -> dict[str, UploadPreview]:
    """Per video, from its jobs of every read version (newest first): the COPY is the
    newest job that made one (a v2 job, or a v1 copy that keeps playing while its strip is
    made), else the newest job's state; the STRIP is the current version's newest job's.

    A v2 job settled by a worker of another version (`_settled_elsewhere`: the deploy's
    race, an old media-worker that took a v2 job and made the copy alone) made the copy
    but no strip: its strip counts as failed (`STALE_VERSION`), so it is asked for again
    — `request_preview` frees that job's key first."""
    current: dict[str, object] = {}
    copies: dict[str, object] = {}
    newest: dict[str, object] = {}
    transient: dict[str, int] = {}
    for row in rows:
        source, version = by_job_key[row.idempotency_key]  # type: ignore[attr-defined]
        status = str(row.status)  # type: ignore[attr-defined]
        if is_transient(status, row.last_error_code):  # type: ignore[attr-defined]
            transient[source] = transient.get(source, 0) + 1
        newest.setdefault(source, row)
        if version == UPLOAD_PREVIEW_VERSION:
            current.setdefault(source, row)
        if _made_copy(row):
            copies.setdefault(source, row)
    out: dict[str, UploadPreview] = {}
    for key in keys:
        cur = current.get(key)
        copy_row = copies.get(key) or cur or newest.get(key)
        if copy_row is None:
            out[key] = UploadPreview(
                source_key=key, status=STATUS_NONE, preview_key=preview_key(tenant_id, key)
            )
            continue
        has_copy = _made_copy(copy_row)
        result = copy_row.result or {}  # type: ignore[attr-defined]
        payload = copy_row.payload or {}  # type: ignore[attr-defined]
        width, height = upright_size(result.get("source"))
        strip = None
        strip_status = STATUS_NONE
        strip_code = None
        if cur is not None:
            strip_status = str(cur.status)  # type: ignore[attr-defined]
            strip_code = cur.last_error_code  # type: ignore[attr-defined]
            if _settled_elsewhere(cur):
                strip_status, strip_code = "failed", STALE_VERSION
            elif strip_status == "done":
                cur_result = cur.result or {}  # type: ignore[attr-defined]
                made = _own_key(tenant_id, cur_result.get("strip_key"), "")
                strip = FrameStrip.from_result(made, cur_result.get("strip")) if made else None
        out[key] = UploadPreview(
            source_key=key,
            status="done" if has_copy else str(copy_row.status),  # type: ignore[attr-defined]
            preview_key=_own_key(
                tenant_id,
                result.get("preview_key") or payload.get("preview_key"),
                preview_key(tenant_id, key),
            ),
            version=str(result.get("version") or copy_row.pipeline_version),  # type: ignore[attr-defined]
            error_code=None if has_copy else copy_row.last_error_code,  # type: ignore[attr-defined]
            created_at=copy_row.created_at,  # type: ignore[attr-defined]
            transient_failures=transient.get(key, 0),
            source_width=width,
            source_height=height,
            strip=strip,
            strip_status=strip_status,
            strip_error_code=strip_code,
        )
    return out


def _settled_elsewhere(row: object) -> bool:
    """A `done` job of the current version whose result names ANOTHER version: settled by
    a worker that did not know the strip (it made the copy alone)."""
    if str(row.pipeline_version) != UPLOAD_PREVIEW_VERSION:  # type: ignore[attr-defined]
        return False
    if str(row.status) != "done":  # type: ignore[attr-defined]
        return False
    made = (row.result or {}).get("version")  # type: ignore[attr-defined]
    return made is not None and str(made) != UPLOAD_PREVIEW_VERSION


def _made_copy(row: object) -> bool:
    """The job left a copy in place: done, or a stale v2 job whose key was freed."""
    status = str(row.status)  # type: ignore[attr-defined]
    return status == "done" or (
        status == "failed" and row.last_error_code == STALE_VERSION  # type: ignore[attr-defined]
    )


def preview_play_key(tenant_id: UUID, source_key: str) -> str:
    """What the editor's preview plays for `source_key`: its 480p copy once made, else the
    original itself (also for a key that is not an uploaded video — the caller's own check
    stands). Only to SHOW it: the copy has no sound and is 480p, so it is never handed to
    the assembly, the brief or a vendor — those always take `source_key`."""
    preview = previews_for(tenant_id, [source_key]).get(source_key)
    return preview.preview_play_key if preview is not None else source_key


def request_preview(tenant_id: UUID, brand_id: UUID, source_key: str) -> UploadPreview:
    """Queue the 480p copy of an uploaded video and its frame strip (one job, one decode)
    — or, for a copy made before the strip (v1), the strip alone (a v2 job that reuses
    that copy's key) — or nothing, when a job that did not fail already holds the key
    (`uq_gallery_jobs_upload_preview`), when both are made, when a copy is on its way, or
    when the earlier jobs failed for good. Returns the state after the call. Raises
    `NotPreviewable` for a key that is not this tenant's uploaded video."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import func, update  # noqa: PLC0415
    from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

    from qualify_api.catalog.business_media_models import GalleryJob  # noqa: PLC0415

    if not is_previewable(tenant_id, source_key):
        raise NotPreviewable(source_key)
    current = previews_for(tenant_id, [source_key])[source_key]
    if current.ready:
        if not current.strip_wanted:
            return current
        copy_key = current.preview_key  # kept: the worker makes the strip alone
    elif current.status in ("queued", "running") or current.failed_for_good:
        return current
    else:
        copy_key = preview_key(tenant_id, source_key)
    with tenant_session(tenant_id) as session:
        if current.strip_error_code == STALE_VERSION:
            # a v2 job settled by an old worker holds the key (`done`): mark it failed —
            # its copy stays in place and counted (`_made_copy`) — so the strip can be
            # queued; never touches a job that made its strip (its result is v2)
            session.execute(
                update(GalleryJob)
                .where(
                    GalleryJob.kind == JOB_KIND,
                    GalleryJob.idempotency_key == preview_job_key(source_key),
                    GalleryJob.status == "done",
                    GalleryJob.result["version"].astext != UPLOAD_PREVIEW_VERSION,
                )
                .values(
                    status="failed",
                    last_error_code=STALE_VERSION,
                    updated_at=func.now(),
                )
            )
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
                    "preview_key": copy_key,
                    "strip_key": strip_key(tenant_id, source_key),
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
    "READ_VERSIONS",
    "STALE_VERSION",
    "FrameStrip",
    "NotPreviewable",
    "UploadPreview",
    "is_previewable",
    "preview_play_key",
    "preview_job_key",
    "preview_key",
    "preview_root",
    "previews_for",
    "request_preview",
    "strip_key",
    "upright_size",
]
