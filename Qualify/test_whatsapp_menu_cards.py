"""m-24955645: «Menús de este número» is one card per menu — its status, a «Versión»
selector over the published versions (the active one first, with its date in the
business's own zone), the «Borrador sin publicar» mark, and «Editar», «Publicar esta
versión» / «Volver a la versión n», «Pausar» (behind a confirmation) / «Reanudar»
(one tap, a toast offers «Pausar» back).

Pure view-model tests first, then the provider over the memory repository, then the
state with the provider calls faked (no database, no Graph).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_api.whatsapp.menus import MemoryMenuRepository, MenuIsAnswering, MenuNotFound
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
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
from .whatsapp_menu_state import TOOLBAR_ELEMENT_ID, WhatsAppMenuState
from .whatsapp_menu_vm import (
    DELETE_BLOCKED,
    DELETE_FAILED,
    DELETE_NEVER_SENT,
    DELETE_PAUSED,
    DELETE_REPLACED,
    DELETED_TOAST,
    PAUSE_CONFIRM,
    PUBLISH_OK,
    RESUMED_TOAST,
    SAVE_NEEDS_FIX,
    TEMPLATE_EMPTY,
    MenuCardInput,
    MenuSummaryVM,
    MenuVersionVM,
    build_menu_card,
    build_menu_cards,
    card_input_from,
    chosen_menu_id,
    default_card_version,
    local_long_date,
    merge_card_input,
    order_menu_cards,
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


def _card(card: MenuCardInput, **kw: Any) -> Any:
    return build_menu_card(card, zone=BOGOTA, today=TODAY, **kw)


# --- the view model -----------------------------------------------------------------------


def test_status_per_menu() -> None:
    live = _card(_input())
    assert (live.status_label, live.status_tone) == ("Respondiendo a tus clientes", "ok")
    assert live.is_live and not live.is_paused
    paused = _card(_input(paused=True))
    assert (paused.status_label, paused.status_tone) == ("En pausa", "warn")
    assert paused.is_live and paused.is_paused
    never = _card(_input(live=None, versions=[(V1, 1, None)]))
    assert (never.status_label, never.status_tone) == ("Sin publicar", "neutral")
    assert not never.is_live and not never.is_paused
    # A pause left on a menu another one replaced does not make it «En pausa».
    demoted = _card(_input(live=None, paused=True))
    assert demoted.status_label == "Sin publicar" and not demoted.is_paused


def test_the_selector_lists_published_versions_newest_first_with_the_local_date() -> None:
    card = _card(_input())
    assert [o.label for o in card.options] == [
        "Versión 2 · creada el 4 de noviembre",
        "Versión 1 · creada el 1 de noviembre",
    ]
    assert V3 not in {o.version_id for o in card.options}  # never published
    assert local_long_date(datetime(2025, 3, 2, 18, tzinfo=UTC), BOGOTA, TODAY) == (
        "2 de marzo de 2025"
    )


def test_the_active_version_is_picked_by_default() -> None:
    card = _card(_input())
    assert card.selected_version_id == V2 and card.selected_number == 2
    assert card.selected_is_active


def test_a_menu_that_is_not_live_starts_on_its_newest_published_version() -> None:
    card = _input(live=None)
    assert default_card_version(card) == V2
    assert not _card(card).selected_is_active


def test_a_menu_never_published_has_no_selector() -> None:
    card = _card(_input(live=None, versions=[(V1, 1, None)]))
    assert not card.has_options and card.selected_version_id == "" and card.publish_title == ""
    assert default_card_version(_input(live=None, versions=[])) == ""


def test_the_owner_s_pick_is_kept_and_a_stranger_value_ignored() -> None:
    picked = _card(_input(), chosen=V1)
    assert picked.selected_version_id == V1 and not picked.selected_is_active
    for bad in (V3, "x", ""):  # the draft, garbage, nothing
        assert _card(_input(), chosen=bad).selected_version_id == V2


def test_the_draft_mark() -> None:
    assert _card(_input()).has_draft  # version 3 saved after the live 2
    assert not _card(_input(versions=[(V1, 1, NOV_1), (V2, 2, NOV_4_LOCAL)])).has_draft
    assert _card(_input(live=None, versions=[(V1, 1, None)])).has_draft
    assert not _card(_input(live=None, versions=[])).has_draft  # an empty new menu


def test_the_confirmations_say_what_will_happen() -> None:
    card = _card(_input(), chosen=V1)
    assert card.publish_title == "Publicar la versión 1"
    assert card.publish_confirm == "Desde ahora tus clientes verán la versión 1. ¿Publicar?"
    assert card.publish_button == "Volver a la versión 1"
    assert card.publish_lines == ["La versión 2 y tu borrador quedan guardados."]
    no_draft = _card(_input(versions=[(V1, 1, NOV_1), (V2, 2, NOV_4_LOCAL)]), chosen=V1)
    assert no_draft.publish_lines == ["La versión 2 queda guardada."]
    paused = _card(_input(paused=True), chosen=V1)
    assert paused.publish_confirm == (
        "Este menú está en pausa: tus clientes verán la versión 1 cuando lo reanudes. ¿Publicar?"
    )
    assert PAUSE_CONFIRM == (
        "Tus clientes dejarán de recibir este menú hasta que lo reanudes. ¿Pausar?"
    )
    assert RESUMED_TOAST == "Listo: tus clientes vuelven a recibir este menú."
    assert card.pause_title == "Pausar «Menú principal»"


def test_another_menu_s_confirmation_names_the_one_it_replaces() -> None:
    cards = build_menu_cards(
        [_input(), _input(menu_id=B, name="Almuerzos", live=None)], zone=BOGOTA, today=TODAY
    )
    assert cards[0].publish_lines == []
    assert cards[1].publish_button == "Publicar esta versión"  # not live: nothing to go back to
    assert cards[1].publish_lines == [
        "Tu menú «Menú principal» deja de responder y este toma su lugar."
    ]


def test_accessible_names_lead_with_the_visible_words() -> None:
    card = _card(_input())
    assert card.select_label == "Versión de Menú principal"
    assert card.edit_label.startswith("Editar ")
    assert card.publish_label.startswith("Publicar esta versión ")
    assert card.pause_label.startswith("Pausar ") and card.resume_label.startswith("Reanudar ")


def test_merging_a_live_menu_demotes_the_others() -> None:
    cards = [_input(), _input(menu_id=B, name="Almuerzos", live=None)]
    fresh = _input(menu_id=B, name="Almuerzos", live=V1)
    merged = merge_card_input(cards, fresh)
    assert [c.live_version_id for c in merged] == ["", V1]
    new = _input(menu_id=str(uuid4()), live=None)
    assert merge_card_input(cards, new)[-1] == new and len(merge_card_input(cards, new)) == 3


def test_card_vms_are_frozen_and_carry_no_credentials() -> None:
    card = _card(_input())
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.name = "x"  # type: ignore[misc]
    fields = {f.name for f in dataclasses.fields(card)}
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
    assert build_menu_card(card, zone=BOGOTA, today=TODAY).has_draft


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
    label = ("En pausa" if paused else "Respondiendo a tus clientes") if live else "Sin publicar"
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


def _detail(card: MenuCardInput) -> MenuDetail:
    live = bool(card.live_version_id)
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
        latest=BIANKI_DEMO_MENU,
        payloads={},
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


def _state() -> WhatsAppMenuState:
    """Two menus: «Menú principal» (A) answering with v2, «Almuerzos» (B) unpublished
    with v1 published once; A is open in the editor."""
    state = WhatsAppMenuState()
    state._scope = {"phone_row_id": str(uuid4()), "brand_id": "", "brand_name": "Bianki"}
    state._zone = "America/Bogota"
    state.loaded_for = CONNECTION
    a = _input()
    b = _input(menu_id=B, name="Almuerzos", live=None, versions=[(V1, 1, NOV_1)])
    state.menus = [_summary(A, a.name, live=True), _summary(B, b.name, live=False)]
    state._cards = [a, b]
    state._rebuild_cards()
    state._show_detail(_detail(a), load_form=True)
    return state


def test_the_state_builds_one_card_per_menu_in_the_business_zone(screen: dict) -> None:
    state = _state()
    assert [c.name for c in state.menu_cards] == ["Menú principal", "Almuerzos"]
    assert state.menu_cards[0].options[0].label == "Versión 2 · creada el 4 de noviembre"


def test_choosing_a_version_only_accepts_that_card_s_published_versions(screen: dict) -> None:
    state = _state()
    state.choose_card_version(A, V1)
    assert state.menu_cards[0].selected_version_id == V1
    state.choose_card_version(A, V3)  # the draft
    state.choose_card_version(B, V2)  # another menu's version
    state.choose_card_version("nope", V1)
    assert state.menu_cards[0].selected_version_id == V1
    assert state.menu_cards[1].selected_version_id == V1


def test_editar_opens_another_menu_and_keeps_the_open_one(screen: dict) -> None:
    state = _state()
    events = state.edit_menu(B)
    assert isinstance(events, list) and len(events) == 2
    assert "open_menu" in str(events[0])
    assert TOOLBAR_ELEMENT_ID in str(state.edit_menu(A))  # only scrolls: nothing typed is lost
    assert state.edit_menu("not-on-screen") is None


async def test_publicar_esta_version_publishes_the_picked_version_through_the_provider(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.choose_card_version(A, V1)
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
    card = state.menu_cards[0]
    assert card.selected_version_id == V1 and card.selected_is_active  # back to the default


async def test_publishing_another_menu_demotes_the_live_one_on_screen(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()

    async def publish(*args: object, **kw: object) -> PublishOutcome:
        fresh = _input(menu_id=B, name="Almuerzos", live=V1, versions=[(V1, 1, NOV_1)])
        return PublishOutcome(
            detail=_detail(fresh), notice=PUBLISH_OK, tone="ok", graph_ok=True, auth_error=False
        )

    monkeypatch.setattr(module, "publish_version", publish)

    await _run(WhatsAppMenuState.publish_card_version, state, B, V1)

    # The picker's order puts the menu that answers first (m-24986800).
    assert [(c.menu_id, c.status_label) for c in state.menu_cards] == [
        (B, "Respondiendo a tus clientes"),
        (A, "Sin publicar"),
    ]
    assert not state.menu.is_published  # A, open in the editor, no longer answers
    assert [m.is_published for m in state.menus] == [False, True]


async def test_nothing_is_published_without_a_published_version(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state._cards = [_input(live=None, versions=[(V1, 1, None)])]
    state._rebuild_cards()
    called: list[object] = []

    async def publish(*args: object, **kw: object) -> None:
        called.append(args)

    monkeypatch.setattr(module, "publish_version", publish)
    await _run(WhatsAppMenuState.publish_card_version, state, A, "")
    assert called == [] and state.card_busy == ""


async def test_the_active_version_is_never_republished_from_a_card(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    called: list[object] = []

    async def publish(*args: object, **kw: object) -> None:
        called.append(args)

    monkeypatch.setattr(module, "publish_version", publish)
    await _run(WhatsAppMenuState.publish_card_version, state, A, V2)  # V2 is live
    assert called == [] and state.card_busy == "" and state.banner == ""


async def test_a_pick_that_changed_since_the_dialog_is_refused(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dialog said «Publicar la versión 1»; a re-read put the card back on the
    active version meanwhile: nothing is published, the owner picks again."""
    state = _state()
    state.choose_card_version(A, V1)
    state._card_choice = {}  # what a refresh of the list does
    state._rebuild_cards()
    called: list[object] = []

    async def publish(*args: object, **kw: object) -> None:
        called.append(args)

    monkeypatch.setattr(module, "publish_version", publish)
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
    state.choose_card_version(A, V1)
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
    assert state.menu_cards[0].status_label == "En pausa" and state.menu.is_paused
    await _run(WhatsAppMenuState.pause_card, state, A, True)  # already paused: no call
    await _run(WhatsAppMenuState.pause_card, state, B, True)  # not published: no call
    events = await _run(WhatsAppMenuState.pause_card, state, A, False)

    assert calls == [(UUID(A), True), (UUID(A), False)]
    # «Reanudar» is one tap: no banner, a toast that offers «Pausar» back.
    assert len(events) == 1 and RESUMED_TOAST in str(events[0]) and "Pausar" in str(events[0])
    assert state.banner == ""
    assert state.menu_cards[0].status_label == "Respondiendo a tus clientes"
    assert state.card_busy == ""


