"""m-24976895 — «Stickers y videos de tu marca» in the chat, offline, through the
PRODUCTION `ChatsGateway` with a fake send service underneath (m-24976894): the third
«¿De dónde?» card, named by kind — always there since m-24986801 §4, with an empty step
(«Revisarlos en Por aprobar» or «Crear para esta temporada») when nothing is approved —
«¿Qué le mandas?» with
the current season first, a sticker alone (never a caption) and a video with an optional
caption, every refusal in the send module's words, the closed window, and a late list
dropped. The «+» keeps its six rows."""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from qualify_api.whatsapp.chats import WindowClosed
from qualify_api.whatsapp.seasonal_send import REFUSAL_TEXT, SeasonalSendRefused

from . import test_whatsapp_chats_provider as _provider
from . import whatsapp_chats_state as state_module
from .test_whatsapp_chats_provider import NUMBER, TENANT, USER, World
from .whatsapp_chats_provider import ChatsGateway, PickerScope
from .whatsapp_chats_state import WhatsAppChatsState
from .whatsapp_chats_vm import (
    EMPTY_THREAD,
    PICK_MEDIA,
    PICK_SEASONAL,
    PICK_SOURCE_CARDS,
    PICK_WINDOW_CLOSED,
    build_seasonal_picks,
    failure_label,
    seasonal_card_title,
)

world = _provider.world  # the provider tests' fixture

BRAND = UUID("c0000000-0000-4000-8000-000000976897")
STICKER = UUID("30000000-0000-4000-8000-000000000001")
VIDEO = UUID("30000000-0000-4000-8000-000000000002")
OLD = UUID("30000000-0000-4000-8000-000000000003")


def _row(media: UUID, kind: str, label: str, key: str) -> Any:
    ext = "mp4" if kind == "video" else "webp"
    return SimpleNamespace(
        id=media,
        kind=kind,
        season_key=key,
        season_label=label,
        object_key=f"seasonal/{TENANT}/{BRAND}/{key}/{media}-1.{ext}",
    )


class FakeLibrary:
    """`SeasonalMediaService.list_seasons`'s surface: per season, its counts by status."""

    def __init__(self) -> None:
        self.seasons: list[Any] = []
        self.calls: list[tuple[UUID, UUID]] = []

    def list_seasons(self, *, tenant_id: UUID, brand_id: UUID) -> list[Any]:
        self.calls.append((tenant_id, brand_id))
        return list(self.seasons)


class FakeSend:
    """`SeasonalSendService`'s surface: the approved list and the send."""

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.sent: list[tuple[Any, ...]] = []
        self.refuse: BaseException | None = None

    def list_for_chat(self, tenant_id: UUID, connection_id: UUID) -> list[Any]:
        return list(self.rows)

    def preview(self, tenant_id: UUID, connection_id: UUID, media_id: UUID) -> Any:
        raise AssertionError("not used by the screen")

    def send(self, tenant_id, thread_id, user_id, media_id, caption, *, request_key=None):  # noqa: ANN001, ANN201
        self.sent.append((media_id, caption, request_key))
        if self.refuse is not None:
            raise self.refuse
        return media_id


ROWS = [
    _row(STICKER, "sticker", "Navidad 2026", "navidad-2026"),
    _row(VIDEO, "video", "Navidad 2026", "navidad-2026"),
    _row(OLD, "sticker", "Día de la Madre 2026", "madre-2026"),
]


@pytest.fixture
def chat(world: World, monkeypatch: pytest.MonkeyPatch) -> tuple[WhatsAppChatsState, FakeSend]:
    send = FakeSend(list(ROWS))
    library = FakeLibrary()
    gw = ChatsGateway(
        service=world.service, store=world.store, seasonal=send, seasonal_library=library
    )
    send.library = library  # type: ignore[attr-defined]  # reached by the empty-state tests
    monkeypatch.setattr(gw, "picker_scope", lambda t, c: PickerScope(BRAND, "food_drink", ""))
    monkeypatch.setattr(state_module, "gateway", lambda: gw)
    # previews: the business-bound signer with no Redis and no R2 behind it
    from . import seasonal_media

    monkeypatch.setattr(
        seasonal_media,
        "issue_seasonal_view_path",
        lambda tenant, brand, key, **_k: (
            f"/r2seasonal/{key.rsplit('/', 1)[-1]}" if brand == BRAND else ""
        ),
    )

    async def tenant(self: WhatsAppChatsState) -> UUID:
        return TENANT

    async def acting(self: WhatsAppChatsState, tenant_id: UUID) -> UUID:
        return USER

    monkeypatch.setattr(WhatsAppChatsState, "_tenant", tenant)
    monkeypatch.setattr(WhatsAppChatsState, "_acting_user", acting)
    thread = str(world.thread(inbound_ago=timedelta(minutes=5)))
    state = WhatsAppChatsState()
    state._connection_id = str(NUMBER)
    state.rows = [
        dataclasses.replace(
            EMPTY_THREAD, thread_id=thread, window_open=True, window_label="x", window_tone="ok"
        )
    ]
    state.open_thread_id = thread
    return state, send


