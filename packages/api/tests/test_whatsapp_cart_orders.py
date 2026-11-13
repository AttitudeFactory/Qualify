"""m-25018684: a WhatsApp catalog cart as the thread's order, and the archive of replaced
orders (`qualify_api.whatsapp.orders`) — offline, pure. Plus the readers that must keep
working with a cart order: metrics and the chats list preview."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.whatsapp.chats import ChatService, MemoryChatRepository
from qualify_api.whatsapp.menus.engine import ENGINE_VERSION
from qualify_api.whatsapp.metrics import (
    NO_CURRENCY,
    MetricsRows,
    ThreadFact,
    aggregate,
)
from qualify_api.whatsapp.orders import (
    CART_ENGINE_VERSION,
    CTX_ORDER_RECORD,
    CTX_PREVIOUS_ORDERS,
    MAX_PREVIOUS_ORDERS,
    ORDER_READY_HEADLINE,
    SOURCE_CART,
    SOURCE_MENU,
    CartProduct,
    OrderLine,
    OrderSummary,
    cart_message_ids,
    cart_product_ids,
    cart_record,
    order_ready_text,
    read_order,
    read_previous_orders,
    record_cart_order,
    record_confirmed_order,
    recorded_order_message_ids,
)
from qualify_api.whatsapp.outbox import MemoryOutboxRepository

AT = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
LATER = AT + timedelta(minutes=5)
PRODUCT = UUID("11111111-1111-4111-8111-111111111111")
OTHER_PRODUCT = UUID("22222222-2222-4222-8222-222222222222")
SHAWARMA = CartProduct(
    product_id=str(PRODUCT),
    name="Shawarma mixto",
    price_amount=Decimal("30"),
    price_currency="USD",
)
PRODUCTS = {str(PRODUCT): SHAWARMA}


def _item(retailer: Any, qty: Any = 1, price: Any = 30, currency: Any = "USD") -> dict:
    return {
        "product_retailer_id": retailer,
        "quantity": qty,
        "item_price": price,
        "currency": currency,
    }


def _cart(context: dict, wamid: str, *items: dict, at: datetime = AT, **kw: Any) -> bool:
    return record_cart_order(
        context,
        items=list(items) or [_item(str(PRODUCT), 2)],
        products=kw.pop("products", PRODUCTS),
        confirmed_at=at,
        source_message_id=wamid,
        archived_at=kw.pop("archived_at", at),
        catalog_id=kw.pop("catalog_id", "194836987003835"),
        note=kw.pop("note", None),
        **kw,
    )


def _menu_summary(product: str = "p1") -> dict[str, Any]:
    return {
        "order": [
            {"product_id": product, "name": "Combo", "qty": 1, "price": "15000", "currency": "COP"}
        ],
        "total": "15000",
        "currency": "COP",
        "order_confirmed": True,
        "collected": {},
        "engine_version": ENGINE_VERSION,
    }


def _payment(order_message_id: str | None, status: str = "awaiting") -> dict[str, Any]:
    return {
        "choice": "method",
        "method_id": "m1",
        "name": "Pago móvil",
        "currency": "VES",
        "pay_on_delivery": False,
        "status": status,
        "order_message_id": order_message_id,
        "chosen_at": AT.isoformat(),
        "source": "menu",
    }


# --- the cart record -------------------------------------------------------------------


def test_meta_doc_cart_without_galeria_products_records_raw_ids() -> None:
    record = cart_record(
        items=[_item("di9ozbzfi4", 2, 30), _item("nqryix03ez", 1, 25)],
        products={},
        confirmed_at=AT,
        source_message_id="wamid.cart",
        catalog_id="194836987003835",
        note="Love these!",
    )
    assert record == {
        "items": [
            {
                "product_id": "di9ozbzfi4",
                "name": "",
                "linked": False,
                "price_mismatch": False,
                "qty": 2,
                "unit_price": "30.00",
                "currency": "USD",
                "retailer_id": "di9ozbzfi4",
            },
            {
                "product_id": "nqryix03ez",
                "name": "",
                "linked": False,
                "price_mismatch": False,
                "qty": 1,
                "unit_price": "25.00",
                "currency": "USD",
                "retailer_id": "nqryix03ez",
            },
        ],
        "confirmed_at": AT.isoformat(),
        "collected": {},
        "source_message_id": "wamid.cart",
        "engine_version": CART_ENGINE_VERSION,
        "source": SOURCE_CART,
        "catalog_id": "194836987003835",
        "note": "Love these!",
        "total": "85.00",
        "currency": "USD",
    }


def test_a_galeria_product_links_with_its_name_and_flags_a_price_change() -> None:
    upper = str(PRODUCT).upper()  # any UUID spelling links
    record = cart_record(
        items=[
            _item(upper, 2, 30),
            _item(str(PRODUCT), 1, "32.50"),
            _item(str(PRODUCT), 1, 30, "COP"),
        ],
        products=PRODUCTS,
        confirmed_at=AT,
        source_message_id="w",
    )
    assert record is not None
    lines = record["items"]
    assert [(i["product_id"], i["name"], i["linked"]) for i in lines] == [
        (str(PRODUCT), "Shawarma mixto", True)
    ] * 3
    assert [i["price_mismatch"] for i in lines] == [False, True, True]
    assert lines[0]["retailer_id"] == upper


def test_a_galeria_price_or_currency_that_is_not_set_is_never_a_mismatch() -> None:
    no_currency = {str(PRODUCT): CartProduct(str(PRODUCT), "Shawarma", Decimal("30"), None)}
    no_price = {str(PRODUCT): CartProduct(str(PRODUCT), "Shawarma", None, None)}
    for products, mismatch in ((no_currency, False), (no_price, False)):
        record = cart_record(
            items=[_item(str(PRODUCT))], products=products, confirmed_at=AT, source_message_id="w"
        )
        assert record is not None and record["items"][0]["price_mismatch"] is mismatch


def test_an_id_of_another_brand_is_simply_not_found_so_it_does_not_link() -> None:
    # The lookup only returns the receiving brand's products: OTHER_PRODUCT is absent.
    record = cart_record(
        items=[_item(str(OTHER_PRODUCT))], products=PRODUCTS, confirmed_at=AT, source_message_id="w"
    )
    assert record is not None
    (line,) = record["items"]
    assert (line["product_id"], line["name"], line["linked"]) == (str(OTHER_PRODUCT), "", False)


def test_only_uuid_retailer_ids_are_looked_up() -> None:
    items = [
        _item(str(PRODUCT)),
        _item(str(PRODUCT).upper()),
        _item("di9ozbzfi4"),
        _item(None),
        _item(12345),
        "junk",
    ]
    assert cart_product_ids(items) == (PRODUCT,)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [
        _item("a", 0),
        _item("a", -1),
        _item("a", "dos"),
        _item("a", True),
        _item("a", 1, 0),
        _item("a", 1, -5),
        _item("a", 1, "gratis"),
        _item("a", 1, None),
        _item("a", 1, "NaN"),
        _item("a", 1, "Infinity"),
        _item("a", 1, "1e400"),
        _item("a", 1, "1000000000000.01"),
        _item("a", 2.9),
        _item("a", "2.5"),
        _item("a", 10**30),
        _item("a", 10_001),
        _item("", 1),
        _item(None, 1),
        _item(True, 1),
    ],
)
def test_garbage_lines_are_skipped(bad: dict) -> None:
    record = cart_record(
        items=[bad, _item("ok", 1, 10)], products={}, confirmed_at=AT, source_message_id="w"
    )
    assert record is not None
    assert [i["product_id"] for i in record["items"]] == ["ok"]
    assert record["total"] == "10.00"


def test_an_empty_cart_records_nothing() -> None:
    assert cart_record(items=[], products={}, confirmed_at=AT, source_message_id="w") is None
    context: dict[str, Any] = {}
    assert not _cart(context, "w", _item("a", 0))
    assert context == {}


def test_totals_use_the_carts_prices_never_galerias() -> None:
    cheap = {str(PRODUCT): CartProduct(str(PRODUCT), "Shawarma", Decimal("1"), "USD")}
    record = cart_record(
        items=[_item(str(PRODUCT), 3, 9.99)], products=cheap, confirmed_at=AT, source_message_id="w"
    )
    assert record is not None and record["total"] == "29.97"


def test_mixed_currencies_are_never_added_together() -> None:
    context: dict[str, Any] = {}
    assert _cart(
        context, "w", _item("a", 2, 30, "usd"), _item("b", 1, 15000, "COP"), _item("c", 1, 5, "USD")
    )
    record = context[CTX_ORDER_RECORD]
    assert (record["total"], record["currency"]) == ("0", None)
    assert record["totals"] == {"COP": "15000.00", "USD": "65.00"}
    order = read_order(context)
    assert order is not None and order.mixed_currency
    assert order.totals_by_currency == {"COP": Decimal("15000"), "USD": Decimal("65")}
    assert order.total == Decimal("0") and order.currency is None


def test_read_order_round_trips_a_cart() -> None:
    context: dict[str, Any] = {}
    assert _cart(
        context, "wamid.c1", _item(str(PRODUCT), 2), _item("abc", 1, 5), note=" sin cebolla "
    )
    order = read_order(context)
    assert order == OrderSummary(
        lines=(
            OrderLine(str(PRODUCT), "Shawarma mixto", 2, Decimal("30"), "USD", str(PRODUCT), True),
            OrderLine("abc", "", 1, Decimal("5"), "USD", "abc", False),
        ),
        total=Decimal("65"),
        currency="USD",
        confirmed_at=AT,
        collected={},
        source_message_id="wamid.c1",
        source=SOURCE_CART,
        catalog_id="194836987003835",
        note="sin cebolla",
    )
    assert order.is_cart and not order.mixed_currency and order.item_count == 3


def test_a_menu_record_reads_with_the_new_fields_defaulted() -> None:
    context: dict[str, Any] = {}
    record_confirmed_order(context, _menu_summary(), confirmed_at=AT, source_message_id="w.1")
    order = read_order(context)
    assert order is not None
    assert (order.source, order.is_cart, order.catalog_id, order.note) == (
        SOURCE_MENU,
        False,
        None,
        None,
    )
    assert order.totals_by_currency == {} and not order.mixed_currency
    (line,) = order.lines
    assert (line.retailer_id, line.linked, line.price_mismatch) == (None, True, False)
    assert "source" not in context[CTX_ORDER_RECORD]


# --- idempotency and the archive -------------------------------------------------------


def test_the_same_cart_twice_keeps_the_first_record() -> None:
    context: dict[str, Any] = {}
    assert _cart(context, "wamid.c1", at=AT)
    assert not _cart(context, "wamid.c1", _item("x"), at=LATER)
    order = read_order(context)
    assert order is not None and order.confirmed_at == AT
    assert CTX_PREVIOUS_ORDERS not in context


def test_an_archived_cart_replayed_late_never_displaces_the_newer_order() -> None:
    context: dict[str, Any] = {}
    _cart(context, "wamid.c1")
    _cart(context, "wamid.c2", at=LATER)
    assert not _cart(context, "wamid.c1", at=LATER)
    assert context[CTX_ORDER_RECORD]["source_message_id"] == "wamid.c2"
    assert recorded_order_message_ids(context) == {"wamid.c1", "wamid.c2"}


def test_a_cart_replacing_a_menu_order_archives_it_with_its_payment() -> None:
    context: dict[str, Any] = {}
    record_confirmed_order(context, _menu_summary(), confirmed_at=AT, source_message_id="w.menu")
    payment = _payment("w.menu", "review")
    assert _cart(context, "w.cart", at=LATER, archived_at=LATER, payment=payment)

    assert context[CTX_ORDER_RECORD]["source"] == SOURCE_CART
    (entry,) = context[CTX_PREVIOUS_ORDERS]
    assert entry["order"]["source_message_id"] == "w.menu"
    assert entry["archived_at"] == LATER.isoformat()
    assert entry["payment"] == payment
    (previous,) = read_previous_orders(context)
    assert previous.order.source == SOURCE_MENU and previous.archived_at == LATER
    assert previous.payment is not None
    assert (previous.payment.status, previous.payment.choice, previous.payment.method_name) == (
        "review",
        "method",
        "Pago móvil",
    )


def test_a_payment_of_another_order_is_not_snapshotted() -> None:
    context: dict[str, Any] = {}
    _cart(context, "w.c1")
    _cart(context, "w.c2", payment=_payment("w.older"))
    (entry,) = context[CTX_PREVIOUS_ORDERS]
    assert entry["payment"] is None
    assert read_previous_orders(context)[0].payment is None


def test_a_menu_confirmation_replacing_a_cart_archives_it() -> None:
    context: dict[str, Any] = {}
    _cart(context, "w.cart")
    assert record_confirmed_order(
        context, _menu_summary(), confirmed_at=LATER, source_message_id="w.menu"
    )
    assert read_order(context).source == SOURCE_MENU  # type: ignore[union-attr]
    (previous,) = read_previous_orders(context)
    assert previous.order.is_cart and previous.order.source_message_id == "w.cart"
    assert previous.archived_at == LATER


def test_a_cart_replacing_a_cart_and_the_archive_cap() -> None:
    context: dict[str, Any] = {}
    for n in range(MAX_PREVIOUS_ORDERS + 3):
        assert _cart(context, f"w.{n}", at=AT + timedelta(minutes=n))
    assert context[CTX_ORDER_RECORD]["source_message_id"] == f"w.{MAX_PREVIOUS_ORDERS + 2}"
    previous = read_previous_orders(context)
    assert [p.order.source_message_id for p in previous] == [
        f"w.{n}" for n in range(MAX_PREVIOUS_ORDERS + 1, 1, -1)
    ]
    assert len(previous) == MAX_PREVIOUS_ORDERS


def test_read_previous_orders_tolerates_junk() -> None:
    assert read_previous_orders(None) == ()
    assert read_previous_orders({CTX_PREVIOUS_ORDERS: "x"}) == ()
    assert (
        read_previous_orders(
            {CTX_PREVIOUS_ORDERS: [1, {"order": "x"}, {"order": {"items": []}}, {"no": 1}]}
        )
        == ()
    )


def test_cart_message_ids_cover_current_and_archive_but_not_menu_orders() -> None:
    context: dict[str, Any] = {}
    _cart(context, "w.c1")
    record_confirmed_order(context, _menu_summary(), confirmed_at=LATER, source_message_id="w.m")
    _cart(context, "w.c2", at=LATER)
    assert cart_message_ids(context) == {"w.c1", "w.c2"}
    assert cart_message_ids(None) == frozenset()


# --- «Pedido listo» --------------------------------------------------------------------


def test_order_ready_text_names_an_unlinked_cart_line_by_its_code() -> None:
    context: dict[str, Any] = {}
    _cart(context, "w", _item(str(PRODUCT), 2), _item("ABC123", 1, 5))
    assert order_ready_text(read_order(context)) == "\n".join(  # type: ignore[arg-type]
        [
            ORDER_READY_HEADLINE,
            "",
            "2 x Shawarma mixto — USD 60",
            "1 x Producto (código ABC123) — USD 5",
            "",
            "Total: USD 65",
            "Gracias por tu pedido.",
        ]
    )


def test_order_ready_text_of_a_menu_order_is_unchanged() -> None:
    order = OrderSummary(
        lines=(OrderLine("p1", "Hamburguesa", 2, Decimal("15000"), "COP"),),
        total=Decimal("30000"),
        currency="COP",
    )
    assert order_ready_text(order) == (
        "¡Tu pedido está listo!\n\n2 x Hamburguesa — COP 30.000\n\n"
        "Total: COP 30.000\nGracias por tu pedido."
    )


def test_order_ready_text_with_mixed_currencies_totals_each() -> None:
    context: dict[str, Any] = {}
    _cart(context, "w", _item("a", 1, 15000, "COP"), _item("b", 2, 5, "USD"))
    text = order_ready_text(read_order(context))  # type: ignore[arg-type]
    assert "Total: COP 15.000 + USD 10" in text


# --- readers: metrics and the chats list -----------------------------------------------


def test_metrics_count_a_cart_and_split_mixed_currencies() -> None:
    single: dict[str, Any] = {}
    _cart(single, "w.1")
    mixed: dict[str, Any] = {}
    _cart(mixed, "w.2", _item("a", 1, 15000, "COP"), _item("b", 2, 5, "USD"))
    threads = [
        ThreadFact(
            thread_id=uuid4(),
            first_inbound_at=AT,
            first_inbound_text=None,
            context=context,
            automated=False,
        )
        for context in (single, mixed)
    ]
    result = aggregate(
        MetricsRows(threads=threads, messages=[], send_failed=0, entry=None),
        connection_id=uuid4(),
        since=AT - timedelta(days=1),
        until=AT + timedelta(days=1),
    )
    assert result.orders_confirmed == 2
    assert result.orders_total == {"USD": Decimal("70"), "COP": Decimal("15000")}
    assert NO_CURRENCY not in result.orders_total


def test_the_chats_list_previews_a_cart_as_an_order_from_the_catalog() -> None:
    # The handler stores an inbound cart with `media_type = 'order'` (0061 lists it).
    tenant, connection = uuid4(), uuid4()
    repo = MemoryChatRepository()
    thread_id = repo.add_thread(
        tenant_id=tenant, connection_id=connection, wa_id="573000000000", last_inbound_at=AT
    )
    repo.add_message(
        thread_id=thread_id, direction="inbound", text_value=None, posted_at=AT, media_kind="order"
    )
    service = ChatService(repo, MemoryOutboxRepository(clock=lambda: AT), clock=lambda: AT)
    [summary] = service.list_threads(tenant)
    assert summary.last_message_preview == "Pedido desde tu catálogo"


# --- review fixes: bounds, truncation, the Galería price ------------------------------


def test_integer_valued_quantities_and_prices_to_the_cent_are_kept() -> None:
    record = cart_record(
        items=[_item("a", "2.0", "9.999"), _item("b", 10_000, "1000000000000")],
        products={},
        confirmed_at=AT,
        source_message_id="w",
    )
    assert record is not None
    assert [(i["qty"], i["unit_price"]) for i in record["items"]] == [
        (2, "10.00"),
        (10_000, "1000000000000.00"),
    ]


def test_lines_beyond_the_cap_are_cut_and_the_record_says_so() -> None:
    from qualify_api.whatsapp.orders import MAX_CART_LINES

    items = [_item("junk", 0)] + [_item(f"sku{n}", 1, 1) for n in range(MAX_CART_LINES + 5)]
    record = cart_record(items=items, products={}, confirmed_at=AT, source_message_id="w")
    assert record is not None
    assert len(record["items"]) == MAX_CART_LINES and record["lines_truncated"] is True
    assert record["total"] == f"{MAX_CART_LINES}.00"
    order = read_order({CTX_ORDER_RECORD: record})
    assert order is not None and order.lines_truncated and not order.note_truncated


def test_a_long_note_is_cut_and_the_record_says_so() -> None:
    from qualify_api.whatsapp.orders import MAX_NOTE_CHARS

    record = cart_record(
        items=[_item("a")], products={}, confirmed_at=AT, source_message_id="w", note="x" * 5000
    )
    assert record is not None
    assert len(record["note"]) == MAX_NOTE_CHARS and record["note_truncated"] is True
    assert "lines_truncated" not in record
    order = read_order({CTX_ORDER_RECORD: record})
    assert order is not None and order.note_truncated
    exact = cart_record(
        items=[_item("a")], products={}, confirmed_at=AT, source_message_id="w", note="y" * 1000
    )
    assert exact is not None and "note_truncated" not in exact


def test_a_mismatch_keeps_the_galeria_price_it_was_compared_to() -> None:
    galeria = {str(PRODUCT): CartProduct(str(PRODUCT), "Shawarma", Decimal("12000"), "cop")}
    context: dict[str, Any] = {}
    _cart(
        context,
        "w",
        _item(str(PRODUCT), 1, 15000, "COP"),
        _item(str(PRODUCT), 1, 12000, "COP"),
        products=galeria,
    )
    changed, same = context[CTX_ORDER_RECORD]["items"]
    assert (changed["gallery_unit_price"], changed["gallery_currency"]) == ("12000", "COP")
    assert "gallery_unit_price" not in same and "gallery_currency" not in same
    first, second = read_order(context).lines  # type: ignore[union-attr]
    assert (first.price_mismatch, first.gallery_unit_price, first.gallery_currency) == (
        True,
        Decimal("12000"),
        "COP",
    )
    assert (second.gallery_unit_price, second.gallery_currency) == (None, None)


def test_old_records_read_without_the_galeria_price() -> None:
    record = {
        "items": [
            {"product_id": "p", "name": "x", "qty": 1, "unit_price": "5", "price_mismatch": True},
            {"product_id": "q", "name": "y", "qty": 1, "gallery_unit_price": "9"},
        ],
        "total": "5",
    }
    first, second = read_order({CTX_ORDER_RECORD: record}).lines  # type: ignore[union-attr]
    assert (first.gallery_unit_price, first.gallery_currency) == (None, None)
    assert second.gallery_unit_price is None  # only read on a flagged line


def test_readers_never_raise_on_absurd_stored_values() -> None:
    record = {
        "items": [
            {"product_id": "p", "name": "Gigante", "qty": 1, "unit_price": "1e400"},
            {"product_id": "q", "name": "Muchos", "qty": 10**30, "unit_price": "5"},
            {"product_id": "r", "name": "Normal", "qty": 2, "unit_price": "5", "currency": "USD"},
        ],
        "total": "1e400",
        "currency": "USD",
        "totals": {"USD": "1e400", "COP": "5"},
    }
    order = read_order({CTX_ORDER_RECORD: record})
    assert order is not None
    assert [(line.name, line.unit_price) for line in order.lines] == [
        ("Gigante", None),
        ("Normal", Decimal("5")),
    ]
    assert order.total == Decimal("0") and order.totals_by_currency == {}
    text = order_ready_text(order)
    assert "1 x Gigante" in text and "2 x Normal — USD 10" in text


def test_format_money_writes_an_unroundable_amount_as_is() -> None:
    from qualify_api.whatsapp.menus.engine import format_money

    assert format_money(Decimal("1E+30"), "USD") == "USD 1E+30"
    assert format_money(Decimal("12500"), "COP") == "COP 12.500"
