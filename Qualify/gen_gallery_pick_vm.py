"""View models of «Tu Galería», a tab of the generator's media drawer (m-24985141).

Pure: no Reflex, no database. In the drawer («Tus productos · Tu Galería · Subir ·
Publicaciones · Inspiración») the owner taps photos and videos of the business and of the
products; «Agregar» puts them in the slot — in a Clip's references with their category: a
product's photo as «Producto», a business photo as «Fondo» (the role select changes it), a
video as a reference video. The tiles and their tokens (`n:<uuid>` a business medium,
`p:<uuid>` a product's) are CM-5's (`catalog_choose_vm`). The category follows the TOKEN the
owner tapped — what the screen showed —, never a guess.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from qualify_creative.schemas import GALLERY_ORIGIN_BUSINESS, GALLERY_ORIGIN_PRODUCT

__all__ = [
    "ADD",
    "COUNT_ID",
    "EMPTY",
    "FAILED",
    "LOAD_FAILED",
    "NOTHING_ADDED",
    "TITLE",
    "add_label",
    "added_note",
    "chosen_text",
    "product_removed_note",
    "product_seed_note",
    "ref_uploads_left_text",
    "slot_held_text",
    "to_add_text",
    "clip_role",
    "origin_of_token",
    "pick_limit",
    "reference_name",
]

TITLE = "Tu Galería"
ADD = "Agregar"
#: The drawer's live count: «Agregar» is described by it (`aria-describedby`).
COUNT_ID = "gen-gallery-count"
EMPTY = (
    "Todavía no tienes fotos ni videos en tu Galería. Puedes subir uno desde tu teléfono "
    "en la pestaña «Subir»."
)
LOAD_FAILED = "No pudimos abrir tu Galería. Inténtalo otra vez en un minuto."
FAILED = "No pudimos agregar lo que elegiste. Inténtalo otra vez en un minuto."
NOTHING_ADDED = (
    "No pudimos agregar lo que elegiste: ya no está en tu Galería o pasaba del máximo. "
    "Elige otras fotos o videos."
)
_PHOTOS_FULL = (
    "Ya llegaste a {n} fotos, el máximo del clip. Toca una de las elegidas para quitarla, "
    "o quita una de tus referencias."
)
_VIDEOS_FULL = (
    "Ya llegaste a {n} videos, el máximo del clip. Toca uno de los elegidos para quitarlo, "
    "o quita uno de tus referencias."
)
_NO_MORE_PHOTOS = "No caben más fotos aquí. Toca una de las elegidas para quitarla."
_NO_MORE_VIDEOS = "No caben más videos aquí. Toca uno de los elegidos para quitarlo."
_PREFIX_ORIGIN = {"n": GALLERY_ORIGIN_BUSINESS, "p": GALLERY_ORIGIN_PRODUCT}
#: The Clip's categories (`CLIP_IMAGE_ROLES`): what a Galería photo starts as.
_ROLE_OF_ORIGIN = {GALLERY_ORIGIN_PRODUCT: "product", GALLERY_ORIGIN_BUSINESS: "place"}


def origin_of_token(token: str) -> str:
    """`n:<uuid>` → the business's, `p:<uuid>` → a product's ("" otherwise)."""
    prefix, sep, _ = token.partition(":")
    return _PREFIX_ORIGIN.get(prefix.strip().lower(), "") if sep else ""


def clip_role(origin: str) -> str:
    """A product's photo is the product; a photo of the business, the place."""
    return _ROLE_OF_ORIGIN.get(origin, "place")


def reference_name(origin: str, media_type: str, product_name: str = "") -> str:
    """The name the reference goes by in the grid (and in the brief)."""
    video = media_type == "video"
    if origin == GALLERY_ORIGIN_PRODUCT and product_name:
        return f"{'Video' if video else 'Foto'} de {product_name}"
    return "Video de tu negocio" if video else "Foto de tu negocio"


def pick_limit(
    chosen: Sequence[str],
    media_of: Mapping[str, str],
    token: str,
    *,
    photo_room: int,
    video_room: int,
    clip: bool = True,
) -> tuple[list[str], str]:
    """A tap: chosen → out; not chosen → in, within the room left for its kind (counting
    what is already chosen here). A slot of ONE file (room 1, not a Clip): the new tap
    replaces the earlier one. Returns the new list and what to say when it did not fit."""
    current = list(chosen)
    if token in current:
        current.remove(token)
        return current, ""
    media = media_of.get(token)
    if media is None:
        return current, ""
    same = [t for t in current if media_of.get(t) == media]
    room = video_room if media == "video" else photo_room
    if room <= 0 and not same and not clip:
        return current, (
            "Aquí no van videos: elige una foto."
            if media == "video"
            else "Aquí no van fotos: elige un video."
        )
    if len(same) >= room:
        if not clip and room == 1:
            return [t for t in current if t not in same] + [token], ""
        if not clip:
            # `room` already counts what the slot holds (review #9)
            return current, _NO_MORE_VIDEOS if media == "video" else _NO_MORE_PHOTOS
        text = _VIDEOS_FULL if media == "video" else _PHOTOS_FULL
        return current, text.format(n=3 if media == "video" else 9)
    return [*current, token], ""


