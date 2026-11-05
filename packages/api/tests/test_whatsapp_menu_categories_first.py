"""Categories first in «Ver menú y pedir» (founder decision 2026-11-06, m-24955838).

A catalog that does not fit one direct list (more than `page_size` products) and has
two or more categories opens on a list of its categories; choosing one shows only that
category. A catalog that fits, or has a single category, keeps the direct list. Pure and
offline: `BIANKI_DEMO_MENU` (`page_size` 10) over fake catalogs.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from qualify_api.whatsapp.menus.engine import (
    CATEGORIES_BACK_ROW_ID,
    CTX_CATEGORIES_PAGE,
    CTX_ORDER,
    CTX_PRODUCTS_CATEGORY,
    CTX_PRODUCTS_PAGE,
    HELP_LINE,
    CatalogItem,
    Inbound,
    OutboundAction,
    SendButtons,
    SendList,
    StepResult,
    ThreadMenuState,
    is_categories_mode,
    products_list,
    step,
)
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU as MENU
from qualify_api.whatsapp.menus.schema import ProductsNode

NODE = MENU.nodes["productos"]
assert isinstance(NODE, ProductsNode)


def _catalog(sizes: Sequence[tuple[str | None, int]]) -> list[CatalogItem]:
    items: list[CatalogItem] = []
    n = 0
    for category, size in sizes:
        for _ in range(size):
            n += 1
            items.append(
                CatalogItem(
                    product_id=f"p{n}",
                    name=f"Producto {n}",
                    price_amount=Decimal(1000 * n),
                    price_currency="COP",
                    category=category,
                )
            )
    return items


# The pilot's shape: 22 products in 5 categories, one of them with 12.
PILOT = _catalog(
    [("Shawarmas", 12), ("Ensaladas", 4), ("Combos", 3), ("Bebidas", 2), ("Postres", 1)]
)


def _list(actions: Sequence[OutboundAction]) -> SendList:
    first = actions[0]
    assert isinstance(first, SendList), first
    return first


def _ids(send: SendList) -> list[str]:
    return [r.id for r in send.rows]


class Walk:
    def __init__(self, catalog: Sequence[CatalogItem], state: ThreadMenuState | None = None):
        self.catalog = catalog
        self.state = state or ThreadMenuState(node_id="inicio")

    def __call__(self, inbound: Inbound) -> StepResult:
        result = step(MENU, self.state, inbound, catalog=self.catalog)
        self.state = result.state
        return result


# --- the rule ----------------------------------------------------------------------


def test_the_pilot_catalog_opens_on_its_categories_in_order_with_counts() -> None:
    walk = Walk(PILOT)
    cats = _list(walk(Inbound.button_reply("ver_menu")).actions)
    assert cats.body == "¿Qué quieres ver?"
    assert [(r.id, r.title, r.description) for r in cats.rows] == [
        ("cat:shawarmas", "Shawarmas", "12 productos"),
        ("cat:ensaladas", "Ensaladas", "4 productos"),
        ("cat:combos", "Combos", "3 productos"),
        ("cat:bebidas", "Bebidas", "2 productos"),
        ("cat:postres", "Postres", "1 producto"),
    ]
    assert [s.title for s in cats.sections] == ["Categorías"]
    assert walk.state.node_id == "productos"
    assert walk.state.context == {CTX_CATEGORIES_PAGE: 0}


def test_choosing_a_category_shows_only_its_products_and_the_way_back() -> None:
    walk = Walk(PILOT)
    walk(Inbound.button_reply("ver_menu"))
    combos = _list(walk(Inbound.list_reply("cat:combos")).actions)
    assert combos.body == "Combos: elige el tuyo."
    assert [s.title for s in combos.sections] == ["Combos", "Más"]
    assert _ids(combos) == ["prod:p17", "prod:p18", "prod:p19", CATEGORIES_BACK_ROW_ID]
    assert combos.rows[0].description == "COP 17.000"
    assert combos.rows[-1].title == "Ver otras categorías"
    assert walk.state.context[CTX_PRODUCTS_CATEGORY] == "combos"


def test_a_category_of_twelve_pages_with_ver_mas() -> None:
    walk = Walk(PILOT)
    walk(Inbound.button_reply("ver_menu"))
    page1 = _list(walk(Inbound.list_reply("cat:shawarmas")).actions)
    assert _ids(page1) == [f"prod:p{i}" for i in range(1, 9)] + ["more:1", "cats:back"]
    assert len(page1.rows) == NODE.page_size
    assert page1.rows[-2].description == "Página 2 de 2"
    page2 = _list(walk(Inbound.list_reply("more:1")).actions)
    assert _ids(page2) == [f"prod:p{i}" for i in range(9, 13)] + ["cats:back"]
    assert walk.state.context[CTX_PRODUCTS_PAGE] == 1
    assert walk.state.context[CTX_PRODUCTS_CATEGORY] == "shawarmas"


def test_back_to_the_categories_keeps_the_order_in_progress() -> None:
    walk = Walk(PILOT)
    walk(Inbound.button_reply("ver_menu"))
    walk(Inbound.list_reply("cat:bebidas"))
    walk(Inbound.list_reply("prod:p20"))
    walk(Inbound.button_reply("agregar_mas"))
    walk(Inbound.list_reply("cat:shawarmas"))
    walk(Inbound.list_reply("more:1"))
    back = _list(walk(Inbound.list_reply("cats:back")).actions)
    assert _ids(back)[0] == "cat:shawarmas" and back.body == "¿Qué quieres ver?"
    assert [line["product_id"] for line in walk.state.context[CTX_ORDER]] == ["p20"]
    assert CTX_PRODUCTS_CATEGORY not in walk.state.context
    assert CTX_PRODUCTS_PAGE not in walk.state.context


def test_a_pick_adds_and_agregar_mas_returns_to_the_categories() -> None:
    walk = Walk(PILOT)
    walk(Inbound.button_reply("ver_menu"))
    walk(Inbound.text("Ensaladas"))  # typed label of a category row
    added = walk(Inbound.text("2"))  # typed position inside the category
    assert isinstance(added.actions[0], SendButtons)
    assert walk.state.node_id == "agregado"
    assert walk.state.order[0]["product_id"] == "p14"
    assert not set(walk.state.context) & {CTX_PRODUCTS_CATEGORY, CTX_PRODUCTS_PAGE}
    again = _list(walk(Inbound.button_reply("agregar_mas")).actions)
    assert _ids(again)[0] == "cat:shawarmas"


def test_keywords_and_ice_breakers_land_on_the_categories() -> None:
    for inbound in (Inbound.text("menú"), Inbound.text("Ver menú"), Inbound.command("menu")):
        walk = Walk(PILOT, ThreadMenuState(node_id="inicio"))
        assert _ids(_list(walk(inbound).actions))[0] == "cat:shawarmas"


def test_unknown_input_inside_a_category_re_renders_that_category() -> None:
    walk = Walk(PILOT)
    walk(Inbound.button_reply("ver_menu"))
    walk(Inbound.list_reply("cat:combos"))
    again = _list(walk(Inbound.text("¿tienen domicilio?")).actions)
    assert again.body.startswith(HELP_LINE)
    assert _ids(again)[0] == "prod:p17" and walk.state.attempts == 1


# --- regressions: the direct list stays exactly as before -------------------------------


def test_eight_products_in_three_categories_keep_the_direct_list() -> None:
    catalog = _catalog([("Shawarmas", 4), ("Bebidas", 3), ("Postres", 1)])
    assert not is_categories_mode(NODE, catalog)
    walk = Walk(catalog)
    send = _list(walk(Inbound.button_reply("ver_menu")).actions)
    assert send.body == NODE.body
    assert [s.title for s in send.sections] == ["Shawarmas", "Bebidas", "Postres"]
    assert _ids(send) == [f"prod:p{i}" for i in range(1, 9)]
    assert walk.state.context == {CTX_PRODUCTS_PAGE: 0}


def test_fifteen_products_in_one_category_keep_the_direct_paged_list() -> None:
    catalog = _catalog([("Shawarmas", 15)])
    assert not is_categories_mode(NODE, catalog)
    walk = Walk(catalog)
    page1 = _list(walk(Inbound.button_reply("ver_menu")).actions)
    assert _ids(page1) == [f"prod:p{i}" for i in range(1, 10)] + ["more:1"]
    page2 = _list(walk(Inbound.list_reply("more:1")).actions)
    assert _ids(page2) == [f"prod:p{i}" for i in range(10, 16)]
    assert walk.state.context == {CTX_PRODUCTS_PAGE: 1}


def test_the_threshold_is_more_than_page_size_products() -> None:
    nine = _catalog([("A", 5), ("B", 4)])
    assert not is_categories_mode(NODE, nine)


def test_ten_products_in_three_categories_fit_and_keep_the_direct_list() -> None:
    catalog = _catalog([("A", 4), ("B", 3), ("C", 3)])
    assert not is_categories_mode(NODE, catalog)
    send = products_list(NODE, catalog)
    assert _ids(send) == [f"prod:p{i}" for i in range(1, 11)]  # no «Ver más»
    assert [s.title for s in send.sections] == ["A", "B", "C"]


def test_eleven_products_in_three_categories_open_on_the_categories() -> None:
    catalog = _catalog([("A", 4), ("B", 4), ("C", 3)])
    assert is_categories_mode(NODE, catalog)
    assert _ids(products_list(NODE, catalog)) == ["cat:a", "cat:b", "cat:c"]


# --- many categories, stale ids, the uncategorized ---------------------------------------


def test_twelve_categories_page_as_nine_plus_ver_mas_categorias() -> None:
    catalog = _catalog([(f"Categoría {c:02d}", 1) for c in range(1, 13)])
    walk = Walk(catalog)
    page1 = _list(walk(Inbound.button_reply("ver_menu")).actions)
    assert len(page1.rows) == 10
    assert _ids(page1)[:9] == [f"cat:categoria {c:02d}" for c in range(1, 10)]
    assert (page1.rows[-1].id, page1.rows[-1].title) == ("catmore:1", "Ver más categorías")
    page2 = _list(walk(Inbound.list_reply("catmore:1")).actions)
    assert _ids(page2) == [f"cat:categoria {c:02d}" for c in range(10, 13)]
    assert walk.state.context == {CTX_CATEGORIES_PAGE: 1}
    # A category from the second page, then back: the second page again.
    walk(Inbound.list_reply("cat:categoria 11"))
    back = _list(walk(Inbound.list_reply("cats:back")).actions)
    assert _ids(back) == _ids(page2)


def test_a_stale_category_falls_back_to_the_categories_list() -> None:
    # A category removed meanwhile: the reply id from an old list…
    walk = Walk(PILOT, ThreadMenuState(node_id="productos", context={CTX_CATEGORIES_PAGE: 0}))
    result = walk(Inbound.list_reply("cat:sopas"))
    assert _ids(_list(result.actions))[0] == "cat:shawarmas" and not result.handed_off
    assert walk.state.attempts == 0
    # …and a thread whose stored category is gone: its view is the categories list, so
    # a typed «1» opens the first category.
    stale = ThreadMenuState(
        node_id="productos", context={CTX_PRODUCTS_CATEGORY: "sopas", CTX_PRODUCTS_PAGE: 3}
    )
    opened = _list(step(MENU, stale, Inbound.text("1"), catalog=PILOT).actions)
    assert _ids(opened)[0] == "prod:p1"


def test_a_tap_on_an_older_category_list_is_honoured() -> None:
    walk = Walk(PILOT)
    walk(Inbound.button_reply("ver_menu"))
    walk(Inbound.list_reply("cat:combos"))
    # The customer scrolls up and taps «Bebidas» on the first list.
    drinks = _list(walk(Inbound.list_reply("cat:bebidas")).actions)
    assert _ids(drinks) == ["prod:p20", "prod:p21", "cats:back"]


def test_the_row_id_survives_a_renamed_spelling() -> None:
    one = _catalog([("Café", 6), ("Bebidas", 6)])
    other = [
        CatalogItem(i.product_id, i.name, i.price_amount, i.price_currency, "  CAFE ")
        if i.category == "Café"
        else i
        for i in one
    ]
    assert _ids(products_list(NODE, one))[0] == _ids(products_list(NODE, other))[0] == "cat:cafe"
    # A thread inside «Café» stays there after the rename.
    state = ThreadMenuState(node_id="productos", context={CTX_PRODUCTS_CATEGORY: "cafe"})
    again = _list(step(MENU, state, Inbound.text("¿y?"), catalog=other).actions)
    assert _ids(again)[0] == "prod:p1" and again.sections[0].title == "CAFE"


def test_products_without_category_go_under_otros_last() -> None:
    catalog = _catalog([(None, 3), ("Shawarmas", 5), ("Bebidas", 4)])
    rows = products_list(NODE, catalog).rows
    assert [(r.id, r.title, r.description) for r in rows] == [
        ("cat:shawarmas", "Shawarmas", "5 productos"),
        ("cat:bebidas", "Bebidas", "4 productos"),
        ("cat:otros", "Otros", "3 productos"),
    ]


def test_a_long_category_name_is_clipped_to_the_row_title_limit() -> None:
    name = "Hamburguesas artesanales de la casa"
    rows = products_list(NODE, _catalog([(name, 6), ("Bebidas", 6)])).rows
    assert len(rows[0].title) <= 24 and rows[0].title.endswith("…")


# --- review follow-ups (C1, C2, C6, U1, U5) ----------------------------------------------


def test_a_product_tap_from_a_pre_deploy_direct_list_is_added() -> None:
    """C1(a): the thread's context predates categories mode (only `products_page`)."""
    walk = Walk(PILOT, ThreadMenuState(node_id="productos", context={CTX_PRODUCTS_PAGE: 1}))
    result = walk(Inbound.list_reply("prod:p15"))
    assert isinstance(result.actions[0], SendButtons) and walk.state.node_id == "agregado"
    assert walk.state.order[0]["product_id"] == "p15" and walk.state.attempts == 0


