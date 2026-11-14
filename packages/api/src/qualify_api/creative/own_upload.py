"""An owner's photo or video uploaded from the planner, as an approved own piece
(m-25026384; founder 2026-11-13).

«Nueva publicación» (the planner's panel) lets the owner upload ONE file in step 1 and
schedule it in step 2 like any other piece. The app writes the file to R2 first
(`Qualify/upload_store.save_upload*` → `t/{tenant}/uploads/…`, `owner_uploads`); this
module turns that already-uploaded object into a piece of kind `own_media`
(`creative.own_media.create_own_media_piece`): born APPROVED by the acting user at upload
time, `reuse_type` `recurrente`, `pipeline_version` `planner-upload-v1`, no copy of the
file, nothing generated, nothing charged (no `creation_charges`, no `consumption_ledger`:
no vendor is called).

## Entry point

`record_planner_upload(tenant_id=, brand_id=, user_id=, upload=OwnUpload(...))` — one
`tenant_session` transaction, idempotent on `upload.upload_id`; returns an
`UploadedPiece` or raises `OwnUploadRefused` with a stable `code` (`UploadRefusal`) and
the Spanish sentence the owner can read (`REFUSAL_TEXT`).

## What the file must be (so the planner can publish it at its hour)

- Under THIS tenant's uploads prefix, `t/{tenant}/uploads/…` (`owner_uploads.new_upload_key`).
  That prefix is readable by every publishing door (`ObjectGate.open_object`,
  `/public/media/{token}`), never purged (the retention rule empties only
  `t/{tenant}/generated/{draft}/`, and own media is exempt by kind anyway) and never
  overwritten (the bucket lock on `t/`).
- An image: `image/jpeg` (a real JPEG — Meta's Content Publishing API takes nothing else)
  of at most 8 MB (`publishing.client.IMAGE_MAX_BYTES`). A PNG/HEIC/WebP must be
  converted to JPEG BEFORE it is uploaded; `planner.publishable.evaluate` refuses any
  other type at publish time.
- A video: `video/mp4` or `video/quicktime`. A video story over 60 s is refused by Meta
  (a warning in the destination picker, never a block here).

## Category and format (the rule)

- video → `reel` / `reels_9_16`: a lone video is a reel (`publishable` never guesses a
  feed video; since 2023 a feed video IS a reel).
- image whose size fits Meta's feed range (4:5 … 1.91:1), or whose size is unknown →
  `galeria` / `feed_4_5` (`feed_1_1` when square): it can go out as «Publicación»;
- image outside that range (a 9:16 phone photo) → `story` / `story_9_16`: «Historia» is
  the only destination Meta takes for it.

The category is the piece's origin; step 2's destination picker reads the MEDIA's shape
(`publishable.destination_options`), so an image always offers Publicación and Historia
(Publicación disabled with its reason when the recorded size is outside the feed range)
and a video Reel and Historia, whatever the category.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid5

from qualify_creative.enums import ContentFormat, PostCategory
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.keys import tenant_prefix
from sqlalchemy import text
from sqlalchemy.orm import Session

from qualify_api.creative.own_media import (
    REQUEST_KEY_NAMESPACE,
    OwnMediaItem,
    OwnMediaPiece,
    create_own_media_piece,
)
from qualify_api.publishing.client import IMAGE_CONTENT_TYPE, IMAGE_MAX_BYTES
from qualify_api.tenancy.models import Brand

#: `content_drafts.pipeline_version` / `piece_versions.pipeline_version` of these pieces.
PIPELINE_VERSION = "planner-upload-v1"
#: `image_assets.params.source`.
SOURCE = "planner_upload"
#: The folder under the tenant prefix where the app writes the owner's uploads.
UPLOADS_FOLDER = "uploads/"

#: The card's title when the owner wrote no text.
UNTITLED_IMAGE = "Foto subida por ti"
UNTITLED_VIDEO = "Video subido por ti"

IMAGE = "image"
VIDEO = "video"
#: What the publisher can send (`planner.publishable._ALLOWED_CONTENT_TYPES`).
IMAGE_CONTENT_TYPES = frozenset({IMAGE_CONTENT_TYPE})
VIDEO_CONTENT_TYPES = frozenset({"video/mp4", "video/quicktime"})
#: Spellings some browsers send for the same type.
_CONTENT_TYPE_ALIASES = {"image/jpg": IMAGE_CONTENT_TYPE, "image/pjpeg": IMAGE_CONTENT_TYPE}

# Meta's feed image range (`planner.publishable.FEED_RATIO_MIN/MAX`), same tolerance.
_FEED_RATIO_MIN = 4 / 5
_FEED_RATIO_MAX = 1.91
_TOLERANCE = 0.005

_LOCK_NAMESPACE = "own_upload:"


class UploadRefusal(StrEnum):
    """Why an upload does not become a piece. Stable: the app words them."""

    NOT_THIS_TENANT = "not_this_tenant"  # the key is not under this tenant's prefix
    NOT_AN_UPLOAD = "not_an_upload"  # under the tenant, but not in `uploads/`
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"  # neither image nor video
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"  # not JPEG / MP4 / MOV
    IMAGE_TOO_LARGE = "image_too_large"  # an image over 8 MB
    INVALID_SIZE = "invalid_size"  # a width, height, duration or byte size ≤ 0
    INVALID_POSTER = "invalid_poster"  # a video's still outside the uploads, or on an image
    UNKNOWN_BRAND = "unknown_brand"  # the brand is not this tenant's


#: What the owner reads for each refusal (plain Spanish, `qualify-copy-es`).
REFUSAL_TEXT: dict[UploadRefusal, str] = {
    UploadRefusal.NOT_THIS_TENANT: "No encontramos el archivo que subiste. Vuelve a subirlo.",
    UploadRefusal.NOT_AN_UPLOAD: "No encontramos el archivo que subiste. Vuelve a subirlo.",
    UploadRefusal.UNSUPPORTED_MEDIA_TYPE: "Solo puedes subir una foto o un video.",
    UploadRefusal.UNSUPPORTED_CONTENT_TYPE: "Instagram no acepta ese archivo. Elige otra foto "
    "o un video MP4 o MOV.",
    UploadRefusal.IMAGE_TOO_LARGE: "La foto pesa más de 8 MB y Instagram no la acepta. "
    "Prueba con una más liviana.",
    UploadRefusal.INVALID_SIZE: "No pudimos leer el archivo. Vuelve a subirlo.",
    UploadRefusal.INVALID_POSTER: "No pudimos leer la portada del video. Vuelve a subirlo.",
    UploadRefusal.UNKNOWN_BRAND: "No encontramos tu negocio. Vuelve a entrar e inténtalo de nuevo.",
}


class OwnUploadRefused(ValueError):
    """The upload cannot become a piece; nothing was written. `code` is stable, `text`
    is the owner's sentence."""

    def __init__(self, code: UploadRefusal) -> None:
        super().__init__(code.value)
        self.code = code
        self.text = REFUSAL_TEXT[code]


