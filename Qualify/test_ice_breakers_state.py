"""`IceBreakersState` — «Preguntas iniciales» (m-24789472, phase 2 UI), offline.

The real `IceBreakerService` over the backend's memory repository and in-memory client
(injected with `ice_breakers_provider.set_service`), with the session's tenant, user and
account stubbed on the CLASS and the background handlers driven through `.fn(state)` —
the harness of `test_conversations_templates_state.py`. Plus the page's static pins.

Pins:
1. Opening loads the account's four defaults; an account Conversaciones does not list is
   refused before any call.
2. Editing keeps the payload; a new question goes out with `payload ""` and comes back
   named `QF_PREGUNTA_<n>`.
3. The service's refusal lands under the question its `index` names, and nothing is saved.
4. Publish/remove ask first, then reach Instagram with the person's id; publishing saves
   unsaved edits first.
5. With the capability off, publish/remove are disabled and refused; editing still works.
6. A remote failure is shown (the status says why); «Comprobar» failing shows its message.
7. Restore asks first; logout resets this state; the panel uses the design system.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from qualify_api.conversations.contracts import SourceConnection
from qualify_api.conversations.ice_breakers import (
    DEFAULT_ITEMS,
    MESSAGES,
    IceBreakerService,
    MemoryIceBreakerRepository,
)
from qualify_api.conversations.ice_breakers_client import (
    CATEGORY_META_UNAVAILABLE,
    IceBreakersApiError,
    MemoryIceBreakersClient,
)
from qualify_api.followups.capabilities import Capabilities, Capability

from . import ice_breakers_provider as provider
from .auth_state import AuthState
from .ice_breakers_state import IceBreakersState

_HERE = Path(__file__).parent
TENANT = UUID("a0000000-0000-4000-8000-0000000000a1")
CONN = UUID("c0000000-0000-4000-8000-0000000000c1")
UNKNOWN = UUID("c0000000-0000-4000-8000-0000000000c9")
USER = UUID("d0000000-0000-4000-8000-0000000000d1")
SOURCE = SourceConnection(
    tenant_id=TENANT, connection_id=CONN, external_account_id="1784", linked_page_id="page-1"
)
ON = Capabilities.from_env({"QUALIFY_ICE_BREAKERS": "on"}).availability(Capability.ICE_BREAKERS)
OFF = Capabilities.from_env({}).availability(Capability.ICE_BREAKERS)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class World:
    def __init__(self, availability: Any = ON) -> None:
        clock = _Clock()
        self.repo = MemoryIceBreakerRepository(connections={CONN: TENANT}, clock=clock)
        self.client = MemoryIceBreakersClient()
        self.service = IceBreakerService(
            repository=self.repo,
            client=self.client,
            connections=lambda t, c: SOURCE if (t, c) == (TENANT, CONN) else None,
            availability=availability,
            clock=clock,
        )


async def _drain(events: Any) -> list[Any]:
    if hasattr(events, "__aiter__"):
        return [event async for event in events]
    await events
    return []


@pytest.fixture(autouse=True)
def _session(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def tenant(self: IceBreakersState) -> UUID:
        return TENANT

    async def acting_user(self: IceBreakersState, tenant_id: UUID) -> UUID:
        return USER

    async def account(self: IceBreakersState, connection_id: str) -> tuple[str, str] | None:
        return ("@bianki", "America/Bogota") if connection_id == str(CONN) else None

    monkeypatch.setattr(IceBreakersState, "_tenant", tenant)
    monkeypatch.setattr(IceBreakersState, "_acting_user", acting_user)
    monkeypatch.setattr(IceBreakersState, "_account_context", account)
    yield
    provider.set_service(None)


def _world(availability: Any = ON) -> World:
    world = World(availability)
    provider.set_service(world.service)
    return world


async def _opened(world: World) -> IceBreakersState:
    state = IceBreakersState()
    events = await _drain(IceBreakersState.open_panel.fn(state, str(CONN)))
    assert events  # it chains the load
    await _drain(IceBreakersState.load.fn(state))
    return state


async def test_opening_loads_the_four_defaults() -> None:
    world = _world()
    state = await _opened(world)
    assert state.panel_open and state.ready
    assert state.panel_title == "Preguntas iniciales de @bianki"
    assert [r.question for r in state.rows] == [i.question for i in DEFAULT_ITEMS]
    assert state.counter == "4/4" and state.at_limit
    assert state.status.label == "Sin publicar" and not state.dirty
    assert state.available and state.can_publish and not state.can_remove
    assert world.client.calls == []  # opening never talks to Instagram


async def test_an_account_conversaciones_does_not_list_is_refused() -> None:
    world = _world()
    state = IceBreakersState()
    assert await _drain(IceBreakersState.open_panel.fn(state, str(UNKNOWN))) == []
    assert state.panel_open is False and state.connection_id == ""
    assert world.repo.rows == {}


async def test_a_new_question_is_sent_with_an_empty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world()
    state = await _opened(world)
    state.remove_question(3)
    assert state.dirty and state.counter == "3/4"
    state.add_question()
    state.set_question(3, "¿Hacen envíos a domicilio?")
    state.set_question(0, "¿Qué producto buscas?")  # text only: the payload stays

    seen: list[Any] = []
    real = provider.save_draft

    def spy(tenant_id: UUID, connection_id: UUID, items: Any, user_id: UUID | None) -> Any:
        seen.append([dict(i) for i in items])
        return real(tenant_id, connection_id, items, user_id)

    monkeypatch.setattr(provider, "save_draft", spy)
    await _drain(IceBreakersState.save.fn(state))

    assert seen[0][3] == {"question": "¿Hacen envíos a domicilio?", "payload": ""}
    assert seen[0][0]["payload"] == DEFAULT_ITEMS[0].payload
    saved = world.repo.rows[CONN]
    assert saved.items[3].payload == "QF_PREGUNTA_1"
    assert saved.updated_by_user_id == USER
    assert state.rows[3].payload == "QF_PREGUNTA_1" and not state.dirty


async def test_the_refusal_lands_under_the_right_question() -> None:
    world = _world()
    state = await _opened(world)
    state.set_question(2, DEFAULT_ITEMS[0].question.upper())  # a repeat, ignoring case
    await _drain(IceBreakersState.save.fn(state))
    assert state.rows[2].error == MESSAGES["question_repeated"]
    assert [r.error for i, r in enumerate(state.rows) if i != 2] == ["", "", ""]
    assert state.dirty and world.repo.rows[CONN].items == DEFAULT_ITEMS  # nothing saved

    state.set_question(1, "   ")
    state.set_question(2, "¿Abren los domingos?")
    await _drain(IceBreakersState.save.fn(state))
    assert state.rows[1].error == MESSAGES["question_empty"]
    assert state.rows[2].error == ""


async def test_publish_asks_first_saves_the_edits_and_carries_the_person() -> None:
    world = _world()
    state = await _opened(world)
    state.set_question(0, "¿Qué combo te provoca?")
    await _drain(IceBreakersState.confirm.fn(state))  # nothing to confirm yet
    assert world.client.calls == []

    state.ask_confirm("publish")
    assert state.confirming == "publish" and "abra un chat" in state.confirm_message
    await _drain(IceBreakersState.confirm.fn(state))

    row = world.repo.rows[CONN]
    assert row.status == "published" and row.published_by_user_id == USER
    assert world.client.remote[CONN][0].question == "¿Qué combo te provoca?"
    assert state.status.tone == "ok" and state.status.label.startswith("Publicadas el ")
    assert state.status.verified  # read back and matched
    assert state.can_remove and state.working == "" and state.confirming == ""

    state.ask_confirm("remove")
    await _drain(IceBreakersState.confirm.fn(state))
    assert CONN not in world.client.remote or world.client.remote[CONN] == ()
    assert world.repo.rows[CONN].status == "removed"
    assert state.status.label == "Sin publicar" and not state.can_remove


async def test_capability_off_disables_publish_and_remove_but_not_editing() -> None:
    world = _world(OFF)
    state = await _opened(world)
    assert state.available is False
    assert state.unavailable_reason == OFF.reason and state.availability_label == "Por verificar"
    assert state.can_publish is False and state.can_remove is False
    state.ask_confirm("publish")
    state.ask_confirm("remove")
    assert state.confirming == ""

    # Even if the browser forces it, the service refuses and Meta is not called.
    state.confirming = "publish"
    events = await _drain(IceBreakersState.confirm.fn(state))
    assert events and world.client.calls == []
    assert world.repo.rows[CONN].status == "draft"

    state.set_question(0, "¿Qué se te antoja hoy?")
    await _drain(IceBreakersState.save.fn(state))
    assert world.repo.rows[CONN].items[0].question == "¿Qué se te antoja hoy?"


async def test_a_remote_failure_is_shown() -> None:
    world = _world()
    state = await _opened(world)
    world.client.fail_next.append(IceBreakersApiError("down", http_status=503, platform_code=2))
    state.ask_confirm("publish")
    events = await _drain(IceBreakersState.confirm.fn(state))

    assert world.repo.rows[CONN].status == "failed"
    assert state.status.tone == "error"
    assert state.status.label == "No se pudo actualizar Instagram"
    assert state.status.detail == MESSAGES[world.repo.rows[CONN].last_error_code]
    assert state.status.detail != "" and events  # plus a toast
    assert state.working == ""


async def test_checking_instagram_reads_and_a_failed_read_is_shown() -> None:
    world = _world(OFF)  # reading works with the capability off
    state = await _opened(world)
    state.set_question(0, "sin guardar")
    await _drain(IceBreakersState.check_remote.fn(state))
    assert ("fetch", CONN) in world.client.calls
    assert state.rows[0].question == "sin guardar" and state.dirty  # edits survive

    world.client.fail_next.append(IceBreakersApiError("down", http_status=503, platform_code=2))
    await _drain(IceBreakersState.check_remote.fn(state))
    assert state.remote_error == MESSAGES[CATEGORY_META_UNAVAILABLE]


async def test_restore_asks_first() -> None:
    world = _world()
    state = await _opened(world)
    state.set_question(0, "otra")
    await _drain(IceBreakersState.save.fn(state))
    assert state.can_restore
    state.ask_confirm("restore")
    assert "se pierde" in state.confirm_message
    state.cancel_confirm()
    assert world.repo.rows[CONN].items[0].question == "otra"

    state.ask_confirm("restore")
    await _drain(IceBreakersState.confirm.fn(state))
    assert world.repo.rows[CONN].items == DEFAULT_ITEMS
    assert [r.question for r in state.rows] == [i.question for i in DEFAULT_ITEMS]
    assert world.client.calls == []


def test_move_and_discard_are_local() -> None:
    state = IceBreakersState()
    state._apply(_world().service.get_config(tenant_id=TENANT, connection_id=CONN))
    first = state.rows[0].payload
    state.move_question(0, 1)
    assert state.rows[1].payload == first and state.dirty
    state.discard_changes()
    assert state.rows[0].payload == first and not state.dirty


def test_logout_resets_this_state() -> None:
    assert "IceBreakersState" in inspect.getsource(AuthState.logout.fn)


def test_the_panel_uses_the_design_system_and_talks_to_the_state_only() -> None:
    source = (_HERE / "ice_breakers_panel.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any("provider" in name or name.startswith("qualify_api") for name in imported)
    assert "rx.color(" not in source and "color_scheme=" not in source
    page = (_HERE / "conversations_page.py").read_text(encoding="utf-8")
    assert "ice_breakers_panel()" in page and "ice_breakers_button(" in page


def test_the_page_renders_the_panel() -> None:
    from .conversations_page import conversations_index

    rendered = str(conversations_index().render())
    for text in (
        "Preguntas iniciales",
        "Publicar en Instagram",
        "Comprobar en Instagram",
        "Quitar de Instagram",
        "Restaurar las preguntas por defecto",
        "Agregar pregunta",
    ):
        assert text in rendered, text
