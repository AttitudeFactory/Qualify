"""m-24976895 — «Stickers y videos de tu marca» in the chat, offline: the third
«¿De dónde?» card only with something approved (named by kind), «¿Qué le mandas?» with
the current season first, a sticker alone and a video with an optional caption, and the
send stubbed until m-24976894. The «+» keeps its six rows."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

from . import test_whatsapp_chats_picker as _picker
from .test_whatsapp_chats_picker import FakeGateway, _drain, _state
from .whatsapp_chats_provider import SeasonalSendNotConnected
from .whatsapp_chats_state import WhatsAppChatsState
from .whatsapp_chats_vm import (
    PICK_MEDIA,
    PICK_SEASONAL,
    PICK_SOURCE_CARDS,
    SEASONAL_SEND_PENDING,
    SeasonalPickVM,
    build_seasonal_picks,
    seasonal_card_title,
)

#: The picker tests' fake gateway, as this module's fixture.
gw = _picker.gw

STICKER = "30000000-0000-4000-8000-000000000001"
VIDEO = "30000000-0000-4000-8000-000000000002"
OLD = "30000000-0000-4000-8000-000000000003"


def _approved(gw: FakeGateway, picks: list[SeasonalPickVM]) -> None:
    def approved_seasonal(tenant_id: UUID, brand_id: UUID) -> list[SeasonalPickVM]:
        return picks

    def send_seasonal_media(tenant, connection, thread, user, media_id, caption, request_key):  # noqa: ANN001, ANN202
        gw.calls.append(("seasonal", {"media": str(media_id), "caption": caption}))
        raise SeasonalSendNotConnected(str(media_id))

    gw.approved_seasonal = approved_seasonal  # type: ignore[attr-defined]
    gw.send_seasonal_media = send_seasonal_media  # type: ignore[attr-defined]


PICKS = [
    SeasonalPickVM(id=STICKER, season_label="Navidad 2026", current=True, src="/s"),
    SeasonalPickVM(id=VIDEO, is_video=True, season_label="Navidad 2026", current=True, src="/v"),
    SeasonalPickVM(id=OLD, season_label="Día de la Madre 2026", current=False, src="/o"),
]


async def _open(state: WhatsAppChatsState) -> None:
    state.open_pick(PICK_MEDIA)
    await WhatsAppChatsState.load_pick_seasonal.fn(state)


def test_still_six_rows() -> None:
    assert len(PICK_SOURCE_CARDS) == 6
    assert PICK_SEASONAL not in {k for k, _i, _t in PICK_SOURCE_CARDS}


def test_only_approved_rows_and_the_title_by_kind() -> None:
    rows = [
        SimpleNamespace(id=STICKER, kind="sticker", season_label="Navidad 2026"),
        SimpleNamespace(id=OLD, kind="video", season_label="Navidad 2026", status="ready"),
    ]
    picks = build_seasonal_picks(rows)
    assert [p.id for p in picks] == [STICKER]  # a non-approved row never reaches the chat
    assert seasonal_card_title(2, 0) == "Stickers de tu marca"
    assert seasonal_card_title(0, 1) == "Videos de tu marca"
    assert seasonal_card_title(1, 1) == "Stickers y videos de tu marca"


async def test_no_card_without_something_approved(gw: FakeGateway) -> None:
    _approved(gw, [])
    state = _state()
    await _open(state)
    assert state.pick_seasonal == [] and state.choose_media_source(PICK_SEASONAL) is None
    assert state.pick_source == PICK_MEDIA


async def test_current_season_first_sticker_alone_video_with_caption(gw: FakeGateway) -> None:
    _approved(gw, PICKS)
    state = _state()
    await _open(state)
    assert state.pick_seasonal_card == "Stickers y videos de tu marca"
    state.choose_media_source(PICK_SEASONAL)
    assert state.pick_title == "¿Qué le mandas?" and state.pick_step == 2
    assert state.pick_seasonal_both and state.pick_seasonal_tab == "sticker"
    assert [p.id for p in state.pick_seasonal_current] == [STICKER]
    assert [p.id for p in state.pick_seasonal_earlier] == [OLD]
    assert state.choose_seasonal("no-es-uno") is None

    state.choose_seasonal(STICKER)
    assert state.pick_step == 3 and state.pick_reviewing and state.pick_caption == ""
    assert "Nada sale sin que toques «Enviar»." in state.pick_help
    state.set_pick_caption("no debería salir")
    events = await _drain(state)
    assert gw.calls[-1] == ("seasonal", {"media": STICKER, "caption": ""})  # alone
    assert state.pick_send_error == SEASONAL_SEND_PENDING and events == []

    state.pick_back()
    state.set_seasonal_tab("video")
    state.choose_seasonal(VIDEO)
    assert state.pick_caption == ""  # optional, empty by default
    state.set_pick_caption("¡Feliz Navidad!")
    await _drain(state)
    assert gw.calls[-1] == ("seasonal", {"media": VIDEO, "caption": "¡Feliz Navidad!"})


async def test_a_late_list_is_dropped(gw: FakeGateway) -> None:
    _approved(gw, PICKS)
    state = _state()
    state.open_pick(PICK_MEDIA)
    state.close_picker()
    await WhatsAppChatsState.load_pick_seasonal.fn(state)
    assert state.pick_seasonal == []


def test_the_tab_draws_it_and_never_autoplays() -> None:
    from .whatsapp_tab_chats import chats_tab

    rendered = str(chats_tab().render())
    for text in (
        "Para saludar y celebrar con tu marca.",
        "De otras temporadas",
        "Los stickers llegan solos, sin texto.",
        "Texto que acompaña el video (opcional)",
    ):
        assert text in rendered or json.dumps(text)[1:-1].replace("\\", "\\\\") in rendered, text
    assert "autoplay" not in rendered.lower()
