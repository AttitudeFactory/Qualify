"""m-24842961 (NAV-3): no empty state without a way out (N8), «¡Al día!» when nobody
waits (N3, N8) — pure checks and a static guard over the client screens."""

from __future__ import annotations

import ast
from pathlib import Path

from .next_steps_vm import ALL_CLEAR_BODY, ALL_CLEAR_TITLE, CREATE_LABEL, CREATE_ROUTE, all_clear

_APP = Path(__file__).parent

# The justified exceptions, listed in the PR: the way out sits right next to the empty
# state on the same screen, so a button inside it would duplicate it.
#   - stock search: the search box above IS the action («Busca una imagen…»);
#   - QR codes: the «Crear código» form sits directly above the empty list;
#   - WhatsApp chats detail pane: «Elige una conversación» — the list is beside it;
#   - the design guide (`styleguide_page.py`) and the primitive itself.
_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("content_generator.py", "Busca una imagen o un video para tu producto"),
        ("whatsapp_page.py", "Aún no tienes códigos QR"),
        ("whatsapp_tab_chats.py", "Elige una conversación"),
    }
)
_SKIP_FILES = frozenset({"styleguide_page.py"})


def _empty_states_without_action() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted(_APP.rglob("*.py")):
        if path.name.startswith("test_") or path.name in _SKIP_FILES or "ui" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "empty_state":
                continue
            has_action = any(k.arg == "action" for k in node.keywords) or len(node.args) >= 4
            if has_action:
                continue
            title = node.args[1] if len(node.args) > 1 else None
            text = title.value if isinstance(title, ast.Constant) else ast.unparse(title or node)
            found.append((path.name, str(text)))
    return found


def test_every_empty_state_of_a_client_screen_has_a_way_out() -> None:
    missing = [hit for hit in _empty_states_without_action() if hit not in _EXCEPTIONS]
    assert missing == [], f"empty_state without action= (N8): {missing}"


def test_the_exceptions_list_has_no_stale_entries() -> None:
    assert _EXCEPTIONS <= set(_empty_states_without_action())


def test_all_clear_copy_is_the_tickets() -> None:
    assert ALL_CLEAR_TITLE == "¡Al día!"
    assert ALL_CLEAR_BODY == "No hay nadie esperando tu respuesta."
    assert CREATE_LABEL == "Crear publicación"
    assert CREATE_ROUTE == "/create"


def test_all_clear_only_when_there_is_a_list_and_nothing_waits() -> None:
    assert all_clear(total=3, pending=0)
    assert not all_clear(total=3, pending=1)
    # An empty list is «nobody wrote yet», not «al día».
    assert not all_clear(total=0, pending=0)


def test_create_route_is_the_menus() -> None:
    from .ui.layout import NAV_ITEMS

    assert (CREATE_LABEL, CREATE_ROUTE) in {(label, route) for label, _i, route, _e in NAV_ITEMS}
