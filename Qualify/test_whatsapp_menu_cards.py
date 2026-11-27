"""«Tu menú de bienvenida» (m-24955645, m-24986800, m-25142807): ONE card with ONE select
«Menú y versión» — every menu of the number as a group, each of its versions an option
(newest first, the draft as «Cambios sin publicar», the live version marked in words) —,
the way to publish what is picked, ONE pause switch on the live menu, and «⋯ › Eliminar».
Option A: what is picked is what the editor and the preview show; saving from an older
version makes the next one.

Pure view-model tests first, then the provider over the memory repository, then the
state with the provider calls faked (no database, no Graph).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime
from functools import partial
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_api.whatsapp.menus import MemoryMenuRepository, MenuIsAnswering, MenuNotFound
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.menus.schema import MenuDefinition
from sqlalchemy.exc import OperationalError

from . import whatsapp_menu_state as module
from .whatsapp_menu_provider import (
    ArchiveOutcome,
    MenuDetail,
    NumberScope,
    PublishOutcome,
    create_menu,
    menu_detail,
    menu_overview,
    save_version,
)
from .whatsapp_menu_state import WhatsAppMenuState
from .whatsapp_menu_vm import (
    DELETE_BLOCKED,
    DELETE_FAILED,
    DELETE_NEVER_SENT,
    DELETE_PAUSED,
    DELETE_REPLACED,
    DELETED_TOAST,
    DRAFT_OPTION,
    PAUSE_CONFIRM,
    PUBLISH_CONFIRM_SAVES,
    PUBLISH_OK,
    RESUMED_TOAST,
    SAVE_NEEDS_FIX,
    SELECTED_IS_ACTIVE,
    SELECTED_IS_ACTIVE_PAUSED,
    SWITCH_GONE,
    TEMPLATE_EMPTY,
    UNSAVED_OPTION,
    MenuCardInput,
    MenuPickerVM,
    MenuSummaryVM,
    MenuVersionVM,
    build_menu_card,
    build_menu_picker,
    card_input_from,
    local_long_date,
    merge_card_input,
    order_menu_cards,
    picker_target,
)

BOGOTA = ZoneInfo("America/Bogota")
TODAY = date(2026, 11, 8)
TENANT = uuid4()
CONNECTION = str(uuid4())
A, B = str(uuid4()), str(uuid4())  # two menus of the number
V1, V2, V3 = str(uuid4()), str(uuid4()), str(uuid4())
# 02:00 UTC on 5 Nov is still 4 Nov in Bogotá (UTC-5): the business's day, not UTC's.
NOV_4_LOCAL = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)
NOV_1 = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)
NOV_7 = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)


def _input(
    *,
    menu_id: str = A,
    name: str = "Menú principal",
    live: str | None = V2,
    paused: bool = False,
    versions: list[tuple[str, int, datetime | None]] | None = None,
) -> MenuCardInput:
    """`versions` as (id, number, published_at); each was created when it was first
    published, the draft on 7 Nov."""
    rows = (
        versions if versions is not None else [(V1, 1, NOV_1), (V2, 2, NOV_4_LOCAL), (V3, 3, None)]
    )
    return card_input_from(
        menu_id=menu_id,
        name=name,
        published_version_id=live,
        is_paused=paused,
        versions=[(v_id, n, at or NOV_7, at) for v_id, n, at in rows],
    )


def _card(card: MenuCardInput) -> Any:
    return build_menu_card(card)


def _picker(cards: list[MenuCardInput], *, open_id: str = A, holding: str = V3) -> MenuPickerVM:
    return build_menu_picker(
        order_menu_cards(cards),
        open_menu_id=open_id,
        editing_version_id=holding,
        zone=BOGOTA,
        today=TODAY,
    )


# --- the view model -----------------------------------------------------------------------


def test_status_per_menu() -> None:
    live = _card(_input())
    assert live.is_live and not live.is_paused
    assert _picker([_input()], holding=V2).status_label == "Activo en tu WhatsApp"
    paused = _card(_input(paused=True))
    assert paused.is_live and paused.is_paused
    assert _picker([_input(paused=True)], holding=V2).status_tone == "warn"
    never = _card(_input(live=None, versions=[(V1, 1, None)]))
    assert not never.is_live and not never.is_paused
    # A pause left on a menu another one replaced does not make it «En pausa».
    demoted = _card(_input(live=None, paused=True))
    assert not demoted.is_live and not demoted.is_paused


def test_one_select_groups_every_menu_and_lists_its_versions_newest_first() -> None:
    picker = _picker([_input(), _input(menu_id=B, name="Almuerzos", live=None)])
    assert [(g.menu_id, g.name) for g in picker.groups] == [
        (A, "Menú principal"),
        (B, "Almuerzos"),
    ]
    main, other = picker.groups
    # The draft first in words, the live one marked in words (never a colour alone),
    # the creation date in the business's own zone.
    assert [o.label for o in main.options] == [
        DRAFT_OPTION,
        "Versión 2 · creada el 4 de noviembre · Activo en tu WhatsApp",
        "Versión 1 · creada el 1 de noviembre",
    ]
    assert [o.value for o in main.options] == [V3, V2, V1]
    assert [o.label for o in other.options][0] == DRAFT_OPTION
    paused = _picker([_input(paused=True)])
    assert paused.groups[0].options[1].label.endswith(" · En pausa")
    assert local_long_date(datetime(2025, 3, 2, 18, tzinfo=UTC), BOGOTA, TODAY) == (
        "2 de marzo de 2025"
    )


def test_older_saves_that_never_went_out_are_left_out_unless_the_editor_holds_one() -> None:
    v4 = str(uuid4())
    card = _input(versions=[(V1, 1, NOV_1), (V2, 2, None), (V3, 3, NOV_4_LOCAL), (v4, 4, None)])
    card = dataclasses.replace(card, live_version_id=V3)
    values = [o.value for o in _picker([card], holding=v4).groups[0].options]
    assert values == [v4, V3, V1]  # 2 was replaced by a later save
    held = [o.value for o in _picker([card], holding=V2).groups[0].options]
    assert held == [v4, V3, V2, V1]


def test_saving_from_an_older_version_never_hides_the_draft() -> None:
    """v1 published, v2 a draft; v1 picked, edited and saved as v3: v2 stays listed."""
    card = _input(live=V1, versions=[(V1, 1, NOV_1), (V2, 2, None), (V3, 3, None)])
    options = _picker([card], holding=V3).groups[0].options
    assert [o.value for o in options] == [V3, V2, V1]
    assert options[0].label == DRAFT_OPTION
    assert options[1].label == "Versión 2 · creada el 7 de noviembre · sin publicar"
    never = _input(live=None, versions=[(V1, 1, None), (V2, 2, None)])
    assert [o.value for o in _picker([never], holding=V2).groups[0].options] == [V2, V1]


def test_a_menu_never_saved_has_one_option_that_opens_it() -> None:
    empty = _input(menu_id=B, name="Vacío", live=None, versions=[])
    picker = _picker([_input(), empty], open_id=B, holding="")
    (option,) = picker.groups[1].options
    assert option.label == UNSAVED_OPTION
    assert picker.value == option.value and picker.trigger_label == "Vacío · Todavía sin guardar"
    assert picker_target(picker, option.value) == (B, "")
    assert picker.is_unpublished and not picker.can_publish_version


def test_the_closed_select_names_the_menu_and_the_version_the_editor_holds() -> None:
    live = _picker([_input(name="prueba 2")], holding=V2)
    assert live.value == V2 and live.trigger_label == "prueba 2 · Versión 2"
    assert live.is_live_version and live.status_label == "Activo en tu WhatsApp"
    assert live.help == SELECTED_IS_ACTIVE and not live.can_publish_version
    draft = _picker([_input(name="prueba 2")], holding=V3)
    assert draft.trigger_label == "prueba 2 · Cambios sin publicar"
    assert draft.is_unpublished and not draft.is_live_version and draft.status_label == ""
    assert draft.help == (
        "Tus clientes reciben «prueba 2 · Versión 2». La que estás viendo todavía no les llega."
    )


def test_an_older_version_says_customers_have_another_and_offers_going_back() -> None:
    older = _picker([_input()], holding=V1)
    assert older.number == 1 and not older.is_live_version and older.can_publish_version
    # It went out once: never «todavía no les llega» of it.
    assert older.help == (
        "Tus clientes reciben «Menú principal · Versión 2». La que estás viendo es una versión "
        "anterior."
    )
    assert older.publish_button == "Volver a la versión 1"
    assert older.publish_title == "Publicar la versión 1"
    assert older.publish_confirm == "Desde ahora tus clientes verán la versión 1. ¿Publicar?"
    assert older.publish_lines == ["La versión 2 y tu borrador quedan guardados."]
    no_draft = _picker([_input(versions=[(V1, 1, NOV_1), (V2, 2, NOV_4_LOCAL)])], holding=V1)
    assert no_draft.publish_lines == ["La versión 2 queda guardada."]


def test_a_paused_menu_says_so_under_the_select_and_in_its_confirmation() -> None:
    live = _picker([_input(paused=True)], holding=V2)
    assert live.status_label == "En pausa" and live.help == SELECTED_IS_ACTIVE_PAUSED
    older = _picker([_input(paused=True)], holding=V1)
    assert older.publish_confirm == (
        "Este menú está en pausa: tus clientes verán la versión 1 cuando lo reanudes. ¿Publicar?"
    )
    assert older.help == (
        "En tu WhatsApp está «Menú principal · Versión 2», en pausa. La que estás viendo es "
        "una versión anterior."
    )
    draft = _picker([_input(paused=True)], holding=V3)
    assert draft.help == (
        "En tu WhatsApp está «Menú principal · Versión 2», en pausa. La que estás viendo "
        "todavía no les llega."
    )
    nothing = _picker([_input(live=None, versions=[(V1, 1, None)])], holding=V1)
    assert nothing.help == "La que estás viendo todavía no les llega a tus clientes."


def test_another_menu_s_confirmation_names_the_one_it_replaces() -> None:
    cards = [_input(), _input(menu_id=B, name="Almuerzos", live=None, versions=[(V1, 1, NOV_1)])]
    picker = _picker(cards, open_id=B, holding=V1)
    assert picker.publish_button == "Publicar esta versión"  # not live: nothing to go back to
    assert picker.publish_lines == [
        "Tu menú «Menú principal» deja de estar activo y este toma su lugar."
    ]


def test_the_switch_acts_on_the_live_menu_and_names_it_when_another_is_picked() -> None:
    cards = [_input(), _input(menu_id=B, name="Almuerzos", live=None, versions=[(V1, 1, NOV_1)])]
    same = _picker(cards, holding=V2)
    assert same.has_live and same.live_menu_id == A and not same.live_paused
    assert same.switch_help == "Tus clientes lo reciben cuando te escriben."
    assert same.pause_title == "Pausar «Menú principal»"
    other = _picker(cards, open_id=B, holding=V1)
    assert other.live_menu_id == A
    assert other.switch_help == (
        "Este botón pausa o reanuda «Menú principal», el menú que está en tu WhatsApp."
    )
    paused = _picker([_input(paused=True)], holding=V2)
    assert paused.live_paused and paused.switch_help == (
        "Está en pausa: tus clientes no lo reciben y sus mensajes te llegan a «Por responder»."
    )
    # Nothing was ever published: no switch.
    assert not _picker([_input(live=None, versions=[(V1, 1, None)])], holding=V1).has_live
    assert PAUSE_CONFIRM == (
        "Tus clientes dejarán de recibir este menú hasta que lo reanudes. Sus mensajes te "
        "llegarán a «Por responder». ¿Pausar?"
    )
    assert RESUMED_TOAST == "Listo: tus clientes vuelven a recibir este menú."


def test_only_options_on_screen_are_accepted() -> None:
    picker = _picker([_input(), _input(menu_id=B, name="Almuerzos", live=None)])
    assert picker_target(picker, V1) == (A, V1)
    for bad in ("x", "", "menu:" + A, str(uuid4())):
        assert picker_target(picker, bad) is None
    assert picker_target(picker, ["x"]) is None  # type: ignore[arg-type]


def test_accessible_names_lead_with_the_visible_words() -> None:
    picker = _picker([_input()])
    assert picker.more_label == "Más opciones del menú Menú principal"


def test_merging_a_live_menu_demotes_the_others() -> None:
    cards = [_input(), _input(menu_id=B, name="Almuerzos", live=None)]
    fresh = _input(menu_id=B, name="Almuerzos", live=V1)
    merged = merge_card_input(cards, fresh)
    assert [c.live_version_id for c in merged] == ["", V1]
    new = _input(menu_id=str(uuid4()), live=None)
    assert merge_card_input(cards, new)[-1] == new and len(merge_card_input(cards, new)) == 3


def test_card_vms_are_frozen_and_carry_no_credentials() -> None:
    for vm in (_card(_input()), _picker([_input()])):
        with pytest.raises(dataclasses.FrozenInstanceError):
            vm.name = "x"  # type: ignore[misc]
        fields = {f.name for f in dataclasses.fields(vm)}
        assert not {f for f in fields if "token" in f or "secret" in f or "credential" in f}


# --- the provider (memory repository) -----------------------------------------------------

SCOPE = NumberScope(phone_row_id=uuid4(), brand_id=None, brand_name="Bianki")


def test_the_overview_reads_summaries_and_cards_in_one_pass() -> None:
    repo = MemoryMenuRepository()
    created = create_menu(TENANT, SCOPE, "Principal", TEMPLATE_EMPTY, repo=repo)
    menu_id = UUID(created.summary.menu_id)
    payload = BIANKI_DEMO_MENU.model_dump(mode="json")
    v1 = save_version(TENANT, SCOPE, menu_id, payload, repo=repo).versions[0].version_id
    repo.publish_version(tenant_id=TENANT, menu_id=menu_id, version_id=UUID(v1), user_id=None)
    save_version(TENANT, SCOPE, menu_id, payload, repo=repo)  # a draft after it

    summaries, cards = menu_overview(TENANT, SCOPE, repo=repo)

    assert [s.name for s in summaries] == ["Principal"]
    (card,) = cards
    assert card.live_version_id == v1 and not card.is_paused
    assert [(v.number, v.published_at is not None) for v in card.versions] == [
        (1, True),
        (2, False),
    ]
    detail = menu_detail(TENANT, SCOPE, menu_id, repo=repo)
    assert detail.card == card
    picker = build_menu_picker(
        [card], open_menu_id=str(menu_id), editing_version_id="", zone=BOGOTA, today=TODAY
    )
    assert picker.groups[0].options[0].label == DRAFT_OPTION


# --- the state ----------------------------------------------------------------------------


class _Proxy:
    """Reflex's StateProxy in a test: `async with self` is a no-op lock."""

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


