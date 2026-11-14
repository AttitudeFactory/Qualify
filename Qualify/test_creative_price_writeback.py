"""The «Precio» edited in «Datos clave» goes back to the catalog — only once the piece is
made (founder 2026-11-04, m-24945916).

Pins: a successful generation updates the product's price once (same completion again:
no second write) and says so in a toast and on the piece's result; a failed, cancelled,
left or timed-out one updates nothing, forgets the edit and says the catalog kept its
price; an unreadable value updates nothing and says why (already in the row's note while
typing); a write the catalog refuses says so; a price changed meanwhile elsewhere is
never overwritten; another business's product is never touched (RLS → the service's
`UnknownProduct`); a product switched or unpicked before the end updates nothing; the
amount is read per the product's currency.
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from uuid import UUID

import pytest
from qualify_api.catalog.read import price_label
from qualify_api.catalog.service import UnknownProduct

from . import catalog_provider
from . import creative_state as module
from .creative_state import CreativeState
from .creative_vm import (
    PRICE_CHANGED_ELSEWHERE,
    PRICE_FACT_HINT,
    catalog_price_edit,
    parse_owner_price,
    price_kept_text,
)

TENANT = UUID(int=7)
PRODUCT = "00000000-0000-0000-0000-0000000000a1"
OTHER = "00000000-0000-0000-0000-0000000000b2"
DRAFT = "00000000-0000-0000-0000-0000000000d1"
KEPT = "No cambiamos el precio en la Galería; sigue en $25.000."

_CATALOG = [
    {"id": PRODUCT, "name": "Shawarma", "price_label": "$25.000", "price_currency": "COP"},
    {"id": OTHER, "name": "Ensalada", "price_label": "$18.000", "price_currency": "COP"},
]


class _Proxy:
    """Reflex's StateProxy in a test: `async with self` is a no-op lock."""

    def __init__(self, state: CreativeState) -> None:
        object.__setattr__(self, "_state", state)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._state, name, value)


class _Catalog:
    """The catalog behind the provider: the price it holds now, and the writes."""

    def __init__(self) -> None:
        self.label = "$25.000"
        self.writes: list[tuple[UUID, UUID, Decimal]] = []

    def read(self, tenant_id: UUID, product_id: UUID) -> str:
        return self.label

    def write(self, tenant_id: UUID, product_id: UUID, amount: Decimal) -> None:
        self.writes.append((tenant_id, product_id, amount))


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> _Catalog:
    fake = _Catalog()
    monkeypatch.setattr(module, "product_price_label", fake.read)
    monkeypatch.setattr(module, "update_product_price", fake.write)
    return fake


def _edited(value: str = "$20.000") -> CreativeState:
    """A piece submitted (and on screen) with the product's «Precio» edited to `value`."""
    state = CreativeState()
    state.catalog_items = [dict(item) for item in _CATALOG]
    state.choose_product(PRODUCT)
    state.set_highlight(0, "value", value)
    snapshot = state._price_edit_snapshot()
    state._price_pending = {**snapshot, "draft_id": DRAFT} if snapshot else {}
    state.gen_draft_id = DRAFT
    state.generator_view = "result"
    return state


async def _complete(state: CreativeState, draft_id: str = DRAFT) -> list[str]:
    events = await CreativeState._sync_catalog_price(_Proxy(state), TENANT, draft_id)
    return [str(event) for event in events]


def _says(events: list[str], text: str) -> bool:
    import json

    return any(text in e or json.dumps(text)[1:-1] in e for e in events)


# -- success ------------------------------------------------------------------------------


async def test_a_made_piece_updates_the_catalog_price_once(catalog: _Catalog) -> None:
    state = _edited("$20.000")
    events = await _complete(state)
    assert catalog.writes == [(TENANT, UUID(PRODUCT), Decimal("20000.00"))]
    done = "Actualizamos el precio en la Galería a $20.000."
    assert _says(events, done)
    assert state.gen_price_note == done and state.gen_price_ok  # on the piece's result
    # the row is the catalog's again, not «edited»
    assert state.brief_highlights[0]["value"] == "$20.000"
    assert state.catalog_items[0]["price_label"] == "$20.000"
    assert state._price_edit_snapshot() == {}
    assert await _complete(state) == []  # the same completion again: no second write
    assert len(catalog.writes) == 1


def test_the_result_screen_shows_the_note() -> None:
    from . import content_generator

    source = inspect.getsource(content_generator._result_view)
    assert "CreativeState.gen_price_note" in source and "gen_price_ok" in source
    state = _edited()
    CreativeState.start_new_piece.fn(state)
    assert state.gen_price_note == ""