@dataclass(frozen=True)
class OwnUpload:
    """ONE file the app already wrote to R2. `upload_id` names it for idempotency: the
    same id always maps to the same piece (the app mints it once per chosen file)."""

    upload_id: UUID
    object_key: str
    media_type: str  # "image" / "video"
    content_type: str
    caption: str = ""
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    size_bytes: int | None = None
    #: A video's still (JPEG under the same uploads prefix), for the calendar card.
    poster_object_key: str | None = None


@dataclass(frozen=True)
class UploadedPiece:
    draft_id: UUID
    created: bool  # False: this upload id already had its piece (nothing written)
    category: PostCategory
    format: ContentFormat


def upload_request_key(upload_id: UUID) -> UUID:
    """The piece's `content_drafts.request_key` for one upload — disjoint from
    «Publicar»'s `own_media.request_key_for(attempt_id)` by its `planner-upload:` name."""
    return uuid5(REQUEST_KEY_NAMESPACE, f"planner-upload:{upload_id}")


def normalized_content_type(content_type: str) -> str:
    """Lower case, without parameters (`image/JPEG; q=1` → `image/jpeg`), aliases folded."""
    base = (content_type or "").split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_ALIASES.get(base, base)


def shape_for(
    media_type: str, width: int | None = None, height: int | None = None
) -> tuple[PostCategory, ContentFormat]:
    """The piece's category and format for a file that was never published (module
    docstring, «Category and format»). Pure."""
    if media_type == VIDEO:
        return PostCategory.REEL, ContentFormat.REELS_9_16
    if not width or not height:
        return PostCategory.GALERIA, ContentFormat.FEED_4_5
    ratio = width / height
    if not _FEED_RATIO_MIN - _TOLERANCE <= ratio <= _FEED_RATIO_MAX + _TOLERANCE:
        return PostCategory.STORY, ContentFormat.STORY_9_16
    if abs(ratio - 1) <= 0.01:
        return PostCategory.GALERIA, ContentFormat.FEED_1_1
    return PostCategory.GALERIA, ContentFormat.FEED_4_5


def _in_uploads(tenant_id: UUID, key: str) -> UploadRefusal | None:
    prefix = tenant_prefix(tenant_id)
    if not key or ".." in key or not key.startswith(prefix):
        return UploadRefusal.NOT_THIS_TENANT
    rest = key[len(prefix) :]
    if not rest.startswith(UPLOADS_FOLDER) or len(rest) == len(UPLOADS_FOLDER):
        return UploadRefusal.NOT_AN_UPLOAD
    return None