async def _run(handler: object, state: WhatsAppMenuState, *args: object) -> list[object]:
    fn = handler.fn  # type: ignore[attr-defined]
    result = fn(_Proxy(state), *args)
    if hasattr(result, "__aiter__"):
        return [event async for event in result]
    await result
    return []


def _summary(menu_id: str, name: str, *, live: bool, paused: bool = False) -> MenuSummaryVM:
    label = ("En pausa" if paused else "Activo en tu WhatsApp") if live else "Sin publicar"
    return MenuSummaryVM(
        menu_id=menu_id,
        name=name,
        published_label="Publicado: versión 2" if live else "Sin publicar",
        is_published=live,
        is_paused=paused,
        status_label=label,
        status_tone="ok" if live else "neutral",
        updated_at="hoy",
    )


VB = str(uuid4())  # «Almuerzos»'s one version


def _payload(number: int) -> dict[str, Any]:
    """A version's definition: the demo menu, its greeting naming the version."""
    data = BIANKI_DEMO_MENU.model_dump(mode="json")
    data["entry"]["welcome"] = f"Hola, versión {number}"
    return data


def _detail(card: MenuCardInput) -> MenuDetail:
    live = bool(card.live_version_id)
    newest = max((v.number for v in card.versions), default=0)
    return MenuDetail(
        summary=_summary(card.menu_id, card.name, live=live, paused=card.is_paused),
        versions=[
            MenuVersionVM(
                version_id=v.version_id,
                label=f"Versión {v.number}",
                created_at="hoy",
                published_at="hoy" if v.published_at else "",
                is_live=v.version_id == card.live_version_id,
            )
            for v in sorted(card.versions, key=lambda v: v.number, reverse=True)
        ],
        latest=MenuDefinition.model_validate(_payload(newest)) if newest else None,
        payloads={v.version_id: _payload(v.number) for v in card.versions},
        card=card,
    )


