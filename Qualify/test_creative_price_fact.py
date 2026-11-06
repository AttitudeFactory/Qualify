"""«Datos clave» takes the catalog product's price (founder requests 2026-11-04).

Pins:
1. Choosing a catalog product with a price adds «Precio» with the catalog's own label,
   first in the rows; it reaches the brief like a typed fact (`_highlight_pairs`).
2. That row belongs to the product: it cannot be removed (no «Quitar» in the view, and
   `remove_highlight` refuses it), its name stays «Precio», and only its value is the
   owner's to change — editing never makes it removable.
3. Changing product replaces it with the new product's price, edited or not (one
   product's price never reaches another's piece); a product without a price, unpicking
   it, a stock image or «Crear una publicación nueva» remove it.
4. A «Precio» the owner typed before picking a product stays theirs: no pre-fill, and
   it can still be removed.
5. The 12-row limit holds; an emptied value is skipped by the brief, as any empty fact.
6. The label is the catalog's formatter (`qualify_api.catalog.read.price_label`),
   carried by the generator's picker rows.
"""

from __future__ import annotations

import inspect
import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
import reflex as rx
from qualify_api.catalog.read import price_label
from qualify_creative.schemas import HIGHLIGHTS_MAX

from .business_switch import REFLEX_TOKEN_KEY, switch_script
from .catalog_vm import ProductVM
from .creative_state import CreativeState
from .creative_vm import (
    DUPLICATE_PRICE_NOTE,
    PRICE_FACT_HINT,
    PRICE_FACT_LABEL,
    RULES_HINT,
    is_catalog_price_fact,
    prefill_price_fact,
    refresh_price_fact,
    rules_hint,
)

_CATALOG = [
    {"id": "p1", "name": "Shawarma mixto", "price_label": "$25000"},
    {"id": "p2", "name": "Ensalada", "price_label": "$18000"},
    {"id": "p3", "name": "Combo sin precio", "price_label": ""},
]


def _state() -> CreativeState:
    state = CreativeState()
    state.catalog_items = [dict(item) for item in _CATALOG]
    return state


def _facts(state: CreativeState) -> list[tuple[str, str]]:
    return [(row["key"], row["value"]) for row in state.brief_highlights]


# -- 1. the pre-fill --------------------------------------------------------------------


def test_a_product_with_a_price_prefills_it_and_the_brief_takes_it() -> None:
    state = _state()
    state.brief_highlights = [{"key": "Descuento", "value": "20 %"}]
    state.choose_product("p1")
    assert _facts(state) == [("Precio", "$25000"), ("Descuento", "20 %")]
    assert is_catalog_price_fact(state.brief_highlights[0])
    assert state._highlight_pairs() == [["Precio", "$25000"], ["Descuento", "20 %"]]
    assert state._generator_form()["highlights"] == [["Precio", "$25000"], ["Descuento", "20 %"]]


def test_a_product_without_a_price_adds_nothing() -> None:
    state = _state()
    state.choose_product("p3")
    assert state.brief_highlights == []
    state.catalog_items = [{"id": "p4", "name": "Viejo"}]  # a row with no price key
    state.choose_product("p4")
    assert state.brief_highlights == []


# -- 2. it cannot be removed; only its value changes --------------------------------------


def test_the_catalog_price_row_cannot_be_removed() -> None:
    state = _state()
    state.brief_highlights = [{"key": "Fecha", "value": "viernes 31"}]
    state.choose_product("p1")
    state.remove_highlight(0)
    assert _facts(state) == [("Precio", "$25000"), ("Fecha", "viernes 31")]
    state.remove_highlight(1)  # any other row still goes
    assert _facts(state) == [("Precio", "$25000")]


def test_editing_the_value_keeps_it_unremovable() -> None:
    state = _state()
    state.choose_product("p1")
    state.set_highlight(0, "value", "$22000 hoy")
    state.remove_highlight(0)
    assert _facts(state) == [("Precio", "$22000 hoy")]
    assert is_catalog_price_fact(state.brief_highlights[0])


def test_its_name_stays_precio() -> None:
    state = _state()
    state.choose_product("p1")
    state.set_highlight(0, "key", "Oferta")
    assert _facts(state) == [("Precio", "$25000")]


