"""m-25017861 (BU-A9, decision D1): «Ajustes de chats», apart from the messages.

In a browser: the hub's three cards (Para todos tus chats · WhatsApp · Instagram) with
the menu entry lit; an Instagram row opens its «Preguntas iniciales» in place, with the
line «Lo que tu cliente puede tocar al abrir el chat»; the Instagram chat's «⋯» ›
«Ajustes de este canal» lands there; the menu's old address lands in «Ajustes de chats ›
WhatsApp»; the messages screens no longer carry those settings; a business with no
accounts sees what to connect. Pictures at 360 and 1280 px, light and dark, when
`QUALIFY_E2E_SHOTS` names a folder.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .conftest import expect

_SHOTS = os.environ.get("QUALIFY_E2E_SHOTS", "")
_HUB = "/chats/ajustes"
_LINE = "Lo que tu cliente puede tocar al abrir el chat"


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"), full_page=True)


def _menu(page):  # noqa: ANN001, ANN202
    return page.locator('nav[aria-label="Secciones"]')


def _theme(page, mode: str) -> None:  # noqa: ANN001
    """Light or dark through the header's own toggle (the app starts dark)."""
    is_dark = page.evaluate("document.documentElement.classList.contains('dark')")
    if is_dark != (mode == "dark"):
        page.locator(".q-page-header button").last.click()
        page.wait_for_function(
            "want => document.documentElement.classList.contains('dark') === want",
            arg=mode == "dark",
        )
    page.wait_for_timeout(400)