@pytest.fixture
def screen(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The number on screen; a test switches it to simulate the owner changing numbers."""
    current = {"connection": CONNECTION}

    async def session(self: object) -> tuple[str, UUID | None, str]:
        return str(TENANT), TENANT, "duena@example.com"

    async def connection_id(self: object) -> str:
        return current["connection"]

    monkeypatch.setattr(WhatsAppMenuState, "_session", session)
    monkeypatch.setattr(WhatsAppMenuState, "_connection_id", connection_id)
    monkeypatch.setattr(module, "user_id_for", lambda *a: None)
    return current


def _almuerzos() -> MenuCardInput:
    return _input(menu_id=B, name="Almuerzos", live=None, versions=[(VB, 1, NOV_1)])


def _state() -> WhatsAppMenuState:
    """Two menus: «Menú principal» (A) answering with v2 and a draft v3, «Almuerzos» (B)
    unpublished with v1 published once; A is open in the editor, on its newest version."""
    state = WhatsAppMenuState()
    state._scope = {"phone_row_id": str(uuid4()), "brand_id": "", "brand_name": "Bianki"}
    state._zone = "America/Bogota"
    state.loaded_for = CONNECTION
    a, b = _input(), _almuerzos()
    state.menus = [_summary(A, a.name, live=True), _summary(B, b.name, live=False)]
    state._cards = [a, b]
    state._rebuild_cards()
    state._show_detail(_detail(a), load_form=True)
    return state


def _never_called(called: list[object]) -> Any:
    async def publish(*args: object, **kw: object) -> None:
        called.append(args)

    return publish


def test_the_select_starts_on_the_newest_saved_version(screen: dict) -> None:
    state = _state()
    assert [g.name for g in state.picker.groups] == ["Menú principal", "Almuerzos"]
    assert state.picker.value == V3 == state.picker_value == state.editing_version_id
    assert state.picker.trigger_label == "Menú principal · Cambios sin publicar"
    assert state.welcome == "Hola, versión 3"


def test_picking_a_version_of_the_open_menu_shows_it_in_the_editor_and_the_preview(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Option A: what is picked is what is seen — no Postgres read, the owner stays on
    the step they were on, and nothing is marked as changed."""
    state = _state()
    monkeypatch.setattr(module, "menu_detail", lambda *a: pytest.fail("read again"))
    state.guided_step, state.advanced_open = 3, True
    assert state.choose_version(V1) is None
    assert state.editing_version_id == V1 and state.picker.value == V1
    assert state.welcome == "Hola, versión 1" and not state.dirty
    assert state._preview_payload["entry"]["welcome"] == "Hola, versión 1"
    assert state.guided_step == 3 and state.advanced_open
    assert state.picker.trigger_label == "Menú principal · Versión 1"
    assert state.picker.can_publish_version
    state.choose_version(V2)
    assert state.welcome == "Hola, versión 2" and state.picker.is_live_version


def test_picking_another_menu_opens_it_on_the_picked_version(screen: dict) -> None:
    state = _state()
    events = state.choose_version(VB)
    assert events is not None and "open_menu" in str(events[0]) and VB in str(events[0])
    assert state.pick_pending == VB and state.picker_value == VB
    # The select is disabled while a menu opens; picking what the editor holds only
    # drops the pending pick.
    assert state.choose_version(V3) is None and state.pick_pending == ""
    for junk in ("junk", "", ["x"], "menu:" + A):
        assert state.choose_version(junk) is None  # type: ignore[arg-type]


async def test_opening_a_menu_on_a_version_loads_that_version(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    b = _input(menu_id=B, name="Almuerzos", live=None, versions=[(VB, 1, NOV_1), (V1, 2, None)])
    state._cards = [state._cards[0], b]
    monkeypatch.setattr(module, "menu_detail", lambda *a: _detail(b))
    await _run(WhatsAppMenuState.open_menu, state, B, VB)
    assert state.menu.menu_id == B and state.editing_version_id == VB
    assert state.welcome == "Hola, versión 1" and state.picker.value == VB
    # A version of another menu is never loaded.
    monkeypatch.setattr(module, "menu_detail", lambda *a: _detail(_input()))
    await _run(WhatsAppMenuState.open_menu, state, A, "not-a-version")
    assert state.menu.menu_id == A and state.editing_version_id == V3


def test_picking_with_unsaved_changes_asks_first(screen: dict) -> None:
    state = _state()
    state.set_welcome("Hola, bienvenido")
    assert state.dirty
    assert state.choose_version(VB) is None
    assert state.switch_open and state.switch_to == VB
    assert state.switch_title == "¿Cambiar de menú?"
    assert state.switch_text == (
        "Tienes cambios sin guardar en «Menú principal». Guárdalos o se pierden."
    )
    assert state.picker_value == V3  # the select stays until the owner decides
    state.set_switch_open(False)  # «Cancelar»
    assert not state.switch_open and state.welcome == "Hola, bienvenido"
    state.choose_version(V1)
    assert state.switch_title == "¿Abrir otra versión?"
    assert state.discard_and_switch() is None  # same menu: loaded in place
    assert state.welcome == "Hola, versión 1" and not state.dirty and not state.switch_open


async def test_guardar_y_cambiar_saves_then_opens(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.set_welcome("Hola, bienvenido")
    state.choose_version(VB)
    saved: list[UUID] = []

    def save(tenant_id: UUID, scope: NumberScope, menu_id: UUID, payload: Any) -> MenuDetail:
        saved.append(menu_id)
        return _detail(_input())

    monkeypatch.setattr(module, "save_version", save)
    events = await _run(WhatsAppMenuState.save_and_switch, state)
    assert saved == [UUID(A)] and not state.dirty
    assert len(events) == 1 and "open_menu" in str(events[0])
    assert state.pick_pending == VB and not state.switch_open


def test_cambiar_sin_guardar_drops_the_typing_and_opens(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.set_welcome("Hola, bienvenido")
    state.choose_version(VB)
    monkeypatch.setattr(module, "save_version", lambda *a: pytest.fail("saved"))
    events = state.discard_and_switch()
    assert events is not None and "open_menu" in str(events[0])
    # What is typed stays (and stays unsaved) until the other menu has opened.
    assert state.dirty and not state.switch_open
    assert state.picker_value == VB
    assert state.discard_and_switch() is None  # nothing pending any more


async def test_guardar_y_cambiar_with_something_to_fix_saves_nothing(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.dirty = True
    state.error_count = 1
    state.switch_to = VB
    monkeypatch.setattr(module, "save_version", lambda *a: pytest.fail("saved"))
    events = await _run(WhatsAppMenuState.save_and_switch, state)
    assert events == [] and state.picker_value == V3
    assert (state.banner, state.banner_tone) == (SAVE_NEEDS_FIX, "warn")


def _memory_state(monkeypatch: pytest.MonkeyPatch) -> tuple[WhatsAppMenuState, Any, list[str]]:
    """A state over the memory repository: a menu with v1 (published) and v2 (draft),
    open on v2."""
    repo = MemoryMenuRepository()
    scope = NumberScope(phone_row_id=uuid4(), brand_id=None, brand_name="Bianki")
    created = create_menu(TENANT, scope, "Principal", TEMPLATE_EMPTY, repo=repo)
    menu_id = UUID(created.summary.menu_id)
    ids = []
    for n in (1, 2):
        detail = save_version(TENANT, scope, menu_id, _payload(n), repo=repo)
        ids.append(detail.versions[0].version_id)
        if n == 1:
            repo.publish_version(
                tenant_id=TENANT, menu_id=menu_id, version_id=UUID(ids[0]), user_id=None
            )
    monkeypatch.setattr(module, "save_version", partial(save_version, repo=repo))
    state = WhatsAppMenuState()
    state._scope = {
        "phone_row_id": str(scope.phone_row_id),
        "brand_id": "",
        "brand_name": "Bianki",
    }
    state.loaded_for = CONNECTION
    summaries, cards = menu_overview(TENANT, scope, repo=repo)
    state.menus, state._cards = summaries, list(cards)
    state._show_detail(menu_detail(TENANT, scope, menu_id, repo=repo), load_form=True)
    return state, repo, ids


async def test_saving_from_an_older_version_makes_the_next_one(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, repo, (v1, v2) = _memory_state(monkeypatch)
    assert state.editing_version_id == v2
    state.choose_version(v1)
    state.set_welcome("Hola, versión 1 corregida")
    await _run(WhatsAppMenuState.save_current_version, state)

    menu_id = UUID(state.menu.menu_id)
    versions = repo.list_versions(tenant_id=TENANT, menu_id=menu_id)
    assert [v.version for v in versions] == [1, 2, 3]
    by_number = {v.version: v for v in versions}
    assert by_number[1].definition.entry.welcome == "Hola, versión 1"  # never changed
    assert by_number[3].definition.entry.welcome == "Hola, versión 1 corregida"
    # The select moves to the version just saved.
    assert state.editing_version_id == str(by_number[3].id) == state.picker.value
    assert state.picker.trigger_label == "Principal · Cambios sin publicar"
    assert not state.dirty


async def test_publicar_publishes_exactly_what_the_editor_shows(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 4's «Publicar» after picking an older version: that version, untouched;
    after editing it, the new version saved from it."""
    state, repo, (v1, _v2) = _memory_state(monkeypatch)
    published: list[UUID] = []

    async def publish(tenant_id, connection_id, scope, menu_id, version_id, **kw):  # noqa: ANN001,ANN003,ANN202
        published.append(version_id)
        return PublishOutcome(
            detail=menu_detail(tenant_id, scope, menu_id, repo=repo),
            notice=PUBLISH_OK,
            tone="ok",
            graph_ok=True,
            auth_error=False,
        )

    monkeypatch.setattr(module, "publish_version", publish)
    state.choose_version(v1)
    assert state.can_publish
    await _run(WhatsAppMenuState.publish_current, state)
    assert published == [UUID(v1)]

    state.set_welcome("Hola de nuevo")
    await _run(WhatsAppMenuState.publish_current, state)
    newest = max(
        repo.list_versions(tenant_id=TENANT, menu_id=UUID(state.menu.menu_id)),
        key=lambda v: v.version,
    )
    assert newest.version == 3 and newest.definition.entry.welcome == "Hola de nuevo"
    assert published[-1] == newest.id


async def test_publicar_esta_version_publishes_the_picked_version_through_the_provider(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.choose_version(V1)
    calls: list[tuple[UUID, UUID]] = []

    async def publish(tenant_id, connection_id, scope, menu_id, version_id, **kw):  # noqa: ANN001,ANN003,ANN202
        calls.append((menu_id, version_id))
        return PublishOutcome(
            detail=_detail(_input(live=V1)),
            notice=PUBLISH_OK,
            tone="ok",
            graph_ok=True,
            auth_error=False,
        )

    monkeypatch.setattr(module, "publish_version", publish)

    await _run(WhatsAppMenuState.publish_card_version, state, A, V1)

    assert calls == [(UUID(A), UUID(V1))]
    assert state.card_busy == "" and state.banner_tone == "ok"
    assert state.banner == "Listo: tus clientes ya ven la versión 1 de «Menú principal»."
    assert state.picker.value == V1 and state.picker.is_live_version


async def test_publishing_another_menu_demotes_the_live_one_on_screen(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state._show_detail(_detail(_almuerzos()), load_form=True)
    assert state.picker.value == VB and state.picker.can_publish_version

    async def publish(*args: object, **kw: object) -> PublishOutcome:
        fresh = _input(menu_id=B, name="Almuerzos", live=VB, versions=[(VB, 1, NOV_1)])
        return PublishOutcome(
            detail=_detail(fresh), notice=PUBLISH_OK, tone="ok", graph_ok=True, auth_error=False
        )

    monkeypatch.setattr(module, "publish_version", publish)

    await _run(WhatsAppMenuState.publish_card_version, state, B, VB)

    # The select's order puts the menu that answers first (m-24986800).
    assert [(c.menu_id, c.is_live) for c in state.menu_cards] == [(B, True), (A, False)]
    assert [m.is_published for m in state.menus] == [False, True]
    assert state.picker.live_menu_id == B and state.picker.is_live_version


async def test_nothing_is_published_without_a_published_version(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    called: list[object] = []
    monkeypatch.setattr(module, "publish_version", _never_called(called))
    await _run(WhatsAppMenuState.publish_card_version, state, A, "")
    await _run(WhatsAppMenuState.publish_card_version, state, A, V3)  # the draft
    assert called == [] and state.card_busy == ""


async def test_the_active_version_is_never_republished_from_the_card(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.choose_version(V2)
    called: list[object] = []
    monkeypatch.setattr(module, "publish_version", _never_called(called))
    await _run(WhatsAppMenuState.publish_card_version, state, A, V2)  # V2 is live
    assert called == [] and state.card_busy == "" and state.banner == ""


async def test_a_version_with_unsaved_changes_is_never_published_from_the_card(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What would go out is not what is on screen: the editor's «Publicar en mi
    WhatsApp» saves first."""
    state = _state()
    state.choose_version(V1)
    state.set_welcome("Hola, bienvenido")
    called: list[object] = []
    monkeypatch.setattr(module, "publish_version", _never_called(called))
    await _run(WhatsAppMenuState.publish_card_version, state, A, V1)
    assert called == [] and state.card_busy == ""


async def test_a_pick_that_changed_since_the_dialog_is_refused(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dialog said «Publicar la versión 1»; the editor holds another version now:
    nothing is published, the owner picks again."""
    state = _state()
    state.choose_version(V1)
    state.choose_version(V2)
    called: list[object] = []
    monkeypatch.setattr(module, "publish_version", _never_called(called))
    await _run(WhatsAppMenuState.publish_card_version, state, A, V1)
    assert called == [] and state.card_busy == ""
    assert (state.banner, state.banner_tone) == (
        "La lista cambió. Elige la versión otra vez.",
        "warn",
    )


async def test_a_failed_card_publish_says_so(screen: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state()

    async def publish(*args: object, **kw: object) -> None:
        raise OperationalError("x", {}, Exception("db down"))

    monkeypatch.setattr(module, "publish_version", publish)
    state.choose_version(V1)
    await _run(WhatsAppMenuState.publish_card_version, state, A, V1)
    assert state.card_busy == "" and state.banner_tone == "error"
    assert "Vuelve a intentarlo" in state.banner


async def test_pausar_and_reanudar_go_through_set_paused(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    calls: list[tuple[UUID, bool]] = []

    def set_paused(tenant_id: UUID, scope: NumberScope, menu_id: UUID, paused: bool) -> Any:
        calls.append((menu_id, paused))
        return _detail(_input(paused=paused))

    monkeypatch.setattr(module, "set_paused", set_paused)

    await _run(WhatsAppMenuState.pause_card, state, A, True)
    assert state.menu_cards[0].is_paused and state.menu.is_paused
    assert state.picker.live_paused
    assert state.picker.groups[0].options[1].label.endswith(" · En pausa")  # v2, in words
    await _run(WhatsAppMenuState.pause_card, state, A, True)  # already paused: no call
    await _run(WhatsAppMenuState.pause_card, state, B, True)  # not published: no call
    events = await _run(WhatsAppMenuState.pause_card, state, A, False)

    assert calls == [(UUID(A), True), (UUID(A), False)]
    # Resuming is one tap: no banner, a toast that offers «Pausar» back.
    assert len(events) == 1 and RESUMED_TOAST in str(events[0]) and "Pausar" in str(events[0])
    assert state.banner == ""
    assert not state.menu_cards[0].is_paused and not state.picker.live_paused
    assert state.card_busy == ""


async def test_the_switch_asks_before_pausing_and_resumes_at_once(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With «Almuerzos» (B) open in the editor, the switch still pauses the live menu
    (A) — and only A."""
    state = _state()
    state._show_detail(_detail(_almuerzos()), load_form=True)
    assert state.menu.menu_id == B and state.picker.menu_id == B
    assert state.picker.live_menu_id == A
    paused_ids: list[tuple[UUID, bool]] = []

    def set_paused(tenant_id: UUID, scope: NumberScope, menu_id: UUID, paused: bool) -> Any:
        paused_ids.append((menu_id, paused))
        return _detail(_input(paused=paused))

    monkeypatch.setattr(module, "set_paused", set_paused)
    assert state.set_answering(False) is None and state.pause_confirm_open
    event = state.confirm_pause()
    assert not state.pause_confirm_open and "pause_card" in str(event)
    await _run(WhatsAppMenuState.pause_card, state, A, True)
    assert paused_ids == [(UUID(A), True)]
    assert state.picker.live_paused and state.menu.menu_id == B  # B stays open
    assert state.set_answering(False) is None  # already paused
    event = state.set_answering(True)
    assert "pause_card" in str(event) and not state.pause_confirm_open
    # Nothing published: no switch, nothing to do.
    state._cards = [_input(live=None), _almuerzos()]
    state._rebuild_cards()
    assert state.set_answering(False) is None and not state.pause_confirm_open
    state.set_pause_confirm_open(True)
    assert not state.pause_confirm_open


async def test_saving_v3_from_v1_keeps_the_draft_v2_listed_and_openable(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _repo, (v1, v2) = _memory_state(monkeypatch)
    state.choose_version(v1)
    state.set_welcome("Hola, versión 1 corregida")
    await _run(WhatsAppMenuState.save_current_version, state)
    labels = {o.value: o.label for o in state.picker.groups[0].options}
    assert v2 in labels and labels[v2].endswith(" · sin publicar")
    assert labels[state.picker.value] == DRAFT_OPTION  # v3
    assert state.choose_version(v2) is None
    assert state.welcome == "Hola, versión 2" and state.editing_version_id == v2


def test_a_switch_that_cannot_load_in_place_keeps_what_is_typed(screen: dict) -> None:
    """The saved copy of the picked version is missing (the list was re-read): the menu
    is read again and opened on it; until then what is typed stays, still unsaved, and
    `editing_version_id` still names the version it was typed over."""
    state = _state()
    state.set_welcome("Hola, bienvenido")
    state.choose_version(V1)
    state._payloads = {}
    events = state.discard_and_switch()
    assert events is not None and "open_menu" in str(events[0]) and V1 in str(events[0])
    assert state.dirty and state.welcome == "Hola, bienvenido"
    assert state.editing_version_id == V3 and state.pick_pending == V1
    # Publishing now would save what is on screen first — never the unshown version 1.
    assert state.publish_confirm_lines[0] == PUBLISH_CONFIRM_SAVES


async def test_a_picked_option_that_left_the_select_is_said(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.set_welcome("Hola, bienvenido")
    state.switch_to = str(uuid4())  # no longer in the select
    assert state.discard_and_switch() is None
    assert (state.banner, state.banner_tone) == (SWITCH_GONE, "warn") and state.dirty
    state.banner, state.switch_to = "", str(uuid4())
    monkeypatch.setattr(module, "save_version", lambda *a: pytest.fail("saved"))
    assert await _run(WhatsAppMenuState.save_and_switch, state) == []
    assert state.banner == SWITCH_GONE


async def test_nothing_publishes_while_another_menu_opens(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.set_welcome("Hola, bienvenido")
    state.opening = True
    assert not state.can_publish
    state.set_publish_confirm_open(True)
    assert not state.publish_confirm_open
    # Opening started while the save was in flight: the publish is dropped.
    state.opening = False
    called: list[object] = []
    monkeypatch.setattr(module, "publish_version", _never_called(called))

    def save(*args: object) -> MenuDetail:
        state.opening = True
        return _detail(_input())

    monkeypatch.setattr(module, "save_version", save)
    await _run(WhatsAppMenuState.publish_current, state)
    assert called == [] and not state.publishing


async def test_a_card_action_waits_for_the_one_in_flight(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.card_busy = B
    called: list[object] = []
    monkeypatch.setattr(module, "set_paused", lambda *a: called.append(a))
    await _run(WhatsAppMenuState.pause_card, state, A, True)
    await _run(WhatsAppMenuState.publish_card_version, state, A, V1)
    assert state.set_answering(False) is None and not state.pause_confirm_open
    assert state.choose_version(V1) is None and state.editing_version_id == V3
    assert called == [] and state.card_busy == B


async def test_the_editor_waits_for_a_card_in_flight(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One write to the number at a time: while a card publishes or pauses, the
    editor's «Guardar», «Publicar» and pause do nothing (and are disabled)."""
    state = _state()
    state.set_welcome("Hola, bienvenido")  # something to save
    assert state.can_save and state.can_publish
    state.card_busy, state.card_busy_action = B, "publish"
    assert not state.can_save and not state.can_publish
    called: list[object] = []
    monkeypatch.setattr(module, "set_paused", lambda *a: called.append(a))
    monkeypatch.setattr(module, "save_version", lambda *a: called.append(a))
    monkeypatch.setattr(module, "publish_version", _never_called(called))
    await _run(WhatsAppMenuState.toggle_pause, state, True)
    await _run(WhatsAppMenuState.save_current_version, state)
    await _run(WhatsAppMenuState.publish_current, state)
    assert called == [] and not state.pausing and not state.saving and not state.publishing


async def test_a_late_publish_after_switching_number_is_dropped(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.choose_version(V1)

    async def publish(*args: object, **kw: object) -> PublishOutcome:
        screen["connection"] = str(uuid4())  # the owner switched numbers meanwhile
        state._reset_number_scoped()
        return PublishOutcome(
            detail=_detail(_input(live=V1)),
            notice=PUBLISH_OK,
            tone="ok",
            graph_ok=True,
            auth_error=False,
        )

    monkeypatch.setattr(module, "publish_version", publish)
    await _run(WhatsAppMenuState.publish_card_version, state, A, V1)

    assert state.menu_cards == [] and state.menus == [] and state.banner == ""
    assert state.card_busy == ""


async def test_a_late_pause_after_switching_number_is_dropped(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()

    def set_paused(*args: object) -> Any:
        screen["connection"] = str(uuid4())
        return _detail(_input(paused=True))

    monkeypatch.setattr(module, "set_paused", set_paused)
    await _run(WhatsAppMenuState.pause_card, state, A, True)

    assert not state.menu_cards[0].is_paused
    assert state.banner == "" and state.card_busy == ""


def test_switching_number_drops_the_cards_and_the_picks(screen: dict) -> None:
    state = _state()
    state.choose_version(VB)
    state._reset_number_scoped()
    assert state.menu_cards == [] and state._cards == []
    assert state.picker == MenuPickerVM() and state.pick_pending == ""


# --- m-24986800: the order of the menus and «Eliminar» ------------------------------------

C = str(uuid4())
NOV_8 = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)


def test_the_picker_order_answering_then_paused_then_unpublished_newest_first() -> None:
    old_draft = _input(menu_id=A, name="Viejo", live=None, versions=[(V1, 1, None)])
    answering = _input(menu_id=B, name="Principal")
    new_draft = card_input_from(
        menu_id=C,
        name="Navidad",
        published_version_id=None,
        is_paused=False,
        versions=[(V3, 1, NOV_8, None)],
    )
    empty = _input(menu_id="E", name="Vacío", live=None, versions=[])
    ordered = order_menu_cards([old_draft, answering, new_draft, empty])
    assert [c.name for c in ordered] == ["Principal", "Navidad", "Viejo", "Vacío"]
    paused = _input(menu_id="P", name="Pausa", paused=True)
    assert [c.name for c in order_menu_cards([old_draft, paused])] == ["Pausa", "Viejo"]


def test_eliminar_is_never_offered_on_the_menu_that_answers() -> None:
    answering = _card(_input(name="Principal"))
    assert not answering.can_delete and not _picker([_input()]).can_delete
    assert DELETE_BLOCKED == "Para eliminarlo, primero páusalo."
    assert _card(_input(name="Principal", paused=True)).can_delete
    paused = _picker([_input(name="Principal", paused=True)])
    assert paused.can_delete and paused.delete_case == DELETE_PAUSED
    # Archiving does not clear WhatsApp's shortcuts (accepted for now): one line says
    # what really happens — a tap reaches the owner's Chats, no automatic answer.
    assert "si alguien las toca, el mensaje te llega a tus Chats" in paused.delete_case
    # m-25017861 (D5): «Atajos» are «Preguntas iniciales» in both channels.
    assert "Las preguntas iniciales pueden seguir apareciendo" in paused.delete_case
    never = _picker([_input(live=None, versions=[(V1, 1, None)])], holding=V1)
    assert never.can_delete and never.delete_case == DELETE_NEVER_SENT
    # Published once, then another menu replaced it: «Nunca les llegó» would be false.
    replaced = _picker([_input(live=None)])
    assert replaced.can_delete and replaced.delete_case == DELETE_REPLACED


def test_the_confirmation_counts_the_saved_versions() -> None:
    assert _picker([_input(paused=True)]).delete_tail == " con sus 3 versiones guardadas."
    one = _picker([_input(live=None, versions=[(V1, 1, None)])], holding=V1)
    assert one.delete_tail == " con su versión guardada."
    assert _picker([_input(live=None, versions=[])], holding="").delete_tail == "."


def test_eliminar_asks_first_and_only_when_it_can_go(screen: dict) -> None:
    state = _state()  # A answers
    state.set_delete_confirm_open(True)
    assert not state.delete_confirm_open
    state._cards = [_input(paused=True), _almuerzos()]
    state._rebuild_cards()
    state.set_delete_confirm_open(True)
    assert state.delete_confirm_open


def _outcome(menu_id: str, name: str, cards: list[MenuCardInput]) -> ArchiveOutcome:
    return ArchiveOutcome(
        menu_id=menu_id,
        name=name,
        summaries=[
            _summary(c.menu_id, c.name, live=bool(c.live_version_id), paused=c.is_paused)
            for c in cards
        ],
        cards=cards,
    )


async def test_eliminar_archives_through_the_provider_and_lands_on_the_next_menu(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state._cards = [_input(paused=True), state._cards[1]]  # A paused: it can go
    state._rebuild_cards()
    calls: list[UUID] = []
    remaining = [state._cards[1]]

    def archive(tenant_id: UUID, scope: NumberScope, menu_id: UUID) -> ArchiveOutcome:
        calls.append(menu_id)
        return _outcome(A, "Menú principal", remaining)

    monkeypatch.setattr(module, "archive_menu", archive)
    events = await _run(WhatsAppMenuState.delete_card, state, A)

    assert calls == [UUID(A)]
    assert [c.menu_id for c in state.menu_cards] == [B]
    assert [m.menu_id for m in state.menus] == [B]
    assert not state.has_menu and not state.dirty  # the editor no longer holds A
    assert state.card_busy == "" and state.delete_error == ""
    text = [str(e) for e in events]
    assert DELETED_TOAST in text[0]
    assert "open_menu" in text[1]
    assert "whatsapp-menu-pick" in text[2]  # focus back to the picker


async def test_deleting_the_last_menu_leaves_the_empty_state(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state._cards = [_input(paused=True)]
    state.menus = [state.menus[0]]
    state._rebuild_cards()
    monkeypatch.setattr(module, "archive_menu", lambda *a: _outcome(A, "Menú principal", []))
    events = await _run(WhatsAppMenuState.delete_card, state, A)
    assert state.menu_cards == [] and state.menus == [] and not state.has_menu
    assert not any("open_menu" in str(e) for e in events)


async def test_the_menu_that_answers_is_never_deleted(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()  # A answers
    monkeypatch.setattr(module, "archive_menu", lambda *a: pytest.fail("archived"))
    assert await _run(WhatsAppMenuState.delete_card, state, A) == []
    assert [c.menu_id for c in state.menu_cards] == [A, B]


async def test_a_refused_or_failed_delete_says_what_to_do(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()

    def answering(*a: object) -> ArchiveOutcome:
        raise MenuIsAnswering(B)

    monkeypatch.setattr(module, "archive_menu", answering)
    events = await _run(WhatsAppMenuState.delete_card, state, B)
    assert state.delete_error == DELETE_BLOCKED and state.card_busy == ""
    assert "reload" in str(events[-1])

    def down(*a: object) -> ArchiveOutcome:
        raise OperationalError("x", {}, Exception("db down"))

    monkeypatch.setattr(module, "archive_menu", down)
    await _run(WhatsAppMenuState.delete_card, state, B)
    assert state.delete_error == DELETE_FAILED and state.card_busy == ""
    assert [c.menu_id for c in state.menu_cards] == [A, B]  # nothing left the list

    def gone(*a: object) -> ArchiveOutcome:
        raise MenuNotFound(B)

    monkeypatch.setattr(module, "archive_menu", gone)
    events = await _run(WhatsAppMenuState.delete_card, state, B)
    assert state.banner_tone == "warn" and "reload" in str(events[-1])


async def test_a_delete_waits_for_the_card_in_flight(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.card_busy = A
    monkeypatch.setattr(module, "archive_menu", lambda *a: pytest.fail("archived"))
    await _run(WhatsAppMenuState.delete_card, state, B)
    assert state.card_busy == A
