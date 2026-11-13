"""m-24945888 — «Foto o menú» from a WhatsApp chat, offline.

`ChatAttachmentService` over the in-memory chat / outbox repositories, an in-memory blob
store and fake reads; `OutboxSender` with a scripted fake client for the upload at send
time. Nothing reaches Meta, R2 or Postgres. Pinned: the picker rows, each of the four
sends (one `reply` row each, window and takeover from the chat), the R2 copy and its
provenance, size/type refusals that write nothing, captions cut at a sentence end, one
upload per row however many retries, and ADR 39's (c) — a WhatsApp send extends a piece.
"""

from __future__ import annotations

import io
import os
import struct
import zlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image

from qualify_api.creative.retention import RetentionFacts, RetentionState, evaluate
from qualify_api.whatsapp.attachments import (
    ATTACHMENT_PIPELINE,
    MAX_CAPTION_CHARS,
    MAX_IMAGE_BYTES,
    MAX_INPUT_BYTES,
    AttachmentRefused,
    ChatAttachmentService,
    MemoryAttachmentReads,
    MemoryBlobStore,
    MenuRef,
    PieceNotFound,
    PieceRow,
    ProductNotFound,
    ProductRow,
    fit_caption,
    fit_image,
    product_text,
    strip_hashtags,
)
from qualify_api.whatsapp.catalog import to_catalog_items
from qualify_api.whatsapp.chats import (
    ChatService,
    MemoryChatRepository,
    MenuCursor,
    TextSend,
    WindowClosed,
)
from qualify_api.whatsapp.client import WhatsAppApiError
from qualify_api.whatsapp.menus.engine import Inbound, SendList, ThreadMenuState, step
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.optins import MemoryOptInRepository, OptInService
from qualify_api.whatsapp.outbox import MemoryOutboxRepository, OutboxSender

NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
TENANT = UUID("a0000000-0000-4000-8000-000000945888")
OTHER_TENANT = UUID("b0000000-0000-4000-8000-000000945888")
BRAND = UUID("c0000000-0000-4000-8000-000000945888")
OTHER_BRAND = UUID("c1000000-0000-4000-8000-000000945888")
CONN = UUID("d0000000-0000-4000-8000-000000945888")
USER = UUID("e0000000-0000-4000-8000-000000945888")
WA_ID = "573001112233"


