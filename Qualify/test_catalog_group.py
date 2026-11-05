"""«Agrupa tus productos» (m-24955838): the notice, the two steps, the import review.

No DB: the provider functions the state calls are stand-ins, `_session_ids` is patched on
the CLASS; background handlers run through `.fn(state)`.

Pins:
1. The notice: 2 or more without a category; hidden after «Dejar el resto en «Otros»»
   until a NEW one appears.
2. Step 1: proposals accepted by default, renamed (24 letters, Spanish refusal), skipped;
   «Siguiente» stores the accepted ones only.
3. Step 2: several at once into an existing or a new category; a failed write (also the
   session lookup) puts them back; «Deshacer».
4. The import review: the proposed category per product, editable, «Nueva».
5. «Tu menú» in the chat says the customer picks a category first when the menu is long.
6. The copy is on the screens.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from qualify_api.catalog.service import CatalogError
from sqlalchemy.exc import OperationalError

from . import catalog_group_state as group_module
from . import catalog_page, whatsapp_tab_menu
from .catalog_group_state import CatalogGroupState
from .catalog_group_vm import (
    ALL_GROUPED,
    GROUP_BUTTON,
    LEAVE_REST,
    NAME_EMPTY,
    NAME_HELP,
    NAME_TOO_LONG,
    NEW_CATEGORY,
    NEW_CHOICE,
    ONLY_OTROS_BUTTON,
    ONLY_OTROS_TEXT,
    PUT_HERE,
    PUT_IN,
    SAVE_FAILED,
    STEP1_TITLE,
    STEP2_TITLE,
    STEP_DONE,
    STEP_LEFTOVERS,
    UNDO_LABEL,
    import_categories_line,
    notice_count,
    notice_text,
)
from .catalog_order_vm import OrderGroup
from .catalog_state import CatalogState
from .catalog_vm import ProductVM
from .whatsapp_chats_vm import build_menu_preview
from .whatsapp_menu_vm import import_view, product_rows

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")
_USER_ID = UUID("c0000000-0000-4000-8000-000000000001")


def _product(name: str, category: str = "", price: str = "5 $") -> ProductVM:
    return ProductVM(
        product_id=f"id-{name}",
        name=name,
        slug=name.lower(),
        description="",
        price_label=price,
        price_amount="",
        price_currency="",
        category=category,
        primary_photo_key="",
        photo_count=0,
        video_count=0,
        counts_label="",
        media=(),
    )


_BIANKI = [
    _product("Combo Vecino"),
    _product("Combo Mixto"),
    _product("Shawarma de carne"),
    _product("Shawarma mixto"),
    _product("Coca-Cola"),
    _product("7UP"),
    _product("Catering oficina", price="45 $"),
    _product("Limonada", "Bebidas"),
]


class _Fake:
    def __init__(self) -> None:
        self.writes: list[tuple[list[str], str]] = []
        self.fail: BaseException | None = None
        self.fail_after = 0

    def list_products(self, tenant_id: UUID, brand_id: UUID) -> tuple[ProductVM, ...]:
        return tuple(_BIANKI)

    def suggest(self, tenant_id: UUID, brand_id: UUID) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return (
            ("Combos", ("id-Combo Vecino", "id-Combo Mixto")),
            ("Shawarmas", ("id-Shawarma de carne", "id-Shawarma mixto")),
        )

    def order(self, tenant_id: UUID, brand_id: UUID) -> tuple[OrderGroup, ...]:
        return (OrderGroup("Bebidas", "Bebidas", ()), OrderGroup("", "Otros", ()))

    def set_category(
        self, tenant_id: UUID, brand_id: UUID, user_id: UUID | None, ids: list[str], cat: str
    ) -> tuple[str, int, bool]:
        assert (tenant_id, brand_id, user_id) == (_TENANT_ID, _BRAND_ID, _USER_ID)
        if self.fail is not None and len(self.writes) >= self.fail_after:
            raise self.fail
        self.writes.append((list(ids), cat))
        return cat, len(ids), True


async def _ids(self: CatalogGroupState) -> tuple[UUID, UUID, UUID]:
    return (_TENANT_ID, _BRAND_ID, _USER_ID)


@pytest.fixture
def fake(monkeypatch) -> _Fake:
    f = _Fake()
    monkeypatch.setattr(CatalogGroupState, "_session_ids", _ids)
    monkeypatch.setattr(group_module, "list_products", f.list_products)
    monkeypatch.setattr(group_module, "suggest_groups", f.suggest)
    monkeypatch.setattr(group_module, "list_order", f.order)
    monkeypatch.setattr(group_module, "set_category", f.set_category)
    return f


async def _drain(events: Any) -> list[Any]:
    return [e async for e in events]


async def _opened() -> CatalogGroupState:
    state = CatalogGroupState()
    state.open_flow()
    await CatalogGroupState.load_flow.fn(state)
    return state


# ---------------------------------------------------------------------------
# 1. the notice


def test_the_notice_needs_two_and_stays_hidden_after_leaving_them_in_otros() -> None:
    assert notice_count(["a"], []) == 0
    assert notice_count(["a", "b"], []) == 2
    assert notice_count(["a", "b"], ["a", "b"]) == 0  # «Dejar el resto en «Otros»»
    assert notice_count(["a", "b", "c"], ["a", "b"]) == 3  # a NEW one appeared
    assert notice_text(22) == (
        "Tienes 22 productos sin categoría. En WhatsApp salen todos en una sola lista larga."
    )
    state = CatalogState()
    state.products = list(_BIANKI)
    assert state.group_notice_count == 7  # «Otros» and blank alike; Limonada has one
    state.dismissed_uncategorized = [p.product_id for p in _BIANKI]
    assert state.group_notice_count == 0


# ---------------------------------------------------------------------------
# 2. step 1


async def test_proposals_start_accepted_and_only_the_accepted_are_stored(fake) -> None:
    state = await _opened()
    assert [c.name for c in state.cards] == ["Combos", "Shawarmas"]
    assert all(c.accepted for c in state.cards)
    assert state.step_total == 2 and state.left_text == "Quedan 3 para el paso 2"
    state.toggle_group(1)  # «No agrupar» «Shawarmas»
    assert not state.cards[1].accepted
    assert state.left_text == "Quedan 5 para el paso 2"
    events = await _drain(CatalogGroupState.store_groups.fn(state))
    assert fake.writes == [(["id-Combo Vecino", "id-Combo Mixto"], "Combos")]
    assert state.step == STEP_LEFTOVERS
    assert [r.name for r in state.leftovers] == [
        "Shawarma de carne",
        "Shawarma mixto",
        "Coca-Cola",
        "7UP",
        "Catering oficina",
    ]
    assert "Combos" in state.categories and events


async def test_renaming_checks_24_letters_and_joins_an_existing_spelling(fake) -> None:
    state = await _opened()
    state.start_rename(0)
    state.set_rename_text("  ")
    state.save_rename()
    assert state.rename_error == NAME_EMPTY
    state.set_rename_text("Combos para compartir en familia")
    state.save_rename()
    assert state.rename_error == NAME_TOO_LONG
    assert "24 letras" in NAME_TOO_LONG
    state.set_rename_text("bebidas")  # an existing category: its own spelling
    state.save_rename()
    assert state.renaming == -1 and state.cards[0].name == "Bebidas"
    assert state.rename_count == "7 de 24"


async def test_the_services_spanish_refusal_is_shown_as_is(fake) -> None:
    state = await _opened()
    fake.fail = CatalogError("El nombre de la categoría puede tener hasta 24 letras.")
    await _drain(CatalogGroupState.store_groups.fn(state))
    assert state.error.startswith("El nombre de la categoría")
    assert state.busy is False and len(state.cards) == 2  # nothing stored, nothing gone


async def test_a_failure_midway_keeps_what_was_stored_and_the_rest(fake) -> None:
    state = await _opened()
    fake.fail, fake.fail_after = OperationalError("x", {}, Exception("down")), 1
    await _drain(CatalogGroupState.store_groups.fn(state))
    assert [c.name for c in state.cards] == ["Shawarmas"]
    assert state.error == SAVE_FAILED and state.busy is False


async def test_without_proposals_it_goes_straight_to_step_2_with_no_counter(
    fake, monkeypatch
) -> None:
    monkeypatch.setattr(group_module, "suggest_groups", lambda t, b: ())
    state = await _opened()
    assert state.step == STEP_LEFTOVERS and state.step_total == 1 and not state.with_groups
    assert len(state.leftovers) == 7


async def test_an_old_link_with_nothing_left_says_so(fake, monkeypatch) -> None:
    monkeypatch.setattr(
        group_module, "list_products", lambda t, b: (_product("Limonada", "Bebidas"),)
    )
    state = await _opened()
    assert state.all_grouped and state.step == STEP_DONE


# ---------------------------------------------------------------------------
# 3. step 2


async def _at_step_2(fake: _Fake) -> CatalogGroupState:
    state = await _opened()
    await _drain(CatalogGroupState.store_groups.fn(state))
    fake.writes.clear()
    return state


async def test_several_at_once_into_an_existing_category_with_undo(fake) -> None:
    state = await _at_step_2(fake)
    state.toggle_leftover("id-Coca-Cola")
    state.toggle_leftover("id-7UP")
    assert state.chosen_text == "2 elegidos"
    state.open_sheet()
    state.set_sheet_choice("Bebidas")
    assert state.put_here() is not None
    assert [r.name for r in state.leftovers] == ["Catering oficina"]  # optimistic
    events = await _drain(CatalogGroupState.store_put.fn(state))
    assert fake.writes == [(["id-Coca-Cola", "id-7UP"], "Bebidas")]
    toast = json.dumps(str(events[0]), ensure_ascii=False)
    assert "Listo: 2 productos ahora están en «Bebidas»." in toast and UNDO_LABEL in toast
    await _drain(CatalogGroupState.undo_put.fn(state))
    assert fake.writes[-1] == (["id-Coca-Cola", "id-7UP"], "")
    assert len(state.leftovers) == 3


async def test_a_new_category_is_checked_then_created(fake) -> None:
    state = await _at_step_2(fake)
    state.toggle_leftover("id-Catering oficina")
    state.open_sheet()
    state.set_sheet_choice(NEW_CHOICE)
    state.set_sheet_new("")
    assert state.put_here() is None and state.sheet_error == NAME_EMPTY
    state.set_sheet_new("Pedidos para empresas y eventos")
    assert state.put_here() is None and state.sheet_error == NAME_TOO_LONG
    state.set_sheet_new("Catering")
    assert state.put_here() is not None
    await _drain(CatalogGroupState.store_put.fn(state))
    assert fake.writes == [(["id-Catering oficina"], "Catering")]
    assert "Catering" in state.categories


async def test_a_failed_put_brings_them_back(fake) -> None:
    state = await _at_step_2(fake)
    fake.fail = OperationalError("x", {}, Exception("down"))
    state.toggle_leftover("id-7UP")
    state.open_sheet()
    state.set_sheet_choice("Bebidas")
    state.put_here()
    await _drain(CatalogGroupState.store_put.fn(state))
    assert len(state.leftovers) == 3 and state.checked == ["id-7UP"]
    assert state.error == SAVE_FAILED and state.busy is False


async def test_a_failing_session_lookup_brings_them_back_too(fake, monkeypatch) -> None:
    state = await _at_step_2(fake)

    async def boom(self: CatalogGroupState) -> None:
        raise OperationalError("x", {}, Exception("down"))

    monkeypatch.setattr(CatalogGroupState, "_session_ids", boom)
    state.toggle_leftover("id-7UP")
    state.open_sheet()
    state.set_sheet_choice("Bebidas")
    state.put_here()
    await _drain(CatalogGroupState.store_put.fn(state))
    assert len(state.leftovers) == 3 and state.error == SAVE_FAILED and not state.busy
    assert fake.writes == []


async def test_leaving_the_rest_in_otros_hides_the_notice(fake, monkeypatch) -> None:
    state = await _at_step_2(fake)
    catalog = CatalogState()
    catalog.products = list(_BIANKI)

    async def get_state(self: Any, cls: type) -> Any:
        return catalog

    monkeypatch.setattr(CatalogGroupState, "get_state", get_state)
    await state.leave_rest()
    assert state.step == STEP_DONE
    assert set(catalog.dismissed_uncategorized) == {
        "id-Coca-Cola",
        "id-7UP",
        "id-Catering oficina",
    }
    grouped = {"Combo Vecino", "Combo Mixto", "Shawarma de carne", "Shawarma mixto"}
    catalog.products = [p for p in _BIANKI if p.name not in grouped]
    assert catalog.group_notice_count == 0
    catalog.products = [*catalog.products, _product("Papas")]  # a new one
    assert catalog.group_notice_count == 4
    assert state.done_text == "Listo: tu menú tiene 3 categorías."  # Bebidas, Combos, Shawarmas


# ---------------------------------------------------------------------------
# 4. the import review


def _found(name: str, category: str) -> Any:
    return SimpleNamespace(
        name=name,
        price_amount=None,
        price_currency="",
        description="",
        evidence="",
        category=category,
    )


def test_the_review_shows_each_category_and_what_it_creates() -> None:
    from .whatsapp_menu_vm import empty_form

    rows = product_rows([_found("Combo Vecino", "Combos"), _found("Agua", "bebidas")])
    rows = [{**r, "checked": "1"} for r in rows]
    catalog = [{"name": "Té", "category": "Bebidas", "price_amount": None}]
    vm = import_view(
        empty_form(),
        kind="url",
        label="bianki.com",
        warnings=(),
        facts=(),
        products=rows,
        catalog=catalog,
        category_editing=1,
    )
    combo, agua = vm.new_products
    assert (combo.category_label, combo.category_new) == ("Combos", True)
    assert (agua.category_new, agua.editing_category) == (False, True)  # same key
    assert vm.categories_line == "Vamos a crear 1 categoría: Combos. Cámbiala si quieres."
    assert import_categories_line(["Combos", "Shawarmas", "Ensaladas", "Bebidas"]) == (
        "Vamos a crear 4 categorías: Combos, Shawarmas, Ensaladas y Bebidas. Cámbialas si quieres."
    )
    none = product_rows([_found("Algo", "")])
    vm = import_view(
        empty_form(), kind="url", label="x", warnings=(), facts=(), products=none, catalog=()
    )
    assert vm.new_products[0].category_label == "Sin categoría"


def test_editing_a_found_category_in_the_state_keeps_it_with_the_product() -> None:
    from .whatsapp_menu_state import IMPORT_REVIEW, WhatsAppMenuState

    state = WhatsAppMenuState()
    state.import_phase = IMPORT_REVIEW
    state._import_products = product_rows([_found("Combo Vecino", "Combos")])
    state._catalog = [{"name": "Té", "category": "Bebidas"}]
    state.edit_import_category(0)
    assert state.import_category_text == "Combos"
    state.set_import_category_text("Pedidos para empresas y eventos")
    state.save_import_category()
    assert state.import_category_error == NAME_TOO_LONG
    state.set_import_category_text("bebidas")
    state.save_import_category()
    assert state._import_products[0]["category"] == "Bebidas"
    assert state.import_category_editing == -1


# ---------------------------------------------------------------------------
# 5. «Tu menú» in the chat


def _preview(count: int, rows_shown: int, overflows: bool) -> Any:
    return SimpleNamespace(
        body="¿Qué se te antoja?",
        button_label="Ver menú",
        header=None,
        footer=None,
        product_count=count,
        rows_shown=rows_shown,
        overflows=overflows,
    )


def test_tu_menu_says_the_customer_picks_a_category_first_when_it_is_long() -> None:
    note = build_menu_preview(_preview(22, 0, False)).overflow_note
    assert note == (
        "Tu menú tiene 22 productos: tu cliente primero elige una categoría y luego ve sus "
        "productos."
    )
    assert "los primeros 9" in build_menu_preview(_preview(12, 9, True)).overflow_note
    assert build_menu_preview(_preview(5, 5, False)).overflow_note == ""


# ---------------------------------------------------------------------------
# 6. the copy is on the screens


def test_the_screens_carry_the_spec_copy() -> None:
    rendered = str(catalog_page.catalog_index())
    for words in (
        GROUP_BUTTON,
        STEP1_TITLE,
        STEP2_TITLE,
        PUT_IN,
        PUT_HERE,
        NEW_CATEGORY,
        LEAVE_REST,
        NAME_HELP,
        ONLY_OTROS_TEXT,
        ONLY_OTROS_BUTTON,
        ALL_GROUPED,
        "Hasta aquí se ve sin tocar «Ver más categorías»",
    ):
        assert json.dumps(words)[1:-1] in rendered, words
    menu = str(whatsapp_tab_menu.menu_tab())
    for words in (GROUP_BUTTON, "save_and_open_group", "edit_import_category", "Nueva"):
        assert json.dumps(words)[1:-1] in menu, words
