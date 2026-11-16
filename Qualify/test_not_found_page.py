"""The app's own 404 (m-24840374): it renders in Spanish with its way back, and it is
the page Reflex registers under its 404 slug."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import reflex as rx
from reflex.constants import Page404

from .not_found_page import (
    NOT_FOUND_ACTION,
    NOT_FOUND_TAB_TITLE,
    NOT_FOUND_TEXT,
    NOT_FOUND_TITLE,
    not_found_index,
)

_HERE = Path(__file__).parent


def test_page_renders_title_text_and_button() -> None:
    rendered = str(not_found_index().render())
    for text in (NOT_FOUND_TITLE, NOT_FOUND_TEXT, NOT_FOUND_ACTION):
        # The render escapes non-ASCII as JSON does, inside a repr.
        assert json.dumps(text)[1:-1].replace("\\", "\\\\") in rendered, text
    assert NOT_FOUND_TITLE == "Esta página no existe"
    assert "q-nf-scene" in rendered
    assert "is_authenticated" in rendered  # Inicio with a session, the login without


def test_registered_as_the_reflex_404() -> None:
    source = (_HERE / "Qualify.py").read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "add_page"
        and node.args
        and getattr(node.args[0], "id", "") == "not_found_index"
    ]
    assert len(calls) == 1
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in calls[0].keywords}
    assert keywords["title"] == NOT_FOUND_TAB_TITLE
    app = rx.App()
    app.add_page(not_found_index, route=keywords["route"], title=keywords["title"])
    assert Page404.SLUG in app._unevaluated_pages