async def _open(state: WhatsAppChatsState) -> None:
    state.open_pick(PICK_MEDIA)
    await WhatsAppChatsState.load_pick_seasonal.fn(state)


async def _send(state: WhatsAppChatsState) -> list[Any]:
    return [e async for e in state._send_pick()]


def test_still_six_rows() -> None:
    assert len(PICK_SOURCE_CARDS) == 6
    assert PICK_SEASONAL not in {k for k, _i, _t in PICK_SOURCE_CARDS}


def test_only_approved_rows_and_the_title_by_kind() -> None:
    rows = [
        SimpleNamespace(id=STICKER, kind="sticker", season_label="Navidad 2026"),
        SimpleNamespace(id=OLD, kind="video", season_label="Navidad 2026", status="ready"),
    ]
    assert [p.id for p in build_seasonal_picks(rows)] == [str(STICKER)]
    assert seasonal_card_title(2, 0) == "Stickers de tu marca"
    assert seasonal_card_title(0, 1) == "Videos de tu marca"
    assert seasonal_card_title(1, 1) == "Stickers y videos de tu marca"
    assert failure_label("seasonal_withdrawn") == (
        "No se envió: la pieza dejó de estar aprobada o su temporada se archivó."
    )


async def test_the_card_is_there_with_nothing_approved(chat: Any) -> None:
    """m-24986801 §4 a): always the third card; with nothing approved it says so."""
    state, send = chat
    send.rows = []
    await _open(state)
    assert state.pick_seasonal == [] and state.pick_seasonal_empty
    assert state.pick_show_progress  # «¿De dónde?» keeps its «Paso 1 de 3»
    assert state.pick_seasonal_card == "Stickers y videos de tu marca"
    assert state.pick_seasonal_line == "Aún no tienes: créalos para esta temporada."
    assert state.pick_seasonal_card_name == (
        "Stickers y videos de tu marca. Aún no tienes: créalos para esta temporada."
    )


async def test_nothing_approved_but_some_waiting_leads_to_approving_them(chat: Any) -> None:
    state, send = chat
    send.rows = []
    send.library.seasons = [
        SimpleNamespace(archived=False, counts={"ready": 2, "pending": 1}),
        SimpleNamespace(archived=True, counts={"ready": 5}),  # an archived season: not counted
    ]
    await _open(state)
    assert send.library.calls == [(TENANT, BRAND)]  # the number's business, not another
    assert state.choose_media_source(PICK_SEASONAL) is not None
    assert state.pick_step == 2 and state.pick_source == PICK_SEASONAL
    assert state.pick_seasonal_pending == 2
    assert state.pick_seasonal_pending_title == (
        "Tienes 2 stickers o videos esperando tu aprobación"
    )
    assert not state.pick_show_progress  # no step bar on the empty step
    state.pick_seasonal_pending = 1
    assert state.pick_seasonal_pending_title == "Tienes 1 sticker o video esperando tu aprobación"
    assert state.pick_title == "Stickers y videos de tu marca" and state.pick_help == ""
    assert not state.pick_reviewing and not state.pick_can_send
    assert state.choose_seasonal("anything") is None  # nothing to choose, nothing sent
    await _send(state)
    assert send.sent == []


async def test_nothing_at_all_leads_to_creating_them(chat: Any) -> None:
    state, send = chat
    send.rows = []
    await _open(state)
    state.choose_media_source(PICK_SEASONAL)
    assert state.pick_seasonal_pending == 0 and state.pick_seasonal_empty
    await _send(state)
    assert send.sent == []
    state.pick_back()  # «Atrás» goes back to «¿De dónde?»
    assert state.pick_step == 1


