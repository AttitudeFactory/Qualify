"""The structured order a person receives: a confirmed menu order (WA-15, QUA-214) or a
cart the customer sent from the WhatsApp catalog (m-25018684).

## One current order per thread

A thread has at most ONE current order, under the reserved key `CTX_ORDER_RECORD`
(`"_order"`) of `whatsapp_thread_state.context`. Two paths write it:

- **The menu.** The engine builds the order in `context["order"]` and, on «Confirmar»,
  ends in a `handoff` whose `Handoff.summary` carries `{order, total, currency,
  order_confirmed, collected, node_id, engine_version}`; the WA-07 handler turns it into
  the record with `record_confirmed_order`.
- **The catalog cart.** A `messages[].type = "order"` webhook (the customer tapped
  «Enviar al negocio» in WhatsApp's own cart) becomes the record with
  `record_cart_order`. The automation answers nothing: the thread is handed to a person.

The record (a menu record has no `source` key and none of the cart-only keys):

    {"items": [{"product_id", "name", "qty", "unit_price", "currency",
                # cart only:
                "retailer_id", "linked", "price_mismatch",
                "gallery_unit_price", "gallery_currency"}],      # the last two on a mismatch
     "total": "35000.00", "currency": "COP",
     "confirmed_at": "2026-10-14T12:00:00+00:00",
     "collected": {"direccion": "Calle 10 # 5-20"},
     "source_message_id": "wamid....", "engine_version": "wa-menu-engine-0.1.0",
     # cart only:
     "source": "cart", "catalog_id": "1948…", "note": "the customer's text" | None,
     "totals": {"COP": "…", "USD": "…"},          # only when the cart mixes currencies
     "lines_truncated": true, "note_truncated": true}   # only when something was cut

Money is stored as decimal strings (the context is jsonb) and read back as `Decimal`.
`source_message_id` (the inbound `wamid` that confirmed, or the cart message itself) and
`engine_version` (`ENGINE_VERSION` of the menu, `CART_ENGINE_VERSION` for a cart) are the
record's provenance. No `messages` row is written for it: the chat UI reads the record
with `read_order`, renders the order card, and offers `order_ready_text` as the «Pedido
listo» quick reply (free-form text, so only inside the 24 h window).

**A cart line.** Meta sends `product_retailer_id`, `quantity`, `item_price`, `currency`
— never a product name. In the catalog Qualify uploads (ADR 48) the retailer id is the
`brand_products.id`, so the handler looks the ids that parse as UUIDs up among the
products of the brand the receiving number belongs to (`whatsapp.catalog.
load_cart_products_for_phone`) and passes what it found here. A found product is
`linked`: `product_id` is its id, `name` its Galería name, and `price_mismatch` says the
cart's price or currency differs from Galería's at the moment of recording (a Galería
price or currency that is not set is never a difference); a flagged line also stores
the Galería price it was compared to (`gallery_unit_price`, `gallery_currency`).
Anything else is not linked: `product_id` is the raw retailer id, `name` is empty (the
UI words it), `retailer_id` keeps the raw value either way. The cart's own prices are
the truth (`item_price × quantity`, never Galería's). A line is skipped unless its
quantity is an integer in 1–`MAX_CART_QTY` and its price is finite, above zero and at
most `MAX_CART_PRICE` (rounded to the cent). At most `MAX_CART_LINES` lines and
`MAX_NOTE_CHARS` of note are kept; the record then says `lines_truncated` /
`note_truncated`. Readers skip a stored value beyond sane bounds instead of raising.
**Mixed currencies** are never added together: `total` is `"0"`, `currency` is `None`
and `totals` carries one decimal string per currency (`""` for a line without one);
`OrderSummary.totals_by_currency` / `mixed_currency` expose it.

**Idempotent per message.** Both writers key on `source_message_id`: the same
confirmation (or the same cart delivered twice) keeps the first record and its
`confirmed_at` (for a cart: the message's timestamp). `recorded_order_message_ids` also
covers the archive, so a late replay of an older cart never displaces a newer order.

**No order is overwritten without a trace.** When a confirmation from a different
message replaces the current order, the previous record first moves to the reserved
key `CTX_PREVIOUS_ORDERS` (`"_orders_previous"`): a list, newest first, capped at
`MAX_PREVIOUS_ORDERS`, each entry `{"order": <record>, "archived_at": iso, "payment":
<the `_payment` record as it stood, or null>}`. The payment snapshot is kept only when
that `_payment` belonged to the archived order (`order_message_id` ==
`source_message_id`); the handler's save re-takes it from the row as stored, in the
same statement (`repository.save_thread_state(archive_payment=True)`), and the current
`_payment` is never carried over to the new order. `read_previous_orders` reads the
archive; `cart_message_ids` names the inbound messages whose cart is still on record
(current or archived), so the chat can tie a cart bubble to its order.

After a confirmed handoff the handler also clears the engine's working order (`order`,
`order_confirmed`), so a conversation resumed later starts a new order instead of
appending to — or silently re-confirming — the one already handed over.

Pure: no I/O, no clock (the caller passes every instant).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Final
from uuid import UUID

from qualify_api.whatsapp.menus.engine import format_money

# Reserved keys inside `whatsapp_thread_state.context` (leading `_`: never an engine key).
CTX_ORDER_RECORD: Final = "_order"
CTX_PREVIOUS_ORDERS: Final = "_orders_previous"
MAX_PREVIOUS_ORDERS: Final = 5

SOURCE_MENU: Final = "menu"
SOURCE_CART: Final = "cart"
#: Provenance of a cart record (the pipeline that built it).
CART_ENGINE_VERSION: Final = "wa-native-cart-0.1.0"

ORDER_READY_HEADLINE: Final = "¡Tu pedido está listo!"
ORDER_READY_CLOSING: Final = "Gracias por tu pedido."
#: Bounds of a cart (m-25018684 review): anything outside is not a line we can trust.
MAX_CART_LINES: Final = 100
MAX_NOTE_CHARS: Final = 1000
MAX_CART_QTY: Final = 10_000
MAX_CART_PRICE: Final = Decimal("1E12")
#: Readers skip a stored amount or quantity beyond these (an old or hand-made record),
#: so a card, a caption or «Pedido listo» never raises on it.
_MAX_READ_AMOUNT: Final = Decimal("1E15")
_MAX_READ_QTY: Final = 1_000_000
_CENT: Final = Decimal("0.01")

#: «Pedido listo» line for a cart product that is not in Galería: its catalog code.
UNLINKED_PRODUCT_LABEL: Final = "Producto (código {code})"


@dataclass(frozen=True)
class OrderLine:
    product_id: str
    name: str
    qty: int
    unit_price: Decimal | None = None
    currency: str | None = None
    #: Cart only: the raw `product_retailer_id` Meta sent (`None` on a menu line).
    retailer_id: str | None = None
    #: A Galería product (always for a menu line; a cart line whose id was found).
    linked: bool = True
    #: Cart only: the cart's price/currency differed from Galería's when recorded.
    price_mismatch: bool = False
    #: Cart only, set only with `price_mismatch`: the Galería price it was compared to.
    gallery_unit_price: Decimal | None = None
    gallery_currency: str | None = None

    @property
    def line_total(self) -> Decimal | None:
        return None if self.unit_price is None else self.unit_price * self.qty


@dataclass(frozen=True)
class OrderSummary:
    lines: tuple[OrderLine, ...]
    #: `Decimal("0")` when the order mixes currencies (see `totals_by_currency`).
    total: Decimal
    currency: str | None = None
    confirmed_at: datetime | None = None
    collected: dict[str, Any] = field(default_factory=dict)
    source_message_id: str | None = None
    #: `SOURCE_MENU` (a record without `source`) or `SOURCE_CART`.
    source: str = SOURCE_MENU
    #: Cart only: the WhatsApp catalog id and the customer's note.
    catalog_id: str | None = None
    note: str | None = None
    #: Only for an order that mixes currencies: one total per currency (`""` = none).
    totals_by_currency: dict[str, Decimal] = field(default_factory=dict)
    #: Cart only: more than `MAX_CART_LINES` lines / a note over `MAX_NOTE_CHARS` were cut.
    lines_truncated: bool = False
    note_truncated: bool = False

    @property
    def item_count(self) -> int:
        return sum(line.qty for line in self.lines)

    @property
    def is_cart(self) -> bool:
        return self.source == SOURCE_CART

    @property
    def mixed_currency(self) -> bool:
        return len(self.totals_by_currency) > 1


@dataclass(frozen=True)
class CartProduct:
    """A Galería product a cart line points at, as the handler's lookup returned it."""

    product_id: str
    name: str
    price_amount: Decimal | None = None
    price_currency: str | None = None


