"""The one rule for "may QUA-111 hand this POST to the publisher, and as what?" — pure.

No DB, no storage, no clock. A `PostReader` gathers what it has into a `PostCandidate`
and calls `evaluate`; the calendar card (`PostSummary.is_publishable`) and the executor
(`PostReader.get_publishable`) both come from here, so they cannot disagree.

The checks run in a fixed order and the first failure is THE reason, so the same POST
always gets the same answer. Order: files purged (m-24828907) → approval → approved revision
→ approved copy → category → media count/order/type → category-and-media shape → R2
custody → content type.

MP-11 — one event per output. A POST rendered by the template engine carries several
outputs in `image_assets.output_port` (`reel` video 9:16, `feed` image 4:5, `story` image
9:16). When the candidate names an `output_port`, only that port's media is evaluated
(re-numbered from position 0) and `media_product_type` is derived from the PORT, not from
the POST's category: `reel` → REELS, `feed` → IMAGE, `story` → STORIES (image or video —
the publisher has published image stories since QUA-113). Without a port, the category
contract below applies.

QUA-118 — `compatibility(platform, category, media_types, output_port)` is the one rule
for "can THIS channel take THIS shape, and as what?". It generalises the Instagram-only
`media_product_type_for` so the assign flow can disable an incompatible account with a
typed reason, and it makes the image story programmable by category (`story` + one
image → STORIES), which the publisher has done since QUA-113 (QUA-118 AC 6).

QUA-118 v2 — the DESTINATION is the event's, not the POST's. The POST's category stays the
origin (what the content is); each `calendar_event` says where it goes out: `post`
(«Publicación»), `reel` or `story`. `destination_options` is the one rule for "where may
this content go" — verified against Meta's IG User Media reference
(`reference/meta-instagram-platform`, 2026-10-06):

- one image → Publicación (only inside 4:5…1.91:1, Meta's feed-image range) or Historia;
  never Reel (a reel is a video);
- one video → Reel or Historia. «Publicación» is not offered: since 2023-11-09 the API has
  no feed `VIDEO` — a feed video IS a reel — so the two buttons would do the same thing;
- a carousel (2–10 images/videos) → Publicación only (a story is one item; a reel cannot
  live in a carousel).

A video story longer than 60 s is refused by Meta; the duration is not stored, so that
limit is a warning, never a block. With a destination, `evaluate` derives the
`media_product_type` from it and the media's shape; without one (an event whose POST
could not be backfilled), the category/port rule above still applies.

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
from qualify_api.stock.keys import is_stock_key

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

# Template output ports (`packages/render/CONTRACT.md` §1, `image_assets.output_port`) →
# what the publisher receives, and which single item type each port admits (MP-11).
OUTPUT_PORT_REEL = "reel"
OUTPUT_PORT_FEED = "feed"
OUTPUT_PORT_STORY = "story"
#: promo_producto v2 (2026-10-13): the 1:1 still is a feed post, and the 4:5 / 1:1
#: videos are Reels (Instagram shows a feed video at its own shape, as a Reel).
OUTPUT_PORT_SQUARE = "square"
OUTPUT_PORT_FEED_VIDEO = "feed-video"
OUTPUT_PORT_SQUARE_VIDEO = "square-video"
_PORT_PRODUCT_TYPE: dict[str, tuple[str, frozenset[str]]] = {
    OUTPUT_PORT_REEL: (MEDIA_TYPE_REELS, frozenset({MEDIA_TYPE_VIDEO})),
    OUTPUT_PORT_FEED: (MEDIA_TYPE_IMAGE, frozenset({MEDIA_TYPE_IMAGE})),
    OUTPUT_PORT_STORY: (MEDIA_TYPE_STORIES, frozenset({MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO})),
    OUTPUT_PORT_SQUARE: (MEDIA_TYPE_IMAGE, frozenset({MEDIA_TYPE_IMAGE})),
    OUTPUT_PORT_FEED_VIDEO: (MEDIA_TYPE_REELS, frozenset({MEDIA_TYPE_VIDEO})),
    OUTPUT_PORT_SQUARE_VIDEO: (MEDIA_TYPE_REELS, frozenset({MEDIA_TYPE_VIDEO})),
}
OUTPUT_PORTS: tuple[str, ...] = tuple(_PORT_PRODUCT_TYPE)

# Channels the Planificador can publish to. TikTok scheduled publishing is blocked by the
# platform (ADR 23c) and Facebook has no publisher: only Instagram today (QUA-118).
PLATFORM_INSTAGRAM = "instagram"
SCHEDULABLE_PLATFORMS: frozenset[str] = frozenset({PLATFORM_INSTAGRAM})

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
    R.UNSUPPORTED_SHAPE: "La categoría no corresponde al contenido (p. ej. un reel con dos "
    "archivos, o una salida sin el tipo de archivo que pide).",
    R.CHANNEL_NOT_SUPPORTED: "Esta cuenta no admite publicaciones programadas desde Qualify.",
    R.MEDIA_NOT_IN_R2: "Los archivos del POST todavía no están listos para publicar (R2).",
    R.CONTENT_TYPE_MISSING: "Falta el formato de algún archivo del POST.",
    R.UNSUPPORTED_CONTENT_TYPE: "Formato no admitido: las imágenes deben ser JPEG.",
    R.DESTINATION_NOT_SUPPORTED: "Instagram no publica este contenido en el destino elegido.",
    R.IMAGE_RATIO_NOT_ALLOWED: "Instagram solo acepta en una publicación imágenes entre 4:5 "
    "(vertical) y 1.91:1 (horizontal).",
    R.STOCK_NOT_PUBLISHABLE: "Una imagen de stock no se publica sola: úsala dentro de una pieza.",
    R.MEDIA_DRAFT_PENDING: "El video es todavía un borrador a 480p: espera a que termine el "
    "video final (o reinténtalo desde la publicación).",
    R.MEDIA_PURGED: "Los archivos de esta pieza se eliminaron a los 3 meses: ya no se puede "
    "publicar. Vuelve a generarla.",
}

# ---------------------------------------------------------------------------
# QUA-118 v2: the event's destination

DESTINATION_POST = "post"  # «Publicación»: a feed image or a carousel
DESTINATION_REEL = "reel"
DESTINATION_STORY = "story"
DESTINATIONS: tuple[str, ...] = (DESTINATION_POST, DESTINATION_REEL, DESTINATION_STORY)

# Meta's feed image range (IG User Media, "Image Specifications"): 4:5 to 1.91:1.
FEED_RATIO_MIN = 4 / 5
FEED_RATIO_MAX = 1.91

# Why a destination is not available, in the operator's words (the selector prints it).
DESTINATION_WHY: Mapping[str, str] = {
    "reel_needs_video": "Un Reel necesita un video; esto es una imagen.",
    "reel_not_carousel": "Un Reel es un solo video; no puede ser un carrusel.",
    "story_not_carousel": "Instagram no publica carruseles como Historia.",
    "post_ratio": "Instagram solo acepta en una publicación imágenes entre 4:5 (vertical) "
    "y 1.91:1 (horizontal); esta mide {ratio}.",
    "no_shape": "Este contenido no se puede publicar en Instagram.",
}
STORY_VIDEO_WARNING = (
    "Una Historia de video puede durar como máximo 60 segundos. Si este video es más "
    "largo, Instagram la rechazará al publicar."
)
STORY_CAPTION_NOTE = "Las historias no muestran el texto del POST."


@dataclass(frozen=True)
class DestinationOption:
    """One button of «¿Dónde quieres publicarlo?». `offered=False` → not shown at all
    (a video has no separate «Publicación»); `reason` says why an offered one is off;
    `warning` is what Meta may still refuse that cannot be checked here."""

    destination: str
    offered: bool
    available: bool
    reason: str = ""
    warning: str = ""


def _shape(media_types: tuple[str, ...]) -> str:
    """ "image" / "video" for one item, "carousel" for 2–10, "" for anything else."""
    if len(media_types) == 1 and media_types[0] in (MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO):
        return "image" if media_types[0] == MEDIA_TYPE_IMAGE else "video"
    if 2 <= len(media_types) <= MAX_CAROUSEL_ITEMS and all(
        t in (MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO) for t in media_types
    ):
        return "carousel"
    return ""


def _ratio_label(width: int, height: int) -> str:
    return f"{width}×{height}"


def feed_ratio_ok(image_size: tuple[int, int] | None) -> bool:
    """True when the image fits Meta's feed range, or when its size is unknown (Meta is
    then the one to say — the selector does not block on a guess)."""
    if not image_size or image_size[0] <= 0 or image_size[1] <= 0:
        return True
    ratio = image_size[0] / image_size[1]
    return FEED_RATIO_MIN - 0.005 <= ratio <= FEED_RATIO_MAX + 0.005


def destination_options(
    media_types: tuple[str, ...], image_size: tuple[int, int] | None = None
) -> tuple[DestinationOption, ...]:
    """Where content of this shape may go, in the selector's order (Publicación, Reel,
    Historia). `media_types` is the publisher's vocabulary (IMAGE / VIDEO)."""
    shape = _shape(media_types)
    post = DestinationOption(DESTINATION_POST, True, False, DESTINATION_WHY["no_shape"])
    reel = DestinationOption(DESTINATION_REEL, True, False, DESTINATION_WHY["no_shape"])
    story = DestinationOption(DESTINATION_STORY, True, False, DESTINATION_WHY["no_shape"])
    if shape == "image":
        if feed_ratio_ok(image_size):
            post = DestinationOption(DESTINATION_POST, True, True)
        else:
            w, h = image_size  # type: ignore[misc]
            why = DESTINATION_WHY["post_ratio"].format(ratio=_ratio_label(w, h))
            post = DestinationOption(DESTINATION_POST, True, False, why)
        reel = DestinationOption(DESTINATION_REEL, True, False, DESTINATION_WHY["reel_needs_video"])
        story = DestinationOption(DESTINATION_STORY, True, True)
    elif shape == "video":
        post = DestinationOption(DESTINATION_POST, False, False)
        reel = DestinationOption(DESTINATION_REEL, True, True)
        story = DestinationOption(DESTINATION_STORY, True, True, warning=STORY_VIDEO_WARNING)
    elif shape == "carousel":
        post = DestinationOption(DESTINATION_POST, True, True)
        reel = DestinationOption(
            DESTINATION_REEL, True, False, DESTINATION_WHY["reel_not_carousel"]
        )
        story = DestinationOption(
            DESTINATION_STORY, True, False, DESTINATION_WHY["story_not_carousel"]
        )
    return (post, reel, story)


