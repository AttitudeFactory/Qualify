"""«Publicación del mes» on the Planificador (m-25120704): the copy and the kind choices."""

from __future__ import annotations

from qualify_api.planner.monthly_post import MONTHLY_POST_KINDS
from qualify_creative.creations import CreationNotOffered, weight_for_request

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
#: The generator's own starting length for a clip (`CreativeState.clip_duration`); every
#: other kind is priced at `weight_for_request`'s defaults (a 30 s presenter).
_CLIP_SECONDS = 5


def kind_options() -> list[dict[str, str]]:
    """The selector's choices, in «¿Qué creamos?»'s order, with the names it uses."""
    return [{"value": k.value, "label": KIND_LABELS[k.value]} for k in MONTHLY_POST_KINDS]


def monthly_cost_text(kind: str) -> str:
    """What the chosen kind uses each month — the generator's base price for it
    (`weight_for_request`, the rule the service charges with). The real post may differ
    a little once its brief exists (a presenter's length, a carousel's slides)."""
    try:
        price = weight_for_request(kind, duration_seconds=_CLIP_SECONDS if kind == "clip" else 30)
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
