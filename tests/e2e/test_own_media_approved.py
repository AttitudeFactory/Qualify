"""«Publicar» → «Aprobados» and «Tu semana», in a browser (m-25019224, epic m-25019215;
founder decisions 2026-11-13).

NEVER publishes: the publication is seeded as an attempt Instagram already accepted
(`publish_attempts`, settled `published`, with a permalink) on an Instagram connection
seeded without a credential, then recorded with the real backend seam
(`qualify_api.planner.immediate.record_publication`, database only). The photo lives in
the harness's fake bucket (`OBJECTS_DIR`, a local directory — never R2).

Walks: «Aprobados» shows the piece with «Subida por ti», the «Tipo» filter separates it
from what Qualify generated, its own page offers nothing that generates or edits; «Por
aprobar» does not list it; «Tu semana» shows its published event with «Ver en Instagram»
(new tab) in the card's «⋯» menu and in the event's panel.

Screenshots at phone width (375) and desktop go to `QUALIFY_E2E_SHOTS` when it is set.
"""

from __future__ import annotations

import io
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from .conftest import OBJECTS_DIR, expect

_SHOTS = os.environ.get("QUALIFY_E2E_SHOTS", "")
_PERMALINK = "https://www.instagram.com/p/E2Eown0001/"
_CAPTION = "Arepas de queso recién hechas #arepas"


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"), full_page=True)


def _seed_published_upload(tenant_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    """A photo the owner published from «Publicar» an hour ago, recorded as the backend
    does once the poll reports it settled. Returns the piece's draft id."""
    from qualify_api.connections.models import SocialConnection
    from qualify_api.planner.immediate import Outcome, record_publication
    from qualify_api.publishing.models import PublishAttempt
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    with tenant_session(tenant_id) as session:
        connection_id = session.scalar(
            select(SocialConnection.id).where(SocialConnection.platform == "instagram")
        )
    assert connection_id is not None
    key = f"t/{tenant_id}/media/{connection_id}/{uuid.uuid4()}"
    # the staged JPEG, in the fake bucket only
    image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    image.new("RGB", (800, 1000), (214, 120, 40)).save(buf, "JPEG")
    path = OBJECTS_DIR / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())

    attempt_id = uuid.uuid4()
    settled = datetime.now(UTC) - timedelta(hours=1)
    with tenant_session(tenant_id) as session:
        session.add(
            PublishAttempt(
                id=attempt_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                idempotency_key=f"e2e-now:{attempt_id}:0",
                caption=_CAPTION,
                media_product_type="IMAGE",
                adapter_version="e2e",
                status="published",
                published_media_id="e2e-media",
                started_at=settled - timedelta(seconds=30),
                settled_at=settled,
                media_object_key=key,
                media_content_type="image/jpeg",
                permalink=_PERMALINK,
            )
        )
    result = record_publication(tenant_id=tenant_id, attempt_id=attempt_id, user_id=user_id)
    assert result.outcome is Outcome.RECORDED, result
    # idempotent: the screen and the tick may both record it
    again = record_publication(tenant_id=tenant_id, attempt_id=attempt_id, user_id=user_id)
    assert again.outcome is Outcome.EXISTING
    assert result.draft_id is not None
    return result.draft_id