def destination_product_type(destination: str, media_types: tuple[str, ...]) -> str | None:
    """What the publisher receives for `destination` and this shape, or None when that
    destination cannot take it. Size is not looked at here (see `evaluate`)."""
    shape = _shape(media_types)
    if destination == DESTINATION_POST:
        return {"image": MEDIA_TYPE_IMAGE, "carousel": MEDIA_TYPE_CAROUSEL}.get(shape)
    if destination == DESTINATION_REEL:
        return MEDIA_TYPE_REELS if shape == "video" else None
    if destination == DESTINATION_STORY:
        return MEDIA_TYPE_STORIES if shape in ("image", "video") else None
    return None


def destination_for_product_type(media_product_type: str | None) -> str | None:
    """The destination an event already had before destinations existed: what its
    category (or port) published as. IMAGE/CAROUSEL → post, REELS → reel, STORIES →
    story; None when the POST was not publishable."""
    return {
        MEDIA_TYPE_IMAGE: DESTINATION_POST,
        MEDIA_TYPE_CAROUSEL: DESTINATION_POST,
        MEDIA_TYPE_REELS: DESTINATION_REEL,
        MEDIA_TYPE_STORIES: DESTINATION_STORY,
    }.get(media_product_type or "")


@dataclass(frozen=True)
class MediaCandidate:
    """One asset as the POST stores it (not yet checked)."""

    object_key: str | None
    content_type: str | None
    media_type: str  # the POST's own vocabulary: "image" / "video"
    position: int
    output_port: str | None = None  # `image_assets.output_port` (0038), None before MP-11
    width: int | None = None  # `image_assets.width/height`, when the POST recorded them
    height: int | None = None
    #: m-24820142: a 480p Seedance draft whose 1080p final is not in place yet.
    draft_pending: bool = False


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
    # MP-11: evaluate ONE output (only media with this `output_port`), or the whole POST.
    output_port: str | None = None
    # QUA-118 v2: the event's destination (`post` / `reel` / `story`); None → derive the
    # product type from the category (or the port), the pre-destination rule.
    destination: str | None = None
    # m-24828907: the retention rule deleted the files (`content_drafts.media_purged_at`).
    media_purged: bool = False


