"""m-24945888 — «Foto o menú» in `WhatsAppChatsState`, offline.

A real state instance over a fake gateway (`state_module.gateway` patched, the tenant and
the acting user stubbed): each source's happy path, the caption prefilled by trade, a
product «Sin foto» sent as text, an unapproved piece sent with its warning and nothing
else touched, the closed window's way out, one request key per intent (a double tap
queues once, a retry reuses the key), a late result dropped, and the phone photo's
type/size refusals. Nothing reaches Meta, R2 or Postgres: the service rules are pinned in
`packages/api/tests/test_whatsapp_chat_attachments.py`.
"""

from __future__ import annotations

import dataclasses
import io
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image
from qualify_api.whatsapp.attachments import AttachmentRefused, MenuPreview
from qualify_api.whatsapp.chats import WindowClosed

from . import whatsapp_chats_state as state_module
from .whatsapp_chats_provider import PickerScope
from .whatsapp_chats_state import PickSend, WhatsAppChatsState, pick_send_error
from .whatsapp_chats_vm import (
    CAPTION_TOO_LONG,
    EMPTY_THREAD,
    MAX_CAPTION_CHARS,
    MENU_EMPTY,
    PHOTO_TOO_LARGE,
    PHOTO_UNREADABLE,
    PHOTO_WRONG_TYPE,
    PICK_MENU,
    PICK_PHOTO,
    PICK_PIECES,
    PICK_PRODUCTS,
    PICK_WINDOW_CLOSED,
    PIECE_NOT_PHOTO,
    PIECES_UNAPPROVED,
    SAVED_PHOTO_UNREADABLE,
    SEND_PHOTO_FAILED,
    build_product_cards,
    caption_error,
    is_food_business,
    photo_refusal,
    pick_heading,
    pick_total_steps,
    product_caption,
    refusal_message,
)

TENANT = UUID("a0000000-0000-4000-8000-000000945888")
BRAND = UUID("c0000000-0000-4000-8000-000000945888")
CONN = "d0000000-0000-4000-8000-000000945888"
THREAD = "f0000000-0000-4000-8000-000000945888"
OTHER_THREAD = "f1000000-0000-4000-8000-000000945888"
USER = UUID("e0000000-0000-4000-8000-000000945888")
SHAWARMA = "10000000-0000-4000-8000-000000000001"
LIMONADA = "10000000-0000-4000-8000-000000000002"
PIECE_OK = "20000000-0000-4000-8000-000000000001"
PIECE_NEW = "20000000-0000-4000-8000-000000000002"


@dataclass(frozen=True)
class _Product:
    id: str
    name: str
    price_label: str
    description: str = ""
    thumb_url: str = ""
    has_photo: bool = True
    thumb_key: str = ""


@dataclass(frozen=True)
class _Piece:
    id: str
    status: str
    caption_suggestion: str
    caption_shortened: bool = False
    thumb_url: str = "https://media.example/p.jpg"
    title: str = ""
    image_count: int = 1


@dataclass
class FakeGateway:
    sector: str = "food_drink"
    rubro: str = ""
    products: list[_Product] = field(default_factory=list)
    pieces: list[_Piece] = field(default_factory=list)
    menu: MenuPreview | None = None
    fail_with: list[BaseException] = field(default_factory=list)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def picker_scope(self, tenant_id: UUID, connection_id: UUID) -> PickerScope:
        return PickerScope(brand_id=BRAND, sector=self.sector, rubro=self.rubro)

    def list_products_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[_Product]:
        assert brand_id == BRAND
        return list(self.products)

    def list_pieces_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[_Piece]:
        assert brand_id == BRAND
        return list(self.pieces)

    def menu_preview(self, tenant_id: UUID, connection_id: UUID) -> MenuPreview:
        assert self.menu is not None
        return self.menu

    def _send(self, kind: str, **kwargs: Any) -> UUID:
        self.calls.append((kind, kwargs))
        if self.fail_with:
            raise self.fail_with.pop(0)
        return uuid4()

    def send_product(self, tenant, connection, thread, user, product_id, caption, request_key):
        return self._send("product", product_id=product_id, caption=caption, key=request_key)

    def send_piece(self, tenant, connection, thread, user, draft_id, caption, request_key):
        return self._send("piece", draft_id=draft_id, caption=caption, key=request_key)

    def send_menu_list(self, tenant, connection, thread, user, request_key):
        return self._send("menu", key=request_key)

    def send_photo(
        self,
        tenant,
        connection,
        thread,
        user,
        content,
        content_type,
        filename,
        caption,
        request_key,
    ):
        return self._send(
            "photo",
            content=content,
            content_type=content_type,
            filename=filename,
            caption=caption,
            key=request_key,
        )


