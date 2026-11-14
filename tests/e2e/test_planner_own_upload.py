"""«Tu semana» → «Nueva publicación» → «Subir foto o video», in a browser (m-25026384).

Never touches the real bucket: the harness's app runs on the fake one (`OBJECTS_DIR`,
`QUALIFY_OBJECT_STORE_DIR`), and nothing here publishes — the piece is only selected on
«Cuándo sale». The neighbouring ready piece is seeded through the same backend seam
the screen uses (`creative.own_upload.record_planner_upload`), its JPEG in the fake
bucket.

Walks, at phone width (380) and desktop: the «+» card is the grid's first card next to
a real tile, and also there when nothing is ready; a refused file says why; a photo is
picked, previewed, saved with its text, and lands selected on step 2. The keyboard path
(card → view title → «Volver a elegir» → card) is checked on desktop. m-25026481: a video
(the 65 s and 2 s fixture clips) shows the poster Qualify took at upload in the view and
on its step-1 tile, and «Historia» warns with the length only when it is over 60 s.

Screenshots go to `QUALIFY_E2E_SHOTS` when it is set.
"""

from __future__ import annotations

import io
import os
import re
import uuid
from pathlib import Path

import pytest

from .conftest import OBJECTS_DIR, expect

_SHOTS = os.environ.get("QUALIFY_E2E_SHOTS", "")
_NEIGHBOUR = "Arepa del día con queso"
_CAPTION = "Nuestra cachapa nueva, desde hoy en el menú"
_CARD = "Subir una foto o un video tuyo para programarlo"


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.wait_for_timeout(700)  # the drawer's slide-in, so the shot is the settled panel
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"), full_page=False)


def _skip_without_fake_bucket() -> None:
    if os.environ.get("QUALIFY_E2E_BASE_URL") and not os.environ.get("QUALIFY_E2E_OBJECTS_DIR"):
        pytest.skip("an external app must run with QUALIFY_OBJECT_STORE_DIR (see conftest)")


def _jpeg(size: tuple[int, int], colour: tuple[int, int, int]) -> bytes:
    image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    image.new("RGB", size, colour).save(buf, "JPEG")
    return buf.getvalue()


