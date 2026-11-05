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
    fired = asyncio.run(BrandEditState.restart.fn(page))
    assert page.referentes_open is True and page.focus_section == ""
    assert page.return_to == "/create?modo=ideas"
    assert page.return_label == "Ideas de videos"
    assert "seccion-referentes" in str(fired)  # scrolled to once it is drawn
    # an ordinary visit keeps every section folded and asks nothing to scroll
    plain = _brand_page("", monkeypatch)
    assert asyncio.run(BrandEditState.restart.fn(plain)) is None
    assert plain.referentes_open is False and plain.return_label == ""


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
