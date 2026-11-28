"""m-25143229: the «+» of an Instagram chat — WhatsApp's rows «Formas de pago» and «Cómo
llegar», their steps, their empty states and the one send per «Enviar».

Seeded by `chat_fixtures.seed_chats` (`chats_page`) and, where the test says so,
`seed_shop_details` (an address on the business's WhatsApp number and one payment
method WITHOUT a QR — no bucket is written). A test that taps «Enviar» only writes
`pending` rows to this run's `conversation_outbox`: the harness runs no worker and the
Instagram account reads through the in-memory channel, so nothing reaches Meta.

With `QUALIFY_E2E_SHOTS` naming a directory the tests also leave screenshots there
(`despues-*`, 360 and 1280 px).
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest

from .chat_fixtures import SHOP_ADDRESS, SHOP_PAYMENT, seed_shop_details
from .conftest import expect

pytestmark = pytest.mark.e2e

PHONE = {"width": 360, "height": 780}
DESKTOP = {"width": 1280, "height": 800}
PLUS = "Enviar algo al cliente"


def _origin(page) -> str:  # noqa: ANN001
    match = re.match(r"https?://[^/]+", page.url)
    assert match is not None
    return match[0]


def _instagram(ids: dict[str, str], key: str) -> str:
    return f"/responder?tab=mensajes&cuenta={ids['instagram_connection']}&chat={ids[key]}"


def _whatsapp(ids: dict[str, str], key: str) -> str:
    return (
        f"/whatsapp?tab=chats&cuenta={ids['whatsapp_connection']}&chat={ids[key]}"
        "&filtro=todos&desde=por-responder"
    )


def _open(page, path: str) -> None:  # noqa: ANN001
    page.goto(_origin(page) + path)
    expect(page.locator(".q-chat-thread .q-chat-msg").first).to_be_visible(timeout=60_000)
    page.wait_for_timeout(600)


def _box(page):  # noqa: ANN001, ANN202
    return page.locator(".q-chat-thread .q-reply-box")


def _shot(page, name: str) -> None:  # noqa: ANN001
    out = os.environ.get("QUALIFY_E2E_SHOTS")
    if not out:
        return
    Path(out).mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(400)
    page.screenshot(path=str(Path(out) / f"{name}.png"))


def _open_plus(page) -> list[tuple[str, str]]:  # noqa: ANN001
    """Opens the «+» and returns its rows: (text, the icon's Lucide class)."""
    _box(page).get_by_role("button", name=PLUS).click()
    items = page.locator(".q-orbit-menu [role=menuitem]")
    expect(items.first).to_be_visible()
    return [
        (
            item.inner_text().strip(),
            item.locator("svg").first.get_attribute("class") or "",
        )
        for item in items.all()
    ]


def _row(page, text: str) -> None:  # noqa: ANN001
    page.locator(".q-orbit-menu [role=menuitem]", has_text=text).click()


def _outbox_texts(tenant_id: uuid.UUID, thread_id: str) -> list[str]:
    from qualify_api.conversations.models import ConversationOutboxItem
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    with tenant_session(tenant_id) as session:
        rows = session.scalars(
            select(ConversationOutboxItem)
            .where(ConversationOutboxItem.thread_id == uuid.UUID(thread_id))
            .where(ConversationOutboxItem.status == "pending")
        ).all()
        return [str((r.payload.get("message") or {}).get("text") or "") for r in rows]


@pytest.mark.parametrize("size", ["360", "1280"])
def test_instagram_plus_has_whatsapps_rows_minus_the_menu(chats_page, size) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(PHONE if size == "360" else DESKTOP)
    # WhatsApp's «+», as it was (and the icons Instagram must share)
    _open(page, _whatsapp(ids, "whatsapp_open"))
    whatsapp = _open_plus(page)
    _shot(page, f"despues-whatsapp-plus-{size}")
    page.keyboard.press("Escape")
    assert [t for t, _ in whatsapp] == [
        "Tus productos",
        "Tu oferta",
        "Tu menú",
        "Formas de pago",
        "Cómo llegar",
        "Fotos y videos",
    ]
    _open(page, _instagram(ids, "instagram_open"))
    instagram = _open_plus(page)
    _shot(page, f"despues-instagram-plus-{size}")
    assert [t for t, _ in instagram] == ["Formas de pago", "Cómo llegar"]
    icons = dict(whatsapp)
    assert all(icons[text] == icon for text, icon in instagram)
    page.keyboard.press("Escape")
    # Instagram's own tools stay, one each
    tools = _box(page).locator(".q-reply-tools .q-reply-tool")
    names = [(t.get_attribute("aria-label") or t.inner_text()).strip() for t in tools.all()]
    assert names == [
        "Sugerir respuesta",
        "Botones",
        "Mensajes guardados",
        "Foto o video",
        "Archivo",
        "Nota de voz",
        "Enviar un corazón",
    ]
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_without_payment_or_address_the_rows_lead_to_where_they_are_set(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(PHONE)
    _open(page, _instagram(ids, "instagram_open"))
    _open_plus(page)
    _row(page, "Formas de pago")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_text("Aún no cargas tus formas de pago")).to_be_visible(timeout=20_000)
    add = drawer.get_by_role("link", name="Agregar forma de pago")
    href = add.get_attribute("href") or ""
    assert href.startswith("/chats/ajustes/formas-de-pago?")
    assert f"cuenta={ids['whatsapp_connection']}" in href and "volver=" in href
    _shot(page, "despues-instagram-pago-vacio-360")
    expect(drawer.get_by_role("button", name="Enviar")).to_have_count(0)
    drawer.get_by_role("button", name="Volver al chat").click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    _open_plus(page)
    _row(page, "Cómo llegar")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_text("Aún no tienes la dirección de tu local")).to_be_visible(
        timeout=20_000
    )
    complete = drawer.get_by_role("link", name="Completar mi dirección")
    assert (complete.get_attribute("href") or "").startswith("/chats/ajustes/whatsapp/perfil?")
    _shot(page, "despues-instagram-llegar-vacio-360")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)


