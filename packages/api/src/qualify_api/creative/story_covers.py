"""The automatic cover of a historia's video (m-25142900, epic m-25130273 N1).

A story ad of a video sends Meta the video AND a 9:16 image as its thumbnail
(`ads.unpublished.video_creative_payload`: `video_data.image_hash`). A historia that is only
a 9:16 MP4 had no such image and was blocked (`StoryBlock.VIDEO_WITHOUT_COVER`). Here the
creative-worker takes ONE frame of that video (`qualify_creative.video.still`: ffmpeg, a
keyframe seek 1 s in, upright, full size) and keeps it as the cover:

- **When:** every maintenance pass of the creative-worker (`cover_chore`, once a minute,
  at most `PER_PASS` covers), for every approved historia whose current version has a
  9:16 MP4, no 9:16 image and no cover yet. One path makes the covers of new approvals
  (within about a minute) and of the historias approved before this existed. Never in the
  web process (a page load or an approval would download the video) and never at
  readiness time (the gallery checks many pieces at once).
- **Where:** `piece_story_covers` (0191), not `image_assets`: no reader of a piece's
  files sees the cover. Only the story ad's readers add it, through `PIECE_FILES`.
- **Idempotent:** one cover per video file (`UNIQUE (tenant_id, source_asset_id)`,
  `ON CONFLICT DO NOTHING`); the object key is derived from the video's row and written
  once (`t/` refuses overwrites). A failed R2 read or write leaves nothing and the next
  pass tries again; a video that gives no frame is recorded `failed` and not retried.
- **Provenance:** the source video's row, `COVER_VERSION`; no model, vendor or cost.
- **Tenancy:** each business's work goes through `tenant_session`; `admin_session` only
  lists which businesses have work (ids only, like `vendor_recovery.discover_tenants`).
- **Retention (ADR 39):** the object sits next to its video, so the piece's purge removes
  both; a purged piece is never a candidate and never a story ad.
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectNotFound
from sqlalchemy import text

logger = logging.getLogger(__name__)

#: Which frame, how it is shaped and encoded — provenance. Bump on any change of the bytes.
COVER_VERSION = "story-cover-v1"
#: Covers made per pass across every business: a pass downloads each video once.
PER_PASS = 5
_NAMESPACE = UUID("5f0c2b7e-8d1a-4c3e-9b25-25142900c0e5")
_JPEG_QUALITY = 92

#: A piece's files plus the automatic covers of its videos, as 9:16 image rows: a drop-in
#: for `FROM image_assets` in the story ad's readers (same name, same columns they read).
#: A failed cover has no key and is left out by their `object_key IS NOT NULL`; so is the
#: cover of a video whose file was replaced in place (a re-join keeps the row).
#: `auto_cover`: the wizard offers such a frame only as its video's cover, never as a photo.
PIECE_FILES = """(SELECT id,draft_id,version_id,object_key,content_type,media_type,width,height,
  position,false AS auto_cover FROM image_assets
  UNION ALL SELECT c.id,c.draft_id,c.version_id,c.object_key,c.content_type,'image',c.width,
  c.height,1000,true FROM piece_story_covers c JOIN image_assets v ON v.id=c.source_asset_id
    AND v.tenant_id=c.tenant_id AND v.object_key=c.source_object_key) AS image_assets"""

_CANDIDATES = """SELECT a.tenant_id,a.id AS asset_id,a.draft_id,a.version_id,a.object_key,
  a.width,a.height
FROM content_drafts d JOIN image_assets a ON a.tenant_id=d.tenant_id AND a.draft_id=d.id
  AND a.version_id=d.active_version_id
