"""«Publicación del mes» on the Planificador (m-25120704): the copy and the kind choices."""

from __future__ import annotations

from collections.abc import Iterable

from qualify_api.planner.monthly_post import MONTHLY_POST_KINDS
from qualify_api.planner.monthly_post_job import AVATAR_SECONDS, CAROUSEL_SLIDES, VIDEO_SECONDS
from qualify_creative.creations import CreationNotOffered, weight_for_request

from .catalog_vm import ProductVM, new_product_href
from .creative_vm import KIND_LABELS, seconds_label

TITLE = "Publicación del mes"
EXPLAIN = (
    "Cada mes te preparamos una publicación para la fecha más importante del mes. "
    "Te la dejamos en Por aprobar al empezar el mes. Tú la revisas antes de publicarla."
)
ENABLED_BADGE = "Activada"
KIND_LABEL = "¿Qué quieres que te preparemos?"
LOAD_FAILED = "No pudimos leer tu publicación del mes. Vuelve a entrar en un momento."
SAVE_FAILED = "No pudimos guardar tu cambio. Inténtalo de nuevo."
SESSION_ENDED = "Tu sesión terminó. Vuelve a entrar para cambiarlo."
TEMPLATE_KIND = "template"
PRODUCT_LABEL = "¿Qué producto mostramos?"
#: «Con plantilla» with no product that can make one (m-25121346). The screen is named
#: «Galería» in the menu (`ui/layout.py`), so the sentence names it that way.
NO_PRODUCTS = "Primero agrega un producto con foto en tu Galería."
NO_PRODUCTS_LINK = "Agregar producto"
#: Straight to «Agregar producto»; no way back: «Volver a tu publicación» is not this card.
NO_PRODUCTS_HREF = new_product_href("")
PRODUCT_MISSING = (
    "El producto que elegiste ya no está disponible. "
    "Elige otro para recibir tu publicación del mes."
)
PICK_PRODUCT = "Elige un producto para guardar este cambio."


def kind_options() -> list[dict[str, str]]:
    """The selector's choices, in «¿Qué creamos?»'s order, with the names it uses."""
    return [{"value": k.value, "label": KIND_LABELS[k.value]} for k in MONTHLY_POST_KINDS]


def product_rows(products: Iterable[ProductVM]) -> list[dict[str, str]]:
    """The products a template can be made from — those with a photo (the backend refuses
    the rest) — as flat rows for the picker: `{id, name, photo_key}`."""
    return [
        {"id": p.product_id, "name": p.name, "photo_key": p.primary_photo_key}
        for p in products
        if p.photo_count > 0
    ]


def monthly_cost_text(kind: str, video_engine: str) -> str:
    """What the chosen kind uses each month: the generator's price
    (`weight_for_request`, the rule the service charges with) for the brief the monthly
    job makes — a clip of `VIDEO_SECONDS`, the avatars at `AVATAR_SECONDS` on the
    configured engine, a carousel of `CAROUSEL_SLIDES` generated slides."""
    avatar = kind in ("avatar_video", "animated_avatar_video")
    try:
        price = weight_for_request(
            kind,
            duration_seconds=AVATAR_SECONDS if avatar else VIDEO_SECONDS,
            video_engine=video_engine,
            generated_slides=CAROUSEL_SLIDES if kind == "carousel" else 0,
        )
    except (CreationNotOffered, ValueError):
        return ""
    if price.weight > 0:
        what = "Este video con presentador usa" if price.is_presenter else "Usa"
        return f"{what} {price.weight} de tus creaciones cada mes."  # «1 de tus creaciones»
    if price.video_seconds > 0:
        return (
            f"Este video usa {seconds_label(price.video_seconds)} de tus videos del mes "
            "cuando lo apruebas."
        )
    return ""
