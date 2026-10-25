"""m-24852260 (PASOS-13): the menu always shows which module you are in.

Every `app.add_page` route of Qualify.py, opened at a real address (`/drafts/123`, not
the `/drafts/[draft_id]` pattern), lights exactly one entry of the sidebar and exactly
one cell of the phone's bottom bar — or, in the sidebar, none for the routes outside the
menu listed below. «/» lights «Inicio» in both. Both navigations are lit by the same
rule (`nav_vm.is_current`), which reads the browser's path (`router.url.path`), never the
matched pattern (`router.page.path` is `/index` on «/»).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from qualify_api.auth import LEGACY_SIGNUP_ROUTE, SIGNUP_ROUTE

from .auth_state import BRAND_START_ROUTE, RESET_ROUTE
from .planner_vm import week_return_query
from .ui import layout, nav_vm

_HERE = Path(__file__).parent

# Names a route may be given by in Qualify.py (anything else fails the collection, so a
# new route cannot slip past this test).
_ROUTE_NAMES = {
    "RESET_ROUTE": [RESET_ROUTE],
    "BRAND_START_ROUTE": [BRAND_START_ROUTE],
    "_signup_route": [SIGNUP_ROUTE, LEGACY_SIGNUP_ROUTE],
}

# A real address for each dynamic route.
_REAL_PATH = {"/drafts/[draft_id]": "/drafts/123"}


def _registered_routes() -> list[str]:
    tree = ast.parse((_HERE / "Qualify.py").read_text(encoding="utf-8"))
    routes: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_page"
        ):
            continue
        route = {k.arg: k.value for k in node.keywords}.get("route", ast.Constant("/"))
        if isinstance(route, ast.Constant):
            routes.append(route.value)
        elif isinstance(route, ast.Name) and route.id in _ROUTE_NAMES:
            routes.extend(_ROUTE_NAMES[route.id])
        else:
            raise AssertionError(f"unknown route expression in Qualify.py: {ast.dump(route)}")
    return routes


_ENTRY_BY_LABEL = {label: route for label, _icon, route, _enabled in layout.NAV_ITEMS}

# Registered route → the sidebar entry it lights (None = a route outside the menu: the
# pre-login screens, the team's design guide, the Canva return legs — which redirect
# into the screen that opened them — and the Brand Kit creation steps of the guest rail).
_SIDEBAR_EXPECTED: dict[str, str | None] = {
    "/": "Inicio",
    "/vitrina": "Inicio",  # only redirects home
    "/responder": "Por responder",
    "/inbox": "Por responder",
    "/conversations": "Por responder",
    "/leads": "Por responder",
    "/whatsapp": "WhatsApp",
    "/create": "Crear publicación",
    "/drafts": "Por aprobar",
    "/drafts/[draft_id]": "Por aprobar",
    "/planner": "Tu semana",
    "/publish": "Publicar ahora",
    "/stories": "Publicar ahora",  # only redirects into Publicar ahora
    "/resultados": "Resultados",
    "/menciones": "Resultados",
    "/clarity": "Resultados",
    "/creadores": "Creadores",
    "/signals": "Oportunidades",
    "/brand/kit": "Tu marca",
    "/catalog": "Tus productos",
    "/connections": "Tus redes",
    "/settings": "Configuración",
    # Outside the menu.
    "/design": None,
    "/design/pasos": None,
    "/login": None,
    SIGNUP_ROUTE: None,
    LEGACY_SIGNUP_ROUTE: None,
    "/forgot": None,
    RESET_ROUTE: None,
    BRAND_START_ROUTE: None,
    "/brand": None,
    "/brand/manual": None,
    "/brand/connect": None,
    "/brand/connect/setup": None,
    "/canva/callback": None,
    "/canva/return": None,
}

_BOTTOM_ROUTES = [route for _label, _source, _icon, route in layout.NAV_BOTTOM]
_BOTTOM_LABEL = {route: label for label, _source, _icon, route in layout.NAV_BOTTOM}


def _path(route: str) -> str:
    return _REAL_PATH.get(route, route)


def _lit_sidebar(path: str, query: dict[str, str] | None = None) -> list[str]:
    routes = nav_vm.current_routes(layout.NAV_ROUTES, path, query)
    by_route = {route: label for label, route in _ENTRY_BY_LABEL.items()}
    return [by_route[route] for route in routes]


def _lit_bottom(path: str, query: dict[str, str] | None = None) -> str:
    """The one bottom-bar cell lit: one of the four, or «Más» when none of them is."""
    from_week = nav_vm.comes_from_week(query or {})
    lit = [
        _BOTTOM_LABEL[route]
        for route in _BOTTOM_ROUTES
        if nav_vm.is_current(route, layout.NAV_ROUTES, path, from_week)
    ]
    assert len(lit) <= 1, f"{path}: {lit}"
    return lit[0] if lit else layout.MORE_LABEL


def test_every_registered_route_has_an_expectation() -> None:
    assert sorted(set(_registered_routes())) == sorted(_SIDEBAR_EXPECTED)


@pytest.mark.parametrize("route", sorted(_SIDEBAR_EXPECTED))
def test_each_route_lights_exactly_its_sidebar_entry(route: str) -> None:
    expected = _SIDEBAR_EXPECTED[route]
    assert _lit_sidebar(_path(route)) == ([expected] if expected else [])


@pytest.mark.parametrize("route", sorted(_SIDEBAR_EXPECTED))
def test_each_route_lights_exactly_one_bottom_cell(route: str) -> None:
    expected = _SIDEBAR_EXPECTED[route]
    entry_route = _ENTRY_BY_LABEL.get(expected) if expected else None
    want = _BOTTOM_LABEL.get(entry_route, layout.MORE_LABEL)
    assert _lit_bottom(_path(route)) == want


def test_home_lights_inicio_in_both_navigations() -> None:
    assert _lit_sidebar("/") == ["Inicio"]
    assert _lit_bottom("/") == "Inicio"
    # …and only on «/»: every path starts with «/».
    assert "Inicio" not in _lit_sidebar("/planner")


def test_a_ficha_lights_por_aprobar_and_from_tu_semana_lights_tu_semana() -> None:
    assert _lit_sidebar("/drafts/123") == ["Por aprobar"]
    assert _lit_bottom("/drafts/123") == layout.MORE_LABEL  # «Por aprobar» is in «Más»
    query = dict(
        pair.split("=", 1) for pair in week_return_query("2026-10-19", "lista")[1:].split("&")
    )
    assert _lit_sidebar("/drafts/123", query) == ["Tu semana"]
    assert _lit_bottom("/drafts/123", query) == "Tu semana"
    # The list itself is never «Tu semana», whatever its query says.
    assert _lit_sidebar("/drafts", query) == ["Por aprobar"]


def test_a_query_or_a_trailing_view_keeps_the_entry() -> None:
    assert _lit_sidebar("/planner/") == ["Tu semana"]
    assert _lit_sidebar("/publish", {"flow": "stories"}) == ["Publicar ahora"]
    # A prefix that is not a sub-screen lights nothing.
    assert _lit_sidebar("/draftsx") == []


def test_the_guest_rail_lets_the_more_specific_entry_win() -> None:
    def lit(path: str) -> list[str]:
        return nav_vm.current_routes(layout.GUEST_ROUTES, path)

    assert lit("/brand") == ["/brand"]
    assert lit(BRAND_START_ROUTE) == ["/brand"]
    assert lit("/brand/manual") == ["/brand"]
    assert lit("/brand/kit") == ["/brand/kit"]
    assert lit(SIGNUP_ROUTE) == [SIGNUP_ROUTE]
    assert lit("/login") == ["/login"]


def test_the_page_reads_the_browser_path_never_the_route_pattern() -> None:
    rendered = str(layout.route_is_current("/"))
    assert "rx_router_url" in rendered
    assert "rx_router_page" not in rendered
    source = (_HERE / "ui" / "layout.py").read_text(encoding="utf-8")
    assert "router.page.path" not in source.replace("``router.page.path``", "")


def test_active_is_never_the_capsule_alone() -> None:
    """Accent colour + weight 600 + `aria-current="page"` (not only the glass capsule)."""
    rendered = str(layout._nav_item("Inicio", "house", "/", True).render())
    assert '"page"' in rendered
    assert '"600"' in rendered
    assert "accent-11" in rendered