async def test_the_same_amount_in_another_format_writes_nothing(catalog: _Catalog) -> None:
    state = _edited("$25000")
    assert await _complete(state) == []
    assert catalog.writes == []
    assert state.brief_highlights[0]["value"] == "$25.000"


@pytest.mark.parametrize(
    ("currency", "amount", "typed", "updated", "label"),
    [
        ("COP", "25000", "$20.000", "20000", "$20.000"),
        ("USD", "1000", "$1000,50", "1000.50", "$1000,50"),
        ("VES", "90", "Bs. 1.234,50", "1234.50", "Bs. 1.234,50"),
        ("UYU", "1000", "$2.345,50", "2345.50", "$2.345,50"),
        ("COP", "1000000000", "$1.000.000.001", "1000000001", "$1.000.000.001"),
        ("UYU", "1000000000", "$1.000.000.001", "1000000001", "$1.000.000.001"),
        ("VES", "1000000000", "Bs. 1.000.000.001", "1000000001", "Bs. 1.000.000.001"),
    ],
)
async def test_localized_price_edits_round_trip_without_changing_the_currency(
    catalog: _Catalog, currency: str, amount: str, typed: str, updated: str, label: str
) -> None:
    state = CreativeState()
    catalog.label = price_label(Decimal(amount), currency)
    state.catalog_items = [
        {**_CATALOG[0], "price_label": catalog.label, "price_currency": currency}
    ]
    state.choose_product(PRODUCT)
    assert state._price_edit_snapshot() == {}
    assert state._highlight_pairs() == [["Precio", catalog.label]]
    assert parse_owner_price(catalog.label, currency) == Decimal(amount)
    state.set_highlight(0, "value", typed)
    state._price_pending = {**state._price_edit_snapshot(), "draft_id": DRAFT}
    state.gen_draft_id, state.generator_view = DRAFT, "result"

    assert _says(await _complete(state), f"Actualizamos el precio en la Galería a {label}.")
    assert catalog.writes == [(TENANT, UUID(PRODUCT), Decimal(updated))]
    assert state.catalog_items[0]["price_label"] == label
    assert state.catalog_items[0]["price_currency"] == currency
    assert state._highlight_pairs() == [["Precio", label]]
    assert state._price_edit_snapshot() == {}
    assert await _complete(state) == []


@pytest.mark.parametrize(
    ("amount", "currency", "equivalent"),
    [
        ("25000", "COP", "$25000"),
        ("10.50", "USD", "$10.50"),
        ("1000", "USD", "1000"),
        ("90", "VES", "Bs.90"),
        ("1234.50", "UYU", "1234,50"),
    ],
)
async def test_equivalent_local_prices_never_write_a_price_back(
    catalog: _Catalog, amount: str, currency: str, equivalent: str
) -> None:
    state = CreativeState()
    catalog.label = price_label(Decimal(amount), currency)
    state.catalog_items = [
        {**_CATALOG[0], "price_label": catalog.label, "price_currency": currency}
    ]
    state.choose_product(PRODUCT)
    state.set_highlight(0, "value", equivalent)
    assert state.highlight_notes == [PRICE_FACT_HINT]
    state._price_pending = {**state._price_edit_snapshot(), "draft_id": DRAFT}
    assert await _complete(state) == []
    assert catalog.writes == []
    assert state.catalog_items[0]["price_label"] == catalog.label


# -- failures, each with its own sentence ---------------------------------------------------


async def test_an_unreadable_value_updates_nothing_and_says_why(catalog: _Catalog) -> None:
    state = _edited("unos 20 mil")
    events = await _complete(state)
    text = "En la Galería sigue $25.000: «unos 20 mil» no lo pudimos leer como precio."
    assert catalog.writes == []
    assert _says(events, text)
    assert state.gen_price_note == text and not state.gen_price_ok
    assert state.catalog_items[0]["price_label"] == "$25.000"


async def test_a_refused_write_says_the_catalog_kept_its_price(
    monkeypatch: pytest.MonkeyPatch, catalog: _Catalog
) -> None:
    def refuse(tenant_id: UUID, product_id: UUID, amount: Decimal) -> None:
        raise UnknownProduct(str(product_id))  # what RLS makes of a foreign product

    monkeypatch.setattr(module, "update_product_price", refuse)
    state = _edited()
    events = await _complete(state)
    text = "No pudimos cambiar el precio en la Galería; sigue en $25.000. Cámbialo allí si quieres."
    assert _says(events, text)
    assert state.catalog_items[0]["price_label"] == "$25.000"


