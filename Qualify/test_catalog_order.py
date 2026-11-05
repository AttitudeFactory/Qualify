"""«Ordenar tu menú» (m-24955643): the view model, the state and the two screens.

No DB: the provider functions the state calls are replaced with stand-ins, and
`_session_ids` is monkeypatched on the CLASS (as in `test_catalog_state.py`); background
handlers run through `.fn(state)`.

Pins:
1. The view: positions, the «⋯» targets, «Otros» movable like any category, the «Ver más»
   cut right after the 9th product only when WhatsApp paginates (more than 10).
2. Moving a category or a product is optimistic, stored through the service's whole-list
   calls, and offers «Deshacer» for 6 s; a product never leaves its category by drag.
3. «Deshacer» stores the previous order through the same calls.
4. A refused write puts the screen back, says «No pudimos guardar el orden…», and a
   typed refusal re-reads the order.
5. WhatsApp step 3 shows the first screen by category, read-only, with «Cambiar el orden».
6. The copy of the spec is on the screens.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from qualify_api.catalog.service import OrderRefused, UnknownCategory
from sqlalchemy.exc import OperationalError

from . import catalog_order_state as order_state_module
from . import catalog_page, whatsapp_tab_menu
from .catalog_order_state import CatalogOrderState
from .catalog_order_vm import (
    FIRST_PAGE_CUT,
    MOVE_DOWN,
    MOVE_FIRST,
    MOVE_LAST,
    MOVE_TO,
    MOVE_UP,
    ORDER_BUTTON,
    ORDER_DONE,
    ORDER_EMPTY,
    ORDER_FAILED,
    ORDER_HELP,
    ORDER_ONLY_ONE,
    ORDER_TITLE,
    TAB_CATEGORIES,
    TAB_PRODUCTS,
    TAB_PRODUCTS_VALUE,
    UNDO_LABEL,
    UNDONE,
    OrderGroup,
    OrderItem,
    build_order_view,
    category_names,
    move_category,
    move_product,
    opens_order,
    order_href,
)
from .catalog_vm import return_path_from_query
from .whatsapp_menu_vm import (
    CHANGE_ORDER,
    ORDER_HINT,
    CatalogRowVM,
    catalog_more_line,
    catalog_order_line,
    catalog_sections,
)

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")
_USER_ID = UUID("c0000000-0000-4000-8000-000000000001")


def _item(name: str) -> OrderItem:
    return OrderItem(product_id=f"id-{name}", name=name, price_label="5 $")


def _group(name: str, *products: str, label: str | None = None) -> OrderGroup:
    return OrderGroup(name=name, label=label or name, products=tuple(_item(p) for p in products))


def _bianki() -> list[OrderGroup]:
    """Today's order for an existing business: A to Z, «Otros» last (invented names)."""
    return [
        _group("Bebidas", "Agua", "Limonada", "Té frío", "Malta", "Refresco"),
        _group("Combos", "Combo personal", "Combo pareja", "Combo familiar"),
        _group("Ensaladas", "Griega", "César", "Tabule", "Fatush"),
        _group("Shawarmas", "Pollo", "Mixto", "Carne", "Falafel", "XL", "Vegano"),
        _group("", "Salsa de ajo", label="Otros"),
    ]


async def _fake_session_ids(self: CatalogOrderState) -> tuple[UUID, UUID, UUID]:
    return (_TENANT_ID, _BRAND_ID, _USER_ID)


async def _drain(events: Any) -> list[Any]:
    return [event async for event in events]


class _FakeStore:
    """Stands in for `catalog_provider`'s order writes; `fail` raises on the next one."""

    def __init__(self) -> None:
        self.categories: list[list[str]] = []
        self.products: list[tuple[str, list[str]]] = []
        self.fail: BaseException | None = None
        self.loads = 0

    def save_categories(
        self, tenant_id: UUID, brand_id: UUID, user_id: UUID | None, names: list[str]
    ) -> None:
        assert (tenant_id, brand_id, user_id) == (_TENANT_ID, _BRAND_ID, _USER_ID)
        if self.fail is not None:
            raise self.fail
        self.categories.append(list(names))

    def save_products(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID | None,
        category: str,
        ids: list[str],
    ) -> None:
        if self.fail is not None:
            raise self.fail
        self.products.append((category, list(ids)))

    def list_order(self, tenant_id: UUID, brand_id: UUID) -> tuple[OrderGroup, ...]:
        self.loads += 1
        return tuple(_bianki())


