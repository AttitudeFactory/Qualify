"""«Publicación del mes» on the Planificador (m-25120704): the copy and the kind choices."""

from __future__ import annotations

from qualify_api.planner.monthly_post import MONTHLY_POST_KINDS
from qualify_creative.creations import (
    CreationNotOffered,
    is_presenter_request,
    weight_for_request,
)

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
#: The generator's starting lengths: a generated video (a clip, an avatar on Seedance) at
#: `CreativeState.clip_duration`, a talking presenter at `media_duration`.
_VIDEO_SECONDS = 5
_PRESENTER_SECONDS = 30


def kind_options() -> list[dict[str, str]]:
    """The selector's choices, in «¿Qué creamos?»'s order, with the names it uses."""
    return [{"value": k.value, "label": KIND_LABELS[k.value]} for k in MONTHLY_POST_KINDS]


def monthly_cost_text(kind: str, video_engine: str) -> str:
    """What the chosen kind uses each month — the generator's base price for it on the
    configured engine (`weight_for_request`, the rule the service charges with). The real
    post may cost more once its brief exists (a presenter's length, a carousel's slides)."""
    presenter = is_presenter_request(kind, video_engine)
    try:
        price = weight_for_request(
            kind,
            duration_seconds=_PRESENTER_SECONDS if presenter else _VIDEO_SECONDS,
            video_engine=video_engine,
        )
    except (CreationNotOffered, ValueError):
        return ""
    if price.weight > 0:
        if price.is_presenter:
            what = "Este video con presentador usa"
        elif kind == "carousel":
            what = "Usa desde"  # priced with no generated slide: each one adds
        else:
            what = "Usa"
        return f"{what} {price.weight} de tus creaciones cada mes."  # «1 de tus creaciones»
    if price.video_seconds > 0:
        return (
            f"Este video usa {seconds_label(price.video_seconds)} de tus videos del mes "
            "cuando lo apruebas."
        )
    return ""