async def test_a_card_action_waits_for_the_one_in_flight(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.card_busy = B
    called: list[object] = []
    monkeypatch.setattr(module, "set_paused", lambda *a: called.append(a))
    await _run(WhatsAppMenuState.pause_card, state, A, True)
    await _run(WhatsAppMenuState.publish_card_version, state, A, V1)
    assert called == [] and state.card_busy == B


async def test_the_editor_waits_for_a_card_in_flight(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One write to the number at a time: while a card publishes or pauses, the
    editor's «Guardar», «Publicar» and pause switch do nothing (and are disabled)."""
    state = _state()
    state.set_welcome("Hola, bienvenido")  # something to save
    assert state.can_save and state.can_publish
    state.card_busy, state.card_busy_action = B, "publish"
    assert not state.can_save and not state.can_publish
    called: list[object] = []
    monkeypatch.setattr(module, "set_paused", lambda *a: called.append(a))
    monkeypatch.setattr(module, "save_version", lambda *a: called.append(a))

    async def publish(*args: object, **kw: object) -> None:
        called.append(args)

    monkeypatch.setattr(module, "publish_version", publish)
    await _run(WhatsAppMenuState.toggle_pause, state, True)
    await _run(WhatsAppMenuState.save_current_version, state)
    await _run(WhatsAppMenuState.publish_current, state)
    assert called == [] and not state.pausing and not state.saving and not state.publishing


async def test_a_late_publish_after_switching_number_is_dropped(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.choose_card_version(A, V1)

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

    assert state.menu_cards[0].status_label == "Respondiendo a tus clientes"
    assert state.banner == "" and state.card_busy == ""


def test_switching_number_drops_the_cards_and_the_picks(screen: dict) -> None:
    state = _state()
    state.choose_card_version(A, V1)
    state._reset_number_scoped()
    assert state.menu_cards == [] and state._card_choice == {} and state._cards == []


# --- m-24986800: one menu at a time («Menú») and «Eliminar» ------------------------------

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


def test_each_option_says_its_status_in_words() -> None:
    cards = build_menu_cards(
        [_input(name="prueba 2"), _input(menu_id=B, name="Navidad", live=None)],
        zone=BOGOTA,
        today=TODAY,
    )
    assert [c.option_label for c in cards] == [
        "prueba 2 · Respondiendo a tus clientes",
        "Navidad · Sin publicar",
    ]


def test_the_chosen_menu_is_the_pick_then_the_open_one_then_the_answering_one() -> None:
    cards = build_menu_cards(
        [_input(menu_id=A, live=None), _input(menu_id=B, name="Almuerzos")],
        zone=BOGOTA,
        today=TODAY,
    )
    assert chosen_menu_id(cards, picked="", open_id="") == B  # answering
    assert chosen_menu_id(cards, picked="", open_id=A) == A  # what the editor shows
    assert chosen_menu_id(cards, picked=A, open_id=B) == A  # opening the owner's pick
    assert chosen_menu_id(cards, picked="junk", open_id="gone") == B
    assert chosen_menu_id([], picked="", open_id="") == ""
    no_live = build_menu_cards([_input(menu_id=A, live=None)], zone=BOGOTA, today=TODAY)
    assert chosen_menu_id(no_live, picked="", open_id="") == A


def test_eliminar_is_never_offered_on_the_menu_that_answers() -> None:
    answering = _card(_input(name="Principal"))
    assert not answering.can_delete
    assert DELETE_BLOCKED == "Para eliminarlo, primero páusalo."
    paused = _card(_input(name="Principal", paused=True))
    assert paused.can_delete and paused.delete_case == DELETE_PAUSED
    # Archiving does not clear WhatsApp's shortcuts (accepted for now): one line says
    # what really happens — a tap reaches the owner's Chats, no automatic answer.
    assert "si alguien los toca, el mensaje te llega a tus Chats" in paused.delete_case
    assert paused.active_help == "Es la versión que tendrán tus clientes cuando lo reanudes."
    assert paused.delete_label == "Eliminar el menú Principal"
    never = _card(_input(live=None, versions=[(V1, 1, None)]))
    assert never.can_delete and never.delete_case == DELETE_NEVER_SENT
    # Published once, then another menu replaced it: «Nunca les llegó» would be false.
    replaced = _card(_input(live=None))
    assert replaced.can_delete and replaced.delete_case == DELETE_REPLACED
    assert answering.active_help == "Es la versión que tienen tus clientes."


def test_the_confirmation_counts_the_saved_versions() -> None:
    assert _card(_input(paused=True)).delete_tail == " con sus 3 versiones guardadas."
    one = _card(_input(live=None, versions=[(V1, 1, None)]))
    assert one.delete_tail == " con su versión guardada."
    assert _card(_input(live=None, versions=[])).delete_tail == "."


def test_only_the_chosen_card_is_on_screen(screen: dict) -> None:
    state = _state()
    assert [c.menu_id for c in state.chosen_cards] == [A]  # A is open in the editor
    assert state.chosen_menu == A


def test_choosing_a_menu_opens_it(screen: dict) -> None:
    state = _state()
    events = state.choose_menu(B)
    assert events is not None and "open_menu" in str(events[0])
    assert state.chosen_menu == B and [c.menu_id for c in state.chosen_cards] == [B]
    # The picker is disabled while a menu opens; were it not, picking the open one
    # back only drops the pending pick (the editor already shows it).
    state.opening = False
    assert state.choose_menu(A) is None and state.chosen_menu == A
    assert state.choose_menu("junk") is None and state.choose_menu(["x"]) is None


def test_choosing_with_unsaved_changes_asks_first(screen: dict) -> None:
    state = _state()
    state.set_welcome("Hola, bienvenido")
    assert state.dirty
    assert state.choose_menu(B) is None
    assert state.switch_open and state.switch_to == B
    assert state.switch_text == (
        "Tienes cambios sin guardar en «Menú principal». Guárdalos o se pierden."
    )
    assert state.chosen_menu == A  # the picker stays until the owner decides
    state.set_switch_open(False)  # «Cancelar»
    assert not state.switch_open and state.chosen_menu == A


async def test_guardar_y_cambiar_saves_then_opens(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.set_welcome("Hola, bienvenido")
    state.choose_menu(B)
    saved: list[UUID] = []

    def save(tenant_id: UUID, scope: NumberScope, menu_id: UUID, payload: Any) -> MenuDetail:
        saved.append(menu_id)
        return _detail(_input())

    monkeypatch.setattr(module, "save_version", save)
    events = await _run(WhatsAppMenuState.save_and_switch, state)
    assert saved == [UUID(A)] and not state.dirty
    assert len(events) == 1 and "open_menu" in str(events[0])
    assert state.menu_pick == B and not state.switch_open


def test_cambiar_sin_guardar_drops_the_typing_and_opens(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.set_welcome("Hola, bienvenido")
    state.choose_menu(B)
    monkeypatch.setattr(module, "save_version", lambda *a: pytest.fail("saved"))
    events = state.discard_and_switch()
    assert events is not None and "open_menu" in str(events[0])
    assert not state.dirty and not state.switch_open and state.chosen_menu == B
    assert state.discard_and_switch() is None  # nothing pending any more


async def test_guardar_y_cambiar_with_something_to_fix_saves_nothing(
    screen: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    state.dirty = True
    state.error_count = 1
    state.switch_to = B
    monkeypatch.setattr(module, "save_version", lambda *a: pytest.fail("saved"))
    events = await _run(WhatsAppMenuState.save_and_switch, state)
    assert events == [] and state.chosen_menu == A
    assert (state.banner, state.banner_tone) == (SAVE_NEEDS_FIX, "warn")


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