def _refuse(
    candidate: PostCandidate, reason: UnpublishableReason, detail: str = ""
) -> NotPublishable:
    return NotPublishable(
        post_id=candidate.post_id,
        reason=reason,
        detail=detail,
        output_port=candidate.output_port,
    )


@dataclass(frozen=True)
class Compatibility:
    """What one channel receives for one POST shape (QUA-118): the publisher's
    `media_product_type`, or the typed reason that channel cannot take it."""

    media_product_type: str | None
    reason: UnpublishableReason | None = None

    @property
    def ok(self) -> bool:
        return self.media_product_type is not None


def _shape_product_type(
    category: str, media_types: tuple[str, ...], output_port: str | None
) -> str | None:
    count = len(media_types)
    single = media_types[0] if count == 1 else None
    if output_port is not None:
        if output_port not in _PORT_PRODUCT_TYPE:
            return None
        product_type, admitted = _PORT_PRODUCT_TYPE[output_port]
        return product_type if single in admitted else None
    if category == PostCategory.GALERIA.value:
        if single == MEDIA_TYPE_IMAGE:
            return MEDIA_TYPE_IMAGE
        if 2 <= count <= MAX_CAROUSEL_ITEMS:
            return MEDIA_TYPE_CAROUSEL  # any mix of IMAGE/VIDEO (QUA-103)
        return None  # a lone video in a galería is a reel, not a guess
    if category == PostCategory.REEL.value:
        return MEDIA_TYPE_REELS if single == MEDIA_TYPE_VIDEO else None
    if category == PostCategory.STORY.value:
        # One image OR one video: the publisher has published image stories since
        # QUA-113 (`is_image_story`). Widened by category on 2026-10-05 (QUA-118 AC 6),
        # the decision MP-11 had left open; before that only the `story` output port
        # reached an image story.
        return MEDIA_TYPE_STORIES if single in (MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO) else None
    return None


