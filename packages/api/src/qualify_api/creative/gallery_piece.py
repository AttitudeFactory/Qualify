"""«Crear publicación con estas» on the server (CM-6, m-24955927; epic m-24955913 §5): a
carousel made from the photos and videos the owner chose in Galería, used as they are.

The API the /create screen (CM-7) calls with `?medios=`:

- `parse_media_query(raw)` / `format_media_query(refs)` — the `medios` value, one item per
  medium in the owner's order, `n:<uuid>` for the business's (`business_media`) and
  `p:<uuid>` for a product's (`product_media`), comma-separated. CM-5 writes it; a
  malformed item is counted, never an error.
- `GalleryPieces.selection(...)` — what /create shows before generating: the media still
  live and of this brand, in order, each with its thumbnail and length; how many of the
  chosen were left out (`dropped` → `DROPPED_TEXT`); whether the sound switch is offered
  (`offers_sound`: a business video saved with its sound, D1).
- `GalleryPieces.create(...)` — the draft: the screen's brief (topic, objective, angle,
  format…) with the chosen media as `SlideSource.GALLERY` slides, the owner's sound
  choice (`use_audio`, off by default, D6) and the segment rule (`select_segment`), then
  `ContentService.create_draft` — the same path, quota check and dispatch as any piece.
  The draft ends in «Por aprobar» and is never scheduled on its own.

Rules (epic §2-§3, CM-6 criteria):

- **Validation under RLS:** every medium is looked up through `tenant_session`, filtered
  by brand and liveness (`gallery_media.DbGalleryMedia`); one of another business, removed,
  being cut, of an inactive product, malformed, repeated or past the tenth is left out
  without an error. Fewer than 2 left → `NotEnoughMedia` (a carousel is 2-10 items).
- **Segment (D2):** `select_segment` — the whole video when it fits the format (a carousel
  plays 60 s: every Galería video), else the stretch from second 0; kept on the slide.
- **Sound (D1/D3/D6):** a business video keeps its sound only when the owner turned it on;
  a product's video never does. A carousel has no generated voice, so nothing mutes it.
- **Own copy (ADR 39):** the producer copies each file into `generated/{draft}/` while it
  fits it to the format, so removing it from Galería never breaks the piece.
- **Provenance:** the brief keeps each slide's origin, id, file, segment and sound, plus
  `gallery_assembly_version`; each asset repeats them in its params.
- **Quota (D5):** `weight_for` prices a carousel by its GENERATED slides — none here — so
  it is one creation (`carousel_by_images` first step) and no video seconds, now or at
  approval (`_videos_of` counts only animated slides). Pinned by tests.
- **No client file reaches a model:** the copy prompt gets one line per slide
  (`render._gallery_slide_line`), never the bytes; nothing goes to BytePlus.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from qualify_creative.enums import ContentKind, ImageRoute, SlideSource
from qualify_creative.schemas import (
    CAROUSEL_MAX_SLIDES,
    CAROUSEL_MIN_SLIDES,
    GALLERY_ORIGIN_BUSINESS,
    GALLERY_ORIGIN_PRODUCT,
    CarouselSlide,
    ContentBrief,
    MediaInputs,
)

from qualify_api.creative.gallery_media import (
    CAROUSEL_SEGMENT_MS,
    GALLERY_ASSEMBLY_VERSION,
    DbGalleryMedia,
    GalleryMediaReader,
    GalleryMedium,
    GalleryRef,
    select_segment,
    usable,
)

if TYPE_CHECKING:  # the service imports media.py, which imports gallery_media
    from qualify_api.creative.service import ContentService

logger = logging.getLogger(__name__)

#: The `medios` query parameter (CM-5 → CM-7) and its item prefixes.
MEDIA_QUERY_PARAM = "medios"
_PREFIX_TO_ORIGIN = {"n": GALLERY_ORIGIN_BUSINESS, "p": GALLERY_ORIGIN_PRODUCT}
_ORIGIN_TO_PREFIX = {origin: prefix for prefix, origin in _PREFIX_TO_ORIGIN.items()}
#: More items than this in a query is not a selection the screen made: the rest is ignored.
_MAX_QUERY_ITEMS = 50

#: What the owner reads (qualify-copy-es). CM-7 shows `DROPPED_TEXT` as is (its criterion).
DROPPED_TEXT = "Una foto o video que elegiste ya no está en tu Galería; la dejamos fuera."
NOT_ENOUGH_MEDIA_TEXT = (
    "Para un carrusel necesitas al menos 2 fotos o videos de tu Galería. "
    "Vuelve a Galería y elige al menos uno más."
)


class NotEnoughMedia(ValueError):
    """Fewer than 2 of the chosen media are usable: no carousel, nothing created or
    charged. `args[0]` is the Spanish text the screen shows."""

    def __init__(self, usable_count: int, dropped: int) -> None:
        super().__init__(NOT_ENOUGH_MEDIA_TEXT)
        self.usable_count = usable_count
        self.dropped = dropped


@dataclass(frozen=True)
class ParsedMediaQuery:
    refs: tuple[GalleryRef, ...]
    #: Items that were not `n:<uuid>` / `p:<uuid>`.
    malformed: int = 0


def parse_media_query(raw: str | Sequence[str] | None) -> ParsedMediaQuery:
    """The refs of a `medios` value, in order. Accepts the value as Reflex hands it (one
    string, or a list when the parameter repeats). Never raises."""
    if raw is None:
        return ParsedMediaQuery(())
    joined = raw if isinstance(raw, str) else ",".join(str(v) for v in raw)
    items = [item.strip() for item in joined.split(",") if item.strip()]
    refs: list[GalleryRef] = []
    malformed = 0
    for item in items[:_MAX_QUERY_ITEMS]:
        prefix, sep, value = item.partition(":")
        origin = _PREFIX_TO_ORIGIN.get(prefix.strip().lower())
        try:
            media_id = UUID(value.strip()) if sep and origin else None
        except ValueError:
            media_id = None
        if origin is None or media_id is None:
            malformed += 1
            continue
        refs.append(GalleryRef(origin, media_id))
    malformed += max(0, len(items) - _MAX_QUERY_ITEMS)
    return ParsedMediaQuery(tuple(refs), malformed)


def format_media_query(refs: Sequence[GalleryRef]) -> str:
    """The `medios` value of `refs`, in order (what CM-5's «Crear publicación con estas»
    puts in `/create?medios=…`)."""
    return ",".join(f"{_ORIGIN_TO_PREFIX[r.origin]}:{r.media_id}" for r in refs)


@dataclass(frozen=True)
class GallerySelection:
    """The chosen media as /create shows them and the piece uses them."""

    media: tuple[GalleryMedium, ...]
    #: How many chosen items were left out: gone, another business's, malformed, a video
    #: too short for Instagram, or past the tenth. Repeats are not counted.
    dropped: int = 0

    @property
    def enough(self) -> bool:
        return len(self.media) >= CAROUSEL_MIN_SLIDES

    @property
    def offers_sound(self) -> bool:
        """Whether «Usar el sonido de tus videos» is shown (CM-7): a business video with
        its own sound is among the chosen."""
        return any(m.keeps_sound for m in self.media)

    @property
    def dropped_text(self) -> str:
        return DROPPED_TEXT if self.dropped else ""


def resolve_selection(
    reader: GalleryMediaReader,
    *,
    tenant_id: UUID,
    brand_id: UUID,
    query: ParsedMediaQuery,
) -> GallerySelection:
    """The usable media of `query`, in the owner's order, at most 10 (Instagram)."""
    ordered = tuple(dict.fromkeys(query.refs))  # a repeated item is used once
    live = reader.resolve(tenant_id=tenant_id, brand_id=brand_id, refs=ordered) if ordered else {}
    kept: list[GalleryMedium] = []
    dropped = query.malformed
    for ref in ordered:
        medium = live.get(ref)
        if medium is None or not usable(medium) or len(kept) >= CAROUSEL_MAX_SLIDES:
            dropped += 1
            continue
        kept.append(medium)
    if dropped:
        logger.info(
            "gallery selection: %d kept, %d left out (brand %s)", len(kept), dropped, brand_id
        )
    return GallerySelection(tuple(kept), dropped)


