"""m-24945889 — the chat shortcuts in `WhatsAppChatsState`, offline
(`docs/ux-whatsapp-atajos.md`): «Fotos y videos» › «¿De dónde?», «Tu oferta», «Cómo
llegar» and video pieces. Same fake gateway as the picker tests; nothing reaches Meta, R2
or Postgres (the service rules: `packages/api/tests/test_whatsapp_chat_shortcuts.py`).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.whatsapp.attachments import AttachmentRefused

from . import test_whatsapp_chats_picker as _picker
from . import whatsapp_chats_state as _state_module
from .test_whatsapp_chats_picker import (
    PIECE_NEW,
    PIECE_OK,
    FakeGateway,
    _drain,
    _open_media,
    _Piece,
    _state,
)
from .whatsapp_chats_state import PickSend, WhatsAppChatsState, pick_send_error
from .whatsapp_chats_vm import (
    DIRECTIONS_NO_LOCATION,
    PICK_DIRECTIONS,
    PICK_MEDIA,
    PICK_OFFER,
    PICK_PHOTO,
    PICK_PIECES,
    VIDEO_TOO_LARGE,
    DirectionsVM,
    offer_marked_label,
    offer_stale_note,
    refusal_message,
    size_label,
)

#: The picker tests' fake gateway, as this module's fixture.
gw = _picker.gw

PIECE_VIDEO = "20000000-0000-4000-8000-000000000003"
PIECE_HEAVY = "20000000-0000-4000-8000-000000000004"


#: Two pinned instants (m-24956210): just after UTC midnight, when the business's date
#: (America/Bogota) is still the previous day, and midday, when both dates agree. The
#: day counts must not depend on when CI runs.
_CLOCKS = (
    datetime(2026, 11, 10, 0, 30, tzinfo=UTC),
    datetime(2026, 11, 10, 12, 0, tzinfo=UTC),
)


@pytest.fixture(params=_CLOCKS, ids=["just-after-utc-midnight", "midday"])
def clock(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Freeze `datetime.now` in the state module: «hace N días» never reads the real clock."""
    pinned: datetime = request.param

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def, override]
            return pinned if tz is None else pinned.astimezone(tz)

    monkeypatch.setattr(_state_module, "datetime", _Frozen)
    return pinned


def _mark(gw: FakeGateway, draft_id: str, days: int, now: datetime) -> None:
    gw.promotion = SimpleNamespace(draft_id=UUID(draft_id), marked_at=now - timedelta(days=days))


def _offer_state() -> WhatsAppChatsState:
    state = _state()
    state._zone_name = "America/Bogota"  # the business's zone, as in production
    return state


async def _load_offer(state: WhatsAppChatsState) -> None:
    await WhatsAppChatsState.load_pick_offer.fn(state)


# --- «Fotos y videos» -----------------------------------------------------------------


def test_pieces_and_phone_photo_open_only_through_where_from() -> None:
    state = _state()
    assert state.open_pick(PICK_PIECES) is None and state.open_pick(PICK_PHOTO) is None
    state.open_pick(PICK_MEDIA)
    assert (state.pick_title, state.pick_step, state.pick_total) == ("¿De dónde?", 1, 3)
    assert state.pick_reviewing is False  # no «Enviar» on «¿De dónde?»
    assert state.choose_media_source("pegar-un-enlace") is None
    events = state.choose_media_source(PICK_PIECES)
    assert state.pick_title == "¿Cuál pieza?" and state.pick_step == 2
    assert WhatsAppChatsState.load_pick_pieces in events
    state.pick_back()
    assert state.pick_source == PICK_MEDIA and state.pick_title == "¿De dónde?"
    assert state.choose_media_source(PICK_PHOTO) is not None
    assert state.pick_title == "¿Qué foto?"


# --- «Tu oferta» ----------------------------------------------------------------------


async def test_the_offer_is_one_step_and_sends_the_marked_piece(
    gw: FakeGateway, clock: datetime
) -> None:
    _mark(gw, PIECE_OK, 3, clock)
    state = _offer_state()
    state.open_pick(PICK_OFFER)
    assert state.pick_total == 1 and state.pick_reviewing  # no «Paso 1 de 1»
    assert state.pick_can_send is False  # not read yet
    await _load_offer(state)
    offer = state.pick_offer
    assert offer.marked and not offer.gone and offer.piece.is_offer
    assert offer.marked_label == "marcada hace 3 días" and offer.stale_note == ""
    assert state.pick_caption == "Martes 2x1 en shawarmas." and state.pick_can_send
    state.set_pick_caption("2x1 hoy")
    await _drain(state)
    assert gw.calls[0][0] == "piece"  # the existing send path, one message
    assert gw.calls[0][1]["draft_id"] == UUID(PIECE_OK)
    assert gw.calls[0][1]["caption"] == "2x1 hoy" and gw.calls[0][1]["key"]


