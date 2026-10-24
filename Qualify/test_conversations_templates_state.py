"""`ConversationsState`'s message templates (m-24789472, PR 1), offline.

The real `ConversationsGateway` over the backend's memory repositories (the `World` of
`test_conversations_provider.py`), with the session's tenant and user stubbed on the
CLASS (`_tenant`, `_acting_user`) and the background handlers driven through `.fn(state)`
— the same harness as `test_catalog_state.py`.

Pins:
1. Opening the picker loads the account's library once.
2. Picking a template REPLACES the box with its text for this person, closes the picker,
   remembers what is left to fill — and queues nothing (the outbox stays empty).
3. A suggestion in the box is set aside (discarded) when a template replaces it.
4. A template id the library does not hold, or a closed composer, is refused first.
5. The manager: create, the service's inline refusal, edit, reorder, delete.
6. Switching accounts forgets the previous account's library.
"""

from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID

import pytest
from qualify_api.conversations.drafts import DraftStatus
from qualify_api.conversations.templates import MESSAGES

from . import conversations_state as state_module
from .conversations_state import ConversationsState
from .conversations_vm import EMPTY_THREAD, DraftVM
from .test_conversations_provider import (
    CONNECTION,
    OTHER_CONNECTION,
    TENANT,
    USER,
    World,
    _account,
)


async def _drain(events: Any) -> list[Any]:
    """Run a handler that is an async generator (or a plain coroutine)."""
    if hasattr(events, "__aiter__"):
        return [event async for event in events]
    await events
    return []


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    return _install(monkeypatch, World())


def _install(monkeypatch: pytest.MonkeyPatch, world: World) -> World:
    """Point the state at `world`'s gateway, with this tenant and user."""

    async def tenant(self: ConversationsState) -> UUID:
        return TENANT

    async def acting_user(self: ConversationsState, tenant_id: UUID) -> UUID:
        return USER

    monkeypatch.setattr(ConversationsState, "_tenant", tenant)
    monkeypatch.setattr(ConversationsState, "_acting_user", acting_user)
    monkeypatch.setattr(state_module, "gateway", lambda: world.gateway)
    return world


def _open_state(world: World) -> tuple[ConversationsState, UUID]:
    thread = world.inbound()
    state = ConversationsState()
    state.accounts = [_account(CONNECTION), _account(OTHER_CONNECTION, label="@otra")]
    state.selected_connection_id = str(CONNECTION)
    state.rows = [dataclasses.replace(EMPTY_THREAD, thread_id=str(thread), window_open=True)]
    state.open_thread_id = str(thread)
    return state, thread


async def _loaded(world: World) -> tuple[ConversationsState, UUID]:
    state, thread = _open_state(world)
    assert state.set_templates_menu_open(True) is ConversationsState.load_templates
    await _drain(ConversationsState.load_templates.fn(state))
    return state, thread


async def test_opening_the_picker_loads_the_library_once(world: World) -> None:
    state, _thread = await _loaded(world)
    assert state.templates_menu_open is True
    assert [t.title for t in state.templates] == ["Saludo", "Precio", "Horario", "Catálogo"]
    assert state.templates_ready and state.templates_counter == "4/50"
    state.set_templates_menu_open(False)
    assert state.set_templates_menu_open(True) is None  # already loaded


async def test_picking_replaces_the_box_and_queues_nothing(world: World) -> None:
    state, _thread = await _loaded(world)
    state.draft_text = "algo que escribí antes"
    price = next(t for t in state.templates if t.title == "Precio")

    await _drain(ConversationsState.apply_template.fn(state, price.template_id))

    assert state.draft_text.startswith("Te comparto el precio: [precio].")
    assert state.applied_blanks == ["[precio]"]
    assert state.template_fill_notice == "Rellena [precio] antes de enviar."
    assert state.templates_menu_open is False
    assert world.outbox.rows == {} and world.sender.sent == []

    state.draft_text = state.draft_text.replace("[precio]", "20 dólares")
    assert state.template_fill_notice == ""


