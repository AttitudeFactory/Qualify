"""The seam between «Crear» with Galería media (CM-7) and CM-6's `GalleryPieces`.

Thin: every rule (RLS validation of each chosen medium, at most 10, the segment of a
video, the sound rule, one creation of the month, the copy of the media into the piece,
landing in «Por aprobar») is `qualify_api.creative.gallery_piece`'s. Blocking functions:
callers on the event loop run them with `asyncio.to_thread`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from qualify_api.creative.composition import production_content_service
from qualify_api.creative.gallery_piece import (
    GallerySelection,
    NotEnoughMedia,
    production_gallery_pieces,
)
from qualify_creative.enums import BriefIntent, BriefObjective
from qualify_creative.schemas import ContentKind

from .create_gallery_vm import DEFAULT_TOPIC, ChosenVM, chosen_tiles, kind_label
from .creative_provider import build_brief
from .r2_media import issue_view_path

logger = logging.getLogger(__name__)

__all__ = ["GalleryChoice", "NotEnoughMedia", "create_gallery_piece", "gallery_choice"]


@dataclass(frozen=True)
class GalleryChoice:
    tiles: tuple[ChosenVM, ...]
    kind: str
    dropped: int
    offers_sound: bool
    single: bool


def _pieces():
    return production_gallery_pieces(production_content_service())


def _view_path(tenant_id: UUID):
    def mint(key: str, kind: str) -> str:
        try:
            return issue_view_path(tenant_id, key, kind)
        except Exception as exc:  # noqa: BLE001 — a thumbnail is not worth the screen
            logger.warning("create gallery view token not issued: %s", type(exc).__name__)
            return ""

    return mint


def _choice(selection: GallerySelection, tenant_id: UUID) -> GalleryChoice:
    return GalleryChoice(
        tiles=tuple(chosen_tiles(selection.media, _view_path(tenant_id))),
        kind=kind_label(selection.media) if selection.media else "",
        dropped=selection.dropped,
        offers_sound=selection.offers_sound,
        single=selection.is_single,
    )


def gallery_choice(tenant_id: UUID, brand_id: UUID, medios: str) -> GalleryChoice:
    """Blocking (DB + Redis): what /create shows for `?medios=` — the usable media in the
    owner's order, validated under RLS (another business's, removed or malformed items
    are left out and counted)."""
    selection = _pieces().selection(tenant_id=tenant_id, brand_id=brand_id, medios=medios)
    return _choice(selection, tenant_id)


def create_gallery_piece(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID,
    *,
    medios: str,
    topic: str,
    use_audio: bool,
    request_key: UUID,
) -> tuple[UUID, int]:
    """Blocking: create the piece (draft id, how many chosen items were left out). The
    screen's base brief only carries the owner's words — `gallery_brief` makes it the
    carousel (or the single image / Reel) with their media. `request_key` makes a second
    tap the same piece. Raises `NotEnoughMedia` and what `create_draft` raises."""
    base = build_brief(
        brand_id,
        objective=BriefObjective.CONSIDERATION.value,
        content_type="product",
        topic=topic.strip() or DEFAULT_TOPIC,
        product_ref="",
        intent=BriefIntent.ORGANIC.value,
        image_route="",
        source_media_key="",
        must_mention="",
        must_avoid="",
        # a neutral base: its kind, format and media are replaced by the carousel's
        kind=ContentKind.STATIC_FLYER.value,
        media={},
    )
    created = _pieces().create(
        tenant_id=tenant_id,
        brand_id=brand_id,
        user_id=user_id,
        brief=base,
        medios=medios,
        use_audio=use_audio,
        request_key=request_key,
    )
    return created.draft_id, created.dropped
