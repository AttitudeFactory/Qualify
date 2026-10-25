"""m-24852260 (PASOS-13): the menu always shows which module you are in, in a browser.

Clicking through every sidebar entry (no reload) lights that entry and only that one —
`aria-current="page"` — and browser back/forward keep it in step with the address. «/»
lights «Inicio»; a ficha lights «Por aprobar», or «Tu semana» when opened from there. On
a phone (≤ 640 px) the bottom bar marks its own cell, or «Más» for the rest. The full
route → entry map is covered offline by `Qualify/test_nav_active.py`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .conftest import expect

_SHOTS = os.environ.get("QUALIFY_E2E_SHOTS", "")

# Sidebar entries in visual order (label, route) — `Qualify/ui/layout.py` NAV_ITEMS.
_ENTRIES = [
    ("Inicio", "/"),
    ("Por responder", "/responder"),
    ("WhatsApp", "/whatsapp"),
    ("Crear publicación", "/create"),
    ("Por aprobar", "/drafts"),
    ("Tu semana", "/planner"),
    ("Publicar ahora", "/publish"),
    ("Resultados", "/resultados"),
    ("Creadores", "/creadores"),
    ("Oportunidades", "/signals"),
    ("Tu marca", "/brand/kit"),
    ("Tus productos", "/catalog"),
    ("Tus redes", "/connections"),
    ("Configuración", "/settings"),
]


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"))


def _url(app_server: str, route: str) -> re.Pattern[str]:
    return re.compile(re.escape(app_server + route) + r"(\?.*)?$")


_ACTIVE_COLOUR_DIFFERS = """() => {
  const nav = document.querySelector('nav[aria-label="Secciones"]');
  const rows = nav ? [...nav.querySelectorAll('.q-nav-item')] : [];
  const lit = rows.find(r => r.closest('[aria-current="page"]'));
  const rest = rows.find(r => !r.closest('[aria-current="page"]'));
  if (!lit || !rest) return false;
  const a = getComputedStyle(lit).color, b = getComputedStyle(rest).color;
  return a !== '' && b !== '' && a !== b;
}"""


def _expect_sidebar_lit(page, route: str) -> None:  # noqa: ANN001
    menu = page.locator('nav[aria-label="Secciones"]')
    expect(menu.locator(f'a[href="{route}"]')).to_have_attribute("aria-current", "page")
    expect(menu.locator('[aria-current="page"]')).to_have_count(1)
    row = menu.locator('[aria-current="page"] .q-nav-item')
    expect(row).to_have_css("font-weight", "600")
    # Never the capsule alone: the active row's colour is not the resting rows' grey.
    page.wait_for_function(_ACTIVE_COLOUR_DIFFERS, timeout=5_000)


# The glass capsule of the active row's island sits on that row (pointer off the menu).
_CAPSULE_ON_ACTIVE = """() => {
  const row = document.querySelector('.q-sidebar [aria-current="page"] .q-nav-item');
  const blob = row && row.closest('.q-island').querySelector(':scope > .q-glass-blob');
  if (!blob) return false;
  const r = row.getBoundingClientRect(), b = blob.getBoundingClientRect();
  const y = b.top + b.height / 2;
  return b.height > 0 && y >= r.top && y <= r.bottom;
}"""


def _expect_capsule_on_active(page) -> None:  # noqa: ANN001
    page.mouse.move(900, 450)  # off the menu: a hovered row would hold the capsule
    page.wait_for_function(_CAPSULE_ON_ACTIVE, timeout=5_000)


def _expect_bottom_lit(page, label: str) -> None:  # noqa: ANN001
    bar = page.locator('nav[aria-label="Accesos rápidos"]')
    expect(bar.locator('.q-bottom-cell[data-active="true"]')).to_have_count(1)
    expect(bar.locator('.q-bottom-cell[data-active="true"] .q-bottom-label')).to_have_text(label)


def test_every_sidebar_entry_lights_itself_and_history_follows(
    signed_up_page,  # noqa: ANN001 — a Playwright Page
    app_server: str,
) -> None:
    page = signed_up_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{app_server}/")
    _expect_sidebar_lit(page, "/")
    _shot(page, "menu-inicio")

    menu = page.locator('nav[aria-label="Secciones"]')
    for _label, route in _ENTRIES[1:]:
        menu.locator(f'a[href="{route}"]').click()
        expect(page).to_have_url(_url(app_server, route), timeout=60_000)
        _expect_sidebar_lit(page, route)

    # Back and forward walk the same entries, and the capsule follows.
    for _label, route in reversed(_ENTRIES[:-1]):
        page.go_back()
        expect(page).to_have_url(_url(app_server, route), timeout=60_000)
        _expect_sidebar_lit(page, route)
        _expect_capsule_on_active(page)
    page.go_forward()
    expect(page).to_have_url(_url(app_server, _ENTRIES[1][1]), timeout=60_000)
    _expect_sidebar_lit(page, _ENTRIES[1][1])
    _expect_capsule_on_active(page)

    # Zen (icons only): the same entries light.
    page.locator("#q-zen-toggle").click()
    for route in ("/planner", "/", "/brand/kit"):
        menu.locator(f'a[href="{route}"]').click()
        expect(page).to_have_url(_url(app_server, route), timeout=60_000)
        _expect_sidebar_lit(page, route)
    _shot(page, "menu-zen-tu-marca")
    page.locator("#q-zen-toggle").click()


def test_a_ficha_lights_its_module(
    signed_up_page,  # noqa: ANN001 — a Playwright Page
    app_server: str,
) -> None:
    page = signed_up_page
    page.set_viewport_size({"width": 1280, "height": 900})
    ficha = "/drafts/00000000-0000-4000-8000-000000000123"
    page.goto(f"{app_server}{ficha}")
    expect(page).to_have_url(_url(app_server, ficha), timeout=60_000)
    _expect_sidebar_lit(page, "/drafts")
    page.goto(f"{app_server}{ficha}?desde=semana&semana=2026-10-19&vista=lista")
    _expect_sidebar_lit(page, "/planner")
    _shot(page, "menu-ficha-desde-semana")


def test_the_phone_bar_marks_its_cell_or_more(
    signed_up_page,  # noqa: ANN001 — a Playwright Page
    app_server: str,
) -> None:
    page = signed_up_page
    page.set_viewport_size({"width": 360, "height": 780})
    page.goto(f"{app_server}/")
    _expect_bottom_lit(page, "Inicio")
    _shot(page, "barra-inicio")
    bar = page.locator('nav[aria-label="Accesos rápidos"]')
    for label, route in (
        ("Por responder", "/responder"),
        ("Crear", "/create"),
        ("Tu semana", "/planner"),
    ):
        bar.locator(f'a[href="{route}"]').click()
        expect(page).to_have_url(_url(app_server, route), timeout=60_000)
        _expect_bottom_lit(page, label)
    page.goto(f"{app_server}/brand/kit")
    _expect_bottom_lit(page, "Más")
    page.go_back()
    _expect_bottom_lit(page, "Tu semana")

    # A ficha: «Más» on the bar, and the drawer it opens shows «Por aprobar» lit.
    page.goto(f"{app_server}/drafts/00000000-0000-4000-8000-000000000123")
    _expect_bottom_lit(page, "Más")
    page.locator(".q-bottom-more").click()
    _expect_sidebar_lit(page, "/drafts")
    _shot(page, "barra-mas-por-aprobar")
