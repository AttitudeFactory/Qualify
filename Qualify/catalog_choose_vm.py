"""View models of «Elegir para una publicación» in Galería (CM-5, m-24955926).

Pure: no Reflex, no database. The owner taps photos and videos — of the business and of
the products — in the order the publication will show them; «Crear publicación con
estas» opens `/create?medios=…` (CM-6's `format_media_query`: `n:<uuid>` a business
medium, `p:<uuid>` a product's). Copy: `docs/epica-galeria-medios-negocio.md` §5 CM-5.

A choice is a *token* (`n:<uuid>` / `p:<uuid>`), so the order the owner tapped is a plain
list of tokens and the link is that list as it is.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from urllib.parse import quote
from uuid import UUID

from qualify_api.creative.gallery_media import GalleryRef
from qualify_api.creative.gallery_piece import MEDIA_QUERY_PARAM, format_media_query
from qualify_creative.schemas import (
    CAROUSEL_MAX_SLIDES,
    GALLERY_ORIGIN_BUSINESS,
    GALLERY_ORIGIN_PRODUCT,
)

from .catalog_gallery_vm import GalleryItemVM, duration_label, duration_spoken
from .catalog_vm import ProductVM

__all__ = [
    "CANCEL",
    "CHOOSE_BUTTON",
    "CHOOSE_HELP",
    "CHOOSE_TITLE",
    "CREATE_WITH",
    "GROUP_BUSINESS",
    "GROUP_PRODUCTS",
    "MAX_CHOSEN",
    "TOO_MANY",
    "ChoiceVM",
    "ProductChoicesVM",
    "business_choices",
    "chosen_label",
    "create_href",
    "product_choices",
    "toggle",
    "with_order",
]

#: What Instagram takes in one carousel (CM-6 keeps at most this many slides).
MAX_CHOSEN = CAROUSEL_MAX_SLIDES

CHOOSE_BUTTON = "Elegir para una publicación"
CHOOSE_TITLE = "Elegir para una publicación"
CHOOSE_HELP = "Toca las fotos y videos en el orden en que quieres que salgan."
GROUP_BUSINESS = "De tu negocio"
GROUP_PRODUCTS = "De tus productos"
CREATE_WITH = "Crear publicación con estas"
CANCEL = "Cancelar"
TOO_MANY = f"Puedes elegir hasta {MAX_CHOSEN}."

_PREFIX = {GALLERY_ORIGIN_BUSINESS: "n", GALLERY_ORIGIN_PRODUCT: "p"}
_ORIGIN = {prefix: origin for origin, prefix in _PREFIX.items()}


@dataclass(frozen=True)
class ChoiceVM:
    """One photo or video that can be chosen. `order` is its place in the publication
    (1-based; 0 = not chosen)."""

    token: str
    media_type: str
    #: What the tile shows: an `/r2media/<token>` path (the business's), a local upload
    #: key (a product's), or "" for the placeholder.
    thumb: str
    #: A product's video has no poster: the tile shows the video's first frame.
    video: str
    duration: str
    #: «Video de 42 segundos» / «Foto de tu negocio» / «Foto de Shawarma mixto».
    label: str
    order: int = 0

    @property
    def spoken(self) -> str:
        """«Video de 42 segundos, elegido 2.º» (CM-5's example) — «elegida 2.ª» for a
        photo."""
        if not self.order:
            return self.label
        if self.media_type == "video":
            return f"{self.label}, elegido {self.order}.º"
        return f"{self.label}, elegida {self.order}.ª"


@dataclass(frozen=True)
class ProductChoicesVM:
    name: str
    choices: tuple[ChoiceVM, ...]


def token(origin: str, media_id: str | UUID) -> str:
    return f"{_PREFIX[origin]}:{media_id}"


def _video_label(duration_ms: int) -> str:
    return f"Video de {duration_spoken(duration_ms)}" if duration_ms else "Video"


def business_choices(items: Iterable[GalleryItemVM]) -> list[ChoiceVM]:
    """The business's media that can be chosen: ready ones only — a video being
    prepared, that failed, or being cut never appears (CM-5)."""
    out: list[ChoiceVM] = []
    for item in items:
        if not item.selectable or not item.media_id:
            continue
        is_video = item.media_type == "video"
        out.append(
            ChoiceVM(
                token=token(GALLERY_ORIGIN_BUSINESS, item.media_id),
                media_type=item.media_type,
                thumb=item.thumb_url,
                video="",
                duration=item.duration,
                label=_video_label(item.duration_ms) if is_video else "Foto de tu negocio",
            )
        )
    return out


def product_choices(products: Iterable[ProductVM]) -> list[ProductChoicesVM]:
    """Each product with media, by name, its photos and videos in its own order."""
    groups: list[ProductChoicesVM] = []
    for product in products:
        choices = []
        for media in product.media:
            is_video = media.media_type == "video"
            choices.append(
                ChoiceVM(
                    token=token(GALLERY_ORIGIN_PRODUCT, media.media_id),
                    media_type=media.media_type,
                    thumb="" if is_video else media.key,
                    video=media.key if is_video else "",
                    duration=duration_label(media.duration_ms) if media.duration_ms else "",
                    label=(
                        f"{_video_label(media.duration_ms)} de {product.name}"
                        if is_video
                        else f"Foto de {product.name}"
                    ),
                )
            )
        if choices:
            groups.append(ProductChoicesVM(name=product.name, choices=tuple(choices)))
    return groups


def toggle(chosen: Sequence[str], choice: str) -> tuple[list[str], str]:
    """A tap: chosen → out (the ones after it move up); not chosen → last in, unless
    there are already `MAX_CHOSEN` («Puedes elegir hasta 10.»)."""
    current = list(chosen)
    if choice in current:
        current.remove(choice)
        return current, ""
    if len(current) >= MAX_CHOSEN:
        return current, TOO_MANY
    return [*current, choice], ""


def with_order(choices: Sequence[ChoiceVM], chosen: Sequence[str]) -> list[ChoiceVM]:
    position = {t: i for i, t in enumerate(chosen, start=1)}
    return [replace(c, order=position.get(c.token, 0)) for c in choices]


def chosen_label(count: int) -> str:
    """«2 elegidas» (fotos y videos: feminine plural, as the epic writes it)."""
    return "1 elegida" if count == 1 else f"{count} elegidas"


def create_href(chosen: Sequence[str]) -> str:
    """`/create?medios=n:<uuid>,p:<uuid>` in the tapped order, through CM-6's own
    formatter (so the generator reads exactly what the screen wrote)."""
    refs = []
    for item in chosen:
        prefix, _, value = item.partition(":")
        origin = _ORIGIN.get(prefix)
        if origin is None:
            continue
        try:
            refs.append(GalleryRef(origin, UUID(value)))
        except ValueError:
            continue
    value = format_media_query(refs)
    return f"/create?{MEDIA_QUERY_PARAM}={quote(value, safe=':,')}"
