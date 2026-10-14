"""`MenuDefinition` validation (WA-14): every Meta limit, every structural invariant.

Fully offline — the schema is pure Pydantic. Each limit gets one case AT the limit
(accepted) and one case past it (rejected), so a future relaxation or tightening of a
constant shows up here and not as a Cloud API error at publish time.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.menus.schema import (
    BODY_MAX_LEN,
    BUTTON_TITLE_MAX_LEN,
    COMMAND_HINT_MAX_LEN,
    COMMAND_NAME_MAX_LEN,
    FOOTER_MAX_LEN,
    HEADER_MAX_LEN,
    ICE_BREAKER_MAX_LEN,
    LIST_BUTTON_MAX_LEN,
    LIST_ROW_DESCRIPTION_MAX_LEN,
    LIST_ROW_TITLE_MAX_LEN,
    LIST_SECTION_TITLE_MAX_LEN,
    MAX_BUTTONS,
    MAX_COMMANDS,
    MAX_ICE_BREAKERS,
    MAX_LIST_ROWS,
    MAX_LIST_SECTIONS,
    MenuDefinition,
    OrderSummaryNode,
    contains_emoji,
    normalize_keyword,
)

# --- helpers ---------------------------------------------------------------------


def _text(body: str = "ok", next_: str | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"kind": "text", "body": body}
    if next_:
        node["next"] = next_
    return node


def _buttons(n: int = 1, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "buttons",
        "body": "Elige",
        "options": [{"id": f"o{i}", "label": f"Opción {i}", "next": "fin"} for i in range(n)],
        **extra,
    }


def _list(sections: int = 1, rows_per_section: int = 1, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "list",
        "body": "Elige",
        "button_label": "Ver",
        "sections": [
            {
                "title": f"S{s}",
                "rows": [
                    {"id": f"r{s}_{r}", "title": f"Fila {s}-{r}", "next": "fin"}
                    for r in range(rows_per_section)
                ],
            }
            for s in range(sections)
        ],
        **extra,
    }


def _menu(nodes: dict[str, Any] | None = None, **top: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "start_node": "inicio",
        "nodes": {"inicio": _buttons(), "fin": _text(), **(nodes or {})},
    }
    base.update(top)
    return base


def _ok(payload: dict[str, Any]) -> MenuDefinition:
    return MenuDefinition.model_validate(payload)


def _rejects(payload: dict[str, Any], *fragments: str) -> None:
    with pytest.raises(ValidationError) as info:
        MenuDefinition.model_validate(payload)
    text = str(info.value)
    for fragment in fragments:
        assert fragment in text, f"{fragment!r} not in:\n{text}"


# --- the demo and the basics -----------------------------------------------------


def test_demo_menu_is_valid_and_round_trips() -> None:
    dumped = BIANKI_DEMO_MENU.model_dump(mode="json")
    assert MenuDefinition.model_validate(dumped) == BIANKI_DEMO_MENU
    assert BIANKI_DEMO_MENU.start_node == "inicio"
    assert len(BIANKI_DEMO_MENU.entry.ice_breakers) == MAX_ICE_BREAKERS
    assert isinstance(BIANKI_DEMO_MENU.node("resumen"), OrderSummaryNode)


def test_minimal_menu_defaults() -> None:
    menu = _ok(_menu())
    assert menu.version == 1
    assert menu.entry.on_first_message is True
    assert menu.entry.keywords == {}
    assert menu.entry.welcome is None


def test_unknown_keys_are_rejected() -> None:
    _rejects(_menu(typo=1), "typo")
    _rejects(_menu(nodes={"x": {**_text(), "nxt": "fin"}}), "nxt")


@pytest.mark.parametrize("node_id", ["Inicio", "con espacio", "ñ", "", "a" * 65])
def test_node_ids_are_slugs(node_id: str) -> None:
    _rejects(_menu(nodes={node_id: _text()}), "node id")


# --- normalization helpers -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Menú", "menu"),
        ("  HACER   Pedido ", "hacer pedido"),
        ("Ubicación", "ubicacion"),
        ("¿Horario?", "¿horario?"),
    ],
)
def test_normalize_keyword(raw: str, expected: str) -> None:
    assert normalize_keyword(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Ver menú", False), ("Pide ya 🍔", True), ("Ok ✅", True), ("☀ sol", True), ("a-b_c", False)],
)
def test_contains_emoji(text: str, expected: bool) -> None:
    assert contains_emoji(text) is expected


# --- entry limits ----------------------------------------------------------------


def test_ice_breakers_limits() -> None:
    ibs = [{"text": f"Atajo {i}", "node": "fin"} for i in range(MAX_ICE_BREAKERS)]
    _ok(_menu(entry={"ice_breakers": ibs}))
    _rejects(_menu(entry={"ice_breakers": ibs + [{"text": "Otro", "node": "fin"}]}), "ice_breakers")
    _ok(_menu(entry={"ice_breakers": [{"text": "x" * ICE_BREAKER_MAX_LEN, "node": "fin"}]}))
    _rejects(
        _menu(entry={"ice_breakers": [{"text": "x" * (ICE_BREAKER_MAX_LEN + 1), "node": "fin"}]}),
        "ice_breakers",
    )
    _rejects(_menu(entry={"ice_breakers": [{"text": "Pide 🍔", "node": "fin"}]}), "emoji")
    _rejects(
        _menu(
            entry={
                "ice_breakers": [
                    {"text": "Menú", "node": "fin"},
                    {"text": "menu", "node": "fin"},
                ]
            }
        ),
        "duplicate ice breaker",
    )


def test_commands_limits() -> None:
    cmds = [{"name": f"c{i}", "hint": "pista", "node": "fin"} for i in range(MAX_COMMANDS)]
    _ok(_menu(entry={"commands": cmds}))
    _rejects(
        _menu(entry={"commands": cmds + [{"name": "extra", "hint": "pista", "node": "fin"}]}),
        "commands",
    )
    _ok(
        _menu(
            entry={"commands": [{"name": "c" * COMMAND_NAME_MAX_LEN, "hint": "h", "node": "fin"}]}
        )
    )
    _rejects(
        _menu(
            entry={
                "commands": [{"name": "c" * (COMMAND_NAME_MAX_LEN + 1), "hint": "h", "node": "fin"}]
            }
        ),
        "name",
    )
    _ok(
        _menu(
            entry={"commands": [{"name": "c", "hint": "h" * COMMAND_HINT_MAX_LEN, "node": "fin"}]}
        )
    )
    _rejects(
        _menu(
            entry={
                "commands": [{"name": "c", "hint": "h" * (COMMAND_HINT_MAX_LEN + 1), "node": "fin"}]
            }
        ),
        "hint",
    )
    _rejects(_menu(entry={"commands": [{"name": "me🍔", "hint": "h", "node": "fin"}]}), "emoji")
    _rejects(_menu(entry={"commands": [{"name": "c", "hint": "h 🍔", "node": "fin"}]}), "emoji")
    _rejects(
        _menu(entry={"commands": [{"name": "dos palabras", "hint": "h", "node": "fin"}]}), "word"
    )
    _rejects(_menu(entry={"commands": [{"name": "/menu", "hint": "h", "node": "fin"}]}), "word")
    _rejects(
        _menu(
            entry={
                "commands": [
                    {"name": "Menu", "hint": "h", "node": "fin"},
                    {"name": "menú", "hint": "h", "node": "fin"},
                ]
            }
        ),
        "duplicate command",
    )


def test_keywords_are_normalized_and_collide() -> None:
    menu = _ok(_menu(entry={"keywords": {"  Menú ": "fin", "HOLA": "inicio"}}))
    assert menu.entry.keywords == {"menu": "fin", "hola": "inicio"}
    _rejects(_menu(entry={"keywords": {"menu": "fin", "Menú": "fin"}}), "duplicate keyword")
    _rejects(_menu(entry={"keywords": {"   ": "fin"}}), "empty")


def test_welcome_respects_body_limit() -> None:
    _ok(_menu(entry={"welcome": "w" * BODY_MAX_LEN}))
    _rejects(_menu(entry={"welcome": "w" * (BODY_MAX_LEN + 1)}), "welcome")


def test_fallback_node_must_be_a_handoff() -> None:
    handoff = {"kind": "handoff", "message": "m", "reason": "fallback"}
    _ok(_menu(nodes={"h": handoff}, entry={"fallback_node": "h"}))
    _rejects(_menu(entry={"fallback_node": "fin"}), "fallback_node", "handoff")
    _rejects(_menu(entry={"fallback_node": "nope"}), "dangling", "entry -> 'nope'")


# --- buttons -----------------------------------------------------------------------


def test_buttons_limits() -> None:
    _ok(_menu(nodes={"b": _buttons(MAX_BUTTONS)}))
    _rejects(_menu(nodes={"b": _buttons(MAX_BUTTONS + 1)}), "options")
    _rejects(_menu(nodes={"b": _buttons(0)}), "options")
    long_label = _buttons(1)
    long_label["options"][0]["label"] = "L" * BUTTON_TITLE_MAX_LEN
    _ok(_menu(nodes={"b": long_label}))
    long_label["options"][0]["label"] = "L" * (BUTTON_TITLE_MAX_LEN + 1)
    _rejects(_menu(nodes={"b": long_label}), "label")


def test_button_ids_unique_within_node() -> None:
    dup = _buttons(2)
    dup["options"][1]["id"] = dup["options"][0]["id"]
    _rejects(_menu(nodes={"b": dup}), "duplicate button id")


def test_body_header_footer_limits() -> None:
    _ok(_menu(nodes={"b": _buttons(body="b" * BODY_MAX_LEN)}))
    _rejects(_menu(nodes={"b": _buttons(body="b" * (BODY_MAX_LEN + 1))}), "body")
    _ok(_menu(nodes={"b": _buttons(header="h" * HEADER_MAX_LEN)}))
    _rejects(_menu(nodes={"b": _buttons(header="h" * (HEADER_MAX_LEN + 1))}), "header")
    _ok(_menu(nodes={"b": _buttons(footer="f" * FOOTER_MAX_LEN)}))
    _rejects(_menu(nodes={"b": _buttons(footer="f" * (FOOTER_MAX_LEN + 1))}), "footer")
    _rejects(_menu(nodes={"t": _text(body="")}), "body")
    _rejects(_menu(nodes={"t": _text(body="t" * (BODY_MAX_LEN + 1))}), "body")


# --- lists -------------------------------------------------------------------------


def test_list_section_and_row_counts() -> None:
    _ok(_menu(nodes={"l": _list(sections=MAX_LIST_SECTIONS, rows_per_section=1)}))
    _rejects(
        _menu(nodes={"l": _list(sections=MAX_LIST_SECTIONS + 1, rows_per_section=1)}), "sections"
    )
    _ok(_menu(nodes={"l": _list(sections=1, rows_per_section=MAX_LIST_ROWS)}))
    _rejects(_menu(nodes={"l": _list(sections=1, rows_per_section=MAX_LIST_ROWS + 1)}), "rows")
    # Total across sections is what Meta caps, not per section.
    _ok(_menu(nodes={"l": _list(sections=2, rows_per_section=5)}))
    _rejects(_menu(nodes={"l": _list(sections=2, rows_per_section=6)}), f"at most {MAX_LIST_ROWS}")
    _rejects(_menu(nodes={"l": _list(sections=0)}), "sections")
    _rejects(_menu(nodes={"l": _list(sections=1, rows_per_section=0)}), "rows")


def test_list_text_limits() -> None:
    node = _list()
    node["sections"][0]["rows"][0]["title"] = "t" * LIST_ROW_TITLE_MAX_LEN
    _ok(_menu(nodes={"l": node}))
    node["sections"][0]["rows"][0]["title"] = "t" * (LIST_ROW_TITLE_MAX_LEN + 1)
    _rejects(_menu(nodes={"l": node}), "title")

    node = _list()
    node["sections"][0]["rows"][0]["description"] = "d" * LIST_ROW_DESCRIPTION_MAX_LEN
    _ok(_menu(nodes={"l": node}))
    node["sections"][0]["rows"][0]["description"] = "d" * (LIST_ROW_DESCRIPTION_MAX_LEN + 1)
    _rejects(_menu(nodes={"l": node}), "description")

    node = _list()
    node["sections"][0]["title"] = "s" * LIST_SECTION_TITLE_MAX_LEN
    _ok(_menu(nodes={"l": node}))
    node["sections"][0]["title"] = "s" * (LIST_SECTION_TITLE_MAX_LEN + 1)
    _rejects(_menu(nodes={"l": node}), "title")

    _ok(_menu(nodes={"l": _list(button_label="b" * LIST_BUTTON_MAX_LEN)}))
    _rejects(
        _menu(nodes={"l": _list(button_label="b" * (LIST_BUTTON_MAX_LEN + 1))}), "button_label"
    )


def test_list_row_ids_unique_across_sections() -> None:
    node = _list(sections=2, rows_per_section=1)
    node["sections"][1]["rows"][0]["id"] = node["sections"][0]["rows"][0]["id"]
    _rejects(_menu(nodes={"l": node}), "duplicate list row id")


# --- products ----------------------------------------------------------------------


def test_products_node_limits_and_defaults() -> None:
    node = {"kind": "products", "body": "Elige", "next_after_pick": "fin"}
    menu = _ok(_menu(nodes={"p": node}))
    products = menu.node("p")
    assert products.kind == "products"
    assert products.page_size == MAX_LIST_ROWS
    assert products.source == "catalog"
    _rejects(_menu(nodes={"p": {**node, "page_size": MAX_LIST_ROWS + 1}}), "page_size")
    _rejects(_menu(nodes={"p": {**node, "page_size": 1}}), "page_size")
    _rejects(_menu(nodes={"p": {**node, "source": "manual"}}), "source")
    _rejects(_menu(nodes={"p": {**node, "more_label": "m" * (LIST_ROW_TITLE_MAX_LEN + 1)}}), "more")
    _rejects(_menu(nodes={"p": {**node, "next_after_pick": "ghost"}}), "dangling", "p -> 'ghost'")


# --- order summary -----------------------------------------------------------------


def _summary(**over: Any) -> dict[str, Any]:
    return {
        "kind": "order_summary",
        "body": "Total {total}",
        "confirm_next": "h",
        "add_more_next": "inicio",
        "cancel_next": "fin",
        **over,
    }


_HANDOFF = {"kind": "handoff", "message": "gracias", "reason": "order_confirmed"}


def test_order_summary_requires_total_placeholder() -> None:
    _ok(_menu(nodes={"r": _summary(), "h": _HANDOFF}))
    _rejects(_menu(nodes={"r": _summary(body="sin total"), "h": _HANDOFF}), "{total}")


def test_order_summary_labels_respect_button_limit() -> None:
    _ok(_menu(nodes={"r": _summary(confirm_label="C" * BUTTON_TITLE_MAX_LEN), "h": _HANDOFF}))
    _rejects(
        _menu(nodes={"r": _summary(confirm_label="C" * (BUTTON_TITLE_MAX_LEN + 1)), "h": _HANDOFF}),
        "confirm_label",
    )


def test_at_most_one_order_summary() -> None:
    _rejects(
        _menu(nodes={"r1": _summary(), "r2": _summary(), "h": _HANDOFF}),
        "at most one order_summary",
    )


def test_confirm_must_reach_a_handoff() -> None:
    # Directly.
    _ok(_menu(nodes={"r": _summary(), "h": _HANDOFF}))
    # Through collect and text nodes.
    collect = {"kind": "collect", "prompt": "¿Dirección?", "field": "direccion", "next": "nota"}
    _ok(
        _menu(
            nodes={
                "r": _summary(confirm_next="c"),
                "c": collect,
                "nota": _text("ya casi", "h"),
                "h": _HANDOFF,
            }
        )
    )
    # Not through a buttons node, nor into a terminal text.
    _rejects(
        _menu(nodes={"r": _summary(confirm_next="inicio"), "h": _HANDOFF}), "confirm must lead"
    )
    _rejects(_menu(nodes={"r": _summary(confirm_next="fin"), "h": _HANDOFF}), "confirm must lead")


# --- collect / handoff -------------------------------------------------------------


def test_collect_field_and_validation() -> None:
    base = {"kind": "collect", "prompt": "¿Tel?", "field": "telefono", "next": "fin"}
    assert _ok(_menu(nodes={"c": base})).node("c").validation == "text"
    _ok(_menu(nodes={"c": {**base, "validation": "phone"}}))
    _ok(_menu(nodes={"c": {**base, "validation": "yes_no"}}))
    _rejects(_menu(nodes={"c": {**base, "validation": "email"}}), "validation")
    _rejects(_menu(nodes={"c": {**base, "field": "Teléfono"}}), "field")
    _rejects(
        _menu(nodes={"c": {**base, "yes_label": "Y" * (BUTTON_TITLE_MAX_LEN + 1)}}), "yes_label"
    )


def test_handoff_reason_is_an_enum_like_slug() -> None:
    _ok(_menu(nodes={"h": _HANDOFF}))
    _rejects(_menu(nodes={"h": {**_HANDOFF, "reason": "Pedido confirmado"}}), "reason")
    _rejects(_menu(nodes={"h": {**_HANDOFF, "message": ""}}), "message")


# --- references and graph shape ----------------------------------------------------


def test_start_node_must_exist() -> None:
    _rejects(_menu(start_node="nada"), "start_node 'nada'")


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        (_menu(nodes={"t": _text("x", "ghost")}), "t -> 'ghost'"),
        (_menu(entry={"keywords": {"hola": "ghost"}}), "entry -> 'ghost'"),
        (_menu(entry={"ice_breakers": [{"text": "Hola", "node": "ghost"}]}), "entry -> 'ghost'"),
        (
            _menu(entry={"commands": [{"name": "c", "hint": "h", "node": "ghost"}]}),
            "entry -> 'ghost'",
        ),
        (_menu(nodes={"l": _list()}, start_node="l") | {"nodes": {"l": _list()}}, "l -> 'fin'"),
    ],
)
def test_dangling_references(payload: dict[str, Any], fragment: str) -> None:
    _rejects(payload, "dangling", fragment)


def test_text_chains_may_not_loop() -> None:
    _ok(_menu(nodes={"a": _text("a", "b"), "b": _text("b", "fin")}))
    _ok(_menu(nodes={"a": _text("a", "inicio")}))  # ends in buttons: fine
    _rejects(_menu(nodes={"a": _text("a", "a")}), "cycle")
    _rejects(_menu(nodes={"a": _text("a", "b"), "b": _text("b", "a")}), "cycle")
