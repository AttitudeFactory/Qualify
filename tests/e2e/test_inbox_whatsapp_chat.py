"""m-25029798 (BU-A11, first part): a WhatsApp chat tapped in «Por responder» opens where
an Instagram chat opens — beside the single list on a desk, the whole screen with
«‹ Por responder» on a phone — and the list comes back with its filter, channel and
scroll.

Seeded by `chat_fixtures.seed_chats` (`chats_page`); nothing reaches Meta or R2 and
nothing is sent: no test taps «Enviar», «Pedido listo» or «Sí, ya pagó».

`test_capture_whatsapp_in_inbox` only takes screenshots (360 px and 1280 px, light and
dark); it runs when `QUALIFY_E2E_SHOTS` names a directory.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from .conftest import _open_business, expect

pytestmark = pytest.mark.e2e

PHONE = {"width": 360, "height": 780}
DESKTOP = {"width": 1280, "height": 800}
MORE = "Más acciones de este chat"
BACK = "Por responder"

#: Where the owner is: the visible «‹ Por responder» buttons, the lit menu entries, the
#: page's title and the address.
_WHERE = """
() => {
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden';
  };
  const backs = [...document.querySelectorAll('button')]
    .filter((b) => shown(b) && b.textContent.trim() === 'Por responder'
      && b.querySelector('svg.lucide-chevron-left'));
  const lit = [...document.querySelectorAll('[aria-current="page"]')]
    .filter(shown).map((el) => el.textContent.trim());
  const h1 = document.querySelector('h1');
  return {
    url: location.pathname + location.search,
    backs: backs.length,
    lit,
    title: h1 ? h1.textContent.trim() : '',
    whatsappFilters: !!document.querySelector('[aria-label="Filtrar chats"]'),
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  };
}
"""


#: U4: what must fit in a 1280×800 window with a chat open (each fully inside it).
_FIT = """
() => {
  const inside = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.height > 0 && r.top >= 0 && r.bottom <= window.innerHeight;
  };
  const byText = (sel, text) => [...document.querySelectorAll(sel)]
    .find((el) => el.textContent.trim().startsWith(text));
  return {
    strip: inside(byText('.q-chat-thread button', 'Pedido')),
    takeOver: inside(byText('.q-chat-thread button', 'Tomar el control')),
    box: inside(document.querySelector('.q-chat-thread .q-wa-composer')),
  };
}
"""
#: m-25029798: the wide open chat — header and messages heights, the messages' share of
#: the window, whether the reply box is fully inside it and whether the page scrolls.
_ROOM = """
() => {
  const r = (sel) => {
    const el = document.querySelector(sel);
    return el ? el.getBoundingClientRect() : null;
  };
  const head = r('.q-chat-thread .q-chat-head');
  const msgs = r('.q-chat-thread .q-chat-scroll');
  const box = r('.q-chat-thread .q-wa-composer');
  const panel = document.querySelector('main.q-panel');
  const vh = window.innerHeight;
  return {
    vh,
    header: head ? Math.round(head.height) : null,
    messages: msgs ? Math.round(msgs.height) : null,
    share: msgs ? Math.round((msgs.height / vh) * 100) : null,
    boxVisible: !!box && box.top >= 0 && box.bottom <= vh,
    pageScrolls: panel.scrollHeight > panel.clientHeight + 2,
  };
}
"""
WIDE = [(1280, 800), (1512, 664), (1024, 768)]


def _origin(page) -> str:  # noqa: ANN001
    match = re.match(r"https?://[^/]+", page.url)
    assert match is not None
    return match[0]


def _list(page, query: str = "") -> None:  # noqa: ANN001
    page.goto(_origin(page) + "/responder?tab=mensajes" + query)
    expect(page.locator(".q-conv-list .q-conv-row").first).to_be_visible(timeout=60_000)


def _row(page, name: str):  # noqa: ANN001, ANN202
    return page.locator(".q-conv-list .q-conv-row").filter(has_text=name).first


def _thread_ready(page) -> None:  # noqa: ANN001
    expect(page.locator(".q-chat-thread .q-chat-msg").first).to_be_visible(timeout=60_000)
    page.wait_for_timeout(400)


def _menu_pick(page, head, name: str, *, click: bool = True) -> None:  # noqa: ANN001
    """Open «⋯» until it offers `name` (the act and the refreshes after it redraw the
    header meanwhile), then tap it."""
    for _ in range(10):
        if page.get_by_role("menu").count() == 0:
            head.get_by_role("button", name=MORE).click()
        item = page.get_by_role("menuitem", name=name, exact=True)
        try:
            expect(item).to_be_enabled(timeout=2_000)
            if click:
                item.click(timeout=2_000)
            return
        except AssertionError:
            page.keyboard.press("Escape")
            page.wait_for_timeout(700)
        except Exception:  # noqa: BLE001 — a redraw detached it: try again
            page.keyboard.press("Escape")
            page.wait_for_timeout(700)
    raise AssertionError(f"«⋯» never offered {name}")


def _panel_scroll(page) -> int:  # noqa: ANN001
    return int(page.evaluate("() => document.querySelector('main.q-panel')?.scrollTop || 0"))


@pytest.mark.skipif(not os.environ.get("QUALIFY_E2E_SHOTS"), reason="QUALIFY_E2E_SHOTS not set")
def test_capture_whatsapp_in_inbox(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    out = Path(os.environ["QUALIFY_E2E_SHOTS"])
    out.mkdir(parents=True, exist_ok=True)
    label = os.environ.get("QUALIFY_E2E_SHOTS_LABEL", "shot")
    report: dict[str, object] = {}
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        page.evaluate(f"localStorage.setItem('theme', '{scheme}')")
        sizes = [("360", PHONE)] + [(f"{w}x{h}", {"width": w, "height": h}) for w, h in WIDE]
        for size_name, size in sizes:
            page.set_viewport_size(size)
            _list(page, "&filtro=todos")
            page.wait_for_timeout(600)
            key = f"{label}-list-{size_name}-{scheme}"
            page.screenshot(path=str(out / f"{key}.png"))
            report[key] = page.evaluate(_WHERE)
            for chat, name in (("whatsapp", "Laura Gómez"), ("instagram", "Camila Ríos")):
                _row(page, name).click()
                _thread_ready(page)
                page.evaluate("() => { document.querySelector('main.q-panel').scrollTop = 0; }")
                page.wait_for_timeout(300)
                key = f"{label}-{chat}-open-{size_name}-{scheme}"
                page.screenshot(path=str(out / f"{key}.png"))
                report[key] = {
                    **page.evaluate(_WHERE),
                    "fit": page.evaluate(_FIT),
                    "room": page.evaluate(_ROOM),
                }
            page.goto(_origin(page) + "/whatsapp?tab=chats&filtro=todos")
            expect(page.get_by_role("button", name="Ir a Por responder")).to_be_visible(
                timeout=60_000
            )
            page.wait_for_timeout(600)
            page.screenshot(path=str(out / f"{label}-whatsapp-tab-{size_name}-{scheme}.png"))
    (out / f"{label}-where.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


def test_the_wide_open_chat_gives_the_messages_the_room(chats_page) -> None:  # noqa: ANN001
    """m-25029798: on a wide screen the open chat (either channel) fills the window below
    the tabs: a compact header (≤ about 7rem, no back row: the list is beside it), the
    messages take what is left (never under 14rem) and the reply box rests inside the
    window without scrolling the page — when the window is tall enough for header +
    14rem + box; a shorter one scrolls the page. Nothing pins under the page header any
    more: the page does not scroll."""
    page = chats_page
    for width, height in WIDE:
        page.set_viewport_size({"width": width, "height": height})
        _list(page, "&filtro=todos")
        for name in ("Laura Gómez", "Camila Ríos"):
            _row(page, name).click()
            _thread_ready(page)
            page.evaluate("() => { document.querySelector('main.q-panel').scrollTop = 0; }")
            page.wait_for_timeout(300)
            room = page.evaluate(_ROOM)
            where = page.evaluate(_WHERE)
            assert where["backs"] == 0, (width, height, name, where)
            if width >= 1280:  # at 1024 the line under the name wraps
                assert room["header"] <= 7.5 * 16, (width, height, name, room)
            assert room["messages"] >= 14 * 16 - 2, (width, height, name, room)
            # where the page does not scroll, the box is in the window; the window is tall
            # enough for that at 1280×800 (1512×664 and 1024×768 scroll the page)
            if not room["pageScrolls"] or height >= 800:
                assert room["boxVisible"] and not room["pageScrolls"], (width, height, name, room)
            print("ROOM", width, height, name, room)
        expect(page.get_by_text("Quién te espera")).to_have_count(0)
    # The order card unfolds inside the pane: the box stays in the window.
    page.set_viewport_size(DESKTOP)
    _row(page, "Laura Gómez").click()
    _thread_ready(page)
    page.get_by_role("button", name=re.compile(r"^Pedido · 3 productos")).click()
    expect(page.get_by_role("button", name="Pedido listo")).to_be_visible()
    page.wait_for_timeout(300)
    assert page.evaluate(_ROOM)["boxVisible"]
    # Back to the list (the browser's «atrás» on a desk): the figures come back.
    page.go_back()
    expect(page.get_by_text("Quién te espera")).to_be_visible()


def test_a_whatsapp_row_opens_beside_the_list(chats_page) -> None:  # noqa: ANN001
    """Desk: the chat opens at the right of the list, at a «Por responder» address of the
    same shape as Instagram's, with one «‹ Por responder» and «Por responder» lit; every
    thing the chat did on its own screen is there."""
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(DESKTOP)
    _list(page, "&filtro=todos")
    _row(page, "Laura Gómez").click()
    _thread_ready(page)
    expect(page).to_have_url(
        re.compile(
            rf"/responder\?tab=mensajes.*cuenta={ids['whatsapp_connection']}"
            rf"&chat={ids['whatsapp_open']}"
        )
    )
    where = page.evaluate(_WHERE)
    assert where["backs"] == 0, where  # the list beside it is the way back on a desk
    assert "Por responder" in where["lit"], where
    assert where["title"] == "Por responder", where
    assert not where["whatsappFilters"], where
    expect(page.locator(".q-conv-list")).to_be_visible()  # the list stays beside it
    head = page.locator(".q-chat-head").first
    expect(head.get_by_role("heading", name="Laura Gómez")).to_be_visible()
    expect(head.get_by_text("Pago por revisar")).to_be_visible()

    # «Tomar el control» / «Devolver al menú» (a state change; nothing is sent)
    page.get_by_role("button", name="Tomar el control").click()
    expect(page.get_by_role("button", name="Devolver al menú")).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="Devolver al menú").click()
    expect(page.get_by_role("button", name="Tomar el control")).to_be_visible(timeout=20_000)

    # The order strip, «Pedido listo» and the payment review (the sheet only opens)
    strip = page.get_by_role("button", name=re.compile(r"^Pedido · 3 productos"))
    strip.click()
    expect(page.get_by_role("button", name="Pedido listo")).to_be_visible()
    page.get_by_role("button", name="Pago recibido").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Todavía no").click()
    expect(dialog).to_have_count(0)
    expect(page.get_by_role("button", name="No lo encuentro")).to_be_visible()

    # «⋯»: Asignar · Cerrar / Reabrir · Ajustes de este canal
    head.get_by_role("button", name=MORE).click()
    expect(page.get_by_role("menuitem")).to_have_text(
        ["Asignar", "Cerrar", "Ajustes de este canal"]
    )
    page.get_by_role("menuitem", name="Cerrar").click()
    _menu_pick(page, head, "Reabrir")  # closed: «⋯» now offers «Reabrir»
    _menu_pick(page, head, "Cerrar", click=False)  # reopened
    page.keyboard.press("Escape")

    # «Botones» and the «+» rows open their panels (choosing never sends)
    page.get_by_role("button", name="Botones").click()
    expect(page.get_by_role("textbox", name="Botón 1")).to_be_visible()
    page.get_by_role("button", name="Botones").click()
    page.get_by_role("button", name="Enviar algo al cliente").click()
    menu_rows = page.get_by_role("menuitem")
    expect(menu_rows.first).to_be_visible()
    menu_rows.first.click()
    drawer = page.get_by_role("dialog")
    expect(drawer).to_be_visible(timeout=20_000)
    page.keyboard.press("Escape")
    expect(drawer).to_have_count(0)

    # The 15 s refresh keeps the draft
    field = page.locator("#wa-reply-field")
    field.fill("Ya casi sale tu pedido")
    page.wait_for_timeout(16_500)
    expect(field).to_have_value("Ya casi sale tu pedido")
    expect(page.locator(".q-conv-list")).to_be_visible()


def test_the_closed_window_chat_offers_the_approved_message(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    page.set_viewport_size(DESKTOP)
    _list(page, "&filtro=cerrados")
    _row(page, "Pedro Díaz").click()
    _thread_ready(page)
    page.get_by_role("button", name="Enviar un mensaje aprobado").click()
    drawer = page.get_by_role("dialog")
    expect(drawer).to_be_visible(timeout=20_000)
    expect(page).to_have_url(re.compile(r"/responder\?.*flujo=mensaje-chat"))
    page.keyboard.press("Escape")
    expect(drawer).to_have_count(0)
    expect(page).to_have_url(re.compile(r"/responder\?tab=mensajes"))


def test_phone_full_screen_back_keeps_filter_channel_and_scroll(chats_page) -> None:  # noqa: ANN001
    """Phone: the chat takes the screen with one «‹ Por responder», the bar lights «Por
    responder»; back (the button, then the browser's «atrás») lands on the same filter,
    channel and scroll, for both channels."""
    from .chat_fixtures import seed_more_whatsapp_chats

    page = chats_page
    ids = page._qualify_e2e_chats
    fillers = seed_more_whatsapp_chats(page._qualify_e2e_tenant_id, ids["whatsapp_connection"], 14)
    page.set_viewport_size(PHONE)
    _list(page, "&filtro=todos&canal=whatsapp")
    last = _row(page, "Cliente 14")
    last.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    before = _panel_scroll(page)
    assert before > 200, before
    last.click()
    _thread_ready(page)
    expect(page).to_have_url(re.compile(rf"chat={fillers[-1]}"))
    where = page.evaluate(_WHERE)
    assert where["backs"] == 1, where
    assert "Por responder" in where["lit"], where
    expect(page.locator(".q-conv-list")).to_be_hidden()

    page.locator(".q-chat-head").first.get_by_role("button", name=BACK).click()
    expect(page.locator(".q-conv-list")).to_be_visible()
    expect(page).to_have_url(re.compile(r"filtro=todos&canal=whatsapp$"))
    page.wait_for_timeout(600)
    assert abs(_panel_scroll(page) - before) <= 4, (_panel_scroll(page), before)
    expect(_row(page, "Cliente 14")).to_be_in_viewport()
    chips = page.get_by_role("group", name="Qué chats ver")
    expect(chips.get_by_role("button", name=re.compile("^Todos"))).to_have_attribute(
        "aria-pressed", "true"
    )

    # The browser's «atrás» from a chat does the same.
    _row(page, "Cliente 14").click()
    _thread_ready(page)
    page.go_back()
    expect(page.locator(".q-conv-list")).to_be_visible()
    page.wait_for_timeout(800)
    assert abs(_panel_scroll(page) - before) <= 4, (_panel_scroll(page), before)

    # Instagram keeps the scroll too (its row is on the «Todos» list of every channel).
    _list(page, "&filtro=todos")
    cami = _row(page, "Camila Ríos")
    cami.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    before, row_y = _panel_scroll(page), cami.bounding_box()["y"]
    assert before > 100, before
    cami.click()
    _thread_ready(page)
    page.locator(".q-chat-head").first.get_by_role("button", name=BACK).click()
    expect(page.locator(".q-conv-list")).to_be_visible()
    page.wait_for_timeout(600)
    assert abs(_panel_scroll(page) - before) <= 4, (_panel_scroll(page), before)
    assert abs(cami.bounding_box()["y"] - row_y) <= 4  # the same row, at the same place


def test_old_whatsapp_chat_addresses_land_in_por_responder(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    page.set_viewport_size(DESKTOP)
    base = f"/whatsapp?tab=chats&cuenta={ids['whatsapp_connection']}&chat={ids['whatsapp_open']}"
    for old in (base, base + "&filtro=por-responder&desde=por-responder"):
        page.goto(_origin(page) + old)
        _thread_ready(page)
        expect(page).to_have_url(
            re.compile(
                rf"/responder\?tab=mensajes&cuenta={ids['whatsapp_connection']}"
                rf"&chat={ids['whatsapp_open']}$"
            )
        )
        expect(page.locator(".q-chat-head").first.get_by_role("heading")).to_have_text(
            "Laura Gómez"
        )
    # The WhatsApp screen itself stays put (no loop): its list, the number, settings.
    for stays in ("/whatsapp", "/whatsapp?tab=chats", "/chats/ajustes/whatsapp"):
        page.goto(_origin(page) + stays)
        page.wait_for_timeout(2_000)
        assert "/responder" not in page.url, (stays, page.url)
    # A row of WhatsApp's own Chats list opens the chat in «Por responder» too.
    page.goto(_origin(page) + "/whatsapp?tab=chats&filtro=todos")
    page.locator(".q-wa-scroll--list .q-conv-row").filter(has_text="Laura Gómez").first.click()
    _thread_ready(page)
    expect(page).to_have_url(re.compile(rf"/responder\?.*chat={ids['whatsapp_open']}"))


def test_a_chat_of_another_business_never_opens(chats_page, app_server, context) -> None:  # noqa: ANN001
    from .chat_fixtures import seed_chats

    page = chats_page
    mine = page._qualify_e2e_chats
    other = _open_business(app_server, context, scopes=None)
    theirs = seed_chats(other._qualify_e2e_tenant_id, other._qualify_e2e_user_id)
    other.close()
    page.set_viewport_size(DESKTOP)
    cases = [
        # their number and their chat
        f"/responder?tab=mensajes&cuenta={theirs['whatsapp_connection']}"
        f"&chat={theirs['whatsapp_open']}",
        # my number, their chat
        f"/responder?tab=mensajes&cuenta={mine['whatsapp_connection']}"
        f"&chat={theirs['whatsapp_open']}",
        # my number, my Instagram chat (not a chat of that number)
        f"/responder?tab=mensajes&cuenta={mine['whatsapp_connection']}"
        f"&chat={mine['instagram_open']}",
        # the old address with their ids
        f"/whatsapp?tab=chats&cuenta={theirs['whatsapp_connection']}"
        f"&chat={theirs['whatsapp_open']}",
    ]
    for address in cases:
        page.goto(_origin(page) + address)
        expect(page).to_have_url(re.compile(r"/responder/?\?tab=mensajes"), timeout=60_000)
        expect(page.locator(".q-wa-chats__list")).to_be_visible(timeout=60_000)
        page.wait_for_timeout(2_500)
        expect(page.locator(".q-chat-thread")).to_have_count(0)
        expect(page.locator(".q-chat-head")).to_have_count(0)
    # My own chat still opens by its address (the check is not a blanket refusal).
    page.goto(
        _origin(page) + f"/responder?tab=mensajes&cuenta={mine['whatsapp_connection']}"
        f"&chat={mine['whatsapp_open']}"
    )
    _thread_ready(page)
    expect(page.locator(".q-chat-head").first.get_by_role("heading")).to_have_text("Laura Gómez")