def test_an_emptied_value_is_skipped_by_the_brief() -> None:
    state = _state()
    state.brief_highlights = [{"key": "Descuento", "value": "20 %"}]
    state.choose_product("p1")
    state.set_highlight(0, "value", "   ")
    assert state._highlight_pairs() == [["Descuento", "20 %"]]
    assert state._generator_form()["highlights"] == [["Descuento", "20 %"]]


def test_the_view_hides_quitar_and_locks_the_name_for_the_catalog_row() -> None:
    from . import content_generator

    source = inspect.getsource(content_generator._highlight_row)
    # «Quitar» only on the false branch of the catalog-row condition
    locked = source.index("rx.cond(\n            from_catalog,")
    assert locked < source.index("CreativeState.remove_highlight(index)")
    # the name is fixed text on the catalog branch, the input only on the other one
    key_input = source.index('CreativeState.set_highlight(index, "key"')
    assert source.index("q-cr-highlight-fixed") < key_input
    row = rx.Var.create({"key": "Precio", "value": "$1", "product": "p1"})
    rendered = str(content_generator._highlight_row(row, rx.Var.create(0)))
    assert "highlight_notes" in rendered  # the note comes from `highlight_notes`
    assert PRICE_FACT_HINT == (
        "Viene de la Galería. Si lo cambias, allí también cambia al crear la publicación."
    )


# -- 3. it belongs to the product ---------------------------------------------------------


def test_changing_product_replaces_the_price_even_after_an_edit() -> None:
    state = _state()
    state.choose_product("p1")
    state.set_highlight(0, "value", "$22000 hoy")
    state.choose_product("p2")
    assert _facts(state) == [("Precio", "$18000")]
    assert state.brief_highlights[0]["product"] == "p2"


def test_a_product_without_a_price_removes_the_previous_one() -> None:
    state = _state()
    state.brief_highlights = [{"key": "Fecha", "value": "viernes 31"}]
    state.choose_product("p1")
    state.set_highlight(0, "value", "$20000")
    state.choose_product("p3")
    assert _facts(state) == [("Fecha", "viernes 31")]


def test_unpicking_the_product_removes_its_price() -> None:
    state = _state()
    state.brief_highlights = [{"key": "Fecha", "value": "viernes 31"}]
    state.choose_product("p1")
    state.set_highlight(0, "value", "$20000")
    state.choose_product("p1")  # the same product again unpicks it
    assert _facts(state) == [("Fecha", "viernes 31")]


def test_a_new_publication_leaves_no_price_row_behind() -> None:
    state = _state()
    state.choose_product("p1")
    state.set_highlight(0, "value", "$20000")
    CreativeState.start_new_piece.fn(state)
    assert state.brief_highlights == []
    state.catalog_items = [dict(item) for item in _CATALOG]
    state.choose_product("p2")
    assert _facts(state) == [("Precio", "$18000")]


# -- 4. a price the owner typed -----------------------------------------------------------


def test_a_price_the_owner_typed_stays_theirs_and_removable() -> None:
    state = _state()
    state.brief_highlights = [{"key": " precio ", "value": "2x $30000"}]
    state.choose_product("p1")
    assert _facts(state) == [(" precio ", "2x $30000")]
    state.choose_product("p2")
    assert _facts(state) == [(" precio ", "2x $30000")]
    assert not is_catalog_price_fact(state.brief_highlights[0])
    state.remove_highlight(0)
    assert state.brief_highlights == []


# -- 5. the limit -------------------------------------------------------------------------


def test_no_room_means_no_prefill() -> None:
    rows = [{"key": f"Dato {i}", "value": "x"} for i in range(HIGHLIGHTS_MAX)]
    out = prefill_price_fact(rows, product_id="p1", price_label="$10", limit=HIGHLIGHTS_MAX)
    assert out == rows


def test_a_full_list_still_swaps_the_catalog_price_on_product_change() -> None:
    state = _state()
    state.choose_product("p1")
    while len(state.brief_highlights) < HIGHLIGHTS_MAX:
        state.add_highlight()
    state.add_highlight()  # the 13th never comes
    assert len(state.brief_highlights) == HIGHLIGHTS_MAX
    state.choose_product("p2")
    assert len(state.brief_highlights) == HIGHLIGHTS_MAX
    assert _facts(state)[0] == ("Precio", "$18000")


