"""«Tu producto en sticker» (m-25017912, backend m-25017372): pure words and view models of
the five-step flow in Tu marca › «Stickers y videos de tu marca».

The flow (`docs/ux-stickers-producto.md`, with the founder's decisions of 2026-11-12: the
cost is said in CREACIONES, never in money; «Pedir otro dibujo» keeps every drawing and the
owner picks one; no cap but the month's creations): 1 product → 2 the drawing (create, ask
for another, pick one — the only paid step) → 3 the messages → 4 with movement, still or
both → 5 review and prepare (free). On screen the style is «tierno», never «kawaii»; the
paid thing is a «dibujo», the free one a «sticker»."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final

# --- where it lives ----------------------------------------------------------------------

#: The query that opens the flow by itself (the seasonal one is `?crear=temporada`).
CREATE_PARAM_VALUE: Final = "producto"
CREATE_HREF: Final = "/brand/kit?crear=producto"
CATALOG_HREF: Final = "/catalog"
DRAFTS_STICKERS_HREF: Final = "/drafts?ver=stickers"

# --- the start card ----------------------------------------------------------------------

START_TITLE: Final = "Tu producto en sticker"
START_LINE: Final = (
    "Dibujamos tu producto, tierno y con tus colores, con un mensaje como "
    "«¡Gracias por tu pedido!» o «En camino»."
)
START_BUTTON: Final = "Crear sticker de producto"
SEASON_START_TITLE: Final = "Para esta temporada · gratis"
SEASON_START_LINE: Final = "Stickers y videos con tu logo para saludar en cada fecha."

# --- steps -------------------------------------------------------------------------------

STEP_PRODUCT: Final = 1
STEP_DRAWING: Final = 2
STEP_MESSAGE: Final = 3
STEP_MOTION: Final = 4
STEP_REVIEW: Final = 5
FLOW_STEPS: Final = 5
STEP_TITLES: Final[dict[int, str]] = {
    STEP_PRODUCT: "¿Qué producto dibujamos?",
    STEP_DRAWING: "Elige el dibujo",
    STEP_MESSAGE: "¿Qué dice el sticker?",
    STEP_MOTION: "¿Quieto o con movimiento?",
    STEP_REVIEW: "Revisa y prepara",
}

# step 1
PRODUCT_HELP: Final = "Elige uno de tus productos. Lo dibujamos tierno, con tus colores."
SEARCH_LABEL: Final = "Buscar producto"
#: More products than this: a search field above the grid, never pages.
SEARCH_FROM: Final = 9
NO_MATCH: Final = "Ningún producto se llama así."
ADD_PHOTOS_LABEL: Final = "Agregar fotos"
NO_PHOTO_TITLE: Final = "Para dibujar tu producto necesitamos una foto de él"
NO_PHOTO_TEXT: Final = "Sube la foto en Galería y vuelve aquí."
GO_CATALOG_LABEL: Final = "Ir a Galería"

# step 2
DRAWING_HELP: Final = "Elige el dibujo que más te guste. Con él hacemos tus stickers."
NO_DRAWING_YET: Final = (
    "Todavía no hay un dibujo de este producto. Toca «Crear dibujo» y llega en unos 30 segundos."
)
DRAWING_WAIT: Final = "Tu dibujo llega en unos 30 segundos. Puedes esperar aquí."
DRAWING_PENDING: Final = "Dibujando…"
DRAWING_FAILED_PILL: Final = "No salió"
DRAWING_USED_PILL: Final = "Ya lo usaste"
DISCARD_LABEL: Final = "Quitar este dibujo"
DISCARD_TITLE: Final = "¿Quitar este dibujo?"
DISCARD_TEXT: Final = (
    "Ya no aparecerá para elegir. Los stickers que hiciste con él se quedan. No se puede deshacer."
)
DISCARD_YES: Final = "Quitar"
CANCEL_LABEL: Final = "Cancelar"
DRAWING_BUSY_LABEL: Final = "Dibujando… espera tu dibujo"
SEASON_INSTEAD_LABEL: Final = "Crear para esta temporada"
PICK_A_DRAWING: Final = "Elige un dibujo listo para seguir."
ASKING_LABEL: Final = "Pidiendo el dibujo…"
DRAWINGS_FAILED: Final = "No pudimos traer tus dibujos. Vuelve a intentarlo en un momento."

# step 3
MESSAGE_HELP: Final = "Puedes elegir varios: cada mensaje es un sticker."
OWN_MESSAGE: Final = "Escribir el mío"
OWN_MESSAGE_LABEL: Final = "Tu mensaje"
OWN_MESSAGE_HINT: Final = "Por ejemplo: ¡Feliz finde!"
MESSAGE_AS_IS: Final = "El mensaje sale escrito tal cual."
NO_MESSAGES: Final = "Elige al menos un mensaje."
MESSAGE_EMPTY: Final = "Escribe el mensaje del sticker."
#: The counter is read aloud only from here on (`aria-live`), not at every letter.
COUNT_ANNOUNCE_FROM: Final = 20

# step 4
MOTION_HELP: Final = "Puedes elegir los dos."
ANIMATED_TITLE: Final = "Con movimiento"
ANIMATED_LINE: Final = "Se mueve en el chat, como los stickers animados."
STILL_TITLE: Final = "Quieto"
STILL_LINE: Final = "Más liviano: llega rápido aunque la señal sea mala."
NO_VARIANT: Final = "Elige si lo quieres con movimiento, quieto o los dos."

# step 5
FREE_LINE: Final = "Los stickers son gratis: ya tienes el dibujo."
TRUST_LINE: Final = "Llegan a Por aprobar en unos minutos. Nada se manda sin que lo apruebes."
PREPARING_LABEL: Final = "Preparando…"
STARTED_TOAST: Final = "Listo: estamos preparando tus stickers. Llegan a Por aprobar."
SEE_DRAFTS_LABEL: Final = "Ver Por aprobar"

# common
NEXT_LABEL: Final = "Siguiente"
BACK_LABEL: Final = "Atrás"
RETRY_LABEL: Final = "Reintentar"
LOAD_FAILED: Final = "No pudimos traer tus productos. Vuelve a intentarlo en un momento."
ACTION_FAILED: Final = "No pudimos hacerlo. Vuelve a intentarlo en un momento."
NO_SESSION: Final = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
CHECKING_COST: Final = "Revisando el costo…"
NO_COST: Final = "Ahora no podemos calcular el costo. Vuelve a intentarlo en un rato."

# --- statuses (the backend's) ------------------------------------------------------------

PENDING: Final = "pending"
READY: Final = "ready"
FAILED: Final = "failed"
APPROVED: Final = "approved"


def creations_word(n: int) -> str:
    return "1 creación" if n == 1 else f"{n} creaciones"


def start_cost_line(creations: int, read: bool = True) -> str:
    """The start card's price, in creaciones; «Revisando el costo…» until it is read, only
    the free part when the read failed (never «everything is free» while it loads)."""
    if not read:
        return CHECKING_COST
    if creations <= 0:
        return "Los stickers que hagas con tu dibujo son gratis."
    return f"Cada dibujo usa {creations_word(creations)}. Los stickers que hagas con él son gratis."


def ask_another_label(creations: int) -> str:
    """«Pedir otro dibujo · 1 creación» — never the same label as the free «Hacer de nuevo»."""
    return f"Pedir otro dibujo · {creations_word(creations)}"


def without_photo_line(n: int) -> str:
    if n <= 0:
        return ""
    if n == 1:
        return "1 producto no sale porque no tiene foto."
    return f"{n} productos no salen porque no tienen foto."


def message_count(text: str, limit: int) -> str:
    return f"{len(text or '')}/{limit}"


def own_message_error(text: str, limit: int) -> str:
    """Step 3's check of the owner's own message (the backend checks again)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return MESSAGE_EMPTY
    if len(cleaned) > limit:
        return f"Máximo {limit} letras. Prueba algo más corto, como «¡Gracias!»."
    return ""


