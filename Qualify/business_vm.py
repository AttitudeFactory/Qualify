"""Pure view model of «¿Con qué negocio quieres trabajar?» (S3 m-24849190) and of
«Cambiar de negocio» (S4 m-24849191): the exact copy of the epic's text table and the
helpers that turn the login's businesses into what the screen shows.

No tenant id ever reaches the browser: the screen gets business **names** and a
position in the list; the server maps the position back to the tenant it holds in a
backend-only var and verifies the membership again (`open_business`) before opening it.
"""

from __future__ import annotations

from collections.abc import Sequence

#: The selector's own route (Spanish, like every path a client sees).
CHOOSE_ROUTE = "/elegir-negocio"

# Copy (docs/epica-multi-negocio-una-sesion.md, «Textos que verá el cliente»).
CHOOSE_TITLE = "¿Con qué negocio quieres trabajar?"
CHOOSE_HELP = "Puedes cambiar de negocio cuando quieras desde la parte de arriba."
CHOOSE_TAB_TITLE = "Elige tu negocio · Qualify"
SWITCH_MENU_LABEL = "Cambiar de negocio"
LEAVE_LABEL = "Salir"

#: When the switch cannot reach the pass store or the database: nothing changed, the
#: owner stays where they were and can retry.
SWITCH_DOWN = (
    "No pudimos cambiar de negocio. Sigues en {business}. Inténtalo de nuevo en un momento."
)
#: The seat in the business picked from the menu is gone; the current session stays.
SWITCH_NO_ACCESS = "Ya no tienes acceso a {target}. Sigues en {business}."
#: A switch pass that expired, was used already or was never ours (`/cambiar`).
SWITCH_PASS_DEAD = "No alcanzamos a abrir el otro negocio. Entra de nuevo y elígelo."
#: The selector was opened without a login waiting for a choice (a reload long after,
#: another tab): back to the login, saying why.
CHOICE_EXPIRED = "Vuelve a entrar para elegir con qué negocio quieres trabajar."


def chip_label(business: str) -> str:
    """The header chip: «Estás en {negocio}»."""
    return f"Estás en {business}"


def opening_label(business: str) -> str:
    """While a business opens: «Abriendo {negocio}…»."""
    return f"Abriendo {business}…"


def parse_choice_index(raw: object, count: int) -> int | None:
    """The position the browser sent, or None when it is not one of the `count` listed.

    The browser only ever sends a position it was shown; anything else (a negative
    number, a tenant id typed by hand, a float, a list) is refused here, before any
    lookup. Booleans are refused too (`True` is an `int` in Python)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        index = raw
    elif isinstance(raw, str) and raw.isdigit() and len(raw) <= 3:
        index = int(raw)
    else:
        return None
    return index if 0 <= index < count else None


def switch_choices(names: Sequence[str], active_index: int) -> list[dict[str, str]]:
    """The «Cambiar de negocio» menu: every OTHER business of the login, in the login's
    order (by name), each with its position. The active one is not offered."""
    return [{"index": str(i), "name": name} for i, name in enumerate(names) if i != active_index]


__all__ = [
    "CHOICE_EXPIRED",
    "CHOOSE_HELP",
    "CHOOSE_ROUTE",
    "CHOOSE_TAB_TITLE",
    "CHOOSE_TITLE",
    "LEAVE_LABEL",
    "SWITCH_DOWN",
    "SWITCH_MENU_LABEL",
    "SWITCH_NO_ACCESS",
    "SWITCH_PASS_DEAD",
    "chip_label",
    "opening_label",
    "parse_choice_index",
    "switch_choices",
]
