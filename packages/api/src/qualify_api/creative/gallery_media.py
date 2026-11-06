"""The media a carousel «hecho con tu Galería» is made from (CM-6, m-24955927; epic
m-24955913 §5): photos and videos the owner chose in Galería — of the business
(`business_media`, CM-1/CM-3) or of one of its products (`product_media`) — and the
deterministic rules that turn a choice into slides.

Everything here reads through `tenant_session`, so RLS scopes every lookup to the caller's
tenant; on top of it each lookup is filtered by the BRAND (a tenant may hold several) and by
liveness: a business medium with a tombstone, or whose video is being cut (an active `cut`
job in `gallery_jobs` — it is about to be replaced by its parts, §4.2), and a product medium
of an inactive product are not offered. Nothing here writes, and nothing here reads a file:
the producer reads the bytes (and copies them into the piece) only after it has asked this
reader again, right before the slide is made.

Imported by `media.py` (the producer's Galería slides) and by `gallery_piece.py` (the API
CM-7 calls), so it imports neither.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from qualify_creative.schemas import (
    GALLERY_ORIGIN_BUSINESS,
    GALLERY_ORIGIN_PRODUCT,
    GALLERY_SEGMENT_MAX_MS,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.catalog.business_media_models import (
    ACTIVE_STATUSES,
    JOB_CUT,
    BusinessMedia,
    GalleryJob,
)
from qualify_api.catalog.models import (
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    BrandProduct,
    ProductMedia,
)

#: The version of the assembly that lays a Galería choice out as slides — stored on the
#: brief (`MediaInputs.gallery_assembly_version`) and on every slide's asset (provenance).
#: A change to the segment rule, the order or the sound rule is a new version.
GALLERY_ASSEMBLY_VERSION = "gallery-carousel-v1"
#: The stretch a carousel slide asks of a video: Instagram plays up to 60 s per item.
CAROUSEL_SEGMENT_MS = GALLERY_SEGMENT_MAX_MS
#: The shortest video Instagram takes in a carousel (`business_media.MIN_PART_MS` too).
MIN_VIDEO_MS = 3_000


@dataclass(frozen=True)
class GalleryRef:
    """One medium the owner chose: whose it is (`GALLERY_ORIGINS`) and its id."""

    origin: str
    media_id: UUID


@dataclass(frozen=True)
class GalleryMedium:
    """A chosen medium as it is now: live, of this brand, its file and what the slide
    needs to know about it. `product_name` is the product's name for a product medium."""

    origin: str
    media_id: UUID
    media_type: str  # "image" | "video"
    object_key: str
    poster_key: str | None
    duration_ms: int | None
    has_audio: bool
    product_name: str = ""

    @property
    def ref(self) -> GalleryRef:
        return GalleryRef(self.origin, self.media_id)

    @property
    def is_video(self) -> bool:
        return self.media_type == MEDIA_TYPE_VIDEO

    @property
    def thumbnail_key(self) -> str:
        return self.poster_key or self.object_key

    @property
    def keeps_sound(self) -> bool:
        """Whether this medium CAN keep its sound: a business video saved with it (D1). A
        product's video never does (D3: normalized without sound)."""
        return self.is_video and self.origin == GALLERY_ORIGIN_BUSINESS and self.has_audio


class GalleryMediaReader(Protocol):
    def resolve(
        self, *, tenant_id: UUID, brand_id: UUID, refs: Sequence[GalleryRef]
    ) -> dict[GalleryRef, GalleryMedium]:
        """The live media of `refs` that are this brand's, by ref; the rest is absent."""
        ...