# --- view models -------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductVM:
    id: str = ""
    name: str = ""
    #: signed `/r2media/…` path, "" → the thumb shows its icon
    src: str = ""


@dataclass(frozen=True)
class DrawingVM:
    id: str = ""
    product_id: str = ""
    product_name: str = ""
    status: str = PENDING
    src: str = ""
    failure_text: str = ""
    pending: bool = False
    failed: bool = False
    #: ready or approved: it can be picked
    usable: bool = False
    approved: bool = False
    alt: str = ""


def product_vms(options: Iterable[Any]) -> list[ProductVM]:
    return [ProductVM(id=str(o.id), name=str(o.name), src=str(o.src or "")) for o in options]


def drawing_vm(card: Any) -> DrawingVM:
    status = str(card.status)
    name = str(card.product_name or "tu producto")
    return DrawingVM(
        id=str(card.id),
        product_id=str(card.product_id),
        product_name=name,
        status=status,
        src=str(card.src or "") if status in (READY, APPROVED) else "",
        failure_text=str(card.failure_text or "") if status == FAILED else "",
        pending=status == PENDING,
        failed=status == FAILED,
        usable=status in (READY, APPROVED),
        approved=status == APPROVED,
        alt=f"Dibujo tierno de {name}",
    )


def drawing_vms(cards: Iterable[Any]) -> list[DrawingVM]:
    """Newest first, as the backend gives them; anything else is left out. Each one is
    told apart for a screen reader («Dibujo 2 de 3 de Shawarma mixto»)."""
    kept = [drawing_vm(c) for c in cards if str(c.status) in (PENDING, READY, FAILED, APPROVED)]
    n = len(kept)
    if n <= 1:
        return kept
    return [replace(d, alt=f"Dibujo {i} de {n} de {d.product_name}") for i, d in enumerate(kept, 1)]