async def test_another_business_product_is_never_touched(
    monkeypatch: pytest.MonkeyPatch, catalog: _Catalog
) -> None:
    def foreign(tenant_id: UUID, product_id: UUID) -> str:
        raise UnknownProduct(str(product_id))  # RLS hides it: it is not this tenant's

    monkeypatch.setattr(module, "product_price_label", foreign)
    state = _edited()
    events = await _complete(state)
    assert catalog.writes == []
    assert _says(events, "No pudimos cambiar el precio en la Galería")


async def test_a_price_changed_elsewhere_is_never_overwritten(catalog: _Catalog) -> None:
    state = _edited("$20.000")
    catalog.label = "$27.000"  # another tab saved a new price while the piece was made
    events = await _complete(state)
    assert catalog.writes == []
    assert _says(events, PRICE_CHANGED_ELSEWHERE)
    assert PRICE_CHANGED_ELSEWHERE == (
        "El precio en la Galería cambió mientras se creaba la publicación; no lo tocamos."
    )


def test_the_provider_writes_only_the_price_under_the_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class _Service:
        def update_product(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(catalog_provider, "_service", lambda: _Service())
    catalog_provider.update_product_price(TENANT, UUID(PRODUCT), Decimal("20000"))
    # the catalog's own door (`tenant_session(tenant_id)` inside the service); the
    # currency and the rest are not sent, so they stay
    assert calls == [
        {"tenant_id": TENANT, "product_id": UUID(PRODUCT), "price_amount": Decimal("20000")}
    ]


# -- the edit that never reaches the catalog ----------------------------------------------


async def test_a_product_switched_before_the_end_updates_nothing(catalog: _Catalog) -> None:
    state = _edited()
    state.choose_product(OTHER)
    assert _says(await _complete(state), KEPT)
    assert catalog.writes == []


async def test_a_product_unpicked_before_the_end_updates_nothing(catalog: _Catalog) -> None:
    state = _edited()
    state.choose_product(PRODUCT)  # unpicks
    assert _says(await _complete(state), KEPT)
    state = _edited()
    CreativeState.start_new_piece.fn(state)
    assert _says(await _complete(state), KEPT)
    assert catalog.writes == []


def test_a_failed_cancelled_left_or_timed_out_piece_forgets_the_edit() -> None:
    state = _edited()
    assert state._drop_pending_price(DRAFT) == KEPT
    assert state._price_pending == {}
    assert state._drop_pending_price(DRAFT) == ""  # said once
    state = _edited()
    assert state._drop_pending_price("00000000-0000-0000-0000-0000000000ff") == ""
    assert state._price_pending  # another piece's end leaves this edit alone
    source = inspect.getsource(CreativeState.poll_generator.fn)
    # every way the poll ends without a made piece drops the pending edit
    assert source.count("_drop_pending_price(draft_id)") == 3
    assert source.index('if outcome == "ready":') < source.index("_sync_catalog_price")
    assert source.index("vm.queue.cancelled") < source.index("_sync_catalog_price")
    assert price_kept_text("$25.000") == KEPT


async def test_a_forgotten_edit_is_never_written_later(catalog: _Catalog) -> None:
    state = _edited()
    state._drop_pending_price(DRAFT)  # the piece failed
    assert await _complete(state) == []  # a later completion of the same draft
    assert catalog.writes == []


async def test_an_emptied_catalog_row_never_writes_an_empty_price(catalog: _Catalog) -> None:
    state = _edited("   ")
    assert state._price_pending == {}
    assert await _complete(state) == []
    assert catalog.writes == []


def test_an_emptied_catalog_row_lets_the_owner_price_reach_the_brief() -> None:
    state = CreativeState()
    state.catalog_items = [dict(item) for item in _CATALOG]
    state.choose_product(PRODUCT)
    state.set_highlight(0, "value", "")
    state.add_highlight()
    state.set_highlight(1, "key", "Precio")
    state.set_highlight(1, "value", "2x $30000")
    assert state._highlight_pairs() == [["Precio", "2x $30000"]]
    state.set_highlight(0, "value", "$25.000")  # the catalog's back: one price only
    assert state._highlight_pairs() == [["Precio", "$25.000"]]


# -- the row's note while editing ---------------------------------------------------------


def test_the_note_says_what_creating_will_do_to_the_catalog() -> None:
    state = CreativeState()
    state.catalog_items = [dict(item) for item in _CATALOG]
    state.choose_product(PRODUCT)
    assert state.highlight_notes == [PRICE_FACT_HINT]
    assert PRICE_FACT_HINT == (
        "Viene de la Galería. Si lo cambias, allí también cambia al crear la publicación. "
        "El precio no se dibuja sobre la imagen. Si quieres que se vea, escríbelo en el texto "
        "de la publicación."
    )
    state.set_highlight(0, "value", "$20.000")
    assert state.highlight_notes == [
        "Al crear la publicación, el precio en la Galería pasará de $25.000 a $20.000. "
        "¿Es solo una promoción? Escríbela en otro dato."
    ]
    state.set_highlight(0, "value", "2x1")  # told before creating, not after
    assert state.highlight_notes == [
        "En la Galería sigue $25.000: «2x1» no lo pudimos leer como precio."
    ]
    state.set_highlight(0, "value", "$25.000")  # the same amount: no change ahead
    assert state.highlight_notes == [PRICE_FACT_HINT]


def test_an_unedited_price_is_no_edit() -> None:
    rows = [{"key": "Precio", "value": "$25.000", "product": PRODUCT}]
    assert catalog_price_edit(rows, product_id=PRODUCT, catalog_label="$25.000") is None
    assert catalog_price_edit(rows, product_id=OTHER, catalog_label="$1") is None


# -- reading the amount -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "currency", "amount"),
    [
        ("$20.000", "COP", Decimal("20000")),
        ("20000", "COP", Decimal("20000")),
        ("$20,50", "COP", Decimal("20.50")),
        ("20.000 pesos", "COP", Decimal("20000")),
        ("20.000 pesos", "UYU", Decimal("20000")),
        ("Bs. 90", "VES", Decimal("90")),
        ("Bs.90", "VES", Decimal("90")),
        ("$12.50", "USD", Decimal("12.50")),
        ("$12,50", "USD", Decimal("12.50")),
        ("1,234.56", "USD", Decimal("1234.56")),
        ("1.234,56", "USD", Decimal("1234.56")),
        ("1,234,567", "USD", Decimal("1234567")),
        ("20 dólares", "USD", Decimal("20")),
        # refused rather than guessed
        ("1.999", "USD", None),
        ("20.000", "USD", None),
        ("1,999", "USD", None),
        ("20.50", "COP", None),
        ("20,000", "COP", None),
        ("1,234.56", "COP", None),
        ("Bs. 90", "COP", None),
        ("$90", "VES", None),
        ("20 dólares", "COP", None),
        ("unos 20 mil", "COP", None),
        ("", "COP", None),
        ("$20", "", None),
        ("0", "COP", None),
        ("$0,00", "COP", None),
        ("-5", "USD", None),
    ],
)
def test_the_amount_is_read_per_the_currency(
    text: str, currency: str, amount: Decimal | None
) -> None:
    got = parse_owner_price(text, currency)
    assert got == (amount.quantize(Decimal("0.01")) if amount is not None else None)


