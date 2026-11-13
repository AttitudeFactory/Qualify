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
#: What has the focus, by its accessible name (or the tag when it has none).
_FOCUSED = (
    "(() => { const e = document.activeElement; "
    "return e ? (e.getAttribute('aria-label') || e.tagName) : ''; })()"
)


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"), full_page=True)


def _seed(tenant_id: uuid.UUID, user_id: uuid.UUID, shots: list[tuple[datetime, str]]) -> None:
    """Publications Instagram already accepted — `(settled_at, "IMAGE" | "REELS")` —
    each recorded as the screen records it once the poll reports it settled. A reel has
    no poster (Instagram never gave one), as the review's case."""
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
    for k, (settled, product) in enumerate(shots):
        key = f"t/{tenant_id}/media/{connection_id}/{uuid.uuid4().hex}"
        if product == "REELS":
            data, content_type = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64, "video/mp4"
        else:
            buf = io.BytesIO()
            image.new("RGB", (600, 750), (30 + 20 * k % 200, 140, 90)).save(buf, "JPEG")
            data, content_type = buf.getvalue(), "image/jpeg"
        path = OBJECTS_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        attempt_id = uuid.uuid4()
        with tenant_session(tenant_id) as session:
            session.add(
                PublishAttempt(
                    id=attempt_id,
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    idempotency_key=f"e2e-mural:{attempt_id}:{k}",
                    caption=f"Mural {k + 1}",
                    media_product_type=product,
                    adapter_version="e2e",
                    status="published",
                    published_media_id=f"e2e-mural-{k}",
                    started_at=settled - timedelta(seconds=3),
                    settled_at=settled,
                    media_object_key=key,
                    media_content_type=content_type,
                    permalink=f"https://www.instagram.com/p/E2Emural{k}/",
                )
            )
        result = record_publication(tenant_id=tenant_id, attempt_id=attempt_id, user_id=user_id)
        assert result.outcome is Outcome.RECORDED, result


def _seed_mural(tenant_id: uuid.UUID, user_id: uuid.UUID, *, chain: bool = False) -> None:
    """Nine photos staged over four clock minutes, the founder's real pattern (m-25026486:
    05:17:34 … 05:20:01), three hours ago; 40 min later a photo and a reel without poster;
    80 min later one lone photo — three batches the 15-minute rule keeps apart."""
    start = (datetime.now(UTC) - timedelta(hours=5)).replace(second=34, microsecond=0)
    gaps = [0, 21, 17, 19, 16, 18, 15, 20, 21]
    mural, t = [], start
    for gap in gaps:
        t += timedelta(seconds=gap)
        mural.append((t, "IMAGE"))
    pair = [
        (start + timedelta(minutes=40), "IMAGE"),
        (start + timedelta(minutes=40, seconds=30), "REELS"),
    ]
    lone = [(start + timedelta(minutes=80), "IMAGE")]
    # with `chain`: thirteen, one every 10 minutes (UX review) — pairs per 15-min span
    tail = [(start + timedelta(minutes=120 + 10 * n), "IMAGE") for n in range(13)] if chain else []
    _seed(tenant_id, user_id, mural + pair + lone + tail)


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
    pair = page.get_by_role("button", name=re.compile(r"· 2 publicaciones en @"))
    expect(pair).to_be_visible(timeout=60_000)
    pair.scroll_into_view_if_needed()
    _shot(page, "batch-reel-375")
    page.evaluate("window.scrollTo(0, 0)")
    expect(row).to_be_visible(timeout=60_000)
    expect(row).to_have_attribute("aria-expanded", "false")
    menus = page.get_by_role("button", name="Acciones de la publicación")
    expect(menus).to_have_count(1)  # folded: only the lone publication's card
    _shot(page, "batch-folded-375")
    focus_after_panel = []
    lone_menu = menus.first
    lone_menu.click()
    page.get_by_role("menuitem", name="Más detalles").click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.wait_for_timeout(1_800)  # past the closing animation and the last refocus try
    focus_after_panel.append(page.evaluate(_FOCUSED))

    # the keyboard opens it (Enter) and closes it (Space)
    row.focus()
    page.keyboard.press("Enter")
    expect(row).to_have_attribute("aria-expanded", "true")
    expect(menus).to_have_count(_N + 1)
    _shot(page, "batch-open-375")

    # every card keeps its own actions
    in_group = menus.nth(3)
    in_group.click()
    expect(page.get_by_role("menuitem").first).to_have_text("Ver en Instagram")
    expect(page.get_by_role("menuitem", name="Volver a programar")).to_be_visible()
    expect(page.get_by_role("menuitem", name="Más detalles")).to_be_visible()
    page.get_by_role("menuitem", name="Más detalles").click()
    expect(page.get_by_role("dialog")).to_contain_text("Publicación que ya salió")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.wait_for_timeout(1_800)  # past the closing animation and the last refocus try
    focus_after_panel.append(page.evaluate(_FOCUSED))
    # review m-25026241 (4): closing the panel gives focus back to the card's «⋯» —
    # inside a group as outside one
    assert focus_after_panel == ["Acciones de la publicación"] * 2, focus_after_panel

    row.focus()
    page.keyboard.press("Space")
    expect(row).to_have_attribute("aria-expanded", "false")
    expect(menus).to_have_count(1)


