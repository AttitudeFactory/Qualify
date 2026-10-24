"""m-24842972 (PRODUCTOS-1): «Crear publicación con este producto» opens /create with the
product already chosen.

Pins:
1. `catalog_vm` builds `/create?producto=<id>` and reads the id back only when it is a
   UUID (anything else is "", never an error).
2. `/create` picks the product the URL names and skips the product screen — but only
   when the business's own catalog (read under RLS) lists it: another tenant's id, a
   deleted product or a malformed value leave the picker as it was, with no error.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from reflex.istate.data import ReflexURL, RouterData

from . import creative_state as creative_state_module
from .catalog_vm import (
    CREATE_PRODUCT_PARAM,
    NEEDS_PHOTO_REASON,
    create_with_product_href,
    product_id_from_query,
)
from .creative_state import CreativeState

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")
_USER_ID = UUID("c0000000-0000-4000-8000-000000000001")
_PRODUCT = "d0000000-0000-4000-8000-000000000001"
_OTHER = "d0000000-0000-4000-8000-000000000002"


# ---------------------------------------------------------------------------
# 1. the link and the query


def test_the_link_names_the_product_in_the_query() -> None:
    assert CREATE_PRODUCT_PARAM == "producto"
    assert create_with_product_href(_PRODUCT) == f"/create?producto={_PRODUCT}"
    assert NEEDS_PHOTO_REASON == "Primero súbele una foto"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"producto": _PRODUCT}, _PRODUCT),
        ({"producto": _PRODUCT.upper()}, _PRODUCT),
        ({"producto": f"  {_PRODUCT} "}, _PRODUCT),
        ({"producto": [_PRODUCT]}, _PRODUCT),
        ({"producto": ""}, ""),
        ({"producto": "1 OR 1=1"}, ""),
        ({"producto": "../drafts"}, ""),
        ({}, ""),
        (None, ""),
    ],
)
def test_only_a_uuid_is_read_from_the_query(params: Any, expected: str) -> None:
    assert product_id_from_query(params) == expected


# ---------------------------------------------------------------------------
# 2. /create opens with the product chosen


async def _fake_session_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
    return (_TENANT_ID, _BRAND_ID, _USER_ID)


def _catalog(*ids: str) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "id": pid,
            "name": f"Producto {n}",
            "photo_key": f"uploads/{pid}/a.jpg",
            "photo_count": "1",
            "video_count": "0",
            "counts_label": "1 foto",
            "photo_keys": f"uploads/{pid}/a.jpg",
            "video_keys": "",
        }
        for n, pid in enumerate(ids, start=1)
    )


def _state(monkeypatch: pytest.MonkeyPatch, query: str, catalog_ids: tuple[str, ...]) -> Any:
    monkeypatch.setattr(CreativeState, "_session_ids", _fake_session_ids)

    def fake_catalog(tenant_id: UUID, brand_id: UUID) -> tuple[dict[str, str], ...]:
        # the catalog is always the SESSION's business: the URL never picks the tenant
        assert (tenant_id, brand_id) == (_TENANT_ID, _BRAND_ID)
        return _catalog(*catalog_ids)

    monkeypatch.setattr(creative_state_module, "catalog_products", fake_catalog)
    state = CreativeState()
    state.router = RouterData(url=ReflexURL(f"http://localhost:3000/create{query}"))
    return state


async def test_the_product_in_the_url_is_chosen_and_the_picker_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch, f"?producto={_PRODUCT}", (_OTHER, _PRODUCT))

    await CreativeState.load_catalog_products.fn(state)

    assert state.selected_product_id == _PRODUCT
    assert state.brief_product_ref == "Producto 2"
    assert state.selected_product_photo_key == f"uploads/{_PRODUCT}/a.jpg"
    assert state.product_tab == "catalog" and state.product_confirmed is True
    assert state.catalog_error == "" and state.create_error == ""


async def test_the_same_product_already_chosen_stays_chosen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`choose_product` toggles: the URL's product must never unpick itself."""
    state = _state(monkeypatch, f"?producto={_PRODUCT}", (_PRODUCT,))
    state.catalog_items = [dict(item) for item in _catalog(_PRODUCT)]
    state.choose_product(_PRODUCT)

    await CreativeState.load_catalog_products.fn(state)

    assert state.selected_product_id == _PRODUCT and state.product_confirmed is True


@pytest.mark.parametrize(
    "query",
    [
        f"?producto={_OTHER}",  # another tenant's (RLS hides it) or a deleted one
        "?producto=no-es-un-producto",
        "?producto=",
        "",
    ],
)
async def test_a_product_the_business_does_not_have_is_ignored_without_error(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    state = _state(monkeypatch, query, (_PRODUCT,))

    await CreativeState.load_catalog_products.fn(state)

    assert state.selected_product_id == "" and state.product_confirmed is False
    assert state.catalog_error == "" and state.create_error == ""
    assert len(state.catalog_items) == 1