class _Upload:
    def __init__(self, data: bytes, content_type: str, name: str = "foto.png") -> None:
        self._data, self.content_type, self.name = data, content_type, name

    async def read(self) -> bytes:
        return self._data


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (32, 24), (10, 120, 110)).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> FakeGateway:
    fake = FakeGateway(
        products=[
            _Product(LIMONADA, "Limonada", "$1", has_photo=False),
            _Product(SHAWARMA, "Shawarma mixto", "$5", thumb_key="t/shawarma.jpg"),
        ],
        pieces=[
            _Piece(PIECE_OK, "approved", "Martes 2x1 en shawarmas.", title="Martes 2x1"),
            _Piece(PIECE_NEW, "unapproved", "Nuevo combo.", title="Nuevo combo", image_count=4),
        ],
        menu=MenuPreview(
            body="Este es nuestro menú.",
            button_label="Ver productos",
            header=None,
            footer=None,
            product_count=12,
            rows_shown=9,
            overflows=True,
            menu_version_id=None,
        ),
    )
    monkeypatch.setattr(state_module, "gateway", lambda: fake)

    async def tenant(self: WhatsAppChatsState) -> UUID:
        return TENANT

    async def acting(self: WhatsAppChatsState, tenant_id: UUID) -> UUID:
        return USER

    monkeypatch.setattr(WhatsAppChatsState, "_tenant", tenant)
    monkeypatch.setattr(WhatsAppChatsState, "_acting_user", acting)
    return fake


def _row(thread_id: str = THREAD, *, window_open: bool = True, tone: str = "ok") -> Any:
    return dataclasses.replace(
        EMPTY_THREAD,
        thread_id=thread_id,
        title="María G.",
        window_open=window_open,
        window_label="Puedes escribirle hasta las 5:00 p. m.",
        window_tone=tone,
    )


def _state() -> WhatsAppChatsState:
    state = WhatsAppChatsState()
    state._connection_id = CONN
    state.rows = [_row(), _row(OTHER_THREAD)]
    state.open_thread_id = THREAD
    state.open_picker()
    assert state.pick_open
    return state


async def _drain(state: WhatsAppChatsState) -> list[Any]:
    return [event async for event in state._send_pick()]


# --- pure helpers ---------------------------------------------------------------------


def test_caption_asks_by_trade_and_skips_a_missing_price() -> None:
    assert product_caption("Shawarma mixto", "$5", food=True) == (
        "Shawarma mixto — $5. ¿Te lo preparo?"
    )
    assert product_caption("Plan Cartagena", "$300", food=False) == (
        "Plan Cartagena — $300. ¿Te interesa?"
    )
    assert product_caption("Combo", "", food=True) == "Combo. ¿Te lo preparo?"
    with_desc = product_caption("Combo", "$7", food=True, description="Shawarma y papas")
    assert with_desc == "Combo — $7. ¿Te lo preparo?\nShawarma y papas"
    long_desc = product_caption("Combo", "$7", food=True, description="x " * 700)
    assert long_desc == "Combo — $7. ¿Te lo preparo?"  # the description did not fit


def test_trade_reads_the_niche_or_the_owners_words() -> None:
    assert is_food_business("food_drink")
    assert is_food_business("", "Heladería de yogur")
    assert is_food_business("", "Comidas rápidas: shawarma y ensaladas")
    assert not is_food_business("travel_lifestyle", "Agencia de viajes")
    assert not is_food_business("", "")  # unknown: the neutral question


def test_heading_uses_the_first_name_or_the_whole_number() -> None:
    assert pick_heading("María G.") == "¿Qué le quieres mandar a María?"
    assert pick_heading("+57 300 111 2233") == "¿Qué le quieres mandar a +57 300 111 2233?"
    assert pick_heading("") == "¿Qué le quieres mandar?"


