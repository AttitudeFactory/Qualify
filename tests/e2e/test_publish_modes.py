"""«Publicar ahora» with several photos, in a browser (spec
`docs/mockups/publicar-varias-imagenes.md`, founder decisions 2026-11-12).

Walks the assistant up to «Revisa y publica» and NEVER presses «Publicar»: the business
has an Instagram connection seeded without a credential, and the run itself (sequence,
keys, «Continuar») is covered offline by `Qualify/test_publish_engine.py`. Checks the
live step count, the three modes, the reorder without dragging («⋯»), the carousel crop
notice, the mural grid, the per-photo descriptions, and the tab title after reaching
`/publish` from «Por aprobar» through the menu (no reload).

Screenshots at phone width (375) and desktop go to `QUALIFY_E2E_SHOTS` when it is set.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from .conftest import expect

_SHOTS = os.environ.get("QUALIFY_E2E_SHOTS", "")


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"), full_page=True)


def _photos(tmp_path: Path) -> list[Path]:
    """Three small JPEGs: square, vertical, square — so the carousel's crop notice shows
    once the vertical one leads."""
    image = pytest.importorskip("PIL.Image")
    out = []
    for name, size, colour in (
        ("cuadrada-1.jpg", (600, 600), (18, 165, 148)),
        ("vertical-2.jpg", (600, 900), (214, 64, 159)),
        ("cuadrada-3.jpg", (600, 600), (62, 99, 221)),
    ):
        path = tmp_path / name
        image.new("RGB", size, colour).save(path, "JPEG")
        out.append(path)
    return out


def _counter(page, text: str) -> None:  # noqa: ANN001
    expect(page.locator(".q-step-head")).to_contain_text(text)


def _title(page, text: str) -> None:  # noqa: ANN001
    expect(page.locator("h1.q-step-title")).to_have_text(text)


def _next(page) -> None:  # noqa: ANN001
    page.locator(".q-step-primary").click()


@pytest.mark.parametrize("width", [375, 1280])
def test_several_photos_walk_to_the_review_without_publishing(
    pre_fase_c_page,  # noqa: ANN001 — a Playwright Page with an Instagram account
    app_server: str,
    tmp_path: Path,
    width: int,
) -> None:
    page = pre_fase_c_page
    page.set_viewport_size({"width": width, "height": 900})
    tag = f"{width}"

    # Reached from «Por aprobar» through the menu: the tab names this page (spec §6).
    page.goto(f"{app_server}/drafts")
    if width >= 768:
        page.locator('nav[aria-label="Secciones"] a[href="/publish"]').click()
    else:
        page.locator(".q-bottom-more").click()
        page.locator('nav[aria-label="Secciones"] a[href="/publish"]').click()
    expect(page).to_have_url(re.compile(r"/publish"), timeout=60_000)
    # «Qualify · Publicar ahora», with the business first once logged in (pending_vm)
    expect(page).to_have_title(re.compile(r"Publicar ahora"), timeout=15_000)
    assert "Por aprobar" not in page.title()

    _title(page, "¿Qué vas a publicar?")
    _counter(page, "Paso 1 de 3")
    page.locator("#publish-gallery-root input[type=file]").set_input_files(
        [str(p) for p in _photos(tmp_path)]
    )
    expect(page.locator("#publish-gallery-root .q-pub-tile")).to_have_count(3, timeout=30_000)
    _counter(page, "Paso 1 de 4")  # M is live: the order step appeared
    expect(
        page.get_by_text("En el paso siguiente eliges si salen juntas o una por una.")
    ).to_be_visible()
    _shot(page, f"publicar-1-galeria-{tag}")

    expect(page.get_by_text("Ideas para tu próxima publicación")).to_be_visible()
    _next(page)
    _title(page, "¿Cómo salen?")
    expect(page.get_by_text("Ideas para tu próxima publicación")).to_have_count(0)
    for name in ("Juntas en un carrusel", "Una por una", "Como historias"):
        expect(page.get_by_role("radio", name=re.compile(name))).to_be_visible()
    expect(page.get_by_role("radio", name=re.compile("Juntas en un carrusel"))).to_have_attribute(
        "aria-checked", "true"
    )
    _shot(page, f"publicar-2-como-{tag}")

    # Carousel order: «⋯ › Primero» on the vertical photo — the crop notice appears.
    _next(page)
    _title(page, "Elige el orden del carrusel")
    expect(page.get_by_text("Portada")).to_be_visible()
    page.get_by_role("button", name="Más opciones de Foto 2").click()
    page.get_by_role("menuitem", name="Primero").click()
    rows = page.locator('[data-rank-group="publish-order"]')
    expect(rows.first).to_contain_text("Foto 2")
    expect(
        page.get_by_text(re.compile(r"Instagram corta todas a la forma de la primera \(vertical\)"))
    ).to_be_visible(timeout=15_000)
    _shot(page, f"publicar-3-carrusel-{tag}")

    # Back to the mode: «Una por una» turns the order step into the profile grid.
    page.locator(".q-step-back").click()
    page.get_by_role("radio", name=re.compile("Una por una")).click()
    _next(page)
    _title(page, "Así se verá tu perfil")
    expect(page.locator('[data-rank-group="publish-mural"]')).to_have_count(3)
    expect(page.locator(".q-pub-mural-before")).to_have_count(0)  # 3 fill a row
    _shot(page, f"publicar-3-mural-{tag}")

    _next(page)
    _title(page, "Revisa y publica")
    _counter(page, "Paso 4 de 4")
    expect(page.get_by_text(re.compile(r"3 publicaciones, una tras otra"))).to_be_visible()
    # named by their place in the mural, as the grid numbers them (UX review)
    expect(page.get_by_text("Publicación 1 de 3")).to_be_visible()
    page.get_by_label("Descripción de la publicación 1 (opcional)").fill("Hoy 2x1")
    page.get_by_role("button", name="Usar este texto en las demás").click()
    expect(page.get_by_label("Descripción de la publicación 3 (opcional)")).to_have_value("Hoy 2x1")
    expect(page.locator(".q-step-primary")).to_have_text("Publicar las 3")
    _shot(page, f"publicar-5-revisa-{tag}")
    # never pressed: nothing is published from a test


def test_whatsapp_is_not_offered_and_one_photo_is_three_steps(
    pre_fase_c_page,  # noqa: ANN001
    app_server: str,
    tmp_path: Path,
) -> None:
    page = pre_fase_c_page
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(f"{app_server}/publish")
    page.locator("#publish-gallery-root input[type=file]").set_input_files(
        [str(_photos(tmp_path)[0])]
    )
    _counter(page, "Paso 1 de 3")
    _next(page)
    _title(page, "¿Cómo sale?")
    page.get_by_role("radio", name=re.compile("Historia")).click()
    _next(page)
    _title(page, "Revisa y publica")
    expect(page.locator(".q-step-primary")).to_have_text("Publicar historia")
    # the assistant (not the menu) never offers WhatsApp
    expect(page.locator(".q-step-head, [role=radiogroup]").get_by_text("WhatsApp")).to_have_count(0)
    _shot(page, "publicar-historia-375")
