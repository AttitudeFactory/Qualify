"""«Tu semana» folds same-minute publications into one row (m-25026241; founder
2026-11-13: «Agrupa publicaciones del mismo minuto»).

NEVER publishes: nine attempts Instagram already accepted in one minute (an «Una por
una» mural) are seeded on an Instagram connection without a credential and recorded with
the real `record_publication` (database only); their photos live in the harness's fake
bucket (`OBJECTS_DIR`, a local directory — never R2).

Phone (375): one folded row «N publicaciones» that a keyboard opens and closes, exposing
`aria-expanded`; open, the nine usual cards with their «⋯» menu. Desktop (1280): the
calendar cell shows one chip «h:mm · 9 publicaciones» that lists the nine beside it.
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
_N = 9


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"), full_page=True)


def _seed_mural(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Nine photos that went out within one minute (5 s apart), each recorded as the
    screen records it once the poll reports it settled."""
    from qualify_api.connections.models import SocialConnection
    from qualify_api.planner.immediate import Outcome, record_publication
    from qualify_api.publishing.models import PublishAttempt
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    image = pytest.importorskip("PIL.Image")
    with tenant_session(tenant_id) as session:
        connection_id = session.scalar(
            select(SocialConnection.id).where(SocialConnection.platform == "instagram")
        )
    assert connection_id is not None
    # the minute an hour ago, never across a minute boundary (5 s … 45 s)
    minute = (datetime.now(UTC) - timedelta(hours=1)).replace(second=0, microsecond=0)
    for k in range(_N):
        key = f"t/{tenant_id}/media/{connection_id}/{uuid.uuid4().hex}"
        buf = io.BytesIO()
        image.new("RGB", (600, 750), (30 + 20 * k, 140, 200 - 15 * k)).save(buf, "JPEG")
        path = OBJECTS_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        attempt_id = uuid.uuid4()
        settled = minute + timedelta(seconds=5 + 5 * k)
        with tenant_session(tenant_id) as session:
            session.add(
                PublishAttempt(
                    id=attempt_id,
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    idempotency_key=f"e2e-mural:{attempt_id}:{k}",
                    caption=f"Mural {k + 1} de {_N}",
                    media_product_type="IMAGE",
                    adapter_version="e2e",
                    status="published",
                    published_media_id=f"e2e-mural-{k}",
                    started_at=settled - timedelta(seconds=3),
                    settled_at=settled,
                    media_object_key=key,
                    media_content_type="image/jpeg",
                    permalink=f"https://www.instagram.com/p/E2Emural{k}/",
                )
            )
        result = record_publication(tenant_id=tenant_id, attempt_id=attempt_id, user_id=user_id)
        assert result.outcome is Outcome.RECORDED, result


def _skip_without_fake_bucket() -> None:
    if os.environ.get("QUALIFY_E2E_BASE_URL") and not os.environ.get("QUALIFY_E2E_OBJECTS_DIR"):
        pytest.skip("an external app must run with QUALIFY_OBJECT_STORE_DIR (see conftest)")


def test_a_mural_is_one_folded_row_on_the_phone(
    pre_fase_c_page,  # noqa: ANN001 — a Playwright Page with an Instagram account
    app_server: str,
) -> None:
    _skip_without_fake_bucket()
    page = pre_fase_c_page
    page.set_viewport_size({"width": 375, "height": 900})
    _seed_mural(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)

    page.goto(f"{app_server}/planner?vista=lista")
    row = page.get_by_role("button", name=re.compile(r"· 9 publicaciones en @"))
    expect(row).to_be_visible(timeout=60_000)
    expect(row).to_have_attribute("aria-expanded", "false")
    menus = page.get_by_role("button", name="Acciones de la publicación")
    expect(menus).to_have_count(0)  # folded: no card
    _shot(page, "minute-group-folded-375")

    # the keyboard opens it (Enter) and closes it (Space)
    row.focus()
    page.keyboard.press("Enter")
    expect(row).to_have_attribute("aria-expanded", "true")
    expect(menus).to_have_count(_N)
    _shot(page, "minute-group-open-375")

    # every card keeps its own actions
    menus.nth(3).click()
    expect(page.get_by_role("menuitem").first).to_have_text("Ver en Instagram")
    expect(page.get_by_role("menuitem", name="Volver a programar")).to_be_visible()
    expect(page.get_by_role("menuitem", name="Más detalles")).to_be_visible()
    page.get_by_role("menuitem", name="Más detalles").click()
    expect(page.get_by_role("dialog")).to_contain_text("Publicación que ya salió")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)

    row.focus()
    page.keyboard.press("Space")
    expect(row).to_have_attribute("aria-expanded", "false")
    expect(menus).to_have_count(0)


def test_a_mural_is_one_chip_in_the_desktop_calendar(
    pre_fase_c_page,  # noqa: ANN001
    app_server: str,
) -> None:
    _skip_without_fake_bucket()
    page = pre_fase_c_page
    page.set_viewport_size({"width": 1280, "height": 900})
    _seed_mural(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)

    page.goto(f"{app_server}/planner?vista=calendario")
    chip = page.get_by_role("button", name=re.compile(r"· 9 publicaciones en @"))
    expect(chip).to_be_visible(timeout=60_000)
    chip.scroll_into_view_if_needed()
    _shot(page, "minute-group-calendar-1280")
    chip.click()
    rows = page.locator(".q-hour-list .q-hour-list-row")
    expect(rows).to_have_count(_N)
    _shot(page, "minute-group-calendar-open-1280")
    rows.nth(0).click()
    expect(page.get_by_role("dialog")).to_contain_text("Publicación que ya salió")