async def test_a_missing_name_is_named_in_the_notice(world: World) -> None:
    state, _thread = await _loaded(world)
    greeting = next(t for t in state.templates if t.title == "Saludo")
    await _drain(ConversationsState.apply_template.fn(state, greeting.template_id))
    assert "Bianki" in state.draft_text
    assert state.template_fill_notice.startswith("Completa {nombre} antes de enviar")


async def test_a_suggestion_in_the_box_is_set_aside(world: World) -> None:
    state, thread = await _loaded(world)
    draft = world.drafts.suggest(tenant_id=TENANT, thread_id=thread)
    state.suggestion = DraftVM(
        draft_id=str(draft.id), text=draft.generated_text, needs_review=False, note=""
    )
    state.draft_text = draft.generated_text
    greeting = next(t for t in state.templates if t.title == "Saludo")

    await _drain(ConversationsState.apply_template.fn(state, greeting.template_id))

    assert state.suggestion.draft_id == ""
    decided = world.draft_rows.get(tenant_id=TENANT, draft_id=draft.id)
    assert decided is not None and decided.status is DraftStatus.DISCARDED


async def test_an_unknown_template_id_is_refused_before_any_call(world: World) -> None:
    state, _thread = await _loaded(world)
    state.draft_text = "lo mío"
    await _drain(ConversationsState.apply_template.fn(state, "no-es-de-esta-lista"))
    assert state.draft_text == "lo mío"
    assert state.applying_template_id == ""


async def test_a_closed_composer_cannot_use_a_template(world: World) -> None:
    state, _thread = await _loaded(world)
    state.rows = [dataclasses.replace(state.rows[0], window_open=False)]
    await _drain(ConversationsState.apply_template.fn(state, state.templates[0].template_id))
    assert state.draft_text == ""


async def test_the_manager_creates_refuses_edits_reorders_and_deletes(world: World) -> None:
    state, _thread = _open_state(world)
    assert state.open_templates_manager() is ConversationsState.load_templates
    await _drain(ConversationsState.load_templates.fn(state))
    assert state.templates_manager_open

    # The service's refusal shows inline, as it comes.
    state.start_new_template()
    state.set_template_form_title("   ")
    state.set_template_form_body("Enviamos a todo el país.")
    await _drain(ConversationsState.save_template.fn(state))
    assert state.template_form_error == MESSAGES["title_empty"]
    assert state.template_form_open and len(state.templates) == 4

    state.set_template_form_title("Envíos")
    assert state.template_form_error == ""
    await _drain(ConversationsState.save_template.fn(state))
    assert [t.title for t in state.templates][-1] == "Envíos"
    assert state.template_form_open is False and state.templates_counter == "5/50"

    envios = state.templates[-1]
    state.start_edit_template(envios.template_id)
    assert state.template_form_heading == "Editar plantilla"
    state.set_template_form_body("Enviamos a todo Uruguay.")
    await _drain(ConversationsState.save_template.fn(state))
    assert state.templates[-1].body == "Enviamos a todo Uruguay."

    await _drain(ConversationsState.move_template.fn(state, envios.template_id, -1))
    assert [t.title for t in state.templates][-2:] == ["Envíos", "Catálogo"]
    first = state.templates[0].template_id
    await _drain(ConversationsState.move_template.fn(state, first, -1))  # already first
    assert state.templates[0].template_id == first

    state.ask_delete_template(envios.template_id)
    assert state.template_confirm_delete_id == envios.template_id
    await _drain(ConversationsState.confirm_delete_template.fn(state))
    assert "Envíos" not in [t.title for t in state.templates]
    assert state.template_confirm_delete_id == ""
    assert world.outbox.rows == {}


async def test_switching_accounts_forgets_the_library(world: World) -> None:
    state, _thread = await _loaded(world)
    state.select_account(str(OTHER_CONNECTION))
    assert state.templates == [] and not state.templates_ready
    assert state.templates_menu_open is False