def check_upload(tenant_id: UUID, upload: OwnUpload) -> OwnUpload:
    """The upload with its content type normalized, or `OwnUploadRefused`. Pure — the
    order is fixed so one upload always gets the same answer: key → media type →
    content type → sizes → image weight → poster."""
    refusal = _in_uploads(tenant_id, upload.object_key)
    if refusal is not None:
        raise OwnUploadRefused(refusal)
    if upload.media_type not in (IMAGE, VIDEO):
        raise OwnUploadRefused(UploadRefusal.UNSUPPORTED_MEDIA_TYPE)
    content_type = normalized_content_type(upload.content_type)
    allowed = IMAGE_CONTENT_TYPES if upload.media_type == IMAGE else VIDEO_CONTENT_TYPES
    if content_type not in allowed:
        raise OwnUploadRefused(UploadRefusal.UNSUPPORTED_CONTENT_TYPE)
    numbers = (upload.width, upload.height, upload.duration_seconds, upload.size_bytes)
    if any(value is not None and value <= 0 for value in numbers):
        raise OwnUploadRefused(UploadRefusal.INVALID_SIZE)
    if upload.media_type == IMAGE and (upload.size_bytes or 0) > IMAGE_MAX_BYTES:
        raise OwnUploadRefused(UploadRefusal.IMAGE_TOO_LARGE)
    if upload.poster_object_key is not None and (
        upload.media_type != VIDEO or _in_uploads(tenant_id, upload.poster_object_key)
    ):
        raise OwnUploadRefused(UploadRefusal.INVALID_POSTER)
    if content_type == upload.content_type:
        return upload
    return OwnUpload(
        upload_id=upload.upload_id,
        object_key=upload.object_key,
        media_type=upload.media_type,
        content_type=content_type,
        caption=upload.caption,
        width=upload.width,
        height=upload.height,
        duration_seconds=upload.duration_seconds,
        size_bytes=upload.size_bytes,
        poster_object_key=upload.poster_object_key,
    )


def create_upload_piece(
    session: Session,
    *,
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID,
    upload: OwnUpload,
    now: datetime,
) -> UploadedPiece:
    """The piece for this upload, in the CALLER's `tenant_session` (never commits).
    Serialized per upload id by a transaction-scoped advisory lock, so two concurrent
    calls leave one piece; the unique `request_key` is the last word."""
    checked = check_upload(tenant_id, upload)
    if session.get(Brand, brand_id) is None:  # RLS: another tenant's brand is not visible
        raise OwnUploadRefused(UploadRefusal.UNKNOWN_BRAND)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{_LOCK_NAMESPACE}{checked.upload_id}"},
    )
    category, fmt = shape_for(checked.media_type, checked.width, checked.height)
    draft_id, created = create_own_media_piece(
        session,
        tenant_id=tenant_id,
        piece=OwnMediaPiece(
            brand_id=brand_id,
            user_id=user_id,
            caption=checked.caption or "",
            category=category,
            format=fmt,
            approved_at=now,
            items=(
                OwnMediaItem(
                    object_key=checked.object_key,
                    content_type=checked.content_type,
                    media_type=checked.media_type,
                    position=0,
                    width=checked.width,
                    height=checked.height,
                    duration_seconds=checked.duration_seconds,
                    thumbnail_key=checked.poster_object_key,
                ),
            ),
            request_key=upload_request_key(checked.upload_id),
            pipeline_version=PIPELINE_VERSION,
            source=SOURCE,
            untitled=UNTITLED_IMAGE if checked.media_type == IMAGE else UNTITLED_VIDEO,
            source_ref=str(checked.upload_id),
        ),
    )
    return UploadedPiece(draft_id, created, category, fmt)


def record_planner_upload(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID,
    upload: OwnUpload,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> UploadedPiece:
    """What the app calls once the file is in R2: the approved own piece for it, in ONE
    `tenant_session` transaction. Idempotent on `upload.upload_id`; raises
    `OwnUploadRefused` (nothing written) for a file the planner could never publish."""
    check_upload(tenant_id, upload)  # refuse before opening a transaction
    with tenant_session(tenant_id) as session:
        return create_upload_piece(
            session,
            tenant_id=tenant_id,
            brand_id=brand_id,
            user_id=user_id,
            upload=upload,
            now=clock(),
        )


__all__ = [
    "IMAGE_CONTENT_TYPES",
    "PIPELINE_VERSION",
    "REFUSAL_TEXT",
    "SOURCE",
    "UNTITLED_IMAGE",
    "UNTITLED_VIDEO",
    "VIDEO_CONTENT_TYPES",
    "OwnUpload",
    "OwnUploadRefused",
    "UploadRefusal",
    "UploadedPiece",
    "check_upload",
    "create_upload_piece",
    "normalized_content_type",
    "record_planner_upload",
    "shape_for",
    "upload_request_key",
]
