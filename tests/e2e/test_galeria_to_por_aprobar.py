"""CM-8 (m-24955929): from Galería to «Por aprobar» with the business's own photos and
videos, in a real browser — niche «locales de comida». Run: `just e2e-galeria`.

The whole road, at 360 px (a phone) and on a computer:

1. upload a photo and a 20 s video with sound to «Fotos y videos de tu negocio»;
2. the video waits in «Preparando…» until media-worker prepares it (run here, once, for
   this business only);
3. cut it with «Cortar aquí» in the wrong place and undo it with «Deshacer»; cut it in
   three, «Quitar esta parte» on the middle one, save the two parts; media-worker cuts
   it — the original leaves the fake bucket, only the two kept parts arrive;
4. choose one photo → Crear says «Una foto»; «Cambiar» → back to the same choice → add
   part 1 and a product photo (three, in that order) → «Crear publicación con estas»;
5. Crear shows the three in order, the sound switch OFF (D6), and — with a medium of
   another business slipped into the address — «…ya no está en tu Galería…»;
6. sound on, «Crear publicación» → the piece is made (copy faked, no paid call) and is
   in «Por aprobar» with three slides in that order — its own copies of the media in
   the bucket — and its (fake) text;
7. a second business sees none of the first one's media, neither in Galería nor by
   `?medios=`.

Nothing real is touched: the harness runs the app — and this test runs media-worker —
with `QUALIFY_OBJECT_STORE_DIR` (every R2 store is a local directory) and
`QUALIFY_COPY_FAKE=1` (copy without Anthropic); see `conftest.FAKE_ENV`. Needs ffmpeg
and the compose Postgres/Redis; the run creates/migrates `qualify_test` itself.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from .conftest import OBJECTS_DIR, REPO_ROOT, _finish_brand_kit, expect, fake_env

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="needs ffmpeg to make the test video"
)

_VIEWPORTS = {
    "telefono": {"width": 360, "height": 800},
    "computador": {"width": 1280, "height": 900},
}
_PASSWORD = "e2e-clave-segura"


@pytest.fixture(scope="module", autouse=True)
def _never_the_real_bucket() -> None:
    """An app started elsewhere (`QUALIFY_E2E_BASE_URL`) must be on the same fake bucket
    — said by `QUALIFY_E2E_OBJECTS_DIR` — or this test does not run at all."""
    if os.environ.get("QUALIFY_E2E_BASE_URL") and not os.environ.get("QUALIFY_E2E_OBJECTS_DIR"):
        pytest.skip("an external app must run with QUALIFY_OBJECT_STORE_DIR (see conftest)")


# -- setup helpers (the sanctioned DB doors, as the harness does) --------------------------


def _media(tmp: Path) -> tuple[Path, Path]:
    """A photo and a 20 s vertical video with sound."""
    photo, video = tmp / "local.jpg", tmp / "cocina.mp4"
    subprocess.run(  # noqa: S603 — fixed argv
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=orange:size=1080x1350",
            "-frames:v",
            "1",
            str(photo),
        ],
        check=True,
    )
    subprocess.run(  # noqa: S603 — fixed argv
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=720x1280:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            "20",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
    )
    return photo, video


def _sign_up(app_server: str, context, name: str) -> tuple[object, uuid.UUID, uuid.UUID]:  # noqa: ANN001
    """A new «locales de comida» business, logged in on a new page: (page, tenant, brand)."""
    from qualify_api.creative.voice_service import VoiceProfileService
    from qualify_api.tenancy.models import Brand
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    email = f"e2e-{uuid.uuid4().hex[:10]}@example.com"
    signup = context.new_page()
    signup.set_default_timeout(60_000)
    signup.goto(f"{app_server}/registro")
    signup.locator("#signup-business").fill(name)
    signup.locator("#signup-email").fill(email)
    signup.locator("#signup-password").fill(_PASSWORD)
    signup.locator("#signup-country").click()
    signup.get_by_role("option", name="Colombia").click()
    signup.get_by_role("button", name="Registrar y entrar").click()
    expect(signup).not_to_have_url(re.compile(r"/registro"), timeout=90_000)
    signup.wait_for_timeout(3_000)
    signup.close()
    # the signup's writes may land a moment after the address changes
    _wait(lambda: _user_exists(email), "the signup to create the user", 30)
    tenant_id, user_id = _finish_brand_kit(email)
    with tenant_session(tenant_id) as session:
        brand_id = session.scalar(select(Brand.id).order_by(Brand.created_at))
    # The generator also needs the brand's voice, which the app adopts when the kit is
    # saved (`creative_provider.save_kit`); `_finish_brand_kit` writes the kit directly.
    VoiceProfileService().adopt_from_kit(tenant_id=tenant_id, brand_id=brand_id, user_id=user_id)
    page = context.new_page()
    page.set_default_timeout(60_000)
    page.goto(f"{app_server}/login")
    page.get_by_placeholder("Correo", exact=True).fill(email)
    page.get_by_placeholder("Contraseña", exact=True).fill(_PASSWORD)
    page.get_by_role("button", name="Entrar", exact=True).click()
    expect(page).not_to_have_url(re.compile(r"/login"), timeout=90_000)
    return page, tenant_id, brand_id


def _product_with_photo(tenant_id: uuid.UUID, brand_id: uuid.UUID, photo: Path) -> str:
    """«Arepa de queso» with one photo (product media live on the app's local upload
    volume, never R2 — CM-9 has not moved them yet)."""
    from qualify_api.catalog.service import CatalogService
    from qualify_api.creative.composition import media_root
    from qualify_api.creative.media import LocalMediaStore

    root = media_root()  # relative to the app's working directory, the repo root
    service = CatalogService(
        store=LocalMediaStore(root if root.is_absolute() else REPO_ROOT / root)
    )
    product_id = service.create_product(
        tenant_id=tenant_id,
        brand_id=brand_id,
        user_id=None,
        name="Arepa de queso",
        description="",
        category="",
    )
    service.add_media(
        tenant_id=tenant_id, product_id=product_id, data=photo.read_bytes(), filename="arepa.jpg"
    )
    return "Arepa de queso"


def _media_worker(tenant_id: uuid.UUID) -> None:
    """One pass of media-worker for THIS business only, on the same fake bucket."""
    subprocess.run(  # noqa: S603 — fixed argv, our own module
        [
            sys.executable,
            "-m",
            "qualify_api.catalog.media_worker",
            "--tenant",
            str(tenant_id),
            "--once",
        ],
        cwd=REPO_ROOT,
        env=fake_env(),
        check=True,
        timeout=600,
    )


def _gallery_folders(tenant_id: uuid.UUID) -> dict[str, list[str]]:
    """The fake bucket's Galería: folder (media id) → its files."""
    root = OBJECTS_DIR / "gallery" / str(tenant_id)
    if not root.is_dir():
        return {}
    return {d.name: sorted(f.name for f in d.iterdir()) for d in root.iterdir() if d.is_dir()}


