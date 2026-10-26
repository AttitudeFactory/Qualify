"""«Mi catálogo · Imagen de stock» on the product screen (plan-integracion-stock R2,
2026-10-16, story STK-04b): the tab opens on the catalog, «Continuar» needs an image AND a
name, only a hit the session listed can be picked, and the imported image becomes THIS
piece's product photo with `product_source="stock"` on the brief. No network: the state's
handlers are called directly, the import's result is applied by hand."""

from __future__ import annotations

from uuid import UUID

import pytest

from . import stock_provider
from .creative_state import CreativeState

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_KEY = f"t/{_TENANT}/stock/pixabay/8434113/abcdef0123456789.jpg"


def _with_results(state: CreativeState) -> None:
    state.stock_results = [
        {
            "id": "pixabay:8434113",
            "thumb": "https://pixabay.com/get/x_640.jpg",
            "author": "Domihattenberger",
            "author_url": "https://pixabay.com/users/40104971/",
            "page_url": "https://pixabay.com/es/photos/x-8434113/",
            "provider": "pixabay",
            "provider_label": "Pixabay",
            "size": "4000×6000",
        }
    ]
    state._stock_items = {"pixabay:8434113": {"provider": "pixabay"}}


def test_the_screen_opens_on_the_catalog_and_never_on_stock() -> None:
    state = CreativeState()
    assert state.product_tab == "catalog" and state.product_source == "catalog"
    state.set_product_tab("nope")
    assert state.product_tab == "catalog"


def test_the_stock_tab_says_unavailable_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("Qualify.creative_state.stock_available", lambda: False)
    state = CreativeState()
    state.set_product_tab("stock")
    assert state.product_tab == "stock" and state.stock_on is False


def test_continue_needs_a_pick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("Qualify.creative_state.stock_available", lambda: False)
    state = CreativeState()
    state.set_product_tab("stock")
    _with_results(state)
    assert state.can_continue_product is False
    state.choose_stock_product("pixabay:8434113")
    assert state.stock_chosen[0]["author"] == "Domihattenberger"
    assert state.can_continue_product is True  # inspiration: no name asked
    state.stock_importing = True
    assert state.can_continue_product is False


def test_only_a_hit_the_session_listed_can_be_picked() -> None:
    state = CreativeState()
    _with_results(state)
    state.choose_stock_product("pixabay:999")  # not in this session's results
    assert state.stock_picks == []
    state.choose_stock_product("pixabay:8434113")
    state.choose_stock_product("pixabay:8434113")  # a second click unpicks
    assert state.stock_picks == []


def test_the_stock_tab_searches_with_the_brand_kit_the_first_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ request 2026-10-16: no typing needed — opening «Imagen de stock» searches with
    the Brand Kit's words; coming back keeps what was found (no second search)."""
    monkeypatch.setattr("Qualify.creative_state.stock_available", lambda: True)
    state = CreativeState()
    assert state.set_product_tab("stock") is not None  # chains search_stock_from_kit
    _with_results(state)
    state.vstock_results = [{"id": "pixabay:v1", "media_type": "video"}]  # and the videos
    state.set_product_tab("catalog")
    assert state.set_product_tab("stock") is None


def test_continue_on_the_stock_tab_imports_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("Qualify.creative_state.stock_available", lambda: False)
    state = CreativeState()
    state.set_product_tab("stock")
    assert state.confirm_product() is not None  # chains confirm_stock_product
    assert state.product_confirmed is False
    state.set_product_tab("catalog")
    state.selected_product_id = "catalog-product"
    assert state.confirm_product() is not None and state.product_confirmed is True


def test_the_imported_image_is_this_pieces_product_photo() -> None:
    state = CreativeState()
    state._apply_stock_selection(
        [{"key": _KEY, "view": "/r2media/tok", "asset_id": "4e0b3f7c-0000-4000-8000-000000000001"}],
        [],
    )
    assert state.product_confirmed is True
    assert state.product_source == "stock"
    assert state.brief_product_ref == "" and state.brief_topic == ""  # the rules say it
    assert state.selected_product_photo_key == _KEY
    assert state.product_photo_keys == [_KEY]
    assert state.piece_views[_KEY] == "/r2media/tok"  # shown from R2, not the upload store
    state.brief_kind = "static_flyer"
    media = state._media_inputs()
    assert media["product_source"] == "stock" and _KEY in media["product_keys"]

    # «Cambiar» keeps it; picking a catalog product puts the source back
    state.change_product()
    assert state.product_confirmed is False and state.product_source == "stock"
    state.catalog_items = [{"id": "p1", "name": "Smash", "photo_key": "", "photo_keys": ""}]
    state.choose_product("p1")
    assert state.product_source == "catalog"


def test_clearing_the_product_forgets_the_stock_source() -> None:
    state = CreativeState()
    state._apply_stock_selection([{"key": _KEY, "view": "", "asset_id": "x"}], [])
    state.clear_product()
    assert state.product_source == "catalog" and state.product_photo_keys == []


def test_the_credit_line_names_each_bank_shown() -> None:
    state = CreativeState()
    _with_results(state)
    assert state.stock_credits == [{"name": "Pixabay", "url": "https://pixabay.com/"}]
    assert set(stock_provider.PROVIDER_CREDITS) == {"pixabay", "pexels"}


async def test_one_failed_import_does_not_lose_the_other_picks(monkeypatch) -> None:
    """Review 2026-10-19: with several picks, the ones that arrived are used and the
    failure is reported — never «todo o nada»."""
    from . import creative_state as creative_state_module

    async def fake_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
        return (_TENANT, _TENANT, _TENANT)

    def fake_image(tenant_id, brand_id, user_id, item, *, query):  # noqa: ANN001, ANN202
        if item["n"] == 2:
            raise RuntimeError("r2 down")
        return {"key": _KEY, "view": "/r2media/tok", "asset_id": "a"}

    monkeypatch.setattr(CreativeState, "_session_ids", fake_ids)
    monkeypatch.setattr(creative_state_module, "import_stock_image", fake_image)
    state = CreativeState()
    state._stock_items = {"pixabay:1": {"n": 1}, "pixabay:2": {"n": 2}}
    state.stock_picks = ["image|pixabay:1", "image|pixabay:2"]

    await CreativeState.confirm_stock_product.fn(state)

    assert state.product_confirmed is True and state.product_photo_keys == [_KEY]
    assert "1 de 2" in state.upload_error
    assert state.stock_importing is False