# --- quick replies and messages with buttons (m-24789472, phase 3) -----------------------


def _with_features(monkeypatch: pytest.MonkeyPatch, *names: str) -> World:
    from qualify_api.followups.capabilities import Capability

    return _install(monkeypatch, World(switched_on=frozenset(Capability(n) for n in names)))


def _features_from(state: ConversationsState, world: World) -> None:
    """What `load_accounts` reads once: the deployment's switches."""
    state.quick_replies_feature, state.buttons_feature = world.gateway.features()


def _type_option(state: ConversationsState, title: str) -> None:
    state.set_quick_reply_input(title)
    state.add_quick_reply({})


def test_the_fourteenth_quick_reply_is_refused_in_the_composer(monkeypatch) -> None:
    from qualify_api.conversations.interactive import MESSAGES as INTERACTIVE

    world = _with_features(monkeypatch, "quick_replies")
    state, _thread = _open_state(world)
    _features_from(state, world)
    for i in range(13):
        _type_option(state, f"Opción {i}")
    assert len(state.quick_replies) == 13 and state.quick_replies_count_label == "13/13"
    assert state.quick_replies_at_limit

    _type_option(state, "Una más")
    assert len(state.quick_replies) == 13
    assert state.quick_reply_error == INTERACTIVE["quick_replies_too_many"]
    assert state.quick_reply_input == "Una más"  # kept, so the person can fix it


def test_a_twenty_one_character_option_is_refused(monkeypatch) -> None:
    from qualify_api.conversations.interactive import MESSAGES as INTERACTIVE

    world = _with_features(monkeypatch, "quick_replies")
    state, _thread = _open_state(world)
    _features_from(state, world)
    _type_option(state, "x" * 21)
    assert state.quick_replies == []
    assert state.quick_reply_error == INTERACTIVE["quick_reply_title_too_long"]
    state.remove_quick_reply(0)  # nothing to remove: no error, no change
    assert state.quick_replies == []


def test_quick_replies_are_off_with_the_reason_while_the_feature_is(world: World) -> None:
    state, _thread = _open_state(world)
    _features_from(state, world)
    assert not state.can_add_quick_replies
    assert state.quick_replies_feature.state_label == "Por verificar"
    _type_option(state, "Sí")
    assert state.quick_replies == [] and state.quick_replies_to_send == []


async def test_sending_passes_the_quick_replies_to_reply_text(monkeypatch) -> None:
    from qualify_api.conversations.interactive import has_quick_replies

    world = _with_features(monkeypatch, "quick_replies")
    state, _thread = _open_state(world)
    _features_from(state, world)
    state.draft_text = "¿Te sirve el envío?"
    _type_option(state, "Sí")
    _type_option(state, "No")
    assert state.can_send

    await _drain(ConversationsState.send_reply.fn(state))

    (row,) = world.outbox.rows.values()
    assert has_quick_replies(row.payload)
    assert [q["title"] for q in row.payload["message"]["quick_replies"]] == ["Sí", "No"]
    assert row.approved_by_user_id == USER
    assert state.quick_replies == [] and state.draft_text == ""


async def test_quick_replies_need_a_text_to_hang_under(monkeypatch) -> None:
    world = _with_features(monkeypatch, "quick_replies")
    state, _thread = _open_state(world)
    _features_from(state, world)
    _type_option(state, "Sí")
    assert not state.can_send and "respuestas rápidas" in state.compose_error


async def _template_with_buttons(world: World, state: ConversationsState) -> None:
    from .conversations_vm import ButtonVM

    world.gateway.create_template(
        TENANT,
        CONNECTION,
        USER,
        "Pedido",
        "¿Cómo quieres pedir?",
        [
            ButtonVM(kind="postback", title="Por aquí"),
            ButtonVM(kind="web_url", title="Ver catálogo", url="https://bianki.co/catalogo"),
        ],
    )
    state.set_templates_menu_open(True)
    await _drain(ConversationsState.load_templates.fn(state))
    pedido = next(t for t in state.templates if t.title == "Pedido")
    assert pedido.buttons_label == "Con botones: Por aquí · Ver catálogo"
    await _drain(ConversationsState.apply_template.fn(state, pedido.template_id))