async def test_a_failed_read_never_says_there_are_none(chat: Any) -> None:
    """Review finding: a failed read is not «Aún no tienes» (it may be false and leads
    to paying for a new batch): the step says it failed and offers «Reintentar»."""
    state, send = chat
    send.rows = []

    def down(**_k: object) -> list[Any]:
        raise RuntimeError("db down")

    send.library.list_seasons = down
    await _open(state)
    assert state.pick_seasonal_failed and not state.pick_seasonal_empty
    assert state.pick_seasonal_line == "Para saludar y celebrar con tu marca."
    state.choose_media_source(PICK_SEASONAL)
    assert state.pick_title == "¿Qué le mandas?"
    retry = state.retry_pick_list()
    assert retry is not None and "load_pick_seasonal" in str(retry)
    assert not state.pick_seasonal_loaded and not state.pick_seasonal_failed
    send.library.list_seasons = lambda **_k: []
    await WhatsAppChatsState.load_pick_seasonal.fn(state)
    assert state.pick_seasonal_empty and not state.pick_seasonal_failed


async def test_a_failed_approved_list_is_a_failure_too(chat: Any) -> None:
    state, send = chat

    def down(*_a: object) -> list[Any]:
        raise RuntimeError("r2 down")

    send.list_for_chat = down  # type: ignore[method-assign]
    await _open(state)
    assert state.pick_seasonal_failed and state.pick_seasonal == []
    assert not state.pick_seasonal_empty


def test_the_empty_step_links_and_its_words() -> None:
    from .whatsapp_chats_vm import SEASONAL_CREATE_HREF, SEASONAL_PENDING_HREF
    from .whatsapp_tab_chats import chats_tab

    rendered = str(chats_tab().render())
    for text in (
        "Apruébalos y quedan listos para mandar desde aquí.",
        "Revisarlos en Por aprobar",
        "Aún no tienes stickers ni videos",
        "Crear para esta temporada",
        "No pudimos traer tus stickers y videos. Vuelve a intentarlo en un momento.",
        SEASONAL_PENDING_HREF,
        SEASONAL_CREATE_HREF,
    ):
        assert text in rendered or json.dumps(text)[1:-1].replace("\\", "\\\\") in rendered, text
    # m-25017173: WhatsApp › Chats has no stickers sub-tab; creating opens Tu marca,
    # with the way back to the chats.
    assert SEASONAL_CREATE_HREF == "/brand/kit?crear=temporada&volver=%2Fwhatsapp%3Ftab%3Dchats"
    assert SEASONAL_PENDING_HREF == "/drafts?ver=stickers"


async def test_sticker_alone_then_video_with_its_caption(chat: Any) -> None:
    state, send = chat
    await _open(state)
    assert state.pick_seasonal_card == "Stickers y videos de tu marca"
    assert state.pick_seasonal[0].src.startswith("/r2seasonal/")  # business-bound preview
    state.choose_media_source(PICK_SEASONAL)
    assert state.pick_title == "¿Qué le mandas?" and state.pick_seasonal_both
    assert [p.id for p in state.pick_seasonal_current] == [str(STICKER)]
    assert [p.id for p in state.pick_seasonal_earlier] == [str(OLD)]

    state.choose_seasonal(str(STICKER))
    assert state.pick_step == 3 and "Nada sale sin que toques «Enviar»." in state.pick_help
    state.set_pick_caption("no debería salir")  # the field is not even drawn for a sticker
    await _send(state)
    assert send.sent[-1][:2] == (STICKER, None)  # never a caption with a sticker
    assert state.pick_open is False  # queued: the drawer closed

    await _open(state)
    state.choose_media_source(PICK_SEASONAL)
    state.set_seasonal_tab("video")
    state.choose_seasonal(str(VIDEO))
    assert state.pick_caption == ""  # optional, empty by default
    state.set_pick_caption("¡Feliz Navidad!")
    await _send(state)
    assert send.sent[-1][:2] == (VIDEO, "¡Feliz Navidad!") and send.sent[-1][2]


@pytest.mark.parametrize("reason", sorted(REFUSAL_TEXT))
async def test_every_refusal_in_the_send_modules_words(chat: Any, reason: str) -> None:
    state, send = chat
    send.refuse = SeasonalSendRefused(reason)
    await _open(state)
    state.choose_media_source(PICK_SEASONAL)
    state.set_seasonal_tab("video")
    state.choose_seasonal(str(VIDEO))
    await _send(state)
    assert state.pick_send_error == REFUSAL_TEXT[reason] and state.pick_open
    first_key = send.sent[-1][2]
    await _send(state)  # «Reintentar» reuses the intent's key
    assert send.sent[-1][2] == first_key


