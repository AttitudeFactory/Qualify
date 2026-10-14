"""Pure tests for the Menú tab's editor half (WA-16): form ↔ definition, Spanish
validation messages for every Meta limit, the phone preview over the engine, and the
publish banner copy. No Reflex state, no database, no network.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace
from decimal import Decimal

import pytest
from qualify_api.whatsapp.menus.engine import CatalogItem, Inbound, ThreadMenuState
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU

from .whatsapp_menu_vm import (
    KIND_BUTTONS,
    KIND_HANDOFF,
    KIND_LIST,
    KIND_ORDER_SUMMARY,
    KIND_TEXT,
    NONE_VALUE,
    REPLY_BUTTON,
    REPLY_LIST,
    CommandForm,
    IceBreakerForm,
    KeywordForm,
    MenuForm,
    MenuSummaryVM,
    MenuVersionVM,
    NodeForm,
    OptionForm,
    PreviewChoiceVM,
    PreviewMessageVM,
    change_kind,
    definition_to_form,
    empty_form,
    form_to_payload,
    issues_summary,
    new_node,
    new_option,
    order_lines,
    preview_turn,
    publish_notice,
    rename_node,
    validate_form,
    validate_menu_name,
)

_FORBIDDEN_FIELD_FRAGMENTS = (
    "token",
    "credential",
    "cipher",
    "secret",
    "key_id",
    "password",
    "plaintext",
)
_VMS = (
    KeywordForm,
    IceBreakerForm,
    CommandForm,
    OptionForm,
    NodeForm,
    MenuForm,
    MenuSummaryVM,
    MenuVersionVM,
    PreviewChoiceVM,
    PreviewMessageVM,
)

CATALOG = (
    CatalogItem("p1", "Hamburguesa clásica", Decimal("18000"), "COP", "Hamburguesas"),
    CatalogItem("p2", "Papas grandes", Decimal("7000"), "COP", "Acompañamientos"),
)


def _demo_form() -> MenuForm:
    return definition_to_form(BIANKI_DEMO_MENU)


def _node(form: MenuForm, node_id: str) -> tuple[int, NodeForm]:
    for index, node in enumerate(form.nodes):
        if node.node_id == node_id:
            return index, node
    raise AssertionError(node_id)


def _with_node(form: MenuForm, node_id: str, **changes: object) -> MenuForm:
    index, node = _node(form, node_id)
    nodes = list(form.nodes)
    nodes[index] = replace(node, **changes)
    return replace(form, nodes=nodes)


def _node_errors(form: MenuForm, node_id: str) -> dict[str, str]:
    return _node(form, node_id)[1].errors


# --- 1. the VM boundary -----------------------------------------------------------------


def test_whatsapp_menu_vm_has_no_credential_fields() -> None:
    for vm_cls in _VMS:
        for f in dataclasses.fields(vm_cls):
            lowered = f.name.lower()
            for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
                assert fragment not in lowered, f"{vm_cls.__name__}.{f.name} ({fragment})"


def test_menu_vms_are_frozen() -> None:
    for vm_cls in _VMS:
        assert vm_cls.__dataclass_params__.frozen, vm_cls.__name__  # type: ignore[attr-defined]


# --- 2. form <-> definition --------------------------------------------------------------


def test_demo_menu_round_trips_through_the_form() -> None:
    form = _demo_form()
    result = validate_form(form)
    assert result.error_count == 0, result.form
    assert result.definition is not None
    assert result.definition.model_dump(mode="json") == BIANKI_DEMO_MENU.model_dump(mode="json")


def test_form_flattens_list_sections_and_regroups_consecutive_rows() -> None:
    definition = BIANKI_DEMO_MENU.model_copy(deep=True)
    payload = definition.model_dump(mode="json")
    payload["nodes"]["info"] = {
        "kind": "list",
        "body": "¿Qué necesitas?",
        "button_label": "Ver opciones",
        "sections": [
            {"title": "Información", "rows": [{"id": "h", "title": "Horario", "next": "horario"}]},
            {
                "title": "Ayuda",
                "rows": [
                    {"id": "u", "title": "Ubicación", "description": "Mapa", "next": "ubicacion"},
                    {"id": "p", "title": "Persona", "next": "persona"},
                ],
            },
        ],
    }
    from qualify_api.whatsapp.menus.schema import MenuDefinition

    original = MenuDefinition.model_validate(payload)
    form = definition_to_form(original)
    _, node = _node(form, "info")
    assert [o.section for o in node.options] == ["Información", "Ayuda", "Ayuda"]
    assert node.options[1].description == "Mapa"
    result = validate_form(form)
    assert result.definition is not None
    assert result.definition.model_dump(mode="json") == original.model_dump(mode="json")


def test_empty_form_is_one_text_step_that_asks_for_its_text() -> None:
    form = empty_form()
    assert [n.kind for n in form.nodes] == [KIND_TEXT]
    result = validate_form(form)
    assert result.definition is None
    assert result.form.nodes[0].errors["body"] == "Obligatorio."
    filled = replace(form, nodes=[replace(form.nodes[0], body="Hola, ¿en qué te ayudo?")])
    assert validate_form(filled).definition is not None


def test_optional_fields_serialize_as_none() -> None:
    payload = form_to_payload(_demo_form())
    assert payload["nodes"]["inicio"]["header"] is None
    assert payload["nodes"]["horario"]["next"] is None
    assert payload["entry"]["fallback_node"] == "persona"
    no_fallback = replace(_demo_form(), fallback_node=NONE_VALUE, welcome="  ")
    payload = form_to_payload(no_fallback)
    assert payload["entry"]["fallback_node"] is None
    assert payload["entry"]["welcome"] is None


def test_rename_carries_every_reference_along() -> None:
    form = _demo_form()
    index, _ = _node(form, "productos")
    renamed = rename_node(form, index, "carta")
    result = validate_form(renamed)
    assert result.error_count == 0
    assert result.definition is not None
    assert "carta" in result.definition.nodes and "productos" not in result.definition.nodes
    assert result.definition.entry.keywords["menu"] == "carta"
    assert result.definition.nodes["agregado"].options[0].next == "carta"  # type: ignore[union-attr]


def test_rename_into_a_collision_does_not_steal_references() -> None:
    form = _demo_form()
    index, _ = _node(form, "horario")
    collided = rename_node(form, index, "ubicacion")
    result = validate_form(collided)
    assert result.definition is None
    assert result.form.nodes[index].errors["node_id"] == "Ya hay otro paso con este identificador."
    # The keyword still points at the old id, now flagged rather than redirected.
    horario_kw = next(k for k in result.form.keywords if k.word == "horario")
    assert horario_kw.node == "horario" and horario_kw.errors["node"] == "Elige un paso que exista."


def test_change_kind_keeps_text_and_options() -> None:
    form = _demo_form()
    _, inicio = _node(form, "inicio")
    as_list = change_kind(inicio, KIND_LIST)
    assert as_list.kind == KIND_LIST
    assert as_list.body == inicio.body
    assert [o.label for o in as_list.options] == [o.label for o in inicio.options]
    assert all(o.section for o in as_list.options)
    assert as_list.button_label == "Ver opciones"
    summary = change_kind(new_node(KIND_TEXT, "x"), KIND_ORDER_SUMMARY)
    assert "{total}" in summary.body and summary.confirm_label == "Confirmar"


def test_new_option_ids_are_unique_inside_the_step() -> None:
    node = new_node(KIND_BUTTONS, "b")
    first = new_option(node)
    second = new_option(replace(node, options=[first]))
    assert first.option_id != second.option_id


# --- 3. validation: every Meta limit, in Spanish, on the field ----------------------------


def test_button_limits() -> None:
    form = _demo_form()
    _, inicio = _node(form, "inicio")
    long_label = [replace(inicio.options[0], label="x" * 25), *inicio.options[1:]]
    result = validate_form(_with_node(form, "inicio", options=long_label))
    assert result.form.nodes[0].options[0].errors["label"] == "Máximo 20 caracteres (tiene 25)."
    assert result.form.nodes[0].has_issue
    assert result.definition is None

    four = [*inicio.options, replace(inicio.options[0], option_id="extra")]
    result = validate_form(_with_node(form, "inicio", options=four))
    assert _node_errors(result.form, "inicio")["options"] == "Máximo 3 botones."


def test_list_limits() -> None:
    form = _demo_form()
    rows = [
        OptionForm(
            option_id=f"r{i}", label=f"Fila {i}", description="", next="horario", section="S"
        )
        for i in range(11)
    ]
    result = validate_form(_with_node(form, "info", kind=KIND_LIST, options=rows))
    assert _node_errors(result.form, "info")["options"].startswith("Una lista admite máximo 10")

    rows = [
        OptionForm(
            option_id="r1", label="y" * 30, description="d" * 80, next="horario", section="S" * 30
        )
    ]
    result = validate_form(
        _with_node(form, "info", kind=KIND_LIST, options=rows, button_label="b" * 21)
    )
    _, info = _node(result.form, "info")
    assert info.options[0].errors["label"] == "Máximo 24 caracteres (tiene 30)."
    assert info.options[0].errors["description"] == "Máximo 72 caracteres (tiene 80)."
    assert info.options[0].errors["section"] == "Máximo 24 caracteres (tiene 30)."
    assert info.errors["button_label"] == "Máximo 20 caracteres (tiene 21)."


def test_body_header_and_footer_limits() -> None:
    form = _with_node(_demo_form(), "inicio", body="b" * 1100, header="h" * 61, footer="f" * 70)
    errors = _node_errors(validate_form(form).form, "inicio")
    assert errors["body"] == "Máximo 1024 caracteres (tiene 1100)."
    assert errors["header"] == "Máximo 60 caracteres (tiene 61)."
    assert errors["footer"] == "Máximo 60 caracteres (tiene 70)."


def test_ice_breaker_limits() -> None:
    form = _demo_form()
    long_text = [replace(form.ice_breakers[0], text="v" * 81), *form.ice_breakers[1:]]
    result = validate_form(replace(form, ice_breakers=long_text))
    assert result.form.ice_breakers[0].errors["text"] == "Máximo 80 caracteres (tiene 81)."

    emoji = [replace(form.ice_breakers[0], text="Ver menú 🍔"), *form.ice_breakers[1:]]
    result = validate_form(replace(form, ice_breakers=emoji))
    assert result.form.ice_breakers[0].errors["text"] == "Meta no admite emojis aquí."

    five = [*form.ice_breakers, IceBreakerForm(text="Promos", node="productos")]
    result = validate_form(replace(form, ice_breakers=five))
    assert result.form.entry_errors["ice_breakers"] == "Máximo 4 atajos."


def test_command_limits() -> None:
    form = _demo_form()
    bad = [replace(form.commands[0], name="n" * 33, hint="h" * 257), *form.commands[1:]]
    result = validate_form(replace(form, commands=bad))
    assert result.form.commands[0].errors["name"] == "Máximo 32 caracteres (tiene 33)."
    assert result.form.commands[0].errors["hint"] == "Máximo 256 caracteres (tiene 257)."

    spaced = [replace(form.commands[0], name="ver menu"), *form.commands[1:]]
    result = validate_form(replace(form, commands=spaced))
    assert result.form.commands[0].errors["name"] == "Una sola palabra, sin la barra «/»."

    many = [CommandForm(name=f"c{i}", hint="Ayuda", node="persona") for i in range(31)]
    result = validate_form(replace(form, commands=many))
    assert result.form.entry_errors["commands"] == "Máximo 30 comandos."


def test_welcome_limit_and_keywords() -> None:
    form = replace(_demo_form(), welcome="w" * 1030)
    assert (
        validate_form(form).form.entry_errors["welcome"] == "Máximo 1024 caracteres (tiene 1030)."
    )

    dup = [*_demo_form().keywords, KeywordForm(word="MENU", node="productos")]
    result = validate_form(replace(_demo_form(), keywords=dup))
    assert result.form.keywords[-1].errors["word"] == "Ya está arriba (sin contar tildes)."
    empty = [*_demo_form().keywords, KeywordForm(word=" ", node="productos")]
    assert validate_form(replace(_demo_form(), keywords=empty)).form.keywords[-1].errors == {
        "word": "Obligatorio."
    }


def test_order_summary_and_collect_rules() -> None:
    form = _with_node(_demo_form(), "resumen", body="Sin total")
    assert _node_errors(validate_form(form).form, "resumen")["body"] == (
        "Incluye {total} en el texto: ahí va el total del pedido."
    )
    form = _with_node(_demo_form(), "direccion", field_name="Dirección")
    assert _node_errors(validate_form(form).form, "direccion")["field_name"].startswith(
        "Solo minúsculas"
    )
    # «Confirmar» must reach a person.
    form = _with_node(_demo_form(), "direccion", next="cancelado")
    errors = _node_errors(validate_form(form).form, "resumen")
    assert errors["confirm_next"].startswith("«Confirmar» debe terminar en «Pasar a una persona»")


def test_products_page_size() -> None:
    form = _with_node(_demo_form(), "productos", page_size="abc")
    assert _node_errors(validate_form(form).form, "productos")["page_size"] == "Escribe un número."
    form = _with_node(_demo_form(), "productos", page_size="11")
    assert _node_errors(validate_form(form).form, "productos")["page_size"] == "Máximo 10."


def test_references_and_fallback() -> None:
    form = _demo_form()
    index, _ = _node(form, "persona")
    removed = replace(form, nodes=[n for k, n in enumerate(form.nodes) if k != index])
    result = validate_form(removed)
    assert result.form.entry_errors["fallback_node"] == "Elige un paso que exista."
    _, inicio = _node(result.form, "inicio")
    assert inicio.options[2].errors["next"] == "Elige un paso que exista."

    not_handoff = replace(form, fallback_node="horario")
    assert validate_form(not_handoff).form.entry_errors["fallback_node"] == (
        "Debe ser un paso «Pasar a una persona»."
    )
    bad_start = replace(form, start_node=NONE_VALUE)
    assert validate_form(bad_start).form.entry_errors["start_node"] == "Elige un paso que exista."


def test_step_ids_and_cycles() -> None:
    form = _demo_form()
    index, _ = _node(form, "horario")
    form = rename_node(form, index, "Horario Abierto")
    result = validate_form(form)
    assert result.form.nodes[index].errors["node_id"].startswith("Solo minúsculas")
    assert result.definition is None
    looped = _with_node(_demo_form(), "horario", next="ubicacion")
    looped = _with_node(looped, "ubicacion", next="horario")
    result = validate_form(looped)
    assert result.definition is None
    assert any("círculo" in n.errors.get("next", "") for n in result.form.nodes)


def test_two_order_summaries_is_a_menu_level_error() -> None:
    form = _demo_form()
    _, resumen = _node(form, "resumen")
    twice = replace(form, nodes=[*form.nodes, replace(resumen, node_id="resumen_2")])
    result = validate_form(twice)
    assert result.form.menu_errors == ["Solo puede haber un paso «Resumen del pedido» por menú."]


def test_issue_summary_copy() -> None:
    assert issues_summary(0) == ""
    assert issues_summary(1) == "Hay 1 cosa por corregir antes de guardar."
    assert issues_summary(3) == "Hay 3 cosas por corregir antes de guardar."


def test_menu_name_rules() -> None:
    assert validate_menu_name("  ", []) == "Ponle un nombre al menú."
    assert validate_menu_name("Principal", ["principal"]) == (
        "Ya hay un menú con ese nombre en este número."
    )
    assert validate_menu_name("Principal", ["Otro"]) == ""


# --- 4. the phone preview over the real engine -------------------------------------------


def _choice(messages: list[PreviewMessageVM], title: str) -> PreviewChoiceVM:
    for message in reversed(messages):
        for choice in message.choices:
            if choice.title == title:
                return choice
    raise AssertionError(title)


def _inbound(choice: PreviewChoiceVM) -> Inbound:
    if choice.reply_kind == REPLY_LIST:
        return Inbound.list_reply(choice.reply_id)
    return Inbound.button_reply(choice.reply_id)


def test_preview_walks_the_demo_menu_to_a_confirmed_order() -> None:
    definition = BIANKI_DEMO_MENU
    state = ThreadMenuState()
    transcript: list[PreviewMessageVM] = []

    def turn(inbound: Inbound, shown: str) -> None:
        nonlocal state
        result = preview_turn(
            definition, state, inbound, CATALOG, shown_text=shown, start_index=len(transcript)
        )
        transcript.extend(result.messages)
        state = result.state

    turn(Inbound.text("hola", first_message=True), "hola")
    assert transcript[0].direction == "in" and transcript[0].text == "hola"
    assert transcript[1].text.startswith("¡Hola! Soy el asistente de Bianki")
    buttons = transcript[2]
    assert [c.title for c in buttons.choices] == [
        "Ver menú y pedir",
        "Horario y ubicación",
        "Hablar con alguien",
    ]
    assert buttons.choices[0].reply_kind == REPLY_BUTTON

    turn(_inbound(_choice(transcript, "Ver menú y pedir")), "Ver menú y pedir")
    products = transcript[-1]
    assert products.is_list and products.list_label == "Ver productos"
    burger = _choice(transcript, "Hamburguesa clásica")
    assert burger.description == "COP 18.000" and burger.section == "Hamburguesas"

    turn(_inbound(burger), burger.title)
    assert order_lines(state) == ["1 x Hamburguesa clásica", "Total: COP 18.000"]
    turn(_inbound(_choice(transcript, "Ver mi pedido")), "Ver mi pedido")
    assert "Total: COP 18.000" in transcript[-1].text
    turn(_inbound(_choice(transcript, "Confirmar")), "Confirmar")
    assert transcript[-1].text.startswith("¿A qué dirección")
    turn(Inbound.text("Calle 10 # 5-20, Centro"), "Calle 10 # 5-20, Centro")

    note = transcript[-1]
    assert note.direction == "note"
    assert note.text.startswith("Pasa a una persona (pedido confirmado)")
    assert "1 x Hamburguesa clásica" in note.text and "Total: COP 18.000" in note.text
    assert "direccion: Calle 10 # 5-20, Centro" in note.text
    assert state.paused
    keys = [m.key for m in transcript]
    assert len(keys) == len(set(keys)), "bubble keys must be unique for rx.foreach"


def test_preview_with_an_empty_catalog_uses_the_empty_text() -> None:
    result = preview_turn(
        BIANKI_DEMO_MENU,
        ThreadMenuState(),
        Inbound.text("menú", first_message=False),
        (),
        shown_text="menú",
        start_index=0,
    )
    assert result.messages[-1].text.startswith("Por ahora no tenemos productos cargados")


def test_preview_handoff_from_a_keyword() -> None:
    result = preview_turn(
        BIANKI_DEMO_MENU,
        ThreadMenuState(),
        Inbound.text("persona"),
        CATALOG,
        shown_text="persona",
        start_index=0,
    )
    assert result.handed_off
    assert result.messages[-1].text.startswith("Pasa a una persona (el cliente pidió una persona)")


# --- 5. publish banner copy ---------------------------------------------------------------


def test_publish_notice_copy() -> None:
    assert publish_notice(graph_ok=True)[1] == "ok"
    message, tone = publish_notice(graph_ok=False, code=100)
    assert message == "Publicado en Qualify; WhatsApp no aceptó los atajos (código 100)."
    assert tone == "warn"
    message, tone = publish_notice(graph_ok=False, code=190, is_auth_error=True)
    assert message.startswith("Publicado en Qualify; WhatsApp no aceptó los atajos (código 190).")
    assert tone == "error"
    assert "emojis" in publish_notice(graph_ok=False, rejected_locally=True)[0]
    assert "no hubo respuesta" in publish_notice(graph_ok=False, is_transport=True)[0]


@pytest.mark.parametrize("kind", [KIND_TEXT, KIND_BUTTONS, KIND_LIST, KIND_HANDOFF])
def test_new_nodes_carry_their_kind_label(kind: str) -> None:
    assert new_node(kind, "x").kind_label
