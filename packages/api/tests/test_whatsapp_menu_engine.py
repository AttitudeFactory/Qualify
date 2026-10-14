"""Deterministic menu engine (WA-14): table-driven walks over `BIANKI_DEMO_MENU`.

Fully offline and pure — `step` touches no network, no DB, no clock. The catalog is a
fake of 12 items across 3 categories so the `products` node must paginate (9 + "Ver
más" on page 1, 3 on page 2 with `page_size=10`).
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest
from qualify_shared.social.wa_shapes import WAMessage

from qualify_api.whatsapp.menus.automation import to_conversational_automation
from qualify_api.whatsapp.menus.engine import (
    CTX_ORDER,
    CTX_PRODUCTS_PAGE,
    ENGINE_VERSION,
    HELP_LINE,
    MAX_UNKNOWN_ATTEMPTS,
    UNKNOWN_HANDOFF_MESSAGE,
    UNKNOWN_INPUT_REASON,
    Button,
    CatalogItem,
    Handoff,
    Inbound,
    OutboundAction,
    SendButtons,
    SendList,
    SendText,
    SetContext,
    StepResult,
    ThreadMenuState,
    format_money,
    inbound_from_message,
    render_node,
    step,
)
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU as MENU
from qualify_api.whatsapp.menus.schema import MenuDefinition

# --- fixtures ----------------------------------------------------------------------

_CATEGORIES = ["Hamburguesas"] * 5 + ["Acompañamientos"] * 4 + ["Bebidas"] * 3


@pytest.fixture
def catalog() -> list[CatalogItem]:
    return [
        CatalogItem(
            product_id=f"p{i}",
            name=f"Producto {i}",
            price_amount=Decimal(1000 * i),
            price_currency="COP",
            category=category,
        )
        for i, category in enumerate(_CATEGORIES, start=1)
    ]


def _kinds(actions: Sequence[OutboundAction]) -> list[str]:
    return [type(a).__name__ for a in actions]


def _messages(actions: Sequence[OutboundAction]) -> list[OutboundAction]:
    return [a for a in actions if not isinstance(a, SetContext)]


def _menu(**top: Any) -> MenuDefinition:
    """A tiny menu for the cases the demo does not shape well."""
    payload: dict[str, Any] = {
        "start_node": "inicio",
        "entry": {"keywords": {"hola": "inicio"}},
        "nodes": {
            "inicio": {
                "kind": "buttons",
                "body": "¿Qué quieres?",
                "options": [
                    {"id": "a", "label": "Opción A", "next": "a"},
                    {"id": "b", "label": "Opción B", "next": "inicio"},
                ],
            },
            "a": {"kind": "text", "body": "Fuiste a A."},
        },
    }
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    return MenuDefinition.model_validate(payload)


# --- the happy path, as a table ------------------------------------------------------


def test_full_order_through_demo_menu(catalog: list[CatalogItem]) -> None:
    state = ThreadMenuState()

    def run(inbound: Inbound) -> StepResult:
        nonlocal state
        result = step(MENU, state, inbound, catalog=catalog)
        state = result.state
        return result

    # 1. First message, unknown text: welcome + start node.
    r = run(Inbound.text("Buenas noches", first_message=True))
    assert _kinds(r.actions) == ["SendText", "SendButtons"]
    assert isinstance(r.actions[0], SendText)
    assert r.actions[0].body == MENU.entry.welcome
    assert isinstance(r.actions[1], SendButtons)
    assert [b.id for b in r.actions[1].buttons] == ["ver_menu", "info", "persona"]
    assert state.node_id == "inicio" and not r.handed_off

    # 2. Tap "Ver menú y pedir": page 1 of the catalog, grouped by category, + "Ver más".
    r = run(Inbound.button_reply("ver_menu"))
    page1 = r.actions[0]
    assert isinstance(page1, SendList)
    assert [s.title for s in page1.sections] == ["Hamburguesas", "Acompañamientos", "Más"]
    assert len(page1.rows) == 10
    assert [r_.id for r_ in page1.rows[:9]] == [f"prod:p{i}" for i in range(1, 10)]
    assert page1.rows[-1].id == "more:1"
    assert page1.rows[0].description == "COP 1.000"
    assert page1.button_label == "Ver productos"
    assert state.node_id == "productos" and state.context[CTX_PRODUCTS_PAGE] == 0

    # 3. "Ver más": page 2 holds the 3 drinks and no "Más" section.
    r = run(Inbound.list_reply("more:1"))
    page2 = r.actions[0]
    assert isinstance(page2, SendList)
    assert [s.title for s in page2.sections] == ["Bebidas"]
    assert [r_.id for r_ in page2.rows] == ["prod:p10", "prod:p11", "prod:p12"]
    assert state.context[CTX_PRODUCTS_PAGE] == 1

    # 4. Pick a drink: order gets one line, we land on `agregado`.
    r = run(Inbound.list_reply("prod:p11"))
    assert isinstance(r.actions[0], SendButtons)
    assert state.node_id == "agregado"
    assert state.order == [
        {"product_id": "p11", "name": "Producto 11", "qty": 1, "price": "11000", "currency": "COP"}
    ]
    assert CTX_PRODUCTS_PAGE not in state.context
    assert isinstance(r.actions[-1], SetContext) and r.actions[-1].context == state.context

    # 5. "Agregar más" goes back to page 1; a typed position picks a row.
    r = run(Inbound.button_reply("agregar_mas"))
    assert isinstance(r.actions[0], SendList) and r.actions[0].rows[-1].id == "more:1"
    r = run(Inbound.text("2"))
    assert state.node_id == "agregado"
    assert [(o["product_id"], o["qty"]) for o in state.order] == [("p11", 1), ("p2", 1)]

    # 6. Picking the same product again increments instead of duplicating.
    run(Inbound.text("agregar más"))
    run(Inbound.text("Producto 2"))
    assert [(o["product_id"], o["qty"]) for o in state.order] == [("p11", 1), ("p2", 2)]

    # 7. Typed label opens the summary: lines, total, three fixed buttons.
    r = run(Inbound.text("ver mi pedido"))
    summary = r.actions[0]
    assert isinstance(summary, SendButtons)
    assert summary.body == (
        "1 x Producto 11 — COP 11.000\n2 x Producto 2 — COP 4.000\n\n"
        "Total: COP 15.000\n¿Confirmas tu pedido?"
    )
    assert summary.buttons == (
        Button("confirm", "Confirmar"),
        Button("add_more", "Agregar más"),
        Button("cancel", "Cancelar"),
    )
    assert state.node_id == "resumen"

    # 8. Two unknown answers re-render with the help line; the counter climbs.
    for attempt in (1, 2):
        r = run(Inbound.text("¿y el domicilio?"))
        again = r.actions[0]
        assert isinstance(again, SendButtons)
        assert again.body.startswith(HELP_LINE + "\n\n1 x Producto 11")
        assert again.buttons == summary.buttons
        assert state.attempts == attempt and state.node_id == "resumen"

    # 9. Confirm: order marked, counter reset, address collected next.
    r = run(Inbound.button_reply("confirm"))
    assert _messages(r.actions) == [
        SendText("¿A qué dirección te lo llevamos? Escríbela completa, con barrio.")
    ]
    assert state.node_id == "direccion" and state.attempts == 0
    assert state.context["order_confirmed"] is True

    # 10. The address lands in `collected`; the handoff carries the structured order.
    r = run(Inbound.text("Calle 10 # 5-20, Centro"))
    assert _kinds(r.actions) == ["SendText", "Handoff", "SetContext"]
    handoff = r.actions[1]
    assert isinstance(handoff, Handoff)
    assert handoff.reason == "order_confirmed"
    assert handoff.summary == {
        "order": [
            {
                "product_id": "p11",
                "name": "Producto 11",
                "qty": 1,
                "price": "11000",
                "currency": "COP",
            },
            {
                "product_id": "p2",
                "name": "Producto 2",
                "qty": 2,
                "price": "2000",
                "currency": "COP",
            },
        ],
        "total": "15000",
        "currency": "COP",
        "order_confirmed": True,
        "collected": {"direccion": "Calle 10 # 5-20, Centro"},
        "node_id": "pedido_confirmado",
        "engine_version": ENGINE_VERSION,
    }
    assert r.handed_off is True
    assert state.paused is True and state.node_id is None

    # 11. Paused: inert, whatever arrives.
    before = state
    r = run(Inbound.text("hola"))
    assert r.actions == [] and r.state == before and not r.handed_off


def test_cancel_clears_the_order(catalog: list[CatalogItem]) -> None:
    state = ThreadMenuState(node_id="productos", context={CTX_PRODUCTS_PAGE: 0})
    state = step(MENU, state, Inbound.list_reply("prod:p1"), catalog=catalog).state
    state = step(MENU, state, Inbound.button_reply("ver_pedido"), catalog=catalog).state
    assert state.node_id == "resumen" and len(state.order) == 1
    r = step(MENU, state, Inbound.text("cancelar"), catalog=catalog)
    assert _messages(r.actions) == [
        SendText("Listo, cancelé el pedido. Cuando quieras volver a empezar, escribe *menú*.")
    ]
    assert r.state.node_id is None and r.state.order == [] and not r.handed_off
    assert CTX_ORDER not in r.state.context


def test_add_more_from_summary_returns_to_catalog(catalog: list[CatalogItem]) -> None:
    state = ThreadMenuState(node_id="resumen", context={CTX_ORDER: []})
    r = step(MENU, state, Inbound.button_reply("add_more"), catalog=catalog)
    assert isinstance(r.actions[0], SendList) and r.state.node_id == "productos"


def test_empty_order_summary_shows_placeholder_line() -> None:
    r = render_node(MENU, "resumen", ThreadMenuState())
    body = r.actions[0]
    assert isinstance(body, SendButtons)
    assert body.body.startswith("(tu pedido está vacío)\n\nTotal: 0\n")


def test_empty_catalog_ends_the_session() -> None:
    state = ThreadMenuState(node_id="inicio")
    r = step(MENU, state, Inbound.button_reply("ver_menu"), catalog=())
    assert _messages(r.actions) == [
        SendText("Por ahora no tenemos productos cargados. Escríbenos y te atendemos.")
    ]
    assert r.state.node_id is None


def test_catalog_that_fits_has_no_more_row() -> None:
    small = [CatalogItem(f"p{i}", f"P {i}", None, None, None) for i in range(10)]
    r = render_node(MENU, "productos", ThreadMenuState(), small)
    send = r.actions[0]
    assert isinstance(send, SendList)
    assert [s.title for s in send.sections] == ["Productos"]
    assert len(send.rows) == 10 and send.rows[0].description is None


def test_long_names_and_categories_are_clipped_to_meta_limits() -> None:
    items = [
        CatalogItem("x", "Hamburguesa doble con tocineta y queso", Decimal("9.5"), "USD", "C" * 40)
    ]
    r = render_node(MENU, "productos", ThreadMenuState(), items)
    send = r.actions[0]
    assert isinstance(send, SendList)
    assert len(send.sections[0].title) <= 24 and send.sections[0].title.endswith("…")
    assert len(send.rows[0].title) <= 24 and send.rows[0].title.endswith("…")
    assert send.rows[0].description == "USD 9,50"


# --- entries -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("inbound", "expected_node", "first_kind"),
    [
        (Inbound.text("MENÚ"), "productos", "SendList"),
        (Inbound.text("  pedir "), "productos", "SendList"),
        (Inbound.text("Horario"), None, "SendText"),  # ice breaker → terminal text
        (Inbound.text("Ubicación"), None, "SendText"),
        (Inbound.text("/horario"), None, "SendText"),  # command typed as text
        (Inbound.text("/menu por favor"), "productos", "SendList"),
        (Inbound.command("/persona"), None, "SendText"),  # handoff
        (Inbound.command("menu"), "productos", "SendList"),
    ],
)
def test_global_entries_route_from_anywhere(
    catalog: list[CatalogItem], inbound: Inbound, expected_node: str | None, first_kind: str
) -> None:
    # From idle AND from the middle of the order flow: entries are escape hatches.
    for start in (ThreadMenuState(), ThreadMenuState(node_id="agregado", attempts=1)):
        r = step(MENU, start, inbound, catalog=catalog)
        assert type(r.actions[0]).__name__ == first_kind
        assert r.state.node_id == expected_node
        assert r.state.attempts == 0


def test_command_handoff_pauses_with_its_reason() -> None:
    r = step(MENU, ThreadMenuState(node_id="inicio"), Inbound.command("persona"))
    assert _kinds(_messages(r.actions)) == ["SendText", "Handoff"]
    handoff = r.actions[1]
    assert isinstance(handoff, Handoff) and handoff.reason == "customer_request"
    assert handoff.summary["order"] == [] and handoff.summary["node_id"] == "persona"
    assert r.handed_off and r.state.paused


def test_welcome_request_greets_and_shows_start_node() -> None:
    r = step(MENU, ThreadMenuState(), Inbound.welcome())
    assert _kinds(r.actions) == ["SendText", "SendButtons"]
    assert isinstance(r.actions[0], SendText) and r.actions[0].body == MENU.entry.welcome


def test_first_message_keyword_still_gets_the_welcome() -> None:
    r = step(MENU, ThreadMenuState(), Inbound.text("horario", first_message=True))
    assert _kinds(r.actions) == ["SendText", "SendText"]
    assert isinstance(r.actions[0], SendText) and r.actions[0].body == MENU.entry.welcome


def test_menu_that_does_not_greet_ignores_unsolicited_first_messages() -> None:
    quiet = _menu(entry={"on_first_message": False, "welcome": "Hola"})
    assert step(quiet, ThreadMenuState(), Inbound.text("buenas", first_message=True)).actions == []
    assert step(quiet, ThreadMenuState(), Inbound.welcome()).actions == []
    # A keyword on the first message still routes — without the welcome.
    r = step(quiet, ThreadMenuState(), Inbound.text("hola", first_message=True))
    assert _kinds(r.actions) == ["SendButtons"]
    # A later unrecognized message re-enters at the start node.
    r = step(quiet, ThreadMenuState(), Inbound.text("hay alguien?"))
    assert _kinds(r.actions) == ["SendButtons"] and r.state.node_id == "inicio"


def test_idle_thread_reenters_at_start_without_welcome() -> None:
    r = step(MENU, ThreadMenuState(), Inbound.text("hay alguien?"))
    assert _kinds(r.actions) == ["SendButtons"] and r.state.node_id == "inicio"
    r = step(MENU, ThreadMenuState(), Inbound.unsupported("audio"))
    assert _kinds(r.actions) == ["SendButtons"]


# --- unknown input -------------------------------------------------------------------


def test_unknown_input_twice_then_declared_fallback_handoff() -> None:
    state = ThreadMenuState(node_id="inicio")
    for attempt in range(1, MAX_UNKNOWN_ATTEMPTS + 1):
        r = step(MENU, state, Inbound.text("???"))
        state = r.state
        again = r.actions[0]
        assert isinstance(again, SendButtons)
        assert again.body == f"{HELP_LINE}\n\n¿Qué quieres hacer?"
        assert state.attempts == attempt and not r.handed_off
    r = step(MENU, state, Inbound.unsupported("sticker"))
    assert _kinds(_messages(r.actions)) == ["SendText", "Handoff"]
    handoff = r.actions[1]
    assert isinstance(handoff, Handoff) and handoff.reason == "customer_request"
    assert r.handed_off and r.state.paused and r.state.attempts == 0


def test_unknown_input_without_fallback_uses_builtin_handoff() -> None:
    plain = _menu()
    state = ThreadMenuState(node_id="inicio", attempts=MAX_UNKNOWN_ATTEMPTS)
    r = step(plain, state, Inbound.text("???"))
    assert r.actions[0] == SendText(UNKNOWN_HANDOFF_MESSAGE)
    handoff = r.actions[1]
    assert isinstance(handoff, Handoff) and handoff.reason == UNKNOWN_INPUT_REASON
    assert handoff.summary["node_id"] == "inicio"
    assert r.handed_off and r.state.paused


def test_recognized_answer_resets_the_counter() -> None:
    state = ThreadMenuState(node_id="inicio", attempts=MAX_UNKNOWN_ATTEMPTS)
    r = step(MENU, state, Inbound.button_reply("info"))
    assert r.state.node_id == "info" and r.state.attempts == 0


def test_wrong_reply_id_counts_as_unknown() -> None:
    r = step(MENU, ThreadMenuState(node_id="inicio"), Inbound.button_reply("confirm"))
    assert r.state.attempts == 1 and r.state.node_id == "inicio"


# --- collect -------------------------------------------------------------------------


def _collect_menu(validation: str) -> MenuDefinition:
    return _menu(
        start_node="c",
        nodes={
            "c": {
                "kind": "collect",
                "prompt": "Dime",
                "field": "dato",
                "validation": validation,
                "error_message": "Así no.",
                "next": "a",
            }
        },
    )


@pytest.mark.parametrize(
    ("validation", "inbound", "stored"),
    [
        ("text", Inbound.text("  Calle 1  "), "Calle 1"),
        ("phone", Inbound.text("+57 300 123-4567"), "+573001234567"),
        ("phone", Inbound.text("(601) 234 5678"), "6012345678"),
        ("yes_no", Inbound.button_reply("yes"), True),
        ("yes_no", Inbound.button_reply("no"), False),
        ("yes_no", Inbound.text("Sí"), True),
        ("yes_no", Inbound.text("nop"), False),
    ],
)
def test_collect_stores_valid_answers(validation: str, inbound: Inbound, stored: Any) -> None:
    menu = _collect_menu(validation)
    r = step(menu, ThreadMenuState(node_id="c"), inbound)
    assert r.state.collected == {"dato": stored}
    assert _messages(r.actions) == [SendText("Fuiste a A.")]
    assert r.state.node_id is None  # `a` is a terminal text node


@pytest.mark.parametrize(
    ("validation", "inbound"),
    [
        ("text", Inbound.text("   ")),
        ("text", Inbound.unsupported("image")),
        ("phone", Inbound.text("123")),
        ("phone", Inbound.text("llámame")),
        ("yes_no", Inbound.text("tal vez")),
        ("yes_no", Inbound.button_reply("confirm")),
    ],
)
def test_collect_rejects_and_reprompts_with_its_error(validation: str, inbound: Inbound) -> None:
    menu = _collect_menu(validation)
    r = step(menu, ThreadMenuState(node_id="c"), inbound)
    assert r.state.node_id == "c" and r.state.attempts == 1 and r.state.collected == {}
    first = r.actions[0]
    body = first.body if isinstance(first, SendText | SendButtons) else ""
    assert body.startswith("Así no.\n\nDime")


def test_yes_no_renders_two_buttons() -> None:
    r = render_node(_collect_menu("yes_no"), "c", ThreadMenuState())
    assert r.actions == [SendButtons("Dime", (Button("yes", "Sí"), Button("no", "No")))]
    r = render_node(_collect_menu("text"), "c", ThreadMenuState())
    assert r.actions == [SendText("Dime")]


# --- render_node, purity, projections -----------------------------------------------


def test_text_nodes_chain_in_one_render() -> None:
    menu = _menu(
        nodes={
            "a": {"kind": "text", "body": "Primero.", "next": "b"},
            "b": {"kind": "text", "body": "Luego.", "next": "inicio"},
        }
    )
    r = render_node(menu, "a", ThreadMenuState())
    assert _kinds(r.actions) == ["SendText", "SendText", "SendButtons"]
    assert r.state.node_id == "inicio"


def test_render_handoff_pauses_and_summarizes() -> None:
    r = render_node(MENU, "persona", ThreadMenuState(context={CTX_ORDER: []}))
    assert _kinds(r.actions) == ["SendText", "Handoff"]
    assert r.state.paused and r.state.node_id is None


def test_step_is_pure_and_does_not_mutate_input(catalog: list[CatalogItem]) -> None:
    state = ThreadMenuState(node_id="productos", context={CTX_PRODUCTS_PAGE: 1, CTX_ORDER: []})
    frozen = copy.deepcopy(state)
    first = step(MENU, state, Inbound.list_reply("prod:p12"), catalog=catalog)
    second = step(MENU, state, Inbound.list_reply("prod:p12"), catalog=catalog)
    assert first == second
    assert state == frozen and state.context == frozen.context


def test_set_context_only_when_context_changed() -> None:
    r = step(MENU, ThreadMenuState(node_id="inicio"), Inbound.button_reply("info"))
    assert not any(isinstance(a, SetContext) for a in r.actions)
    r = step(MENU, ThreadMenuState(node_id="resumen"), Inbound.button_reply("confirm"))
    assert isinstance(r.actions[-1], SetContext)
    assert r.actions[-1].context == {"order_confirmed": True}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "id": "wamid.1",
                "from": "57300",
                "timestamp": "1",
                "type": "text",
                "text": {"body": "hola"},
            },
            Inbound.text("hola"),
        ),
        (
            {
                "id": "wamid.2",
                "from": "57300",
                "timestamp": "1",
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "ver_menu", "title": "x"},
                },
            },
            Inbound.button_reply("ver_menu"),
        ),
        (
            {
                "id": "wamid.3",
                "from": "57300",
                "timestamp": "1",
                "type": "interactive",
                "interactive": {
                    "type": "list_reply",
                    "list_reply": {"id": "prod:p1", "title": "x"},
                },
            },
            Inbound.list_reply("prod:p1"),
        ),
        (
            {"id": "wamid.4", "from": "57300", "timestamp": "1", "type": "request_welcome"},
            Inbound.welcome(),
        ),
        (
            {"id": "wamid.5", "from": "57300", "timestamp": "1", "type": "image"},
            Inbound.unsupported("image"),
        ),
    ],
)
def test_inbound_from_message(payload: dict[str, Any], expected: Inbound) -> None:
    assert inbound_from_message(WAMessage.model_validate(payload)) == expected


def test_inbound_from_message_propagates_first_message_flag() -> None:
    msg = WAMessage.model_validate(
        {"id": "w", "from": "1", "timestamp": "1", "type": "text", "text": {"body": "hola"}}
    )
    assert inbound_from_message(msg, first_message=True).first_message is True


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (Decimal("12500"), "COP", "COP 12.500"),
        (Decimal("12500.00"), "COP", "COP 12.500"),
        (Decimal("9.5"), "USD", "USD 9,50"),
        (Decimal("1234567.89"), None, "1.234.567,89"),
        (Decimal("0"), "COP", "COP 0"),
    ],
)
def test_format_money(amount: Decimal, currency: str | None, expected: str) -> None:
    assert format_money(amount, currency) == expected


# --- conversational automation -------------------------------------------------------


def test_to_conversational_automation_for_demo() -> None:
    assert to_conversational_automation(MENU) == {
        "enable_welcome_message": True,
        "prompts": ["Ver menú", "Hacer pedido", "Horario", "Ubicación"],
        "commands": [
            {"command_name": "menu", "command_description": "Ver el menú y hacer un pedido"},
            {"command_name": "horario", "command_description": "Horario de atención"},
            {"command_name": "ubicacion", "command_description": "Dónde estamos"},
            {"command_name": "persona", "command_description": "Hablar con una persona del equipo"},
        ],
    }


def test_to_conversational_automation_clears_what_the_menu_lacks() -> None:
    assert to_conversational_automation(_menu()) == {
        "enable_welcome_message": False,
        "prompts": [],
        "commands": [],
    }
    greets_silently = _menu(entry={"on_first_message": False, "welcome": "Hola"})
    assert to_conversational_automation(greets_silently)["enable_welcome_message"] is False
