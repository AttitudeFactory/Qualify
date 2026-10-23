"""m-24842973 (PRODUCTOS-2, N4): «Agregar producto» from Crear or Variaciones goes to Tus
productos and comes back to the publication with the new product chosen.

Pins:
1. `?volver=` only takes the app's own routes: a scheme, a host, `//`, a backslash, a
   control character, a fragment or `/catalog` itself are refused ("", never an error).
2. The links: `/catalog?nuevo=1&volver=<ruta>` out, `<ruta>` + `producto=<id>` back,
   with the route's own query (`modo=variaciones`) kept.
3. `/catalog?nuevo=1&volver=/create` opens the form and «Listo» goes back to the
   publication; a visit from the menu forgets the way back (PRODUCTOS-1 as before).
4. Back on `/create` nothing the owner had written or chosen is lost: the topic, the
   route open, and — from Variaciones — Crear's own product; the new product is chosen.
5. Crear and Variaciones link «Agregar producto» there (no «Ir al catálogo» dead end).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from reflex.istate.data import ReflexURL, RouterData

from . import catalog_state as catalog_state_module
from . import creative_state as creative_state_module
from . import variations_state as variations_state_module
from .catalog_state import CatalogState
from .catalog_vm import (
    ADD_PRODUCT_LABEL,
    RETURN_HINT,
    RETURN_LABEL,
    RETURN_WITHOUT_LABEL,
    VARIATIONS_RETURN_PATH,
    ProductVM,
    create_mode_from_query,
    new_product_href,
    opens_new_product_form,
    return_path_from_query,
    return_with_product_href,
    safe_return_path,
)
from .creative_state import CreativeState
from .creative_vm import RouteOptionVM
from .variations_state import VariationsState

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")
_USER_ID = UUID("c0000000-0000-4000-8000-000000000001")
_OLD = "d0000000-0000-4000-8000-000000000001"
_NEW = "d0000000-0000-4000-8000-000000000002"


async def _fake_session_ids(self: Any) -> tuple[UUID, UUID, UUID]:
    return (_TENANT_ID, _BRAND_ID, _USER_ID)


def _router(path_and_query: str) -> RouterData:
    return RouterData(url=ReflexURL(f"http://localhost:3000{path_and_query}"))


# ---------------------------------------------------------------------------
# 1. only the app's own routes


@pytest.mark.parametrize(
    "raw",
    ["/create", "/create?modo=variaciones", "/drafts/abc", "  /create  "],
)
def test_an_app_route_is_a_way_back(raw: str) -> None:
    assert safe_return_path(raw) == raw.strip()


@pytest.mark.parametrize(
    "raw",
    [
        "",
        None,
        "create",
        "https://otro.sitio/create",
        "http:/create",
        "//otro.sitio",
        "/\\otro.sitio",
        "/create\\..",
        "javascript:alert(1)",
        "/create\n/otro",
        "/create#arriba",
        "/catalog",
        "/catalog/",
        "/catalog?nuevo=1",
        "/" + "a" * 400,
    ],
)
def test_anything_else_is_refused_without_error(raw: Any) -> None:
    assert safe_return_path(raw) == ""


def test_the_query_is_read_safely() -> None:
    assert return_path_from_query({"volver": "/create"}) == "/create"
    assert return_path_from_query({"volver": ["https://otro.sitio"]}) == ""
    assert return_path_from_query(None) == ""
    assert opens_new_product_form({"nuevo": "1"}) is True
    assert opens_new_product_form({"nuevo": "si"}) is False
    assert create_mode_from_query({"modo": "variaciones"}) == "variaciones"
    assert create_mode_from_query({"modo": "otro"}) == ""


# ---------------------------------------------------------------------------
# 2. the links


def test_the_way_out_and_the_way_back() -> None:
    assert new_product_href("/create") == "/catalog?nuevo=1&volver=%2Fcreate"
    assert (
        new_product_href(VARIATIONS_RETURN_PATH)
        == "/catalog?nuevo=1&volver=%2Fcreate%3Fmodo%3Dvariaciones"
    )
    assert new_product_href("https://otro.sitio") == "/catalog?nuevo=1"
    assert return_with_product_href("/create", _NEW) == f"/create?producto={_NEW}"
    assert (
        return_with_product_href(VARIATIONS_RETURN_PATH, _NEW)
        == f"/create?modo=variaciones&producto={_NEW}"
    )
    assert return_with_product_href(f"/create?producto={_OLD}", _NEW) == f"/create?producto={_NEW}"
    assert return_with_product_href("//otro.sitio", _NEW) == ""
    assert return_with_product_href("/create", "") == "/create"


def test_the_copy() -> None:
    assert ADD_PRODUCT_LABEL == "Agregar producto"
    assert RETURN_LABEL == "Volver a tu publicación"
    assert RETURN_HINT == (
        "Cuando guardes el producto, vuelves a tu publicación con él ya elegido."
    )
    assert RETURN_WITHOUT_LABEL == "Volver sin agregar"


# ---------------------------------------------------------------------------
# 3. Tus productos remembers where the owner came from


def _product(product_id: str) -> ProductVM:
    return ProductVM(
        product_id=product_id,
        name="Shawarma mixto",
        slug="shawarma-mixto",
        description="",
        price_label="",
        price_amount="",
        price_currency="",
        category="",
        primary_photo_key="k.jpg",
        photo_count=1,
        video_count=0,
        counts_label="1 foto",
        media=(),
    )


def _catalog_state(monkeypatch: pytest.MonkeyPatch, query: str) -> CatalogState:
    monkeypatch.setattr(CatalogState, "_session_ids", _fake_session_ids)
    monkeypatch.setattr(catalog_state_module, "_sweep_staging", lambda tenant_id: None)
    monkeypatch.setattr(
        catalog_state_module, "list_products", lambda tenant_id, brand_id: (_product(_NEW),)
    )
    state = CatalogState()
    state.router = _router(f"/catalog{query}")
    return state


async def test_from_crear_the_form_opens_and_listo_goes_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _catalog_state(monkeypatch, "?nuevo=1&volver=%2Fcreate")

    await CatalogState.load_catalog.fn(state)

    assert state.form_open is True and state.returning is True
    assert state.return_to == "/create"
    state.created_id = _NEW
    assert state.created_href == f"/create?producto={_NEW}"
    state.selected_id = _NEW
    assert state.selected_create_href == f"/create?producto={_NEW}"


async def test_from_variaciones_listo_goes_back_to_variaciones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _catalog_state(monkeypatch, "?nuevo=1&volver=%2Fcreate%3Fmodo%3Dvariaciones")

    await CatalogState.load_catalog.fn(state)

    state.created_id = _NEW
    assert state.created_href == f"/create?modo=variaciones&producto={_NEW}"


@pytest.mark.parametrize(
    "query",
    ["", "?volver=https%3A%2F%2Fotro.sitio", "?volver=%2F%2Fotro.sitio", "?nuevo=0"],
)
async def test_from_the_menu_or_a_foreign_route_there_is_no_way_back(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    state = _catalog_state(monkeypatch, query)
    state.return_to = "/create"  # left over from an earlier round trip

    await CatalogState.load_catalog.fn(state)

    assert state.return_to == "" and state.returning is False
    assert state.form_open is False
    state.created_id = _NEW
    assert state.created_href == f"/create?producto={_NEW}"  # PRODUCTOS-1, unchanged


# ---------------------------------------------------------------------------
# 4. back on /create nothing is lost


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


def _creative_state(monkeypatch: pytest.MonkeyPatch, query: str) -> CreativeState:
    monkeypatch.setattr(CreativeState, "_session_ids", _fake_session_ids)
    monkeypatch.setattr(
        creative_state_module, "catalog_products", lambda tenant_id, brand_id: _catalog(_OLD, _NEW)
    )
    state = CreativeState()
    state.router = _router(f"/create{query}")
    return state


async def test_back_from_crear_the_new_product_is_chosen_and_the_text_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _creative_state(monkeypatch, f"?producto={_NEW}")
    state.brief_topic = "Promo del viernes, 2x1 en shawarmas"

    await CreativeState.load_catalog_products.fn(state)

    assert state.selected_product_id == _NEW and state.product_confirmed is True
    assert state.brief_topic == "Promo del viernes, 2x1 en shawarmas"
    assert state.gen_mode == "create"


async def test_back_from_variaciones_crear_keeps_its_own_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _creative_state(monkeypatch, f"?modo=variaciones&producto={_NEW}")
    state.catalog_items = [dict(item) for item in _catalog(_OLD)]
    state.choose_product(_OLD)
    state.product_confirmed = True

    await CreativeState.load_catalog_products.fn(state)

    assert state.gen_mode == "variations"
    assert state.selected_product_id == _OLD and state.product_confirmed is True


def _route(key: str) -> RouteOptionVM:
    return RouteOptionVM(
        key=key,
        rank=1,
        title=key,
        description="",
        cost_label="",
        badge="",
        badge_tone="",
        enabled=True,
        disabled_reason="",
        warning="",
        requires_disclosure=False,
        needs_upload=False,
    )


async def test_back_on_create_the_route_the_owner_had_open_stays_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_voice_flag(tenant_id: UUID, brand_id: UUID) -> bool:
        return False

    monkeypatch.setattr(CreativeState, "_session_ids", _fake_session_ids)
    monkeypatch.setattr(CreativeState, "_kit_voice_missing", staticmethod(no_voice_flag))
    monkeypatch.setattr(creative_state_module, "brand_readiness", lambda t, b: None)
    monkeypatch.setattr(
        creative_state_module,
        "route_options_for",
        lambda t, b, c: (_route("from_upload"), _route("generate")),
    )
    monkeypatch.setattr(creative_state_module, "brand_media", lambda t, b: [])
    monkeypatch.setattr(creative_state_module, "brand_campaign_options", lambda t, b: [])
    state = CreativeState()

    await CreativeState.load_create.fn(state)
    first_visit = state.selected_route
    other = "generate" if first_visit != "generate" else "from_upload"
    state.selected_route = other  # the owner opened another route, then left

    await CreativeState.load_create.fn(state)

    assert state.selected_route == other


def _variations_state(monkeypatch: pytest.MonkeyPatch, query: str) -> tuple[Any, list[str]]:
    chosen: list[str] = []

    async def fake_choose(self: VariationsState, product_id: str) -> None:
        chosen.append(product_id)

    monkeypatch.setattr(VariationsState, "_session_ids", _fake_session_ids)
    monkeypatch.setattr(VariationsState, "_choose", fake_choose)
    monkeypatch.setattr(
        variations_state_module, "catalog_products", lambda t, b: _catalog(_OLD, _NEW)
    )
    monkeypatch.setattr(variations_state_module, "list_variation_sets", lambda t, b: ())
    state = VariationsState()
    state.router = _router(f"/create{query}")
    return state, chosen


async def test_variaciones_rereads_its_picker_and_chooses_the_new_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, chosen = _variations_state(monkeypatch, f"?modo=variaciones&producto={_NEW}")

    await VariationsState.load_from_query.fn(state)

    assert [row["id"] for row in state.products] == [_OLD, _NEW]
    assert chosen == [_NEW]


@pytest.mark.parametrize(
    "query",
    [
        "?modo=variaciones&producto=d0000000-0000-4000-8000-00000000ffff",  # not listed
        "?modo=variaciones&producto=no-es-un-producto",
        "?modo=variaciones",
        f"?producto={_NEW}",  # a Crear return: not Variaciones' business
        "",
    ],
)
async def test_variaciones_ignores_anything_else_without_error(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    state, chosen = _variations_state(monkeypatch, query)

    await VariationsState.load_from_query.fn(state)

    assert chosen == [] and state.error == ""


async def test_variaciones_does_not_choose_again_the_product_already_chosen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, chosen = _variations_state(monkeypatch, f"?modo=variaciones&producto={_NEW}")
    state.product_id = _NEW

    await VariationsState.load_from_query.fn(state)

    assert chosen == []


# ---------------------------------------------------------------------------
# 5. the screens link there


def test_crear_and_variaciones_link_agregar_producto_with_the_way_back() -> None:
    from . import catalog_page, content_generator, variations_view

    generator = Path(content_generator.__file__).read_text(encoding="utf-8")
    assert "Ir al catálogo" not in generator
    assert generator.count("new_product_href(CREATE_RETURN_PATH)") == 2
    variations = Path(variations_view.__file__).read_text(encoding="utf-8")
    assert "Ir a Tus productos" not in variations
    assert variations.count("new_product_href(VARIATIONS_RETURN_PATH)") == 2
    catalog = Path(catalog_page.__file__).read_text(encoding="utf-8")
    assert "RETURN_LABEL" in catalog and "RETURN_HINT" in catalog
    assert "href=CatalogState.return_to" in catalog