@pytest.mark.parametrize("size", ["360", "1280"])
def test_payment_and_directions_preview_then_one_send_per_tap(chats_page, size) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    tenant = page._qualify_e2e_tenant_id
    seed_shop_details(tenant)
    page.set_viewport_size(PHONE if size == "360" else DESKTOP)
    _open(page, _instagram(ids, "instagram_open"))

    # «Formas de pago»: one method → straight to «Revisa y envía», nothing sent yet
    _open_plus(page)
    _row(page, "Formas de pago")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_text("Revisa y envía")).to_be_visible(timeout=20_000)
    expect(drawer.get_by_text(SHOP_PAYMENT)).to_be_visible(timeout=20_000)
    expect(drawer.get_by_role("link", name="Cambiar estos datos")).to_be_visible()
    _shot(page, f"despues-instagram-pago-revisa-{size}")
    assert _outbox_texts(tenant, ids["instagram_open"]) == []
    send = drawer.get_by_role("button", name="Enviar")
    expect(send).to_be_enabled()
    send.dblclick()  # a double tap queues ONE message
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
    page.wait_for_timeout(1_500)
    sent = _outbox_texts(tenant, ids["instagram_open"])
    assert len(sent) == 1 and sent[0].startswith(SHOP_PAYMENT), sent

    # «Cómo llegar»: the address with a maps link, one text
    _open_plus(page)
    _row(page, "Cómo llegar")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_text(f"Estamos en {SHOP_ADDRESS}.", exact=False)).to_be_visible(
        timeout=20_000
    )
    expect(drawer.get_by_text("Si pones tu local en el mapa")).to_have_count(0)
    _shot(page, f"despues-instagram-llegar-revisa-{size}")
    drawer.get_by_role("button", name="Enviar").click()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
    page.wait_for_timeout(1_500)
    sent = _outbox_texts(tenant, ids["instagram_open"])
    assert len(sent) == 2
    assert any(t.startswith(f"Estamos en {SHOP_ADDRESS}.\nhttps://maps.google.com/") for t in sent)


