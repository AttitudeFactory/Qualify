"""m-25027373 (BU-A10): «Tu número» left `/whatsapp` — the WhatsApp module is empty.

Founder: «el otro módulo solo sería … para configuración». Where each sub-tab went:

    Estado          → the number's card in «Tus redes» (`/connections`)
    Actividad       → `/connections/whatsapp/actividad`, from that card
    Perfil          → «Ajustes de chats» › `/chats/ajustes/whatsapp/perfil`
    Códigos QR      → «Ajustes de chats» › `/chats/ajustes/whatsapp/codigos-qr`
    Formas de pago  → «Ajustes de chats» › `/chats/ajustes/formas-de-pago`

Seeded by `chat_fixtures.seed_chats` (`chats_page`), plus a second number
(`seed_second_number`) where the number selector matters. Nothing reaches Meta: the
numbers have NO credential, so Perfil and Códigos QR show their read error, and no test
taps «Verificar ahora», «Guardar» or «Crear código».

`test_capture_tu_numero_moved` only takes screenshots (360 and 1280, light; dark for
«Tus redes» and «Ajustes de chats»); it runs when `QUALIFY_E2E_SHOTS` names a directory
(`QUALIFY_E2E_SHOTS_LABEL` prefixes the files: «antes» on `origin/main`, «despues» here).
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


def _origin(page) -> str:  # noqa: ANN001
    return re.match(r"https?://[^/]+", page.url)[0]


def _menu(page):  # noqa: ANN001, ANN202
    return page.locator("nav, aside").first


def _lit(page):  # noqa: ANN001, ANN202
    return page.locator('nav [aria-current="page"]')


def _no_sideways_scroll(page) -> None:  # noqa: ANN001
    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")


def _number_card(page, title: str = r"^Arepera E2E"):  # noqa: ANN001, ANN202
    """The «Tus redes» card of the WhatsApp number whose title matches `title`."""
    heading = page.get_by_role("heading", level=2, name=re.compile(title))
    return page.locator("div").filter(has=heading).filter(has_text="Más detalles").last


# --- Estado: the number's card in «Tus redes» ---------------------------------------------


@pytest.mark.parametrize("size", [PHONE, DESKTOP], ids=["360", "1280"])
def test_tus_redes_shows_the_numbers_state(chats_page, size: dict[str, int]) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats  # noqa: SLF001
    page.set_viewport_size(size)
    page.goto(_origin(page) + "/connections")
    card = _number_card(page)
    expect(card).to_be_visible(timeout=60_000)
    expect(card.get_by_text("Conectada", exact=True)).to_be_visible()
    # «Verificar ahora» and the number's facts sit behind the card's «Más detalles»
    # (the Instagram card's «Comprobar ahora» is not repeated on it).
    expect(card.get_by_role("button", name="Verificar ahora")).to_have_count(0)
    card.get_by_role("button", name="Más detalles").click()
    expect(card.get_by_role("button", name="Verificar ahora")).to_be_visible(timeout=30_000)
    assert card.get_by_role("button", name="Verificar ahora").bounding_box()["height"] >= 44
    for fact in ("Nombre verificado", "Calidad", "Límite de mensajes", "Último mensaje recibido"):
        expect(card.get_by_text(fact, exact=True)).to_be_visible()
    expect(card.get_by_role("button", name="Comprobar ahora")).to_have_count(0)
    _no_sideways_scroll(page)
    # Actividad hangs from the card.
    activity = card.get_by_role("link", name="Actividad")
    expect(activity).to_have_attribute(
        "href", f"/connections/whatsapp/actividad?cuenta={ids['whatsapp_connection']}"
    )
    activity.click()
    expect(page).to_have_url(
        re.compile(rf"/connections/whatsapp/actividad\?cuenta={ids['whatsapp_connection']}$"),
        timeout=60_000,
    )
    expect(page.get_by_role("heading", level=1, name="Actividad")).to_be_visible(timeout=60_000)
    expect(page.get_by_role("link", name="Tus redes").first).to_be_visible()
    expect(page.get_by_text("Conversaciones nuevas").first).to_be_visible(timeout=60_000)
    if size is DESKTOP:
        expect(_lit(page).first).to_contain_text("Tus redes")
    _no_sideways_scroll(page)


def test_every_number_has_its_own_card(chats_page) -> None:  # noqa: ANN001
    from .chat_fixtures import seed_second_number

    page = chats_page
    second = seed_second_number(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)  # noqa: SLF001
    page.set_viewport_size(DESKTOP)
    page.goto(_origin(page) + "/connections")
    first_card, second_card = _number_card(page), _number_card(page, r"Sede Norte")
    expect(first_card).to_be_visible(timeout=60_000)
    expect(second_card).to_be_visible()
    expect(second_card.get_by_role("link", name="Actividad")).to_have_attribute(
        "href", f"/connections/whatsapp/actividad?cuenta={second['connection']}"
    )


# --- Perfil, Códigos QR, Formas de pago, Actividad: their own addresses ------------------


@pytest.mark.parametrize(
    ("address", "title", "lit", "back"),
    [
        ("/chats/ajustes/whatsapp/perfil", "Perfil", "Ajustes de chats", "Ajustes de chats"),
        (
            "/chats/ajustes/whatsapp/codigos-qr",
            "Códigos QR",
            "Ajustes de chats",
            "Ajustes de chats",
        ),
        ("/chats/ajustes/formas-de-pago", "Formas de pago", "Ajustes de chats", "Ajustes de chats"),
        ("/connections/whatsapp/actividad", "Actividad", "Tus redes", "Tus redes"),
    ],
)
@pytest.mark.parametrize("size", [PHONE, DESKTOP], ids=["360", "1280"])
def test_each_moved_section_opens_at_its_address(  # noqa: ANN001
    chats_page, address: str, title: str, lit: str, back: str, size: dict[str, int]
) -> None:
    from .chat_fixtures import seed_second_number

    page = chats_page
    seed_second_number(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)  # noqa: SLF001
    page.set_viewport_size(size)
    page.goto(_origin(page) + address)
    expect(page.get_by_role("heading", level=1, name=title)).to_be_visible(timeout=60_000)
    # The way back to the place it hangs from, and (two numbers) the number selector.
    expect(page.locator(".q-page-header").get_by_role("link", name=back)).to_be_visible()
    expect(page.locator(".q-page-header [role=combobox]").first).to_be_visible(timeout=60_000)
    # No «Tu número» strip, no WhatsApp screen around it.
    expect(page.get_by_role("group", name="Tu número")).to_have_count(0)
    expect(page.get_by_text("Tus chats de WhatsApp se responden en Por responder.")).to_have_count(
        0
    )
    page.wait_for_timeout(1_500)
    assert page.url.split("?")[0].endswith(address), page.url
    if size is DESKTOP:
        expect(_lit(page)).to_have_count(1)
        expect(_lit(page)).to_contain_text(lit)
    _no_sideways_scroll(page)


def test_the_hub_opens_the_moved_sections(chats_page) -> None:  # noqa: ANN001
    """«Ajustes de chats»: «Formas de pago» opens the editor itself (no longer a pointer to
    `/whatsapp`), «Cómo llegar» the profile, and the WhatsApp card has Perfil and QR."""
    page = chats_page
    page.set_viewport_size(PHONE)
    page.goto(_origin(page) + "/chats/ajustes")
    for key, href in (
        ("formas-de-pago", "/chats/ajustes/formas-de-pago"),
        ("como-llegar", "/chats/ajustes/whatsapp/perfil"),
        ("perfil", "/chats/ajustes/whatsapp/perfil"),
        ("codigos-qr", "/chats/ajustes/whatsapp/codigos-qr"),
        ("menu", "/chats/ajustes/whatsapp"),
    ):
        row = page.locator(f'[data-setting="{key}"]')
        expect(row).to_have_attribute("href", href, timeout=60_000)
        assert row.bounding_box()["height"] >= 44, key
    expect(page.locator('a[href^="/whatsapp"]').filter(has_not_text="Promociones")).to_have_count(0)
    page.locator('[data-setting="formas-de-pago"]').click()
    expect(page).to_have_url(re.compile(r"/chats/ajustes/formas-de-pago$"), timeout=60_000)
    expect(page.get_by_role("heading", level=1, name="Formas de pago")).to_be_visible()
    expect(page.get_by_role("button", name="Agregar forma de pago").first).to_be_visible(
        timeout=60_000
    )
    _no_sideways_scroll(page)


# --- every old `/whatsapp` address redirects --------------------------------------------


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("/whatsapp", r"/connections$"),
        ("/whatsapp?tab=numero", r"/connections$"),
        ("/whatsapp?tab=numero&sub=estado", r"/connections$"),
        ("/whatsapp?tab=conexion", r"/connections$"),
        (
            "/whatsapp?tab=numero&sub=perfil&cuenta={c}",
            r"/chats/ajustes/whatsapp/perfil\?cuenta={c}$",
        ),
        (
            "/whatsapp?tab=numero&sub=pagos&cuenta={c}",
            r"/chats/ajustes/formas-de-pago\?cuenta={c}$",
        ),
        (
            "/whatsapp?tab=numero&sub=qr&cuenta={c}",
            r"/chats/ajustes/whatsapp/codigos-qr\?cuenta={c}$",
        ),
        ("/whatsapp?tab=qr", r"/chats/ajustes/whatsapp/codigos-qr$"),
        (
            "/whatsapp?tab=numero&sub=actividad&cuenta={c}",
            r"/connections/whatsapp/actividad\?cuenta={c}$",
        ),
        ("/whatsapp?tab=x&sub=<b>&otro=1", r"/connections$"),
        # The redirects that already existed keep working.
        ("/whatsapp?tab=respuesta&cuenta={c}", r"/chats/ajustes/whatsapp\?cuenta={c}$"),
        ("/whatsapp?tab=plantillas", r"/whatsapp/promociones\?sub=aprobados$"),
        (
            "/whatsapp?tab=chats&filtro=cerrados",
            r"/responder\?tab=mensajes&filtro=cerrados&canal=whatsapp$",
        ),
    ],
)
def test_every_old_whatsapp_address_redirects_once(chats_page, old: str, new: str) -> None:  # noqa: ANN001
    page = chats_page
    c = page._qualify_e2e_chats["whatsapp_connection"]  # noqa: SLF001
    page.set_viewport_size(DESKTOP)
    page.goto(_origin(page) + "/chats/ajustes")
    expect(page.get_by_role("heading", level=1, name="Ajustes de chats")).to_be_visible(
        timeout=60_000
    )
    before = page.url
    page.goto(_origin(page) + old.format(c=c))
    expect(page).to_have_url(re.compile(new.format(c=c)), timeout=60_000)
    page.wait_for_timeout(1_500)
    expect(page).to_have_url(re.compile(new.format(c=c)))  # no second hop, no loop
    # Replaced, not pushed: «atrás» goes to the page before, never the old address.
    page.go_back()
    expect(page).to_have_url(before, timeout=30_000)


def test_the_chats_way_back_survives_the_redirect(chats_page) -> None:  # noqa: ANN001
    """An old «Cambiar estos datos» bookmark: the profile opens with «Volver al chat»."""
    from urllib.parse import quote

    page = chats_page
    ids = page._qualify_e2e_chats  # noqa: SLF001
    chat = (
        f"/responder?tab=mensajes&cuenta={ids['whatsapp_connection']}&chat={ids['whatsapp_open']}"
    )
    page.set_viewport_size(PHONE)
    page.goto(
        _origin(page)
        + f"/whatsapp?tab=numero&sub=perfil&cuenta={ids['whatsapp_connection']}"
        + f"&volver={quote(chat, safe='')}"
    )
    expect(page).to_have_url(re.compile(r"/chats/ajustes/whatsapp/perfil\?cuenta=.*&volver="))
    back = page.get_by_role("link", name="Volver al chat")
    expect(back).to_be_visible(timeout=60_000)
    expect(back).to_have_attribute("href", chat)
    # A link off Qualify never rides along.
    page.goto(
        _origin(page)
        + "/whatsapp?tab=numero&sub=pagos&volver="
        + quote("https://example.com/responder?tab=mensajes&chat=x", safe="")
    )
    expect(page).to_have_url(re.compile(r"/chats/ajustes/formas-de-pago$"), timeout=60_000)


# --- the menu ------------------------------------------------------------------------------


def test_the_menu_has_no_whatsapp_entry(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    page.set_viewport_size(DESKTOP)
    page.goto(_origin(page) + "/connections")
    expect(page.get_by_role("heading", level=1, name="Tus redes")).to_be_visible(timeout=60_000)
    nav = page.locator("nav")
    expect(nav.locator('a[href="/whatsapp"]')).to_have_count(0)
    expect(nav.locator("a").filter(has_text=re.compile(r"^\s*WhatsApp\s*$"))).to_have_count(0)
    expect(nav.locator('a[href="/chats/ajustes"]').first).to_be_visible()
    expect(nav.locator('a[href="/whatsapp/promociones"]').first).to_be_visible()
    # The phone's «Más» drawer lists the same entries: no «WhatsApp» there either.
    page.set_viewport_size(PHONE)
    page.reload()
    more = page.get_by_role("button", name="Más")
    expect(more.first).to_be_visible(timeout=60_000)
    more.first.click()
    expect(page.locator('a[href="/chats/ajustes"]').first).to_be_visible(timeout=30_000)
    expect(page.locator('a[href="/whatsapp"]')).to_have_count(0)


# --- a foreign or junk number id opens nothing ---------------------------------------------


def test_a_foreign_number_opens_nothing(chats_page, app_server, context) -> None:  # noqa: ANN001
    """`?cuenta=` is only taken when it is one of the business's numbers: another
    business's number, or junk, leaves the page on the number it shows without one."""
    from .chat_fixtures import seed_chats, seed_second_number
    from .conftest import _open_business

    page = chats_page
    second = seed_second_number(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)  # noqa: SLF001
    other = _open_business(app_server, context, scopes=None)
    theirs = seed_chats(other._qualify_e2e_tenant_id, other._qualify_e2e_user_id)  # noqa: SLF001
    other.close()
    page.set_viewport_size(DESKTOP)
    selector = page.locator(".q-page-header [role=combobox]").first

    def shown(address: str) -> str:
        page.goto(_origin(page) + address)
        expect(selector).to_be_visible(timeout=60_000)
        page.wait_for_timeout(2_000)
        return selector.inner_text()

    for route in ("/connections/whatsapp/actividad", "/chats/ajustes/whatsapp/codigos-qr"):
        default = shown(route)
        # positive control: my own second number is taken
        assert "+57 311" in shown(f"{route}?cuenta={second['connection']}"), route
        for junk in (theirs["whatsapp_connection"], "<script>", "not-a-uuid"):
            assert shown(f"{route}?cuenta={junk}") == default, (route, junk)
    # The old address with their number lands on the page, which ignores it the same way.
    page.goto(_origin(page) + f"/whatsapp?tab=numero&sub=qr&cuenta={theirs['whatsapp_connection']}")
    expect(page).to_have_url(re.compile(r"/chats/ajustes/whatsapp/codigos-qr\?cuenta="))
    expect(selector).to_be_visible(timeout=60_000)
    page.wait_for_timeout(2_000)
    assert "+57 311" not in selector.inner_text() or "+57 311" in default
    # On «Tus redes», only this business's cards.
    page.goto(_origin(page) + "/connections")
    expect(_number_card(page)).to_be_visible(timeout=60_000)
    expect(page.locator(f'a[href*="{theirs["whatsapp_connection"]}"]')).to_have_count(0)


