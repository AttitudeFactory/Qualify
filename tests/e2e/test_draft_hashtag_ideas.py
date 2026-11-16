"""m-25032581 (UX review): the draft editor's «Sugeridas para tu texto» on a phone and a
computer — «Mejor» only where the rule puts it, each idea's reason opened by touch and by
keyboard, the chip's tap still adding the etiqueta, nothing wider than the screen.

The AI answers from `stubs/sitecustomize.py` (no paid call): two watched tags the text
does not name (`carne`, `pollo`) come first and must never carry «Mejor».
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from .conftest import expect
from .test_piece_ad_destination import _business, _seed_piece

_BEST = ["recienhecho", "cafeteria", "desayuno", "barrio", "cafedeespecialidad"]


def _shot(page: Any, name: str) -> None:
    target = os.environ.get("QUALIFY_E2E_SHOTS")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(target) / name), full_page=False)


def _chip(page: Any, tag: str) -> Any:
    # the add chip's accessible name starts with «Agregar #tag» (+ «, una de las mejores»)
    return page.locator(".q-rv-idea").filter(has=page.locator(f'[aria-label^="Agregar #{tag}"]'))


@pytest.mark.parametrize("width", [360, 1280], ids=["telefono", "computador"])
def test_best_marks_and_reasons_of_ai_ideas(app_server: str, context: Any, width: int) -> None:
    if os.environ.get("QUALIFY_E2E_BASE_URL"):
        pytest.skip("needs the harness's own app (the stubbed «Sugerir con IA»)")
    page, tenant, user, _email = _business(app_server, context)
    page.set_viewport_size({"width": width, "height": 800})
    draft, _variant = _seed_piece(tenant, user)  # caption: «Ven por un café recién hecho.»

    page.goto(f"{app_server}/drafts/{draft}")
    page.get_by_role("button", name="Editar texto", exact=True).click()
    page.get_by_role("button", name="Sugerir con IA", exact=True).click()
    expect(page.get_by_text("De tu tipo de negocio", exact=True)).to_be_visible()
    expect(page.get_by_text("De nicho", exact=True)).to_have_count(0)
    expect(page.get_by_text("De tu zona y tu marca", exact=True)).to_be_visible()

    # «Mejor» lands on the first five ELIGIBLE ideas; the unnamed watched ones are shown
    for tag in ("carne", "pollo"):
        expect(page.get_by_role("button", name=f"Agregar #{tag}", exact=True)).to_be_visible()
    for tag in _BEST:
        expect(
            page.get_by_role("button", name=f"Agregar #{tag}, una de las mejores", exact=True)
        ).to_be_visible()
    expect(page.get_by_role("button", name="Agregar #tachira", exact=True)).to_be_visible()
    # the piece already carries #cafe: room for four more of the recommended five
    expect(page.get_by_role("button", name="Agregar las 4 mejores", exact=True)).to_be_visible()

    # nothing wider than the screen
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 0, f"horizontal overflow of {overflow}px at {width}px"
    layout = page.evaluate(
        """() => ({panel: document.querySelector('.q-rv-suggest').clientWidth,
        rows: new Set([...document.querySelectorAll('.q-rv-idea')]
            .map(e => Math.round(e.getBoundingClientRect().top))).size})"""
    )
    print(f"ideas layout at {width}px: {layout}")  # noqa: T201 — read with -s
    why = page.get_by_role("button", name="Por qué te sugerimos #carne", exact=True)
    box = why.evaluate(
        """el => { const r = el.getBoundingClientRect(), a = getComputedStyle(el, '::after');
        return {w: r.width + parseFloat(a.right) * -1, h: r.height - 2 * parseFloat(a.top)} }"""
    )
    assert box["w"] >= 43.5 and box["h"] >= 43.5, box  # the touch target, ::after included

    # by touch (a click is what a tap fires): the reason opens; the chip did not add it
    why.click()
    reason = page.get_by_role("dialog").get_by_text("Tu texto nombra la carne")
    expect(reason).to_be_visible()
    _shot(page, f"m-25032581-motivo-{width}.png")
    page.keyboard.press("Escape")
    expect(reason).to_have_count(0)
    expect(page.get_by_role("button", name="Agregar #carne", exact=True)).to_be_visible()

    # by keyboard: focus the «i», Enter opens, Escape closes and gives focus back
    best_why = page.get_by_role("button", name="Por qué te sugerimos #desayuno", exact=True)
    best_why.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text("Muy usada por la mañana")).to_be_visible()
    expect(dialog.get_by_text("Mejor: una de las que más te sirven")).to_be_visible()
    expect(dialog.get_by_text("visto 1.2k veces en publicaciones reales")).to_be_visible()
    page.keyboard.press("Escape")
    expect(best_why).to_be_focused()

    # the chip's tap still adds the etiqueta (and it leaves the ideas)
    page.get_by_role("button", name="Agregar #pollo", exact=True).click()
    expect(_chip(page, "pollo")).to_have_count(0)
    expect(page.get_by_role("button", name="Agregar las 3 mejores", exact=True)).to_be_visible()
    _shot(page, f"m-25032581-ideas-{width}.png")
    page.close()