@pytest.mark.parametrize("width", [375, 1280])
def test_an_upload_lives_in_aprobados_and_its_week_links_to_instagram(
    pre_fase_c_page,  # noqa: ANN001 — a Playwright Page with an Instagram account
    app_server: str,
    width: int,
) -> None:
    if os.environ.get("QUALIFY_E2E_BASE_URL") and not os.environ.get("QUALIFY_E2E_OBJECTS_DIR"):
        pytest.skip("an external app must run with QUALIFY_OBJECT_STORE_DIR (see conftest)")
    page = pre_fase_c_page
    page.set_viewport_size({"width": width, "height": 900})
    draft_id = _seed_published_upload(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)

    # «Aprobados»: the upload is there, named for what it is
    page.goto(f"{app_server}/aprobados")
    card = page.locator(".q-gcard").filter(has_text="Arepas de queso")
    expect(card).to_have_count(1, timeout=60_000)
    expect(card).to_contain_text("Subida por ti")
    # «Tipo»: the only type is the owner's uploads (nothing generated in this business)
    page.locator("#approved-posts-kind").click()
    expect(page.get_by_role("option", name="Subidas por ti")).to_be_visible()
    expect(page.get_by_role("option", name="Todos los tipos")).to_be_visible()
    page.get_by_role("option", name="Subidas por ti").click()
    expect(page).to_have_url(re.compile(r"tipo=own_media"))
    expect(card).to_have_count(1)
    _shot(page, f"own-media-aprobados-{width}")

    # «Por aprobar» never lists it
    page.goto(f"{app_server}/drafts")
    expect(page.locator(".q-gcard").filter(has_text="Arepas de queso")).to_have_count(
        0, timeout=30_000
    )

    # its own page: nothing that generates or edits
    page.goto(f"{app_server}/drafts/{draft_id}")
    expect(page.get_by_text("Subida por ti").first).to_be_visible(timeout=60_000)
    for label in ("Editar texto", "Regenerar", "Pedir otra versión", "Crearla otra vez"):
        expect(page.get_by_role("button", name=label)).to_have_count(0)
    expect(page.get_by_text("Imagen hecha con IA")).to_have_count(0)
    # only the text that went out — no brand-rule claim, no empty sections
    expect(page.get_by_text("Texto que salió")).to_be_visible()
    expect(page.get_by_text(_CAPTION).first).to_be_visible()
    for absent in ("Cumple las reglas de tu marca", "Sin gancho.", "Sin llamado a la acción."):
        expect(page.get_by_text(absent)).to_have_count(0)
    _shot(page, f"own-media-ficha-{width}")

    # «Tu semana»: the published event (list view) with «Ver en Instagram»
    page.goto(f"{app_server}/planner?vista=lista")
    menu = page.get_by_role("button", name="Acciones de la publicación").first
    expect(menu).to_be_visible(timeout=60_000)
    menu.click()
    items = page.get_by_role("menuitem")
    expect(items.first).to_have_text("Ver en Instagram")
    expect(page.get_by_role("menuitem", name="Volver a programar")).to_be_visible()
    expect(page.get_by_role("menuitem", name="Más detalles")).to_be_visible()
    expect(page.get_by_role("menuitem", name="Ver publicación")).to_have_count(0)
    page.keyboard.press("Escape")
    _shot(page, f"own-media-semana-{width}")

    # the event's panel: the same link, opening a new tab
    menu.click()
    page.get_by_role("menuitem", name="Más detalles").click()
    panel_link = page.get_by_role("link", name=re.compile("Ver en Instagram"))
    expect(panel_link).to_be_visible(timeout=30_000)
    expect(panel_link).to_have_attribute("href", _PERMALINK)
    expect(panel_link).to_have_attribute("target", "_blank")
    panel = page.get_by_role("dialog")
    expect(panel).to_contain_text("Publicación que ya salió")
    expect(panel).to_contain_text("Mírala en Instagram o vuelve a programarla.")
    expect(panel).to_contain_text("Salió como publicación")
    expect(panel).not_to_contain_text("Product")
    expect(panel.get_by_role("button", name="Volver a programar")).to_be_visible()
    _shot(page, f"own-media-panel-{width}")

    # «Descartar» from «Aprobados» (observed, not changed — UX review m-25019224): it
    # says Instagram keeps it, the card leaves «Aprobados», the published event stays.
    if width != 375:
        return
    page.goto(f"{app_server}/aprobados")
    card = page.locator(".q-gcard").filter(has_text="Arepas de queso")
    card.get_by_role("button", name="Descartar").click()
    expect(page.get_by_role("alertdialog")).to_contain_text("sigue en tu Instagram")
    page.get_by_role("button", name="Sí, descartar").click()
    expect(card).to_have_count(0, timeout=30_000)
    page.goto(f"{app_server}/planner?vista=lista")
    week_card = page.get_by_text("Arepas de queso recién hechas", exact=False).first
    expect(week_card).to_be_visible(timeout=60_000)
    _shot(page, "own-media-descartada-semana-375")