WHERE d.status='approved' AND d.approved_revision=d.revision AND d.parent_draft_id IS NULL
  AND d.part_removed_at IS NULL AND d.media_purged_at IS NULL
  AND a.media_type='video' AND a.content_type='video/mp4' AND a.object_key IS NOT NULL
  AND a.width>0 AND a.width*16=a.height*9
  AND a.object_key LIKE 't/' || a.tenant_id::text || '/%' AND position('..' in a.object_key)=0
  AND (d.category='story' OR NOT EXISTS (SELECT 1 FROM image_assets o
    WHERE o.tenant_id=d.tenant_id AND o.draft_id=d.id AND o.version_id=d.active_version_id
      AND o.output_port IS DISTINCT FROM 'story'))
  AND NOT EXISTS (SELECT 1 FROM image_assets i
    WHERE i.tenant_id=d.tenant_id AND i.draft_id=d.id AND i.version_id=d.active_version_id
      AND i.media_type='image' AND i.content_type IN ('image/jpeg','image/png')
      AND i.object_key IS NOT NULL AND i.width>0 AND i.width*16=i.height*9)
  AND NOT EXISTS (SELECT 1 FROM piece_story_covers c
    WHERE c.tenant_id=a.tenant_id AND c.source_asset_id=a.id
      AND c.source_object_key=a.object_key)"""
_TENANTS = text(f"SELECT DISTINCT tenant_id FROM ({_CANDIDATES}) AS c ORDER BY tenant_id")
_WORK = text(
    f"""{_CANDIDATES} AND NOT a.id=ANY(CAST(:resting AS uuid[]))
ORDER BY d.approved_at DESC NULLS LAST,a.id LIMIT :limit"""
)
#: A video that failed for a reason of the machine waits this long before another try, so
#: a few stubborn ones never take every pass's slots.
REST_SECONDS = 30 * 60
_INSERT = text("""INSERT INTO piece_story_covers (tenant_id,draft_id,version_id,source_asset_id,
  source_object_key,state,object_key,content_type,width,height,pipeline_version,failure_reason)
VALUES (:tenant,:draft,:version,:asset,:source,:state,:key,:type,:width,:height,:pipeline,
  :reason)
ON CONFLICT (tenant_id,source_asset_id,source_object_key) DO NOTHING""")

Grab = Callable[..., bytes]


def cover_key(video_key: str, asset_id: UUID) -> str:
    """Next to the video, so it shares the video's retention (only videos under the
    tenant's `t/` are candidates); a new file of the same row gets a new key."""
    name = uuid5(_NAMESPACE, f"{COVER_VERSION}:{asset_id}:{video_key}")
    return f"{video_key.rsplit('/', 1)[0]}/story-cover-{name}.jpg"


