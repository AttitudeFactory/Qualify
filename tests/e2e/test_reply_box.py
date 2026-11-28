"""m-25027374 (BU-A7): one reply box for WhatsApp and Instagram, drawing only what the
channel can send, and an open chat that gives the phone's screen to the conversation.

Seeded by `chat_fixtures.seed_chats` (`chats_page`); nothing reaches Meta or R2 and
nothing is sent: no test taps «Enviar».

`test_capture_reply_box` only takes screenshots and measures (360 px and 1280 px, light
and dark, both channels, open and closed window); it runs when `QUALIFY_E2E_SHOTS` names
a directory, and prints the share of the viewport the messages get on a phone.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from .conftest import expect

pytestmark = pytest.mark.e2e

PHONE = {"width": 360, "height": 780}
DESKTOP = {"width": 1280, "height": 800}

#: What the page and the open chat take of the viewport, with the reply box in view.
_MEASURE = """
() => {
  const vh = window.innerHeight;
  const rect = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return null;
    return {top: r.top, bottom: r.bottom, height: r.height};
  };
  const header = rect('.q-page-header');
  const bar = rect('.q-bottom-bar');
  const box = rect('.q-chat-thread .q-wa-composer');
  const scroll = rect('.q-chat-thread .q-chat-scroll');
  const head = rect('.q-chat-thread .q-chat-head__top') || rect('.q-chat-thread .q-chat-head');
  const pinned = head && head.top <= 1 ? head.bottom : 0;
  const top = Math.max(scroll ? scroll.top : 0, header ? header.bottom : 0, pinned, 0);
  const bottom = Math.min(scroll ? scroll.bottom : 0, bar ? bar.top : vh, vh);
  return {
    vh,
    header: header && Math.max(0, Math.min(header.bottom, vh) - Math.max(header.top, 0)),
    bar: bar && Math.max(0, vh - bar.top),
    box: box && Math.max(0, Math.min(box.bottom, vh) - Math.max(box.top, 0)),
    head: head && Math.max(0, Math.min(head.bottom, vh) - Math.max(head.top, 0)),
    messages: Math.max(0, bottom - top),
    share: Math.max(0, bottom - top) / vh,
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  };
}
"""


def _origin(page) -> str:  # noqa: ANN001
    match = re.match(r"https?://[^/]+", page.url)
    assert match is not None
    return match[0]


def _whatsapp(ids: dict[str, str], key: str) -> str:
    return (
        f"/whatsapp?tab=chats&cuenta={ids['whatsapp_connection']}&chat={ids[key]}"
        "&filtro=todos&desde=por-responder"
    )


def _instagram(ids: dict[str, str], key: str) -> str:
    return f"/responder?tab=mensajes&cuenta={ids['instagram_connection']}&chat={ids[key]}"


def _open(page, path: str) -> None:  # noqa: ANN001
    page.goto(_origin(page) + path)
    expect(page.locator(".q-chat-thread .q-chat-msg").first).to_be_visible(timeout=60_000)
    page.wait_for_timeout(600)


def _box_in_view(page) -> None:  # noqa: ANN001
    # What the owner sees when replying: the page scrolled to its foot (the panel is the
    # scroll container; its foot clears the bottom bar).
    page.evaluate(
        "() => { const p = document.querySelector('.q-panel');"
        " if (p) p.scrollTop = p.scrollHeight; }"
    )
    page.wait_for_timeout(300)


@pytest.mark.skipif(not os.environ.get("QUALIFY_E2E_SHOTS"), reason="QUALIFY_E2E_SHOTS not set")
def test_capture_reply_box(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    out = Path(os.environ["QUALIFY_E2E_SHOTS"])
    out.mkdir(parents=True, exist_ok=True)
    label = os.environ.get("QUALIFY_E2E_SHOTS_LABEL", "shot")
    report: dict[str, object] = {}
    cases = [
        ("whatsapp-open", _whatsapp(ids, "whatsapp_open")),
        ("whatsapp-closed", _whatsapp(ids, "whatsapp_closed")),
        ("instagram-open", _instagram(ids, "instagram_open")),
        ("instagram-closed", _instagram(ids, "instagram_closed")),
    ]
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        # the app keeps the owner's choice (the header's toggle) under `theme`
        page.evaluate(f"localStorage.setItem('theme', '{scheme}')")
        for size_name, size in (("360", PHONE), ("1280", DESKTOP)):
            page.set_viewport_size(size)
            for name, path in cases:
                _open(page, path)
                _box_in_view(page)
                key = f"{label}-{name}-{size_name}-{scheme}"
                page.screenshot(path=str(out / f"{key}.png"))
                report[key] = page.evaluate(_MEASURE)
    (out / f"{label}-measures.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    for key, value in report.items():
        if "-360-light" in key:
            print(key, value)  # noqa: T201 — the run's measure, read by hand


# ======================================================================================
# The box, as the owner sees it
# ======================================================================================

_SMALL_CONTROLS = """
(sel) => [...document.querySelectorAll(sel)]
  .filter((el) => el.offsetParent !== null && !el.closest('.q-reply-hidden-upload'))
  .map((el) => [el.getAttribute('aria-label') || el.textContent.trim(),
                Math.round(el.getBoundingClientRect().height),
                Math.round(el.getBoundingClientRect().width)])
  .filter(([, h, w]) => h < 44 || w < 44)
