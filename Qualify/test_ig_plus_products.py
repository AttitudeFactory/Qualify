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