def vertical_jpeg(jpeg: bytes) -> tuple[bytes, int, int]:
    """The frame as an exact 9:16 JPEG: unchanged when it already is, else centre-cropped
    (an odd display size can be a pixel off). Raises `VideoStillError` when unusable."""
    from PIL import Image, UnidentifiedImageError  # noqa: PLC0415 — worker only
    from qualify_creative.video.still import VideoStillError  # noqa: PLC0415

    try:
        with Image.open(io.BytesIO(jpeg)) as image:
            width, height = image.size
            unit = min(width // 9, height // 16)
            if unit == 0:
                raise VideoStillError("the frame is too small")
            if (width, height) == (9 * unit, 16 * unit):
                return jpeg, width, height
            left, top = (width - 9 * unit) // 2, (height - 16 * unit) // 2
            cropped = image.convert("RGB").crop((left, top, left + 9 * unit, top + 16 * unit))
    except (UnidentifiedImageError, OSError) as exc:
        raise VideoStillError("the frame is not a readable image") from exc
    out = io.BytesIO()
    cropped.save(out, "JPEG", quality=_JPEG_QUALITY)
    return out.getvalue(), 9 * unit, 16 * unit


def make_cover(gate: Any, work: Mapping[str, Any], grab: Grab | None = None) -> bool:
    """The cover of one video, stored and recorded; False when the video gave no frame
    (recorded `failed`). R2, database and timeout errors propagate: nothing is recorded and the
    next pass tries again."""
    from qualify_creative.video.still import (  # noqa: PLC0415 — worker only
        POSTER_PREFERRED_SECONDS,
        VideoStillError,
        poster_from_video_file,
    )

    tenant, asset = work["tenant_id"], work["asset_id"]
    values = {
        "tenant": tenant,
        "draft": work["draft_id"],
        "version": work["version_id"],
        "asset": asset,
        "source": work["object_key"],
        "pipeline": COVER_VERSION,
        "state": "stored",
        "key": None,
        "type": None,
        "width": None,
        "height": None,
        "reason": None,
    }
    with tempfile.TemporaryDirectory(prefix="story-cover-") as folder:
        path = Path(folder) / "video.mp4"
        try:
            with gate.open_object(tenant, work["object_key"]) as source, path.open("wb") as out:
                shutil.copyfileobj(source, out)
            # full size (never scaled under the video's own long side): the frame keeps 9:16
            jpeg = (grab or poster_from_video_file)(
                path,
                at_seconds=POSTER_PREFERRED_SECONDS,
                max_side=max(work["width"], work["height"]),
            )
            jpeg, width, height = vertical_jpeg(jpeg)
        except ObjectNotFound:  # the video's own file is gone: no frame to take, ever
            values |= {"state": "failed", "reason": "source_missing"}
        except VideoStillError as exc:
            # a timeout is the machine's: not recorded, the video is tried again later
            if isinstance(exc.__cause__, subprocess.TimeoutExpired):
                raise
            logger.info("story_cover.no_frame error_type=%s", type(exc).__name__)
            values |= {"state": "failed", "reason": "no_frame"}
    if values["state"] == "stored":
        key = cover_key(work["object_key"], asset)
        if not gate.has_object(tenant, key):  # `t/` is write-once: a retry reuses it
            gate.put_media(tenant, key, io.BytesIO(jpeg), "image/jpeg")
        values |= {"key": key, "type": "image/jpeg", "width": width, "height": height}
    with tenant_session(tenant) as session:
        session.execute(_INSERT, values)
    return values["state"] == "stored"


def discover_tenants() -> list[UUID]:
    """PRODUCTION discovery: ids of the businesses with a video historia lacking a cover."""
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415 — production only

    with admin_session() as session:
        return list(session.scalars(_TENANTS))


def pending(
    tenant_id: UUID, limit: int = PER_PASS, resting: Iterable[UUID] = ()
) -> list[dict[str, Any]]:
    """This business's videos waiting for a cover, newest approval first, except those
    resting after a failure of the machine."""
    values = {"limit": limit, "resting": list(resting)}
    with tenant_session(tenant_id) as session:
        return [dict(row) for row in session.execute(_WORK, values).mappings()]


def sweep(
    tenant_ids: Iterable[UUID],
    gate: Any,
    limit: int = PER_PASS,
    grab: Grab | None = None,
    resting: dict[UUID, float] | None = None,
) -> int:
    """At most `limit` attempts over these businesses; how many covers were stored. A video
    that fails (R2, database, timeout) is logged and rests `REST_SECONDS` in `resting` (the
    worker's memory: a restart simply tries it again), never stopping the rest of the pass."""
    made, now = 0, time.monotonic()
    resting = {} if resting is None else resting
    for asset in [a for a, until in resting.items() if until <= now]:
        del resting[asset]
    for tenant in tenant_ids:
        for work in pending(tenant, limit, resting):
            try:
                made += make_cover(gate, work, grab)
            except Exception as exc:  # noqa: BLE001 — tried again later; the others go on
                logger.warning("story_cover.failed error_type=%s", type(exc).__name__)
                resting[work["asset_id"]] = now + REST_SECONDS
            limit -= 1
            if limit <= 0:
                return made
    return made


def cover_chore(scope: list[UUID] | None) -> Callable[[], int]:
    """The worker's pass (`None` = every business). The R2 gate is built on the first pass
    (after `.env`); any error is logged by type only and the next pass starts over."""
    built: dict[str, Any] = {}
    resting: dict[UUID, float] = {}

    def run() -> int:
        try:
            if not built:
                from qualify_api.creative.owner_uploads import default_gate  # noqa: PLC0415

                built["gate"] = default_gate()
            tenants = discover_tenants() if scope is None else scope
            return sweep(tenants, built["gate"], resting=resting)
        except Exception as exc:  # noqa: BLE001 — a pass never stops the worker
            logger.warning("story_cover.pass_failed error_type=%s", type(exc).__name__)
            return 0

    return run