async def test_the_closed_window_offers_the_approved_message(chat: Any) -> None:
    state, send = chat
    send.refuse = WindowClosed(None)
    await _open(state)
    state.choose_media_source(PICK_SEASONAL)
    state.choose_seasonal(str(STICKER))
    await _send(state)
    assert state.pick_send_error == PICK_WINDOW_CLOSED and state.pick_window_closed


async def test_a_late_list_is_dropped(chat: Any) -> None:
    state, _send_service = chat
    state.open_pick(PICK_MEDIA)
    state.close_picker()
    await WhatsAppChatsState.load_pick_seasonal.fn(state)
    assert state.pick_seasonal == []


def test_the_tab_draws_it_and_never_autoplays() -> None:
    from .whatsapp_tab_chats import chats_tab

    rendered = str(chats_tab().render())
    for text in (
        "De otras temporadas",
        "Los stickers llegan solos, sin texto.",
        "Texto que acompaña el video (opcional)",
    ):
        assert text in rendered or json.dumps(text)[1:-1].replace("\\", "\\\\") in rendered, text
    assert "autoplay" not in rendered.lower()


def test_every_seasonal_failure_code_has_its_own_line() -> None:
    expected = {
        "seasonal_withdrawn": (
            "No se envió: la pieza dejó de estar aprobada o su temporada se archivó."
        ),
        "not_sticker_size": (
            "No se envió: el sticker no cumple el tamaño de WhatsApp (512 × 512, menos de "
            "500 KB). Pide otro."
        ),
        "sticker_too_large": (
            "No se envió: el sticker no cumple el tamaño de WhatsApp (512 × 512, menos de "
            "500 KB). Pide otro."
        ),
        "video_too_large": "No se envió: el video pesa más de 16 MB. Pide otro.",
        "not_a_sticker": "No se envió: el archivo no es válido. Pide otro.",
        "not_a_video": "No se envió: el archivo no es válido. Pide otro.",
    }
    for code, line in expected.items():
        assert failure_label(code) == line, code
    assert failure_label("attachment_refused").startswith("No se envió: el archivo cambió")
    assert failure_label("something_else") == "No se entregó"


def test_every_mapped_code_is_a_backend_code() -> None:
    """Review of 996bef52: no hand-typed code that the backend does not raise."""
    import inspect
    import re

    from qualify_api.whatsapp import outbox, seasonal_send

    from .whatsapp_chats_vm import SEASONAL_FILE_FAILURES, _unsent_lines

    # The backend names its file codes (`FILE_REFUSAL_*`, collected in `FILE_REFUSAL_CODES`);
    # every one of them is raised by `check_file`, and the screen maps exactly those.
    source = inspect.getsource(seasonal_send)
    raised_names = set(re.findall(r"SeasonalFileRefused\((FILE_REFUSAL_[A-Z_]+)\)", source))
    raised = {getattr(seasonal_send, name) for name in raised_names}
    assert raised == set(seasonal_send.FILE_REFUSAL_CODES)
    assert set(SEASONAL_FILE_FAILURES) == raised  # exactly the file codes, none invented
    errors = {v for k, v in vars(outbox).items() if k.startswith("ERROR_")}
    assert set(_unsent_lines()) <= errors | raised


def test_the_create_link_s_way_back_is_safe_and_says_chats() -> None:
    """m-25017173: Tu marca reads `?volver=` through the same guard as every other way
    back (no open redirect) and names where it leads."""
    from urllib.parse import parse_qs, urlsplit

    from .catalog_vm import RETURN_LABEL, return_label_for, return_path_from_query
    from .whatsapp_chats_vm import SEASONAL_CREATE_HREF, SEASONAL_EMPTY_TEXT

    params = {k: v[0] for k, v in parse_qs(urlsplit(SEASONAL_CREATE_HREF).query).items()}
    assert params["crear"] == "temporada"
    back = return_path_from_query(params)
    assert back == "/whatsapp?tab=chats"
    assert return_label_for(back) == "Volver a tus chats"
    assert return_label_for("/create") == RETURN_LABEL
    assert return_path_from_query({"volver": "https://example.com/whatsapp"}) == ""
    assert "en Tu marca" in SEASONAL_EMPTY_TEXT
    assert "sigue respondiendo" not in SEASONAL_EMPTY_TEXT
