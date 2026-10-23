"""m-24842957 (NAV-1): the menu follows the map of docs/ux-guia-navegacion.md §3.

Inicio · Atiende · Publica · Resultados · Tu negocio, ordered by the owner's jobs, with
Creadores and Oportunidades marked «Pronto» (N10) and no demo or team tool in the menu.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from .ui import layout
from .ui.layout import (
    BUSINESS_ZONE_LABEL,
    NAV_BUSINESS,
    NAV_HOME,
    NAV_ITEMS,
    NAV_RESULTS,
    NAV_ZONES,
)

_HERE = Path(__file__).parent

# The 12 entries of the guide §3, in its order.
_GUIDE_MAP = [
    "Inicio",
    "Por responder",
    "WhatsApp",
    "Crear publicación",
    "Por aprobar",
    "Tu semana",
    "Publicar ahora",
    "Resultados",
    "Tu marca",
    "Tus productos",
    "Tus redes",
    "Configuración",
]
_SOON = ["Creadores", "Oportunidades"]


def _registered_routes() -> set[str]:
    tree = ast.parse((_HERE / "Qualify.py").read_text(encoding="utf-8"))
    routes: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_page"
        ):
            kw = {k.arg: k.value for k in node.keywords}
            route = kw.get("route", ast.Constant("/"))
            if isinstance(route, ast.Constant):
                routes.add(route.value)
    return routes


def test_the_menu_has_the_twelve_entries_of_the_guide_in_order() -> None:
    usable = [label for label, _icon, _route, enabled in NAV_ITEMS if enabled]
    assert usable == _GUIDE_MAP


def test_creadores_and_oportunidades_are_the_only_soon_entries() -> None:
    assert [label for label, _icon, _route, enabled in NAV_ITEMS if not enabled] == _SOON
    assert [label for label, *_ in NAV_RESULTS] == ["Resultados", *_SOON]


def test_the_blocks_are_inicio_atiende_publica_resultados_tu_negocio() -> None:
    assert [label for label, *_ in NAV_HOME] == ["Inicio"]
    assert [(zone, title) for zone, title, _items in NAV_ZONES] == [
        ("listen", "Atiende"),
        ("publish", "Publica"),
    ]
    zones = {zone: [label for label, *_ in items] for zone, _title, items in NAV_ZONES}
    assert zones["listen"] == ["Por responder", "WhatsApp"]
    assert zones["publish"] == ["Crear publicación", "Por aprobar", "Tu semana", "Publicar ahora"]
    assert BUSINESS_ZONE_LABEL == "Tu negocio"
    assert [label for label, *_ in NAV_BUSINESS] == [
        "Tu marca",
        "Tus productos",
        "Tus redes",
        "Configuración",
    ]


def test_no_demo_or_team_tool_is_in_the_menu() -> None:
    routes = {route for _label, _icon, route, _enabled in NAV_ITEMS}
    assert not routes & {"/design", "/vitrina", "#"}
    assert not any("vitrina" in label.lower() for label, *_ in NAV_ITEMS)


def test_every_menu_entry_opens_a_registered_screen() -> None:
    routes = {route for _label, _icon, route, _enabled in NAV_ITEMS}
    assert routes <= _registered_routes()
    assert len(routes) == len(NAV_ITEMS), "two entries share a route"


@pytest.mark.parametrize("route", ["/", "/inbox", "/conversations", "/leads", "/clarity"])
def test_old_addresses_keep_working(route: str) -> None:
    """No saved link breaks (guide §3): each old address is still a registered page."""
    assert route in _registered_routes()


def test_stories_still_redirects_into_publicar_ahora() -> None:
    source = (_HERE / "Qualify.py").read_text(encoding="utf-8")
    assert 'rx.redirect("/publish?flow=stories", replace=True)' in source


def test_a_soon_row_says_pronto_in_text_and_is_a_link() -> None:
    for label, icon, route, enabled in NAV_ITEMS:
        if enabled:
            continue
        rendered = str(layout._nav_item(label, icon, route, enabled).render())
        assert "Pronto" in rendered, label
        assert route in rendered, label
        assert "aria-disabled" not in rendered and "aria_disabled" not in rendered


@pytest.mark.parametrize(
    ("module", "action_route"),
    [("creators_page.py", "/create"), ("signals_page.py", "/conversations")],
)
def test_a_soon_screen_says_what_is_coming_and_where_to_go_today(
    module: str, action_route: str
) -> None:
    """N10 + N8: never an empty screen — «Pronto», then one button that works today."""
    source = (_HERE / module).read_text(encoding="utf-8")
    assert 'tone_badge("Pronto"' in source
    assert "empty_state(" in source and "action=" in source
    assert f'href="{action_route}"' in source
