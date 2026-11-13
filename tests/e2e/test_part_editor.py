"""UI-4 on the real compiled create page. Manual parts avoid every paid model door.

Run against the isolated fake-auth/test-database app from conftest, never production.
The only fixture write is a product belonging to the exact business just signed up.
"""

from __future__ import annotations

import io
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

import pytest

from .conftest import expect, playwright_sync


def _socket_event(frame: str | bytes) -> dict:
    """Decode Socket.IO's event frame, leaving heartbeats and binary media alone."""
    if not isinstance(frame, str) or not frame.startswith("42"):
        return {}
    try:
        event, payload = json.loads(frame[frame.index("[") :])
    except (ValueError, TypeError):
        return {}
    return payload if event == "event" and isinstance(payload, dict) else {}


@pytest.fixture(scope="module", autouse=True)
def _only_the_fake_bucket() -> None:
    if os.environ.get("QUALIFY_E2E_BASE_URL") and not os.environ.get("QUALIFY_E2E_OBJECTS_DIR"):
        pytest.skip("the external test app must use the same fake object directory")


@pytest.mark.parametrize("width", [375, 1280])
def test_manual_parts_editor_history_focus_and_six_active_limit(
    signed_up_page,
    app_server: str,
    width: int,
    tmp_path: Path,
) -> None:
    import av
    from PIL import Image

    from Qualify.catalog_provider import add_media, create_product
    from Qualify.creative_provider import default_brand_id

    page = signed_up_page
    page.set_viewport_size({"width": width, "height": 900})
    tenant = page._qualify_e2e_tenant_id
    brand = default_brand_id(tenant)
    assert brand is not None
    product = create_product(
        tenant,
        brand,
        page._qualify_e2e_user_id,
        name="Vaso UI4",
        description="Un vaso de prueba",
        category="Pruebas",
    )
    photo = io.BytesIO()
    Image.new("RGB", (160, 200), "teal").save(photo, format="PNG")
    add_media(tenant, product, data=photo.getvalue(), filename="vaso-ui4.png")
    video = tmp_path / "mi-video.mp4"
    with av.open(str(video), "w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 96, 128, "yuv420p"
        for _ in range(50):
            frame = av.VideoFrame.from_image(Image.new("RGB", (96, 128), "teal"))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    create_loads = {"started": 0, "ready": 0, "hydrated": False, "errored": False}

    def received(frame: str | bytes) -> None:
        for fields in _socket_event(frame).get("delta", {}).values():
            values = {key.removesuffix("_rx_state_"): value for key, value in fields.items()}
            if "is_hydrated" in values:
                create_loads["hydrated"] = values["is_hydrated"]
            loading = values.get("create_loading")
            if loading is False and ("route_options" in values or values.get("create_error")):
                # Initial hydration carries defaults, not a completed invocation.
                if create_loads["ready"] < create_loads["started"]:
                    create_loads["ready"] += 1
                    create_loads["errored"] |= bool(values.get("create_error"))
            elif loading is True or (
                loading is False
                and values.get("create_error") == ""
                and values.get("upload_error") == ""
                and "route_options" not in values
            ):
                # on_load runs in the server, without a separate sent event.
                # A warm close starts with false and both errors reset; its final
                # data frame includes route_options. Count every concurrent start.
                create_loads["started"] += 1

    def connected(socket) -> None:
        # Attach before the boot hydration can start its on_load handlers.
        # Otherwise an uncounted old background read can satisfy a close.
        socket.on("framereceived", received)

    page.on("websocket", connected)
    with page.expect_websocket() as connection:
        page.goto(f"{app_server}/create?producto={product}")
    socket = connection.value
    monitoring = [False]

    def all_create_data_ready() -> bool:
        # Reflex queues the hydrated flip after dispatching the on_load handlers.
        # Background handlers can outlive that flip, so also drain every read.
        return (
            create_loads["hydrated"]
            and create_loads["started"] > 0
            and create_loads["ready"] == create_loads["started"]
        )

    def remember_step_marker() -> None:
        page.evaluate("""() => {
          if (!window.__ui4PopListener) {
            window.__ui4PopListener = true;
            window.__ui4Pops = 0;
            window.addEventListener('popstate', () => window.__ui4Pops++);
          }
          window.__ui4MarkerObserver?.disconnect();
          window.__ui4StepMarker = document.querySelector('.q-step-sync');
          window.__ui4MarkerRemoved = false;
          window.__ui4MarkerObserver = new MutationObserver(() => {
            if (!window.__ui4StepMarker?.isConnected) window.__ui4MarkerRemoved = true;
          });
          window.__ui4MarkerObserver.observe(document.body, {childList:true, subtree:true});
        }""")
        monitoring[0] = True

    @contextmanager
    def route_load_settled(phase: str, *, same_marker: bool = True, require_new_load: bool = True):
        before = create_loads["started"]
        history_before = {}
        # Drain older concurrent loads before the close, not merely any final
        # false frame after it. No prior invocation may satisfy this barrier.
        try:
            if not all_create_data_ready():
                with socket.expect_event(
                    "framereceived", predicate=lambda _: all_create_data_ready(), timeout=30_000
                ):
                    pass
            assert not create_loads["errored"]
            if same_marker and not monitoring[0]:
                remember_step_marker()
            before = create_loads["started"]
            history_before = page.evaluate("""() => ({search:location.search,
              entry:!!history.state?.qPartEntry,pops:window.__ui4Pops || 0})""")

            def finished(frame: str | bytes) -> bool:
                return create_loads["started"] > before and all_create_data_ready()

            yield
            if require_new_load:
                if not finished(""):
                    with socket.expect_event("framereceived", predicate=finished, timeout=30_000):
                        pass
            else:
                # A native sheet push does not update React's prevLocationRef.
                # These repeated-base POPs close the sheet without a page on_load.
                # Prove the POP/closed URL, and still drain any observed load work.
                expect(page).not_to_have_url(re.compile(r"[?&]parte="))
                page.wait_for_function(
                    "before => window.__ui4Pops > before",
                    arg=history_before["pops"],
                    timeout=5_000,
                )
                page.evaluate(
                    "() => new Promise(done => "
                    "requestAnimationFrame(() => requestAnimationFrame(done)))"
                )
                if not all_create_data_ready():
                    with socket.expect_event(
                        "framereceived", predicate=lambda _: all_create_data_ready(), timeout=30_000
                    ):
                        pass
            assert not create_loads["errored"]
        except playwright_sync.TimeoutError as exc:
            history_after = page.evaluate("""() => ({search:location.search,
              entry:!!history.state?.qPartEntry,pops:window.__ui4Pops || 0})""")
            raise AssertionError(
                f"{phase} create-data barrier: ticket={before}, counts={create_loads}, "
                f"history_before={history_before}, history_after={history_after}"
            ) from exc
        # The wire event precedes React's application of that delta.
        page.evaluate(
            "() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))"
        )
        if same_marker:
            assert page.evaluate("""() => !window.__ui4MarkerRemoved &&
              window.__ui4StepMarker === document.querySelector('.q-step-sync') &&
              window.__ui4StepMarker.isConnected""")

    clip = page.get_by_role("radio", name=re.compile(r"^Clip"))
    # The existing mobile kind picker starts collapsed beside its «Cambiar» button.
    if width < 900:
        toggle = page.locator("[aria-controls=create-kind-options]")
        expect(toggle).to_be_visible(timeout=30_000)
        if not clip.is_visible():
            toggle.click()
    expect(clip).to_be_visible(timeout=30_000)
    clip.click()
    page.get_by_role("button", name="Armar mi video por partes", exact=True).click()
    page.get_by_role("button", name="Prefiero armarlas yo", exact=True).click()
    change = page.get_by_role("button", name="Cambiar la parte 1", exact=True)
    change.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(page).to_have_url(re.compile(r"[?&]parte=1(?:&|$)"))
    expect(page.locator("#q-part-editor-question")).to_be_focused()
    # each «Quitar» names its file after its visible label («Quitar foto <nombre>»)
    expect(dialog.get_by_role("button", name=re.compile(r"^Quitar foto "))).to_have_count(1)
    shots = os.environ.get("QUALIFY_E2E_SHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        dialog.evaluate(
            "async el => { await Promise.all(el.getAnimations().map(a => a.finished)); }"
        )
        (Path(shots) / f"ui4-{width}-metrics.json").write_text(
            json.dumps(
                dialog.evaluate("""el => ({viewport:innerWidth,
              document:document.documentElement.scrollWidth, body:document.body.scrollWidth,
              drawer:el.getBoundingClientRect().toJSON(),translate:getComputedStyle(el).translate})""")
            ),
            encoding="utf-8",
        )
        page.screenshot(path=str(Path(shots) / f"ui4-{width}.png"), full_page=True)
        (Path(shots) / "manual-access.json").write_text(
            json.dumps(
                {
                    "email": page._qualify_e2e_email,
                    "password": "e2e-clave-segura",
                    "url": f"{app_server}/create?producto={product}",
                    "login": f"{app_server}/login",
                }
            ),
            encoding="utf-8",
        )
    for _ in range(18):
        page.keyboard.press("Tab")
        assert dialog.evaluate("el => el.contains(document.activeElement)")
    extend = dialog.get_by_role("radio", name=re.compile("Sigue a la anterior"))
    expect(extend).to_have_attribute("aria-disabled", "true")
    described_by = extend.get_attribute("aria-describedby")
    expect(page.locator(f"#{described_by}")).to_be_visible()
    save = dialog.get_by_role("button", name="Guardar", exact=True)
    expect(save).to_have_attribute("aria-disabled", "true")
    expect(page.locator("#" + save.get_attribute("aria-describedby"))).to_be_visible()
    # an empty part has no original video: an own one is the only way to keep a video,
    # so «Video o audio tuyo» is already open
    more = dialog.get_by_role("button", name="Video o audio tuyo", exact=True)
    expect(more).to_have_attribute("aria-expanded", "true")
    dialog.locator("#part_videos input[type=file]").set_input_files(str(video))
    edit = dialog.get_by_role("radio", name=re.compile(r"^Tu video, con tu marca"))
    reference = dialog.get_by_role("radio", name=re.compile(r"^Nueva, con tu producto"))
    expect(edit).to_have_attribute("aria-disabled", "false", timeout=30_000)
    expect(reference).to_have_attribute("tabindex", "0")
    expect(edit).to_have_attribute("tabindex", "-1")
    reference.focus()
    page.keyboard.press("ArrowLeft")
    expect(edit).to_be_focused()
    expect(edit).to_have_attribute("aria-checked", "true")
    expect(edit).to_have_attribute("tabindex", "0")
    expect(reference).to_have_attribute("tabindex", "-1")
    page.keyboard.press("ArrowRight")
    expect(reference).to_be_focused()
    expect(reference).to_have_attribute("aria-checked", "true")
    dialog.locator("#q-part-more").get_by_role("button", name=re.compile(r"^Quitar video ")).click()
    more.click()
    expect(more).to_have_attribute("aria-expanded", "false")
    dialog.get_by_label("¿Qué pasa en esta parte?").fill("Una mano acerca el vaso")
    with route_load_settled("Save"):
        dialog.get_by_role("button", name="Guardar", exact=True).click()
    expect(dialog).not_to_be_visible()
    expect(change).to_be_focused()
    expect(page.get_by_text("Una mano acerca el vaso", exact=True)).to_be_visible()

    # Editing stays transactional; Esc returns to the same stable row's action.
    change.click()
    expect(dialog).to_be_visible()
    expect(page).to_have_url(re.compile(r"[?&]parte=1(?:&|$)"))
    dialog.get_by_label("¿Qué pasa en esta parte?").fill("Un cambio sin guardar")
    with route_load_settled("Escape", require_new_load=False):
        page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(change).to_be_focused()
    expect(page.get_by_text("Un cambio sin guardar", exact=True)).to_have_count(0)
    change.click()
    expect(dialog).to_be_visible()
    expect(page).to_have_url(re.compile(r"[?&]parte=1(?:&|$)"))
    with route_load_settled("Back", require_new_load=False):
        page.go_back()
    expect(dialog).not_to_be_visible()
    expect(page).not_to_have_url(re.compile(r"[?&]parte="))
    expect(page).to_have_url(re.compile(r"[?&]paso=2(?:&|$)"))
    # Forward opens a route again; its full refresh is deliberately retained.
    page.evaluate("window.__ui4MarkerObserver.disconnect()")
    monitoring[0] = False
    with route_load_settled("Forward", same_marker=False):
        page.go_forward()
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("¿Qué pasa en esta parte?")).to_have_value("Una mano acerca el vaso")
    with route_load_settled("Cancel"):
        dialog.get_by_role("button", name="Cancelar", exact=True).click()
    expect(dialog).not_to_be_visible()
    expect(change).to_be_focused()
    page.evaluate("window.__ui4MarkerObserver.disconnect()")

    # The summary targets the missing row without starting a paid proposal/generation.
    for step in (3, 4, 5):
        page.get_by_role("button", name="Siguiente", exact=True).click()
        expect(page).to_have_url(re.compile(rf"[?&]paso={step}(?:&|$)"))
    page.get_by_role("button", name=re.compile(r"^Escribir qué pasa")).click()
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("heading", name="Parte 2 de 2", exact=True)).to_be_visible()
    expect(page).to_have_url(re.compile(r"[?&]paso=2(?:&|$)"))
    expect(dialog.get_by_label("¿Qué pasa en esta parte?")).to_have_value("")
    dialog.get_by_label("¿Qué pasa en esta parte?").fill("El vaso aparece solo")
    dialog.get_by_role("button", name="Guardar", exact=True).click()
    expect(dialog).not_to_be_visible()

    # Arrow movement is UI-3's keyboard alternative to dragging; identity survives it.
    card = page.locator(".q-part-card").filter(has_text="Una mano acerca el vaso")
    card.focus()
    page.keyboard.press("ArrowRight")
    page.get_by_role("button", name="Cambiar la parte 2", exact=True).click()
    expect(dialog.get_by_label("¿Qué pasa en esta parte?")).to_have_value("Una mano acerca el vaso")
    dialog.get_by_role("button", name="Cancelar", exact=True).click()
    expect(dialog).not_to_be_visible()

    for number in range(3, 7):
        page.get_by_role("button", name="Añadir parte", exact=True).click()
        expect(dialog).to_be_visible()
        dialog.get_by_label("¿Qué pasa en esta parte?").fill(f"Mostramos el vaso {number}")
        dialog.get_by_role("button", name="Guardar", exact=True).click()
        expect(dialog).not_to_be_visible()
    expect(page.get_by_role("button", name="Añadir parte", exact=True)).to_have_attribute(
        "aria-disabled", "true"
    )
    expect(
        page.get_by_text(
            "Tu video ya tiene 6 partes, el máximo. Quita o junta una para añadir otra.",
            exact=True,
        )
    ).to_be_visible()
    assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
    page.goto(f"{app_server}/create?paso=2&parte=99")
    expect(page).not_to_have_url(re.compile(r"[?&]parte="))
    expect(page.get_by_role("dialog")).not_to_be_visible()
