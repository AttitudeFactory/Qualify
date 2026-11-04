"""«Revisa y crea» (the generator's summary): how its rows count what the piece uses.

Live test 2026-11-03 (a real tenant): «Fotos: 2 subidas» ignored the background and
said «subidas» for photos taken from Inspiración and the catalog; «Logo: Disponible ·
Otros logos: 2» did not say which logo; «1 videos» broke the plural. Pure functions, so
the wording is tested without a state.
"""

from __future__ import annotations


def count_text(count: int, singular: str, plural: str) -> str:
    """«1 video», «2 videos» — the noun agrees with the number."""
    return f"{count} {singular if count == 1 else plural}"


def flyer_photos_text(*, background: bool, products: int) -> str:
    """What the image is made from, by role, wherever the photos came from — never
    «subidas»: they may come from Inspiración, the catalog or a piece."""
    parts = []
    if background:
        parts.append("Fondo: 1 foto")
    if products:
        parts.append("Producto: " + count_text(products, "foto", "fotos"))
    return " · ".join(parts) or "Ninguna"


def clip_references_text(*, images: int, videos: int, audios: int) -> str:
    """«2 imágenes · 1 video» — the parts with nothing are left out."""
    parts = [
        count_text(n, singular, plural)
        for n, singular, plural in (
            (images, "imagen", "imágenes"),
            (videos, "video", "videos"),
            (audios, "audio", "audios"),
        )
        if n
    ]
    return " · ".join(parts) or "Ninguna"


#: A logo version's designer name → what the owner sees in it (UX review 2026-11-03:
#: «Imagotipo», «Isologo» are a designer's words; Tu marca explains them, the summary
#: should not need to).
LOGO_PLAIN_NAMES = {
    "logo": "tu logo",
    "logotipo": "solo el nombre",
    "isotipo": "solo el dibujo",
    "imagotipo": "el dibujo con el nombre",
    "isologo": "el nombre y el dibujo unidos",
}


def logo_plain_name(label: str) -> str:
    """«Imagotipo» → «el dibujo con el nombre»; a name the owner gave stays as it is."""
    clean = " ".join(label.split())
    return LOGO_PLAIN_NAMES.get(clean.lower(), clean)


def brand_resources_text(
    *,
    logo_label: str,
    other_logos: int,
    elements: int,
    other_logo_labels: tuple[str, ...] = (),
) -> str:
    """«Tu logo: el dibujo con el nombre · También: solo el dibujo · 1 imagen de tu
    marca»; «Sin logo» when none. The logos are named (live test 2026-11-03, draft
    35a5918b: the owner believed she had chosen another one) in plain words, never the
    designer's (UX review 2026-11-03)."""
    plain = logo_plain_name(logo_label)
    parts = [
        ("Tu logo" if plain == LOGO_PLAIN_NAMES["logo"] else f"Tu logo: {plain}")
        if logo_label
        else "Sin logo"
    ]
    named = [logo_plain_name(label) for label in other_logo_labels if label]
    if named and len(named) == other_logos:
        parts.append("También: " + ", ".join(named))
    elif other_logos:
        parts.append(count_text(other_logos, "logo más", "logos más"))
    if elements:
        parts.append(count_text(elements, "imagen de tu marca", "imágenes de tu marca"))
    return " · ".join(parts)


#: «¿Dónde lo ponemos?» (UX review 2026-11-03) — the summary repeats the owner's choice.
LOGO_IN_SCENE_TEXT = "Donde mejor se vea en la foto"
LOGO_SIGNATURE_TEXT = "En una esquina, como firma"
#: The backend places a logo as a corner signature ONLY when the owner's own text asks
#: for it in so many words (`qualify_api.creative.resource_selection`: an affirmative
#: sentence holding «como firma»). «En una esquina, como firma» writes that sentence for
#: the owner, under their text — the screen used to tell them to type it themselves.
LOGO_SIGNATURE_REQUEST = "Pon mi logo en una esquina, como firma."


#: «Revisa y crea» of a piece with a logo (draft 35a5918b, 2026-11-03): the logo is
#: placed on something the scene really shows, else as a corner signature — said
#: before the owner creates, so a corner logo is never a surprise. It repeats the
#: owner's «¿Dónde lo ponemos?» (UX review 2026-11-03).
CLIP_LOGO_PLACEMENT_TEXT = (
    f"{LOGO_IN_SCENE_TEXT}, como un empaque o un letrero. "
    "Si no hay dónde, irá como firma en una esquina."
)


def campaign_hint(chosen: str, *, clip: bool, new: bool = False) -> str:
    """The folded «Más opciones» of «Cómo la quieres»: with a campaign chosen it names it
    — one carried over by «Crear otra» must be seen there, not found in the summary."""
    if chosen:
        return f"Va en la campaña «{chosen}». Puedes cambiarla o quitarla aquí."
    if new:  # «+ Nueva campaña» still without a name
        return "Va en una campaña nueva. Puedes cambiarla o quitarla aquí."
    if clip:
        return "El sonido, los subtítulos y la campaña. Puedes crear sin tocarlos."
    return "Agrupa esta publicación en una campaña. Puedes crear sin tocarla."


#: «Contexto» of a reel replica the owner added nothing to (live test 2026-11-03).
REPLICA_OWN_TOPIC_EMPTY = "No escribiste nada: seguimos el reel original"
_NETWORKS = {"instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook"}


def source_reel_text(source_reel: dict[str, str]) -> str:
    """«@inspiracion (Instagram)» — the reel a replica is based on."""
    handle = str(source_reel.get("handle") or "").strip()
    network = _NETWORKS.get(str(source_reel.get("platform") or "").strip().lower(), "")
    if handle and network:
        return f"{handle} ({network})"
    return handle or (f"Un reel de {network}" if network else "Un reel")


def source_reel_href(source_reel: dict[str, str]) -> str:
    """The original reel's address, only an `https://` one ("" otherwise)."""
    url = str(source_reel.get("url") or "").strip()
    return url if url.startswith("https://") else ""