def test_the_prefill_label_is_plain_spanish() -> None:
    assert PRICE_FACT_LABEL == "Precio"


# -- 6. the catalog's label ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "currency", "label"),
    [
        (Decimal("25000.00"), "COP", "$25000"),
        (Decimal("10.00"), "USD", "$10"),
        (Decimal("12.50"), "USD", "$12.5"),
        (Decimal("450"), "UYU", "$450"),
        (Decimal("90"), "VES", "Bs.90"),
        (Decimal("89990"), "CLP", "89990 CLP"),
        (None, "COP", ""),
    ],
)
def test_the_label_is_the_catalogs_own_formatting(
    amount: Decimal | None, currency: str, label: str
) -> None:
    assert price_label(amount, currency) == label


def test_the_pickers_rows_carry_the_catalog_price(monkeypatch: pytest.MonkeyPatch) -> None:
    from . import catalog_provider
    from .creative_provider import catalog_products

    product = ProductVM(
        product_id="p1",
        name="Shawarma mixto",
        slug="shawarma-mixto",
        description="",
        price_label="$25000",
        price_amount="25000",
        price_currency="COP",
        category="",
        primary_photo_key="",
        photo_count=0,
        video_count=0,
        counts_label="",
    )
    monkeypatch.setattr(catalog_provider, "list_products", lambda tenant, brand: (product,))
    rows = catalog_products(UUID(int=1), UUID(int=2))
    assert rows[0]["price_label"] == "$25000"


# -- 7. review fixes (2026-11-04) ---------------------------------------------------------


def test_the_folded_hint_names_the_catalog_price() -> None:
    state = _state()
    assert state.rules_hint == RULES_HINT
    state.choose_product("p1")
    assert (
        state.rules_hint == "Ya pusimos el precio de tu producto ($25000). Ábrelo para cambiarlo."
    )
    state.set_highlight(0, "value", "  ")
    assert state.rules_hint == RULES_HINT  # an emptied price says nothing
    assert rules_hint([{"key": "Precio", "value": "$5"}]) == RULES_HINT  # the owner's own


def test_the_step_shows_the_hint_var_not_a_fixed_text() -> None:
    from . import content_generator

    assert "CreativeState.rules_hint" in inspect.getsource(content_generator._step_say)


def test_the_catalog_row_name_is_text_with_a_spacer_and_a_described_value() -> None:
    from . import content_generator

    row = rx.Var.create({"key": "Precio", "value": "$1", "product": "p1"})
    rendered = str(content_generator._highlight_row(row, rx.Var.create(0)))
    assert "q-cr-highlight-fixed" in rendered
    assert "q-cr-highlight-spacer" in rendered
    assert "q-cr-hl-hint-" in rendered
    assert "aria-describedby" in rendered or "ariaDescribedby" in rendered
    assert "read_only" not in inspect.getsource(content_generator._highlight_row)
    css = (Path(__file__).resolve().parent.parent / "assets" / "qualify-creative.css").read_text(
        encoding="utf-8"
    )
    assert ".q-cr-highlight-spacer { width: 44px;" in css  # = `.q-cr-rules .rt-IconButton`
    assert ".q-cr-highlight-fixed { min-height: 44px;" in css


def _chosen() -> CreativeState:
    state = _state()
    state.choose_product("p1")
    return state


def _reload(state: CreativeState, items: list[dict[str, str]]) -> None:
    previous = state.catalog_items
    state.catalog_items = items
    state._refresh_price_fact(previous)


def test_a_reread_catalog_without_the_product_drops_its_price() -> None:
    state = _chosen()
    _reload(state, [dict(_CATALOG[1])])
    assert state.brief_highlights == []


def test_a_reread_catalog_without_its_price_drops_the_row() -> None:
    state = _chosen()
    _reload(state, [{**_CATALOG[0], "price_label": ""}])
    assert state.brief_highlights == []


def test_a_changed_catalog_price_overwrites_the_value() -> None:
    state = _chosen()
    state.set_highlight(0, "value", "$22000 hoy")
    _reload(state, [{**_CATALOG[0], "price_label": "$27000"}])
    assert _facts(state) == [("Precio", "$27000")]