async def test_a_template_with_buttons_is_sent_with_reply_buttons(monkeypatch) -> None:
    from qualify_api.conversations.interactive import template_payload

    world = _with_features(monkeypatch, "structured_templates", "quick_replies")
    state, _thread = _open_state(world)
    _features_from(state, world)
    await _template_with_buttons(world, state)
    assert [b.title for b in state.applied_buttons] == ["Por aquí", "Ver catálogo"]
    assert state.buttons_will_send and not state.can_add_quick_replies

    state.set_draft_text("¿Cómo quieres pedir tu combo?")  # the edited text is what goes
    await _drain(ConversationsState.send_reply.fn(state))

    (row,) = world.outbox.rows.values()
    body = template_payload(row.payload)
    assert body is not None and body["text"] == "¿Cómo quieres pedir tu combo?"
    assert [b["title"] for b in body["buttons"]] == ["Por aquí", "Ver catálogo"]
    assert state.applied_buttons == []


async def test_a_long_text_with_buttons_offers_to_send_without_them(monkeypatch) -> None:
    world = _with_features(monkeypatch, "structured_templates")
    state, _thread = _open_state(world)
    _features_from(state, world)
    await _template_with_buttons(world, state)
    state.set_draft_text("x" * 641)
    assert not state.can_send and "640" in state.compose_hint

    state.drop_applied_buttons()
    assert state.can_send and not state.buttons_will_send


async def test_with_buttons_off_the_text_goes_alone_after_a_warning(world: World) -> None:
    from qualify_api.conversations.interactive import is_structured_template

    state, _thread = _open_state(world)
    _features_from(state, world)
    await _template_with_buttons(world, state)
    assert state.buttons_dropped_notice and not state.buttons_will_send

    await _drain(ConversationsState.send_reply.fn(state))

    (row,) = world.outbox.rows.values()
    assert not is_structured_template(row.payload)
    assert row.payload["message"]["text"] == "¿Cómo quieres pedir?"


async def test_the_form_shows_the_640_error_inline(world: World) -> None:
    state, _thread = _open_state(world)
    state.open_templates_manager()
    await _drain(ConversationsState.load_templates.fn(state))
    state.start_new_template()
    state.set_template_form_title("Largo")
    state.set_template_form_body("x" * 641)
    assert state.template_form_body_error == ""  # no buttons: 1000 is the limit
    assert state.template_body_counter == "641/1000"

    state.add_template_button()
    state.set_template_button_title(0, "Sí")
    assert state.template_form_body_error == MESSAGES["body_too_long_for_buttons"]
    assert state.template_body_counter == "641/640"

    await _drain(ConversationsState.save_template.fn(state))
    assert state.template_form_error == MESSAGES["body_too_long_for_buttons"]
    assert "Largo" not in [t.title for t in state.templates]


async def test_the_form_edits_kinds_and_keeps_at_most_three_buttons(world: World) -> None:
    state, _thread = _open_state(world)
    state.open_templates_manager()
    await _drain(ConversationsState.load_templates.fn(state))
    state.start_new_template()
    for _ in range(4):
        state.add_template_button()
    assert len(state.template_form_buttons) == 3 and state.template_form_buttons_full

    state.set_template_button_kind(1, "web_url")
    state.set_template_button_url(1, " https://bianki.co ")
    assert state.template_form_buttons[1].url == "https://bianki.co"
    state.set_template_button_kind(1, "postback")
    assert state.template_form_buttons[1].url == ""  # a reply button has no link
    state.set_template_button_kind(1, "teletransporte")  # not a kind: ignored
    assert state.template_form_buttons[1].kind == "postback"
    state.remove_template_button(0)
    assert len(state.template_form_buttons) == 2