def _no_sideways_scroll(page) -> None:  # noqa: ANN001
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_the_hub_has_three_cards_on_phone_and_desktop(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    base = re.match(r"https?://[^/]+", page.url)[0]
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{base}/")
    _menu(page).locator(f'a[href="{_HUB}"]').click()
    expect(page).to_have_url(f"{base}{_HUB}")
    expect(page.get_by_role("heading", level=1, name="Ajustes de chats")).to_be_visible()
    expect(page).to_have_title(re.compile("Ajustes de chats"))
    lit = _menu(page).locator('[aria-current="page"]')
    expect(lit).to_have_count(1)
    expect(lit).to_contain_text("Ajustes de chats")
    for heading in ("Para todos tus chats", "WhatsApp", "Instagram"):
        expect(page.get_by_role("heading", level=2, name=heading)).to_be_visible(timeout=60_000)
    main = page.locator("main")
    for row in ("Mensajes guardados", "Formas de pago", "Cómo llegar", "Tu menú de bienvenida"):
        expect(main.get_by_role("link", name=re.compile(row))).to_be_visible()
    # One WhatsApp row (UX U3); «Preguntas iniciales» is Instagram's only.
    expect(main.get_by_role("button", name=re.compile("Preguntas iniciales"))).to_have_count(1)
    expect(main.get_by_role("link", name=re.compile("Preguntas iniciales"))).to_have_count(0)
    expect(main.get_by_role("link", name="Ir a Tus redes")).to_be_visible()
    for link in ("Ir a Por responder", "Ir a Tus redes"):  # N12: 44 px targets
        box = main.get_by_role("link", name=re.compile(link)).first.bounding_box()
        assert box and box["height"] >= 44, (link, box)
    expect(main.get_by_role("link", name=re.compile("Ir a Por responder"))).to_have_attribute(
        "href", "/responder"
    )
    expect(page.get_by_text("Respuesta automática")).to_have_count(0)
    page.mouse.move(900, 450)
    for mode in ("dark", "light"):
        _theme(page, mode)
        _shot(page, f"hub-1280-{mode}-v2")

    page.set_viewport_size({"width": 360, "height": 780})
    page.reload()
    expect(page.get_by_role("heading", level=2, name="Instagram")).to_be_visible(timeout=60_000)
    _no_sideways_scroll(page)
    for mode in ("dark", "light"):
        _theme(page, mode)
        _shot(page, f"hub-360-{mode}-v2")


def test_an_instagram_row_opens_its_starter_questions_here(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    base = re.match(r"https?://[^/]+", page.url)[0]
    page.set_viewport_size({"width": 360, "height": 780})
    page.goto(f"{base}{_HUB}")
    row = page.locator("main").get_by_role("button", name=re.compile("Preguntas iniciales"))
    expect(row).to_be_visible(timeout=60_000)
    drawer = page.get_by_role("dialog")
    for mode in ("dark", "light"):
        _theme(page, mode)  # before opening: the drawer's overlay covers the toggle
        row.click()
        expect(drawer).to_be_visible()
        expect(drawer.get_by_text(_LINE)).to_be_visible()
        page.wait_for_timeout(800)  # the slide-in ends (UX U1 looked mid-animation)
        box = drawer.bounding_box()
        assert box and box["x"] == 0 and box["width"] == 360, box  # the whole phone width
        for name in ("Agregar pregunta", "Publicar en Instagram", "Guardar"):
            target = drawer.get_by_role("button", name=name).bounding_box()
            assert target and target["x"] + target["width"] <= 360, (name, target)
        _shot(page, f"instagram-preguntas-360-{mode}-v2")
        page.keyboard.press("Escape")
        expect(drawer).to_have_count(0)
    expect(page).to_have_url(f"{base}{_HUB}")


def test_the_instagram_chats_settings_link_lands_there(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats  # noqa: SLF001
    base = re.match(r"https?://[^/]+", page.url)[0]
    page.set_viewport_size({"width": 1280, "height": 900})
    for mode in ("dark", "light"):
        page.goto(
            f"{base}/responder?tab=mensajes&cuenta={ids['instagram_connection']}"
            f"&chat={ids['instagram_open']}"
        )
        head = page.locator(".q-chat-head").first
        expect(head).to_be_visible(timeout=60_000)
        _theme(page, mode)  # before the drawer: its overlay covers the toggle
        # D1: the messages screen no longer has the «Preguntas iniciales» door.
        main = page.locator("main")
        expect(main.get_by_role("button", name="Preguntas iniciales")).to_have_count(0)
        head.get_by_role("button", name="Más acciones de este chat").click()
        page.get_by_role("menuitem", name="Ajustes de este canal").click()
        expect(page).to_have_url(
            f"{base}/chats/ajustes/instagram?cuenta={ids['instagram_connection']}",
            timeout=60_000,
        )
        drawer = page.get_by_role("dialog")
        expect(drawer).to_be_visible(timeout=60_000)
        expect(drawer.get_by_text(_LINE)).to_be_visible()
        lit = _menu(page).locator('[aria-current="page"]')
        expect(lit).to_contain_text("Ajustes de chats")
        page.wait_for_timeout(500)
        _shot(page, f"instagram-ajustes-de-este-canal-1280-{mode}-v2")


def test_the_menus_old_address_lands_in_ajustes(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats  # noqa: SLF001
    base = re.match(r"https?://[^/]+", page.url)[0]
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{base}/whatsapp?tab=respuesta&cuenta={ids['whatsapp_connection']}&x=1")
    expect(page).to_have_url(
        f"{base}/chats/ajustes/whatsapp?cuenta={ids['whatsapp_connection']}", timeout=60_000
    )
    lit = _menu(page).locator('[aria-current="page"]')
    expect(lit).to_have_count(1)
    expect(lit).to_contain_text("Ajustes de chats")
    expect(page.locator(".q-wa-chats__list")).to_have_count(0)
    expect(page.get_by_role("group", name="Secciones de WhatsApp")).to_have_count(0)
    # The page's name, or the menu's guided steps (they name the way back).
    expect(
        page.get_by_text(re.compile("Tu menú de bienvenida|Ajustes de chats")).first
    ).to_be_visible(timeout=60_000)
    for mode in ("dark", "light"):
        if page.locator(".q-page-header").count():  # the guided frame has no toggle
            _theme(page, mode)
        _shot(page, f"whatsapp-menu-1280-{mode}-v2")
    page.set_viewport_size({"width": 360, "height": 780})
    page.reload()
    expect(page.locator("main").first).to_be_visible(timeout=60_000)
    _no_sideways_scroll(page)
    _shot(page, "whatsapp-menu-360-v2")

    # m-25027373: «Tu número» left the WhatsApp screen — its Estado is the number's
    # card in «Tus redes», where its old address lands.
    page.goto(f"{base}/whatsapp?tab=numero&sub=estado")
    expect(page).to_have_url(f"{base}/connections", timeout=60_000)
    expect(page.get_by_role("group", name="Tu número")).to_have_count(0)
    expect(page.get_by_role("group", name="Secciones de WhatsApp")).to_have_count(0)
    _shot(page, "whatsapp-mensajes-360-despues-v2")


def test_without_accounts_the_hub_says_what_to_connect(signed_up_page, app_server: str) -> None:  # noqa: ANN001
    page = signed_up_page
    page.set_viewport_size({"width": 360, "height": 780})
    page.goto(f"{app_server}{_HUB}")
    expect(page.get_by_text("Todavía no tienes tu número de WhatsApp conectado.")).to_be_visible(
        timeout=60_000
    )
    expect(page.get_by_text("Todavía no tienes una cuenta de Instagram conectada.")).to_be_visible()
    expect(page.get_by_role("link", name="Conectar en Tus redes")).to_have_attribute(
        "href", "/connections"
    )
    # UX U2: without a number, the two rows kept with it are not offered.
    expect(page.get_by_role("link", name=re.compile("Mensajes guardados"))).to_be_visible()
    for gone in ("Formas de pago", "Cómo llegar"):
        expect(page.get_by_role("link", name=re.compile(gone))).to_have_count(0)
    _no_sideways_scroll(page)
    for mode in ("dark", "light"):
        _theme(page, mode)
        _shot(page, f"hub-vacio-360-{mode}-v2")


def _seed_menus(tenant_id, connection_id: str) -> None:  # noqa: ANN001
    """m-25142807: «prueba 2» answering with v2 (v1 published before it, a draft v3 on
    top) and «Navidad» never published. Written straight to the database — publishing
    here is the repository's row update, never a call to WhatsApp."""
    from uuid import UUID

    from qualify_api.whatsapp.menus import PostgresMenuRepository
    from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU

    from Qualify.whatsapp_menu_provider import create_menu, number_scope, save_version
    from Qualify.whatsapp_menu_vm import TEMPLATE_EMPTY

    repo = PostgresMenuRepository()
    scope = number_scope(tenant_id, UUID(connection_id))

    def payload(n: int) -> dict:
        data = BIANKI_DEMO_MENU.model_dump(mode="json")
        data["entry"]["welcome"] = f"Hola, esta es la versión {n} del menú."
        return data

    def menu(name: str, versions: int, live: int | None) -> None:
        created = create_menu(tenant_id, scope, name, TEMPLATE_EMPTY, repo=repo)
        menu_id = UUID(created.summary.menu_id)
        for n in range(1, versions + 1):
            saved = save_version(tenant_id, scope, menu_id, payload(n), repo=repo)
            if live is not None and n <= live:
                repo.publish_version(
                    tenant_id=tenant_id,
                    menu_id=menu_id,
                    version_id=UUID(saved.versions[0].version_id),
                    user_id=None,
                )

    menu("Navidad", 1, None)
    menu("prueba 2", 3, 2)


def _pick(page, name: str) -> None:  # noqa: ANN001
    page.get_by_role("combobox", name="Menú y versión").click()
    page.get_by_role("option", name=re.compile(name)).click()


def test_the_welcome_menu_is_one_box(chats_page) -> None:  # noqa: ANN001
    """m-25142807 (option A): one select «Menú y versión» over every menu's versions,
    what is picked is what the editor shows, one pause switch that asks first."""
    page = chats_page
    ids = page._qualify_e2e_chats  # noqa: SLF001
    _seed_menus(page._qualify_e2e_tenant_id, ids["whatsapp_connection"])  # noqa: SLF001
    base = re.match(r"https?://[^/]+", page.url)[0]
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{base}/chats/ajustes/whatsapp?cuenta={ids['whatsapp_connection']}")
    box = page.locator("#whatsapp-menu-toolbar")
    expect(box.get_by_role("heading", name="Tu menú de bienvenida")).to_be_visible(timeout=60_000)
    select = page.get_by_role("combobox", name="Menú y versión")
    expect(select).to_have_count(1)
    # The newest saved version opens first: the draft on top of the live one.
    expect(select).to_contain_text("prueba 2 · Cambios sin publicar", timeout=30_000)
    for gone in ("Elige qué menú ver", "Pausar el menú en tu WhatsApp", "Editando a partir"):
        expect(page.get_by_text(gone)).to_have_count(0)
    expect(page.get_by_role("button", name="Editar", exact=True)).to_have_count(0)
    expect(page.get_by_role("switch", name="Responde en tu WhatsApp")).to_be_checked()
    _shot(page, "menu-una-caja-1280-borrador")

    # Every menu is a group; the live version is marked in words, open and closed.
    select.click()
    expect(page.get_by_role("group", name="Navidad")).to_be_visible()
    page.get_by_role("option", name=re.compile(r"^Versión 2 · .* · Activo en tu WhatsApp$")).click()
    expect(select).to_contain_text("prueba 2 · Versión 2")
    expect(select).to_contain_text("Activo en tu WhatsApp")
    expect(box.get_by_text("Es la versión que tienen tus clientes.")).to_be_visible()
    expect(page.get_by_text("Hola, esta es la versión 2 del menú.").first).to_be_visible()
    _shot(page, "menu-una-caja-1280-activa")

    # An older version: the editor shows it, and the way back is offered.
    _pick(page, r"^Versión 1 · ")
    expect(select).to_contain_text("prueba 2 · Versión 1")
    expect(
        box.get_by_text("Tus clientes tienen «prueba 2 · Versión 2». Esta todavía no les llega.")
    ).to_be_visible()
    expect(box.get_by_role("button", name="Volver a la versión 1")).to_be_visible()
    expect(page.get_by_text("Hola, esta es la versión 1 del menú.").first).to_be_visible()
    _shot(page, "menu-una-caja-1280-anterior")

    page.set_viewport_size({"width": 375, "height": 812})
    page.wait_for_timeout(500)
    _no_sideways_scroll(page)
    _shot(page, "menu-una-caja-375-anterior")
    _pick(page, r"^Versión 2 · ")
    expect(box.get_by_text("Es la versión que tienen tus clientes.")).to_be_visible()
    _no_sideways_scroll(page)
    _shot(page, "menu-una-caja-375-activa")

    # Pausing asks first, then the switch says «En pausa».
    page.get_by_role("switch", name="Responde en tu WhatsApp").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("Pausar «prueba 2»")
    dialog.get_by_role("button", name="Sí, pausar").click()
    expect(page.get_by_role("switch", name="En pausa")).not_to_be_checked(timeout=30_000)
    expect(select).to_contain_text("En pausa")
    _no_sideways_scroll(page)
    _shot(page, "menu-una-caja-375-pausa")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.wait_for_timeout(500)
    _shot(page, "menu-una-caja-1280-pausa")
