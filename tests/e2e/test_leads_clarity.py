"""Modules: leads and Clarity — fresh food venue, DB-only screens.

Clarity's "Actualizar desde Clarity" is the ONE control on this page that calls a
vendor (Microsoft Clarity Data Export API, 10/day quota); it must be disabled while the
project is unconfigured and the suite never clicks it.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from .conftest import goto

LEAD_COLUMNS = ["Nombre", "WhatsApp", "Interés", "Fuente", "Datos extra", "Registro"]


def test_leads_empty_state_for_a_fresh_venue(app: Page) -> None:
    goto(app, "/leads")
    expect(app.get_by_role("heading", name="Leads", exact=True)).to_be_visible(timeout=20_000)
    expect(
        app.get_by_text("Personas captadas por tu funnel, con su consentimiento registrado")
    ).to_be_visible()
    expect(app.get_by_text("0 leads", exact=True)).to_be_visible(timeout=20_000)
    expect(app.get_by_text("Todavía no hay leads")).to_be_visible()
    expect(
        app.get_by_text(
            "Comparte el formulario de captura de este negocio: cada registro con "
            "consentimiento aparecerá aquí."
        )
    ).to_be_visible()


def test_clarity_unconfigured_state_and_the_vendor_button_is_disabled(app: Page) -> None:
    goto(app, "/clarity")
    expect(app.get_by_role("heading", name="Clarity", exact=True)).to_be_visible(timeout=20_000)
    expect(
        app.get_by_text("Comportamiento web del sitio de este negocio, vía Microsoft Clarity")
    ).to_be_visible()
    expect(app.get_by_role("heading", name="Proyecto de Clarity")).to_be_visible(timeout=20_000)
    expect(app.get_by_text("sin configurar", exact=True)).to_be_visible()
    expect(app.get_by_placeholder("ID de proyecto (p. ej. abc123xyz)")).to_be_visible()
    expect(app.get_by_placeholder("Token de la Data Export API")).to_have_attribute(
        "type", "password"
    )
    expect(app.get_by_role("button", name="Actualizar desde Clarity")).to_be_disabled()
    expect(app.get_by_text("Todavía no hay datos de Clarity")).to_be_visible()
    expect(app.get_by_text("actualizaciones restantes hoy", exact=False)).to_be_visible()