def _live_media(tenant_id: uuid.UUID) -> list[tuple[str, str, int]]:
    """(id, type, duration ms) of the business's live Galería media, under its own RLS."""
    from qualify_api.catalog.business_media_models import BusinessMedia
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(BusinessMedia.id, BusinessMedia.media_type, BusinessMedia.duration_ms).where(
                BusinessMedia.deleted_at.is_(None)
            )
        ).all()
    return [(str(i), t, ms or 0) for i, t, ms in rows]


def _user_exists(email: str) -> bool:
    from qualify_api.tenancy.models import User
    from qualify_shared.db.admin import admin_session
    from sqlalchemy import select

    with admin_session() as session:
        return session.scalar(select(User.id).where(User.email == email)) is not None


def _draft(tenant_id: uuid.UUID, draft_id: str) -> str:
    from qualify_api.creative.models import ContentDraft
    from qualify_shared.db.session import tenant_session

    with tenant_session(tenant_id) as session:
        draft = session.get(ContentDraft, uuid.UUID(draft_id))
        return draft.status if draft is not None else ""


def _wait(predicate, what: str, timeout: float = 120.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(1.0)


def _drag_line(page, seconds: float, total: float) -> None:  # noqa: ANN001
    """Drag the cutter's line like a finger (the slider is uncontrolled while dragged;
    keys would race the server), until the thumb says it is there (±1 s)."""
    track = page.locator(".rt-SliderRoot").first
    thumb = track.get_by_role("slider")
    for _ in range(3):
        track.scroll_into_view_if_needed()
        box = track.bounding_box()
        y = box["y"] + box["height"] / 2
        page.mouse.move(box["x"] + 2, y)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] * seconds / total, y, steps=10)
        page.mouse.up()
        page.wait_for_timeout(500)
        now = float(thumb.get_attribute("aria-valuenow") or "0")
        if abs(now - seconds * 1000) <= 1000:
            return
    raise AssertionError(f"the line stayed at {now} ms, not {seconds * 1000:.0f}")