@dataclass(frozen=True)
class PreviousPayment:
    """How the payment of an archived order stood when it was replaced."""

    status: str | None
    choice: str
    method_name: str | None = None
    currency: str | None = None
    pay_on_delivery: bool = False
    order_message_id: str | None = None
    confirmed_at: datetime | None = None


@dataclass(frozen=True)
class PreviousOrder:
    order: OrderSummary
    archived_at: datetime | None = None
    payment: PreviousPayment | None = None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _qty(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        qty = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return qty if qty > 0 else None


def _amount(value: Any) -> Decimal | None:
    """A stored money value as the readers take it: `None` beyond `_MAX_READ_AMOUNT`."""
    out = _decimal(value)
    return out if out is not None and abs(out) <= _MAX_READ_AMOUNT else None


def _read_qty(value: Any) -> int | None:
    qty = _qty(value)
    return qty if qty is not None and qty <= _MAX_READ_QTY else None


def _cart_qty(value: Any) -> int | None:
    """A cart quantity: an integer value (`2`, `"2"`, `2.0`) in 1–`MAX_CART_QTY`; `2.9`,
    `"dos"`, `True` are not one."""
    if isinstance(value, bool):
        return None
    number = _decimal(value)
    if number is None or number != number.to_integral_value():
        return None
    qty = int(number)
    return qty if 1 <= qty <= MAX_CART_QTY else None


def _cart_price(value: Any) -> Decimal | None:
    """A cart unit price: finite, above zero, at most `MAX_CART_PRICE`, to the cent."""
    price = _decimal(value)
    if price is None or price <= 0 or price > MAX_CART_PRICE:
        return None
    return price.quantize(_CENT, rounding=ROUND_HALF_UP)


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _currency(value: Any) -> str | None:
    return (value.strip().upper() or None) if isinstance(value, str) else None


def _uuid_text(value: str) -> str | None:
    try:
        return str(UUID(value.strip()))
    except (ValueError, AttributeError):
        return None


# --- the menu record -------------------------------------------------------------------


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


# --- the cart record -------------------------------------------------------------------


def cart_product_ids(items: Sequence[Mapping[str, Any]]) -> tuple[UUID, ...]:
    """The distinct retailer ids of a cart that parse as UUIDs — the only ones that can
    be Galería products (ADR 48 uploads `brand_products.id` as the retailer id)."""
    out: dict[str, UUID] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        raw = item.get("product_retailer_id")
        text = _uuid_text(raw) if isinstance(raw, str) else None
        if text is not None:
            out.setdefault(text, UUID(text))
    return tuple(out.values())


def cart_record(
    *,
    items: Sequence[Mapping[str, Any]],
    products: Mapping[str, CartProduct],
    confirmed_at: datetime,
    source_message_id: str,
    catalog_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any] | None:
    """The `_order` record for a catalog cart, or `None` when no line survives.

    `items` are Meta's `order.product_items` as mappings; `products` is what the
    handler's lookup returned, keyed by the product id as canonical UUID text (only the
    receiving brand's products: an id of another brand or tenant is simply absent)."""
    lines: list[dict[str, Any]] = []
    totals: dict[str, Decimal] = {}
    lines_truncated = False
    for item in items:
        if not isinstance(item, Mapping):
            continue
        raw_id = item.get("product_retailer_id")
        retailer_id = (
            str(raw_id).strip()
            if isinstance(raw_id, str | int) and not isinstance(raw_id, bool)
            else ""
        )
        qty = _cart_qty(item.get("quantity"))
        price = _cart_price(item.get("item_price"))
        if not retailer_id or qty is None or price is None:
            continue
        if len(lines) >= MAX_CART_LINES:
            lines_truncated = True
            break
        currency = _currency(item.get("currency"))
        key = _uuid_text(retailer_id)
        product = products.get(key) if key is not None else None
        if product is not None:
            galeria_price = _amount(product.price_amount)
            galeria_currency = _currency(product.price_currency)
            # A Galería price or currency that is not set is never a difference.
            mismatch = (galeria_price is not None and galeria_price != price) or (
                galeria_currency is not None and galeria_currency != currency
            )
            line = {
                "product_id": product.product_id,
                "name": product.name,
                "linked": True,
                "price_mismatch": mismatch,
            }
            if mismatch:
                line["gallery_unit_price"] = (
                    str(galeria_price) if galeria_price is not None else None
                )
                line["gallery_currency"] = galeria_currency
        else:
            line = {
                "product_id": retailer_id,
                "name": "",
                "linked": False,
                "price_mismatch": False,
            }
        lines.append(
            {
                **line,
                "qty": qty,
                "unit_price": str(price),
                "currency": currency,
                "retailer_id": retailer_id,
            }
        )
        totals[currency or ""] = totals.get(currency or "", Decimal("0")) + price * qty
    if not lines:
        return None
    note_text = (note or "").strip()
    note_truncated = len(note_text) > MAX_NOTE_CHARS
    record: dict[str, Any] = {
        "items": lines,
        "confirmed_at": confirmed_at.isoformat(),
        "collected": {},
        "source_message_id": source_message_id,
        "engine_version": CART_ENGINE_VERSION,
        "source": SOURCE_CART,
        "catalog_id": catalog_id or None,
        "note": note_text[:MAX_NOTE_CHARS] or None,
    }
    if lines_truncated:
        record["lines_truncated"] = True
    if note_truncated:
        record["note_truncated"] = True
    if len(totals) == 1:
        ((currency_key, total),) = totals.items()
        record.update(total=str(total), currency=currency_key or None)
    else:
        record.update(
            total="0",
            currency=None,
            totals={code: str(amount) for code, amount in sorted(totals.items())},
        )
    return record


# --- writing: idempotency and the archive ----------------------------------------------


def recorded_order_message_ids(context: Mapping[str, Any] | None) -> frozenset[str]:
    """Every `source_message_id` of the current order and of the archived ones."""
    out: set[str] = set()
    for record in _records(context):
        source = record.get("source_message_id")
        if isinstance(source, str) and source:
            out.add(source)
    return frozenset(out)


def cart_message_ids(context: Mapping[str, Any] | None) -> frozenset[str]:
    """The inbound `wamid`s of the carts on record (current order + archive), so the chat
    can tie a cart message (`media_type = 'order'`) to its order card."""
    out: set[str] = set()
    for record in _records(context):
        source = record.get("source_message_id")
        if record.get("source") == SOURCE_CART and isinstance(source, str) and source:
            out.add(source)
    return frozenset(out)


def _records(context: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not context:
        return []
    out: list[Mapping[str, Any]] = []
    current = context.get(CTX_ORDER_RECORD)
    if isinstance(current, Mapping):
        out.append(current)
    previous = context.get(CTX_PREVIOUS_ORDERS)
    if isinstance(previous, list):
        for entry in previous:
            if isinstance(entry, Mapping) and isinstance(entry.get("order"), Mapping):
                out.append(entry["order"])
    return out


def payment_belongs_to(payment: Any, order: Mapping[str, Any]) -> bool:
    """`_payment` was written for this order (`order_message_id` == its source)."""
    if not isinstance(payment, Mapping):
        return False
    source = order.get("source_message_id")
    return bool(source) and payment.get("order_message_id") == source


def archive_entry(
    order: Mapping[str, Any], *, archived_at: datetime, payment: Any = None
) -> dict[str, Any]:
    """One `_orders_previous` entry; the payment snapshot only if it was this order's."""
    return {
        "order": dict(order),
        "archived_at": archived_at.isoformat(),
        "payment": dict(payment) if payment_belongs_to(payment, order) else None,
    }


# Compared when no `source_message_id` is known: the same content is the same record.
_CONTENT_KEYS: Final = ("items", "total", "currency", "collected")


def _store(
    context: dict[str, Any],
    record: dict[str, Any],
    *,
    archived_at: datetime,
    payment: Any,
) -> bool:
    existing = context.get(CTX_ORDER_RECORD)
    if isinstance(existing, Mapping):
        source = record.get("source_message_id")
        if source is not None:
            same = existing.get("source_message_id") == source
        else:
            same = all(existing.get(k) == record.get(k) for k in _CONTENT_KEYS)
        if same:
            return False
        previous = context.get(CTX_PREVIOUS_ORDERS)
        kept = [e for e in previous if isinstance(e, Mapping)] if isinstance(previous, list) else []
        entry = archive_entry(existing, archived_at=archived_at, payment=payment)
        context[CTX_PREVIOUS_ORDERS] = [entry, *kept][:MAX_PREVIOUS_ORDERS]
    context[CTX_ORDER_RECORD] = record
    return True


def record_confirmed_order(
    context: dict[str, Any],
    summary: Mapping[str, Any],
    *,
    confirmed_at: datetime,
    source_message_id: str | None = None,
    archived_at: datetime | None = None,
    payment: Any = None,
) -> bool:
    """Store the order of a confirmed handoff under `CTX_ORDER_RECORD` in `context`
    (mutated). Returns `True` when the record was written; `False` when there was nothing
    to record, or this very confirmation is already recorded — same `source_message_id`,
    or, without one, the same content — in which case the stored record (and its
    `confirmed_at`) is kept. A different confirmation replaces the record after moving
    the previous one to `CTX_PREVIOUS_ORDERS` (with `payment`, the thread's `_payment`
    as read, when it was that order's)."""
    record = order_record_from_handoff(
        summary, confirmed_at=confirmed_at, source_message_id=source_message_id
    )
    if record is None:
        return False
    return _store(context, record, archived_at=archived_at or confirmed_at, payment=payment)


def record_cart_order(
    context: dict[str, Any],
    *,
    items: Sequence[Mapping[str, Any]],
    products: Mapping[str, CartProduct],
    confirmed_at: datetime,
    source_message_id: str,
    archived_at: datetime,
    catalog_id: str | None = None,
    note: str | None = None,
    payment: Any = None,
) -> bool:
    """Store a catalog cart as the thread's current order (`context` mutated). `False`
    when no line survives, or this cart (`source_message_id`) is already recorded —
    current or archived. Otherwise archives the current order (see the module docs)."""
    if source_message_id in recorded_order_message_ids(context):
        return False
    record = cart_record(
        items=items,
        products=products,
        confirmed_at=confirmed_at,
        source_message_id=source_message_id,
        catalog_id=catalog_id,
        note=note,
    )
    if record is None:
        return False
    return _store(context, record, archived_at=archived_at, payment=payment)


# --- reading ---------------------------------------------------------------------------


def _summary_from_record(record: Any) -> OrderSummary | None:
    if not isinstance(record, Mapping):
        return None
    lines: list[OrderLine] = []
    for item in record.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        qty = _read_qty(item.get("qty"))
        product_id = item.get("product_id")
        if qty is None or not product_id:
            continue
        retailer_id = item.get("retailer_id")
        linked = item.get("linked")
        mismatch = item.get("price_mismatch") is True
        gallery_currency = item.get("gallery_currency") if mismatch else None
        lines.append(
            OrderLine(
                product_id=str(product_id),
                name=str(item.get("name") or ""),
                qty=qty,
                unit_price=_amount(item.get("unit_price")),
                currency=item.get("currency") or None,
                retailer_id=str(retailer_id) if retailer_id else None,
                linked=linked if isinstance(linked, bool) else True,
                price_mismatch=mismatch,
                gallery_unit_price=_amount(item.get("gallery_unit_price")) if mismatch else None,
                gallery_currency=(
                    gallery_currency
                    if isinstance(gallery_currency, str) and gallery_currency
                    else None
                ),
            )
        )
    if not lines:
        return None
    collected = record.get("collected")
    source_id = record.get("source_message_id")
    source = record.get("source")
    totals: dict[str, Decimal] = {}
    raw_totals = record.get("totals")
    if isinstance(raw_totals, Mapping):
        for code, amount in raw_totals.items():
            value = _amount(amount)
            if isinstance(code, str) and value is not None:
                totals[code] = value
    catalog_id = record.get("catalog_id")
    note = record.get("note")
    return OrderSummary(
        lines=tuple(lines),
        total=_amount(record.get("total")) or Decimal("0"),
        currency=record.get("currency") or None,
        confirmed_at=_when(record.get("confirmed_at")),
        collected=dict(collected) if isinstance(collected, Mapping) else {},
        source_message_id=source_id if isinstance(source_id, str) else None,
        source=source if source == SOURCE_CART else SOURCE_MENU,
        catalog_id=catalog_id if isinstance(catalog_id, str) and catalog_id else None,
        note=note if isinstance(note, str) and note else None,
        totals_by_currency=totals if len(totals) > 1 else {},
        lines_truncated=record.get("lines_truncated") is True,
        note_truncated=record.get("note_truncated") is True,
    )


def read_order(context: Mapping[str, Any] | None) -> OrderSummary | None:
    """The thread's current order, or `None` when there is none (or the stored value is
    not an order record). Tolerant: a malformed line is skipped, never raised on — this
    feeds a UI card. A record written before carts existed reads exactly as before."""
    if not context:
        return None
    return _summary_from_record(context.get(CTX_ORDER_RECORD))


def _previous_payment(raw: Any) -> PreviousPayment | None:
    if not isinstance(raw, Mapping):
        return None
    status = raw.get("status")
    name = raw.get("name")
    currency = raw.get("currency")
    order_message_id = raw.get("order_message_id")
    return PreviousPayment(
        status=status if isinstance(status, str) and status else None,
        choice=str(raw.get("choice") or "none"),
        method_name=name if isinstance(name, str) and name else None,
        currency=currency if isinstance(currency, str) and currency else None,
        pay_on_delivery=raw.get("pay_on_delivery") is True,
        order_message_id=order_message_id if isinstance(order_message_id, str) else None,
        confirmed_at=_when(raw.get("confirmed_at")),
    )


def read_previous_orders(context: Mapping[str, Any] | None) -> tuple[PreviousOrder, ...]:
    """The archived orders, newest first (at most `MAX_PREVIOUS_ORDERS`). Tolerant: an
    entry that does not read as an order is skipped."""
    raw = (context or {}).get(CTX_PREVIOUS_ORDERS)
    if not isinstance(raw, list):
        return ()
    out: list[PreviousOrder] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        order = _summary_from_record(entry.get("order"))
        if order is None:
            continue
        out.append(
            PreviousOrder(
                order=order,
                archived_at=_when(entry.get("archived_at")),
                payment=_previous_payment(entry.get("payment")),
            )
        )
    return tuple(out)


def order_ready_text(order: OrderSummary) -> str:
    """The «Pedido listo» quick reply: headline, one line per product, the total. A cart
    product not in Galería is named by its catalog code; an order in several currencies
    gets one amount per currency."""
    out = [ORDER_READY_HEADLINE, ""]
    for line in order.lines:
        name = line.name
        if not line.linked and not name:
            name = UNLINKED_PRODUCT_LABEL.format(code=line.retailer_id or line.product_id)
        text = f"{line.qty} x {name}"
        if line.line_total is not None:
            text += f" — {format_money(line.line_total, line.currency or order.currency)}"
        out.append(text)
    if order.mixed_currency:
        total = " + ".join(
            format_money(amount, code or None) for code, amount in order.totals_by_currency.items()
        )
    else:
        total = format_money(order.total, order.currency)
    out += ["", f"Total: {total}", ORDER_READY_CLOSING]
    return "\n".join(out)


__all__ = [
    "CART_ENGINE_VERSION",
    "CTX_ORDER_RECORD",
    "CTX_PREVIOUS_ORDERS",
    "MAX_PREVIOUS_ORDERS",
    "ORDER_READY_CLOSING",
    "ORDER_READY_HEADLINE",
    "SOURCE_CART",
    "SOURCE_MENU",
    "UNLINKED_PRODUCT_LABEL",
    "CartProduct",
    "OrderLine",
    "OrderSummary",
    "PreviousOrder",
    "PreviousPayment",
    "archive_entry",
    "cart_message_ids",
    "cart_product_ids",
    "cart_record",
    "order_ready_text",
    "order_record_from_handoff",
    "payment_belongs_to",
    "read_order",
    "read_previous_orders",
    "record_cart_order",
    "record_confirmed_order",
    "recorded_order_message_ids",
]
