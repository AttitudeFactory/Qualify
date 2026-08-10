"""A3 — media staging, fully offline against an in-memory ObjectStore double.

Green without network and without boto3 installed: the double implements the same
`ObjectStore` protocol the real R2 store does, so the gate's checks (tenant prefix, size
ceiling, content-type requirement) run for real.
"""

from __future__ import annotations

import io
from uuid import UUID

import pytest
from qualify_shared.objects.gate import MAX_MEDIA_BYTES, ObjectGate, ObjectSizeExceeded
from qualify_shared.objects.keys import TenantPrefixViolation

from qualify_api.publishing.staging import MediaStagingService, StagedMedia

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
    """IMAGE has no resumable path (QUA-68) and a typo'd type must not reach the bucket.
    Same vocabulary as the publish client — a type staged here but unpublishable there
    would fail hours later, at publish time, looking like a Meta problem."""
    service, store = build()

    for bad in ("IMAGE", "REEL", "reels", ""):
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
