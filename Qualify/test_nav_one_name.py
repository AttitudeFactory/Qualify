"""m-24842958 (N1, docs/ux-guia-navegacion.md §4): one name per place.

For every enabled menu entry, the label in `ui/layout.py`, the `h1` of the page's
`page_header` and the browser tab title `Qualify · <nombre>` in `Qualify.py` are the same
words — the owner's, never the team's («Brand Kit», «Leads», «Piezas»…).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from .ui.layout import NAV_ITEMS

_HERE = Path(__file__).parent

# Route → the module whose `page_header` (or `creative_pages._screen`) names the page.
_PAGE_SOURCE: dict[str, str] = {
    "/": "components.py",
    "/connections": "connections_page.py",
    "/whatsapp": "whatsapp_page.py",
    "/inbox": "inbox_page.py",
    "/conversations": "conversations_page.py",
    "/create": "content_generator.py",
    "/drafts": "creative_pages.py",
    "/planner": "planner_page.py",
    "/publish": "publishing_page.py",
    "/leads": "leads_page.py",
    "/clarity": "clarity_page.py",
    "/brand/kit": "brand_kit_editor.py",
    "/catalog": "catalog_page.py",
    "/settings": "settings_page.py",
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


def _enabled_items() -> list[tuple[str, str]]:
    return [(label, route) for label, _icon, route, enabled in NAV_ITEMS if enabled]


def test_every_enabled_menu_entry_has_a_known_page() -> None:
    assert {route for _label, route in _enabled_items()} <= set(_PAGE_SOURCE)


@pytest.mark.parametrize(("label", "route"), _enabled_items())
def test_menu_label_header_and_tab_title_are_the_same_name(label: str, route: str) -> None:
    title = _tab_titles()[route]
    assert title.startswith("Qualify · ")
    name = title.removeprefix("Qualify · ")
    assert _MENU_SHORT_FORM.get(route, name) == label

    page_source = (_HERE / _PAGE_SOURCE[route]).read_text(encoding="utf-8")
    header = re.compile(r"(?:page_header|_screen)\(\s*\"" + re.escape(name) + r"\"")
    assert header.search(page_source), f"{_PAGE_SOURCE[route]} has no h1 «{name}»"


def test_no_menu_entry_or_tab_title_uses_an_old_name() -> None:
    names = [label for label, *_ in NAV_ITEMS] + list(_tab_titles().values())
    for name in names:
        for old in _OLD_NAMES:
            assert old not in name, f"«{name}» still says «{old}»"
