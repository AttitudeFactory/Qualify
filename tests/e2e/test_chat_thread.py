"""m-25027371 (BU-A5): an open WhatsApp chat and an open Instagram chat look and read alike.

Seeded by `chat_fixtures.seed_chats` (`chats_page`); nothing reaches Meta or R2."""

from __future__ import annotations

import re

import pytest

from .conftest import expect

pytestmark = pytest.mark.e2e

MORE = "Más acciones de este chat"


def _open(page, path: str) -> None:  # noqa: ANN001
    origin = re.match(r"https?://[^/]+", page.url)
    assert origin is not None
    page.goto(origin[0] + path)
    expect(page.locator(".q-chat-thread .q-chat-msg").first).to_be_visible(timeout=60_000)


def test_both_threads_share_the_header_bubbles_and_menu(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size({"width": 360, "height": 800})

    _open(
        page,
        f"/whatsapp?tab=chats&cuenta={ids['whatsapp_connection']}&chat={ids['whatsapp_open']}"
        "&filtro=por-responder&desde=por-responder",
    )
    head = page.locator(".q-chat-head").first
    expect(head.get_by_role("heading", name="Laura Gómez")).to_be_visible()
    expect(head.get_by_role("button", name="Por responder")).to_be_visible()
    expect(head.get_by_text("Pago por revisar")).to_be_visible()
    expect(page.get_by_role("separator", name="Ayer")).to_be_visible()
    expect(page.get_by_role("img", name="Leído")).to_have_count(1)
    expect(page.get_by_role("img", name="No entregado")).to_have_count(1)
    head.get_by_role("button", name=MORE).click()
    expect(page.get_by_role("menuitem")).to_have_text(
        ["Asignar", "Cerrar", "Ajustes de este canal"]
    )
    page.keyboard.press("Escape")
    strip = page.get_by_role("button", name=re.compile(r"^Pedido · 3 productos"))
    expect(strip).to_have_attribute("aria-expanded", "false")
    strip.click()
    expect(page.get_by_role("button", name="Pedido listo")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    _open(
        page,
        f"/responder?tab=mensajes&cuenta={ids['instagram_connection']}"
        f"&chat={ids['instagram_open']}",
    )
    head = page.locator(".q-chat-head").first
    expect(head.get_by_role("heading", name="Camila Ríos")).to_be_visible()
    expect(page.get_by_role("separator", name="Hoy")).to_be_visible()
    head.get_by_role("button", name=MORE).click()
    expect(page.get_by_role("menuitem")).to_have_text(["Cerrar", "Ajustes de este canal"])
