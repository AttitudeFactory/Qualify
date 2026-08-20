"""Module: Brand Content Engine (/brand, /create, /drafts) — the arepera builds its brand
kit and hits the readiness gate.

Nothing here calls the LLM or R2: "Generar borrador" is never clicked (it is not even
reachable — see the readiness gate), and the kit save is a DB write. The niche content
matters: the kit is filled with the venue's own vocabulary (promo 2x1 queso de mano,
horario, palabras vetadas «gourmet») so the persistence round-trip is checked with real
Spanish text, accents included.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import Persona, area_under_label, goto

GAP_POSITIONING = "Posicionamiento de la marca"
GAP_AUDIENCE = "Audiencia objetivo"
GAP_TONE = "Ejes de tono"
GAP_DO = "Ejemplos de copy que SÍ suenan a la marca"
GAP_DONT = "Ejemplos de copy que NO suenan a la marca"
GAP_CTA = "Patrones de llamado a la acción"
GAP_PALETTE = "Paleta de colores"
GAP_LOGO = "Logo de la marca"
GAP_VOICE = "Perfil de voz aprobado"

BLOCKED_HEADING = "La marca aún no está lista para generar"


def _completeness_pct(page: Page) -> int:
    panel = page.get_by_text("Completitud del sustrato de marca").locator("..").locator("..")
    match = re.search(r"(\d+)\s*%", panel.inner_text())
    assert match, "readiness panel shows a percentage"
    return int(match.group(1))


def _open_section(page: Page, header: str) -> None:
    trigger = page.get_by_role("button", name=header, exact=True)
    if trigger.get_attribute("data-state") != "open":
        trigger.click()


def test_fresh_venue_starts_at_zero_with_every_gap_listed(app: Page) -> None:
    goto(app, "/brand")
    expect(app.get_by_role("heading", name="Brand Kit")).to_be_visible(timeout=20_000)
    expect(app.get_by_text("Completitud del sustrato de marca")).to_be_visible(timeout=20_000)
    assert _completeness_pct(app) == 0
    for gap in (GAP_POSITIONING, GAP_AUDIENCE, GAP_DO, GAP_DONT, GAP_CTA, GAP_VOICE):
        expect(app.get_by_text(gap, exact=True).first).to_be_visible()


def test_create_is_gated_until_the_kit_exists(app: Page) -> None:
    goto(app, "/create")
    expect(app.get_by_role("heading", name="Nuevo encargo")).to_be_visible(timeout=20_000)
    expect(app.get_by_text(BLOCKED_HEADING)).to_be_visible(timeout=20_000)
    expect(
        app.get_by_text(
            "Antes de encargar contenido hay que completar el sustrato: es lo que hace que "
            "cada pieza suene a TU marca."
        )
    ).to_be_visible()
    # The order form — and with it the only button that spends money — is not rendered.
    expect(app.get_by_role("button", name="Generar borrador")).to_have_count(0)


def test_drafts_empty_state_routes_to_create(app: Page) -> None:
    goto(app, "/drafts")
    expect(app.get_by_role("heading", name="Borradores", exact=True)).to_be_visible(timeout=20_000)
    expect(
        app.get_by_text("Cada pieza espera tu revisión: nada sale sin aprobación humana")
    ).to_be_visible()
    expect(app.get_by_text("Todavía no hay borradores")).to_be_visible(timeout=20_000)
    app.get_by_role("button", name="Crear el primero").or_(
        app.get_by_role("link", name="Crear el primero")
    ).first.click()
    expect(app).to_have_url(re.compile(r"/create/?$"), timeout=20_000)
    expect(app.get_by_role("heading", name="Nuevo encargo")).to_be_visible(timeout=20_000)


def test_arepera_fills_and_saves_its_brand_kit(app: Page, food_venue: Persona) -> None:
    brand = food_venue.brand
    goto(app, "/brand")
    expect(app.get_by_text("Completitud del sustrato de marca")).to_be_visible(timeout=20_000)

    # Identidad (open by default)
    app.get_by_placeholder("Qué es la marca y por qué importa").fill(
        f"{brand['name']}: {brand['tagline']}. {brand['offer']}"
    )
    app.get_by_placeholder("A quién le habla").fill(brand["audience"])
    app.get_by_role("combobox").first.click()
    app.get_by_role("option", name="es-VE").click()

    # Voz
    _open_section(app, "Voz")
    formal_casual = app.get_by_role("slider").first
    formal_casual.focus()
    for _ in range(30):
        formal_casual.press("ArrowRight")
    area_under_label(app, "Ejemplos que SÍ suenan a la marca (uno por línea)").fill(
        "¿Ya probaste la reina pepiada de Doña Carmen? Se acaba a las 9.\n"
        "Martes de 2x1 en queso de mano: trae al compa."
    )
    area_under_label(app, "Ejemplos que NO suenan a la marca (uno por línea)").fill(
        "Descubra una experiencia culinaria gourmet inigualable.\n"
        "Nuestro portafolio de productos premium."
    )
    area_under_label(app, "Patrones de llamado a la acción (uno por línea)").fill(
        "Pásate hoy por el Korner Club\nEscríbenos por WhatsApp y te la tenemos lista"
    )

    # Visual
    _open_section(app, "Visual")
    app.get_by_placeholder("#0A3D2E, #F2C94C").fill("#F2C94C, #8B1E1E, #1B1B1B")

    # Restricciones
    _open_section(app, "Restricciones")
    area_under_label(app, "Palabras vetadas (una por línea)").fill(
        brand["words_to_avoid"].replace(", ", "\n")
    )
    area_under_label(app, "Claims prohibidos (uno por línea)").fill(
        "la mejor arepa de Venezuela\nsin grasa"
    )

    app.get_by_role("button", name="Guardar kit").click()
    expect(app.get_by_text("Brand kit guardado.")).to_be_visible(timeout=20_000)

    # Readiness moved: the identity/voice/CTA/palette gaps are gone, voice approval and
    # logo remain (they cannot be closed from this form).
    expect(app.get_by_text(GAP_POSITIONING, exact=True)).to_have_count(0)
    expect(app.get_by_text(GAP_AUDIENCE, exact=True)).to_have_count(0)
    expect(app.get_by_text(GAP_DO, exact=True)).to_have_count(0)
    expect(app.get_by_text(GAP_DONT, exact=True)).to_have_count(0)
    expect(app.get_by_text(GAP_CTA, exact=True)).to_have_count(0)
    expect(app.get_by_text(GAP_PALETTE, exact=True)).to_have_count(0)
    expect(app.get_by_text(GAP_VOICE, exact=True).first).to_be_visible()
    expect(app.get_by_text(GAP_LOGO, exact=True).first).to_be_visible()
    assert _completeness_pct(app) >= 80

    # Persistence: a fresh page load reads the kit back from Postgres, accents intact.
    goto(app, "/brand")
    expect(app.get_by_placeholder("Qué es la marca y por qué importa")).to_have_value(
        re.compile(re.escape(brand["tagline"])), timeout=20_000
    )
    expect(app.get_by_placeholder("A quién le habla")).to_have_value(
        re.compile(re.escape("Jugadores de padel"))
    )
    _open_section(app, "Restricciones")
    expect(area_under_label(app, "Palabras vetadas (una por línea)")).to_have_value(
        re.compile("gourmet")
    )
    assert _completeness_pct(app) >= 80


def test_after_the_kit_create_is_still_gated_by_voice_approval(
    app: Page, food_venue: Persona
) -> None:
    """Depends on the kit having been saved (previous test in file order); if it ran
    alone the assertion below is still true, only for more reasons."""
    goto(app, "/create")
    expect(app.get_by_text(BLOCKED_HEADING)).to_be_visible(timeout=20_000)
    expect(app.get_by_text(GAP_VOICE, exact=True).first).to_be_visible()
    expect(app.get_by_role("button", name="Generar borrador")).to_have_count(0)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: /brand renders «Perfil de voz →» linking to /brand/voice, but Qualify.py "
        "registers no such route (404), and the voice-approval UI is never mounted — so "
        "the readiness gate on /create can never be cleared from the product. Flip this "
        "test to passing when the route exists."
    ),
)
def test_voice_profile_link_from_brand_kit_opens_a_page(app: Page) -> None:
    goto(app, "/brand")
    expect(app.get_by_text("Completitud del sustrato de marca")).to_be_visible(timeout=20_000)
    app.get_by_role("button", name="Perfil de voz →").click()
    expect(app).to_have_url(re.compile(r"/brand/voice/?$"), timeout=20_000)
    expect(app.get_by_role("heading", name="Brand Kit")).to_have_count(0)
    expect(app.get_by_text("404", exact=False)).to_have_count(0, timeout=10_000)
    expect(app.get_by_role("heading", name=re.compile("Perfil de voz"))).to_be_visible(
        timeout=20_000
    )