def test_products_without_photo_go_last_and_keep_their_order() -> None:
    cards = build_product_cards(
        [
            _Product("a", "A", "$1", has_photo=False),
            _Product("b", "B", "$2"),
            _Product("c", "C", "$3", has_photo=False),
            _Product("d", "D", "$4", thumb_url="https://x/d.jpg", thumb_key="k"),
        ]
    )
    assert [c.id for c in cards] == ["b", "d", "a", "c"]
    assert cards[1].thumb_key == ""  # a ready URL wins over the upload-store key


def test_photo_refusals_and_refusal_reasons_in_words() -> None:
    assert photo_refusal("image/png", 10) == ""
    assert photo_refusal("image/gif", 10) == PHOTO_WRONG_TYPE
    assert photo_refusal("image/jpeg", 5 * 1024 * 1024 + 1) == PHOTO_TOO_LARGE
    assert photo_refusal("image/webp", 0) == PHOTO_UNREADABLE
    assert refusal_message("empty_menu", PICK_MENU) == MENU_EMPTY
    assert refusal_message("not_photo", PICK_PIECES) == PIECE_NOT_PHOTO
    assert refusal_message("too_large", PICK_PHOTO) == PHOTO_TOO_LARGE
    assert refusal_message("unreadable", PICK_PRODUCTS) == SAVED_PHOTO_UNREADABLE
    assert caption_error("x" * (MAX_CAPTION_CHARS + 1)) == CAPTION_TOO_LONG
    assert pick_total_steps(PICK_MENU) == 2 and pick_total_steps(PICK_PIECES) == 3


def test_errors_never_carry_the_exception_text() -> None:
    plan = PickSend(
        session=1, source=PICK_PHOTO, thread_id=THREAD, connection_id=CONN, request_key="k"
    )
    assert pick_send_error(RuntimeError("bucket secret-name down"), plan) == SEND_PHOTO_FAILED
    assert pick_send_error(WindowClosed(None), plan) == PICK_WINDOW_CLOSED
    assert pick_send_error(AttachmentRefused("too_large"), plan) == PHOTO_TOO_LARGE


# --- the drawer -------------------------------------------------------------------------


def test_the_button_only_opens_while_the_chat_may_get_a_free_message() -> None:
    state = WhatsAppChatsState()
    state.rows = [_row(window_open=False, tone="neutral")]
    state.open_thread_id = THREAD
    state.open_picker()
    assert state.pick_open is False  # outside the 24 h `_expired_composer` stays


async def test_products_happy_path_prefills_and_sends_once(gw: FakeGateway) -> None:
    state = _state()
    assert state.pick_title == "¿Qué le quieres mandar a María?"
    events = state.choose_pick_source(PICK_PRODUCTS)
    assert state.pick_step == 2 and state.pick_total == 3
    assert WhatsAppChatsState.load_pick_products in events
    await state._load_pick(PICK_PRODUCTS)
    assert [c.name for c in state.pick_products] == ["Shawarma mixto", "Limonada"]

    state.choose_product(SHAWARMA)
    assert state.pick_step == 3 and state.pick_reviewing
    assert state.pick_caption == "Shawarma mixto — $5. ¿Te lo preparo?"
    assert state.pick_caption_count == "36/1024"
    assert state.pick_can_send

    events = await _drain(state)
    assert [kind for kind, _ in gw.calls] == ["product"]
    sent = gw.calls[0][1]
    assert sent["product_id"] == UUID(SHAWARMA)
    assert sent["caption"] == "Shawarma mixto — $5. ¿Te lo preparo?"
    assert sent["key"]
    assert state.pick_open is False  # closed; the bubble shows on the refresh
    assert WhatsAppChatsState.refresh in events
    assert state.open_thread.automation_paused is True


async def test_other_trades_ask_if_it_interests(gw: FakeGateway) -> None:
    gw.sector, gw.rubro = "travel_lifestyle", "Agencia de viajes"
    state = _state()
    state.choose_pick_source(PICK_PRODUCTS)
    await state._load_pick(PICK_PRODUCTS)
    state.choose_product(SHAWARMA)
    assert state.pick_caption.endswith("¿Te interesa?")


