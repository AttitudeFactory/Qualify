"""m-25029799 (BU-A11, second part): WhatsApp's chats are attended only in «Por
responder»; the WhatsApp screen keeps its configuration («Tu número»).

Seeded by `chat_fixtures.seed_chats` (`chats_page`) plus a second WhatsApp number
(`seed_second_number`); nothing reaches Meta or R2 and nothing is sent: no test taps
«Enviar».

`test_capture_whatsapp_config_only` only takes screenshots (360 px and 1280 px, light and
dark) of the WhatsApp screen, of the old list address and of «Por responder» narrowed to
WhatsApp; it runs when `QUALIFY_E2E_SHOTS` names a directory (`QUALIFY_E2E_SHOTS_LABEL`
prefixes the files: «antes» on `origin/main`, «despues» on the branch).
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

#: Where the owner is: the address, the page's title, the lit menu entries, the side
#: menu's «WhatsApp» and «Por responder» entries (where they lead and their badge), the
#: filters on screen and whether anything slides sideways.
_WHERE = """
() => {
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden';
  };
  const entry = (name) => {
    const a = [...document.querySelectorAll('a')]
      .find((el) => el.textContent.trim().startsWith(name) && el.closest('nav, aside'));
    return a ? { href: a.getAttribute('href'), text: a.textContent.trim() } : null;
  };
  const h1 = document.querySelector('h1');
  const groups = [...document.querySelectorAll('[role="group"]')].filter(shown)
    .map((g) => ({ label: g.getAttribute('aria-label'),
                   items: [...g.querySelectorAll('button')].filter(shown)
                     .map((b) => b.textContent.trim()) }));
  return {
    url: location.pathname + location.search,
    title: h1 ? h1.textContent.trim() : '',
    lit: [...document.querySelectorAll('[aria-current="page"]')].filter(shown)
      .map((el) => el.textContent.trim()),
    whatsappEntry: entry('WhatsApp'),
    respondEntry: entry('Por responder'),
    groups,
    rows: [...document.querySelectorAll('.q-conv-row')].filter(shown).length,
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  };
}
"""


def _origin(page) -> str:  # noqa: ANN001
    return page.url.split("/", 3)[0] + "//" + page.url.split("/", 3)[2]


def _settle(page) -> None:  # noqa: ANN001
    expect(page.locator("h1").first).to_be_visible(timeout=60_000)
    page.wait_for_timeout(2_500)


@pytest.mark.skipif(not os.environ.get("QUALIFY_E2E_SHOTS"), reason="QUALIFY_E2E_SHOTS not set")
def test_capture_whatsapp_config_only(chats_page) -> None:  # noqa: ANN001
    from .chat_fixtures import seed_second_number

    page = chats_page
    seed_second_number(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)
    out = Path(os.environ["QUALIFY_E2E_SHOTS"])
    out.mkdir(parents=True, exist_ok=True)
    label = os.environ.get("QUALIFY_E2E_SHOTS_LABEL", "shot")
    report: dict[str, object] = {}
    views = (
        ("whatsapp", "/whatsapp"),
        ("lista-vieja", "/whatsapp?tab=chats&filtro=abiertos"),
        ("por-responder-whatsapp", "/responder?tab=mensajes&canal=whatsapp&filtro=todos"),
    )
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        page.evaluate(f"localStorage.setItem('theme', '{scheme}')")
        for size_name, size in (("360", PHONE), ("1280", DESKTOP)):
            page.set_viewport_size(size)
            for name, address in views:
                page.goto(_origin(page) + address)
                _settle(page)
                # On «Por responder» the list sits under «Quién te espera»: show it.
                page.evaluate(
                    "() => document.querySelector('.q-wa-chats__list')"
                    "?.scrollIntoView({block: 'start'})"
                )
                page.wait_for_timeout(300)
                key = f"{label}-{name}-{size_name}-{scheme}"
                page.screenshot(path=str(out / f"{key}.png"))
                report[key] = page.evaluate(_WHERE)
    (out / f"{label}-where.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8"
    )


# --- the story, in the browser -------------------------------------------------------------


def _row(page, name: str):  # noqa: ANN001, ANN202
    return page.locator(".q-conv-list .q-conv-row").filter(has_text=name).first


def _menu_entry(page, name: str):  # noqa: ANN001, ANN202
    """The side menu's entry (desktop), by its visible word."""
    return page.locator("nav a").filter(has_text=re.compile(rf"^\s*{name}")).first