# -- the road --------------------------------------------------------------------------------


@pytest.mark.parametrize("device", list(_VIEWPORTS))
def test_from_galeria_to_por_aprobar(app_server: str, browser, tmp_path: Path, device: str) -> None:  # noqa: ANN001, PLR0915
    photo, video = _media(tmp_path)
    context = browser.new_context(viewport=_VIEWPORTS[device], device_scale_factor=1)
    page, tenant, brand = _sign_up(app_server, context, f"E2E · Arepera {device}")
    product = _product_with_photo(tenant, brand, photo)

    # 1–2. upload; the video waits for media-worker, then is ready
    page.goto(f"{app_server}/catalog")
    expect(page.get_by_text("Fotos y videos de tu negocio")).to_be_visible()
    page.locator("#gallery_business_media input[type=file]").set_input_files(
        [str(photo), str(video)]
    )
    expect(page.get_by_text("Preparando tu video…").first).to_be_visible(timeout=120_000)
    _media_worker(tenant)
    expect(page.get_by_text("Preparando tu video…")).to_have_count(0, timeout=60_000)
    expect(page.locator("video")).to_have_count(1, timeout=60_000)
    assert sorted(t for _, t, _ in _live_media(tenant)) == ["image", "video"]
    original = next(i for i, t, _ in _live_media(tenant) if t == "video")
    assert _gallery_folders(tenant)[original] == ["poster.jpg", "video.mp4"]

    # 3. cut in two, «Deshacer» once, cut again, save; media-worker cuts
    page.get_by_role("button", name=re.compile(r"^Cortar el video de")).click()
    expect(page.get_by_text("Corta tu video en partes")).to_be_visible()
    cut = page.get_by_role("button", name="Cortar aquí")
    parts = page.get_by_role("radio")
    _drag_line(page, 4.0, 20.0)
    cut.click()
    expect(parts).to_have_count(2)
    page.get_by_role("button", name="Deshacer").click()  # wrong place: undo it
    expect(parts).to_have_count(1)
    expect(page.get_by_text("Quitamos el último corte.")).to_be_visible()
    _drag_line(page, 8.0, 20.0)
    cut.click()
    expect(parts).to_have_count(2)
    _drag_line(page, 14.0, 20.0)
    cut.click()
    expect(parts).to_have_count(3)
    page.get_by_role("radio", name=re.compile(r"^Parte 2,")).click()  # the middle one
    page.get_by_role("button", name="Quitar esta parte").click()
    expect(parts).to_have_count(2)  # only the kept parts are listed
    page.get_by_role("button", name="Guardar partes").click()
    expect(page.get_by_text(re.compile(r"^Vamos a guardar 2 partes\."))).to_be_visible()
    page.get_by_role("button", name="Guardar", exact=True).click()
    expect(page.get_by_text("Cortando tu video…").first).to_be_visible(timeout=60_000)
    _media_worker(tenant)
    expect(page.get_by_text("Listo: tu video quedó en 2 partes.")).to_be_visible(timeout=60_000)
    videos = {i: ms for i, t, ms in _live_media(tenant) if t == "video"}
    assert len(videos) == 2 and original not in videos
    folders = _gallery_folders(tenant)
    # the original left the bucket (D4) and the removed part never reached it: only the
    # photo and the two kept parts are left
    assert original not in folders and len(folders) == 3
    assert all(folders[v] == ["poster.jpg", "video.mp4"] for v in videos)
    # part 1 (0:00–0:08) is the longer one; part 2 is 0:14–0:20
    part_1 = max(videos, key=lambda v: videos[v])
    assert sorted(round(ms / 1000) for ms in videos.values()) == [6, 8], videos

    # 4. choose one photo → Crear says «Una foto»; «Cambiar» → add part 1 and a product's
    page.get_by_role("button", name="Elegir para una publicación").click()
    expect(page.get_by_text("De tu negocio", exact=True)).to_be_visible()
    page.get_by_role("checkbox", name="Foto de tu negocio").click()
    page.get_by_role("button", name="Crear publicación con estas").click()
    expect(page.get_by_text("Lo que elegiste").first).to_be_visible(timeout=60_000)
    expect(page.get_by_text("Una foto", exact=True)).to_be_visible()
    expect(page.get_by_role("switch")).to_have_count(0)  # no video: no sound question
    page.get_by_role("button", name="Cambiar lo que elegiste").click()
    expect(page.get_by_text("1 elegida")).to_be_visible(timeout=60_000)
    page.get_by_role("checkbox", name=f"Video de {round(videos[part_1] / 1000)} segundos").click()
    page.get_by_role("checkbox", name=f"Foto de {product}").click()
    expect(page.get_by_text("3 elegidas")).to_be_visible()
    page.get_by_role("button", name="Crear publicación con estas").click()

    # 5. Crear: three in order, sound OFF (D6); a foreign medium is left out, and said
    expect(page.get_by_text("Lo que elegiste").first).to_be_visible(timeout=60_000)
    tiles = page.get_by_role("list", name="Lo que elegiste").get_by_role("listitem")
    expect(tiles).to_have_count(3)
    labels = [tiles.nth(i).get_attribute("aria-label") for i in range(3)]
    assert labels[0].startswith("1 de 3: foto de tu negocio")
    assert labels[1].startswith("2 de 3: video de tu negocio")
    assert labels[2] == f"3 de 3: foto de {product}"
    expect(page.get_by_text("Carrusel de 3: 1 video y 2 fotos")).to_be_visible()
    switch = page.get_by_role("switch")
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(page.get_by_text("Apagado: tus videos van sin sonido.")).to_be_visible()
    medios = re.search(r"medios=([^&]+)", page.url).group(1)

    # 7. (first half) a second business: its own photo only, never the first's
    # its own browser (cookies and storage): another phone, not another tab
    other_context = browser.new_context(viewport=_VIEWPORTS[device], device_scale_factor=1)
    other_page, other_tenant, _ = _sign_up(app_server, other_context, f"E2E · Heladería {device}")
    other_page.goto(f"{app_server}/catalog")
    other_page.locator("#gallery_business_media input[type=file]").set_input_files([str(photo)])
    expect(other_page.get_by_role("button", name="Quitar la foto de tu negocio")).to_have_count(
        1, timeout=60_000
    )
    expect(other_page.locator("video")).to_have_count(0)  # none of the first one's videos
    other_photo = _live_media(other_tenant)[0][0]
    other_page.goto(f"{app_server}/create?medios={medios}")
    expect(
        other_page.get_by_text("Las fotos y videos que elegiste ya no están en tu Galería.")
    ).to_be_visible(timeout=60_000)  # the first business's media are not its own
    other_context.close()

    page.goto(f"{app_server}/create?medios={medios},n:{other_photo}")
    expect(
        page.get_by_text(
            "Una foto o video que elegiste ya no está en tu Galería; la dejamos fuera."
        )
    ).to_be_visible(timeout=60_000)
    expect(page.get_by_role("list", name="Lo que elegiste").get_by_role("listitem")).to_have_count(
        3
    )
    page.goto(f"{app_server}/create?medios={medios}")
    expect(page.get_by_text("Lo que elegiste").first).to_be_visible(timeout=60_000)

    # 6. with sound, create → «Por aprobar», three slides in that order, its own copy
    page.get_by_role("switch").click()
    expect(page.get_by_text("Encendido: tus videos van con su sonido.")).to_be_visible()
    page.get_by_role("button", name="Crear publicación", exact=True).click()
    expect(page).to_have_url(re.compile(r"/drafts/[0-9a-f-]{36}"), timeout=90_000)
    draft_id = re.search(r"/drafts/([0-9a-f-]{36})", page.url).group(1)
    _wait(lambda: _draft(tenant, draft_id) == "generated", "the piece to be made", 180)
    generated = OBJECTS_DIR / "t" / str(tenant) / "generated" / draft_id
    files = sorted(p.name for p in generated.rglob("slide-*") if not p.name.endswith("poster.jpg"))
    assert files == ["slide-1.jpg", "slide-2.mp4", "slide-3.jpg"], files
    page.goto(f"{app_server}/drafts")
    expect(page.get_by_role("button", name="Por revisar 1")).to_be_visible(timeout=60_000)
    expect(page.get_by_text("La publicación no está aprobada.")).to_be_visible()
    page.get_by_role("button", name="Revisar", exact=True).click()
    expect(page).to_have_url(re.compile(rf"/drafts/{draft_id}"), timeout=60_000)
    expect(page.get_by_text("Ven a visitarnos").first).to_be_visible(timeout=60_000)
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= _VIEWPORTS[device]["width"], width
    context.close()
