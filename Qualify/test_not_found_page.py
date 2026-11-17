"""The app's own 404 (m-24840374): it renders in Spanish with its way back, and it is
the page Reflex registers under its 404 slug."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from reflex.constants import Page404
from reflex_base.utils.format import format_route

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
    assert "q-nf-scene" in rendered
    # Always `/`: its on_load sends each visitor to Inicio, the brand draft or its start.
    assert "'to:\"/\"'" in rendered


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
    # Reflex's own normalisation of the route is what makes it the 404 page.
    assert format_route(keywords["route"]) == Page404.SLUG