def gallery_slides(selection: GallerySelection, *, use_audio: bool) -> tuple[CarouselSlide, ...]:
    """One `GALLERY` slide per medium, in order: a photo as it is; a video with its
    segment (`select_segment`) and its sound only when the owner asked for it and the
    medium has it (a business video)."""
    slides: list[CarouselSlide] = []
    for medium in selection.media:
        if medium.is_video:
            start, end = select_segment(medium.duration_ms, CAROUSEL_SEGMENT_MS)
            slides.append(
                CarouselSlide(
                    source=SlideSource.GALLERY,
                    object_key=medium.object_key,
                    gallery_origin=medium.origin,
                    gallery_media_id=medium.media_id,
                    segment_start_ms=start,
                    segment_end_ms=end,
                    audio=use_audio and medium.keeps_sound,
                )
            )
        else:
            slides.append(
                CarouselSlide(
                    source=SlideSource.GALLERY,
                    object_key=medium.object_key,
                    gallery_origin=medium.origin,
                    gallery_media_id=medium.media_id,
                )
            )
    return tuple(slides)


def gallery_brief(
    base: ContentBrief,
    selection: GallerySelection,
    *,
    use_audio: bool = False,
    closing_slide: bool = False,
) -> ContentBrief:
    """The screen's brief made a Galería carousel: its words (topic, objective, angle,
    must-mention…) as the owner set them; kind `CAROUSEL`, its format if a carousel offers
    it (else 4:5); the owner's own media placed untouched (`FROM_UPLOAD`, keyed on the
    first); the slides; the sound choice and the assembly version. Media inputs of other
    kinds are dropped — this piece reads nothing else. When the chosen product media are
    all of one product and the brief names none, it names that one, so the copy knows it.
    Raises `NotEnoughMedia` below 2 media and the brief's own `ValidationError` otherwise."""
    if not selection.enough:
        raise NotEnoughMedia(len(selection.media), selection.dropped)
    slides = gallery_slides(selection, use_audio=use_audio)
    if closing_slide and len(slides) >= CAROUSEL_MAX_SLIDES:
        closing_slide = False  # ten media already fill the carousel
    products = {m.product_name for m in selection.media if m.origin == GALLERY_ORIGIN_PRODUCT}
    product_ref = base.product_ref
    if not product_ref and len(products) == 1:
        product_ref = next(iter(products)) or None
    fmt = base.format if base.format in ContentKind.CAROUSEL.formats else None
    media = MediaInputs(
        slides=slides,
        closing_slide=closing_slide,
        gallery_audio=use_audio,
        gallery_assembly_version=GALLERY_ASSEMBLY_VERSION,
    )
    return ContentBrief.model_validate(
        {
            **base.model_dump(exclude={"media", "kind", "format", "image_route"}),
            "product_ref": product_ref,
            "kind": ContentKind.CAROUSEL,
            "format": fmt or ContentKind.CAROUSEL.default_format,
            "image_route": ImageRoute.FROM_UPLOAD,
            "source_media_key": selection.media[0].object_key,
            "video_plan": None,
            "media": media,
        }
    )