async def test_a_product_without_photo_goes_as_text(gw: FakeGateway) -> None:
    state = _state()
    state.choose_pick_source(PICK_PRODUCTS)
    await state._load_pick(PICK_PRODUCTS)
    state.choose_product(LIMONADA)
    assert state.pick_as_text is True
    assert state.pick_preview_text == "Limonada — $1. ¿Te lo preparo?"
    await _drain(state)
    assert gw.calls[0][0] == "product"  # the backend sends it as text


async def test_unapproved_piece_warns_sends_and_touches_nothing_else(gw: FakeGateway) -> None:
    state = _state()
    state.choose_pick_source(PICK_PIECES)
    await state._load_pick(PICK_PIECES)
    assert [c.id for c in state.pick_visible_pieces] == [PIECE_OK]  # «Aprobadas» first
    state.set_piece_tab(PIECES_UNAPPROVED)
    card = state.pick_visible_pieces[0]
    assert (card.status_label, card.status_tone, card.photos_label) == (
        "Sin aprobar",
        "warn",
        "1 de 4 fotos",
    )
    state.choose_piece(PIECE_NEW)
    assert state.pick_selected_piece.unapproved is True  # the warning above «Enviar»
    assert state.pick_caption == "Nuevo combo."
    await _drain(state)
    assert gw.calls == [
        (
            "piece",
            {"draft_id": UUID(PIECE_NEW), "caption": "Nuevo combo.", "key": gw.calls[0][1]["key"]},
        )
    ]
    assert not hasattr(gw, "approve")  # nothing approves it for the networks


async def test_the_menu_is_two_steps_and_says_how_many(gw: FakeGateway) -> None:
    state = _state()
    state.choose_pick_source(PICK_MENU)
    assert state.pick_total == 2 and state.pick_reviewing
    assert state.pick_can_send is False  # not read yet
    await state._load_pick(PICK_MENU)
    assert state.pick_menu.count_label == "12 productos de Tus productos"
    assert "los primeros 9" in state.pick_menu.overflow_note
    assert state.pick_send_label == "Enviar el menú"
    await _drain(state)
    assert [kind for kind, _ in gw.calls] == ["menu"]


async def test_an_empty_menu_cannot_be_sent(gw: FakeGateway) -> None:
    gw.menu = dataclasses.replace(gw.menu, product_count=0, rows_shown=0, overflows=False)
    state = _state()
    state.choose_pick_source(PICK_MENU)
    await state._load_pick(PICK_MENU)
    assert state.pick_menu.empty and state.pick_can_send is False


async def test_window_closed_while_choosing_offers_the_approved_message(
    gw: FakeGateway,
) -> None:
    gw.fail_with = [WindowClosed(None)]
    state = _state()
    state.choose_pick_source(PICK_MENU)
    await state._load_pick(PICK_MENU)
    await _drain(state)
    assert state.pick_send_error == PICK_WINDOW_CLOSED
    assert state.pick_window_closed and state.pick_can_send is False
    assert state.open_thread.window_open is False
    events = state.pick_to_templates()
    assert state.pick_open is False
    assert WhatsAppChatsState.open_templates in events


async def test_double_tap_queues_once_and_a_retry_reuses_the_key(gw: FakeGateway) -> None:
    state = _state()
    state.choose_pick_source(PICK_PRODUCTS)
    await state._load_pick(PICK_PRODUCTS)
    state.choose_product(SHAWARMA)
    first = state._begin_pick_send()
    assert first is not None
    assert state._begin_pick_send() is None  # the second tap while the first is in flight
    state.pick_sending = False

    gw.fail_with = [RuntimeError("db down")]
    await _drain(state)
    assert state.pick_send_error == SEND_PHOTO_FAILED
    assert state.pick_caption == "Shawarma mixto — $5. ¿Te lo preparo?"  # kept
    await _drain(state)  # «Reintentar»
    keys = [kwargs["key"] for _kind, kwargs in gw.calls]
    assert len(keys) == 2 and keys[0] == keys[1] == first.request_key

    state.open_picker()
    state.choose_pick_source(PICK_PRODUCTS)
    await state._load_pick(PICK_PRODUCTS)
    state.choose_product(SHAWARMA)
    assert state._pick_request_key != first.request_key  # a new intent, a new key