# --- screenshots ------------------------------------------------------------------------------


@pytest.mark.skipif(not os.environ.get("QUALIFY_E2E_SHOTS"), reason="QUALIFY_E2E_SHOTS not set")
def test_capture_tu_numero_moved(chats_page) -> None:  # noqa: ANN001
    from .chat_fixtures import seed_second_number

    page = chats_page
    seed_second_number(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)  # noqa: SLF001
    out = Path(os.environ["QUALIFY_E2E_SHOTS"])
    out.mkdir(parents=True, exist_ok=True)
    label = os.environ.get("QUALIFY_E2E_SHOTS_LABEL", "shot")
    views = [
        ("tus-redes", "/connections", True),
        ("ajustes-de-chats", "/chats/ajustes", True),
        ("whatsapp", "/whatsapp", False),
        ("perfil", "/whatsapp?tab=numero&sub=perfil", False),
        ("codigos-qr", "/whatsapp?tab=numero&sub=qr", False),
        ("formas-de-pago", "/whatsapp?tab=numero&sub=pagos", False),
        ("actividad", "/whatsapp?tab=numero&sub=actividad", False),
    ]
    report: dict[str, object] = {}
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        page.evaluate(f"localStorage.setItem('theme', '{scheme}')")
        for size_name, size in (("360", PHONE), ("1280", DESKTOP)):
            page.set_viewport_size(size)
            for name, address, both in views:
                if scheme == "dark" and not both:
                    continue
                page.goto(_origin(page) + address)
                expect(page.locator("h1").first).to_be_visible(timeout=60_000)
                page.wait_for_timeout(2_500)
                if name == "tus-redes":
                    toggle = page.get_by_role("button", name="Más detalles")
                    if toggle.count():
                        _number_card(page).get_by_role("button", name="Más detalles").click()
                        page.wait_for_timeout(500)
                key = f"{label}-{name}-{size_name}-{scheme}"
                page.screenshot(path=str(out / f"{key}.png"), full_page=True)
                report[key] = {
                    "url": page.evaluate("location.pathname + location.search"),
                    "h1": page.locator("h1").first.inner_text(),
                    "overflow": page.evaluate(
                        "document.documentElement.scrollWidth > window.innerWidth"
                    ),
                }
    (out / f"{label}-where.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8"
    )
