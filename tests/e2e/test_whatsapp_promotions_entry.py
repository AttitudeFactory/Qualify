"""m-25017862 (BU-A12, D3): «Promociones por WhatsApp» sits next to «Anuncios».

In a browser: the menu entry follows «Anuncios» in «Publica» and opens its own page
(`/whatsapp/promociones`), lit on its own — never «WhatsApp»; an old address of the
Promociones tab under `/whatsapp` lands there; on a phone the entry is in the «Más»
drawer. The signed-up business has no WhatsApp number, so the page shows its
no-number state under its own header; the panels themselves are covered offline
(`Qualify/test_whatsapp_page.py`).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .conftest import expect

_SHOTS = os.environ.get("QUALIFY_E2E_SHOTS", "")
_ROUTE = "/whatsapp/promociones"
_TITLE = "Promociones por WhatsApp"


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"), full_page=True)


def _menu(page):  # noqa: ANN001, ANN202
    return page.locator('nav[aria-label="Secciones"]')


def _expect_lit(page, route: str) -> None:  # noqa: ANN001
    menu = _menu(page)
    expect(menu.locator(f'a[href="{route}"]')).to_have_attribute("aria-current", "page")
    expect(menu.locator('[aria-current="page"]')).to_have_count(1)


def test_the_entry_follows_anuncios_and_opens_its_own_page(
    signed_up_page,  # noqa: ANN001 — a Playwright Page
    app_server: str,
) -> None:
    page = signed_up_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{app_server}/")
    links = _menu(page).locator("a[href]")
    hrefs = links.evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert hrefs.index(_ROUTE) == hrefs.index("/promotions") + 1, hrefs

    _menu(page).locator(f'a[href="{_ROUTE}"]').click()
    expect(page).to_have_url(re.compile(re.escape(app_server + _ROUTE) + r"(\?.*)?$"))
    _expect_lit(page, _ROUTE)
    expect(page.get_by_role("heading", level=1, name=_TITLE)).to_be_visible()
    expect(page).to_have_title(f"Qualify · {_TITLE}")
    _shot(page, "promociones-whatsapp-escritorio")

    # «WhatsApp» lights only itself, and its strip no longer offers «Promociones».
    _menu(page).locator('a[href^="/whatsapp"]').first.click()
    expect(page).to_have_url(re.compile(re.escape(app_server) + r"/whatsapp(\?.*)?$"))
    expect(_menu(page).locator('[aria-current="page"]')).to_have_count(1)
    expect(_menu(page).locator(f'a[href="{_ROUTE}"]')).not_to_have_attribute("aria-current", "page")
    expect(page.get_by_role("heading", level=1, name="WhatsApp")).to_be_visible()


def test_an_old_promotions_address_lands_on_the_new_page(
    signed_up_page,  # noqa: ANN001 — a Playwright Page
    app_server: str,
) -> None:
    page = signed_up_page
    page.set_viewport_size({"width": 1280, "height": 900})
    for old, sub in (
        ("/whatsapp?tab=promociones&sub=aprobados", "aprobados"),
        ("/whatsapp?tab=plantillas", "aprobados"),
        ("/whatsapp?tab=campanas", "enviadas"),
    ):
        page.goto(f"{app_server}{old}")
        expect(page).to_have_url(f"{app_server}{_ROUTE}?sub={sub}", timeout=60_000)
        _expect_lit(page, _ROUTE)
        expect(page.get_by_role("heading", level=1, name=_TITLE)).to_be_visible()


def test_on_a_phone_the_entry_is_in_the_more_drawer(
    signed_up_page,  # noqa: ANN001 — a Playwright Page
    app_server: str,
) -> None:
    page = signed_up_page
    page.set_viewport_size({"width": 360, "height": 780})
    page.goto(f"{app_server}/")
    page.locator(".q-bottom-more").click()
    entry = page.locator("#q-sidebar").locator(f'a[href="{_ROUTE}"]')
    entry.scroll_into_view_if_needed()
    expect(entry).to_be_visible()
    expect(entry).to_contain_text(_TITLE)
    _shot(page, "promociones-whatsapp-cajon-celular")
    entry.click()
    expect(page).to_have_url(re.compile(re.escape(app_server + _ROUTE) + r"(\?.*)?$"))
    expect(page.locator("#q-sidebar")).not_to_have_class(re.compile(r"q-mobile-open"))
    bar = page.locator('nav[aria-label="Accesos rápidos"]')
    expect(bar.locator('.q-bottom-cell[data-active="true"] .q-bottom-label')).to_have_text("Más")
    expect(page.get_by_role("heading", level=1, name=_TITLE)).to_be_visible()
    _shot(page, "promociones-whatsapp-celular")