def test_a_closed_window_offers_nothing_to_send(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(PHONE)
    _open(page, _instagram(ids, "instagram_closed"))
    expect(_box(page).get_by_role("button", name=PLUS)).to_have_count(0)
    expect(_box(page).get_by_role("button")).to_have_count(0)


def test_the_phones_back_steps_the_panel_back_then_closes_it_in_the_chat(chats_page) -> None:  # noqa: ANN001
    """Review U2: WhatsApp's `?flujo=` mechanism — «atrás» is one step back, then the
    panel closes, and the owner is still in the same chat."""
    from .chat_fixtures import seed_cash_method

    page = chats_page
    ids = page._qualify_e2e_chats
    tenant = page._qualify_e2e_tenant_id
    seed_shop_details(tenant)
    seed_cash_method(tenant)
    page.set_viewport_size(PHONE)
    _open(page, _instagram(ids, "instagram_open"))
    _open_plus(page)
    _row(page, "Formas de pago")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_text("¿Cuál forma de pago?")).to_be_visible(timeout=20_000)
    expect(page).to_have_url(re.compile(r"flujo=enviar-ig"), timeout=10_000)
    drawer.get_by_text("Nequi", exact=True).click()
    expect(drawer.get_by_text("Revisa y envía")).to_be_visible(timeout=20_000)
    expect(page).to_have_url(re.compile(r"paso=2"), timeout=10_000)
    page.go_back()
    expect(page.get_by_role("dialog").get_by_text("¿Cuál forma de pago?")).to_be_visible(
        timeout=20_000
    )
    page.go_back()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=20_000)
    assert f"chat={ids['instagram_open']}" in page.url and "flujo=" not in page.url
    expect(_box(page).get_by_role("button", name=PLUS)).to_be_visible()
    assert _outbox_texts(tenant, ids["instagram_open"]) == []


def test_directions_help_and_link_are_instagrams(chats_page) -> None:  # noqa: ANN001
    """Review U3 and U4: Instagram's own help line; the link has no «#» nor «%20»."""
    page = chats_page
    ids = page._qualify_e2e_chats
    seed_shop_details(page._qualify_e2e_tenant_id)
    page.set_viewport_size(PHONE)
    _open(page, _instagram(ids, "instagram_open"))
    _open_plus(page)
    _row(page, "Cómo llegar")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_text("Le llega tu dirección con un enlace al mapa.")).to_be_visible(
        timeout=20_000
    )
    expect(drawer.get_by_text("Le llega tu local en el mapa")).to_have_count(0)
    expect(
        drawer.get_by_text("https://maps.google.com/?q=Calle+10+5-20%2C+C%C3%BAcuta")
    ).to_be_visible()
    _shot(page, "despues-instagram-llegar-revisa-360")
    page.keyboard.press("Escape")


def test_without_a_whatsapp_number(chats_page) -> None:  # noqa: ANN001
    """Review U1, as built: the business has no WhatsApp number of its own. Recorded on
    screen (`despues-instagram-sin-numero-360`); see the report for what is pending."""
    from .chat_fixtures import unlink_whatsapp_numbers

    page = chats_page
    ids = page._qualify_e2e_chats
    unlink_whatsapp_numbers(page._qualify_e2e_tenant_id)
    page.set_viewport_size(PHONE)
    _open(page, _instagram(ids, "instagram_open"))
    _open_plus(page)
    _row(page, "Cómo llegar")
    drawer = page.get_by_role("dialog")
    expect(drawer.get_by_text("Aún no tienes la dirección de tu local")).to_be_visible(
        timeout=20_000
    )
    _shot(page, "despues-instagram-sin-numero-360")
    page.keyboard.press("Escape")