async def test_an_old_offer_asks_but_never_blocks(gw: FakeGateway, clock: datetime) -> None:
    _mark(gw, PIECE_OK, 20, clock)
    state = _offer_state()
    state.open_pick(PICK_OFFER)
    await _load_offer(state)
    assert state.pick_offer.stale_note == "La marcaste hace 20 días. ¿Sigue vigente?"
    assert state.pick_can_send


async def test_no_offer_or_a_gone_one_opens_the_empty_state(
    gw: FakeGateway, clock: datetime
) -> None:
    state = _offer_state()
    state.open_pick(PICK_OFFER)
    await _load_offer(state)
    assert state.pick_offer.present and not state.pick_offer.marked
    assert state.pick_can_send is False and state.pick_error == ""
    _mark(gw, PIECE_NEW, 1, clock)  # unapproved now (it was marked approved)
    state.open_pick(PICK_OFFER)
    await _load_offer(state)
    assert state.pick_offer.gone and state.pick_can_send is False


def test_marked_words() -> None:
    zone, now = UTC, datetime(2026, 11, 8, 15, tzinfo=UTC)
    assert offer_marked_label(now - timedelta(hours=2), now, zone) == "marcada hoy"
    assert offer_marked_label(now - timedelta(days=1), now, zone) == "marcada ayer"
    assert offer_marked_label(now - timedelta(days=5), now, zone) == "marcada hace 5 días"
    assert offer_stale_note(14) == "" and offer_stale_note(15).startswith("La marcaste hace 15")


async def test_a_late_offer_is_dropped(gw: FakeGateway) -> None:
    _mark(gw, PIECE_OK, 0, _CLOCKS[1])
    state = _state()
    state.open_pick(PICK_OFFER)
    state.close_picker()
    await _load_offer(state)
    assert state.pick_offer.present is False and state.pick_selected == ""


# --- «Cómo llegar» --------------------------------------------------------------------


async def test_directions_with_a_point_send_on_the_owners_tap(gw: FakeGateway) -> None:
    gw.directions = DirectionsVM(
        present=True, empty=False, has_point=True, name="Bianki", address="Av. 5 #10-20"
    )
    state = _state()
    state.open_pick(PICK_DIRECTIONS)
    assert state.pick_title == "Así le llega tu ubicación" and state.pick_total == 1
    await state._load_pick(PICK_DIRECTIONS)
    assert state.pick_can_send and not gw.calls  # nothing goes by itself
    await _drain(state)
    assert [kind for kind, _ in gw.calls] == ["directions"] and gw.calls[0][1]["key"]
    assert state.pick_open is False


async def test_directions_without_a_point_preview_the_text(gw: FakeGateway) -> None:
    text = "Estamos en Av. 5.\nhttps://maps.google.com/?q=Av.%205"
    gw.directions = DirectionsVM(present=True, empty=False, address="Av. 5", text=text)
    state = _state()
    state.open_pick(PICK_DIRECTIONS)
    await state._load_pick(PICK_DIRECTIONS)
    assert state.pick_directions.text == text and not state.pick_directions.has_point
    assert state.pick_can_send


async def test_no_address_opens_the_empty_state_with_the_way_back(gw: FakeGateway) -> None:
    gw.directions = DirectionsVM(present=True)
    state = _state()
    state.open_pick(PICK_DIRECTIONS)
    await state._load_pick(PICK_DIRECTIONS)
    assert state.pick_directions.empty and state.pick_can_send is False
    href = state.pick_profile_href
    assert href.startswith("/whatsapp?tab=numero&sub=perfil&volver=")
    assert "tab%3Dchats" in href
    plan = PickSend(
        session=1, source=PICK_DIRECTIONS, thread_id="t", connection_id="c", request_key="k"
    )
    assert pick_send_error(AttachmentRefused("no_location"), plan) == DIRECTIONS_NO_LOCATION


# --- video pieces ---------------------------------------------------------------------