@dataclass(frozen=True)
class GalleryCreation:
    """What `GalleryPieces.create` made: the draft (in «Por aprobar» once generated), the
    selection it used and how many chosen media were left out (→ `DROPPED_TEXT`)."""

    draft_id: UUID
    selection: GallerySelection

    @property
    def dropped(self) -> int:
        return self.selection.dropped


class GalleryPieces:
    """CM-6's entry point for the /create screen (CM-7)."""

    def __init__(
        self, *, content: ContentService, reader: GalleryMediaReader | None = None
    ) -> None:
        self._content = content
        self._reader: GalleryMediaReader = reader or DbGalleryMedia()

    def selection(
        self, *, tenant_id: UUID, brand_id: UUID, medios: str | Sequence[str] | None
    ) -> GallerySelection:
        """What /create shows for `?medios=`: the usable media in order and what was
        left out. Never raises for a bad query (an empty selection instead)."""
        return resolve_selection(
            self._reader,
            tenant_id=tenant_id,
            brand_id=brand_id,
            query=parse_media_query(medios),
        )

    def create(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID,
        brief: ContentBrief,
        medios: str | Sequence[str] | None,
        use_audio: bool = False,
        closing_slide: bool = False,
        request_key: UUID | None = None,
    ) -> GalleryCreation:
        """Resolve `medios` again (the screen's copy may be minutes old), build the
        carousel brief and create the draft through `ContentService.create_draft` —
        readiness, route policy, the month's creations (one, D5) and the dispatch are its.
        `request_key` makes it idempotent, as there. Raises `NotEnoughMedia`, and what
        `create_draft` raises (`BrandNotReady`, `NotEnoughCreations`, …)."""
        selection = self.selection(tenant_id=tenant_id, brand_id=brand_id, medios=medios)
        carousel = gallery_brief(brief, selection, use_audio=use_audio, closing_slide=closing_slide)
        draft_id = self._content.create_draft(
            tenant_id=tenant_id,
            brand_id=brand_id,
            brief=carousel,
            user_id=user_id,
            request_key=request_key,
        )
        return GalleryCreation(draft_id=draft_id, selection=selection)


def production_gallery_pieces(content: ContentService) -> GalleryPieces:
    """The real wiring: the composed content service and the Postgres reader."""
    return GalleryPieces(content=content, reader=DbGalleryMedia())


__all__ = [
    "DROPPED_TEXT",
    "MEDIA_QUERY_PARAM",
    "NOT_ENOUGH_MEDIA_TEXT",
    "GalleryCreation",
    "GalleryPieces",
    "GallerySelection",
    "NotEnoughMedia",
    "ParsedMediaQuery",
    "format_media_query",
    "gallery_brief",
    "gallery_slides",
    "parse_media_query",
    "production_gallery_pieces",
    "resolve_selection",
]
