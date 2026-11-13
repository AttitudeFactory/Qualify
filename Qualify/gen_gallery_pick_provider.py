"""The seam between the generator's «Elegir de tu Galería» (m-24985141) and the Galería.

What the drawer offers is read like CM-5's «Elegir para una publicación»
(`catalog_gallery_provider.load_gallery` + `catalog_provider.list_products`). What it adds is
resolved again HERE, on the server, under RLS (`DbGalleryMedia.resolve`, CM-6): the browser
only sends `n:<uuid>` / `p:<uuid>` tokens, so another business's medium, a removed one or a
video being cut never reaches the piece.

A business medium (`gallery/{tenant}/…`, R2) is COPIED into the owner's uploads
(`t/{tenant}/uploads/gallery/…`) when it is added — the way CM-6 copies the media into the
piece — so deleting it from the Galería later never breaks a new version of this piece. A
product's medium is the catalog's own file, kept as the catalog's photos always were.
Blocking functions: callers on the event loop run them with `asyncio.to_thread`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from qualify_api.creative.gallery_media import DbGalleryMedia, GalleryMedium, usable
from qualify_api.creative.gallery_piece import parse_media_query
from qualify_creative.schemas import GALLERY_ORIGIN_BUSINESS

from .catalog_choose_vm import ChoiceVM, ProductChoicesVM, business_choices, product_choices
from .catalog_gallery_provider import load_gallery
from .catalog_provider import list_products
from .gen_gallery_pick_vm import clip_role, origin_of_token, reference_name
from .upload_store import save_upload_file, upload_path

logger = logging.getLogger(__name__)

__all__ = ["GalleryPick", "gallery_choices", "resolve_picks"]

#: Where a copied Galería medium lands among the owner's uploads.
_COPY_FOLDER = "gallery"


@dataclass(frozen=True)
class GalleryPick:
    """One chosen medium, ready for the slot."""

    key: str
    media_type: str  # "image" | "video"
    name: str
    #: The Clip's category a photo starts as ("product" / "place"); "" for a video.
    role: str
    #: The token the owner tapped (`n:<uuid>` / `p:<uuid>`).
    token: str = ""


def gallery_choices(
    tenant_id: UUID, brand_id: UUID
) -> tuple[list[ChoiceVM], list[ProductChoicesVM]]:
    """Blocking: the business's ready media and each product with media — CM-5's tiles."""
    snapshot = load_gallery(tenant_id, brand_id)
    products = list_products(tenant_id, brand_id)
    return business_choices(snapshot.items), product_choices(products)


def _copy(tenant_id: UUID, medium: GalleryMedium) -> str:
    """The business medium copied into the owner's uploads; its new key."""
    name = PurePosixPath(medium.object_key).name or ("video.mp4" if medium.is_video else "foto.jpg")
    with upload_path(tenant_id, medium.object_key) as path, path.open("rb") as source:
        return save_upload_file(tenant_id, source, name, folder=_COPY_FOLDER)


def resolve_picks(
    tenant_id: UUID,
    brand_id: UUID,
    tokens: Sequence[str],
    copied: Mapping[str, str] | None = None,
) -> list[GalleryPick]:
    """Blocking (DB + R2): the chosen tokens, in the order chosen. A token that is
    malformed, another business's, removed, or a video too short is left out; a business
    medium that cannot be copied is left out too (logged). `copied` maps a token to the
    key an earlier «Agregar» of this session copied it to: it is checked again (RLS) but
    not copied twice. The category follows the token the owner tapped (`n:` → «Fondo»,
    `p:` → «Producto»)."""
    known = dict(copied or {})
    pairs = []
    for token in dict.fromkeys(tokens):
        refs = parse_media_query(token).refs if origin_of_token(token) else ()
        if refs:
            pairs.append((token, refs[0]))
    if not pairs:
        return []
    found = DbGalleryMedia().resolve(
        tenant_id=tenant_id, brand_id=brand_id, refs=[ref for _, ref in pairs]
    )
    picks: list[GalleryPick] = []
    seen: set[str] = set()
    for token, ref in pairs:
        medium = found.get(ref)
        if medium is None or not usable(medium):
            continue
        origin = origin_of_token(token)
        key = medium.object_key
        if origin == GALLERY_ORIGIN_BUSINESS:
            key = known.get(token, "")
            if not key:
                try:
                    key = _copy(tenant_id, medium)
                except Exception as exc:  # noqa: BLE001 — one medium never fails the rest
                    logger.warning("gallery reference not copied: %s", type(exc).__name__)
                    continue
        if key in seen:
            continue
        seen.add(key)
        picks.append(
            GalleryPick(
                key=key,
                media_type=medium.media_type,
                name=reference_name(origin, medium.media_type, medium.product_name),
                role="" if medium.is_video else clip_role(origin),
                token=token,
            )
        )
    return picks
