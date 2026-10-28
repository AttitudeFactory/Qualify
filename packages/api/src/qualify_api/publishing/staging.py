"""Media staging to the object plane (A3 — layer L6, the FIRST link of the publish chain).

A publish that fails halfway must not cost the operator a re-upload, so the bytes land in
durable storage BEFORE anything touches the platform (ADR 28d). Verified when this was
specced: no call to `ObjectGate.put_media` existed outside the gate's own tests — without
this service the publish chain ends at an empty bucket.

Deliberately NOT here:
- No `scheduled_posts` row. `publish_attempts.scheduled_post_id` is nullable precisely to
  admit publish-now; writing a schedule row nobody reads would promise a clock that does
  not exist.
- No key construction by hand. `media_key` is the single spelling of the layout, and the
  gate re-checks the tenant prefix on every operation anyway.

Vocabulary note: what this service accepts, carries and returns is `media_product_type`
(`REELS`/`STORIES`/`VIDEO`/`IMAGE` since QUA-68 — see `PUBLISHABLE_MEDIA_TYPES`), NEVER
`media_type`. Meta's `media_type` reads back `IMAGE`/`VIDEO` even for a story; the
property that distinguishes a story is `media_product_type`, and persisting the wrong one
leaves every future "was this a reel or a story?" query silently wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import IO
from uuid import UUID

from qualify_shared.objects.gate import ObjectGate, ObjectSizeExceeded, UnsizedStream
from qualify_shared.objects.keys import media_key

from qualify_api.publishing.client import (
    IMAGE_CONTENT_TYPE,
    IMAGE_MAX_BYTES,
    JPEG_MAGIC_BYTES,
    MEDIA_TYPE_IMAGE,
    RESUMABLE_MEDIA_TYPES,
    is_image_story,
)

# QUA-68: everything this service will stage for publication — the resumable video types
# plus the one non-resumable image type. Kept as its own name (not folded into
# `RESUMABLE_MEDIA_TYPES`, whose meaning stays "accepted by `create_container`") so a
# reader of `stage_media`'s validation sees the actual, current scope of this service.
PUBLISHABLE_MEDIA_TYPES = RESUMABLE_MEDIA_TYPES | {MEDIA_TYPE_IMAGE}


@dataclass(frozen=True)
class StagedMedia:
    """What the rest of the chain needs to know about a staged asset — the key the
    publisher will open, and the two properties that travel with it."""

    media_object_key: str
    media_product_type: str
    content_type: str


class UnsupportedImageFormat(Exception):
    """QUA-103: the declared `content_type` is not `image/jpeg`, or the bytes are not
    actually a JPEG regardless of what was declared.

    Raised instead of silently accepting anything non-empty (`ObjectGate.put_media`'s own,
    looser check) — JPEG-only is a Meta platform restriction (`content-publishing.md:53`),
    not an incomplete validation to relax later, so this is a permanent, not provisional,
    guard.
    """


class MediaStagingService:
    """Stages one media asset behind the gate. One instance wraps one gate."""

    def __init__(self, gate: ObjectGate, *, guard_connection_uploads: bool = False) -> None:
        self._gate = gate
        # Production composition always enables the DB consent fence. Offline
        # staging tests exercise format/size checks without constructing a DB door.
        self._guard_connection_uploads = guard_connection_uploads

    def stage_media(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        media_id: str,
        fileobj: IO[bytes],
        content_type: str,
        media_product_type: str,
    ) -> StagedMedia:
        """Validate, then write. Nothing is uploaded unless every check passes: the
        product-type vocabulary here, the IMAGE-specific format/size checks below, and
        the tenant prefix / absolute size ceiling / content-type requirement inside the
        gate.
        """
        if media_product_type not in PUBLISHABLE_MEDIA_TYPES:
            raise ValueError(
                f"media_product_type {media_product_type!r} is not publishable; "
                f"expected one of {sorted(PUBLISHABLE_MEDIA_TYPES)}"
            )
        # QUA-113: an image Story is an image to Meta — same JPEG-only, 8 MB rules.
        if media_product_type == MEDIA_TYPE_IMAGE or is_image_story(
            media_product_type, content_type
        ):
            # QUA-103/QUA-68 ordering is deliberate: content-type (a string compare) and
            # size (`_reject_oversized_image`, `seek`-only, never a real `read`) both
            # reject WITHOUT touching a single byte of the stream — same "reject before
            # any byte moves" posture `HugeStream` in this package's tests exists to
            # prove. The magic-byte check is the one real `read()` in this chain, so it
            # runs LAST, only once the stream has already earned that read.
            _reject_non_jpeg_content_type(content_type)
            # QUA-68: `ig-user/media.md:55` caps a feed/story image at 8 MB — a tenth of
            # `ObjectGate.MAX_MEDIA_BYTES` (300 MB), which stays the store's own absolute
            # ceiling for everything else.
            _reject_oversized_image(fileobj)
            _reject_non_jpeg_bytes(fileobj)
        key = media_key(tenant_id, connection_id, media_id)
        if self._guard_connection_uploads:
            self._gate.put_connection_media(tenant_id, connection_id, key, fileobj, content_type)
        else:
            self._gate.put_media(tenant_id, key, fileobj, content_type)
        return StagedMedia(
            media_object_key=key,
            media_product_type=media_product_type,
            content_type=content_type,
        )


def _reject_non_jpeg_content_type(content_type: str) -> None:
    """QUA-103: exact match against `IMAGE_CONTENT_TYPE` — not a prefix check, not
    case-insensitive normalization beyond this one comparison. `ObjectGate.put_media`
    only ever demanded a non-empty string; this is the first real whitelist for IMAGE."""
    if content_type != IMAGE_CONTENT_TYPE:
        raise UnsupportedImageFormat(
            f"content_type {content_type!r} is not supported for IMAGE — "
            f"only {IMAGE_CONTENT_TYPE!r} is accepted (Meta's Content Publishing API "
            "supports no other image format)"
        )


def _reject_non_jpeg_bytes(fileobj: IO[bytes]) -> None:
    """QUA-103: a declared `content_type` is input, not proof — a browser or a renamed
    file can say `image/jpeg` for bytes that are not. Reads only the first 3 bytes (the
    JPEG SOI marker, `JPEG_MAGIC_BYTES`), position restored, so this costs nothing
    against the 8 MB ceiling below. Does NOT distinguish a plain JPEG from an extended
    variant (MPO/JPS) Meta itself rejects — that would need parsing APP marker segments,
    a real feature this ticket deliberately does not build; it only closes the cheap,
    common case of a mislabeled or renamed non-JPEG file."""
    try:
        origin = fileobj.seek(0, 1)
        header = fileobj.read(len(JPEG_MAGIC_BYTES))
        fileobj.seek(origin, 0)
    except (AttributeError, OSError) as exc:
        raise UnsizedStream("stream is not seekable, so its format cannot be checked") from exc
    if header != JPEG_MAGIC_BYTES:
        raise UnsupportedImageFormat(
            "file content is not a JPEG (magic bytes did not match) — a declared "
            "content_type of image/jpeg is not proof of the actual file format"
        )


def _reject_oversized_image(fileobj: IO[bytes]) -> None:
    """Measure a seekable stream's length, position restored, and refuse anything over
    `IMAGE_MAX_BYTES` — same `ObjectSizeExceeded`/`UnsizedStream` vocabulary the gate
    already raises for its own (looser) ceiling, so a caller has exactly one pair of
    exceptions to handle regardless of which ceiling tripped."""
    try:
        origin = fileobj.seek(0, 1)
        size = fileobj.seek(0, 2)
        fileobj.seek(origin, 0)
    except (AttributeError, OSError) as exc:
        raise UnsizedStream("stream is not seekable, so its size cannot be checked") from exc
    length = size - origin
    if length > IMAGE_MAX_BYTES:
        raise ObjectSizeExceeded(
            f"image is {length} bytes, over the {IMAGE_MAX_BYTES}-byte ceiling for IMAGE "
            "(ig-user/media.md:55) — video's 300 MB ceiling does not apply here"
        )
