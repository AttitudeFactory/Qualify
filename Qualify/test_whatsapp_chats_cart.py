"""The WhatsApp catalog cart in the Chats tab (m-25018684): the order card of a cart,
the «Pedidos anteriores» section and the cart's bubble — pure view-model tests over the
backend's own reader (`qualify_api.whatsapp.orders`), no Reflex, no Postgres."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from qualify_api.whatsapp.chats import MessageRecord
from qualify_api.whatsapp.orders import (
    cart_message_ids,
    read_order,
    read_previous_orders,
)

from . import whatsapp_chats_vm as vm_module
from .whatsapp_chats_vm import (
    CART_BUBBLE_NO_DETAIL,
    CART_CHARGE_HINT,
    CUSTOMER_NOTE_LABEL,
    ORDER_TITLE_CART,
    ORDER_TITLE_MENU,
    ORDER_TRUNCATED_LINE,
    PRICE_MISMATCH_LINE,
    UNLINKED_PRODUCT_NAME,
    OrderCardVM,
    OrderFieldVM,
    PreviousOrderVM,
    build_conversation,
    build_message_vm,
    build_order_card,
    cart_details,
    previous_orders_label,
    price_mismatch_notice,
    short_code,
    split_note,
    unlinked_notice,
)

ZONE = ZoneInfo("America/Bogota")
NOW = datetime(2026, 11, 13, 20, 0, tzinfo=UTC)  # 15:00 in Bogotá
PRODUCT = "8c1d1f7e-0000-4000-8000-000000000001"


def _cart(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "items": [
            {
                "product_id": PRODUCT,
                "name": "Shawarma mixto",
                "qty": 2,
                "unit_price": "12000",
                "currency": "COP",
                "retailer_id": PRODUCT,
                "linked": True,
                "price_mismatch": True,
            },
            {
                "product_id": "ABC123",
                "name": "",
                "qty": 1,
                "unit_price": "21000",
                "currency": "COP",
                "retailer_id": "ABC123",
                "linked": False,
                "price_mismatch": False,
            },
        ],
        "total": "45000",
        "currency": "COP",
        "confirmed_at": "2026-11-13T19:42:00+00:00",
        "collected": {},
        "source_message_id": "wamid.cart",
        "engine_version": "wa-native-cart-0.1.0",
        "source": "cart",
        "catalog_id": "1948",
        "note": "Sin cebolla, porfa",
    }
    record.update(overrides)
    return record


_MENU = {
    "items": [
        {"product_id": "p1", "name": "Ensalada César", "qty": 1, "unit_price": "18000"},
        {"product_id": "p2", "name": "Limonada", "qty": 2, "unit_price": "6000"},
    ],
    "total": "30000",
    "currency": "COP",
    "confirmed_at": "2026-11-13T00:05:00+00:00",  # ayer 19:05 in Bogotá
    "collected": {"direccion": "Calle 10 # 5-20"},
    "source_message_id": "wamid.menu",
}


def _card(context: dict[str, Any], *, has_payment: bool = False):  # type: ignore[no-untyped-def]
    return build_order_card(
        read_order(context),
        now=NOW,
        zone=ZONE,
        previous=read_previous_orders(context),
        has_payment=has_payment,
    )


# --- the cart's card -----------------------------------------------------------------


def test_cart_card_title_time_and_lines() -> None:
    card = _card({"_order": _cart()})
    assert card.present and card.is_cart
    assert card.title == ORDER_TITLE_CART == "Pedido desde tu catálogo"
    assert card.confirmed_label == "Llegó 14:42"
    assert card.items_label == "3 productos"
    assert card.total_label == "COP 45.000"
    linked, unlinked = card.lines
    assert (linked.label, linked.amount, linked.code) == ("2 × Shawarma mixto", "COP 24.000", "")
    assert linked.price_note == PRICE_MISMATCH_LINE
    assert unlinked.label == f"1 × {UNLINKED_PRODUCT_NAME}"
    assert (unlinked.amount, unlinked.code, unlinked.price_note) == ("COP 21.000", "ABC123", "")


def test_cart_unlinked_line_never_shows_the_code_as_its_name() -> None:
    card = _card({"_order": _cart()})
    assert all("ABC123" not in line.label for line in card.lines)


def test_price_notice_singular_and_plural() -> None:
    assert price_mismatch_notice(0) == ""
    assert price_mismatch_notice(1) == (
        "El precio de 1 producto en tu catálogo de WhatsApp no es el de tu Galería. "
        "El total usa el precio que vio tu cliente."
    )
    assert price_mismatch_notice(2).startswith("El precio de 2 productos en tu catálogo")
    one = _card({"_order": _cart()})
    assert one.price_notice == price_mismatch_notice(1)
    items = _cart()["items"]
    both = [items[0], {**items[1], "linked": True, "name": "Falafel", "price_mismatch": True}]
    assert _card({"_order": _cart(items=both)}).price_notice == price_mismatch_notice(2)
    clean = [{**items[0], "price_mismatch": False}, items[1]]
    card = _card({"_order": _cart(items=clean)})
    assert card.price_notice == "" and all(line.price_note == "" for line in card.lines)


def test_price_mark_names_the_galeria_price_when_the_record_has_it() -> None:
    items = _cart()["items"]
    priced = {**items[0], "gallery_unit_price": "10000", "gallery_currency": "COP"}
    card = _card({"_order": _cart(items=[priced, items[1]])})
    # 2 × …: a unit price under a line total says «cada uno».
    assert card.lines[0].price_note == "En tu Galería: COP 10.000 cada uno"
    single = {**priced, "qty": 1}
    card = _card({"_order": _cart(items=[single, items[1]])})
    assert card.lines[0].price_note == "En tu Galería: COP 10.000"
    # Only the currency differs (no Galería price kept): the mark without an amount.
    no_price = {**items[0], "gallery_unit_price": None, "gallery_currency": "USD"}
    card = _card({"_order": _cart(items=[no_price, items[1]])})
    assert card.lines[0].price_note == PRICE_MISMATCH_LINE


def test_customer_note_is_its_own_block_as_written() -> None:
    card = _card({"_order": _cart(note="<b>Sin cebolla</b>\nTimbre 2")})
    assert (card.note, card.note_rest) == ("<b>Sin cebolla</b>\nTimbre 2", "")
    assert card.collected == []
    assert CUSTOMER_NOTE_LABEL == "Nota del cliente"
    assert _card({"_order": _cart(note=None)}).note == ""
    assert _card({"_order": _MENU}).note == ""


def test_a_long_note_shows_its_start_and_folds_the_rest() -> None:
    lines = "Uno\nDos\nTres\nCuatro\nCinco"
    shown, rest = split_note(lines)
    assert (shown, rest) == ("Uno\nDos\nTres…", "Cuatro\nCinco")
    long = "palabra " * 40
    shown, rest = split_note(long.strip())
    assert shown.endswith("…") and len(shown) <= 161
    assert (shown[:-1] + " " + rest).split() == long.split()
    assert split_note("Sin cebolla") == ("Sin cebolla", "")
    card = _card({"_order": _cart(note=lines)})
    assert (card.note, card.note_rest) == ("Uno\nDos\nTres…", "Cuatro\nCinco")


def test_mixed_currencies_show_one_amount_per_currency() -> None:
    items = _cart()["items"]
    mixed = [items[0], {**items[1], "currency": "USD", "unit_price": "10"}]
    context = {
        "_order": _cart(items=mixed, total="0", currency=None, totals={"COP": "24000", "USD": "10"})
    }
    card = _card(context)
    assert card.total_label == "COP 24.000 + USD 10"
    assert card.lines[1].amount == "USD 10"


def test_charge_hint_only_for_a_cart_without_payment() -> None:
    assert _card({"_order": _cart()}).charge_hint == CART_CHARGE_HINT
    assert _card({"_order": _cart()}, has_payment=True).charge_hint == ""
    assert _card({"_order": _MENU}).charge_hint == ""


def test_truncated_cart_says_so() -> None:
    assert _card({"_order": _cart()}).truncated_line == ""
    card = _card({"_order": _cart(lines_truncated=True)})
    assert card.truncated_line == ORDER_TRUNCATED_LINE
    assert ORDER_TRUNCATED_LINE == "Este pedido es muy largo: mostramos los primeros 100 productos."


def test_a_cut_note_ends_with_an_ellipsis() -> None:
    card = _card({"_order": _cart(note="Sin cebolla", note_truncated=True)})
    assert card.note == "Sin cebolla…"
    assert card.truncated_line == ""


# --- the menu order is unchanged -----------------------------------------------------


def test_menu_order_card_reads_as_before() -> None:
    card = _card({"_order": _MENU}, has_payment=False)
    assert (card.title, card.is_cart) == (ORDER_TITLE_MENU, False)
    assert card.confirmed_label == "Confirmado ayer 19:05"
    assert [(line.label, line.amount, line.code, line.price_note) for line in card.lines] == [
        ("1 × Ensalada César", "COP 18.000", "", ""),
        ("2 × Limonada", "COP 12.000", "", ""),
    ]
    assert card.total_label == "COP 30.000"
    assert card.collected == [OrderFieldVM(label="Dirección", value="Calle 10 # 5-20")]
    assert (card.price_notice, card.charge_hint, card.truncated_line) == ("", "", "")
    assert (card.note, card.note_rest, card.unlinked_notice) == ("", "", "")
    assert (card.previous, card.previous_label) == ([], "")


# --- previous orders -----------------------------------------------------------------


def _entry(order: dict[str, Any], payment: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"order": order, "archived_at": "2026-11-13T19:42:00+00:00", "payment": payment}


def test_no_previous_orders() -> None:
    card = _card({"_order": _cart()})
    assert (card.previous, card.previous_label) == ([], "")


def test_one_previous_order_with_its_payment_word() -> None:
    payment = {"status": "received", "choice": "method", "order_message_id": "wamid.menu"}
    card = _card({"_order": _cart(), "_orders_previous": [_entry(_MENU, payment)]})
    assert card.previous_label == "1 pedido anterior"
    assert card.previous == [
        PreviousOrderVM(
            origin_label="Por el menú · ayer 19:05",
            items_line="1 × Ensalada César, 2 × Limonada",
            summary_label="3 productos · COP 30.000",
            payment_label="Pago recibido",
            payment_tone="ok",
        )
    ]


def test_many_previous_orders_newest_first_and_payment_words() -> None:
    older_cart = _cart(source_message_id="wamid.old", confirmed_at="2026-11-13T15:00:00+00:00")
    entries = [
        _entry(older_cart, {"status": "review", "choice": "method"}),
        _entry(_MENU, {"status": "awaiting", "choice": "method"}),
        _entry(_MENU, {"status": "on_delivery", "choice": "method"}),
        _entry(_MENU, {"status": None, "choice": "other"}),
        _entry(_MENU, None),
    ]
    card = _card({"_order": _cart(), "_orders_previous": entries})
    assert card.previous_label == "5 pedidos anteriores · 1 pago por revisar"
    assert card.previous[0].origin_label == "Desde tu catálogo · 10:00"
    assert card.previous[0].items_line == "2 × Shawarma mixto, 1 × Producto sin nombre"
    assert [(p.payment_label, p.payment_tone) for p in card.previous] == [
        ("Pago por revisar", "warn"),
        ("Esperando el pago", "neutral"),
        ("Paga al recibir", "neutral"),
        ("", "neutral"),
        ("", "neutral"),
    ]


def test_previous_orders_label_words() -> None:
    assert previous_orders_label(0) == ""
    assert previous_orders_label(1) == "1 pedido anterior"
    assert previous_orders_label(3) == "3 pedidos anteriores"
    assert previous_orders_label(2, review=1, awaiting=1) == (
        "2 pedidos anteriores · 1 pago por revisar"
    )
    assert previous_orders_label(3, review=2) == "3 pedidos anteriores · 2 pagos por revisar"
    assert previous_orders_label(1, awaiting=1) == "1 pedido anterior · 1 esperando el pago"
    assert previous_orders_label(3, awaiting=2) == "3 pedidos anteriores · 2 esperando el pago"


def test_the_closed_row_names_an_awaiting_payment() -> None:
    entries = [_entry(_MENU, {"status": "awaiting"}), _entry(_MENU, {"status": "received"})]
    card = _card({"_order": _cart(), "_orders_previous": entries})
    assert card.previous_label == "2 pedidos anteriores · 1 esperando el pago"


def _walk(component: Any) -> list[Any]:
    out = [component]
    for child in getattr(component, "children", []) or []:
        out.extend(_walk(child))
    return out


def test_previous_orders_render_without_any_action() -> None:
    from .whatsapp_chats_state import WhatsAppChatsState
    from .whatsapp_tab_chats import _previous_order

    tree = _walk(_previous_order(WhatsAppChatsState.order.previous[0]))
    assert len(tree) > 3
    assert all(not getattr(c, "event_triggers", None) for c in tree)


def test_previous_orders_are_read_only() -> None:
    names = set(PreviousOrderVM.__dataclass_fields__)
    assert names == {
        "origin_label",
        "items_line",
        "summary_label",
        "payment_label",
        "payment_tone",
    }


# --- the cart's bubble ---------------------------------------------------------------


def test_unlinked_lines_are_named_by_pedido_listo() -> None:
    assert unlinked_notice(0) == ""
    assert unlinked_notice(1) == (
        "Un producto no está en tu Galería: en el mensaje saldrá con su código."
    )
    assert unlinked_notice(2) == (
        "2 productos no están en tu Galería: en el mensaje saldrán con su código."
    )
    assert _card({"_order": _cart()}).unlinked_notice == unlinked_notice(1)


def test_a_long_code_is_shortened_for_display() -> None:
    assert short_code("ABC123") == "ABC123"
    assert short_code("x" * 64) == "x" * 64
    assert short_code("x" * 300) == "x" * 64 + "…"
    items = _cart()["items"]
    long = {**items[1], "product_id": "y" * 200, "retailer_id": "y" * 200}
    assert _card({"_order": _cart(items=[items[0], long])}).lines[1].code == "y" * 64 + "…"


_BANNED = re.compile(
    r"\bSKU\b|\bID\b|\bpost\b|sincroniz|\b(?:cart|order|item|price|check|link|code)\b",
    re.IGNORECASE,
)


def test_new_copy_speaks_plain_spanish() -> None:
    texts = [
        value
        for name in (
            "ORDER_TITLE_MENU",
            "ORDER_TITLE_CART",
            "UNLINKED_PRODUCT_NAME",
            "UNLINKED_CODE_LABEL",
            "PRICE_MISMATCH_LINE",
            "PRICE_MISMATCH_AMOUNT",
            "PRICE_MISMATCH_AMOUNT_EACH",
            "ORDER_TRUNCATED_LINE",
            "PRICE_MISMATCH_LINK",
            "CUSTOMER_NOTE_LABEL",
            "NOTE_MORE_LABEL",
            "CART_CHARGE_HINT",
            "PREVIOUS_FROM_CART",
            "PREVIOUS_FROM_MENU",
            "CART_BUBBLE",
            "CART_BUBBLE_NO_DETAIL",
        )
        for value in [getattr(vm_module, name)]
    ]
    texts += [price_mismatch_notice(2), unlinked_notice(2), previous_orders_label(2, review=2)]
    for text in texts:
        words = re.sub(r"\{\w+\}", "", text)  # format slots are not copy
        assert not _BANNED.search(words), text


def _cart_message(wamid: str = "wamid.cart", **overrides: Any) -> MessageRecord:
    values: dict[str, Any] = {
        "id": uuid4(),
        "direction": "inbound",
        "text": None,
        "posted_at": NOW - timedelta(minutes=18),
        "delivery_status": None,
        "delivery_error_code": None,
        "external_message_id": wamid,
        "media_kind": "order",
    }
    values.update(overrides)
    return MessageRecord(**values)


def _carts(context: dict[str, Any]) -> dict[str, str]:
    return cart_details(
        read_order(context), read_previous_orders(context), cart_message_ids(context)
    )


def test_cart_bubble_with_detail() -> None:
    context = {
        "_order": _cart(),
        "_orders_previous": [_entry(_cart(source_message_id="wamid.old")), _entry(_MENU)],
    }
    carts = _carts(context)
    assert carts == {
        "wamid.cart": "3 productos · COP 45.000",
        "wamid.old": "3 productos · COP 45.000",
    }
    vm = build_message_vm(_cart_message(), now=NOW, zone=ZONE, carts=carts)
    assert vm.text == "Mandó un pedido desde tu catálogo: 3 productos · COP 45.000"
    assert (vm.is_order, vm.is_media_placeholder) == (True, True)


def test_cart_bubble_without_detail() -> None:
    carts = _carts({"_order": _cart()})
    vm = build_message_vm(_cart_message("wamid.gone"), now=NOW, zone=ZONE, carts=carts)
    assert vm.text == CART_BUBBLE_NO_DETAIL
    assert vm.text == "Mandó un pedido desde tu catálogo. El detalle ya no está guardado."
    assert vm.is_order
    assert "[pedido]" not in build_message_vm(_cart_message(), now=NOW, zone=ZONE).text


def test_cart_details_skip_menu_orders() -> None:
    assert _carts({"_order": _MENU}) == {}
    assert cart_details(None) == {}


def test_other_message_kinds_are_unchanged() -> None:
    location = _cart_message(media_kind="location")
    contact = _cart_message(media_kind="contacts")
    text = _cart_message(media_kind=None, text="Hola")
    outbound = _cart_message(direction="outbound", media_kind="image")
    vms = build_conversation(
        [location, contact, text, outbound],
        [],
        now=NOW,
        zone=ZONE,
        carts={"wamid.cart": "x"},
    )
    assert [(m.text, m.is_order) for m in vms] == [
        ("[ubicación]", False),
        ("[contacto]", False),
        ("Hola", False),
        ("[imagen]", False),
    ]


# --- the state: the payment flag and the reset ----------------------------------------


def test_a_failed_payment_read_never_offers_the_charge_hint() -> None:
    from .whatsapp_chats_state import WhatsAppChatsState, _payment_status

    class Failing:
        def payment_status(self, *args: Any) -> Any:
            raise RuntimeError("down")

    class Empty:
        def payment_status(self, *args: Any) -> Any:
            return None

    ids = (uuid4(), uuid4(), uuid4())
    assert _payment_status(Failing(), *ids) == (None, False)
    assert _payment_status(Empty(), *ids) == (None, True)

    state = WhatsAppChatsState()
    state._order_raw = read_order({"_order": _cart()})
    state._render_conversation()
    assert state.order.charge_hint == CART_CHARGE_HINT
    state._payment_unread = True
    state._render_conversation()
    assert state.order.charge_hint == ""


def test_the_cart_state_resets_with_the_conversation() -> None:
    from .whatsapp_chats_state import WhatsAppChatsState

    context = {"_order": _cart(), "_orders_previous": [_entry(_MENU)]}
    state = WhatsAppChatsState()
    state._order_raw = read_order(context)
    state._previous_orders_raw = read_previous_orders(context)
    state._cart_ids = cart_message_ids(context)
    state._payment_unread = True
    state._render_conversation()
    assert state.order.previous_label == "1 pedido anterior"
    state._reset_conversation()
    assert state.order == OrderCardVM(present=False)
    assert (state._previous_orders_raw, state._cart_ids, state._payment_unread) == (
        (),
        frozenset(),
        False,
    )