@pytest.mark.parametrize("size", [PHONE, DESKTOP], ids=["360", "1280"])
def test_whatsapp_keeps_only_tu_numero(chats_page, size: dict[str, int]) -> None:  # noqa: ANN001
    page = chats_page
    page.set_viewport_size(size)
    page.goto(_origin(page) + "/whatsapp")
    expect(page.get_by_role("heading", level=1, name="WhatsApp")).to_be_visible(timeout=60_000)
    expect(page.get_by_text("Ver detalles").first).to_be_visible(timeout=60_000)
    page.wait_for_timeout(1_500)
    assert "/whatsapp" in page.url and "/responder" not in page.url
    for gone in ("Filtrar chats", "Secciones de WhatsApp"):
        expect(page.get_by_role("group", name=gone)).to_have_count(0)
    expect(page.locator(".q-conv-row")).to_have_count(0)
    expect(page.locator(".q-wa-chats__list")).to_have_count(0)
    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")


@pytest.mark.parametrize(
    ("old", "chip", "pressed"),
    [
        ("/whatsapp?tab=chats", "todos", "Todos"),
        ("/whatsapp?tab=chats&filtro=abiertos", "todos", "Todos"),
        ("/whatsapp?tab=chats&filtro=sin-leer", "por-responder", "Por responder"),
        ("/whatsapp?tab=chats&filtro=por-responder", "por-responder", "Por responder"),
        ("/whatsapp?tab=chats&filtro=cerrados", "cerrados", "Cerrados"),
        ("/whatsapp?tab=chats&filtro=pago-por-revisar", "pago-por-revisar", "Pago por revisar"),
    ],
)
def test_every_old_list_address_lands_in_por_responder(  # noqa: ANN001
    chats_page, old: str, chip: str, pressed: str
) -> None:
    page = chats_page
    page.set_viewport_size(DESKTOP)
    page.goto(_origin(page) + "/whatsapp?tab=numero&sub=qr")
    expect(page.get_by_role("heading", level=1, name="WhatsApp")).to_be_visible(timeout=60_000)
    before = page.url
    page.goto(_origin(page) + old)
    expect(page).to_have_url(
        re.compile(rf"/responder\?tab=mensajes&filtro={chip}&canal=whatsapp$"), timeout=60_000
    )
    filters = page.get_by_role("group", name="Qué chats ver")
    expect(filters.locator('[aria-pressed="true"]')).to_contain_text(pressed, timeout=60_000)
    lit = page.locator('nav [aria-current="page"]')
    expect(lit.first).to_contain_text("Por responder")
    # Replaced, not pushed: «atrás» goes to the page before, never the old address.
    page.go_back()
    expect(page).to_have_url(before, timeout=30_000)