def _seed_ready_piece(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """One ready own piece (a 4:5 photo), so the grid has a real tile next to the card."""
    from qualify_api.creative.own_upload import OwnUpload, record_planner_upload
    from qualify_api.tenancy.models import Brand
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    with tenant_session(tenant_id) as session:
        brand_id = session.scalar(select(Brand.id).order_by(Brand.created_at))
    data = _jpeg((800, 1000), (214, 120, 40))
    key = f"t/{tenant_id}/uploads/planner/{uuid.uuid4().hex}_arepa.jpg"
    path = OBJECTS_DIR / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    record_planner_upload(
        tenant_id=tenant_id,
        brand_id=brand_id,
        user_id=user_id,
        upload=OwnUpload(
            upload_id=uuid.uuid4(),
            object_key=key,
            media_type="image",
            content_type="image/jpeg",
            caption=_NEIGHBOUR,
            width=800,
            height=1000,
            size_bytes=len(data),
        ),
    )


def _open_step_one(page, app_server: str) -> None:  # noqa: ANN001 — a Playwright Page
    page.goto(f"{app_server}/planner")
    page.get_by_role("button", name="Nueva publicación").first.click()
    expect(page.get_by_text("¿Qué vas a publicar?")).to_be_visible(timeout=60_000)


def _active_id(page) -> str:  # noqa: ANN001 — a Playwright Page
    return page.evaluate("document.activeElement && document.activeElement.id")


@pytest.mark.parametrize("width", [380, 1280])
def test_upload_a_photo_and_land_selected_on_when(
    pre_fase_c_page,  # noqa: ANN001 — a Playwright Page with an Instagram account
    app_server: str,
    width: int,
    tmp_path: Path,
) -> None:
    _skip_without_fake_bucket()
    page = pre_fase_c_page
    page.set_viewport_size({"width": width, "height": 900})
    _seed_ready_piece(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)

    _open_step_one(page, app_server)
    grid = page.locator(".q-drawer .q-tile-grid")
    expect(grid.locator(".q-tile")).to_have_count(2, timeout=60_000)
    first = grid.locator(".q-tile").first
    expect(first).to_have_attribute("aria-label", _CARD)
    expect(first).to_contain_text("Subir foto o video")
    # the card and the real tile are the same size, side by side or stacked
    card_box, tile_box = first.bounding_box(), grid.locator(".q-tile").nth(1).bounding_box()
    assert card_box and tile_box
    assert abs(card_box["width"] - tile_box["width"]) < 2
    assert abs(card_box["height"] - tile_box["height"]) < 2
    assert card_box["height"] >= 44 and card_box["width"] >= 44
    # nothing wider than the panel
    assert page.evaluate(
        "(() => { const b = document.querySelector('.q-drawer .q-drawer-body');"
        " return b.scrollWidth <= b.clientWidth + 1; })()"
    )
    _shot(page, f"a-grid-{width}")

    if width > 600:
        # keyboard: Enter on the card opens the view with the focus on its title; Enter on
        # «Volver a elegir» comes back to the card
        first.focus()
        page.keyboard.press("Enter")
        expect(page.get_by_text("Sube tu foto o video")).to_be_visible()
        page.wait_for_function("document.activeElement?.id === 'q-own-upload-title'")
        back = page.get_by_role("button", name="Volver a elegir")
        back_box = back.bounding_box()
        assert back_box and back_box["height"] >= 44
        back.focus()
        page.keyboard.press("Enter")
        page.wait_for_function("document.activeElement?.id === 'q-own-upload-card'")
        assert _active_id(page) == "q-own-upload-card"
        first.click()
    else:
        first.click()
    expect(page.get_by_text("Sube tu foto o video")).to_be_visible()
    expect(page.get_by_text("Paso 1 de 3").first).to_be_visible()
    _shot(page, f"c-view-{width}")

    file_input = page.locator(".q-drawer input[type=file]").first
    # a refused file: said in plain words, nothing stored
    pdf = tmp_path / "menu.pdf"
    pdf.write_bytes(b"%PDF-1.4 e2e")
    file_input.set_input_files(str(pdf))
    expect(page.get_by_text("no es una foto ni un video que podamos usar")).to_be_visible()
    _shot(page, f"c-refused-{width}")

    photo = tmp_path / "cachapa.png"
    photo.write_bytes(_jpeg((1080, 1350), (240, 200, 60)))  # a JPEG named .png: still opens
    file_input.set_input_files(str(photo))
    expect(page.get_by_text("Cambiar archivo")).to_be_visible(timeout=60_000)
    expect(page.locator(".q-own-upload-preview img")).to_be_visible()
    page.locator("#q-own-upload-caption").fill(_CAPTION)
    save = page.get_by_role("button", name="Guardar y continuar")
    save_box = save.bounding_box()
    assert save_box and save_box["height"] >= 40
    _shot(page, f"d-picked-{width}")

    save.click()
    _shot(page, f"e-saving-{width}")  # best effort: the save is quick on a local DB
    expect(page.get_by_text("Paso 2 de 3").first).to_be_visible(timeout=60_000)
    expect(page.locator(".q-drawer")).to_contain_text(_CAPTION[:20])
    _shot(page, f"f-when-{width}")
    # exactly one piece stored for this file in the fake bucket, under uploads/planner
    tenant = page._qualify_e2e_tenant_id
    stored = list((OBJECTS_DIR / f"t/{tenant}/uploads/planner").glob("*cachapa.jpg"))
    assert len(stored) == 1


@pytest.mark.parametrize("width", [380, 1280])
def test_the_card_is_there_when_nothing_is_ready(
    pre_fase_c_page,  # noqa: ANN001 — an account (the button needs one), no pieces
    app_server: str,
    width: int,
) -> None:
    _skip_without_fake_bucket()
    page = pre_fase_c_page
    page.set_viewport_size({"width": width, "height": 900})
    _open_step_one(page, app_server)
    card = page.get_by_role("button", name=_CARD)
    expect(card).to_be_visible(timeout=60_000)
    expect(page.get_by_text("No hay publicaciones para programar")).to_be_visible()
    expect(page.get_by_role("link").filter(has_text="Crear una publicación")).to_be_visible()
    _shot(page, f"b-empty-{width}")


# --- m-25026481: a video's poster and length ----------------------------------------------

_CLIPS = Path(__file__).resolve().parents[2] / "packages/creative/tests/fixtures"
_LONG_STORY = "Este video dura 1 min 5 s"
_GENERIC_STORY = "Si este video es más largo"


def _skip_without_ffmpeg() -> None:
    import shutil

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("the app needs ffmpeg/ffprobe on PATH to read a video")


def _pick_video(page, clip: str, as_name: str, tmp_path: Path) -> None:  # noqa: ANN001
    """From step 1: the «+» card, then the clip, until the preview shows its poster."""
    page.locator(".q-drawer .q-tile-grid .q-tile").first.click()
    expect(page.get_by_text("Sube tu foto o video")).to_be_visible()
    video = tmp_path / as_name
    video.write_bytes((_CLIPS / clip).read_bytes())
    page.locator(".q-drawer input[type=file]").first.set_input_files(str(video))
    expect(page.get_by_text("Cambiar archivo")).to_be_visible(timeout=60_000)
    preview = page.locator(".q-own-upload-preview video")
    expect(preview).to_be_visible()
    # the frame Qualify took at upload, not an empty player
    expect(preview).to_have_attribute("poster", re.compile(r"\.jpg"))


def _loaded_width(page, selector: str, attr: str) -> int:  # noqa: ANN001
    """The natural width of the picture an element points at (0 when it does not load)."""
    return page.evaluate(
        """([sel, attr]) => new Promise((done) => {
            const el = document.querySelector(sel);
            const url = el && el.getAttribute(attr);
            if (!url) return done(0);
            const img = new Image();
            img.onload = () => done(img.naturalWidth);
            img.onerror = () => done(0);
            img.src = url;
        })""",
        [selector, attr],
    )


def _save_and_choose_story(page) -> None:  # noqa: ANN001
    page.get_by_role("button", name="Guardar y continuar").click()
    expect(page.get_by_text("Paso 2 de 3").first).to_be_visible(timeout=60_000)
    # the piece's card on step 2 shows the poster too
    expect(page.locator(".q-drawer .q-plan-thumb video[poster]").first).to_be_visible()
    # «¿Dónde quieres publicarlo?» lives under «Más opciones» (closed by default)
    page.locator(".q-drawer").get_by_role("button", name="Más opciones", exact=True).first.click()
    page.locator(".q-drawer .q-dest-btn.q-dest-story").first.click()
    expect(page.locator(".q-drawer .q-dest-btn--on.q-dest-story").first).to_be_visible()


@pytest.mark.parametrize("width", [380, 1280])
def test_a_video_shows_its_poster_and_a_long_story_warns_with_its_length(
    pre_fase_c_page,  # noqa: ANN001 — a Playwright Page with an Instagram account
    app_server: str,
    width: int,
    tmp_path: Path,
) -> None:
    _skip_without_fake_bucket()
    _skip_without_ffmpeg()
    page = pre_fase_c_page
    page.set_viewport_size({"width": width, "height": 900})
    tenant = page._qualify_e2e_tenant_id
    folder = OBJECTS_DIR / f"t/{tenant}/uploads/planner"

    # 1. the 65 s clip: poster in the view, saved, selected on step 2
    _open_step_one(page, app_server)
    _pick_video(page, "video-portrait-65s.mp4", "cachapa-larga.mp4", tmp_path)
    assert _loaded_width(page, ".q-own-upload-preview video", "poster") > 0
    _shot(page, f"g-video-picked-{width}")
    assert len(list(folder.glob("*cachapa-larga.mp4"))) == 1
    assert len(list(folder.glob("*cachapa-larga.jpg"))) == 1  # its poster, same folder

    # 2. «Historia» warns BEFORE scheduling, naming the length
    _save_and_choose_story(page)
    warning = page.locator(".q-drawer").get_by_text(_LONG_STORY).first
    expect(warning).to_be_visible()
    expect(warning).to_contain_text("Instagram la rechazará")
    # the «Historia» button is described by that warning, for screen readers
    story = page.locator(".q-drawer .q-dest-btn--on.q-dest-story").first
    described = story.get_attribute("aria-describedby") or ""
    assert described.startswith("dest-warn-")
    expect(page.locator(f"#{described}")).to_contain_text("1 min 5 s")
    warning.scroll_into_view_if_needed()
    _shot(page, f"h-long-story-{width}")

    # 2b. «Confirmar» (only shown, never confirmed): the row is tagged and the note names
    # the story by its hour
    page.get_by_role("button", name="Continuar").click()
    expect(page.get_by_text("Paso 3 de 3").first).to_be_visible(timeout=30_000)
    drawer = page.locator(".q-drawer")
    tag = drawer.get_by_text("Dura más de 1 minuto").first
    expect(tag).to_be_visible()
    note = drawer.get_by_text(re.compile(r"^La Historia de la.? .* dura 1 min 5 s")).first
    expect(note).to_be_visible()
    expect(note).to_contain_text("Instagram la rechazará")
    expect(drawer.get_by_text("No pudimos leer cuánto duran")).to_have_count(0)
    note.scroll_into_view_if_needed()
    _shot(page, f"k-confirm-long-story-{width}")

    # 3. step 1 again: the piece's tile shows the poster, not the placeholder
    _open_step_one(page, app_server)
    tiles = page.locator(".q-drawer .q-tile-grid .q-tile")
    expect(tiles).to_have_count(2, timeout=60_000)
    poster_tile = ".q-drawer .q-tile-grid .q-tile video[poster]"
    expect(page.locator(poster_tile)).to_have_count(1)
    expect(page.locator(".q-drawer .q-tile-grid .q-media-empty")).to_have_count(0)
    assert _loaded_width(page, poster_tile, "poster") > 0
    _shot(page, f"i-grid-poster-{width}")

    # 4. the 2 s clip as «Historia»: no warning at all
    _pick_video(page, "video-portrait-2s.mp4", "cachapa-corta.mp4", tmp_path)
    _save_and_choose_story(page)
    drawer = page.locator(".q-drawer")
    expect(drawer).to_contain_text("Paso 2 de 3")
    expect(drawer.get_by_text("Este video dura")).to_have_count(0)
    expect(drawer.get_by_text(_GENERIC_STORY)).to_have_count(0)
    _shot(page, f"j-short-story-{width}")
