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
import uuid
from pathlib import Path

from .conftest import _E2E_PLATFORM_APP, expect

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
    expect(_menu(page).locator(f'a[href="{_ROUTE}"]')).to_be_visible()  # menu hydrated
    links = _menu(page).locator("a[href]")
    hrefs = links.evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert hrefs.index(_ROUTE) == hrefs.index("/promotions") + 1, hrefs

    _menu(page).locator(f'a[href="{_ROUTE}"]').click()
    expect(page).to_have_url(re.compile(re.escape(app_server + _ROUTE) + r"(\?.*)?$"))
    _expect_lit(page, _ROUTE)
    expect(page.get_by_role("heading", level=1, name=_TITLE)).to_be_visible()
    expect(page).to_have_title(re.compile(re.escape(_TITLE)))
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


# --- with a number: the panels load (review of 2026-11-14) -------------------------------


def _seed_whatsapp_number(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """A connected WhatsApp number as `whatsapp.connect` would leave it — WITHOUT a
    credential: nothing here can call Meta. Written in-tenant through the sanctioned
    door, on the platform app row `conftest` seeds for Instagram."""
    from qualify_api.connections.models import PlatformApp, SocialConnection
    from qualify_api.tenancy.models import Brand
    from qualify_api.whatsapp.models import WhatsAppPhoneNumber
    from qualify_shared.db.admin import admin_session
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    with admin_session() as session:
        if session.get(PlatformApp, _E2E_PLATFORM_APP) is None:
            session.add(
                PlatformApp(
                    id=_E2E_PLATFORM_APP,
                    app_id="e2e-test-app",
                    secret_ref="env:E2E_TEST_APP_SECRET",
                    api_version="v23.0",
                )
            )
    connection_id = uuid.uuid4()
    with tenant_session(tenant_id) as session:
        brand_id = session.scalar(select(Brand.id).order_by(Brand.created_at))
        session.add(
            SocialConnection(
                id=connection_id,
                tenant_id=tenant_id,
                brand_id=brand_id,
                platform_app_id=_E2E_PLATFORM_APP,
                platform="whatsapp",
                account_type="business",
                external_account_id=f"e2e-wa-{connection_id}",
                external_username="+57 300 000 0000",
                granted_scopes=[],
                status="active",
                access_posture="development",
                current_credential_version=1,
                connected_by_user_id=user_id,
            )
        )
        session.flush()
        session.add(
            WhatsAppPhoneNumber(
                tenant_id=tenant_id,
                brand_id=brand_id,
                connection_id=connection_id,
                waba_id=f"e2e-waba-{connection_id}",
                phone_number_id=f"e2e-phone-{connection_id}",
                display_phone_number="+57 300 000 0000",
                verified_name="E2E · Arepera Doña Carmen",
            )
        )


# Records, from the click on, whether a page ever drew the OTHER page's panel under its
# own header: the chat list under «Promociones por WhatsApp», or the promotions strip
# under «WhatsApp». A MutationObserver sees every intermediate render.
_WATCH_WRONG_PANEL = """() => {
  window.__qWrongPanel = [];
  const check = () => {
    const h1 = document.querySelector('h1');
    const title = h1 ? h1.textContent.trim() : '';
    if (title === 'Promociones por WhatsApp' && document.querySelector('.q-wa-chats'))
      window.__qWrongPanel.push('chats under Promociones');
    if (title === 'WhatsApp' && document.body.innerText.includes('Clientes que aceptaron'))
      window.__qWrongPanel.push('promotions under WhatsApp');
  };
  new MutationObserver(check).observe(document.body,
    { subtree: true, childList: true, characterData: true });
}"""


def test_switching_pages_never_draws_the_other_pages_panel(
    signed_up_page,  # noqa: ANN001 — a Playwright Page
    app_server: str,
) -> None:
    page = signed_up_page
    _seed_whatsapp_number(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)  # noqa: SLF001
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{app_server}/whatsapp?tab=chats")
    expect(page.locator(".q-wa-chats")).to_be_visible(timeout=60_000)
    page.evaluate(_WATCH_WRONG_PANEL)

    _menu(page).locator(f'a[href="{_ROUTE}"]').click()
    expect(page.get_by_role("heading", level=1, name=_TITLE)).to_be_visible()
    expect(page.get_by_text("Clientes que aceptaron").first).to_be_visible(timeout=60_000)
    _shot(page, "promociones-whatsapp-con-numero")

    _menu(page).locator('a[href^="/whatsapp"]').first.click()
    expect(page.get_by_role("heading", level=1, name="WhatsApp")).to_be_visible()
    expect(page.locator(".q-wa-chats")).to_be_visible(timeout=60_000)
    assert page.evaluate("window.__qWrongPanel") == []