async def test_a_late_result_after_switching_chat_is_dropped(gw: FakeGateway) -> None:
    state = _state()
    state.choose_pick_source(PICK_MENU)
    await state._load_pick(PICK_MENU)
    plan = state._begin_pick_send()
    assert plan is not None
    state.open_thread_id = OTHER_THREAD
    state._reset_conversation()
    assert state._finish_pick_send(plan, "") is False
    assert state.pick_open is False and state.pick_send_error == ""

    state.open_picker()
    state.choose_pick_source(PICK_PRODUCTS)
    session = state._pick_session
    state.close_picker()
    await state._load_pick(PICK_PRODUCTS)  # closed: nothing is read or painted
    assert state.pick_products == [] and state._pick_session != session


async def test_phone_photo_refusals_then_preview_and_send(gw: FakeGateway) -> None:
    state = _state()
    state.choose_pick_source(PICK_PHOTO)
    await state.handle_pick_photo([_Upload(b"GIF89a", "image/gif", "a.gif")])
    assert state.pick_photo_error == PHOTO_WRONG_TYPE and state.pick_step == 2
    await state.handle_pick_photo([_Upload(b"x" * (5 * 1024 * 1024 + 1), "image/jpeg")])
    assert state.pick_photo_error == PHOTO_TOO_LARGE
    await state.handle_pick_photo([_Upload(b"not an image", "image/png")])
    assert state.pick_photo_error == PHOTO_UNREADABLE

    data = _png()
    await state.handle_pick_photo([_Upload(data, "image/png", "dir/menu del dia.png")])
    assert state.pick_step == 3 and state.pick_photo_error == ""
    assert state.pick_photo_preview.startswith("data:image/jpeg;base64,")
    assert "pick_photo_preview" in WhatsAppChatsState.vars
    assert "_pick_photo" not in WhatsAppChatsState.vars  # the bytes never leave
    state.set_pick_caption("Así quedó")
    await _drain(state)
    kind, sent = gw.calls[0]
    assert kind == "photo" and sent["content"] == data and sent["content_type"] == "image/png"
    assert sent["filename"] == "menu del dia.png" and sent["caption"] == "Así quedó"


async def test_photo_refused_by_the_backend_is_worded(gw: FakeGateway) -> None:
    gw.fail_with = [AttachmentRefused("too_large")]
    state = _state()
    state.choose_pick_source(PICK_PHOTO)
    await state.handle_pick_photo([_Upload(_png(), "image/png")])
    await _drain(state)
    assert state.pick_send_error == PHOTO_TOO_LARGE and state.pick_open


async def test_a_caption_over_the_limit_switches_send_off(gw: FakeGateway) -> None:
    state = _state()
    state.choose_pick_source(PICK_PIECES)
    await state._load_pick(PICK_PIECES)
    state.choose_piece(PIECE_OK)
    state.set_pick_caption("x" * (MAX_CAPTION_CHARS + 5))
    assert state.pick_caption_error == CAPTION_TOO_LONG
    assert state.pick_can_send is False
    assert await _drain(state) == [] and gw.calls == []


def test_back_keeps_the_choice_and_step_one_closes() -> None:
    state = WhatsAppChatsState()
    state.rows = [_row()]
    state.open_thread_id = THREAD
    state.open_picker()
    state.choose_pick_source(PICK_PIECES)
    state.pick_pieces = []  # nothing loaded: a forged id is refused
    assert state.choose_piece(PIECE_OK) is None and state.pick_step == 2
    state.pick_back()
    assert state.pick_step == 1 and state.pick_open
    state.pick_back()
    assert state.pick_open is False


def test_the_tab_renders_the_picker_and_no_link_field() -> None:
    from .whatsapp_tab_chats import chats_tab

    rendered = str(chats_tab().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in (
        "Foto o menú",
        "Tus productos",
        "Tus piezas",
        "Tu menú",
        "Una foto de tu celular",
        "Texto que acompaña la foto",
        "Este producto no tiene foto: le llegará solo el texto.",
        "Todavía no aprobaste esta pieza.",
        "Elegir una foto",
        "Volver al chat",
    ):
        assert present(text), text
    # The dropzone's `on_drop` (`handle_pick_photo`) is wired by its upload id.
    for handler in ("open_picker", "send_pick", "choose_product", "wa_chat_photo"):
        assert handler in rendered, handler
    assert not present("Imagen por enlace")
    assert not present("enlace público de la imagen")
