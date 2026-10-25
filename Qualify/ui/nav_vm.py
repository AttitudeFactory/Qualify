"""Which menu entry is «you are here» (m-24852260, PASOS-13).

ONE rule for both navigations — the sidebar and the phone's bottom bar — written once
and evaluated two ways: with plain ``str``/``bool`` in the tests, and with Reflex Vars in
the page (``NavState.router.url.path``, the path the browser shows). Never the matched
route pattern (``router.page.path``): Reflex registers «/» as ``/index`` and a ficha as
``/drafts/[draft_id]``, so comparing against it left «Inicio» and every sub-screen dark.

The rule, for an entry whose route is ``route``:

* «/» lights only on «/» (every path starts with ``/``);
* any other entry lights on ``route`` and on its own sub-screens ``route/…``
  (``/drafts/123`` lights «Por aprobar»), and on the old addresses that only redirect to
  it (``/menciones`` → «Resultados»), so the menu is right even before the redirect lands;
* when another entry's route is a sub-screen of this one (the guest rail has «Crea tu
  marca» ``/brand`` and «Tu marca» ``/brand/kit``), the more specific one wins;
* a ficha opened from Tu semana (``/drafts/<id>?desde=semana``) lights «Tu semana», not
  «Por aprobar» — the module the owner came from (rule N7, ``planner_back.py``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import reflex as rx

from ..planner_vm import FROM_WEEK, URL_FROM

HOME_ROUTE = "/"
DRAFTS_ROUTE = "/drafts"
PLANNER_ROUTE = "/planner"

# Old addresses that only redirect into an entry (Qualify.py): the entry they land on.
ROUTE_ALIASES: dict[str, tuple[str, ...]] = {
    HOME_ROUTE: ("/vitrina",),
    "/responder": ("/inbox", "/conversations", "/leads"),
    "/resultados": ("/menciones", "/clarity"),
    "/publish": ("/stories",),
}

# A bool in the tests, a BooleanVar / StringVar in the page.
Cond = Any
Path = Any


def _not(cond: Cond) -> Cond:
    return ~cond if isinstance(cond, rx.Var) else not cond


def _under(path: Path, route: str) -> Cond:
    """``route`` itself or one of its own screens (``route/…``)."""
    return (path == route) | path.startswith(f"{route}/")


def is_current(route: str, routes: Iterable[str], path: Path, from_week: Cond) -> Cond:
    """Whether the entry at ``route`` is the current one, among the entries ``routes`` of
    the same navigation. ``path`` is the browser's path (no query); ``from_week`` whether
    the address carries ``?desde=semana``."""
    routes = tuple(routes)
    lit = path == HOME_ROUTE if route == HOME_ROUTE else _under(path, route)
    for alias in ROUTE_ALIASES.get(route, ()):
        lit = lit | _under(path, alias)
    if route != HOME_ROUTE:
        for other in routes:
            if other != route and other.startswith(f"{route}/"):
                lit = lit & _not(_under(path, other))
    ficha_from_week = path.startswith(f"{DRAFTS_ROUTE}/") & from_week
    if route == DRAFTS_ROUTE and PLANNER_ROUTE in routes:
        lit = lit & _not(ficha_from_week)
    if route == PLANNER_ROUTE:
        lit = lit | ficha_from_week
    return lit


def comes_from_week(query_parameters: Mapping[str, object]) -> bool:
    """``?desde=semana`` in a parsed query (the test-side twin of the page's Var)."""
    return str(query_parameters.get(URL_FROM, "") or "") == FROM_WEEK


def current_routes(
    routes: Iterable[str], path: str, query_parameters: Mapping[str, object] | None = None
) -> list[str]:
    """The entries lit for ``path`` (and its query): at most one for every path."""
    routes = tuple(routes)
    from_week = comes_from_week(query_parameters or {})
    return [route for route in routes if is_current(route, routes, path, from_week)]
