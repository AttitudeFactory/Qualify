"""WA-15: the order record a person receives (`qualify_api.whatsapp.orders`) — offline."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from qualify_api.whatsapp.menus.engine import ENGINE_VERSION
from qualify_api.whatsapp.orders import (
    CTX_ORDER_RECORD,
    ORDER_READY_HEADLINE,
    OrderLine,
    OrderSummary,
    order_ready_text,
    order_record_from_handoff,
    read_order,
    record_confirmed_order,
)

AT = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 14, 12, 5, tzinfo=UTC)


def _summary(**overrides: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "order": [
            {
                "product_id": "p1",
                "name": "Hamburguesa",
                "qty": 2,
                "price": "15000",
                "currency": "COP",
            },
            {"product_id": "p2", "name": "Gaseosa", "qty": 1, "price": "5000", "currency": "COP"},
        ],
        "total": "35000",
        "currency": "COP",
        "order_confirmed": True,
        "collected": {"direccion": "Calle 10 # 5-20"},
        "node_id": "pedido_confirmado",
        "engine_version": ENGINE_VERSION,
    }
    summary.update(overrides)
    return summary


def test_the_record_carries_items_total_collected_and_provenance() -> None:
    record = order_record_from_handoff(_summary(), confirmed_at=AT, source_message_id="wamid.9")
    assert record == {
        "items": [
            {
                "product_id": "p1",
                "name": "Hamburguesa",
                "qty": 2,
                "unit_price": "15000",
                "currency": "COP",
            },
            {
                "product_id": "p2",
                "name": "Gaseosa",
                "qty": 1,
                "unit_price": "5000",
                "currency": "COP",
            },
        ],
        "total": "35000",
        "currency": "COP",
        "confirmed_at": AT.isoformat(),
        "collected": {"direccion": "Calle 10 # 5-20"},
        "source_message_id": "wamid.9",
        "engine_version": ENGINE_VERSION,
    }


def test_unconfirmed_or_empty_handoffs_record_nothing() -> None:
    assert order_record_from_handoff(_summary(order_confirmed=False), confirmed_at=AT) is None
    assert order_record_from_handoff(_summary(order_confirmed="true"), confirmed_at=AT) is None
    assert order_record_from_handoff(_summary(order=[]), confirmed_at=AT) is None
    context: dict[str, Any] = {}
    assert record_confirmed_order(context, _summary(order=[]), confirmed_at=AT) is False
    assert context == {}


def test_recording_the_same_confirmation_twice_keeps_the_first() -> None:
    context: dict[str, Any] = {"order": []}
    assert record_confirmed_order(context, _summary(), confirmed_at=AT, source_message_id="w.1")
    first = dict(context[CTX_ORDER_RECORD])
    assert not record_confirmed_order(
        context, _summary(), confirmed_at=LATER, source_message_id="w.1"
    )
    assert context[CTX_ORDER_RECORD] == first
    assert context[CTX_ORDER_RECORD]["confirmed_at"] == AT.isoformat()
    assert context["order"] == []  # engine keys are not this function's business


def test_without_a_source_id_the_same_content_is_the_same_record() -> None:
    context: dict[str, Any] = {}
    assert record_confirmed_order(context, _summary(), confirmed_at=AT)
    assert not record_confirmed_order(context, _summary(), confirmed_at=LATER)
    assert context[CTX_ORDER_RECORD]["confirmed_at"] == AT.isoformat()


def test_a_different_confirmation_replaces_the_record() -> None:
    context: dict[str, Any] = {}
    record_confirmed_order(context, _summary(), confirmed_at=AT, source_message_id="w.1")
    new = _summary(
        order=[{"product_id": "p3", "name": "Perro", "qty": 1, "price": "9000", "currency": "COP"}],
        total="9000",
    )
    assert record_confirmed_order(context, new, confirmed_at=LATER, source_message_id="w.7")
    order = read_order(context)
    assert order is not None
    assert [line.product_id for line in order.lines] == ["p3"]
    assert order.confirmed_at == LATER
    assert order.source_message_id == "w.7"


def test_read_order_round_trips_with_decimals() -> None:
    context: dict[str, Any] = {}
    record_confirmed_order(context, _summary(), confirmed_at=AT, source_message_id="w.1")
    order = read_order(context)
    assert order == OrderSummary(
        lines=(
            OrderLine("p1", "Hamburguesa", 2, Decimal("15000"), "COP"),
            OrderLine("p2", "Gaseosa", 1, Decimal("5000"), "COP"),
        ),
        total=Decimal("35000"),
        currency="COP",
        confirmed_at=AT,
        collected={"direccion": "Calle 10 # 5-20"},
        source_message_id="w.1",
    )
    assert order.item_count == 3
    assert order.lines[0].line_total == Decimal("30000")


def test_read_order_is_none_without_a_record_and_tolerates_junk() -> None:
    assert read_order(None) is None
    assert read_order({}) is None
    assert read_order({"order": [{"product_id": "p1"}]}) is None  # the engine's, not a record
    assert read_order({CTX_ORDER_RECORD: "nope"}) is None
    assert read_order({CTX_ORDER_RECORD: {"items": [{"name": "sin id", "qty": 1}]}}) is None
    junk = {
        CTX_ORDER_RECORD: {
            "items": [
                {"product_id": "p1", "name": "Ok", "qty": 1, "unit_price": "x"},
                {"product_id": "p2", "name": "Cero", "qty": 0},
                "not a line",
            ],
            "total": None,
            "confirmed_at": "not a date",
        }
    }
    order = read_order(junk)
    assert order is not None
    assert order.lines == (OrderLine("p1", "Ok", 1, None, None),)
    assert order.total == Decimal("0")
    assert order.confirmed_at is None


def test_order_ready_text() -> None:
    context: dict[str, Any] = {}
    record_confirmed_order(context, _summary(), confirmed_at=AT)
    order = read_order(context)
    assert order is not None
    assert order_ready_text(order) == (
        "¡Tu pedido está listo!\n"
        "\n"
        "2 x Hamburguesa — COP 30.000\n"
        "1 x Gaseosa — COP 5.000\n"
        "\n"
        "Total: COP 35.000\n"
        "Gracias por tu pedido."
    )
    assert order_ready_text(order).startswith(ORDER_READY_HEADLINE)


def test_order_ready_text_omits_the_amount_of_unpriced_lines() -> None:
    order = OrderSummary(
        lines=(OrderLine("p1", "Salsa", 1), OrderLine("p2", "Agua", 2, Decimal("2500.50"))),
        total=Decimal("5001"),
        currency="COP",
    )
    text = order_ready_text(order)
    assert "1 x Salsa\n" in text
    assert "2 x Agua — COP 5.001\n" in text
    assert "Total: COP 5.001" in text
