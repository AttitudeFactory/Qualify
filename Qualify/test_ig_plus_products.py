"""m-25143229 (slice b): «Tus productos» and «Tu oferta» in Instagram's «+», offline.

The gateway over the backend's in-memory conversation service (`World`), WhatsApp's
own in-memory catalog/piece reads (`MemoryAttachmentReads`) and a marked offer; the
panel's state over that gateway (`test_ig_plus_state.Harness`). What these hold:

- only media Instagram can fetch goes as media — under `t/<tenant>/` and JPEG/PNG (MP4
  for a video offer); anything else (an old local key, WebP) is text alone;
- the photo / picture as one reply and the text as the next, with THIS user's approval;
  a text that fails after the medium was queued never queues the medium twice;
- another business's product, an offer that is not the marked one, a closed window or
  another account's thread refuse BEFORE anything is written;
- the panel: WhatsApp's pre-written product text, one send per tap, the guards.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.conversations.service import ThreadNotFound, WindowClosed
from qualify_api.whatsapp.attachments import (
    MemoryAttachmentReads,
    PieceNotFound,
    PieceRow,
    ProductNotFound,
    ProductRow,
    product_text,
)
from qualify_api.whatsapp.promotions import WeeklyPromotion

from .conversations_pick_state import InstagramPickState
from .conversations_provider import TextNotQueued
from .ig_plus_provider import sendable_media
from .test_conversations_provider import CONNECTION, NOW, OTHER_CONNECTION, TENANT, USER
from .test_ig_plus import BRAND, FakePlus
from .test_ig_plus_state import Harness, _send
from .whatsapp_chats_vm import PICK_OFFER, PICK_PRODUCTS

PREFIX = f"t/{TENANT}/"
PHOTO = f"{PREFIX}uploads/catalog/p1/a.jpg"


def _product(name: str = "Shawarma mixto", *, photo: str | None = PHOTO, **kw: Any) -> ProductRow:
    return ProductRow(
        id=uuid4(),
        brand_id=kw.pop("brand_id", BRAND),
        name=name,
        description="Con papas y salsa de ajo",
        price_amount=Decimal("25000"),
        price_currency="COP",
        category="",
        position=0,
        photo_key=photo,
    )


def _piece(key: str = f"{PREFIX}generated/d1/1.png", media_type: str = "image") -> PieceRow:
    return PieceRow(
        id=uuid4(),
        brand_id=BRAND,
        status="approved",
        title="2x1 los martes",
        text="Martes de 2x1 en shawarmas",
        image_key=key,
        image_count=1,
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
        media_type=media_type,
    )


class Catalog:
    def __init__(self) -> None:
        self.reads = MemoryAttachmentReads()
        self.offer: WeeklyPromotion | None = None
        self.sizes: dict[str, int] = {}

    def size(self, tenant_id: UUID, key: str) -> int | None:
        return self.sizes.get(key) if tenant_id == TENANT else None

    def add(self, row: ProductRow | PieceRow, tenant: UUID = TENANT) -> Any:
        table = self.reads.product_rows if isinstance(row, ProductRow) else self.reads.piece_rows
        table[row.id] = (tenant, row)
        return row

    def mark(self, piece: PieceRow) -> None:
        self.offer = WeeklyPromotion(
            brand_id=BRAND, draft_id=piece.id, marked_at=NOW - timedelta(days=1)
        )

    def promotion(self, tenant_id: UUID, brand_id: UUID) -> WeeklyPromotion | None:
        if tenant_id != TENANT or self.offer is None or self.offer.brand_id != brand_id:
            return None
        return self.offer


def _wire(gateway: Any) -> Catalog:
    catalog = Catalog()
    gateway._catalog_reads = catalog.reads
    gateway._promotions = catalog.promotion
    gateway._sizes = catalog.size  # a HEAD in production; never a bucket here
    return catalog


@pytest.fixture
def world():  # noqa: ANN201
    from .test_conversations_provider import World

    w = World()
    w.gateway._plus = FakePlus([], None)
    w.catalog = _wire(w.gateway)
    return w


def _rows(world: Any) -> list[Any]:
    return list(world.outbox.rows.values())


# --- what Instagram can fetch -------------------------------------------------------------


def test_only_the_tenants_own_jpeg_png_or_mp4_go_as_media() -> None:
    assert sendable_media(TENANT, f"{PREFIX}a/b.JPG") == "image/jpeg"
    assert sendable_media(TENANT, f"{PREFIX}a/b.png") == "image/png"
    assert sendable_media(TENANT, f"{PREFIX}a/b.mp4", "video") == "video/mp4"
    assert sendable_media(TENANT, f"{PREFIX}a/b.webp") == ""  # no conversion here
    assert sendable_media(TENANT, f"{PREFIX}a/b.mp4") == ""  # a video is not an image
    assert sendable_media(TENANT, "uploads/old/local.jpg") == ""  # local upload store
    assert sendable_media(TENANT, f"t/{uuid4()}/a.jpg") == ""  # another tenant's
    assert sendable_media(TENANT, None) == ""


# --- Tus productos -------------------------------------------------------------------------


def test_the_grid_is_the_accounts_business_with_unusable_photos_as_sin_foto(world) -> None:  # noqa: ANN001
    good = world.catalog.add(_product("Shawarma"))
    webp = world.catalog.add(_product("Falafel", photo=f"{PREFIX}uploads/catalog/x.webp"))
    world.catalog.add(_product("Ensalada", photo=None))
    world.catalog.add(_product("Ajeno", brand_id=uuid4()))  # another business
    picks = world.gateway.list_products_for_chat(TENANT, CONNECTION)
    assert [(p.name, p.has_photo) for p in picks] == [
        ("Shawarma", True),
        ("Falafel", False),
        ("Ensalada", False),
    ]
    assert picks[0].thumb_url == "/r2media/image/a.jpg" and picks[1].thumb_url == ""
    assert picks[1].thumb_key == "" and good.id and webp.id
    assert world.gateway.list_products_for_chat(TENANT, OTHER_CONNECTION) == []


def test_a_product_goes_as_its_photo_then_the_owners_text(world) -> None:  # noqa: ANN001
    product = world.catalog.add(_product())
    thread = world.inbound()
    image_id, text_id = world.gateway.send_product(
        TENANT, CONNECTION, thread, USER, product.id, "Shawarma mixto — $ 25.000. ¿Te lo preparo?"
    )
    image, text = world.outbox.rows[image_id], world.outbox.rows[text_id]
    assert (image.media.object_key, image.media.media_type, image.media.content_type) == (
        PHOTO,
        "image",
        "image/jpeg",
    )
    assert text.payload["message"]["text"] == "Shawarma mixto — $ 25.000. ¿Te lo preparo?"
    assert {image.approved_by_user_id, text.approved_by_user_id} == {USER}
    assert world.sender.sent == []


@pytest.mark.parametrize("photo", [None, f"{PREFIX}uploads/catalog/x.webp", "uploads/a.jpg"])
def test_a_product_without_a_usable_photo_is_whatsapps_text_alone(world, photo) -> None:  # noqa: ANN001
    product = world.catalog.add(_product(photo=photo))
    thread = world.inbound()
    (only,) = world.gateway.send_product(TENANT, CONNECTION, thread, USER, product.id, "")
    row = world.outbox.rows[only]
    assert row.media is None
    assert row.payload["message"]["text"] == product_text(
        "Shawarma mixto", "$25.000", "Con papas y salsa de ajo", ""
    )


def test_product_refusals_write_nothing(world) -> None:  # noqa: ANN001
    mine = world.catalog.add(_product())
    other = world.catalog.add(_product("Ajeno", brand_id=uuid4()))
    elsewhere = world.catalog.add(_product("De otro"), tenant=uuid4())
    thread = world.inbound()
    for product_id in (other.id, elsewhere.id, uuid4()):
        with pytest.raises(ProductNotFound):
            world.gateway.send_product(TENANT, CONNECTION, thread, USER, product_id, "hola")
    late = world.inbound(at=NOW - timedelta(hours=25), counterpart="igsid-late")
    with pytest.raises(WindowClosed):
        world.gateway.send_product(TENANT, CONNECTION, late, USER, mine.id, "hola")
    foreign = world.inbound(connection_id=OTHER_CONNECTION, counterpart="igsid-x")
    with pytest.raises(ThreadNotFound):
        world.gateway.send_product(TENANT, CONNECTION, foreign, USER, mine.id, "hola")
    assert world.outbox.rows == {}


def test_a_failed_text_after_the_photo_never_queues_the_photo_twice(world, monkeypatch) -> None:  # noqa: ANN001
    product = world.catalog.add(_product())
    thread = world.inbound()
    real = world.service.reply_text

    def broken(**_kw: Any) -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(world.service, "reply_text", broken)
    with pytest.raises(TextNotQueued) as caught:
        world.gateway.send_product(TENANT, CONNECTION, thread, USER, product.id, "hola")
    assert caught.value.qr_key == PHOTO
    monkeypatch.setattr(world.service, "reply_text", real)
    world.gateway.send_product(
        TENANT, CONNECTION, thread, USER, product.id, "hola", skip_media_key=PHOTO
    )
    assert [r.media.object_key if r.media else "text" for r in _rows(world)] == [PHOTO, "text"]


# --- Tu oferta --------------------------------------------------------------------------------


def test_the_offer_is_the_marked_piece_only(world) -> None:  # noqa: ANN001
    marked, other = world.catalog.add(_piece()), world.catalog.add(_piece())
    thread = world.inbound()
    with pytest.raises(PieceNotFound):  # nothing marked
        world.gateway.send_offer(TENANT, CONNECTION, thread, USER, marked.id, "hola")
    assert world.gateway.offer_for_chat(TENANT, CONNECTION).promotion is None
    world.catalog.mark(marked)
    read = world.gateway.offer_for_chat(TENANT, CONNECTION)
    assert read.promotion.draft_id == marked.id and read.sendable
    assert {p.id for p in read.pieces} == {str(marked.id), str(other.id)}
    with pytest.raises(PieceNotFound):  # another piece than the marked one
        world.gateway.send_offer(TENANT, CONNECTION, thread, USER, other.id, "hola")
    assert world.outbox.rows == {}
    image_id, text_id = world.gateway.send_offer(
        TENANT, CONNECTION, thread, USER, marked.id, "Martes de 2x1"
    )
    assert world.outbox.rows[image_id].media.content_type == "image/png"
    assert world.outbox.rows[text_id].payload["message"]["text"] == "Martes de 2x1"


def test_a_video_offer_is_a_video_reply_and_a_webp_one_text_alone(world) -> None:  # noqa: ANN001
    video = world.catalog.add(_piece(f"{PREFIX}generated/d2/v.mp4", "video"))
    world.catalog.sizes[video.image_key] = 5 * 1024 * 1024
    world.catalog.mark(video)
    thread = world.inbound()
    first, _text = world.gateway.send_offer(TENANT, CONNECTION, thread, USER, video.id, "Mira")
    media = world.outbox.rows[first].media
    assert (media.media_type, media.content_type) == ("video", "video/mp4")
    webp = world.catalog.add(_piece(f"{PREFIX}generated/d3/1.webp"))
    world.catalog.mark(webp)
    assert world.gateway.offer_for_chat(TENANT, CONNECTION).sendable is False
    (only,) = world.gateway.send_offer(TENANT, CONNECTION, thread, USER, webp.id, "Solo texto")
    assert world.outbox.rows[only].media is None


# --- the panel ----------------------------------------------------------------------------


def _harness(monkeypatch: pytest.MonkeyPatch) -> tuple[Harness, Catalog]:
    h = Harness(monkeypatch)
    return h, _wire(h.world.gateway)


async def test_a_product_review_has_whatsapps_text_and_one_tap_sends_once(monkeypatch) -> None:  # noqa: ANN001
    h, catalog = _harness(monkeypatch)
    product = catalog.add(_product())
    pick = h.pick
    pick.pick_open, pick.pick_source, pick.pick_thread = True, PICK_PRODUCTS, str(h.thread)
    pick._connection = h.conv.selected_connection_id
    await InstagramPickState.load_products.fn(pick)
    assert [c.name for c in pick.pick_products] == ["Shawarma mixto"]
    pick.choose_product(str(product.id))
    assert pick.pick_reviewing and pick.pick_caption.startswith("Shawarma mixto — $25.000")
    assert pick.pick_media_src == "/r2media/image/a.jpg"
    assert pick.pick_preview_text == pick.pick_caption.strip()
    plan = pick._begin_send()
    assert plan is not None and pick._begin_send() is None  # the double tap
    assert pick.choose_product(str(product.id)) is None  # nothing changes in flight
    async for _event in pick._send(plan):
        pass
    assert [r.media.media_type if r.media else "text" for r in h.rows()] == ["image", "text"]
    assert pick.pick_open is False
    await _send(pick)  # a late second tap: nothing left to send
    assert len(h.rows()) == 2


async def test_the_offer_loads_as_its_one_review_step(monkeypatch) -> None:  # noqa: ANN001
    h, catalog = _harness(monkeypatch)
    piece = catalog.add(_piece())
    catalog.mark(piece)
    pick = h.pick
    pick.pick_open, pick.pick_source, pick.pick_thread = True, PICK_OFFER, str(h.thread)
    pick._connection = h.conv.selected_connection_id
    await InstagramPickState.load_offer.fn(pick)
    assert pick.pick_offer.marked and pick.pick_reviewing
    assert pick.pick_selected == str(piece.id) and pick.pick_caption != ""
    assert not pick.pick_as_text and pick.pick_can_send
    await _send(pick)
    assert [r.media.media_type if r.media else "text" for r in h.rows()] == ["image", "text"]


async def test_without_a_marked_offer_the_step_leads_to_por_aprobar(monkeypatch) -> None:  # noqa: ANN001
    h, _catalog = _harness(monkeypatch)
    pick = h.pick
    pick.pick_open, pick.pick_source, pick.pick_thread = True, PICK_OFFER, str(h.thread)
    pick._connection = h.conv.selected_connection_id
    await InstagramPickState.load_offer.fn(pick)
    assert pick.pick_offer.present and not pick.pick_offer.marked
    assert not pick.pick_can_send


async def test_directions_is_offered_only_with_a_whatsapp_number(monkeypatch) -> None:  # noqa: ANN001
    """UX U1: the address lives on the business's WhatsApp number; without one the «+»
    does not offer «Cómo llegar» (read once per account)."""
    from .ig_plus_provider import PlusScope

    h, _catalog = _harness(monkeypatch)
    pick = h.pick
    await InstagramPickState.load_scope.fn(pick)
    assert pick.pick_has_number is True
    pick._scope_for = ""
    monkeypatch.setattr(h.world.plus, "scope", lambda t, c: PlusScope(brand_id=BRAND))
    await InstagramPickState.load_scope.fn(pick)
    assert pick.pick_has_number is False


# --- review fixes (C1–C6, U3) ---------------------------------------------------------------


def test_a_video_offer_over_instagrams_25_mb_queues_nothing(world) -> None:  # noqa: ANN001
    from .conversations_provider import MediaTooLarge

    key = f"{PREFIX}generated/d9/v.mp4"
    video = world.catalog.add(_piece(key, "video"))
    world.catalog.mark(video)
    world.catalog.sizes[key] = 25 * 1024 * 1024 + 1
    read = world.gateway.offer_for_chat(TENANT, CONNECTION)
    assert read.too_large and not read.sendable
    assert [p.too_large for p in read.pieces] == [True]
    thread = world.inbound()
    with pytest.raises(MediaTooLarge):
        world.gateway.send_offer(TENANT, CONNECTION, thread, USER, video.id, "Mira")
    assert world.outbox.rows == {}
    world.catalog.sizes[key] = 17 * 1024 * 1024  # over WhatsApp's 16 MB, within 25 MB
    assert world.gateway.offer_for_chat(TENANT, CONNECTION).sendable
    assert len(world.gateway.send_offer(TENANT, CONNECTION, thread, USER, video.id, "Mira")) == 2


def test_the_text_is_one_instagram_message_never_split(world) -> None:  # noqa: ANN001
    from .conversations_provider import TextTooLong
    from .ig_plus_provider import IG_MAX_TEXT

    product = world.catalog.add(_product())
    thread = world.inbound()
    with pytest.raises(TextTooLong):  # refused before the photo is queued
        world.gateway.send_product(TENANT, CONNECTION, thread, USER, product.id, "a" * 1001)
    assert world.outbox.rows == {}
    long_one = world.catalog.add(_product("Combo", photo=None))
    world.catalog.reads.product_rows[long_one.id] = (
        TENANT,
        ProductRow(**{**long_one.__dict__, "description": "Muy rico. " * 300}),
    )
    (only,) = world.gateway.send_product(TENANT, CONNECTION, thread, USER, long_one.id, "")
    assert len(world.outbox.rows[only].payload["message"]["text"]) <= IG_MAX_TEXT


def test_nothing_to_send_is_never_reported_as_sent(world) -> None:  # noqa: ANN001
    from .conversations_provider import NothingToSend

    webp = world.catalog.add(_piece(f"{PREFIX}generated/d3/1.webp"))
    world.catalog.mark(webp)
    thread = world.inbound()
    with pytest.raises(NothingToSend):
        world.gateway.send_offer(TENANT, CONNECTION, thread, USER, webp.id, "   ")
    assert world.outbox.rows == {}


async def test_the_offers_too_large_video_turns_send_off(monkeypatch) -> None:  # noqa: ANN001
    h, catalog = _harness(monkeypatch)
    key = f"{PREFIX}generated/d9/v.mp4"
    piece = catalog.add(_piece(key, "video"))
    catalog.mark(piece)
    catalog.sizes[key] = 30 * 1024 * 1024
    pick = h.pick
    pick.pick_open, pick.pick_source, pick.pick_thread = True, PICK_OFFER, str(h.thread)
    pick._connection = h.conv.selected_connection_id
    await InstagramPickState.load_offer.fn(pick)
    assert pick.pick_offer_too_large and not pick.pick_as_text
    assert not pick.pick_can_send


async def test_the_panel_counts_to_1000_and_trims_the_prewritten_text(monkeypatch) -> None:  # noqa: ANN001
    h, catalog = _harness(monkeypatch)
    product = catalog.add(_product())
    catalog.reads.product_rows[product.id] = (
        TENANT,
        ProductRow(**{**product.__dict__, "description": "Muy rico. " * 120}),
    )
    pick = h.pick
    pick.pick_open, pick.pick_source, pick.pick_thread = True, PICK_PRODUCTS, str(h.thread)
    pick._connection = h.conv.selected_connection_id
    await InstagramPickState.load_products.fn(pick)
    pick.choose_product(str(product.id))
    assert len(pick.pick_caption) <= 1000 and pick.pick_caption_count.endswith("/1000")
    assert pick.pick_caption_error == ""
    pick.set_pick_caption("a" * 1001)
    assert pick.pick_caption_error == "El texto admite hasta 1000 caracteres."
    assert not pick.pick_can_send


async def test_a_retry_after_a_half_send_skips_the_photo_and_the_offers_picture(
    monkeypatch,  # noqa: ANN001
) -> None:
    h, catalog = _harness(monkeypatch)
    product = catalog.add(_product())
    piece = catalog.add(_piece())
    catalog.mark(piece)
    real = h.world.service.reply_text
    fail = {"next": True}

    def flaky(**kw: Any) -> Any:
        if fail["next"]:
            fail["next"] = False
            raise RuntimeError("db down")
        return real(**kw)

    monkeypatch.setattr(h.world.service, "reply_text", flaky)
    pick = h.pick
    pick.pick_open, pick.pick_source, pick.pick_thread = True, PICK_PRODUCTS, str(h.thread)
    pick._connection = h.conv.selected_connection_id
    await InstagramPickState.load_products.fn(pick)
    pick.choose_product(str(product.id))
    await _send(pick)
    assert pick.pick_send_error != "" and pick.pick_open
    await _send(pick)  # «Reintentar»
    assert [r.media.media_type if r.media else "text" for r in h.rows()] == ["image", "text"]

    fail["next"] = True
    pick.pick_open, pick.pick_source, pick.pick_thread = True, PICK_OFFER, str(h.thread)
    pick._connection = h.conv.selected_connection_id
    await InstagramPickState.load_offer.fn(pick)
    await _send(pick)
    await _send(pick)
    kinds = [r.media.media_type if r.media else "text" for r in h.rows()]
    assert kinds == ["image", "text", "image", "text"]


async def test_opening_the_plus_reads_the_scope_again(monkeypatch) -> None:  # noqa: ANN001
    from .ig_plus_provider import PlusScope

    h, _catalog = _harness(monkeypatch)
    pick = h.pick
    await InstagramPickState.load_scope.fn(pick)
    assert pick.pick_has_number is True
    # the business lost its number meanwhile: the next «+» must know (C3)
    monkeypatch.setattr(h.world.plus, "scope", lambda t, c: PlusScope(brand_id=BRAND))
    events = await InstagramPickState.open_pick.fn(pick, PICK_PRODUCTS)
    assert InstagramPickState.load_scope in events and pick._scope_for == ""
    await InstagramPickState.load_scope.fn(pick)
    assert pick.pick_has_number is False


async def test_another_account_never_keeps_the_previous_answer(monkeypatch) -> None:  # noqa: ANN001
    from .ig_plus_provider import PlusScope

    h, _catalog = _harness(monkeypatch)
    pick = h.pick
    monkeypatch.setattr(h.world.plus, "scope", lambda t, c: PlusScope(brand_id=BRAND))
    await InstagramPickState.load_scope.fn(pick)
    assert pick.pick_has_number is False

    def broken(t: UUID, c: UUID) -> PlusScope:
        raise RuntimeError("db down")

    monkeypatch.setattr(h.world.plus, "scope", broken)
    h.conv.selected_connection_id = str(OTHER_CONNECTION)
    await InstagramPickState.load_scope.fn(pick)
    assert pick.pick_has_number is True  # C4: reset for the new account, read failed


def test_add_a_product_leads_back_to_the_chat_on_both_channels(monkeypatch) -> None:  # noqa: ANN001
    from urllib.parse import parse_qs, urlsplit

    from .whatsapp_chats_state import WhatsAppChatsState

    h, _catalog = _harness(monkeypatch)
    pick = h.pick
    pick.pick_thread, pick._connection = str(h.thread), h.conv.selected_connection_id
    query = parse_qs(urlsplit(pick.products_add_href).query)
    assert query["nuevo"] == ["1"] and f"chat={h.thread}" in query["volver"][0]
    wa = WhatsAppChatsState()
    wa.open_thread_id, wa._connection_id = str(uuid4()), str(uuid4())
    query = parse_qs(urlsplit(wa.products_add_href).query)
    assert query["volver"][0].startswith("/responder?") and wa.open_thread_id in query["volver"][0]


# --- last fixes -------------------------------------------------------------------------------


def test_long_payment_instructions_never_lose_the_closing_line() -> None:
    import dataclasses

    from qualify_api.whatsapp.menus.engine import PAYMENT_CLOSING

    from .ig_plus_provider import IG_MAX_TEXT, payment_text
    from .test_ig_plus import _method

    method = dataclasses.replace(
        _method(), instructions="Transferencia a la cuenta 123. " * 31
    )  # ~960 characters
    assert len(method.instructions) > 950
    text = payment_text(method)
    assert len(text) <= IG_MAX_TEXT
    assert text.endswith(PAYMENT_CLOSING)  # only the instructions were clipped
    assert text.startswith("Transferencia a la cuenta 123.")


def test_a_video_offer_of_unknown_size_sends_nothing(world) -> None:  # noqa: ANN001
    from .conversations_provider import MediaSizeUnknown

    video = world.catalog.add(_piece(f"{PREFIX}generated/d5/v.mp4", "video"))
    world.catalog.mark(video)  # no size known for it
    read = world.gateway.offer_for_chat(TENANT, CONNECTION)
    assert read.size_unknown and not read.sendable and not read.too_large
    thread = world.inbound()
    with pytest.raises(MediaSizeUnknown):
        world.gateway.send_offer(TENANT, CONNECTION, thread, USER, video.id, "Mira")
    assert world.outbox.rows == {}


async def test_the_panel_says_the_existing_failure_for_an_unknown_size(monkeypatch) -> None:  # noqa: ANN001
    from .conversations_pick_state import ig_send_error
    from .conversations_provider import MediaSizeUnknown
    from .whatsapp_chats_vm import OFFER_FAILED, send_failed_message

    h, catalog = _harness(monkeypatch)
    piece = catalog.add(_piece(f"{PREFIX}generated/d5/v.mp4", "video"))
    catalog.mark(piece)
    pick = h.pick
    pick.pick_open, pick.pick_source, pick.pick_thread = True, PICK_OFFER, str(h.thread)
    pick._connection = h.conv.selected_connection_id
    await InstagramPickState.load_offer.fn(pick)
    assert pick.pick_error == OFFER_FAILED and not pick.pick_can_send
    assert ig_send_error(MediaSizeUnknown("x"), PICK_OFFER) == send_failed_message(PICK_OFFER)


def test_the_offer_listing_reads_sizes_without_warnings(world, caplog) -> None:  # noqa: ANN001
    import logging

    video = world.catalog.add(_piece(f"{PREFIX}generated/d6/v.mp4", "video"))
    world.catalog.sizes[video.image_key] = 1024
    world.catalog.mark(video)
    with caplog.at_level(logging.WARNING):
        read = world.gateway.offer_for_chat(TENANT, CONNECTION)
    assert read.sendable and read.pieces[0].bytes == 1024
    assert "size_failed" not in caplog.text and "size failed" not in caplog.text
