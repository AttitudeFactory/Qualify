"""A3 — media staging, fully offline against an in-memory ObjectStore double.

Green without network and without boto3 installed: the double implements the same
`ObjectStore` protocol the real R2 store does, so the gate's checks (tenant prefix, size
ceiling, content-type requirement) run for real.
"""

from __future__ import annotations

import io
from uuid import UUID

import pytest
from qualify_shared.objects.gate import (
    MAX_MEDIA_BYTES,
    ObjectGate,
    ObjectSizeExceeded,
    UnsizedStream,
)
from qualify_shared.objects.keys import TenantPrefixViolation

from qualify_api.publishing.client import IMAGE_MAX_BYTES
from qualify_api.publishing.staging import MediaStagingService, StagedMedia, UnsupportedImageFormat

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")


class MemoryStore:
    """In-memory `(key, bytes, content_type)` sink implementing the ObjectStore protocol."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, fileobj: io.IOBase, content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key][0])


class HugeStream:
    """Seekable stream REPORTING an oversized length; reading it is an error, because an
    oversized object must be rejected before a single byte moves."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._pos = 0

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 1:
            return self._pos
        if whence == 2:
            self._pos = self._size
            return self._size
        self._pos = offset
        return offset

    def read(self, size: int = -1) -> bytes:
        raise AssertionError("an oversized stream must never be read")


def build() -> tuple[MediaStagingService, MemoryStore]:
    store = MemoryStore()
    return MediaStagingService(ObjectGate(store)), store


def test_stages_a_reel_under_the_tenant_media_key() -> None:
    service, store = build()

    staged = service.stage_media(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_id="m-1",
        fileobj=io.BytesIO(b"reel-bytes"),
        content_type="video/mp4",
        media_product_type="REELS",
    )

    expected_key = f"t/{TENANT}/media/{CONNECTION}/m-1"
    assert staged == StagedMedia(
        media_object_key=expected_key, media_product_type="REELS", content_type="video/mp4"
    )
    assert store.objects[expected_key] == (b"reel-bytes", "video/mp4")


def test_a_story_travels_as_media_product_type_never_media_type() -> None:
    """The story trap, asserted structurally: Meta's `media_type` reads back VIDEO even
    for a story, so the field this layer carries is `media_product_type` and a `media_type`
    attribute must not exist to be reached for."""
    service, _ = build()

    staged = service.stage_media(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_id="m-story",
        fileobj=io.BytesIO(b"story-bytes"),
        content_type="video/mp4",
        media_product_type="STORIES",
    )

    assert staged.media_product_type == "STORIES"
    assert not hasattr(staged, "media_type")


def test_rejects_unpublishable_product_types_before_writing() -> None:
    """A typo'd or invented type must not reach the bucket — same vocabulary as the
    publish client, so a type staged here but unpublishable there would fail hours later,
    at publish time, looking like a Meta problem. `IMAGE` is deliberately NOT in this list
    since QUA-68 — see `test_stages_an_image_under_the_tenant_media_key` below for its own
    (accepted) path."""
    service, store = build()

    for bad in ("REEL", "reels", "video", ""):
        with pytest.raises(ValueError, match="media_product_type"):
            service.stage_media(
                tenant_id=TENANT,
                connection_id=CONNECTION,
                media_id="m-bad",
                fileobj=io.BytesIO(b"x"),
                content_type="video/mp4",
                media_product_type=bad,
            )
    assert store.objects == {}


def test_traversal_in_media_id_raises_and_uploads_nothing() -> None:
    """The one route a caller-controlled value has into the key. The gate's prefix check
    catches it and the store must stay empty."""
    service, store = build()

    with pytest.raises(TenantPrefixViolation):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="../../../other-tenant/secret",
            fileobj=io.BytesIO(b"x"),
            content_type="video/mp4",
            media_product_type="REELS",
        )
    assert store.objects == {}


def test_empty_content_type_is_rejected_before_writing() -> None:
    service, store = build()

    with pytest.raises(ValueError, match="content_type"):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="m-1",
            fileobj=io.BytesIO(b"x"),
            content_type="",
            media_product_type="REELS",
        )
    assert store.objects == {}


def test_oversized_media_raises_without_partial_residue() -> None:
    """`HugeStream.read` raises if touched, so passing this test PROVES rejection happens
    before any byte moves — not merely that an exception surfaced eventually."""
    service, store = build()

    with pytest.raises(ObjectSizeExceeded):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="m-big",
            fileobj=HugeStream(MAX_MEDIA_BYTES + 1),  # type: ignore[arg-type]
            content_type="video/mp4",
            media_product_type="REELS",
        )
    assert store.objects == {}


# --------------------------------------------------------------------------------------
# IMAGE (QUA-68)
# --------------------------------------------------------------------------------------


