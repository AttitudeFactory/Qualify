"""RESULTADOS-6 (m-24849134): «Señales» is called «Oportunidades» (founder decision §2b-6).

Menu, `h1` and browser tab say «Oportunidades» (N1); the entry carries «Pronto» as text and
opens a screen with a next step, never an empty one (N10); no client-visible string in the
app says «Señales» or «Avisos de oportunidad».
"""

from __future__ import annotations

import ast
from pathlib import Path

from .ui.layout import NAV_ITEMS, RESPOND_ROUTE

_HERE = Path(__file__).parent
_NAME = "Oportunidades"
_ROUTE = "/signals"
_RETIRED = ("Señales", "Avisos de oportunidad")


def _client_strings(path: Path) -> list[tuple[int, str]]:
    """Every string literal of a module except docstrings (comments never reach the AST)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_menu_entry_is_oportunidades_marked_pronto() -> None:
    entries = [item for item in NAV_ITEMS if item[2] == _ROUTE]
    assert len(entries) == 1
    label, _icon, _route, enabled = entries[0]
    assert label == _NAME
    # disabled = a «Pronto» entry: still a link, with the word «Pronto» as text (layout).
    assert enabled is False


def test_h1_and_tab_title_say_oportunidades() -> None:
    page = (_HERE / "signals_page.py").read_text(encoding="utf-8")
    assert f'page_header(\n            "{_NAME}",' in page
    assert 'tone_badge("Pronto", "neutral")' in page
    app = (_HERE / "Qualify.py").read_text(encoding="utf-8")
    assert f'route="{_ROUTE}"' in app
    assert f'title="Qualify · {_NAME}"' in app


def test_the_pronto_screen_is_never_a_dead_end() -> None:
    from .signals_page import signals_index

    rendered = str(signals_index().render())
    assert "Ir a Por responder" in rendered
    assert RESPOND_ROUTE in rendered


def test_no_visible_string_says_the_retired_names() -> None:
    offenders = [
        f"{path.name}:{line}: {text!r}"
        for path in sorted([*_HERE.glob("*.py"), *(_HERE / "ui").glob("*.py")])
        if not path.name.startswith("test_")
        for line, text in _client_strings(path)
        if any(old in text for old in _RETIRED)
    ]
    assert offenders == []
