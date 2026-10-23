"""m-24848536: the automatic menu in four steps, with no technical identifier.

Pure tests over `whatsapp_menu_vm.guided_*` (the same form the advanced editor edits)
plus the state's step navigation: «Paso N de 4», «Atrás» without losing data, step ids
generated and never shown, the measurement log on publish.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from qualify_api.whatsapp.menus.engine import CatalogItem
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU

from . import whatsapp_menu_state as module
from .whatsapp_menu_provider import MenuDetail, PublishOutcome
from .whatsapp_menu_state import WhatsAppMenuState
from .whatsapp_menu_vm import (
    ACTION_MORE,
    ACTION_PERSON,
    ACTION_PRODUCTS,
    ACTION_TEXT,
    ADDRESS_ASK,
    ADDRESS_SKIP,
    KIND_COLLECT,
    KIND_HANDOFF,
    KIND_PRODUCTS,
    PUBLISH_OK,
    MenuForm,
    MenuSummaryVM,
    MenuVersionVM,
    catalog_rows,
    definition_to_form,
    empty_form,
    guided_add_button,
    guided_remove_button,
    guided_review,
    guided_set_address,
    guided_set_address_prompt,
    guided_set_button_action,
    guided_set_button_label,
    guided_set_button_text,
    guided_set_greeting,
    guided_step_label,
    guided_use_buttons,
    guided_view,
    node_choices,
    validate_form,
)

_GENERATED_ID = re.compile(r"^[a-z0-9-]+-[0-9a-f]{4}\d*$")


def _demo() -> MenuForm:
    return definition_to_form(BIANKI_DEMO_MENU)


def _view(form: MenuForm):  # type: ignore[no-untyped-def]
    result = validate_form(form)
    return guided_view(result.form, result.error_count), result


# --- the template, read as four steps -----------------------------------------------------


def test_the_template_reads_as_four_steps() -> None:
    view, result = _view(_demo())
    assert result.error_count == 0 and view.hidden_issues == 0
    assert view.greeting == BIANKI_DEMO_MENU.entry.welcome
    assert view.uses_buttons and view.question == "¿Qué quieres hacer?"
    assert [(b.label, b.action) for b in view.buttons] == [
        ("Ver menú y pedir", ACTION_PRODUCTS),
        ("Horario y ubicación", ACTION_MORE),
        ("Hablar con alguien", ACTION_PERSON),
    ]
    assert view.buttons[1].more_summary == "Horario · Ubicación · Volver"
    assert view.buttons_full and view.has_products and view.has_order
    assert view.address_choice == ADDRESS_ASK


def test_step_label_says_n_of_4() -> None:
    assert guided_step_label(1) == "Paso 1 de 4"
    assert guided_step_label(4) == "Paso 4 de 4"


# --- step 1 and 2 -------------------------------------------------------------------------


def test_greeting_and_button_label_edit_the_menu() -> None:
    form = guided_set_greeting(_demo(), "¡Hola! Bienvenido a Polette.")
    form = guided_set_button_label(form, 0, "Ver la carta")
    _view_, result = _view(form)
    assert result.definition is not None
    assert result.definition.entry.welcome == "¡Hola! Bienvenido a Polette."
    assert result.definition.nodes["inicio"].options[0].label == "Ver la carta"  # type: ignore[union-attr]
    # the button keeps its id: renaming it never breaks what WhatsApp echoes back
    assert result.definition.nodes["inicio"].options[0].id == "ver_menu"  # type: ignore[union-attr]


def test_a_button_can_answer_with_a_message_in_a_generated_step() -> None:
    form = guided_set_button_action(_demo(), 1, ACTION_TEXT)
    view, result = _view(form)
    assert view.buttons[1].action == ACTION_TEXT
    assert view.buttons[1].text_error == "Obligatorio."  # written right where it is typed
    assert result.definition is None
    form = guided_set_button_text(form, 1, "Abrimos de 12:00 a 22:00 en la Calle 10.")
    view, result = _view(form)
    assert result.definition is not None and view.hidden_issues == 0
    target = result.definition.nodes["inicio"].options[1].next  # type: ignore[union-attr]
    assert _GENERATED_ID.match(target), target
    assert result.definition.nodes[target].title == "Horario y ubicación"
    # the old sub-menu stays (keywords and shortcuts still reach it): nothing is deleted
    assert "info" in result.definition.nodes


def test_choosing_message_twice_does_not_pile_up_steps() -> None:
    once = guided_set_button_action(_demo(), 1, ACTION_TEXT)
    twice = guided_set_button_action(once, 1, ACTION_TEXT)
    assert len(twice.nodes) == len(once.nodes)


def test_buttons_are_capped_at_three_and_never_drop_to_zero() -> None:
    full = _demo()
    assert guided_add_button(full) == full
    form = guided_remove_button(guided_remove_button(full, 2), 1)
    assert len(guided_view(validate_form(form).form).buttons) == 1
    assert guided_remove_button(form, 0) == form
    grown = guided_add_button(form)
    view, _ = _view(grown)
    assert len(view.buttons) == 2 and view.buttons[1].action == ACTION_PERSON
    assert view.buttons[1].label_error == "Obligatorio."


def test_out_of_range_and_unknown_inputs_change_nothing() -> None:
    form = _demo()
    assert guided_set_button_label(form, 7, "x") == form
    assert guided_set_button_action(form, 0, "teleport") == form
    assert guided_set_button_action(form, -1, ACTION_TEXT) == form
    assert guided_set_address(form, "maybe") == form


# --- an empty menu grows into the template's shape ----------------------------------------


def test_an_empty_menu_gets_buttons_products_and_a_person_with_generated_ids() -> None:
    form = guided_use_buttons(empty_form())
    form = guided_set_button_action(form, 0, ACTION_PRODUCTS)
    view, result = _view(form)
    assert result.error_count == 0, result.form
    assert result.definition is not None
    assert view.uses_buttons and view.has_products and view.has_order
    kinds = {n.kind for n in result.definition.nodes.values()}
    assert {KIND_PRODUCTS, KIND_HANDOFF, KIND_COLLECT, "order_summary"} <= kinds
    for node_id in result.definition.nodes:
        assert node_id == "inicio" or _GENERATED_ID.match(node_id), node_id


# --- step 3: the address ------------------------------------------------------------------


def test_address_can_be_skipped_and_asked_again_without_losing_the_text() -> None:
    form = guided_set_address_prompt(_demo(), "¿A dónde te lo mandamos?")
    skipped = guided_set_address(form, ADDRESS_SKIP)
    view, result = _view(skipped)
    assert view.address_choice == ADDRESS_SKIP and result.definition is not None
    assert result.definition.nodes["resumen"].confirm_next == "pedido_confirmado"  # type: ignore[union-attr]
    asked = guided_set_address(skipped, ADDRESS_ASK)
    view, result = _view(asked)
    assert view.address_choice == ADDRESS_ASK
    assert view.address_prompt == "¿A dónde te lo mandamos?"
    assert len(asked.nodes) == len(form.nodes)  # the same question step came back


def test_catalog_rows_show_the_price_or_say_there_is_none() -> None:
    rows = catalog_rows(
        (
            CatalogItem("p1", "Shawarma mixto", Decimal("18000"), "COP", "Shawarmas"),
            CatalogItem("p2", "Ensalada", None, None, None),
        )
    )
    assert [(r.name, r.price) for r in rows] == [
        ("Shawarma mixto", "COP 18.000"),
        ("Ensalada", "Sin precio"),
    ]


# --- step 4 and «no identifiers» ----------------------------------------------------------


def test_review_says_in_words_what_the_customer_gets() -> None:
    view, _ = _view(guided_set_address(_demo(), ADDRESS_SKIP))
    lines = guided_review(view, 2)
    assert lines[0].startswith("Saluda: «¡Hola!")
    assert any("«Ver menú y pedir» muestra tus productos con su precio." == ln for ln in lines)
    assert "Muestra tus 2 productos con su precio." in lines
    assert lines[-1] == "Al confirmar un pedido, te pasa el chat para que lo cierres."
    empty = guided_review(view, 0)
    assert "Tu catálogo está vacío: agrega tus productos para que te puedan pedir." in empty


def test_nothing_the_owner_reads_is_an_identifier() -> None:
    form = guided_set_button_action(_demo(), 1, ACTION_TEXT)
    form = guided_set_button_text(form, 1, "Abrimos a las 12.")
    result = validate_form(form)
    ids = {n.node_id for n in result.form.nodes}
    option_ids = {o.option_id for n in result.form.nodes for o in n.options}
    view = guided_view(result.form, result.error_count)
    shown = [
        *guided_review(view, 3),
        *(b.label for b in view.buttons),
        *(c.label for c in node_choices(result.form.nodes)),
        *(n.label for n in result.form.nodes),
    ]
    for text in shown:
        assert text not in ids | option_ids, text
        assert not _GENERATED_ID.match(text), text
    labels = [c.label for c in node_choices(result.form.nodes)]
    assert len(labels) == len(set(labels))  # two steps never read the same


def test_the_screen_shows_no_identifier_fields() -> None:
    source = (Path(__file__).parent / "whatsapp_tab_menu.py").read_text()
    for gone in ("Identificador del paso", '"Identificador"', '"Se guarda como"', "Motivo (para"):
        assert gone not in source, gone
    for present in ("Paso ", "Atrás", "Siguiente", "Guardar y seguir después"):
        assert (
            present in source
            or present in (Path(__file__).parent / "whatsapp_menu_vm.py").read_text()
        ), present
    assert "Más opciones (avanzado)" in source
    assert "Agrega tus productos" in source and 'href="/catalog"' in source


# --- the state: navigation keeps everything; publishing is measured ------------------------

TENANT = uuid4()
CONNECTION = str(uuid4())
MENU_ID = str(uuid4())
V1, V2 = str(uuid4()), str(uuid4())


def _summary(published: bool) -> MenuSummaryVM:
    return MenuSummaryVM(
        menu_id=MENU_ID,
        name="Menú principal",
        published_label="Sin publicar",
        is_published=published,
        is_paused=False,
        status_label="Sin publicar",
        status_tone="neutral",
        updated_at="hoy",
    )


def _detail(versions: list[MenuVersionVM], published: bool = False) -> MenuDetail:
    payload = BIANKI_DEMO_MENU.model_dump(mode="json")
    return MenuDetail(
        summary=_summary(published),
        versions=versions,
        latest=BIANKI_DEMO_MENU,
        payloads={v.version_id: payload for v in versions},
    )


def _version(version_id: str, n: int, live: bool = False) -> MenuVersionVM:
    return MenuVersionVM(
        version_id=version_id,
        label=f"Versión {n}",
        created_at="hoy",
        published_at="hoy" if live else "",
        is_live=live,
    )


class _Proxy:
    def __init__(self, state: WhatsAppMenuState) -> None:
        object.__setattr__(self, "_state", state)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._state, name, value)


def _state(monkeypatch: pytest.MonkeyPatch) -> WhatsAppMenuState:
    async def session(self: object) -> tuple[str, UUID | None, str]:
        return str(TENANT), TENANT, "duena@example.com"

    async def connection_id(self: object) -> str:
        return CONNECTION

    monkeypatch.setattr(WhatsAppMenuState, "_session", session)
    monkeypatch.setattr(WhatsAppMenuState, "_connection_id", connection_id)
    monkeypatch.setattr(module, "user_id_for", lambda *a: None)
    state = WhatsAppMenuState()
    state._scope = {"phone_row_id": str(uuid4()), "brand_id": "", "brand_name": "Bianki"}
    state.menus = [_summary(False)]
    state._show_detail(_detail([_version(V1, 1)]), load_form=True)
    return state


def test_back_and_next_keep_what_was_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    assert state.guided_step == 1 and state.guided_step_text == "Paso 1 de 4"
    state.set_guided_greeting("¡Hola! Soy Polette.")
    state.guided_next()
    state.set_guided_button_label(0, "Ver helados")
    state.guided_next()
    state.guided_back()
    state.guided_back()
    assert state.guided_step == 1
    assert state.guided.greeting == "¡Hola! Soy Polette."
    assert state.guided.buttons[0].label == "Ver helados"
    state.set_advanced(True)  # the full editor shows the same form
    assert state.welcome == "¡Hola! Soy Polette."
    state.set_advanced(False)
    assert state.guided.greeting == "¡Hola! Soy Polette."
    state.guided_go(9)  # over the wire: ignored
    assert state.guided_step == 1
    for _ in range(6):
        state.guided_next()
    assert state.guided_step == 4


def test_renaming_a_step_in_the_editor_keeps_its_id(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    index = next(i for i, n in enumerate(state.nodes) if n.node_id == "productos")
    state.select_node(index)
    state.set_node_field("title", "La carta")
    state.set_node_field("node_id", "carta")  # no longer editable: ignored
    assert state.nodes[index].node_id == "productos"
    assert state.nodes[index].label == "La carta"
    assert state.error_count == 0
    state.add_node("text")
    assert _GENERATED_ID.match(state.nodes[-1].node_id)
    assert state.nodes[-1].title == "Texto"


async def test_publishing_from_the_steps_logs_how_long_it_took(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    state = _state(monkeypatch)

    def save(*a: object) -> MenuDetail:
        return _detail([_version(V2, 2), _version(V1, 1)])

    async def publish(*a: object, **kw: object) -> PublishOutcome:
        versions = [_version(V2, 2, live=True), _version(V1, 1)]
        return PublishOutcome(
            detail=_detail(versions, published=True),
            notice=PUBLISH_OK,
            tone="ok",
            graph_ok=True,
            auth_error=False,
        )

    monkeypatch.setattr(module, "save_version", save)
    monkeypatch.setattr(module, "publish_version", publish)
    state.set_guided_greeting("¡Hola!")
    with caplog.at_level(logging.INFO, logger=module.__name__):
        _ = [e async for e in WhatsAppMenuState.publish_current.fn(_Proxy(state))]  # type: ignore[attr-defined]
    assert state.just_published
    assert any(
        "whatsapp_menu_guided_publish seconds=" in r.getMessage()
        and "advanced=False" in r.getMessage()
        for r in caplog.records
    )