def chosen_text(count: int) -> str:
    """«2 elegidas» (CM-5's words); "" before the first tap."""
    if count <= 0:
        return ""
    return "1 elegida" if count == 1 else f"{count} elegidas"


def added_note(wanted: int, added: int) -> str:
    """What could not be added (gone from the Galería, or past the maximum); "" when
    all went in."""
    if added >= wanted:
        return ""
    if added == 0:
        return NOTHING_ADDED
    missing = wanted - added
    if missing == 1:
        return (
            "Una de las que elegiste ya no está en tu Galería o pasaba del máximo; "
            "agregamos las demás."
        )
    return (
        f"{missing} de las que elegiste ya no están en tu Galería o pasaban del máximo; "
        "agregamos las demás."
    )


def to_add_text(count: int) -> str:
    """The media drawer's foot: «1 por agregar» / «3 por agregar» ("" with none) — its
    own words, CM-5's «N elegidas» stays as it is."""
    if count <= 0:
        return ""
    return f"{count} por agregar"


def add_label(count: int) -> str:
    """The foot's one button: «Agregar 2» with something chosen in «Tu Galería»,
    «Listo» otherwise. Always enabled, it always closes the drawer."""
    return f"Agregar {count}" if count > 0 else "Listo"


def slot_held_text(count: int, *, video: bool = False) -> str:
    """What a slot holds, beside the foot's button."""
    if count <= 0:
        return "Nada elegido aún"
    if video:
        return "Video elegido"
    return "1 foto puesta" if count == 1 else f"{count} fotos puestas"


def product_removed_note(name: str) -> str:
    """After a change of product: which photos left the references."""
    name = " ".join((name or "").split())
    if not name:
        return "Quitamos de tus referencias las fotos de tu producto anterior."
    return f"Quitamos de tus referencias las fotos de “{name}”."


def product_seed_note(
    name: str, *, photos_in: int, photos_out: int, videos_in: int, videos_out: int
) -> str:
    """When a product brings more than a Clip takes (9 photos, 3 videos): what went in
    and what did not — never dropped in silence. "" when everything fit."""
    if not photos_out and not videos_out:
        return ""
    name = " ".join((name or "").split()) or "tu producto"
    parts = []
    for count_in, count_out, one, many, top in (
        (photos_in, photos_out, "foto", "fotos", 9),
        (videos_in, videos_out, "video", "videos", 3),
    ):
        if not count_out:
            continue
        if not count_in:
            # no room at all: none of them went in
            what = f"la {one}" if count_out == 1 else f"las {count_out} {many}"
            if one == "video":
                what = "el video" if count_out == 1 else f"los {count_out} videos"
            verb = "No cupo" if count_out == 1 else "No cupieron"
            parts.append(f"{verb} {what} de “{name}” (máximo {top} por clip).")
            continue
        went = f"1 {one}" if count_in == 1 else f"{count_in} {many}"
        verb = "Entró" if count_in == 1 else "Entraron"
        left = "1 no cupo" if count_out == 1 else f"{count_out} no cupieron"
        parts.append(f"{verb} {went} de “{name}”; {left} (máximo {top} por clip).")
    return " ".join(parts)


def ref_uploads_left_text(photos: int, videos: int, max_photos: int) -> str:
    """What an avatar's references drop did not take: «No agregamos 2 fotos: ya tienes
    10, el máximo. Quita una para cambiarla.» and «No agregamos 1 video: va un solo video
    de referencia; usamos el primero.» — "" when everything went in."""
    notes = []
    if photos > 0:
        what = "1 foto" if photos == 1 else f"{photos} fotos"
        notes.append(
            f"No agregamos {what}: ya tienes {max_photos}, el máximo. Quita una para cambiarla."
        )
    if videos > 0:
        what = "1 video" if videos == 1 else f"{videos} videos"
        notes.append(f"No agregamos {what}: va un solo video de referencia; usamos el primero.")
    return " ".join(notes)
