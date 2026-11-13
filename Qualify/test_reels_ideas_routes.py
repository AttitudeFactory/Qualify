"""R7 (m-24854854, UX review 4): the reels ideas' empty states lead to «Negocios parecidos
al tuyo» on the brand page — open and in view — and «‹ Ideas de videos» leads back to the
ideas on /create. No dead end, and the way back says where it goes (N4, N7)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from reflex.istate.data import ReflexURL, RouterData

from . import brand_kit_editor as editor
from . import creative_state as creative_state_module
from .brand_kit_editor import BrandEditState
from .catalog_vm import (
    IDEAS_MODE,
    IDEAS_RETURN_PATH,
    RETURN_LABEL,
    brand_referentes_href,
    create_mode_from_query,
    return_label_for,
)
from .creative_state import CreativeState
from .test_return_with_product import _NEW, _OLD, _catalog, _fake_session_ids


def _router(path_and_query: str) -> RouterData:
    return RouterData(url=ReflexURL(f"http://localhost:3000{path_and_query}"))


def test_the_link_opens_the_referentes_with_the_way_back_to_the_ideas() -> None:
    href = brand_referentes_href(IDEAS_RETURN_PATH)
    assert href == "/brand/kit?seccion=referentes&volver=%2Fcreate%3Fmodo%3Dideas"
    assert brand_referentes_href("https://otro.sitio/") == "/brand/kit?seccion=referentes"
    assert create_mode_from_query({"modo": "ideas"}) == IDEAS_MODE
    assert create_mode_from_query({"modo": "variaciones"}) == "variaciones"
    assert create_mode_from_query({"modo": "otro"}) == ""


def test_the_way_back_says_where_it_leads() -> None:
    assert return_label_for("/create?modo=ideas") == "Ideas de videos"
    assert return_label_for("/create") == RETURN_LABEL
    assert return_label_for("/create?modo=variaciones") == RETURN_LABEL
    assert return_label_for("/drafts/abc?modo=ideas") == RETURN_LABEL


def _brand_page(query: str, monkeypatch: pytest.MonkeyPatch) -> BrandEditState:
    states: dict[type, Any] = {
        BrandEditState: BrandEditState(),
        editor.BrandConnectState: editor.BrandConnectState(),
    }

    async def get_state(_self: Any, cls: type) -> Any:
        return states[cls]

    monkeypatch.setattr(BrandEditState, "get_state", get_state)
    page = states[BrandEditState]
    page.router = _router(f"/brand/kit{query}")
    return page


def test_the_brand_page_opens_the_referentes_and_brings_them_into_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _brand_page("?seccion=referentes&volver=%2Fcreate%3Fmodo%3Dideas", monkeypatch)
    assert asyncio.run(BrandEditState.restart.fn(page)) is None
    assert page.referentes_open is True and page.focus_section == ""
    assert page.return_to == "/create?modo=ideas"
    assert page.return_label == "Ideas de videos"
    # UX re-check 2: no timed wait — the section's own mount (after the saved details)
    # brings it into view, once
    assert page.scroll_to_referentes is True
    fired = BrandEditState.referentes_in_view.fn(page)
    assert "seccion-referentes" in str(fired) and page.scroll_to_referentes is False
    assert BrandEditState.referentes_in_view.fn(page) is None
    # an ordinary visit keeps every section folded and asks nothing to scroll
    plain = _brand_page("", monkeypatch)
    assert asyncio.run(BrandEditState.restart.fn(plain)) is None
    assert plain.referentes_open is False and plain.return_label == ""
    assert plain.scroll_to_referentes is False


def test_the_way_back_to_the_ideas_is_only_the_link() -> None:
    """Nothing on the way back to the ideas waits for a save: the publication's reminder
    is not shown, and the link reads «‹ Ideas de videos»."""
    rendered = str(editor._return_banner())
    assert "Ideas de videos" in rendered and "ChevronLeft" in rendered
    assert "vuelve para seguir con tu publicaci" in rendered  # still there for a publication


async def test_create_reopens_on_the_ideas_with_the_owners_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(CreativeState, "_session_ids", _fake_session_ids)
    monkeypatch.setattr(
        creative_state_module,
        "catalog_products",
        lambda tenant_id, brand_id: _catalog(_OLD, _NEW),
    )
    state = CreativeState()
    state.router = _router("/create?modo=ideas")
    state.catalog_items = [dict(item) for item in _catalog(_OLD)]
    state.choose_product(_OLD)
    state.product_confirmed = True
    state.gen_mode = "create"

    await CreativeState.load_catalog_products.fn(state)

    assert state.gen_mode == "discover"
    assert state.selected_product_id == _OLD and state.product_confirmed is True


# --------------------------------------------------------------------------------------
# UX review 6: on a phone the ideas start in sight
# --------------------------------------------------------------------------------------


def test_choosing_an_option_lands_its_title_under_the_sticky_header() -> None:
    """`_scroll_to_view` aligns `#q-cr-view` 8 px under the sticky page header as drawn at
    that moment, in the box that scrolls; a second pass only corrects a title the header
    ended up covering (it may grow as the option opens) and never fights a good spot."""
    from .creative_state import _ALIGN_VIEW_JS
    from .test_route_history import _node

    result = _node(
        r"""