def _videos(gw: FakeGateway) -> None:
    gw.pieces = [
        _Piece(
            PIECE_VIDEO,
            "approved",
            "Así se prepara.",
            title="Video shawarma",
            media_type="video",
            bytes=3_400_000,
        ),
        _Piece(
            PIECE_HEAVY,
            "approved",
            "Largo.",
            title="Video largo",
            media_type="video",
            bytes=20 * 1024 * 1024,
            too_large=True,
        ),
    ]


async def test_a_heavy_video_cannot_be_sent(gw: FakeGateway) -> None:
    _videos(gw)
    _mark(gw, PIECE_VIDEO, 0, _CLOCKS[1])
    state = _state()
    _open_media(state, PICK_PIECES)
    await state._load_pick(PICK_PIECES)
    cards = {c.id: c for c in state.pick_visible_pieces}
    assert cards[PIECE_VIDEO].is_video and cards[PIECE_VIDEO].size_label == "3,2 MB"
    assert cards[PIECE_VIDEO].is_offer  # «Tu oferta» badge in «Tus piezas»
    assert cards[PIECE_HEAVY].too_large and cards[PIECE_VIDEO].photos_label == ""
    state.choose_piece(PIECE_HEAVY)
    assert state.pick_step == 3 and state.pick_can_send is False
    assert await _drain(state) == [] and gw.calls == []
    state.pick_back()
    state.choose_piece(PIECE_VIDEO)
    assert state.pick_can_send
    assert refusal_message("video_too_large", PICK_PIECES) == VIDEO_TOO_LARGE


def test_size_words() -> None:
    assert size_label(None) == "" and size_label(0) == ""
    assert size_label(850 * 1024) == "850 KB"
    assert size_label(16 * 1024 * 1024) == "16,0 MB"


def test_the_tab_draws_the_shortcuts_and_never_autoplays() -> None:
    from .whatsapp_tab_chats import chats_tab

    rendered = str(chats_tab().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in (
        "Aún no marcas tu oferta",
        "Ir a Por aprobar",
        "Cambiar tu oferta",
        "Aún no tienes la dirección de tu local",
        "Completar mi dirección",
        "Si pones tu local en el mapa, le llega el mapa con la ruta.",
        "Ponerlo en el mapa",
        "Video",
        "Muy pesado",
        VIDEO_TOO_LARGE,
        "Crear de nuevo",
    ):
        assert present(text), text
    assert "autoplay" not in rendered.lower()
    assert "choose_media_source" in rendered


def test_offer_and_directions_reset_with_the_picker() -> None:
    state = _state()
    state.pick_offer = dataclasses.replace(state.pick_offer, present=True, marked=True)
    state.pick_directions = DirectionsVM(present=True, empty=False)
    state._reset_picker()
    assert not state.pick_offer.present and not state.pick_directions.present


# --- a sent pin in the transcript (backend 1d2c9ae1) ----------------------------------


def test_a_location_row_shows_its_pin_text_never_an_empty_bubble() -> None:
    from .test_whatsapp_chats import NOW, _message
    from .whatsapp_chats_vm import build_message_vm, outbox_text

    sent = build_message_vm(
        _message(direction="outbound", text="Ubicación: Bianki", media_kind="location"),
        now=NOW,
        zone=UTC,
    )
    assert sent.is_location and sent.text == "Ubicación: Bianki"
    bare = build_message_vm(
        _message(direction="outbound", text=None, media_kind="location"), now=NOW, zone=UTC
    )
    assert bare.is_location and bare.text == "Ubicación enviada"
    plain = build_message_vm(_message(text="Hola"), now=NOW, zone=UTC)
    assert not plain.is_location
    assert outbox_text({"type": "location", "location": {"name": "Bianki"}}) == (
        "Ubicación: Bianki"
    )
    assert outbox_text({"type": "location", "location": {}}) == "Ubicación enviada"


def test_a_pin_row_without_coordinates_has_no_map_link() -> None:
    """Today's `MessageRecord` carries no coordinates: «Ver en el mapa» stays hidden."""
    import inspect

    from . import whatsapp_tab_chats
    from .test_whatsapp_chats import NOW, _message
    from .whatsapp_chats_vm import build_message_vm

    pin = build_message_vm(
        _message(direction="outbound", text="Ubicación: Bianki", media_kind="location"),
        now=NOW,
        zone=UTC,
    )
    assert pin.is_location and pin.location_href == ""
    body = inspect.getsource(whatsapp_tab_chats._bubble_body)
    assert 'm.location_href != ""' in body  # the link is drawn only with a href
