"""Module: Vitrina de locales — the niche's own screen: a food-stall picker for a
gastronomic fair (Korner Club demo). Zero backend, so this is the purest UI check in the
suite: selection state, day switch, chart remount, disclaimer, and the disabled CTA.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from .conftest import goto

SECTIONS = [
    "Locales disponibles",
    "Quién pasa por esta puerta, y a qué hora",
    "Qué público ya viene",
    "Cocina caliente",
    "Lo que nadie está vendiendo",
    "Qué venden los vecinos",
    "¿Te sirve este local?",
]
NEIGHBOUR_COLUMNS = ["Dist.", "Local", "Rubro", "Precio", "Horario", "Qué vende"]


def _bars(page: Page):
    return page.locator("svg.recharts-surface path.recharts-rectangle")


def test_vitrina_renders_the_full_demo_with_its_disclaimer(app: Page) -> None:
    goto(app, "/vitrina")
    expect(app.get_by_role("heading", name="Korner Club")).to_be_visible(timeout=20_000)
    expect(app.get_by_text("demo", exact=True)).to_be_visible()
    expect(
        app.get_by_text(
            "Comida · Bar · Canchas de padel y arena · Av. Los Agustinos, San Cristóbal"
        )
    ).to_be_visible()
    expect(
        app.get_by_text("Demostración. Los números son ilustrativos", exact=False)
    ).to_be_visible()
    for section in SECTIONS:
        expect(app.get_by_role("heading", name=section, exact=True)).to_be_visible()
    for column in NEIGHBOUR_COLUMNS:
        expect(app.get_by_role("columnheader", name=column, exact=True)).to_be_visible()
    for stat in ("Visitantes por semana", "Locales", "Ticket promedio", "Hora pico"):
        expect(app.get_by_text(stat, exact=True).first).to_be_visible()
    expect(app.get_by_role("button", name="Reservar visita")).to_be_disabled()


def test_default_selection_is_local_04_and_the_ficha_follows_the_click(app: Page) -> None:
    goto(app, "/vitrina")
    expect(app.get_by_role("heading", name="Local 04")).to_have_count(2, timeout=20_000)
    # ficha header echoes the selected local's numbers
    expect(app.get_by_text("18 m² · $180 / mes · 82% del flujo del club")).to_be_visible()

    app.get_by_role("heading", name="Local 07").click()
    expect(app.get_by_text("12 m² · $150 / mes · 100% del flujo del club")).to_be_visible(
        timeout=10_000
    )
    expect(app.get_by_role("heading", name="Local 07")).to_have_count(2)
    expect(app.get_by_role("heading", name="Local 04")).to_have_count(1)
    expect(
        app.get_by_text("Pasa todo el mundo, pero solo sirve para producto frío o terminado.")
    ).to_be_visible()

    app.get_by_role("heading", name="Local 09").click()
    expect(app.get_by_text("26 m² · $210 / mes · 46% del flujo del club")).to_be_visible(
        timeout=10_000
    )
    expect(app.get_by_text("Vigente hasta 03/2027.")).to_be_visible()


def test_hot_kitchen_verdict_never_renders_unknown_as_no(app: Page) -> None:
    """Three states by design: «desconocido» must surface as «Sin dato», not «No»."""
    goto(app, "/vitrina")
    app.get_by_role("heading", name="Local 04").first.click()
    expect(app.get_by_text("Nadie lo tramitó todavía.")).to_be_visible(timeout=10_000)
    row = app.get_by_text("Concepto sanitario", exact=True).locator("..").locator("..")
    expect(row).to_contain_text(re.compile("Sin dato|desconocido", re.IGNORECASE))
    expect(row).not_to_contain_text(re.compile(r"\bNo\b"))


def test_day_switch_changes_peak_hour_note_and_redraws_the_chart(app: Page) -> None:
    goto(app, "/vitrina")
    expect(app.get_by_text("de lunes a viernes", exact=False).first).to_be_visible(timeout=20_000)
    expect(app.locator("svg.recharts-surface").first).to_be_visible(timeout=20_000)
    expect(_bars(app)).to_have_count(14, timeout=10_000)  # 10:00 … 23:00

    app.get_by_role("radio", name="Fin de semana").or_(
        app.get_by_text("Fin de semana", exact=True)
    ).first.click()
    expect(app.get_by_text("sábado y domingo", exact=False).first).to_be_visible(timeout=10_000)
    expect(app.locator("svg.recharts-surface").first).to_be_visible()
    # Same 14 hours, new heights: the chart is remounted (keyed), not lost.
    expect(_bars(app)).to_have_count(14, timeout=10_000)
    expect(app.get_by_text(re.compile(r"Pico\s+\d{2}:00"))).to_be_visible()