#: For every chip of the calendar: does any text box overflow what it is given?
_CLIPPED = """() => {
  const out = [];
  for (const el of document.querySelectorAll('.q-cal-chip .q-chip-line, .q-cell-group')) {
    if (el.scrollWidth > el.clientWidth + 1)
      out.push(el.textContent.trim() + ' | ' + el.clientWidth + ' < ' + el.scrollWidth
               + ' chip ' + (el.closest('.q-cal-chip')?.clientWidth || 0)
               + ' kids ' + Array.from(el.children).map(
                   c => (c.className.baseVal ?? c.className) + ':' + Math.round(
                     c.getBoundingClientRect().width)).join(','));
    for (const t of el.querySelectorAll('.q-chip-time, .q-chip-count')) {
      const r = t.getBoundingClientRect(), box = el.getBoundingClientRect();
      if (r.width > 0 && (r.right > box.right + 1 || t.scrollWidth > t.clientWidth + 1))
        out.push(t.textContent.trim() + ' | box ' + Math.round(box.width)
                 + ' line ' + el.scrollWidth + ' time ' + Math.round(r.width));
    }
  }
  return out;
}"""


@pytest.mark.parametrize("width", [1280, 1024])
def test_a_mural_is_one_chip_in_the_desktop_calendar(
    pre_fase_c_page,  # noqa: ANN001
    app_server: str,
    width: int,
) -> None:
    _skip_without_fake_bucket()
    page = pre_fase_c_page
    page.set_viewport_size({"width": width, "height": 900})
    _seed_mural(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id, chain=True)

    page.goto(f"{app_server}/planner?vista=calendario")
    chip = page.get_by_role("button", name=re.compile(r" – .* · 9 publicaciones en @"))
    expect(chip).to_be_visible(timeout=60_000)
    expect(chip).to_have_count(1)  # one batch, once — not one chip per clock minute
    # the pair, and the 13-chain cut in six pairs (+ one lone): seven «2 publicaciones»
    expect(page.get_by_role("button", name=re.compile(r"· 2 publicaciones en @"))).to_have_count(7)
    # the group chip starts with its time: «h:mm · 9»
    expect(chip).to_contain_text(re.compile(r"\d{1,2}:\d{2} · 9"))
    # a single chip keeps its time (no «a. m.» here) even in the narrow column
    times = page.locator(".q-cal-chip .q-chip-hm")
    expect(times.first).to_be_visible()
    expect(times.first).to_have_text(re.compile(r"^\d{1,2}:\d{2}$"))
    chip.scroll_into_view_if_needed()
    assert page.evaluate(_CLIPPED) == []  # no chip shows a clipped word or time
    _shot(page, f"batch-calendar-{width}")
    chip.click()
    rows = page.locator(".q-hour-list .q-hour-list-row")
    expect(rows).to_have_count(_N)
    expect(page.get_by_role("dialog").or_(page.locator(".rt-PopoverContent"))).to_contain_text(
        "· 9 publicaciones"
    )
    _shot(page, f"batch-calendar-open-{width}")
    rows.nth(0).click()
    expect(page.get_by_role("dialog")).to_contain_text("Publicación que ya salió")