def select_segment(
    duration_ms: int | None, wanted_ms: int = CAROUSEL_SEGMENT_MS
) -> tuple[int, int]:
    """The stretch of a video a slide shows, in ms (D2; rule of `gallery-carousel-v1`):

    - the whole video when it lasts no more than the format asks (`wanted_ms`) — in a
      carousel (60 s) that is every Galería video (business ≤ 60 s, products ≤ 15 s);
    - otherwise the stretch of `wanted_ms` that starts at second 0.

    The epic's fallback («o el siguiente si el primero es de menos de 3 s») cannot fire
    with a start at 0 — the first stretch always has the requested length, or is the whole
    video — so a video shorter than `MIN_VIDEO_MS` is left out when the choice is resolved
    (`usable`) rather than shown cut. A video of unknown length is asked for at most
    `wanted_ms`; the producer records the length it actually kept."""
    if wanted_ms <= 0:
        raise ValueError("a stretch has a positive length")
    if duration_ms is None or duration_ms <= 0:
        return 0, wanted_ms
    return 0, min(duration_ms, wanted_ms)


def usable(medium: GalleryMedium) -> bool:
    """Whether a live medium can be a slide: a photo always; a video when it lasts at
    least what Instagram accepts (an unknown length is let through: the producer fits it)."""
    if not medium.is_video:
        return medium.media_type == MEDIA_TYPE_IMAGE
    return medium.duration_ms is None or medium.duration_ms >= MIN_VIDEO_MS


class DbGalleryMedia:
    """`GalleryMediaReader` over Postgres, through the tenant door (RLS)."""

    def resolve(
        self, *, tenant_id: UUID, brand_id: UUID, refs: Sequence[GalleryRef]
    ) -> dict[GalleryRef, GalleryMedium]:
        business = _ids(refs, GALLERY_ORIGIN_BUSINESS)
        product = _ids(refs, GALLERY_ORIGIN_PRODUCT)
        found: dict[GalleryRef, GalleryMedium] = {}
        if not business and not product:
            return found
        with tenant_session(tenant_id) as session:
            if business:
                cutting = set(
                    session.scalars(
                        select(GalleryJob.source_media_id).where(
                            GalleryJob.kind == JOB_CUT,
                            GalleryJob.status.in_(ACTIVE_STATUSES),
                            GalleryJob.source_media_id.in_(business),
                        )
                    )
                )
                rows = session.scalars(
                    select(BusinessMedia).where(
                        BusinessMedia.id.in_(business),
                        BusinessMedia.brand_id == brand_id,
                        BusinessMedia.deleted_at.is_(None),
                    )
                )
                for m in rows:
                    if m.id in cutting:
                        continue
                    medium = GalleryMedium(
                        origin=GALLERY_ORIGIN_BUSINESS,
                        media_id=m.id,
                        media_type=m.media_type,
                        object_key=m.object_key,
                        poster_key=m.poster_key,
                        duration_ms=m.duration_ms,
                        has_audio=bool(m.has_audio),
                    )
                    found[medium.ref] = medium
            if product:
                pairs = session.execute(
                    select(ProductMedia, BrandProduct.name)
                    .join(BrandProduct, BrandProduct.id == ProductMedia.product_id)
                    .where(
                        ProductMedia.id.in_(product),
                        ProductMedia.brand_id == brand_id,
                        BrandProduct.brand_id == brand_id,
                        BrandProduct.is_active.is_(True),
                    )
                ).all()
                for m, name in pairs:
                    duration = (
                        int(round(float(m.duration_sec) * 1000))
                        if m.duration_sec is not None
                        else None
                    )
                    medium = GalleryMedium(
                        origin=GALLERY_ORIGIN_PRODUCT,
                        media_id=m.id,
                        media_type=m.media_type,
                        object_key=m.object_key,
                        poster_key=None,
                        duration_ms=duration if m.media_type == MEDIA_TYPE_VIDEO else None,
                        # D3: a product's clip is normalized without sound — never kept
                        has_audio=False,
                        product_name=str(name or ""),
                    )
                    found[medium.ref] = medium
        return found


def _ids(refs: Iterable[GalleryRef], origin: str) -> list[UUID]:
    return list(dict.fromkeys(r.media_id for r in refs if r.origin == origin))


__all__ = [
    "CAROUSEL_SEGMENT_MS",
    "GALLERY_ASSEMBLY_VERSION",
    "MIN_VIDEO_MS",
    "DbGalleryMedia",
    "GalleryMediaReader",
    "GalleryMedium",
    "GalleryRef",
    "select_segment",
    "usable",
]
