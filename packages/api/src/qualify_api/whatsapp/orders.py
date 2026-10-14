"""The structured order a person receives when the menu hands a confirmed order over
(WA-15, QUA-214).

The menu engine builds the order in `context["order"]` and, on «Confirmar», ends in a
`handoff` whose `Handoff.summary` carries `{order, total, currency, order_confirmed,
collected, node_id, engine_version}`. The WA-07 handler turns that summary into ONE
record under the reserved key `CTX_ORDER_RECORD` (`"_order"`) of
`whatsapp_thread_state.context`:

    {"items": [{"product_id", "name", "qty", "unit_price", "currency"}],
     "total": "35000.00", "currency": "COP",
     "confirmed_at": "2026-10-14T12:00:00+00:00",
     "collected": {"direccion": "Calle 10 # 5-20"},
     "source_message_id": "wamid....", "engine_version": "wa-menu-engine-0.1.0"}

Money is stored as decimal strings (the context is jsonb) and read back as `Decimal`.
`source_message_id` (the inbound `wamid` whose step confirmed) and `engine_version` are
the record's provenance. No `messages` row is written for it: the chat UI reads the
record with `read_order`, renders the order card at the top of the thread, and offers
`order_ready_text` as the «Pedido listo» quick reply (a free-form text, so it only goes
out inside the 24 h window).

**Idempotent per handoff.** `record_confirmed_order` keys on `source_message_id`: the same
confirmation recorded twice keeps the first record and its `confirmed_at`; a different
confirmation replaces it (one current order per thread — the previous one was already
handed to a person). After a confirmed handoff the handler also clears the engine's
working order (`order`, `order_confirmed`), so a conversation resumed later starts a new
order instead of appending to — or silently re-confirming — the one already handed over.

Pure: no I/O, no clock (the caller passes `confirmed_at`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from qualify_api.whatsapp.menus.engine import format_money

# Reserved key inside `whatsapp_thread_state.context` (leading `_`: never an engine key).
CTX_ORDER_RECORD: Final = "_order"

ORDER_READY_HEADLINE: Final = "¡Tu pedido está listo!"
ORDER_READY_CLOSING: Final = "Gracias por tu pedido."


@dataclass(frozen=True)
class OrderLine:
    product_id: str
    name: str
    qty: int
    unit_price: Decimal | None = None
    currency: str | None = None

    @property
    def line_total(self) -> Decimal | None:
        return None if self.unit_price is None else self.unit_price * self.qty


@dataclass(frozen=True)
class OrderSummary:
    lines: tuple[OrderLine, ...]
    total: Decimal
    currency: str | None = None
    confirmed_at: datetime | None = None
    collected: dict[str, Any] = field(default_factory=dict)
    source_message_id: str | None = None

    @property
    def item_count(self) -> int:
        return sum(line.qty for line in self.lines)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _qty(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        qty = int(value)
    except (TypeError, ValueError):
        return None
    return qty if qty > 0 else None


def order_record_from_handoff(
    summary: Mapping[str, Any],
    *,
    confirmed_at: datetime,
    source_message_id: str | None = None,
) -> dict[str, Any] | None:
    """The `_order` record for a handoff summary, or `None` when the handoff does not
    carry a confirmed, non-empty order (a «hablar con una persona» handoff, an
    unknown-input handoff, an order confirmed with nothing in it). `source_message_id`
    is the `wamid` of the inbound message whose step produced the handoff."""
    if summary.get("order_confirmed") is not True:
        return None
    items: list[dict[str, Any]] = []
    for line in summary.get("order") or []:
        if not isinstance(line, Mapping):
            continue
        qty = _qty(line.get("qty", 1))
        product_id = line.get("product_id")
        if qty is None or not product_id:
            continue
        price = _decimal(line.get("price"))
        items.append(
            {
                "product_id": str(product_id),
                "name": str(line.get("name") or ""),
                "qty": qty,
                "unit_price": str(price) if price is not None else None,
                "currency": line.get("currency") or None,
            }
        )
    if not items:
        return None
    total = _decimal(summary.get("total")) or Decimal("0")
    collected = summary.get("collected")
    return {
        "items": items,
        "total": str(total),
        "currency": summary.get("currency") or None,
        "confirmed_at": confirmed_at.isoformat(),
        "collected": dict(collected) if isinstance(collected, Mapping) else {},
        "source_message_id": source_message_id,
        "engine_version": summary.get("engine_version"),
    }


# Compared when no `source_message_id` is known: the same content is the same record.
_CONTENT_KEYS: Final = ("items", "total", "currency", "collected")


def record_confirmed_order(
    context: dict[str, Any],
    summary: Mapping[str, Any],
    *,
    confirmed_at: datetime,
    source_message_id: str | None = None,
) -> bool:
    """Store the order of a confirmed handoff under `CTX_ORDER_RECORD` in `context`
    (mutated). Returns `True` when the record was written; `False` when there was nothing
    to record, or this very confirmation is already recorded — same `source_message_id`,
    or, without one, the same content — in which case the stored record (and its
    `confirmed_at`) is kept. A different confirmation replaces the record."""
    record = order_record_from_handoff(
        summary, confirmed_at=confirmed_at, source_message_id=source_message_id
    )
    if record is None:
        return False
    existing = context.get(CTX_ORDER_RECORD)
    if isinstance(existing, Mapping):
        if source_message_id is not None:
            same = existing.get("source_message_id") == source_message_id
        else:
            same = all(existing.get(k) == record[k] for k in _CONTENT_KEYS)
        if same:
            return False
    context[CTX_ORDER_RECORD] = record
    return True


def read_order(context: Mapping[str, Any] | None) -> OrderSummary | None:
    """The confirmed order stored in a thread's context, or `None` when there is none
    (or the stored value is not an order record). Tolerant: a malformed line is skipped,
    never raised on — this feeds a UI card."""
    if not context:
        return None
    record = context.get(CTX_ORDER_RECORD)
    if not isinstance(record, Mapping):
        return None
    lines: list[OrderLine] = []
    for item in record.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        qty = _qty(item.get("qty"))
        product_id = item.get("product_id")
        if qty is None or not product_id:
            continue
        lines.append(
            OrderLine(
                product_id=str(product_id),
                name=str(item.get("name") or ""),
                qty=qty,
                unit_price=_decimal(item.get("unit_price")),
                currency=item.get("currency") or None,
            )
        )
    if not lines:
        return None
    confirmed_at: datetime | None = None
    raw_at = record.get("confirmed_at")
    if isinstance(raw_at, str):
        try:
            confirmed_at = datetime.fromisoformat(raw_at)
        except ValueError:
            confirmed_at = None
    collected = record.get("collected")
    source = record.get("source_message_id")
    return OrderSummary(
        lines=tuple(lines),
        total=_decimal(record.get("total")) or Decimal("0"),
        currency=record.get("currency") or None,
        confirmed_at=confirmed_at,
        collected=dict(collected) if isinstance(collected, Mapping) else {},
        source_message_id=source if isinstance(source, str) else None,
    )


def order_ready_text(order: OrderSummary) -> str:
    """The «Pedido listo» quick reply: headline, one line per product, the total."""
    out = [ORDER_READY_HEADLINE, ""]
    for line in order.lines:
        text = f"{line.qty} x {line.name}"
        if line.line_total is not None:
            text += f" — {format_money(line.line_total, line.currency or order.currency)}"
        out.append(text)
    out += ["", f"Total: {format_money(order.total, order.currency)}", ORDER_READY_CLOSING]
    return "\n".join(out)


__all__ = [
    "CTX_ORDER_RECORD",
    "ORDER_READY_CLOSING",
    "ORDER_READY_HEADLINE",
    "OrderLine",
    "OrderSummary",
    "order_ready_text",
    "order_record_from_handoff",
    "read_order",
    "record_confirmed_order",
]
