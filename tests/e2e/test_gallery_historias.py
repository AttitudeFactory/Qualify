"""Historias in «Aprobados», in a browser (founder request 2026-11-16).

NEVER publishes and never opens Instagram: the historia is seeded as one the owner
already published from «Publicar» (`publish_attempts` settled `published`, recorded with
`qualify_api.planner.immediate.record_publication`, database only), its 9:16 image in
the harness's fake bucket (`OBJECTS_DIR`, never R2). The phone's share panel is replaced
by a stub that only records the File it was given.

Walks, at phone width: the card says «Historia»; «Tipo» offers «Historias» and keeps only
them; on an iPhone there is no «Abrir en Instagram»; on Android there is, and a tap
fetches the historia's own file and hands it, as a JPEG File, to `navigator.share`.

Screenshots go to `QUALIFY_E2E_SHOTS` when it is set.
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
_CAPTION = "Shawarma del día #historia"
_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Mobile Safari/537.36"
)
_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
#: The share panel, stubbed before the app loads: it records what it was handed.
_SHARE_STUB = """
window.__e2eShared = [];
navigator.canShare = (data) => !!(data && data.files && data.files.length);
navigator.share = async (data) => {
  const file = data.files[0];
  window.__e2eShared.push({ name: file.name, type: file.type, size: file.size });
};
"""


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"), full_page=True)


def _seed_story(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    product_type: str = "STORIES",
    size: tuple[int, int] = (540, 960),
    caption: str = _CAPTION,
) -> uuid.UUID:
    """A piece the owner published from «Publicar» an hour ago (a 9:16 historia by
    default). Returns its draft id."""
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
    image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    image.new("RGB", size, (20, 120, 110)).save(buf, "JPEG")
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
                idempotency_key=f"e2e-story:{attempt_id}:0",
                caption=caption,
                media_product_type=product_type,
                adapter_version="e2e",
                status="published",
                published_media_id="e2e-story",
                started_at=settled - timedelta(seconds=30),
                settled_at=settled,
                media_object_key=key,
                media_content_type="image/jpeg",
            )
        )
    result = record_publication(tenant_id=tenant_id, attempt_id=attempt_id, user_id=user_id)
    assert result.outcome is Outcome.RECORDED, result
    assert result.draft_id is not None
    return result.draft_id


def _as_phone(page, agent: str) -> None:  # noqa: ANN001 — a Playwright Page
    """This tab now reports `agent` (Chromium's DevTools protocol; the session token
    lives in the tab, so the login survives)."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setUserAgentOverride", {"userAgent": agent})


def test_a_historia_is_labelled_filtered_and_shared_only_on_android(
    pre_fase_c_page,  # noqa: ANN001 — a Playwright Page with an Instagram account
    app_server: str,
) -> None:
    if os.environ.get("QUALIFY_E2E_BASE_URL") and not os.environ.get("QUALIFY_E2E_OBJECTS_DIR"):
        pytest.skip("an external app must run with QUALIFY_OBJECT_STORE_DIR (see conftest)")
    page = pre_fase_c_page
    page.set_viewport_size({"width": 375, "height": 900})
    page.add_init_script(_SHARE_STUB)
    _seed_story(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)

    # iPhone: labelled and filterable, but no «Abrir en Instagram»
    _as_phone(page, _IPHONE)
    page.goto(f"{app_server}/aprobados")
    card = page.locator(".q-gcard").filter(has_text="Shawarma del día")
    expect(card).to_have_count(1, timeout=60_000)
    expect(card).to_contain_text("Historia")
    page.locator("#approved-posts-kind").click()
    page.get_by_role("option", name="Historias").click()
    expect(page).to_have_url(re.compile(r"tipo=historias"))
    expect(card).to_have_count(1)
    expect(card.get_by_role("button", name="Abrir en Instagram")).to_have_count(0)
    _shot(page, "historias-aprobados-iphone-375")

    # Android: the button, and a tap hands the historia's own file to the share panel
    _as_phone(page, _ANDROID)
    page.goto(f"{app_server}/aprobados?ver=publicaciones&tipo=historias")
    button = card.get_by_role("button", name="Abrir en Instagram")
    expect(button).to_be_visible(timeout=60_000)
    expect(card).to_contain_text("agrégale la música")
    _shot(page, "historias-aprobados-android-375")
    # right under the card's main button, above «Ver publicación»
    view = card.get_by_role("link", name="Ver publicación")
    if view.count():
        assert button.bounding_box()["y"] < view.bounding_box()["y"]
    # a slow download: the button says so, is off, and a second tap fetches nothing more
    held: list = []  # the file's download, held until the test lets it go

    def _hold(route) -> None:  # noqa: ANN001 — a Playwright Route
        held.append(route)

    page.route(re.compile(r"/r2media/"), _hold)
    button.click()
    busy = card.get_by_text("Preparando tu historia…")
    expect(busy).to_be_visible(timeout=5_000)
    expect(card.locator("button[data-busy]")).to_be_disabled()
    card.locator("button[data-busy]").click(force=True)
    page.wait_for_timeout(500)
    assert len(held) == 1  # the second tap started no second download
    held[0].continue_()
    expect(page.get_by_text("Si elegiste Instagram")).to_be_visible(timeout=30_000)
    expect(button).to_be_enabled()
    assert len(held) == 1
    shared = page.evaluate("window.__e2eShared")
    assert len(shared) == 1
    assert shared[0]["type"] == "image/jpeg"
    assert shared[0]["name"] == "historia.jpg"
    assert shared[0]["size"] > 0