async def test_piece_a_never_leaves_its_note_on_piece_b(catalog: _Catalog) -> None:
    state = _edited()
    state.gen_price_note, state.gen_price_ok = "nota de A", True
    state.create_back()  # result → form
    assert state.gen_price_note == "" and not state.gen_price_ok
    # A lands while the owner is on the form (or on B): toast only, no note
    events = await _complete(state)
    assert _says(events, "Actualizamos el precio")
    assert state.gen_price_note == ""
    source = inspect.getsource(CreativeState.submit_generator_form.fn)
    assert source.index("self.gen_draft_id = str(draft_id)") < source.index(
        'self.gen_price_note = ""'
    )


async def test_a_product_without_currency_is_unreadable_and_points_to_tus_productos(
    catalog: _Catalog,
) -> None:
    state = CreativeState()
    state.catalog_items = [{**_CATALOG[0], "price_currency": ""}]
    state.choose_product(PRODUCT)
    state.set_highlight(0, "value", "$20.000")
    snapshot = state._price_edit_snapshot()
    state._price_pending = {**snapshot, "draft_id": DRAFT}
    state.gen_draft_id, state.generator_view = DRAFT, "result"
    events = await _complete(state)
    assert catalog.writes == []
    assert _says(events, "No pudimos cambiar el precio en la Galería; sigue en $25.000.")
    assert state.highlight_notes  # the note does not crash without a currency
