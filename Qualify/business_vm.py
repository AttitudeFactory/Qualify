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


#: The menu entry of the business already open (S4, block B of the sidebar 2026-11-08).
HERE_LABEL = "Aquí estás"
#: The sidebar's open/close control (alternative B, m-24976899). `⌘ .` is the shortcut.
COLLAPSE_LABEL = "Contraer el menú"
EXPAND_LABEL = "Expandir el menú"
CLOSE_DRAWER_LABEL = "Cerrar el menú"
SHORTCUT_HINT = "⌘ ."
#: Under the sidebar's top row, before «◎ Qualify»: who stands behind the business's
#: screen. It must convey trust (founder, 2026-11-08); one constant so the alternative
#: «Acompañados por» is a one-line change.
CREDIT_LABEL = "Con el respaldo de"

#: How long a minted logo path is used before the shell asks for a fresh one. The
#: `/r2media` token lives an hour and is reused only with 15+ minutes left, so a
#: path younger than this is always good for the rest of a visit to one page.
LOGO_FRESH_SECONDS = 10 * 60


def trigger_label(business: str, opening: str = "") -> str:
    """The name on the sidebar's top row: the business, or «Abriendo {negocio}…»."""
    return opening_label(opening) if opening else business


def switch_trigger_aria(business: str, opening: str = "") -> str:
    """Screen-reader name of the business name when it opens «Cambiar de negocio»."""
    return f"{chip_label(business) if not opening else opening_label(opening)}. {SWITCH_MENU_LABEL}"


def credit_aria() -> str:
    """Screen-reader name of the credit link: the visible words plus where it goes."""
    return f"{CREDIT_LABEL} Qualify. Ir al sitio de Qualify"


def rail_toggle_title(label: str) -> str:
    """Tooltip of the open/close control: its name plus the shortcut."""
    return f"{label} ({SHORTCUT_HINT})"


def logo_needs_refresh(*, tenant: str, logo_tenant: str, fetched_at: float, now: float) -> bool:
    """Whether the shell should mint the business logo's path again: another business
    (or none read yet, or marked stale with 0) or a path older than
    `LOGO_FRESH_SECONDS`. Without a session there is nothing to read."""
    if not tenant:
        return False
    if tenant != logo_tenant or fetched_at <= 0:
        return True
    return now - fetched_at >= LOGO_FRESH_SECONDS


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


def business_menu(names: Sequence[str], active_index: int) -> list[dict[str, str]]:
    """The sidebar's «Cambiar de negocio» list (alternative B): EVERY business of the
    login in the login's order, the open one flagged `current` ("1") so the menu marks it
    «Aquí estás» instead of offering it. Positions only, never tenant ids."""
    return [
        {"index": str(i), "name": name, "current": "1" if i == active_index else ""}
        for i, name in enumerate(names)
    ]


__all__ = [
    "CHOICE_EXPIRED",
    "CLOSE_DRAWER_LABEL",
    "COLLAPSE_LABEL",
    "EXPAND_LABEL",
    "HERE_LABEL",
    "LOGO_FRESH_SECONDS",
    "CREDIT_LABEL",
    "SHORTCUT_HINT",
    "CHOOSE_HELP",
    "CHOOSE_ROUTE",
    "CHOOSE_TAB_TITLE",
    "CHOOSE_TITLE",
    "LEAVE_LABEL",
    "SWITCH_DOWN",
    "SWITCH_MENU_LABEL",
    "SWITCH_NO_ACCESS",
    "SWITCH_PASS_DEAD",
    "business_menu",
    "chip_label",
    "credit_aria",
    "logo_needs_refresh",
    "opening_label",
    "parse_choice_index",
    "rail_toggle_title",
    "switch_choices",
    "switch_trigger_aria",
    "trigger_label",
]