def _image(fmt: str = "JPEG", size: tuple[int, int] = (64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(out, format=fmt)
    return out.getvalue()


def _png_header(width: int, height: int) -> bytes:
    """A tiny PNG whose header DECLARES `width × height` — a decompression bomb's shape."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" * 64)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


JPEG = _image("JPEG")
PNG = _image("PNG")
WEBP = _image("WEBP")


class FakeLinker:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        self.calls.append(object_key)
        return f"https://app.qualify.la/public/media/{len(self.calls)}"


class World:
    def __init__(self) -> None:
        self.chat_repo = MemoryChatRepository()
        self.outbox = MemoryOutboxRepository(clock=lambda: NOW)
        self.chats = ChatService(self.chat_repo, self.outbox, clock=lambda: NOW)
        self.reads = MemoryAttachmentReads()
        self.blobs = MemoryBlobStore()
        self.linker = FakeLinker()
        self.service = ChatAttachmentService(self.chats, self.reads, self.blobs, self.linker)
        self.reads.brands[(TENANT, CONN)] = BRAND

    def thread(self, *, inbound_ago: timedelta | None = timedelta(hours=1)) -> UUID:
        thread_id = self.chat_repo.add_thread(tenant_id=TENANT, connection_id=CONN, wa_id=WA_ID)
        if inbound_ago is not None:
            self.chat_repo.add_message(
                thread_id=thread_id,
                direction="inbound",
                text_value="¿tienen shawarma?",
                posted_at=NOW - inbound_ago,
            )
            self.outbox.threads[thread_id] = NOW - inbound_ago
        return thread_id

    def product(
        self,
        name: str,
        *,
        photo: str | None = None,
        price: str | None = "5",
        tenant: UUID = TENANT,
        brand: UUID = BRAND,
        category: str = "",
        position: int = 0,
        description: str = "",
    ) -> UUID:
        row = ProductRow(
            id=uuid4(),
            brand_id=brand,
            name=name,
            description=description,
            price_amount=Decimal(price) if price is not None else None,
            price_currency="USD",
            category=category,
            position=position,
            photo_key=photo,
        )
        self.reads.product_rows[row.id] = (tenant, row)
        return row.id

    def piece(
        self,
        *,
        status: str = "approved",
        text: str = "Martes 2x1. Ven por tu combo.",
        key: str | None = None,
        days_ago: int = 1,
        brand: UUID = BRAND,
        tenant: UUID = TENANT,
    ) -> UUID:
        draft_id = uuid4()
        key = key or f"t/{tenant}/generated/{draft_id}/r1/feed.png"
        self.reads.piece_rows[draft_id] = (
            tenant,
            PieceRow(
                id=draft_id,
                brand_id=brand,
                status=status,
                title="Martes 2x1",
                text=text,
                image_key=key,
                image_count=1,
                created_at=NOW - timedelta(days=days_ago),
            ),
        )
        self.blobs.objects[(tenant, key)] = PNG
        return draft_id

    def only_row(self):
        assert len(self.outbox.rows) == 1
        return next(iter(self.outbox.rows.values()))


@pytest.fixture
def world() -> World:
    return World()


# --- pure helpers ----------------------------------------------------------------------


def test_hashtags_leave_the_caption_and_hashtag_only_lines_go_away() -> None:
    text = "Martes 2x1 #promo en shawarma\n\n#bianki #cucuta\nVen hoy."
    assert strip_hashtags(text) == "Martes 2x1 en shawarma\n\nVen hoy."


def test_a_long_caption_is_cut_at_the_last_sentence_that_fits() -> None:
    sentence = "Nuestro shawarma mixto lleva pollo, carne y salsa de la casa. "
    text = sentence * 30
    fitted, shortened = fit_caption(text)
    assert shortened and len(fitted) <= MAX_CAPTION_CHARS
    assert fitted.endswith("casa.")
    assert fit_caption("Corto.") == ("Corto.", False)


def test_a_product_text_does_not_repeat_the_name_the_caption_already_has() -> None:
    assert (
        product_text("Limonada", "$1", "", "Limonada — $1. ¿Te la preparo?")
        == "Limonada — $1. ¿Te la preparo?"
    )
    assert product_text("Limonada", "$1", "Natural", "") == "Limonada — $1\nNatural"
    assert product_text("Limonada", "", "", "¿Te provoca?") == "Limonada\n¿Te provoca?"


# --- the picker ------------------------------------------------------------------------


def test_products_list_in_menu_order_with_the_ones_without_photo_last(world: World) -> None:
    r2 = f"t/{TENANT}/catalog/x.jpg"
    world.product("Shawarma mixto", photo=f"uploads/{TENANT}/catalog/p/a.jpg", position=1)
    world.product("Limonada", photo=None, position=0)
    world.product("Ensalada César", photo=r2, position=2, price="4.50")
    world.product("De otro negocio", photo=None, brand=OTHER_BRAND)
    world.product("De otro cliente", photo=None, tenant=OTHER_TENANT)

    picks = world.service.list_products_for_chat(TENANT, BRAND)

    assert [p.name for p in picks] == ["Shawarma mixto", "Ensalada César", "Limonada"]
    shawarma, ensalada, limonada = picks
    assert (shawarma.price_label, shawarma.has_photo) == ("$5", True)
    # A local upload-store photo: no token URL, the page resolves the key.
    assert shawarma.thumb_url == "" and shawarma.thumb_key.startswith("uploads/")
    assert ensalada.thumb_url.startswith("https://") and ensalada.price_label == "$4,50"
    assert (limonada.has_photo, limonada.thumb_url) == (False, "")
    assert world.linker.calls == [r2]


def test_pieces_list_approved_and_published_first_then_unapproved(world: World) -> None:
    old_approved = world.piece(status="approved", days_ago=5)
    published = world.piece(status="published", days_ago=3)
    staged = world.piece(status="staged", days_ago=4)
    fresh_unapproved = world.piece(status="generated", days_ago=0, text="Nuevo #combo listo.")
    world.piece(status="rejected")
    world.piece(status="drafting")
    world.piece(status="approved", tenant=OTHER_TENANT)

    picks = world.service.list_pieces_for_chat(TENANT, BRAND)

    assert [UUID(p.id) for p in picks] == [published, staged, old_approved, fresh_unapproved]
    assert [p.status for p in picks] == ["published", "approved", "approved", "unapproved"]
    assert picks[-1].caption_suggestion == "Nuevo listo."
    assert all(p.thumb_url.startswith("https://") for p in picks)


def test_a_long_piece_text_is_suggested_shortened(world: World) -> None:
    world.piece(text="Ven por tu combo hoy mismo. " * 60)
    (pick,) = world.service.list_pieces_for_chat(TENANT, BRAND)
    assert pick.caption_shortened and len(pick.caption_suggestion) <= MAX_CAPTION_CHARS


# --- sends -----------------------------------------------------------------------------


def test_a_product_photo_goes_as_an_uploadable_image_with_its_provenance(world: World) -> None:
    source = f"uploads/{TENANT}/catalog/p/a.jpg"
    world.blobs.objects[(TENANT, source)] = JPEG
    product_id = world.product("Shawarma mixto", photo=source)
    thread_id = world.thread()

    item_id = world.service.send_product(
        TENANT, thread_id, USER, product_id, "Shawarma mixto — $5. ¿Te lo preparo?"
    )

    row = world.only_row()
    assert row.id == item_id and row.kind == "reply" and row.created_by_user_id == USER
    assert row.payload["type"] == "image" and row.payload["to"] == WA_ID
    # No link and no id yet: the sender uploads the R2 copy right before the send.
    assert row.payload["image"] == {"caption": "Shawarma mixto — $5. ¿Te lo preparo?"}
    assert row.preview_text == "Shawarma mixto — $5. ¿Te lo preparo?"
    att = row.attachment
    assert att["kind"] == "product" and att["product_id"] == str(product_id)
    assert att["source_key"] == source and att["pipeline"] == ATTACHMENT_PIPELINE
    assert att["object_key"].startswith(f"t/{TENANT}/whatsapp/outbound/{CONN}/")
    assert att["object_key"].endswith(".jpg") and att["media_id"] is None
    assert (att["content_type"], att["bytes"]) == ("image/jpeg", len(JPEG))
    assert world.blobs.objects[(TENANT, att["object_key"])] == JPEG
    # The owner's send is a takeover, like a typed reply.
    assert world.chat_repo.states[thread_id].automation_paused_at == NOW


def test_a_product_without_photo_goes_as_text(world: World) -> None:
    product_id = world.product("Limonada", photo=None, price="1", description="Natural")
    thread_id = world.thread()

    world.service.send_product(TENANT, thread_id, USER, product_id, "")

    row = world.only_row()
    assert row.payload["type"] == "text"
    assert row.payload["text"]["body"] == "Limonada — $1\nNatural"
    assert row.attachment["fallback"] == "text" and "object_key" not in row.attachment
    assert world.blobs.objects == {}


def test_a_product_of_another_tenant_or_business_is_not_found(world: World) -> None:
    thread_id = world.thread()
    foreign = world.product("Ajeno", tenant=OTHER_TENANT)
    other_brand = world.product("Polette", brand=OTHER_BRAND)
    for product_id in (foreign, other_brand, uuid4()):
        with pytest.raises(ProductNotFound):
            world.service.send_product(TENANT, thread_id, USER, product_id, "")
    assert world.outbox.rows == {}


def test_an_unapproved_piece_is_sent_and_recorded_as_such(world: World) -> None:
    draft_id = world.piece(status="generated")
    thread_id = world.thread()

    world.service.send_piece(TENANT, thread_id, USER, draft_id, "Martes 2x1. Ven por tu combo.")

    row = world.only_row()
    assert row.payload["type"] == "image"
    att = row.attachment
    assert (att["kind"], att["draft_id"], att["status_at_send"]) == (
        "piece",
        str(draft_id),
        "generated",
    )
    assert att["content_type"] == "image/png" and att["object_key"].endswith(".png")


def test_a_rejected_or_foreign_piece_is_not_sent(world: World) -> None:
    thread_id = world.thread()
    for draft_id in (
        world.piece(status="rejected"),
        world.piece(tenant=OTHER_TENANT),
        world.piece(brand=OTHER_BRAND),
    ):
        with pytest.raises(PieceNotFound):
            world.service.send_piece(TENANT, thread_id, USER, draft_id, "")
    assert world.outbox.rows == {}


def test_a_caption_over_the_limit_is_cut_at_a_sentence(world: World) -> None:
    draft_id = world.piece()
    thread_id = world.thread()
    world.service.send_piece(TENANT, thread_id, USER, draft_id, "Ven hoy mismo. " * 100)
    caption = world.only_row().payload["image"]["caption"]
    assert len(caption) <= MAX_CAPTION_CHARS and caption.endswith("mismo.")


MENU_VERSION = UUID("f0000000-0000-4000-8000-000000945888")


def _publish_menu(world: World) -> None:
    world.reads.menus[(TENANT, CONN)] = MenuRef(
        node_id="productos",
        node=BIANKI_DEMO_MENU.nodes["productos"],  # type: ignore[arg-type]
        menu_version_id=MENU_VERSION,
    )


def _engine_state(world: World, thread_id: UUID) -> ThreadMenuState:
    stored = world.chat_repo.states[thread_id]
    return ThreadMenuState(
        node_id=stored.node_id,
        context=dict(stored.context),
        paused=stored.automation_paused_at is not None,
        attempts=stored.attempts,
    )


def test_the_menu_goes_as_the_engines_product_list(world: World) -> None:
    _publish_menu(world)
    world.product("Shawarma mixto", category="Shawarmas")
    world.product("Limonada", price="1", category="Bebidas")
    thread_id = world.thread()

    world.service.send_menu_list(TENANT, thread_id, USER)

    row = world.only_row()
    interactive = row.payload["interactive"]
    assert row.payload["type"] == "interactive" and interactive["type"] == "list"
    assert interactive["body"]["text"] == BIANKI_DEMO_MENU.nodes["productos"].body
    titles = [r["title"] for s in interactive["action"]["sections"] for r in s["rows"]]
    assert sorted(titles) == ["Limonada", "Shawarma mixto"]
    att = row.attachment
    assert (att["kind"], att["menu_version_id"], att["node_id"]) == (
        "menu",
        str(MENU_VERSION),
        "productos",
    )
    assert len(att["product_ids"]) == 2


def test_sending_the_menu_resumes_the_automation_at_the_products_step(world: World) -> None:
    """Founder decision 2026-11-04: «Tu menú» is an invitation to order through the menu."""
    _publish_menu(world)
    world.product("Shawarma mixto")
    thread_id = world.thread()
    # The owner had taken the chat over earlier (a typed reply).
    world.chat_repo.pause_automation(tenant_id=TENANT, thread_id=thread_id, user_id=USER, at=NOW)
    world.chat_repo.states[thread_id].context["order"] = [{"product_id": "x", "qty": 1}]

    world.service.send_menu_list(TENANT, thread_id, USER)

    state = world.chat_repo.states[thread_id]
    assert state.automation_paused_at is None and state.paused_by_user_id is None
    assert (state.node_id, state.menu_version_id, state.attempts) == (
        "productos",
        MENU_VERSION,
        0,
    )
    assert state.context["products_page"] == 0
    assert state.context["order"] == [{"product_id": "x", "qty": 1}]  # kept


def test_a_pick_from_the_chat_sent_list_continues_the_order(world: World) -> None:
    _publish_menu(world)
    for i in range(12):
        world.product(f"Producto {i:02d}", position=i)
    thread_id = world.thread()
    world.service.send_menu_list(TENANT, thread_id, USER)
    rows = [
        r for s in world.only_row().payload["interactive"]["action"]["sections"] for r in s["rows"]
    ]
    catalog = to_catalog_items(world.reads.products(TENANT, BRAND))

    # «Ver más» pages on its own…
    more = next(r["id"] for r in rows if r["id"].startswith("more:"))
    paged = step(
        BIANKI_DEMO_MENU, _engine_state(world, thread_id), Inbound.list_reply(more), catalog=catalog
    )
    assert any(isinstance(a, SendList) for a in paged.actions)
    assert paged.state.node_id == "productos" and paged.state.context["products_page"] == 1

    # …and a pick goes into the order, on to the menu's next step.
    pick = next(r for r in rows if r["id"].startswith("prod:"))
    picked = step(
        BIANKI_DEMO_MENU,
        _engine_state(world, thread_id),
        Inbound.list_reply(pick["id"]),
        catalog=catalog,
    )
    assert [line["name"] for line in picked.state.context["order"]] == [pick["title"]]
    assert picked.state.node_id != "productos" and picked.actions


def test_a_chat_sent_menu_in_categories_mode_waits_for_a_category_pick(world: World) -> None:
    """m-24955838: 12 products in two categories open on the categories list, and the
    thread is left on that list even if it was inside a category before."""
    _publish_menu(world)
    for i in range(6):
        world.product(f"Shawarma {i}", category="Shawarmas", position=i)
        world.product(f"Bebida {i}", category="Bebidas", position=i)
    thread_id = world.thread()
    world.chat_repo.pause_automation(tenant_id=TENANT, thread_id=thread_id, user_id=USER, at=NOW)
    stored = world.chat_repo.states[thread_id].context
    stored.update(
        {
            "order": [{"product_id": "x", "qty": 1}],
            "products_category": "bebidas",
            "products_page": 1,
        }
    )

    world.service.send_menu_list(TENANT, thread_id, USER)

    row = world.only_row()
    rows = [r for s in row.payload["interactive"]["action"]["sections"] for r in s["rows"]]
    assert [r["id"] for r in rows] == ["cat:bebidas", "cat:shawarmas"]
    assert row.payload["interactive"]["body"]["text"] == "¿Qué quieres ver?"
    assert row.attachment["product_ids"] == []
    state = _engine_state(world, thread_id)
    assert state.node_id == "productos" and state.context["products_category"] is None
    assert state.context["order"] == [{"product_id": "x", "qty": 1}]  # kept

    catalog = to_catalog_items(
        world.reads.products(TENANT, BRAND), world.reads.category_order(TENANT, BRAND)
    )
    opened = step(BIANKI_DEMO_MENU, state, Inbound.list_reply("cat:shawarmas"), catalog=catalog)
    shown = opened.actions[0]
    assert isinstance(shown, SendList) and shown.sections[0].title == "Shawarmas"
    assert opened.state.context["products_category"] == "shawarmas"

    preview = world.service.menu_preview(TENANT, CONN)
    assert (preview.product_count, preview.overflows, preview.rows_shown) == (12, False, 0)
    assert preview.body == "¿Qué quieres ver?"


@pytest.mark.parametrize("menu", ["none", "no_products_step"])
def test_without_a_live_menu_the_list_is_refused_and_nothing_changes(
    world: World, menu: str
) -> None:
    # `PostgresAttachmentReads.menu_node` answers None for no published menu, a paused
    # menu, and a menu without a products step — the service sees the same None.
    world.product("Shawarma mixto")
    thread_id = world.thread()
    world.chat_repo.pause_automation(tenant_id=TENANT, thread_id=thread_id, user_id=USER, at=NOW)
    with pytest.raises(AttachmentRefused) as refused:
        world.service.send_menu_list(TENANT, thread_id, USER)
    assert refused.value.reason == "no_menu"
    assert "Respuesta automática" in refused.value.message
    with pytest.raises(AttachmentRefused):
        world.service.menu_preview(TENANT, CONN)
    assert world.outbox.rows == {}
    assert world.chat_repo.states[thread_id].automation_paused_at == NOW  # still paused


def test_the_menu_preview_says_when_it_overflows(world: World) -> None:
    _publish_menu(world)
    for i in range(12):
        world.product(f"Producto {i:02d}", position=i)
    preview = world.service.menu_preview(TENANT, CONN)
    page_size = BIANKI_DEMO_MENU.nodes["productos"].page_size  # type: ignore[union-attr]
    assert (preview.product_count, preview.overflows) == (12, True)
    assert preview.rows_shown == page_size - 1 and preview.menu_version_id == str(MENU_VERSION)


def test_an_empty_menu_is_refused_before_anything_is_queued(world: World) -> None:
    _publish_menu(world)
    thread_id = world.thread()
    with pytest.raises(AttachmentRefused) as refused:
        world.service.send_menu_list(TENANT, thread_id, USER)
    assert refused.value.reason == "empty_menu"
    assert world.outbox.rows == {} and thread_id not in world.chat_repo.states


@pytest.mark.parametrize("kind", ["product", "piece", "photo", "text"])
def test_every_other_send_still_pauses_the_automation(world: World, kind: str) -> None:
    thread_id = world.thread()
    world.chat_repo.resume_automation_at(
        tenant_id=TENANT,
        thread_id=thread_id,
        cursor=MenuCursor(menu_version_id=MENU_VERSION, node_id="productos"),
    )
    assert world.chat_repo.states[thread_id].automation_paused_at is None
    if kind == "product":
        world.service.send_product(TENANT, thread_id, USER, world.product("Limonada"), "")
    elif kind == "piece":
        world.service.send_piece(TENANT, thread_id, USER, world.piece(), "")
    elif kind == "photo":
        world.service.send_photo(TENANT, thread_id, USER, JPEG, "image/jpeg", "a.jpg", "")
    else:
        world.chats.send(TENANT, thread_id, USER, TextSend(text="hola"))
    state = world.chat_repo.states[thread_id]
    assert (state.automation_paused_at, state.paused_by_user_id) == (NOW, USER)


def test_a_phone_photo_is_copied_to_r2_and_a_webp_becomes_a_jpeg(world: World) -> None:
    thread_id = world.thread()
    world.service.send_photo(
        TENANT, thread_id, USER, WEBP, "image/webp", "IMG 0042.webp", "Así quedó tu pedido."
    )
    att = world.only_row().attachment
    assert (att["kind"], att["content_type"], att["filename"]) == (
        "photo",
        "image/jpeg",
        "IMG_0042.jpg",
    )
    stored = world.blobs.objects[(TENANT, att["object_key"])]
    assert stored[:3] == b"\xff\xd8\xff" and len(stored) == att["bytes"]


@pytest.mark.parametrize(
    ("content", "content_type", "reason"),
    [
        (b"\xff\xd8\xff" + b"0" * MAX_INPUT_BYTES, "image/jpeg", "too_large"),
        (_png_header(20_000, 20_000), "image/png", "too_large"),
        (b"GIF89a....", "image/gif", "unsupported_type"),
        (b"%PDF-1.7 not an image", "image/jpeg", "unsupported_type"),
        (b"", "image/png", "empty"),
    ],
    # Keep PYTEST_CURRENT_TEST below Windows' environment-variable size limit.
    ids=["oversized-bytes", "oversized-dimensions", "gif", "disguised-pdf", "empty"],
)
def test_a_phone_photo_too_big_or_of_another_type_writes_nothing(
    world: World, content: bytes, content_type: str, reason: str
) -> None:
    thread_id = world.thread()
    with pytest.raises(AttachmentRefused) as refused:
        world.service.send_photo(TENANT, thread_id, USER, content, content_type, "x", "")
    assert refused.value.reason == reason
    assert world.outbox.rows == {} and world.blobs.objects == {}
    assert thread_id not in world.chat_repo.states


def test_outside_the_window_nothing_is_copied_or_queued(world: World) -> None:
    draft_id = world.piece()
    blobs_before = dict(world.blobs.objects)
    thread_id = world.thread(inbound_ago=timedelta(hours=25))
    with pytest.raises(WindowClosed):
        world.service.send_piece(TENANT, thread_id, USER, draft_id, "")
    with pytest.raises(WindowClosed):
        world.service.send_photo(TENANT, thread_id, USER, JPEG, "image/jpeg", "a.jpg", "")
    assert world.outbox.rows == {} and world.blobs.objects == blobs_before


def test_a_double_tap_with_the_same_request_key_queues_once(world: World) -> None:
    thread_id = world.thread()
    first = world.service.send_photo(
        TENANT, thread_id, USER, JPEG, "image/jpeg", "a.jpg", "", request_key="tap-1"
    )
    second = world.service.send_photo(
        TENANT, thread_id, USER, JPEG, "image/jpeg", "a.jpg", "", request_key="tap-1"
    )
    assert first == second and len(world.outbox.rows) == 1


# --- the upload at send time -----------------------------------------------------------


class UploadingClient:
    """`upload_media` answers media ids; `send_payload` follows the script."""

    def __init__(self, *outcomes: str | Exception, upload_error: Exception | None = None) -> None:
        self._outcomes = list(outcomes)
        self._upload_error = upload_error
        self.uploads: list[tuple[int, str, str]] = []
        self.payloads: list[dict[str, Any]] = []

    async def upload_media(self, content: bytes, content_type: str, filename: str) -> str:
        if self._upload_error is not None:
            error, self._upload_error = self._upload_error, None
            raise error
        self.uploads.append((len(content), content_type, filename))
        return f"media-{len(self.uploads)}"

    async def send_payload(self, payload: dict[str, Any]) -> str:
        self.payloads.append(payload)
        outcome = self._outcomes.pop(0) if self._outcomes else f"wamid.{uuid4().hex}"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class R2Source:
    def __init__(self, blobs: MemoryBlobStore) -> None:
        self.blobs = blobs
        self.reads = 0

    def read(self, tenant_id: UUID, object_key: str) -> bytes:
        self.reads += 1
        return self.blobs.read(tenant_id, object_key)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _sender(world: World, client: UploadingClient, clock: Clock) -> tuple[OutboxSender, R2Source]:
    async def factory(*, tenant_id: UUID, connection_id: UUID) -> UploadingClient:
        return client

    source = R2Source(world.blobs)
    world.outbox._clock = clock  # the rows' due times follow the sender's clock
    sender = OutboxSender(
        world.outbox,
        factory,
        lambda **_: None,
        worker_id="test:attachments",
        opt_ins=OptInService(MemoryOptInRepository(), clock=clock),
        clock=clock,
        attachments=source,
    )
    return sender, source


async def test_a_retried_send_does_not_upload_twice(world: World) -> None:
    thread_id = world.thread()
    item_id = world.service.send_photo(
        TENANT, thread_id, USER, JPEG, "image/jpeg", "pedido.jpg", "Tu pedido."
    )
    client = UploadingClient(WhatsAppApiError("boom", is_transport=True), "wamid.ok")
    clock = Clock()
    sender, source = _sender(world, client, clock)

    first = await sender.run_once(TENANT)
    assert (first.retried, first.sent) == (1, 0)
    row = world.outbox.rows[item_id]
    # The id was recorded before the (failed) send: on the row AND in the body.
    assert row.attachment["media_id"] == "media-1"
    assert row.payload["image"] == {"caption": "Tu pedido.", "id": "media-1"}

    clock.now = NOW + timedelta(minutes=5)
    second = await sender.run_once(TENANT)

    assert second.sent == 1 and row.status == "sent" and row.wamid == "wamid.ok"
    assert client.uploads == [(len(JPEG), "image/jpeg", "pedido.jpg")]
    assert source.reads == 1
    assert [p["image"]["id"] for p in client.payloads] == ["media-1", "media-1"]
    # The conversation shows the caption, like an inbound captioned photo.
    assert world.outbox.messages[-1].text == "Tu pedido."


async def test_a_failed_upload_is_retried_and_uploads_on_the_next_try(world: World) -> None:
    thread_id = world.thread()
    item_id = world.service.send_photo(TENANT, thread_id, USER, PNG, "image/png", "a.png", "")
    client = UploadingClient(upload_error=WhatsAppApiError("HTTP 500", status=500))
    clock = Clock()
    sender, _ = _sender(world, client, clock)

    assert (await sender.run_once(TENANT)).retried == 1
    assert world.outbox.rows[item_id].attachment["media_id"] is None and client.payloads == []
    clock.now = NOW + timedelta(minutes=5)
    assert (await sender.run_once(TENANT)).sent == 1
    assert len(client.uploads) == 1 and client.payloads[0]["image"]["id"] == "media-1"


async def test_a_text_or_menu_row_never_uploads(world: World) -> None:
    _publish_menu(world)
    world.product("Limonada", photo=None)
    thread_id = world.thread()
    world.service.send_menu_list(TENANT, thread_id, USER)
    client = UploadingClient()
    sender, source = _sender(world, client, Clock())
    assert (await sender.run_once(TENANT)).sent == 1
    assert client.uploads == [] and source.reads == 0


# --- retention (ADR 39 (c), founder decision 2026-11-04) -------------------------------


def test_a_piece_sent_over_whatsapp_10_days_ago_is_not_purged() -> None:
    generated = NOW - timedelta(days=100)
    never_sent = evaluate(RetentionFacts(generated_at=generated), NOW)
    sent = evaluate(
        RetentionFacts(generated_at=generated, last_whatsapp_at=NOW - timedelta(days=10)), NOW
    )
    assert never_sent.state is RetentionState.EXPIRED
    assert sent.state is RetentionState.ACTIVE
    assert sent.deadline == NOW + timedelta(days=80)


def test_the_latest_use_wins_whichever_it_is() -> None:
    generated = NOW - timedelta(days=200)
    facts = RetentionFacts(
        generated_at=generated,
        last_event_at=NOW - timedelta(days=50),
        last_whatsapp_at=NOW - timedelta(days=120),
    )
    assert evaluate(facts, NOW).deadline == NOW + timedelta(days=40)


def test_a_big_phone_photo_is_downscaled_to_a_jpeg_that_fits(world: World) -> None:
    """UX review: Android photos are often over 5 MB — re-encoded, not refused."""
    side = 1500
    noisy = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
    out = io.BytesIO()
    noisy.save(out, format="PNG")
    big = out.getvalue()
    assert MAX_IMAGE_BYTES < len(big) <= MAX_INPUT_BYTES
    thread_id = world.thread()

    world.service.send_photo(TENANT, thread_id, USER, big, "image/png", "IMG_1.png", "")

    att = world.only_row().attachment
    stored = world.blobs.objects[(TENANT, att["object_key"])]
    assert att["content_type"] == "image/jpeg" and stored[:3] == b"\xff\xd8\xff"
    assert len(stored) <= MAX_IMAGE_BYTES


def test_a_huge_dimension_tiny_file_is_refused_before_decoding() -> None:
    bomb = _png_header(20_000, 20_000)
    assert len(bomb) < 1024
    with pytest.raises(AttachmentRefused) as refused:
        fit_image(bomb)
    assert refused.value.reason == "too_large"
    assert "demasiado grande" in refused.value.message


@pytest.mark.parametrize("kind", ["product", "piece"])
def test_a_number_without_a_brand_sends_no_product_or_piece(world: World, kind: str) -> None:
    """ADR 43: a multi-business tenant must never mix businesses."""
    del world.reads.brands[(TENANT, CONN)]
    thread_id = world.thread()
    with pytest.raises(AttachmentRefused) as refused:
        if kind == "product":
            world.service.send_product(TENANT, thread_id, USER, world.product("Limonada"), "")
        else:
            world.service.send_piece(TENANT, thread_id, USER, world.piece(), "")
    assert refused.value.reason == "no_brand"
    assert refused.value.message == "Este número no tiene una marca con productos."
    assert world.outbox.rows == {}


def test_a_double_tap_prepares_once(world: World) -> None:
    thread_id = world.thread()
    for _ in range(2):
        world.service.send_photo(
            TENANT, thread_id, USER, JPEG, "image/jpeg", "a.jpg", "", request_key="tap-2"
        )
    assert len(world.outbox.rows) == 1 and len(world.blobs.objects) == 1


# --- 0123's CHECK takes SQL NULL or an object, never JSON `null` -------------------------


def test_no_attachment_is_sql_null_not_json_null() -> None:
    """CI run 41932495976: `Jsonb(None)` (JSON `null`) broke every plain enqueue."""
    from sqlalchemy import null
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from qualify_api.whatsapp.models import WhatsAppOutboxItem

    column_type = WhatsAppOutboxItem.__table__.c.attachment.type
    assert column_type.none_as_null is True
    dialect = postgresql.psycopg.dialect()
    process = column_type.bind_processor(dialect)
    assert process is None or process(None) is None  # SQL NULL, not a Jsonb(None)

    compiled = (
        pg_insert(WhatsAppOutboxItem)
        .values(tenant_id=TENANT, kind="reply", payload={"to": WA_ID}, attachment=null())
        .compile(dialect=dialect)
    )
    assert "attachment" in str(compiled) and "NULL" in str(compiled)
    assert "attachment" not in compiled.params