def filter_products(products: Sequence[ProductVM], query: str) -> list[ProductVM]:
    q = (query or "").strip().casefold()
    if not q:
        return list(products)
    return [p for p in products if q in p.name.casefold()]


def last_message(stickers: Sequence[Any]) -> str:
    """The message of the newest product sticker ("" when there is none). The backend lists
    them oldest first."""
    for card in reversed(list(stickers)):
        message = str(getattr(card, "message", "") or "")
        if message:
            return message
    return ""


def chosen_messages(
    presets: Sequence[str], picked: Sequence[str], own_on: bool, own_text: str
) -> list[str]:
    """What the owner chose, in the screen's order, the own message last; no repeats."""
    out = [p for p in presets if p in picked]
    own = (own_text or "").strip()
    if own_on and own and own not in out:
        out.append(own)
    return out


def variant_words(animated: bool, still: bool) -> str:
    if animated and still:
        return "con movimiento y quietos"
    return "con movimiento" if animated else "quietos" if still else ""


def sticker_total(messages: int, animated: bool, still: bool) -> int:
    return messages * (int(animated) + int(still))


def _quoted_list(items: Sequence[str]) -> str:
    quoted = [f"«{i}»" for i in items]
    if len(quoted) <= 1:
        return "".join(quoted)
    return ", ".join(quoted[:-1]) + " y " + quoted[-1]


def review_line(product: str, messages: Sequence[str], animated: bool, still: bool) -> str:
    """«Vamos a preparar 2 stickers con el dibujo de Shawarma mixto: «¡Gracias por tu
    pedido!», con movimiento y quietos.»"""
    total = sticker_total(len(messages), animated, still)
    if not total:
        return ""
    what = "1 sticker" if total == 1 else f"{total} stickers"
    variant = variant_words(animated, still)
    if total == 1:
        variant = "con movimiento" if animated else "quieto"
    return (
        f"Vamos a preparar {what} con el dibujo de {product or 'tu producto'}: "
        f"{_quoted_list(messages)}, {variant}."
    )


def prepare_label(total: int) -> str:
    if total <= 1:
        return "Preparar el sticker · gratis"
    return f"Preparar {total} stickers · gratis"


def can_next(
    step: int,
    *,
    product_id: str,
    drawing: DrawingVM | None,
    messages: Sequence[str],
    own_error: str,
    animated: bool,
    still: bool,
) -> bool:
    if step == STEP_PRODUCT:
        return product_id != ""
    if step == STEP_DRAWING:
        return drawing is not None and drawing.usable
    if step == STEP_MESSAGE:
        return bool(messages) and own_error == ""
    if step == STEP_MOTION:
        return animated or still
    return False