@pytest.fixture
def store(monkeypatch) -> _FakeStore:
    fake = _FakeStore()
    monkeypatch.setattr(CatalogOrderState, "_session_ids", _fake_session_ids)
    monkeypatch.setattr(order_state_module, "save_category_order", fake.save_categories)
    monkeypatch.setattr(order_state_module, "save_product_order", fake.save_products)
    monkeypatch.setattr(order_state_module, "list_order", fake.list_order)
    return fake


def _state(groups: list[OrderGroup] | None = None) -> CatalogOrderState:
    state = CatalogOrderState()
    state._groups = list(_bianki() if groups is None else groups)
    state.ordering = True
    return state


def _labels(state: CatalogOrderState) -> list[str]:
    return [g.label for g in state._groups]


def _toast_text(event: Any) -> str:
    return json.dumps(str(event), ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1. the view


def test_the_view_numbers_every_row_and_names_its_place() -> None:
    view = build_order_view(_bianki())
    assert [c.label for c in view] == ["Bebidas", "Combos", "Ensaladas", "Shawarmas", "Otros"]
    shawarmas = view[3]
    assert (shawarmas.position, shawarmas.total, shawarmas.count_label) == (4, 5, "6 productos")
    assert shawarmas.place_label == "Shawarmas, posición 4 de 5"
    assert shawarmas.more_label == "Más opciones para «Shawarmas»"
    assert (shawarmas.up_to, shawarmas.down_to, shawarmas.last_to) == (2, 4, 4)
    assert shawarmas.positions == (1, 2, 3, 4, 5)
    mixto = shawarmas.products[1]
    assert mixto.place_label == "Mixto, posición 2 de 6 en «Shawarmas»"
    assert mixto.rank_group == "order-products:Shawarmas"
    assert view[4].count_label == "1 producto"


def test_otros_is_a_category_like_any_other_and_last_by_default() -> None:
    view = build_order_view(_bianki())
    otros = view[-1]
    assert (otros.name, otros.label, otros.movable) == ("", "Otros", True)
    first = move_category(_bianki(), "", 0)
    assert first is not None and category_names(first)[0] == ""
    # a lone product cannot be ordered: no handle, no «⋯»
    assert otros.products[0].movable is False


def test_the_ver_mas_cut_sits_after_the_ninth_product_only_when_whatsapp_paginates() -> None:
    view = build_order_view(_bianki())  # 19 products: 9 + «Ver más»
    flat = [p for c in view for p in c.products]
    assert [p.name for p in flat if p.after_cut] == [flat[8].name]
    # Bianki puts Shawarmas (6) and Combos (3) first: the first screen is exactly those
    groups = move_category(_bianki(), "Shawarmas", 0)
    assert groups is not None
    groups = move_category(groups, "Combos", 1)
    assert groups is not None
    flat = [p for c in build_order_view(groups) for p in c.products]
    assert [p.name for p in flat[:9]] == [
        "Pollo",
        "Mixto",
        "Carne",
        "Falafel",
        "XL",
        "Vegano",
        "Combo personal",
        "Combo pareja",
        "Combo familiar",
    ]
    assert flat[8].after_cut and not any(p.after_cut for p in flat[9:])
    # ten products fit in one WhatsApp list: no cut at all
    ten = [_group("A", *[f"p{i}" for i in range(10)])]
    assert not any(p.after_cut for c in build_order_view(ten) for p in c.products)


def test_a_product_moves_only_inside_its_category() -> None:
    result = move_product(_bianki(), "id-Mixto", 0)
    assert result is not None
    groups, index = result
    assert index == 3
    assert [p.name for p in groups[3].products][:2] == ["Mixto", "Pollo"]
    assert move_product(_bianki(), "id-Pollo", 0) is None  # already first
    assert move_product(_bianki(), "ajeno", 0) is None


def test_the_way_in_from_whatsapp_keeps_only_an_app_route() -> None:
    href = order_href("/whatsapp?tab=menu&flujo=menu&paso=3")
    assert href.startswith("/catalog?ordenar=1&volver=")
    params = dict(p.split("=", 1) for p in href.split("?", 1)[1].split("&"))
    from urllib.parse import unquote

    params = {k: unquote(v) for k, v in params.items()}
    assert opens_order(params)
    assert return_path_from_query(params) == "/whatsapp?tab=menu&flujo=menu&paso=3"
    assert order_href("https://otro.sitio") == "/catalog?ordenar=1"


# ---------------------------------------------------------------------------
# 2. moves, saved at once, with «Deshacer»


async def test_moving_a_category_saves_the_whole_order_and_offers_undo(store) -> None:
    state = _state()
    follow = state.place_category("Shawarmas", 0)
    assert follow is not None
    # optimistic: the screen already shows it
    assert _labels(state) == ["Shawarmas", "Bebidas", "Combos", "Ensaladas", "Otros"]
    events = await _drain(CatalogOrderState.flush_order.fn(state))
    assert store.categories == [["Shawarmas", "Bebidas", "Combos", "Ensaladas", ""]]
    assert len(events) == 1
    toast = _toast_text(events[0])
    assert "Listo: «Shawarmas» va primero en tu menú." in toast
    assert UNDO_LABEL in toast and "6000" in toast
    assert state.announce == "Listo: «Shawarmas» va primero en tu menú."
    assert state.order_busy is False and state._queue == []


async def test_moving_a_product_saves_its_category_only(store) -> None:
    state = _state()
    state.place_product("id-Vegano", 1)
    await _drain(CatalogOrderState.flush_order.fn(state))
    assert store.products == [
        (
            "Shawarmas",
            ["id-Pollo", "id-Vegano", "id-Mixto", "id-Carne", "id-Falafel", "id-XL"],
        )
    ]
    assert state.announce == "Listo: «Vegano» va en el lugar 2 en «Shawarmas»."


def test_a_drag_moves_inside_one_category_and_never_across(store) -> None:
    state = _state()
    state.pick("id-Mixto")
    assert state.drop_product("id-Agua") is None  # another category: an edit, not a drag
    assert state._queue == []
    state.pick("id-Mixto")
    assert state.drop_product("id-Pollo") is not None
    assert [p.name for p in state._groups[3].products][:2] == ["Mixto", "Pollo"]
    state.pick("cat:Shawarmas")
    assert state.drop_category("Bebidas") is not None
    assert _labels(state)[0] == "Shawarmas"
    assert state.drop_category("Bebidas") is None  # nothing was lifted
    state.pick("cat:")  # «Otros» drags like any category
    assert state.drop_category("Shawarmas") is not None
    assert _labels(state)[0] == "Otros"
    state.pick("id-Mixto")
    assert state.drop_category("Bebidas") is None  # a product is not a category


def test_the_menu_moves_clamp_at_the_ends(store) -> None:
    state = _state()
    assert state.place_category("Bebidas", 0) is None  # already first: nothing queued
    assert state.place_category("Bebidas", 99) is not None
    assert _labels(state)[-1] == "Bebidas"
    assert state.announce == "Listo: «Bebidas» va al final en tu menú."


# ---------------------------------------------------------------------------
# 3. «Deshacer»


async def test_undo_stores_the_previous_order_through_the_same_calls(store) -> None:
    state = _state()
    state.place_category("Shawarmas", 0)
    await _drain(CatalogOrderState.flush_order.fn(state))
    assert state.undo_order() is not None
    assert _labels(state) == ["Bebidas", "Combos", "Ensaladas", "Shawarmas", "Otros"]
    events = await _drain(CatalogOrderState.flush_order.fn(state))
    assert store.categories[-1] == ["Bebidas", "Combos", "Ensaladas", "Shawarmas", ""]
    assert UNDONE in _toast_text(events[0]) and UNDO_LABEL not in _toast_text(events[0])
    assert state.undo_order() is None  # one undo, not a history

    state.place_product("id-XL", 0)
    await _drain(CatalogOrderState.flush_order.fn(state))
    state.undo_order()
    await _drain(CatalogOrderState.flush_order.fn(state))
    assert store.products[-1] == (
        "Shawarmas",
        ["id-Pollo", "id-Mixto", "id-Carne", "id-Falafel", "id-XL", "id-Vegano"],
    )


# ---------------------------------------------------------------------------
# 4. a refused write


async def test_a_refused_write_puts_the_row_back_and_rereads(store) -> None:
    state = _state()
    store.fail = UnknownCategory("Combos")
    state.place_category("Combos", 0)
    events = await _drain(CatalogOrderState.flush_order.fn(state))
    assert _labels(state) == ["Bebidas", "Combos", "Ensaladas", "Shawarmas", "Otros"]
    assert state.order_error == ORDER_FAILED
    assert ORDER_FAILED == "No pudimos guardar el orden. Revisa tu conexión y vuelve a moverlo."
    assert events and "load_order" in str(events[0])
    assert state.undo_order() is None


async def test_a_database_failure_puts_the_row_back_without_rereading(store) -> None:
    state = _state()
    store.fail = OperationalError("x", {}, Exception("down"))
    state.place_product("id-Mixto", 0)
    state.place_category("Shawarmas", 0)  # a second move queued behind the failing one
    events = await _drain(CatalogOrderState.flush_order.fn(state))
    assert [p.name for p in state._groups[3].products][:2] == ["Pollo", "Mixto"]
    assert _labels(state)[0] == "Bebidas"
    assert state._queue == [] and state.order_error == ORDER_FAILED
    assert events == []


async def test_an_unexpected_failure_never_leaves_the_writer_busy(store) -> None:
    """C2: a `ValueError` (a malformed id reaching `UUID(...)`) is not a typed refusal,
    yet the screen goes back, the queue empties and the next move is stored."""
    state = _state()
    store.fail = ValueError("badly formed hexadecimal UUID string")
    state.place_product("id-Mixto", 0)
    state.place_category("Shawarmas", 0)
    events = await _drain(CatalogOrderState.flush_order.fn(state))
    assert events == []
    assert [p.name for p in state._groups[3].products][:2] == ["Pollo", "Mixto"]
    assert _labels(state)[0] == "Bebidas"
    assert state.order_busy is False and state._queue == []
    assert state.order_error == ORDER_FAILED
    store.fail = None
    state.place_category("Combos", 0)
    await _drain(CatalogOrderState.flush_order.fn(state))
    assert store.categories == [["Combos", "Bebidas", "Ensaladas", "Shawarmas", ""]]


async def test_a_refusal_is_a_typed_error_of_the_service(store) -> None:
    state = _state()
    store.fail = OrderRefused("not in category")
    state.place_product("id-Mixto", 0)
    await _drain(CatalogOrderState.flush_order.fn(state))
    assert state.order_error == ORDER_FAILED


# ---------------------------------------------------------------------------
# open / load / close


async def test_opening_reads_todays_order(store) -> None:
    state = CatalogOrderState()
    assert state.open_order() is not None
    assert state.ordering and state.tab == "categorias"
    await CatalogOrderState.load_order.fn(state)
    assert _labels(state) == ["Bebidas", "Combos", "Ensaladas", "Shawarmas", "Otros"]
    assert state.loading_order is False and store.loads == 1
    state.set_tab(TAB_PRODUCTS_VALUE)
    assert state.tab == TAB_PRODUCTS_VALUE
    state.set_tab("otra")
    assert state.tab == TAB_PRODUCTS_VALUE


def test_listo_goes_back_where_the_owner_came_from() -> None:
    state = _state()
    state.return_to = "/whatsapp?tab=menu"
    assert "/whatsapp?tab=menu" in str(state.finish_order())
    assert state.ordering is False
    state.ordering, state.return_to = True, ""
    assert "load_catalog" in str(state.finish_order())
    # «Agregar producto» from the empty order view stays on the catalog
    state.ordering, state.return_to = True, "/whatsapp?tab=menu"
    assert state.close_order() is None and state.ordering is False


def test_one_category_or_one_product_has_nothing_to_order() -> None:
    state = _state([_group("Helados", "Yogur")])
    assert state.single_category and state.single_product and state.has_order_products
    assert not _state([]).has_order_products


# ---------------------------------------------------------------------------
# 5. WhatsApp step 3, read-only


def _rows(n: int, category: str = "Shawarmas") -> list[CatalogRowVM]:
    return [CatalogRowVM(name=f"P{i}", price="5 $", category=category) for i in range(n)]


def test_step_3_shows_the_first_screen_by_category() -> None:
    rows = _rows(6) + _rows(3, "Combos") + _rows(4, "Bebidas")
    sections = catalog_sections(rows)
    assert [(s.label, len(s.rows)) for s in sections] == [("Shawarmas", 6), ("Combos", 3)]
    assert catalog_order_line(rows) == "Shawarmas · Combos · Bebidas"
    assert catalog_more_line(rows) == "Y 4 más al tocar «Ver más»."
    assert catalog_more_line(_rows(10)) == ""
    assert len(catalog_sections(_rows(10))[0].rows) == 10


# ---------------------------------------------------------------------------
# 6. the copy is on the screens


def test_the_catalog_screen_carries_the_spec_copy() -> None:
    rendered = str(catalog_page.catalog_index())
    for words in (
        ORDER_BUTTON,
        ORDER_DONE,
        ORDER_TITLE,
        ORDER_HELP,
        TAB_CATEGORIES,
        TAB_PRODUCTS,
        FIRST_PAGE_CUT,
        ORDER_EMPTY,
        ORDER_ONLY_ONE,
        MOVE_FIRST,
        MOVE_UP,
        MOVE_DOWN,
        MOVE_LAST,
        MOVE_TO,
        "GripVertical",
        "data-rank-handle",
    ):
        assert json.dumps(words)[1:-1] in rendered, words


def test_whatsapp_step_3_links_to_the_order() -> None:
    rendered = str(whatsapp_tab_menu.menu_tab())
    for words in (ORDER_HINT, CHANGE_ORDER):
        assert json.dumps(words)[1:-1] in rendered, words
    assert "save_and_open_order" in rendered


# ---------------------------------------------------------------------------
# review follow-ups (U1, U3, archived categories)


def test_the_cut_also_shows_in_categorias_after_the_last_whole_category() -> None:
    view = build_order_view(_bianki())  # Bebidas 5 + Combos 3 = 8; Ensaladas would be 12
    assert [c.label for c in view if c.after_cut] == ["Combos"]
    groups = move_category(_bianki(), "Shawarmas", 0)
    assert groups is not None
    groups = move_category(groups, "Combos", 1)
    assert groups is not None
    assert [c.label for c in build_order_view(groups) if c.after_cut] == ["Combos"]  # 6 + 3
    # the first category alone overflows the first screen: no category line to draw
    big = [_group("A", *[f"p{i}" for i in range(12)]), _group("B", "x")]
    assert not any(c.after_cut for c in build_order_view(big))
    # everything fits in one list: no cut
    assert not any(c.after_cut for c in build_order_view([_group("A", "a"), _group("B", "b")]))


def test_a_menu_move_gives_the_focus_back_to_the_rows_more_button(store) -> None:
    state = _state()
    events = state.place_category("Shawarmas", 0)
    assert events is not None and len(events) == 2
    assert "data-order-more" in str(events[1]) and "cat:Shawarmas" in str(events[1])
    events = state.place_product("id-Mixto", 0)
    assert events is not None and "id-Mixto" in str(events[1])
    # a drop does not move the focus (the finger is already there)
    state.pick("cat:Bebidas")
    assert "call_script" not in str(state.drop_category("Combos"))


def _load_world_module() -> Any:
    """The backend's offline fake of the catalog tables (`World`), reused as is."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "packages/api/tests/test_catalog_order.py"
    spec = importlib.util.spec_from_file_location("_catalog_order_world", path)
    assert spec is not None and spec.loader is not None
    import sys

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


async def test_a_category_with_only_archived_products_keeps_its_place(monkeypatch) -> None:
    """The screen lists active products only, so it never submits «Postres» while its one
    product is archived: a move through the real provider and service keeps its place."""
    from qualify_api.catalog import service as service_module

    from . import catalog_provider

    mod = _load_world_module()
    world = mod.World()
    for i, (name, category) in enumerate(
        [("Agua", "Bebidas"), ("Combo", "Combos"), ("Pollo", "Shawarmas")]
    ):
        world.product(name, category, i)
    world.product("Torta", "Postres", 9, active=False)
    monkeypatch.setattr(service_module, "tenant_session", lambda _t: mod.FakeSession(world))
    monkeypatch.setattr(catalog_provider, "_service", lambda: world.service)
    world.service.set_category_order(
        tenant_id=mod.TENANT, brand_id=mod.BRAND, names=["Postres", "Bebidas"], user_id=None
    )

    async def ids(self: CatalogOrderState) -> tuple[UUID, UUID, None]:
        return (mod.TENANT, mod.BRAND, None)

    monkeypatch.setattr(CatalogOrderState, "_session_ids", ids)
    state = CatalogOrderState()
    await CatalogOrderState.load_order.fn(state)
    assert _labels(state) == ["Bebidas", "Combos", "Shawarmas"]  # «Postres» is not shown
    state.place_category("Shawarmas", 0)
    await _drain(CatalogOrderState.flush_order.fn(state))
    assert state.order_error == ""
    stored = world.service.category_order(tenant_id=mod.TENANT, brand_id=mod.BRAND)
    assert stored == ("Shawarmas", "Bebidas", "Combos", "Postres")


# ---------------------------------------------------------------------------
# the handle's keyboard (`ui.sort_handle`, founder 2026-11-06)


def test_sort_handle_is_a_button_that_takes_the_keyboard() -> None:
    from .ui import SortHandle, sort_handle

    assert "on_key_down" in SortHandle.create().get_event_triggers()
    handle = sort_handle(
        "Mover «Shawarmas», posición 4 de 5",
        lambda key: CatalogOrderState.category_handle_key("Shawarmas", key),
        key="cat:Shawarmas",
        lifted=True,
    )
    rendered = str(handle)
    assert '"button"' in rendered and "q-sort-handle" in rendered
    assert "data-rank-handle" in rendered and "data-sort-key" in rendered
    assert "aria-pressed" in rendered and "aria-hidden" not in rendered
    assert json.dumps("Mover «Shawarmas», posición 4 de 5")[1:-1] in rendered
    assert "category_handle_key" in rendered


async def test_space_lifts_arrows_move_on_screen_and_space_drops_with_one_write(
    store,
) -> None:
    state = _state()
    assert state.category_handle_key("Shawarmas", "ArrowUp") is None  # not lifted yet
    assert _labels(state)[3] == "Shawarmas"
    assert state.category_handle_key("Shawarmas", " ") is None
    assert state.lifted == "cat:Shawarmas"
    assert state.announce.startswith("Levantaste «Shawarmas», posición 4 de 5.")
    for _ in range(3):
        events = state.category_handle_key("Shawarmas", "ArrowUp")
        assert events is not None and "data-sort-key" in str(events[0])
    assert _labels(state)[0] == "Shawarmas"
    assert state.announce == "Shawarmas, posición 1 de 5"
    assert state._queue == []  # moving is on screen only
    assert state.category_handle_key("Shawarmas", "ArrowUp") is None  # already first
    events = state.category_handle_key("Shawarmas", " ")
    assert events is not None and state.lifted == ""
    await _drain(CatalogOrderState.flush_order.fn(state))
    assert store.categories == [["Shawarmas", "Bebidas", "Combos", "Ensaladas", ""]]
    # «Deshacer» brings back the order from before the lift
    state.undo_order()
    assert _labels(state)[3] == "Shawarmas"


def test_escape_puts_the_row_back_and_stores_nothing(store) -> None:
    state = _state()
    state.product_handle_key("id-Vegano", " ")
    state.product_handle_key("id-Vegano", "ArrowUp")
    state.product_handle_key("id-Vegano", "ArrowUp")
    assert state.announce == "Vegano, posición 4 de 6 en «Shawarmas»"
    assert state.product_handle_key("id-Vegano", "Escape") is not None
    assert [p.name for p in state._groups[3].products][-1] == "Vegano"
    assert state.lifted == "" and state._queue == []
    assert state.announce == "Listo, no cambiamos nada: «Vegano» volvió a su lugar."
    # lifted and dropped where it was: nothing to store either
    state.product_handle_key("id-Pollo", " ")
    assert state.product_handle_key("id-Pollo", " ") is None
    assert state._queue == [] and state.announce == "«Pollo» se quedó en su lugar."


async def test_a_failing_session_lookup_never_leaves_the_writer_busy(store, monkeypatch) -> None:
    """The brand or user lookup raising (the DB is down) rolls back like a failed write."""

    async def boom(self: CatalogOrderState) -> None:
        raise OperationalError("x", {}, Exception("down"))

    monkeypatch.setattr(CatalogOrderState, "_session_ids", boom)
    state = _state()
    state.place_category("Shawarmas", 0)
    state.place_product("id-Mixto", 0)
    assert await _drain(CatalogOrderState.flush_order.fn(state)) == []
    assert _labels(state)[3] == "Shawarmas"
    assert [p.name for p in state._groups[3].products][:2] == ["Pollo", "Mixto"]
    assert state.order_busy is False and state._queue == []
    assert state.order_error == ORDER_FAILED and store.categories == []
