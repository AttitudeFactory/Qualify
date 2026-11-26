"""«Publicación del mes» on the Planificador (m-25120704): the copy and the kind choices."""

from __future__ import annotations

from qualify_api.planner.monthly_post import MONTHLY_POST_KINDS

from .creative_vm import KIND_LABELS

TITLE = "Publicación del mes"
EXPLAIN = (
    "Cada mes te preparamos una publicación para la fecha más importante del mes. "
    "Usa 1 de tus creaciones del mes. Tú la revisas antes de publicarla."
)
KIND_LABEL = "Tipo de pieza"
LOAD_FAILED = "No pudimos leer tu publicación del mes. Vuelve a entrar en un momento."
SAVE_FAILED = "No pudimos guardar tu cambio. Inténtalo de nuevo."
SESSION_ENDED = "Tu sesión terminó. Vuelve a entrar para cambiarlo."


def kind_options() -> list[dict[str, str]]:
    """The selector's choices, in «¿Qué creamos?»'s order, with the names it uses."""
    return [{"value": k.value, "label": KIND_LABELS[k.value]} for k in MONTHLY_POST_KINDS]
