"""The one rule for "may QUA-111 hand this POST to the publisher, and as what?" — pure.

No DB, no storage, no clock. A `PostReader` gathers what it has into a `PostCandidate`
and calls `evaluate`; the calendar card (`PostSummary.is_publishable`) and the executor
(`PostReader.get_publishable`) both come from here, so they cannot disagree.

The checks run in a fixed order and the first failure is THE reason, so the same POST
always gets the same answer. Order: approval → approved revision → approved copy →
category → media count/order/type → category-and-media shape → R2 custody → content type.

What this does NOT decide, on purpose (QUA-109/110 contract gaps, recorded in QUA-111):
- whether the approved copy/category is the one the human saw — only `revision ==
  approved_revision` is checkable, and `category` changes do not bump `revision` today;
- whether the media was rendered from the approved variant;
- whether each object actually exists in R2 — the key's tenant prefix is checked, the
  object is the POST owner's guarantee.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from qualify_creative.enums import PostCategory
from qualify_shared.objects.keys import TenantPrefixViolation, require_tenant_prefix

from qualify_api.planner.post_reader import (
    ApprovalStatus,
    NotPublishable,
    PublishableMedia,
    PublishablePost,
    UnpublishableReason,
)
from qualify_api.publishing.client import (
    IMAGE_CONTENT_TYPE,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_REELS,
    MEDIA_TYPE_STORIES,
    MEDIA_TYPE_VIDEO,
)
from qualify_api.publishing.service import MAX_CAROUSEL_ITEMS, MEDIA_TYPE_CAROUSEL

R = UnpublishableReason

# A POST asset's `media_type` (creative's `image_assets`, 0026) → the publisher's.
_PUBLISHER_MEDIA_TYPE: dict[str, str] = {"image": MEDIA_TYPE_IMAGE, "video": MEDIA_TYPE_VIDEO}

# What the publisher can send per item type. IMAGE is Meta's JPEG-only rule, already
# enforced by the staging service; video goes up as bytes, MP4/MOV being what Meta takes.
_ALLOWED_CONTENT_TYPES: dict[str, frozenset[str]] = {
    MEDIA_TYPE_IMAGE: frozenset({IMAGE_CONTENT_TYPE}),
    MEDIA_TYPE_VIDEO: frozenset({"video/mp4", "video/quicktime"}),
}

# Categories that exist in QUA-109's vocabulary but are never published by this executor.
_NEVER_PUBLISHED: frozenset[str] = frozenset({PostCategory.TIKTOK_VIDEO.value})

REASON_TEXT: Mapping[UnpublishableReason, str] = {
    R.POST_NOT_FOUND: "El POST ya no existe o no es visible.",
    R.NOT_APPROVED: "El POST no está aprobado.",
    R.REVISION_NOT_APPROVED: "El POST se editó después de aprobarse: hay que aprobarlo de nuevo.",
    R.APPROVED_COPY_MISSING: "No se encuentra el texto aprobado del POST.",
    R.CATEGORY_MISSING: "El POST no tiene categoría.",
    R.CATEGORY_NOT_PUBLISHABLE: "Esta categoría no se puede publicar automáticamente.",
    R.NO_MEDIA: "El POST no tiene imágenes ni video.",
    R.TOO_MANY_MEDIA: f"Una galería admite como máximo {MAX_CAROUSEL_ITEMS} elementos.",
    R.MEDIA_ORDER_AMBIGUOUS: "El orden de los elementos del POST es ambiguo.",
    R.UNSUPPORTED_MEDIA_TYPE: "El POST tiene un tipo de archivo que no se publica.",
    R.UNSUPPORTED_SHAPE: "La categoría no corresponde al contenido (p. ej. story de imagen).",
    R.MEDIA_NOT_IN_R2: "Los archivos del POST todavía no están listos para publicar (R2).",
    R.CONTENT_TYPE_MISSING: "Falta el formato de algún archivo del POST.",
    R.UNSUPPORTED_CONTENT_TYPE: "Formato no admitido: las imágenes deben ser JPEG.",
}


@dataclass(frozen=True)
class MediaCandidate:
    """One asset as the POST stores it (not yet checked)."""

    object_key: str | None
    content_type: str | None
    media_type: str  # the POST's own vocabulary: "image" / "video"
    position: int


@dataclass(frozen=True)
class PostCandidate:
    """Everything `evaluate` looks at, read from the POST by a `PostReader`. `caption` is
    None when the approved copy could not be read."""

    tenant_id: UUID
    post_id: UUID
    brand_id: UUID
    approval: ApprovalStatus
    revision: int
    approved_revision: int | None
    category: str | None
    caption: str | None
    media: tuple[MediaCandidate, ...]
    requires_ai_disclosure: bool = False
    provenance: tuple[tuple[str, str], ...] = ()


def _refuse(
    candidate: PostCandidate, reason: UnpublishableReason, detail: str = ""
) -> NotPublishable:
    return NotPublishable(post_id=candidate.post_id, reason=reason, detail=detail)


def media_product_type_for(category: str, media_types: tuple[str, ...]) -> str | None:
    """QUA-109's category contract (`PostCategory`: galería → IMAGE/CAROUSEL, story →
    STORIES, reel → REELS) restricted to what `PublishService` can actually publish.
    None = that combination is not publishable. There is no default branch: a category
    this function does not name never becomes a reel."""
    count = len(media_types)
    single = media_types[0] if count == 1 else None
    if category == PostCategory.GALERIA.value:
        if single == MEDIA_TYPE_IMAGE:
            return MEDIA_TYPE_IMAGE
        if 2 <= count <= MAX_CAROUSEL_ITEMS:
            return MEDIA_TYPE_CAROUSEL  # any mix of IMAGE/VIDEO (QUA-103)
        return None  # a lone video in a galería is a reel, not a guess
    if category == PostCategory.REEL.value:
        return MEDIA_TYPE_REELS if single == MEDIA_TYPE_VIDEO else None
    if category == PostCategory.STORY.value:
        # The publisher has no image story (`create_image_container` takes no media type).
        return MEDIA_TYPE_STORIES if single == MEDIA_TYPE_VIDEO else None
    return None


def evaluate(candidate: PostCandidate) -> PublishablePost | NotPublishable:
    if candidate.approval is not ApprovalStatus.APPROVED or candidate.approved_revision is None:
        return _refuse(candidate, R.NOT_APPROVED)
    if candidate.revision != candidate.approved_revision:
        return _refuse(
            candidate,
            R.REVISION_NOT_APPROVED,
            f"revision {candidate.revision}, approved {candidate.approved_revision}",
        )
    if candidate.caption is None:
        return _refuse(candidate, R.APPROVED_COPY_MISSING)

    category = candidate.category
    if not category:
        return _refuse(candidate, R.CATEGORY_MISSING)
    if category in _NEVER_PUBLISHED or category not in {c.value for c in PostCategory}:
        return _refuse(candidate, R.CATEGORY_NOT_PUBLISHABLE, category)

    media = candidate.media
    if not media:
        return _refuse(candidate, R.NO_MEDIA)
    if len(media) > MAX_CAROUSEL_ITEMS:
        return _refuse(candidate, R.TOO_MANY_MEDIA, str(len(media)))
    positions = [item.position for item in media]
    if len(set(positions)) != len(positions):
        return _refuse(candidate, R.MEDIA_ORDER_AMBIGUOUS)
    ordered = sorted(media, key=lambda item: item.position)

    publisher_types: list[str] = []
    for item in ordered:
        publisher_type = _PUBLISHER_MEDIA_TYPE.get(item.media_type)
        if publisher_type is None:
            return _refuse(candidate, R.UNSUPPORTED_MEDIA_TYPE, item.media_type)
        publisher_types.append(publisher_type)

    media_product_type = media_product_type_for(category, tuple(publisher_types))
    if media_product_type is None:
        return _refuse(
            candidate, R.UNSUPPORTED_SHAPE, f"{category} with {', '.join(publisher_types)}"
        )

    items: list[PublishableMedia] = []
    for item, publisher_type in zip(ordered, publisher_types, strict=True):
        if not item.object_key:
            return _refuse(candidate, R.MEDIA_NOT_IN_R2, f"position {item.position}")
        try:
            require_tenant_prefix(candidate.tenant_id, item.object_key)
        except TenantPrefixViolation:
            return _refuse(candidate, R.MEDIA_NOT_IN_R2, f"position {item.position}")
        if not item.content_type:
            return _refuse(candidate, R.CONTENT_TYPE_MISSING, f"position {item.position}")
        if item.content_type not in _ALLOWED_CONTENT_TYPES[publisher_type]:
            return _refuse(candidate, R.UNSUPPORTED_CONTENT_TYPE, item.content_type)
        items.append(
            PublishableMedia(
                object_key=item.object_key,
                content_type=item.content_type,
                media_type=publisher_type,
                position=item.position,
            )
        )

    return PublishablePost(
        tenant_id=candidate.tenant_id,
        post_id=candidate.post_id,
        brand_id=candidate.brand_id,
        approved_revision=candidate.approved_revision,
        caption=candidate.caption,
        media_product_type=media_product_type,
        media=tuple(items),
        requires_ai_disclosure=candidate.requires_ai_disclosure,
        provenance=candidate.provenance,
    )
