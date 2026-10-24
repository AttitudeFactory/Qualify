"""m-24842958 (N1, docs/ux-guia-navegacion.md §4): one name per place.

For every menu entry («Pronto» ones included), the label in `ui/layout.py`, the `h1` of the page's
`page_header` and the browser tab title `Qualify · <nombre>` in `Qualify.py` are the same
words — the owner's, never the team's («Brand Kit», «Leads», «Piezas»…).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from .ui.layout import NAV_ITEMS, RESULTS_ROUTE

_HERE = Path(__file__).parent

# Route → the module whose `page_header` (or `creative_pages._screen`) names the page.
_PAGE_SOURCE: dict[str, str] = {
    "/": "home_page.py",
    "/menciones": "components.py",
    "/connections": "connections_page.py",
    "/whatsapp": "whatsapp_page.py",
    "/inbox": "inbox_page.py",
    "/conversations": "conversations_page.py",
    "/responder": "responder_page.py",
    "/create": "content_generator.py",
    "/drafts": "creative_pages.py",
    "/planner": "planner_page.py",
    "/publish": "publishing_page.py",
    "/leads": "leads_page.py",
    "/clarity": "clarity_page.py",
    "/brand/kit": "brand_kit_editor.py",
    "/catalog": "catalog_page.py",
    "/settings": "settings_page.py",
    "/creadores": "creators_page.py",
    "/signals": "signals_page.py",
}

# NAV-1 (m-24842957): three hubs of the menu map are built by other stories. Until each
# lands, its entry points at today's closest screen, whose own name is still the old
# one. label → (the route it points at today, the hub's own route, the ticket).
# `test_a_pending_hub_is_switched_the_day_it_lands` fails as soon as the hub exists, so
# this table only shrinks.
# Inicio (m-24842962) and «Por responder» (m-24842990) have landed and left the table.
_PENDING_HUBS: dict[str, tuple[str, str, str]] = {
    "Resultados": (RESULTS_ROUTE, "/resultados", "m-24843003"),
}

# The one sanctioned short form (ticket m-24842958): the page is «Clientes interesados»,
# the rail has room for «Interesados».
_MENU_SHORT_FORM: dict[str, str] = {"/leads": "Interesados"}

_OLD_NAMES = (
    "Brand Kit",
    "Brandkit",
    "Catálogo",
    "Conexiones",
    "Cuentas conectadas",
    "pieza",
    "Piezas",
    "Planificador",
    "Stories",
    "Interacciones",
    "Leads",
    "Clarity",
    "Borrador",
)


def _tab_titles() -> dict[str, str]:
    """route → `title=` of every `app.add_page(...)` in Qualify.py."""
    tree = ast.parse((_HERE / "Qualify.py").read_text(encoding="utf-8"))
    titles: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_page"
        ):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        # A page registered without `route=` is the index (Reflex's default: "/").
        route, title = kw.get("route", ast.Constant("/")), kw.get("title")
        if isinstance(route, ast.Constant) and isinstance(title, ast.Constant):
            titles[route.value] = title.value
    return titles


def _menu_items() -> list[tuple[str, str]]:
    """Every menu entry — «Pronto» ones too: they open a screen of their own (N10)."""
    return [(label, route) for label, _icon, route, _enabled in NAV_ITEMS]


def _hub_has_landed(label: str) -> bool:
    _today, hub_route, _ticket = _PENDING_HUBS[label]
    return _tab_titles().get(hub_route) == f"Qualify · {label}"


def test_every_menu_entry_has_a_known_page() -> None:
    assert {route for _label, route in _menu_items()} <= set(_PAGE_SOURCE)


@pytest.mark.parametrize("label", sorted(_PENDING_HUBS))
def test_a_pending_hub_is_switched_the_day_it_lands(label: str) -> None:
    today, hub_route, ticket = _PENDING_HUBS[label]
    route = next(r for name, r in _menu_items() if name == label)
    assert route == today
    assert not _hub_has_landed(label), (
        f"«{label}» ({ticket}) now has its own screen at {hub_route}: point the menu entry "
        f"there (ui/layout.py) and drop it from _PENDING_HUBS."
    )


@pytest.mark.parametrize(
    ("label", "route"), [item for item in _menu_items() if item[0] not in _PENDING_HUBS]
)
def test_menu_label_header_and_tab_title_are_the_same_name(label: str, route: str) -> None:
    title = _tab_titles()[route]
    assert title.startswith("Qualify · ")
    name = title.removeprefix("Qualify · ")
    assert _MENU_SHORT_FORM.get(route, name) == label

    page_source = (_HERE / _PAGE_SOURCE[route]).read_text(encoding="utf-8")
    header = re.compile(r"(?:page_header|_screen)\(\s*\"" + re.escape(name) + r"\"")
    assert header.search(page_source), f"{_PAGE_SOURCE[route]} has no h1 «{name}»"


# A text that SENDS the owner to a place names it with the menu's word (N1): «en Piezas»,
# «Ir a Conexiones», «desde el Planificador», «Negocio → Brand Kit»… Concept uses («tu
# Brand Kit no permite…») are the domain copy tickets' and are not matched here.
_OLD_PLACE = r"(?:Piezas|Planificador|Catálogo|Conexiones|Interacciones|Crear pieza|Brand Kit)"
_OLD_DESTINATION = re.compile(
    r"(?:\b(?:en|a|de|desde)\s+(?:el\s+|mi\s+)?«?" + _OLD_PLACE + r"»?(?=[\s.,:;»]|$)"
    r"|→\s*" + _OLD_PLACE + r"|^Crear pieza$)"
)


def _client_strings() -> list[tuple[str, int, str]]:
    """Every string literal of the app's modules (tests excluded), docstrings skipped."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(_HERE.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                found.append((path.name, node.lineno, node.value))
    return found


def test_no_text_sends_the_owner_to_a_place_by_its_old_name() -> None:
    offenders = [
        f"{name}:{line}: {text!r}"
        for name, line, text in _client_strings()
        if _OLD_DESTINATION.search(text)
    ]
    assert not offenders, "\n".join(offenders)


def test_the_destination_check_catches_the_old_forms() -> None:
    for text in (
        "Revísala en Piezas.",
        "Ir a Conexiones",
        "ya puedes programarlo en el Planificador.",
        "desde Negocio → Brand Kit.",
        "búscalos en «Catálogo» o súbelos.",
        "Ir a mi Brand Kit",
        "Crear pieza",
    ):
        assert _OLD_DESTINATION.search(text), text
    for concept in ("Lo que tu Brand Kit no permite", "Es una regla de tu Brand Kit."):
        assert not _OLD_DESTINATION.search(concept), concept


def test_no_menu_entry_or_tab_title_uses_an_old_name() -> None:
    names = [label for label, *_ in NAV_ITEMS] + list(_tab_titles().values())
    for name in names:
        for old in _OLD_NAMES:
            assert old not in name, f"«{name}» still says «{old}»"
