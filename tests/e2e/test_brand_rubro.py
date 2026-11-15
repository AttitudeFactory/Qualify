"""m-25029206: «Tu rubro y tus etiquetas» in Tu marca, in a browser, at desktop and phone
width (360 px). A business with no etiquetas is invited to add them; «Cambiar» edits the
rubro and the etiquetas (an invalid one is refused with what to fix); «Cancelar» keeps
nothing; «Guardar» writes only `connect.rubro_text` and `connect.hashtags` — read back from
the database, every other key of `connect` as it was. No search and no AI call: the
harness app has no vendor keys, and nothing here could reach one.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from .conftest import expect

_SHOTS = os.environ.get("QUALIFY_E2E_SHOTS", "")


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"), full_page=False)


def _connect(page) -> dict[str, Any]:  # noqa: ANN001
    from qualify_api.creative.brand_kit_store import BrandKitStore
    from qualify_api.tenancy.models import Brand
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    tenant_id = page._qualify_e2e_tenant_id
    with tenant_session(tenant_id) as session:
        brand_id = session.scalars(select(Brand.id)).first()
    return BrandKitStore().load_details(tenant_id=tenant_id, brand_id=brand_id).connect


@pytest.mark.parametrize("width", [1280, 360])
def test_the_owner_sees_and_changes_the_rubro_and_its_tags(
    signed_up_page,  # noqa: ANN001
    app_server: str,
    width: int,
) -> None:
    page = signed_up_page
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(f"{app_server}/brand/kit")
    section = page.locator("#seccion-rubro")
    expect(section).to_be_visible(timeout=60_000)
    expect(section.get_by_text("Agrega hasta 5 palabras", exact=False)).to_be_visible()
    before = _connect(page)
    _shot(page, f"rubro-vacio-{width}")

    # «Cancelar» keeps nothing
    section.get_by_role("button", name="Cambiar", exact=True).click()
    section.locator("#brand-rubro-text").fill("algo que no se guarda")
    section.get_by_role("button", name="Cancelar", exact=True).click()
    expect(section.get_by_role("button", name="Cambiar", exact=True)).to_be_visible()
    assert _connect(page) == before

    section.get_by_role("button", name="Cambiar", exact=True).click()
    section.locator("#brand-rubro-text").fill("arepera de barrio")
    section.get_by_role("button", name="Agregar etiqueta").click()
    tag_input = section.get_by_label("Nueva etiqueta")
    tag_input.fill("c++")
    tag_input.press("Enter")
    expect(section.get_by_text("Usa solo letras, números", exact=False)).to_be_visible()
    tag_input.fill("#Arepas")
    tag_input.press("Enter")
    expect(section.get_by_text("#arepas", exact=True)).to_be_visible()
    # the input that closed on Enter must not add it again on its way out
    page.wait_for_timeout(500)
    expect(section.get_by_text("Esa etiqueta ya está en tu lista.")).to_have_count(0)
    section.get_by_role("button", name="Agregar etiqueta").click()
    section.get_by_label("Nueva etiqueta").fill("comida casera")  # joined into one
    section.get_by_label("Nueva etiqueta").press("Enter")
    expect(section.get_by_text("#comidacasera", exact=True)).to_be_visible()
    page.wait_for_timeout(500)
    expect(section.get_by_text("Esa etiqueta ya está en tu lista.")).to_have_count(0)
    joined = section.get_by_text("La unimos en una sola: #comidacasera.", exact=False)
    expect(joined).to_be_visible()
    joined.scroll_into_view_if_needed()
    _shot(page, f"rubro-unidas-{width}")
    # the helper's own example, commas and all, adds three
    section.get_by_role("button", name="Agregar etiqueta").click()
    section.get_by_label("Nueva etiqueta").fill("pizzeria, ropadeportiva")
    section.get_by_label("Nueva etiqueta").press("Enter")
    expect(section.get_by_text("#ropadeportiva", exact=True)).to_be_visible()
    section.scroll_into_view_if_needed()
    _shot(page, f"rubro-editando-{width}")
    # nothing on the page is wider than the phone
    assert page.evaluate("document.documentElement.scrollWidth") <= width + 1

    section.get_by_role("button", name="Guardar", exact=True).click()
    expect(page.get_by_text("Sección guardada.")).to_be_visible(timeout=30_000)
    expect(section.get_by_text("#arepas", exact=True)).to_be_visible()
    section.scroll_into_view_if_needed()
    _shot(page, f"rubro-guardado-{width}")

    after = _connect(page)
    assert after["rubro_text"] == "arepera de barrio"
    assert [pill["tag"] for pill in after["hashtags"]] == [
        "arepas",
        "comidacasera",
        "pizzeria",
        "ropadeportiva",
    ]
    assert all(set(pill) == {"tag", "origin", "reason", "model"} for pill in after["hashtags"])
    rest = {k: v for k, v in after.items() if k not in ("rubro_text", "hashtags")}
    assert rest == {k: v for k, v in before.items() if k not in ("rubro_text", "hashtags")}