def test_stages_an_image_under_the_tenant_media_key() -> None:
    service, store = build()

    staged = service.stage_media(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_id="m-img",
        fileobj=io.BytesIO(b"\xff\xd8\xff\xe0jpeg-bytes"),
        content_type="image/jpeg",
        media_product_type="IMAGE",
    )

    expected_key = f"t/{TENANT}/media/{CONNECTION}/m-img"
    assert staged == StagedMedia(
        media_object_key=expected_key, media_product_type="IMAGE", content_type="image/jpeg"
    )
    assert store.objects[expected_key] == (b"\xff\xd8\xff\xe0jpeg-bytes", "image/jpeg")


def test_an_image_right_at_the_8mb_ceiling_is_accepted() -> None:
    """Exactly `IMAGE_MAX_BYTES`, not one byte more — a real, readable stream (unlike
    `HugeStream`, which fakes size without real content and exists only to test
    REJECTION paths that never read): acceptance means the write actually happens, so
    this proves the boundary is `> IMAGE_MAX_BYTES` (over is rejected), not `>=`."""
    service, store = build()

    service.stage_media(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_id="m-img-max",
        # Real JPEG magic bytes (QUA-103's format check runs on every IMAGE, this
        # fixture is no exception) padded out to exactly the ceiling.
        fileobj=io.BytesIO(b"\xff\xd8\xff" + b"x" * (IMAGE_MAX_BYTES - 3)),
        content_type="image/jpeg",
        media_product_type="IMAGE",
    )

    key = f"t/{TENANT}/media/{CONNECTION}/m-img-max"
    assert len(store.objects[key][0]) == IMAGE_MAX_BYTES


def test_an_image_over_8mb_is_rejected_without_reading_it() -> None:
    """Mirrors `test_oversized_media_raises_without_partial_residue`, but against the
    TIGHTER 8 MB ceiling — video's 300 MB `HugeStream(MAX_MEDIA_BYTES + 1)` would NOT
    trip this check, which is exactly why IMAGE needs its own, separate guard rather than
    relying on the gate's absolute ceiling."""
    service, store = build()

    with pytest.raises(ObjectSizeExceeded, match="IMAGE"):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="m-img-big",
            fileobj=HugeStream(IMAGE_MAX_BYTES + 1),  # type: ignore[arg-type]
            content_type="image/jpeg",
            media_product_type="IMAGE",
        )
    assert store.objects == {}


def test_a_video_well_under_8mb_is_never_subjected_to_the_image_ceiling() -> None:
    """The bifurcation itself, proven both ways: an 8 MB+ VIDEO must stage fine (the
    image-only check must not accidentally apply to it), while the same size for IMAGE
    (tested above) is rejected."""
    service, store = build()
    over_the_image_ceiling_under_the_video_one = IMAGE_MAX_BYTES + 1

    service.stage_media(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_id="m-vid-9mb",
        fileobj=io.BytesIO(b"x" * over_the_image_ceiling_under_the_video_one),
        content_type="video/mp4",
        media_product_type="REELS",
    )

    key = f"t/{TENANT}/media/{CONNECTION}/m-vid-9mb"
    assert len(store.objects[key][0]) == over_the_image_ceiling_under_the_video_one


def test_an_unseekable_image_stream_raises_unsized_stream() -> None:
    """The IMAGE-specific size check (`_reject_oversized_image`) must translate a
    non-seekable stream the same way the gate's own ceiling does — `UnsizedStream`, not an
    `AttributeError`/`OSError` leaking past this service."""
    service, _ = build()

    class Unseekable:
        def read(self, size: int = -1) -> bytes:  # pragma: no cover - must not be reached
            raise AssertionError("must be rejected before any read")

    with pytest.raises(UnsizedStream):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="m-img-bad-stream",
            fileobj=Unseekable(),  # type: ignore[arg-type]
            content_type="image/jpeg",
            media_product_type="IMAGE",
        )


# --------------------------------------------------------------------------------------
# JPEG-only whitelist + magic bytes (QUA-103) — a platform restriction, not a partial
# validation: Meta's Content Publishing API supports no image format other than JPEG.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad_content_type", ["image/png", "image/webp", "image/gif", "image/heic"])
def test_a_non_jpeg_content_type_is_rejected_before_writing(bad_content_type: str) -> None:
    """PNG/WebP/GIF/HEIC are not "unvalidated" — Meta's API does not accept them via
    `image_url` at all (content-publishing.md:53), so this whitelist has exactly one
    entry and is not expected to grow."""
    service, store = build()

    with pytest.raises(UnsupportedImageFormat, match="image/jpeg"):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="m-bad-format",
            fileobj=io.BytesIO(b"\xff\xd8\xffwhatever-bytes"),
            content_type=bad_content_type,
            media_product_type="IMAGE",
        )
    assert store.objects == {}