def test_a_product_tap_from_another_categorys_message_is_added() -> None:
    """C1(b): inside «Combos», the customer taps a drink from an earlier message."""
    walk = Walk(PILOT)
    walk(Inbound.button_reply("ver_menu"))
    walk(Inbound.list_reply("cat:combos"))
    walk(Inbound.list_reply("prod:p20"))
    assert walk.state.node_id == "agregado"
    assert [line["product_id"] for line in walk.state.order] == ["p20"]


def test_a_tap_on_a_product_no_longer_in_the_catalog_is_unknown_input() -> None:
    walk = Walk(PILOT, ThreadMenuState(node_id="productos", context={CTX_CATEGORIES_PAGE: 0}))
    result = walk(Inbound.list_reply("prod:retirado"))
    assert _list(result.actions).body.startswith(HELP_LINE) and walk.state.attempts == 1
    assert walk.state.order == []


def test_agregar_mas_reopens_the_categories_hub_not_the_last_category() -> None:
    """C2 (lead's decision): after a pick the categories list is the hub — after a combo
    the customer usually wants another category."""
    walk = Walk(PILOT)
    walk(Inbound.button_reply("ver_menu"))
    walk(Inbound.list_reply("cat:combos"))
    walk(Inbound.list_reply("prod:p17"))
    hub = _list(walk(Inbound.button_reply("agregar_mas")).actions)
    assert _ids(hub)[0].startswith("cat:") and hub.body == NODE.categories_body
    assert CTX_PRODUCTS_CATEGORY not in walk.state.context