def test_an_unchanged_catalog_price_keeps_the_owner_edit() -> None:
    state = _chosen()
    state.set_highlight(0, "value", "$22000 hoy")
    _reload(state, [dict(_CATALOG[0])])
    assert _facts(state) == [("Precio", "$22000 hoy")]
    state.catalog_items = []  # a first read: the price before is unknown, so no change
    _reload(state, [dict(_CATALOG[0])])
    assert _facts(state) == [("Precio", "$22000 hoy")]


def test_a_price_new_to_the_product_is_prefilled_on_reread() -> None:
    state = _state()
    state.choose_product("p3")
    _reload(state, [{**_CATALOG[2], "price_label": "$9000"}])
    assert _facts(state) == [("Precio", "$9000")]


def test_refresh_without_a_product_only_drops_the_catalog_row() -> None:
    rows = [{"key": "Precio", "value": "$1", "product": "p1"}, {"key": "Fecha", "value": "x"}]
    out = refresh_price_fact(rows, product_id="", old_label="$1", new_label="$1", limit=12)
    assert out == [{"key": "Fecha", "value": "x"}]


def test_an_empty_owner_price_row_makes_way_for_the_catalog_price() -> None:
    state = _state()
    state.brief_highlights = [{"key": "Precio", "value": ""}, {"key": "Fecha", "value": "x"}]
    state.choose_product("p1")
    assert _facts(state) == [("Precio", "$25000"), ("Fecha", "x")]


def _type(state: CreativeState, index: int, text: str) -> None:
    """Letter by letter, as the input sends it."""
    for end in range(1, len(text) + 1):
        state.set_highlight(index, "key", text[:end])


def test_the_owner_can_type_any_name_precio_included() -> None:
    state = _chosen()
    state.add_highlight()
    _type(state, 1, "Precio antes")
    assert state.brief_highlights[1]["key"] == "Precio antes"
    state.set_highlight(1, "key", "")
    _type(state, 1, "Precio")
    assert state.brief_highlights[1]["key"] == "Precio"


def test_the_brief_gets_only_the_catalog_price() -> None:
    state = _chosen()
    state.add_highlight()
    _type(state, 1, "Precio")
    state.set_highlight(1, "value", "2x1")
    state.add_highlight()
    _type(state, 2, "Precio antes")
    state.set_highlight(2, "value", "$30000")
    assert state._highlight_pairs() == [["Precio", "$25000"], ["Precio antes", "$30000"]]


def test_the_duplicate_note_shows_only_under_an_exact_precio() -> None:
    state = _chosen()
    state.add_highlight()
    state.add_highlight()
    _type(state, 1, " precio ")
    _type(state, 2, "Precio antes")
    assert state.highlight_notes == [PRICE_FACT_HINT, DUPLICATE_PRICE_NOTE, ""]
    assert DUPLICATE_PRICE_NOTE == "Ya tienes el precio de tu producto arriba. Cámbialo ahí."
    state.choose_product("p1")  # unpicked: no catalog price, so no note
    assert state.highlight_notes == ["", ""]


def test_rows_without_a_note_carry_no_aria_describedby() -> None:
    from . import content_generator

    source = inspect.getsource(content_generator._highlight_row)
    branches = source.index("has_note,\n                    value_input(aria_describedby=hint_id),")
    assert source.index("value_input(),") > branches
    assert "aria_describedby=rx.cond" not in source


def test_an_owner_price_that_slipped_in_is_skipped_by_the_brief() -> None:
    state = _state()
    state.brief_highlights = [
        {"key": "Precio", "value": "$25000", "product": "p1"},
        {"key": "precio", "value": "2x1"},
        {"key": "Fecha", "value": "viernes"},
    ]
    assert state._highlight_pairs() == [["Precio", "$25000"], ["Fecha", "viernes"]]


def test_a_business_switch_starts_from_a_fresh_state() -> None:
    script = switch_script("abc")
    assert f"sessionStorage.removeItem({json.dumps(REFLEX_TOKEN_KEY)})" in script
    assert "location.replace(" in script
    # a new Reflex token is a new CreativeState: no other business's price rides along
    assert CreativeState().brief_highlights == []