def test_any_non_empty_content_type_is_no_longer_accepted_for_image() -> None:
    """The gap QUA-68 left open, closed: `ObjectGate.put_media`'s own check (non-empty
    string) used to be the ONLY gate for IMAGE — this whitelist is stricter than that,
    on purpose."""
    service, store = build()

    with pytest.raises(UnsupportedImageFormat):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="m-anything",
            fileobj=io.BytesIO(b"\xff\xd8\xffx"),
            content_type="anything-non-empty",
            media_product_type="IMAGE",
        )
    assert store.objects == {}


def test_a_file_declaring_jpeg_but_with_non_jpeg_bytes_is_rejected() -> None:
    """The real content check: a declared `content_type` is input, not proof. A PNG
    signature (`\\x89PNG`) behind a `image/jpeg` label must not reach R2."""
    service, store = build()

    with pytest.raises(UnsupportedImageFormat, match="magic bytes"):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="m-mislabeled",
            fileobj=io.BytesIO(b"\x89PNG\r\n\x1a\nrest-of-a-real-png"),
            content_type="image/jpeg",
            media_product_type="IMAGE",
        )
    assert store.objects == {}


def test_a_real_jpeg_signature_with_more_bytes_after_it_is_accepted() -> None:
    """Regression: the magic-byte check must not be so strict it rejects a real JPEG —
    only the first 3 bytes are checked, whatever legitimately follows them is fine."""
    service, store = build()

    staged = service.stage_media(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_id="m-real-jpeg",
        fileobj=io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00rest-of-a-real-jpeg"),
        content_type="image/jpeg",
        media_product_type="IMAGE",
    )

    assert staged.content_type == "image/jpeg"
    assert store.objects[staged.media_object_key][0].startswith(b"\xff\xd8\xff")


def test_the_size_ceiling_is_checked_before_the_magic_bytes_read() -> None:
    """Ordering pin: an oversized stream must be rejected by `seek` alone, the SAME
    "never read an oversized stream" guarantee `test_an_image_over_8mb_is_rejected_
    without_reading_it` already proves for the size check on its own — the magic-byte
    check's `read()` must never run first and defeat that guarantee."""
    service, store = build()

    with pytest.raises(ObjectSizeExceeded):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="m-oversized-would-fail-magic-bytes-too",
            # Reports oversized AND would fail the magic-byte check if ever read —
            # proves size is checked first, by `seek` alone, never touching bytes.
            fileobj=HugeStream(IMAGE_MAX_BYTES + 1),  # type: ignore[arg-type]
            content_type="image/jpeg",
            media_product_type="IMAGE",
        )
    assert store.objects == {}


# --------------------------------------------------------------------------------------
# Image Story (QUA-113) — an image Story is an image: JPEG-only, 8 MB
# --------------------------------------------------------------------------------------


def test_an_image_story_is_staged_like_an_image() -> None:
    service, store = build()

    staged = service.stage_media(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_id="m-story-img",
        fileobj=io.BytesIO(b"\xff\xd8\xff\xe0jpeg-bytes"),
        content_type="image/jpeg",
        media_product_type="STORIES",
    )

    assert staged.media_product_type == "STORIES"
    assert staged.content_type == "image/jpeg"
    assert store.objects[staged.media_object_key][1] == "image/jpeg"


def test_an_image_story_over_8mb_is_rejected_without_reading_it() -> None:
    service, store = build()

    with pytest.raises(ObjectSizeExceeded):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="m-story-big",
            fileobj=HugeStream(IMAGE_MAX_BYTES + 1),  # type: ignore[arg-type]
            content_type="image/jpeg",
            media_product_type="STORIES",
        )
    assert store.objects == {}


@pytest.mark.parametrize("content_type", ["image/png", "image/webp"])
def test_an_image_story_must_be_jpeg(content_type: str) -> None:
    service, store = build()

    with pytest.raises(UnsupportedImageFormat):
        service.stage_media(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_id="m-story-png",
            fileobj=io.BytesIO(b"\x89PNG...."),
            content_type=content_type,
            media_product_type="STORIES",
        )
    assert store.objects == {}


def test_a_video_story_is_never_subjected_to_the_image_rules() -> None:
    service, store = build()
    size = IMAGE_MAX_BYTES + 1

    service.stage_media(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_id="m-story-vid",
        fileobj=io.BytesIO(b"x" * size),
        content_type="video/mp4",
        media_product_type="STORIES",
    )

    assert len(store.objects[f"t/{TENANT}/media/{CONNECTION}/m-story-vid"][0]) == size