def compatibility(
    platform: str,
    category: str,
    media_types: tuple[str, ...],
    output_port: str | None = None,
) -> Compatibility:
    """QUA-109's category contract (`PostCategory`: galería → IMAGE/CAROUSEL, story →
    STORIES, reel → REELS) restricted to what `PublishService` can actually publish on
    `platform`. There is no default branch: a category this function does not name
    never becomes a reel, and a platform it does not name never gets an event.

    With `output_port` (MP-11) the PORT decides, not the category: `reel` → REELS (one
    video), `feed` → IMAGE (one image), `story` → STORIES (one image or one video). An
    unknown port is never published."""
    if platform not in SCHEDULABLE_PLATFORMS:
        return Compatibility(None, R.CHANNEL_NOT_SUPPORTED)
    product_type = _shape_product_type(category, media_types, output_port)
    if product_type is None:
        return Compatibility(None, R.UNSUPPORTED_SHAPE)
    return Compatibility(product_type)


def media_product_type_for(
    category: str, media_types: tuple[str, ...], output_port: str | None = None
) -> str | None:
    """`compatibility` for Instagram, as the evaluator reads it: the product type, or None
    when that combination is not publishable."""
    return compatibility(PLATFORM_INSTAGRAM, category, media_types, output_port).media_product_type