def test_marking_a_piece_as_a_historia_on_its_page_shows_it_in_historias(
    pre_fase_c_page,  # noqa: ANN001 — a Playwright Page with an Instagram account
    app_server: str,
) -> None:
    if os.environ.get("QUALIFY_E2E_BASE_URL") and not os.environ.get("QUALIFY_E2E_OBJECTS_DIR"):
        pytest.skip("an external app must run with QUALIFY_OBJECT_STORE_DIR (see conftest)")
    page = pre_fase_c_page
    page.set_viewport_size({"width": 375, "height": 900})
    draft_id = _seed_story(
        page._qualify_e2e_tenant_id,
        page._qualify_e2e_user_id,
        product_type="IMAGE",
        size=(800, 1000),
        caption="Ensalada de la casa #feed",
    )
    _as_phone(page, _ANDROID)

    # «Aprobados»: a feed picture, not a historia yet
    page.goto(f"{app_server}/aprobados")
    card = page.locator(".q-gcard").filter(has_text="Ensalada de la casa")
    expect(card).to_have_count(1, timeout=60_000)
    expect(card.get_by_text("Historia", exact=True)).to_have_count(0)

    # its own page: «Es una historia», then back to «Aprobados»
    page.goto(f"{app_server}/drafts/{draft_id}?desde=aprobados")
    switch = page.get_by_role("switch")
    expect(switch).to_be_visible(timeout=60_000)
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(page.get_by_text("Es una historia")).to_be_visible()
    switch.click()
    expect(
        page.get_by_text("Listo: ahora es una historia. La encuentras en Aprobados")
    ).to_be_visible(timeout=30_000)
    expect(switch).to_have_attribute("aria-checked", "true")
    _shot(page, "historia-switch-375")

    page.goto(f"{app_server}/aprobados")
    expect(card.get_by_text("Historia", exact=True)).to_be_visible(timeout=60_000)
    expect(card.get_by_role("button", name="Abrir en Instagram")).to_be_visible()
    page.locator("#approved-posts-kind").click()
    page.get_by_role("option", name="Historias").click()
    expect(card).to_have_count(1)

    # undo: it is a feed picture again
    page.goto(f"{app_server}/drafts/{draft_id}")
    switch = page.get_by_role("switch")
    expect(switch).to_have_attribute("aria-checked", "true", timeout=60_000)
    switch.click()
    expect(page.get_by_text("Listo: vuelve a ser una publicación.")).to_be_visible(timeout=30_000)


def test_a_vertical_video_uploaded_as_a_historia_lands_in_historias(
    pre_fase_c_page,  # noqa: ANN001 — a Playwright Page with an Instagram account
    app_server: str,
    tmp_path: Path,
) -> None:
    """«Nueva publicación» › «Subir foto o video»: a 9:16 video comes with «Es una
    historia» off; turned on and saved, step 2 proposes «Historia», and «Aprobados» ›
    «Historias» lists it. Nothing is scheduled (the drawer is closed on step 2)."""
    from .test_planner_own_upload import (
        _open_step_one,
        _pick_video,
        _skip_without_fake_bucket,
        _skip_without_ffmpeg,
    )

    _skip_without_fake_bucket()
    _skip_without_ffmpeg()
    page = pre_fase_c_page
    page.set_viewport_size({"width": 375, "height": 900})

    _open_step_one(page, app_server)
    _pick_video(page, "video-portrait-2s.mp4", "historia-del-dia.mp4", tmp_path)
    switch = page.locator("#q-own-upload-story")
    expect(switch).to_have_attribute("aria-checked", "false")  # off until the owner says
    switch.click()
    expect(switch).to_have_attribute("aria-checked", "true")
    expect(page.locator(".q-drawer").get_by_text("Es una historia")).to_be_visible()
    page.locator("#q-own-upload-caption").fill("Historia del día")
    _shot(page, "upload-historia-switch-375")
    page.get_by_role("button", name="Guardar y continuar").click()
    expect(page.get_by_text("Paso 2 de 3").first).to_be_visible(timeout=60_000)
    page.locator(".q-drawer").get_by_role("button", name="Más opciones", exact=True).first.click()
    expect(page.locator(".q-drawer .q-dest-btn--on.q-dest-story").first).to_be_visible()
    _shot(page, "upload-historia-step2-375")

    page.goto(f"{app_server}/aprobados?ver=publicaciones&tipo=historias")
    card = page.locator(".q-gcard").filter(has_text="Historia del día")
    expect(card).to_have_count(1, timeout=60_000)
    expect(card.get_by_text("Historia", exact=True)).to_be_visible()