"""
_CONTROLS = ".q-reply-box button, .q-reply-box textarea, .q-reply-box .rt-TextFieldRoot"


def _box(page):  # noqa: ANN001, ANN202
    return page.locator(".q-chat-thread .q-reply-box")


def _page_header_steps_aside(page) -> None:  # noqa: ANN001
    header = page.locator(".q-page-header")
    assert header.evaluate("el => getComputedStyle(el).position") == "static"
    expect(header.get_by_role("heading", level=1)).to_have_count(1)  # still read
    expect(page.locator(".q-business-chip")).to_be_hidden()
    expect(page.locator(".q-chat-head__top")).to_be_visible()


def _only_send_is_solid(page) -> None:  # noqa: ANN001
    solid = _box(page).locator(".rt-Button.rt-variant-solid")
    expect(solid).to_have_count(1)
    expect(solid).to_have_text("Enviar")


def _plus_rows(page) -> list[str]:  # noqa: ANN001
    _box(page).get_by_role("button", name="Enviar algo al cliente").click()
    items = page.locator(".q-orbit-menu [role=menuitem]")
    expect(items.first).to_be_visible()
    texts = [t.strip() for t in items.all_inner_texts()]
    page.keyboard.press("Escape")
    return texts


def test_whatsapp_reply_box_on_a_phone(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(PHONE)
    _open(page, _whatsapp(ids, "whatsapp_open"))
    box = _box(page)
    # The conversation gets the screen: the page header is no longer pinned and shows
    # no title (still one h1 for screen readers); the chat's top line is pinned.
    _page_header_steps_aside(page)
    top = page.locator(".q-chat-head__top")
    assert top.evaluate("el => getComputedStyle(el).position") == "sticky"
    expect(top.get_by_role("button", name="Por responder")).to_be_visible()
    # One box: «+», «Botones», the text, «Enviar» — and the menu's new name.
    expect(box.get_by_role("textbox", name="Tu respuesta")).to_be_visible()
    expect(box.get_by_role("button", name="Botones")).to_have_attribute("aria-pressed", "false")
    expect(box.get_by_text("tu menú de bienvenida se pausa")).to_be_visible()
    expect(box.get_by_text("respuesta automática")).to_have_count(0)
    expect(box.get_by_role("button", name="Sugerir respuesta")).to_have_count(0)  # BU-A18
    _only_send_is_solid(page)
    assert _plus_rows(page) == [
        "Tus productos",
        "Tu oferta",
        "Tu menú",
        "Formas de pago",
        "Cómo llegar",
        "Fotos y videos",
    ]
    box.get_by_role("button", name="Botones").click()
    expect(box.get_by_role("button", name="Botones")).to_have_attribute("aria-pressed", "true")
    expect(box.get_by_role("textbox", name="Botón 1")).to_be_visible()
    assert page.evaluate(_SMALL_CONTROLS, _CONTROLS) == []
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    # Enter writes a new line (nothing sends on a key); a draft survives the 15 s refresh.
    field = box.get_by_role("textbox", name="Tu respuesta")
    field.fill("Hola Laura")
    field.press("Enter")
    field.type("¿Lo quieres con papas?")
    page.wait_for_timeout(17_000)
    expect(field).to_have_value("Hola Laura\n¿Lo quieres con papas?")
    expect(page.locator(".q-chat-msg", has_text="Hola Laura")).to_have_count(0)


def test_instagram_reply_box_on_a_phone(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(PHONE)
    _open(page, _instagram(ids, "instagram_open"))
    box = _box(page)
    _page_header_steps_aside(page)
    # The 24 h is said once, in the header — not again over the box.
    expect(page.locator(".q-chat-head__rest .q-chat-window")).to_have_count(1)
    expect(box.get_by_text("Instagram solo permite responder")).to_have_count(0)
    # U1: the most used first, so «Sugerir respuesta» is on screen at 360 px.
    tools = box.locator(".q-reply-tools .q-reply-tool")
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
    suggest = box.get_by_role("button", name="Sugerir respuesta").bounding_box()
    assert suggest is not None and suggest["x"] + suggest["width"] <= PHONE["width"]
    botones = box.get_by_role("button", name="Botones")
    assert botones.get_attribute("aria-pressed") is None  # one ARIA state: expanded
    expect(botones).to_have_attribute("aria-expanded", "false")
    expect(box.get_by_role("button", name="Respuestas rápidas")).to_have_count(0)
    _only_send_is_solid(page)
    # m-25143229: the «+» with WhatsApp's rows Instagram can send; nothing disabled.
    assert _plus_rows(page) == ["Formas de pago", "Cómo llegar"]
    # The tool IS the file input's target: the picker opens on the owner's own tap.
    for tool in ("Foto o video", "Archivo"):
        with page.expect_file_chooser(timeout=5_000) as chooser:
            box.get_by_role("button", name=tool).click()
        assert chooser.value is not None
    assert page.evaluate(_SMALL_CONTROLS, _CONTROLS) == []
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    box.get_by_role("button", name="Mensajes guardados").click()
    # exact: «Editar mensajes guardados» (m-25131413) sits in the same menu
    expect(
        page.locator(".q-conv-templates").get_by_text("Mensajes guardados", exact=True)
    ).to_be_visible()
    page.keyboard.press("Escape")
    field = box.get_by_role("textbox", name="Tu respuesta")
    field.fill("Ya te paso el total")
    page.wait_for_timeout(17_000)
    expect(field).to_have_value("Ya te paso el total")


def test_closed_windows_keep_only_what_the_owner_can_do(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(PHONE)
    _open(page, _whatsapp(ids, "whatsapp_closed"))
    box = _box(page)
    expect(box.get_by_role("button", name="Enviar un mensaje aprobado")).to_be_visible()
    expect(box.get_by_text("Pasaron más de 24 horas")).to_have_count(0)
    expect(box.get_by_role("button", name="Enviar", exact=True)).to_have_count(0)
    _open(page, _instagram(ids, "instagram_closed"))
    box = _box(page)
    # U2: the reason is in the header; no box to type into, only when it comes back.
    expect(page.locator(".q-chat-head__rest .q-chat-window")).to_have_text(
        "Pasaron 24 h: Instagram no deja responder desde aquí"
    )
    expect(box).to_have_text("Cuando vuelva a escribir, podrás responderle aquí.")
    expect(box.get_by_role("textbox")).to_have_count(0)
    expect(box.get_by_role("button")).to_have_count(0)


def test_on_a_wide_screen_the_page_header_stays(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(DESKTOP)
    for path in (_whatsapp(ids, "whatsapp_open"), _instagram(ids, "instagram_open")):
        _open(page, path)
        expect(page.locator(".q-page-header")).to_be_visible()
        _only_send_is_solid(page)
        assert page.evaluate(_SMALL_CONTROLS, _CONTROLS) == []
        # U5 / m-25029798: while typing, the chat header stays in view under the page header
        # (on a desk the chat fills the pane, so the page does not scroll it away).
        _box_in_view(page)
        top = page.locator(".q-chat-head").first.bounding_box()
        header = page.locator(".q-page-header").bounding_box()
        assert top is not None and header is not None
        assert top["y"] >= header["y"] + header["height"] - 1
        assert top["y"] + top["height"] <= DESKTOP["height"]
