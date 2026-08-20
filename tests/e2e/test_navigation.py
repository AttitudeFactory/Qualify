"""Module: shell (sidebar / topbar / titles) — every module is reachable from the sidebar
and identifies itself, for a fresh food-venue tenant."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import Persona, goto

# (sidebar label, href, page heading, <title>)
NAV = [
    ("Menciones", "/", "Dashboard de menciones", "Qualify · Menciones"),
    ("Conexiones", "/connections", "Cuentas conectadas", "Qualify · Conexiones"),
    ("Publicar", "/publish", "Publicar", "Qualify · Publicar"),
    ("Marca", "/brand", "Brand Kit", "Qualify · Brand Kit"),
    ("Crear pieza", "/create", "Nuevo encargo", "Qualify · Nuevo encargo"),
    ("Borradores", "/drafts", "Borradores", "Qualify · Borradores"),
    ("Contenido", "/inbox", "Contenido de Instagram", "Qualify · Contenido"),
    ("Leads", "/leads", "Leads", "Qualify · Leads"),
    ("Clarity", "/clarity", "Clarity", "Qualify · Clarity"),
    ("Vitrina", "/vitrina", "Korner Club", "Qualify · Vitrina de locales"),
]

COMING_SOON = ["Creadores", "Señales", "Configuración"]


@pytest.mark.parametrize(("label", "href", "heading", "title"), NAV, ids=[n[1] for n in NAV])
def test_sidebar_link_reaches_module(
    app: Page, label: str, href: str, heading: str, title: str
) -> None:
    goto(app, "/")
    sidebar_link = app.get_by_role("link", name=label, exact=True).first
    expect(sidebar_link).to_have_attribute("href", href)
    sidebar_link.click()
    expect(app.get_by_role("heading", name=heading, exact=True).first).to_be_visible(timeout=20_000)
    expect(app).to_have_title(title, timeout=20_000)


def test_coming_soon_entries_are_visible_but_inert(app: Page) -> None:
    """Creadores / Señales / Configuración are announced, badged «pronto», and are NOT
    links — nothing to click, nowhere to go."""
    goto(app, "/")
    for label in COMING_SOON:
        expect(app.get_by_text(label, exact=True).first).to_be_visible()
        expect(app.get_by_role("link", name=label, exact=True)).to_have_count(0)
    expect(app.get_by_text("pronto", exact=True)).to_have_count(len(COMING_SOON))


def test_topbar_names_the_business_on_the_dashboard(app: Page, food_venue: Persona) -> None:
    goto(app, "/")
    expect(app.get_by_text(food_venue.business_name, exact=True).first).to_be_visible(
        timeout=20_000
    )
    expect(app.get_by_role("button", name="Salir")).to_be_visible()
