"""Module: mentions dashboard (`/`) — still the exploratory SQLite-seeded screen, so the
tests pin only its shell and its client-side filter behaviour, not the numbers.

Known limitation recorded here on purpose: this screen is NOT tenant-scoped (plain
`get_session()` + `seed_if_empty()`), so the arepera sees the same seed rows as any other
business. When Fase 1 Parte 3 lands and it becomes tenant-scoped, the fresh-tenant test
below must flip to an empty state.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from .conftest import goto

STAT_CARDS = ["Total menciones", "Positivas", "Neutras", "Negativas"]
COLUMNS = ["Fecha", "Plataforma", "Marca", "Creador", "Caption", "Sentiment", "Vistas", "Likes"]


def _rows(page: Page):
    return page.locator("table tbody tr")


def test_dashboard_shell(app: Page) -> None:
    goto(app, "/")
    expect(app.get_by_role("heading", name="Dashboard de menciones")).to_be_visible(timeout=20_000)
    expect(app.get_by_text("Menciones de marca en TikTok e Instagram Reels")).to_be_visible()
    for card in STAT_CARDS:
        expect(app.get_by_text(card, exact=True)).to_be_visible()
    for column in COLUMNS:
        expect(app.get_by_role("columnheader", name=column, exact=True)).to_be_visible()


def test_fresh_food_venue_sees_seeded_rows_not_an_empty_table(app: Page) -> None:
    """Documents the current (non-tenant-scoped, auto-seeded) behaviour. Flip when the
    dashboard is wired to the analytical plane."""
    goto(app, "/")
    expect(_rows(app).first).to_be_visible(timeout=20_000)
    assert _rows(app).count() > 0


def test_search_box_narrows_the_table_and_clearing_restores_it(app: Page) -> None:
    goto(app, "/")
    expect(_rows(app).first).to_be_visible(timeout=20_000)
    total = _rows(app).count()

    search = app.get_by_placeholder("Buscar por caption o creador...")
    search.fill("zzz-nada-que-coincida-zzz")
    expect(_rows(app)).to_have_count(0, timeout=10_000)

    search.fill("")
    expect(_rows(app)).to_have_count(total, timeout=10_000)


def test_search_matches_creator_handle(app: Page) -> None:
    goto(app, "/")
    expect(_rows(app).first).to_be_visible(timeout=20_000)
    handle = _rows(app).first.locator("td").nth(3).inner_text().strip()
    assert handle, "seed rows always carry a creator handle"
    term = handle.lstrip("@")[:6]
    app.get_by_placeholder("Buscar por caption o creador...").fill(term)
    # Poll until the filter has been applied: every remaining row matches the term.
    expect(_rows(app).filter(has_not_text=re.compile(re.escape(term), re.I))).to_have_count(
        0, timeout=10_000
    )
    expect(_rows(app).first).to_be_visible()