def _position(item: MediaCandidate) -> int:
    return item.position


def _port_media(media: tuple[MediaCandidate, ...], output_port: str) -> tuple[MediaCandidate, ...]:
    """Only the port's assets, re-numbered from position 0 in their own order, so a
    single-item port always lands as one item at position 0 whatever slot it occupied in
    the POST."""
    own = sorted((item for item in media if item.output_port == output_port), key=_position)
    return tuple(
        MediaCandidate(
            object_key=item.object_key,
            content_type=item.content_type,
            media_type=item.media_type,
            position=index,
            output_port=item.output_port,
            draft_pending=item.draft_pending,
        )
        for index, item in enumerate(own)
    )


def evaluate(candidate: PostCandidate) -> PublishablePost | NotPublishable:
    # First: no other check matters once the files are gone, and the key prefix check
    # below would still pass on a purged piece (its keys look right, the bytes are gone).
    if candidate.media_purged:
        return _refuse(candidate, R.MEDIA_PURGED)
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

    port = candidate.output_port
    media = _port_media(candidate.media, port) if port is not None else candidate.media
    if not media:
        return _refuse(candidate, R.NO_MEDIA, f"port {port}" if port else "")
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

    if candidate.destination is not None:
        # QUA-118 v2: the event's destination decides, over the media's shape.
        media_product_type = destination_product_type(candidate.destination, tuple(publisher_types))
        if media_product_type is None:
            return _refuse(
                candidate,
                R.DESTINATION_NOT_SUPPORTED,
                f"{candidate.destination} with {', '.join(publisher_types)}",
            )
        first = ordered[0]
        if media_product_type == MEDIA_TYPE_IMAGE and not feed_ratio_ok(
            (first.width, first.height) if first.width and first.height else None
        ):
            return _refuse(candidate, R.IMAGE_RATIO_NOT_ALLOWED, f"{first.width}x{first.height}")
    else:
        media_product_type = media_product_type_for(category, tuple(publisher_types), port)
        if media_product_type is None:
            shape = f"{category} with {', '.join(publisher_types)}"
            return _refuse(
                candidate, R.UNSUPPORTED_SHAPE, f"port {port} ({shape})" if port else shape
            )

    items: list[PublishableMedia] = []
    for item, publisher_type in zip(ordered, publisher_types, strict=True):
        if not item.object_key:
            return _refuse(candidate, R.MEDIA_NOT_IN_R2, f"position {item.position}")
        if item.draft_pending:
            return _refuse(candidate, R.MEDIA_DRAFT_PENDING, f"position {item.position}")
        try:
            require_tenant_prefix(candidate.tenant_id, item.object_key)
        except TenantPrefixViolation:
            return _refuse(candidate, R.MEDIA_NOT_IN_R2, f"position {item.position}")
        if is_stock_key(item.object_key):
            # unreachable today (only `image_assets` rows are published): defence in depth
            # should a route ever copy an input to its output
            return _refuse(candidate, R.STOCK_NOT_PUBLISHABLE, f"position {item.position}")
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
        provenance=(
            *candidate.provenance,
            *((("output_port", port),) if port is not None else ()),
            *((("destination", candidate.destination),) if candidate.destination else ()),
        ),
        output_port=port,
    )