@pytest.mark.parametrize(
    ("size", "expected_rows"),
    [
        (8, [f"prod:p{i}" for i in range(1, 9)] + ["cats:back"]),
        (9, [f"prod:p{i}" for i in range(1, 10)] + ["cats:back"]),
        (10, [f"prod:p{i}" for i in range(1, 9)] + ["more:1", "cats:back"]),
    ],
)
def test_a_category_pages_only_when_its_items_do_not_fit_beside_the_back_row(
    size: int, expected_rows: list[str]
) -> None:
    """C6: 9 items + «Ver otras categorías» are 10 rows — one page."""
    catalog = _catalog([("Grande", size), ("Otra", 3)])
    walk = Walk(catalog)
    walk(Inbound.button_reply("ver_menu"))
    shown = _list(walk(Inbound.list_reply("cat:grande")).actions)
    assert _ids(shown) == expected_rows and len(shown.rows) <= NODE.page_size
    assert shown.rows[-1].title == "Ver otras categorías"  # always last


def test_the_category_body_says_where_the_customer_is() -> None:
    """U5: «{Categoría}: elige el tuyo.», neutral for any trade."""
    walk = Walk(PILOT)
    walk(Inbound.button_reply("ver_menu"))
    assert _list(walk(Inbound.list_reply("cat:ensaladas")).actions).body == (
        "Ensaladas: elige el tuyo."
    )


def test_the_schema_default_is_neutral_and_the_food_starter_keeps_its_question() -> None:
    """U1: a stored menu without the field gets «¿Qué quieres ver?»; a menu born from the
    food starter says «¿Qué se te antoja?»."""
    from qualify_api.whatsapp.menus.starter import (
        FOOD_CATEGORIES_BODY,
        StarterFacts,
        build_starter_menu,
    )

    assert NODE.categories_body == "¿Qué quieres ver?"  # the demo predates the field
    starter = build_starter_menu(StarterFacts(business_name="La Esquina"))
    food = starter.nodes["productos"]
    assert isinstance(food, ProductsNode)
    assert food.categories_body == FOOD_CATEGORIES_BODY == "¿Qué se te antoja?"
    assert products_list(food, PILOT).body == "¿Qué se te antoja?"