const calls = [];
const headRect = {bottom: 167};
let viewTop = 600;
const body = {};
const scroller = {parentElement: body, scrollHeight: 2000, clientHeight: 800,
  scrollBy(o) { calls.push(o); viewTop -= o.top; }};
const main = {querySelector(sel) {
  return sel === '.q-page-header' ? {getBoundingClientRect() { return headRect; }} : null; }};
const view = {parentElement: scroller,
  closest(sel) { return sel === 'main' ? main : null; },
  getBoundingClientRect() { return {top: viewTop}; }};
const document = {body, scrollingElement: {scrollBy(o) { calls.push(['page', o]); }},
  getElementById(id) { return id === 'q-cr-view' ? view : null; }};
const getComputedStyle = (el) => ({overflowY: el === scroller ? 'auto' : 'visible'});
"""
        + _ALIGN_VIEW_JS
        + r"""
align(true);
headRect.bottom = 200;  // the header grew as the option opened: the title is covered
align(false);
headRect.bottom = 100;  // a header that shrank leaves the title in sight: no move
align(false);
console.log(JSON.stringify(calls));
"""
    )
    assert result == [{"top": 425, "behavior": "smooth"}, {"top": -33, "behavior": "auto"}]


def test_the_ideas_do_not_carry_the_create_notices() -> None:
    """UX review 6: «Completa tu marca…» and «Tu marca todavía no tiene su voz…» are about
    creating a piece; in the ideas they pushed the first idea below a phone's screen."""
    import inspect

    from . import content_generator
    from .content_generator import _DISCOVER_HEADING

    workspace = inspect.getsource(content_generator._workspace)
    gate = workspace.index('CreativeState.gen_mode != "discover"')
    assert gate < workspace.index("_brand_flag()") < workspace.index("_voice_flag()")
    # UX review 8: the weekly rhythm, and the accounts by the screen's one name
    assert _DISCOVER_HEADING[1] == (
        "Cada lunes, los reels que mejor les funcionan a las cuentas que te inspiran, solo de "
        "tu producto o su categoría, para que hagas uno parecido."
    )


def test_the_referentes_come_into_view_when_they_mount() -> None:
    """The trigger lives inside «Negocios parecidos al tuyo», which is drawn only after
    the saved details: its mount is the moment to scroll (no 5-second guess), and the
    section carries the way back at its foot too."""
    section = editor._referentes_section()
    hooks = " ".join(section._get_all_hooks().keys())
    assert "referentes_in_view" in hooks  # on_mount of the hidden trigger
    rendered = str(section)
    assert "scroll_to_referentes" in rendered  # mounted only while asked
    assert "Ideas de videos" in rendered and "ChevronLeft" in rendered  # «‹ Ideas de videos»
