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
    world = World()

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
