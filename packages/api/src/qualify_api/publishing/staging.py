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
(`REELS`/`STORIES`/`VIDEO` — the same set the publish client's resumable path accepts),
NEVER `media_type`. Meta's `media_type` reads back `IMAGE`/`VIDEO` even for a story; the
property that distinguishes a story is `media_product_type`, and persisting the wrong one
leaves every future "was this a reel or a story?" query silently wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import IO
from uuid import UUID

from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.keys import media_key

from qualify_api.publishing.client import RESUMABLE_MEDIA_TYPES


@dataclass(frozen=True)
class StagedMedia:
    """What the rest of the chain needs to know about a staged asset — the key the
    publisher will open, and the two properties that travel with it."""

    media_object_key: str
    media_product_type: str
    content_type: str


class MediaStagingService:
    """Stages one media asset behind the gate. One instance wraps one gate."""

    def __init__(self, gate: ObjectGate) -> None:
        self._gate = gate

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
        product-type vocabulary here, and the tenant prefix / size ceiling / content-type
        requirement inside the gate."""
        if media_product_type not in RESUMABLE_MEDIA_TYPES:
            raise ValueError(
                f"media_product_type {media_product_type!r} is not publishable; "
                f"expected one of {sorted(RESUMABLE_MEDIA_TYPES)}"
            )
        key = media_key(tenant_id, connection_id, media_id)
        self._gate.put_media(tenant_id, key, fileobj, content_type)
        return StagedMedia(
            media_object_key=key,
            media_product_type=media_product_type,
            content_type=content_type,
        )
