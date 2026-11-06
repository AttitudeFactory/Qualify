"""View models of «Crear» with what the owner chose in Galería (CM-7, m-24955928).

Pure: no Reflex, no database. `/create?medios=n:<uuid>,p:<uuid>` (CM-5's link) opens a
short screen of its own instead of the generator's product step: the chosen photos and
videos in order with «Cambiar» (back to Galería with the same choice), what was left out,
the sound switch when a business video has sound, and «Crear publicación». The piece is
made by CM-6's `GalleryPieces.create` — a carousel, or a single image / a Reel for one
medium — and lands in «Por aprobar». Copy: `docs/epica-galeria-medios-negocio.md` §5
CM-7, verbatim; D6: the sound switch starts OFF; D7: the format is called «Carrusel».
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlencode

from qualify_api.creative.gallery_media import GalleryMedium
from qualify_api.creative.gallery_piece import (
    DROPPED_TEXT,
    MEDIA_QUERY_PARAM,
    NOT_ENOUGH_MEDIA_TEXT,
    format_media_query,
    parse_media_query,
)
from qualify_creative.schemas import GALLERY_ORIGIN_BUSINESS

from .catalog_gallery_vm import duration_label, duration_spoken

__all__ = [
    "BACK_LABEL",
    "CHANGE",
    "CREATE",
    "DROPPED_TEXT",
    "NOT_ENOUGH_MEDIA_TEXT",
    "SOUND_LABEL",
    "SOUND_OFF",
    "SOUND_ON",
    "TITLE",
    "TOPIC_HINT",
    "TOPIC_LABEL",
    "VOICE_TEXT",
    "ChosenVM",
    "change_href",
    "chosen_tiles",
    "kind_label",
    "sound_line",
]

TITLE = "Crear publicación"
BACK_LABEL = "Galería"
CHANGE = "Cambiar"
SOUND_LABEL = "Usar el sonido de tus videos"
SOUND_OFF = "Apagado: tus videos van sin sonido."
SOUND_ON = "Encendido: tus videos van con su sonido."
#: When the format carries a generated voice (CM-7's criterion). A Galería piece is a
#: carousel, a single image or a Reel of the owner's own media — CM-6 adds no voice to
#: any of them — so today the screen never shows it; the rule lives here for the day a
#: voiced format takes Galería media.
VOICE_TEXT = "Esta publicación lleva voz, así que tus videos van sin sonido."
TOPIC_LABEL = "¿Qué quieres contar? (opcional)"
TOPIC_HINT = (
    "Por ejemplo: «Así preparamos el pan cada mañana». Si lo dejas vacío, lo escribimos por ti."
)
CREATE = "Crear publicación"
#: What the piece is about when the owner writes nothing (the copy model still needs a
#: topic; the brand's own context does the rest).
DEFAULT_TOPIC = "Fotos y videos reales de nuestro negocio"


@dataclass(frozen=True)
class ChosenVM:
    """One chosen medium, in the publication's order (`order`, 1-based)."""

    key: str
    order: int
    media_type: str
    #: `/r2media/<token>` (a business medium) or a local upload key (a product's).
    thumb: str
    video: str
    duration: str
    label: str


def kind_label(media: Sequence[GalleryMedium]) -> str:
    """What the owner is about to make: «Carrusel de 3 fotos y videos» (D7's word), or
    — one medium — «Una foto» / «Un video (Reel)» (CM-6: one photo is a single image, one
    video a Reel)."""
    if len(media) == 1:
        return "Un video (Reel)" if media[0].is_video else "Una foto"
    videos = sum(1 for m in media if m.is_video)
    photos = len(media) - videos
    if videos and photos:
        what = "fotos y videos"
    elif videos:
        what = "videos"
    else:
        what = "fotos"
    return f"Carrusel de {len(media)} {what}"


def chosen_tiles(
    media: Iterable[GalleryMedium], view_path: Callable[[str, str], str]
) -> list[ChosenVM]:
    """The chosen media as tiles. `view_path(key, kind)` turns a business medium's R2 key
    into a browser path; a product's key is a local upload key, used as it is."""
    tiles: list[ChosenVM] = []
    for order, m in enumerate(media, start=1):
        business = m.origin == GALLERY_ORIGIN_BUSINESS
        thumb_key = m.thumbnail_key if (business or not m.is_video) else ""
        thumb = (view_path(thumb_key, "image") if business else thumb_key) if thumb_key else ""
        video = "" if business or not m.is_video else m.object_key
        whose = "de tu negocio" if business else f"de {m.product_name}"
        if m.is_video:
            length = f", {duration_spoken(m.duration_ms)}" if m.duration_ms else ""
            label = f"{order}.º: video {whose}{length}"
        else:
            label = f"{order}.ª: foto {whose}"
        tiles.append(
            ChosenVM(
                key=f"{m.origin}-{m.media_id}",
                order=order,
                media_type="video" if m.is_video else "image",
                thumb=thumb,
                video=video,
                duration=duration_label(m.duration_ms) if m.is_video and m.duration_ms else "",
                label=label,
            )
        )
    return tiles


def sound_line(*, offered: bool, on: bool, voiced: bool = False) -> str:
    """The line under the sound switch (or instead of it when the format has a voice)."""
    if voiced:
        return VOICE_TEXT
    if not offered:
        return ""
    return SOUND_ON if on else SOUND_OFF


def change_href(medios: str | Sequence[str] | None) -> str:
    """«Cambiar»: back to Galería's choice with the same media chosen
    (`/catalog?elegir=1&medios=…`, CM-5 reopens it) — only well-formed items travel."""
    parsed = parse_media_query(medios)
    params = {"elegir": "1"}
    if parsed.refs:
        params[MEDIA_QUERY_PARAM] = format_media_query(parsed.refs)
    return f"/catalog?{urlencode(params, safe=':,')}"
