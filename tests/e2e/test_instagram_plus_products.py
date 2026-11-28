"""m-25143229 slice (b): «Tus productos» and «Tu oferta» in the «+» of an Instagram chat,
and «Cómo llegar» only with a WhatsApp number (UX U1).

Seeded by `chat_fixtures.seed_chats` (`chats_page`) and, where the test says so,
`seed_products_and_offer` (rows only: no file is written to any bucket). A tap on
«Enviar» only writes `pending` rows to this run's `conversation_outbox`; the harness
runs no worker and Instagram reads through the in-memory channel: nothing reaches Meta.

With `QUALIFY_E2E_SHOTS` the tests leave `despues-*` screenshots (360 and 1280 px).
"""

from __future__ import annotations

import pytest

from .chat_fixtures import (
    SHOP_OFFER_TEXT,
    SHOP_PRODUCT,
    SHOP_PRODUCT_NO_PHOTO,
    seed_products_and_offer,
    unlink_whatsapp_numbers,
)
from .conftest import expect
from .test_instagram_plus import (
    DESKTOP,
    PHONE,
    _box,
    _instagram,
    _open,
    _open_plus,
    _outbox_texts,
    _row,
    _shot,
    _whatsapp,
)

pytestmark = pytest.mark.e2e


def _outbox_media(tenant_id, thread_id: str) -> list[str]:  # noqa: ANN001
    import uuid

    from qualify_api.conversations.models import ConversationOutboxItem
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    with tenant_session(tenant_id) as session:
        rows = session.scalars(
            select(ConversationOutboxItem)
            .where(ConversationOutboxItem.thread_id == uuid.UUID(thread_id))
            .where(ConversationOutboxItem.status == "pending")
            .order_by(ConversationOutboxItem.created_at)
        ).all()
        return [r.media_type or "text" for r in rows]


@pytest.mark.parametrize("size", ["360", "1280"])
def test_instagram_plus_has_whatsapps_four_rows(chats_page, size) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(PHONE if size == "360" else DESKTOP)
    _open(page, _whatsapp(ids, "whatsapp_open"))
    whatsapp = dict(_open_plus(page))
    page.keyboard.press("Escape")
    _open(page, _instagram(ids, "instagram_open"))
    rows = _open_plus(page)
    _shot(page, f"despues-instagram-plus-{size}")
    assert [t for t, _ in rows] == ["Tus productos", "Tu oferta", "Formas de pago", "Cómo llegar"]
    assert all(whatsapp[text] == icon for text, icon in rows)
    page.keyboard.press("Escape")


def test_without_a_whatsapp_number_directions_is_not_offered(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    unlink_whatsapp_numbers(page._qualify_e2e_tenant_id)
    page.set_viewport_size(PHONE)
    _open(page, _instagram(ids, "instagram_open"))
    rows = [t for t, _ in _open_plus(page)]
    _shot(page, "despues-instagram-sin-numero-360")
    assert rows == ["Tus productos", "Tu oferta", "Formas de pago"]
    page.keyboard.press("Escape")


def test_empty_products_and_offer_lead_to_where_they_are_set(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(PHONE)
    _open(page, _instagram(ids, "instagram_open"))
    _open_plus(page)
    _row(page, "Tus productos")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_role("link", name="Agregar un producto")).to_be_visible(timeout=20_000)
    _shot(page, "despues-instagram-productos-vacio-360")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    _open_plus(page)
    _row(page, "Tu oferta")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_role("link", name="Ir a Por aprobar")).to_be_visible(timeout=20_000)
    _shot(page, "despues-instagram-oferta-vacia-360")
    # WhatsApp's own one-step rule: «Enviar» is there and off, nothing to send
    expect(drawer.get_by_role("button", name="Enviar")).to_be_disabled()
    page.keyboard.press("Escape")


@pytest.mark.parametrize("size", ["360", "1280"])
def test_a_product_and_the_offer_go_as_picture_then_text(chats_page, size) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    tenant = page._qualify_e2e_tenant_id
    seed_products_and_offer(tenant, page._qualify_e2e_user_id)
    page.set_viewport_size(PHONE if size == "360" else DESKTOP)
    _open(page, _instagram(ids, "instagram_open"))
    thread = ids["instagram_open"]

    # «Tus productos»: the grid → the review (two bubbles + the text) → one send per tap
    _open_plus(page)
    _row(page, "Tus productos")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_text(SHOP_PRODUCT_NO_PHOTO)).to_be_visible(timeout=20_000)
    _shot(page, f"despues-instagram-productos-{size}")
    drawer.get_by_text(SHOP_PRODUCT, exact=True).click()
    expect(drawer.get_by_text("Revisa y envía")).to_be_visible(timeout=20_000)
    field = drawer.get_by_role("textbox", name="Texto que acompaña la foto")
    assert (field.input_value() or "").startswith(f"{SHOP_PRODUCT} — $25.000")
    _shot(page, f"despues-instagram-producto-revisa-{size}")
    assert _outbox_texts(tenant, thread) == []
    drawer.get_by_role("button", name="Enviar").dblclick()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
    page.wait_for_timeout(1_500)
    assert _outbox_media(tenant, thread) == ["image", "text"]

    # a product without a photo: its text alone
    _open_plus(page)
    _row(page, "Tus productos")
    drawer = page.get_by_role("dialog")
    drawer.get_by_text(SHOP_PRODUCT_NO_PHOTO, exact=True).click()
    expect(drawer.get_by_text("le llegará solo el texto")).to_be_visible(timeout=20_000)
    drawer.get_by_role("button", name="Enviar").click()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
    page.wait_for_timeout(1_500)
    assert _outbox_media(tenant, thread) == ["image", "text", "text"]

    # «Tu oferta»: the marked piece, its text ready to edit, picture then text
    _open_plus(page)
    _row(page, "Tu oferta")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_text("Tu oferta").first).to_be_visible(timeout=20_000)
    expect(drawer.get_by_text(SHOP_OFFER_TEXT).first).to_be_visible(timeout=20_000)
    _shot(page, f"despues-instagram-oferta-revisa-{size}")
    drawer.get_by_role("button", name="Enviar").click()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
    page.wait_for_timeout(1_500)
    assert _outbox_media(tenant, thread) == ["image", "text", "text", "image", "text"]
    expect(_box(page)).to_be_visible()