def test_the_number_choice_narrows_and_survives_a_chat(chats_page) -> None:  # noqa: ANN001
    from .chat_fixtures import seed_second_number

    page = chats_page
    ids = page._qualify_e2e_chats  # noqa: SLF001
    second = seed_second_number(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)  # noqa: SLF001
    page.set_viewport_size(DESKTOP)
    page.goto(_origin(page) + "/responder?tab=mensajes&filtro=todos&canal=whatsapp")
    numbers = page.get_by_role("group", name="De qué número de WhatsApp")
    expect(numbers).to_be_visible(timeout=60_000)
    expect(numbers.get_by_role("button")).to_have_text(
        ["Todos los números", re.compile(r"\+57 311"), re.compile(r"\+57 300")]
    )
    expect(_row(page, "Laura Gómez")).to_be_visible()
    expect(_row(page, "Sofía Ruiz")).to_be_visible()
    numbers.get_by_role("button", name=re.compile(r"\+57 311")).click()
    expect(page).to_have_url(re.compile(rf"numero={second['connection']}"), timeout=30_000)
    expect(_row(page, "Laura Gómez")).to_have_count(0, timeout=30_000)
    expect(_row(page, "Sofía Ruiz")).to_be_visible()
    todos = page.get_by_role("group", name="Qué chats ver").get_by_role(
        "button", name=re.compile("^Todos")
    )
    expect(todos).to_have_text("Todos · 2")
    # Its chat opens beside the list and the way back keeps the number.
    _row(page, "Sofía Ruiz").click()
    expect(page.locator(".q-chat-thread .q-chat-msg").first).to_be_visible(timeout=60_000)
    assert f"numero={second['connection']}" in page.url and "chat=" in page.url
    page.go_back()
    expect(page).to_have_url(re.compile(rf"numero={second['connection']}$"), timeout=30_000)
    expect(_row(page, "Laura Gómez")).to_have_count(0)
    # The old list's address with its number lands on that number.
    page.goto(_origin(page) + f"/whatsapp?tab=chats&cuenta={second['connection']}&filtro=sin-leer")
    expect(page).to_have_url(
        re.compile(
            rf"/responder\?tab=mensajes&filtro=por-responder&canal=whatsapp"
            rf"&numero={second['connection']}$"
        ),
        timeout=60_000,
    )
    expect(_row(page, "Sofía Ruiz")).to_be_visible(timeout=60_000)
    expect(_row(page, "Laura Gómez")).to_have_count(0)
    # Another business's number in the address narrows nothing.
    page.goto(
        _origin(page)
        + "/responder?tab=mensajes&filtro=todos&canal=whatsapp&numero="
        + str(ids["instagram_connection"])
    )
    expect(_row(page, "Laura Gómez")).to_be_visible(timeout=60_000)
    expect(_row(page, "Sofía Ruiz")).to_be_visible()


def test_one_number_draws_no_choice(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    page.set_viewport_size(PHONE)
    page.goto(_origin(page) + "/responder?tab=mensajes&filtro=todos&canal=whatsapp")
    expect(page.locator(".q-conv-list .q-conv-row").first).to_be_visible(timeout=60_000)
    expect(page.get_by_role("group", name="De qué número de WhatsApp")).to_have_count(0)


def test_menu_and_inicio_reach_whatsapp_chats_in_por_responder(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    page.set_viewport_size(DESKTOP)
    page.goto(_origin(page) + "/whatsapp")
    expect(page.get_by_role("heading", level=1, name="WhatsApp")).to_be_visible(timeout=60_000)
    page.wait_for_timeout(2_000)  # the menu's counts poll lands
    whatsapp = _menu_entry(page, "WhatsApp")
    expect(whatsapp).to_have_attribute("href", "/whatsapp")
    assert re.fullmatch(r"\s*WhatsApp\s*", whatsapp.inner_text()), whatsapp.inner_text()  # no badge
    respond = _menu_entry(page, "Por responder")
    expect(respond).to_have_attribute("href", "/responder")
    respond.click()
    expect(page).to_have_url(re.compile(r"/responder"), timeout=60_000)
    expect(page.locator(".q-wa-chats__list")).to_be_visible(timeout=60_000)
    # The default chip is «Por responder»; every WhatsApp chat is under «Todos».
    page.get_by_role("group", name="Qué chats ver").get_by_role(
        "button", name=re.compile("^Todos")
    ).click()
    expect(_row(page, "Laura Gómez")).to_be_visible(timeout=60_000)
    expect(page.locator('nav [aria-current="page"]').first).to_contain_text("Por responder")
    # Inicio's «Te escribieron» (both channels) opens the same list.
    page.goto(_origin(page) + "/")
    link = page.get_by_role("link", name=re.compile("Te escribieron"))
    expect(link.first).to_be_visible(timeout=60_000)
    link.first.click()
    expect(page).to_have_url(re.compile(r"/responder"), timeout=60_000)
    expect(page.locator(".q-wa-chats__list")).to_be_visible(timeout=60_000)
    # The default chip is «Por responder»; every WhatsApp chat is under «Todos».
    page.get_by_role("group", name="Qué chats ver").get_by_role(
        "button", name=re.compile("^Todos")
    ).click()
    expect(_row(page, "Laura Gómez")).to_be_visible(timeout=60_000)
    expect(page.locator('nav [aria-current="page"]').first).to_contain_text("Por responder")
