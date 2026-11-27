"""EF-05 (m-25026573): the Python half of the `video_text` template — props, job ids, the
manifest it reads, and how a job's outcome comes back. Offline: a fake render service."""

from __future__ import annotations

import io
from typing import Any
from uuid import uuid4

import pytest
from PIL import Image

from qualify_creative.render.client import RenderJob, RenderServiceError
from qualify_creative.render.registry import TemplateRegistry
from qualify_creative.render.video_text import (
    BACKDROP_PORT,
    BOX_COLOR_LAYOUTS,
    CANVAS,
    DEFAULT_LAYOUT_ID,
    LETTERS_PORT,
    MAX_RENDER_ATTEMPTS,
    PORT,
    SUPPORTED_LAYOUTS,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    TEMPLATE_VERSION_V2,
    V1_LAYOUTS,
    BrandText,
    TextFont,
    VideoTextRefused,
    VideoTextRequest,
    brand_props,
    config_digest,
    heading_font_of,
    layout_version,
    overlay_revision,
    render_video_text,
)
from qualify_creative.schemas import (
    VIDEO_TEXT_BAND_COLOR,
    VIDEO_TEXT_BAND_INK,
    VIDEO_TEXT_BOX_COLOR_LAYOUTS,
    VIDEO_TEXT_BOX_PAD_PX,
    VIDEO_TEXT_BOX_RADIUS_PX,
    VIDEO_TEXT_INK_DARK,
    VIDEO_TEXT_INK_LIGHT,
    VIDEO_TEXT_LAYOUTS,
    VIDEO_TEXT_MAX,
    VIDEO_TEXT_PLACES,
    BrandKit,
    ToneAxes,
)

BRAND = {"name": "La Espiga", "palette": ["#B5532A", "#FFFFFF"], "fonts": {"heading": "Poppins"}}

#: rows the fake draws its «letters» on, per place (inside 270-1536, like the real scrim)
FAKE_ROWS = {"top": (300, 380), "middle": (920, 1000), "bottom": (1440, 1520)}


def fake_png(place: str) -> bytes:
    """A transparent 1080×1920 layer: a 60 % black band and a white block where the place is."""
    img = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    y0, y1 = FAKE_ROWS[place]
    img.paste((0, 0, 0, 153), (0, y0 - 40, CANVAS[0], y1 + 40))
    img.paste((255, 255, 255, 255), (64, y0, 600, y1))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class FakeVideoTextService:
    """`render`/`wait`/`download` of RemotionRenderClient for `video_text`. `outcome`:
    `completed`, `refused`, `failed`, or an exception instance to raise on `render`; a list
    gives one outcome per NEW job. Like the service (`jobs.mjs` `submit`), a job id it already
    holds is answered with that job, finished or not."""

    def __init__(self, outcome: Any = "completed", *, versions: int = 2) -> None:
        self.outcomes = list(outcome) if isinstance(outcome, list) else None
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []
        self.pngs: dict[str, bytes] = {}
        self.jobs: dict[str, RenderJob] = {}
        #: ED-13: the newest `video_text` the service has (its `/health`), uploaded assets
        self.versions = versions
        self.health_calls = 0
        self.assets: dict[str, bytes] = {}

    def health(self) -> dict[str, Any]:
        self.health_calls += 1
        if isinstance(self.versions, BaseException):
            raise self.versions
        return {
            "ok": True,
            "bundleReady": True,
            "templates": [{"id": "video_text", "version": self.versions}],
        }

    def upload_asset(self, data: bytes, *, filename: str, content_type: str) -> Any:
        import hashlib

        from qualify_creative.render.client import AssetRef

        digest = hashlib.sha256(data).hexdigest()
        self.assets[digest] = data
        return AssetRef(asset_id=digest, url=f"http://x/{digest}", mime_type=content_type, bytes=0)

    def render(self, **kwargs: Any) -> RenderJob:
        self.calls.append(kwargs)
        if kwargs["job_id"] in self.jobs:
            return self.jobs[kwargs["job_id"]]
        if self.outcomes is not None:
            self.outcome = self.outcomes.pop(0)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        # a new job starts pending (as on the service); `wait` gives its final state
        self.jobs[kwargs["job_id"]] = self._new_job(**kwargs)
        return RenderJob.from_payload(
            {
                "jobId": kwargs["job_id"],
                "templateId": kwargs["template_id"],
                "version": kwargs["version"],
                "status": "pending",
                "outputs": {
                    port: {"kind": "still", "status": "pending"} for port in kwargs["outputs"]
                },
            }
        )

    def _new_job(self, **kwargs: Any) -> RenderJob:
        texts = kwargs["props"]["texts"]
        place = texts["place"]
        ports = list(kwargs["outputs"])
        out: dict[str, Any] = {
            "kind": "still",
            "status": "completed",
            "width": 1080,
            "height": 1920,
        }
        status = "completed"
        if self.outcome == "completed":
            out["report"] = {
                "template": "video_text",
                "layout_rendered": texts["layout_id"],
                "place": place,
                "lines": texts["text"].split(" ", 1),
                "size": 112,
                "cover": 0.45,
                "engine_revision": 3,
                "overlay_revision": 1,
            }
            if kwargs["version"] >= 2:
                y0, y1 = FAKE_ROWS[place]
                chars = [*texts["text"]]
                out["report"]["letter_boxes"] = [
                    {"x": 64 + 40 * i, "y": y0, "w": 40, "h": y1 - y0, "line": 0}
                    for i in range(len(chars))
                ]
            self.pngs[kwargs["job_id"]] = fake_png(place)
        elif self.outcome == "refused":
            status = "failed"
            out = {
                "kind": "still",
                "status": "failed",
                "failureReason": "invalid_parameters",
                "errorMessage": "invalid_parameters: layer_unrenderable {…}",
                "refusal": {
                    "code": "layer_unrenderable",
                    "slot": "text",
                    "reason": "word_too_wide",
                    "detail": "Supercalifragilístico",
                },
            }
        else:
            status = "failed"
            out = {
                "kind": "still",
                "status": "failed",
                "failureReason": "render_error",
                "errorMessage": "Chromium crashed",
            }
        return RenderJob.from_payload(
            {
                "jobId": kwargs["job_id"],
                "templateId": kwargs["template_id"],
                "version": kwargs["version"],
                "status": status,
                "outputs": {port: out for port in ports},
            }
        )

    def wait(self, job_id: str, **_: Any) -> RenderJob:
        return self.jobs[job_id]

    def download(self, job_id: str, port: str) -> tuple[bytes, str]:
        assert port in self.jobs[job_id].outputs
        # each port its own bytes, so a test can tell them apart
        return self.pngs[job_id] + port.encode(), "image/png"


def _kit(**over: Any) -> BrandKit:
    return BrandKit(
        brand_id=uuid4(),
        positioning="p",
        audience="a",
        tone_axes=ToneAxes(
            formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50
        ),
        **over,
    )


def test_the_manifest_loads_with_its_video_text_block_and_matches_the_editor_limits() -> None:
    manifest = TemplateRegistry.from_dir().get(TEMPLATE_ID, TEMPLATE_VERSION)
    assert set(manifest.outputs) == {PORT}
    out = manifest.outputs[PORT]
    assert (out.width, out.height) == CANVAS
    assert out.composition == "video-text-v1--overlay"
    assert manifest.inputs["text"].max == VIDEO_TEXT_MAX
    assert manifest.inputs["place"].enum == VIDEO_TEXT_PLACES
    assert manifest.inputs["layout_id"].enum == V1_LAYOUTS == (DEFAULT_LAYOUT_ID,)
    # ED-13: v2 draws the four backgrounds of the schemas, and the letters apart
    v2 = TemplateRegistry.from_dir().get(TEMPLATE_ID, TEMPLATE_VERSION_V2)
    assert v2.inputs["layout_id"].enum == SUPPORTED_LAYOUTS == VIDEO_TEXT_LAYOUTS
    assert set(v2.outputs) == {PORT, BACKDROP_PORT, LETTERS_PORT}
    assert all((o.width, o.height) == CANVAS for o in v2.outputs.values())
    block = v2.video_text or {}
    assert block["band"]["pad"] == block["box"]["pad"] == VIDEO_TEXT_BOX_PAD_PX
    assert block["box"]["radius"] == VIDEO_TEXT_BOX_RADIUS_PX
    # «Franja» is a fixed dark neutral strip with white letters, never the brand's surface
    assert (block["band"]["color"], block["band"]["ink"]) == (
        VIDEO_TEXT_BAND_COLOR,
        VIDEO_TEXT_BAND_INK,
    )
    # «Sin fondo» draws clean letters: no text shadow in the manifest (Deivid, 2026-11-23)
    assert "shadow" not in block
    # a picked colour's letters: white or near-black by contrast (the schemas' inks)
    assert block["box_ink"] == {"light": VIDEO_TEXT_INK_LIGHT, "dark": VIDEO_TEXT_INK_DARK}
    assert v2.inputs["box_color"].optional and v2.inputs["box_color"].max == 7
    assert "box_color" not in manifest.inputs
    assert v2.inputs["text_color"].optional and v2.inputs["text_color"].max == 7
    assert "text_color" not in manifest.inputs
    assert overlay_revision(TEMPLATE_VERSION_V2) >= 1
    assert config_digest(TEMPLATE_VERSION_V2) != config_digest()
    # never picked by a post recipe
    assert manifest.serves_angles == ("video_text_overlay",)
    assert overlay_revision() >= 1
    # the catalog the render draws is the layer stage's own (drift test in test_layer_catalog_drift)
    assert layout_version() == 3


def test_props_carry_the_text_place_and_default_design() -> None:
    props = VideoTextRequest(text="  Pan fresco ", place="middle", brand=BRAND).props()
    # every text is drawn by v2, which centres its lines (Deivid 2026-11-24)
    assert props["meta"] == {
        "templateId": TEMPLATE_ID,
        "version": TEMPLATE_VERSION_V2,
        "port": PORT,
    }
    assert props["texts"] == {
        "text": "Pan fresco",
        "place": "middle",
        "layout_id": "scrim",
        "layout_version": layout_version(),
    }
    assert props["brand"] == BRAND


def test_the_job_id_is_deterministic_and_changes_with_every_pixel_input() -> None:
    base = VideoTextRequest(text="Pan fresco", place="top", brand=BRAND)
    assert (
        base.job_id()
        == VideoTextRequest(text="Pan fresco ", place="top", brand=dict(BRAND)).job_id()
    )
    others = [
        VideoTextRequest(text="Pan frescos", place="top", brand=BRAND),
        VideoTextRequest(text="Pan fresco", place="bottom", brand=BRAND),
        VideoTextRequest(
            text="Pan fresco", place="top", brand={**BRAND, "fonts": {"heading": "Lobster"}}
        ),
        VideoTextRequest(text="Pan fresco", place="top", brand={**BRAND, "palette": ["#000000"]}),
        VideoTextRequest(
            text="Pan fresco", place="top", brand=BRAND, layout_id="scrim", layout_version=2
        ),
    ]
    assert len({base.job_id(), *(o.job_id() for o in others)}) == len(others) + 1
    # the brand's name does not move a pixel of the layer
    assert (
        base.job_id()
        == VideoTextRequest(
            text="Pan fresco", place="top", brand={**BRAND, "name": "Otra"}
        ).job_id()
    )


def test_brand_props_from_a_kit_draw_its_one_typeface_and_no_logo() -> None:
    kit = _kit(
        font_heading="Lobster",
        font_body="Inter",
        palette_rgb=("#112233",),
        logo_asset_key="t/x/logo.png",
    )
    assert brand_props(kit) == {
        "name": "",
        "palette": ["#112233"],
        "fonts": {"heading": "Lobster", "body": "Inter"},
        "logo": None,
    }
    only_body = _kit(font_body="Inter")
    assert brand_props(only_body)["fonts"] == {"heading": "Inter", "body": "Inter"}
    assert brand_props({**BRAND, "logo": "asset://x"})["logo"] is None


def test_a_completed_job_returns_the_png_and_its_provenance_at_zero_cost() -> None:
    service = FakeVideoTextService()
    request = VideoTextRequest(text="Pan fresco", place="bottom", brand=BRAND)
    image = render_video_text(service, request)  # type: ignore[arg-type]
    assert Image.open(io.BytesIO(image.png)).mode == "RGBA"
    assert service.calls[0]["outputs"] == [PORT]
    assert image.job_id == request.job_id()
    assert image.provenance == {
        "provider": "remotion",
        "model_id": "remotion_selfhost",
        "template": "video_text@2",
        "layout_id": "scrim",
        "layout_version": layout_version(),
        "engine_revision": 3,
        "overlay_revision": 1,
        "job_id": request.job_id(),
        "render_attempt": 0,
        "config_digest": config_digest(TEMPLATE_VERSION_V2),
        "font_source": "family",
        "font_sha256": None,
        "cost_usd": "0",
    }
    # v2 checks the service has it once and, with no font file, uploads nothing
    assert service.health_calls == 1 and service.assets == {}
    assert image.backdrop_png is None and image.letters_png is None


def test_a_refused_text_raises_the_refusal_with_its_reason() -> None:
    with pytest.raises(VideoTextRefused) as caught:
        render_video_text(
            FakeVideoTextService("refused"),  # type: ignore[arg-type]
            VideoTextRequest(text="Supercalifragilístico", place="top", brand=BRAND),
        )
    assert caught.value.reason == "word_too_wide"
    assert caught.value.code == "invalid_parameters"


def test_a_failed_render_raises_the_service_reason() -> None:
    with pytest.raises(RenderServiceError) as caught:
        render_video_text(
            FakeVideoTextService("failed"),  # type: ignore[arg-type]
            VideoTextRequest(text="Pan", place="top", brand=BRAND),
        )
    assert caught.value.code == "render_error"
    assert not isinstance(caught.value, VideoTextRefused)


def test_a_layout_video_text_v1_does_not_draw_is_refused_before_any_call() -> None:
    service = FakeVideoTextService()
    with pytest.raises(RenderServiceError):
        render_video_text(
            service,  # type: ignore[arg-type]
            VideoTextRequest(
                text="Pan", place="top", brand=BRAND, layout_id="plate", layout_version=3
            ),
        )
    assert service.calls == []


def test_a_retry_after_a_failed_render_renders_afresh_under_a_derived_id() -> None:
    """The service keeps a failed job under its id for a day: the retry must not get it back."""
    service = FakeVideoTextService(["failed", "completed"])
    request = VideoTextRequest(text="Pan fresco", place="top", brand=BRAND)
    with pytest.raises(RenderServiceError) as first:
        render_video_text(service, request)  # type: ignore[arg-type]
    assert first.value.code == "render_error"
    assert service.calls[-1]["job_id"] == request.job_id()
    # «inténtalo de nuevo»: the same request, a moment later
    image = render_video_text(service, request)  # type: ignore[arg-type]
    assert image.job_id == request.attempt_job_id(1) != request.job_id()
    assert image.provenance["render_attempt"] == 1
    assert image.provenance["job_id"] == request.attempt_job_id(1)
    # deterministic: the same derived ids every time, and a third call reuses the good job
    assert request.attempt_job_id(1) == VideoTextRequest(
        text="Pan fresco", place="top", brand=dict(BRAND)
    ).attempt_job_id(1)
    again = render_video_text(service, request)  # type: ignore[arg-type]
    assert again.job_id == image.job_id and again.png == image.png


def test_a_refused_text_is_not_retried_under_another_id() -> None:
    service = FakeVideoTextService(["refused", "completed"])
    request = VideoTextRequest(text="Supercalifragilístico", place="top", brand=BRAND)
    for _ in range(2):
        with pytest.raises(VideoTextRefused):
            render_video_text(service, request)  # type: ignore[arg-type]
    assert {c["job_id"] for c in service.calls} == {request.job_id()}


def test_the_derived_ids_are_capped() -> None:
    service = FakeVideoTextService(["failed"] * (MAX_RENDER_ATTEMPTS + 2))
    request = VideoTextRequest(text="Pan", place="top", brand=BRAND)
    for _ in range(MAX_RENDER_ATTEMPTS + 2):
        with pytest.raises(RenderServiceError):
            render_video_text(service, request)  # type: ignore[arg-type]
    assert len({c["job_id"] for c in service.calls}) == MAX_RENDER_ATTEMPTS


def test_the_manifest_video_text_block_is_part_of_the_job_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qualify_creative.render.video_text as vt

    request = VideoTextRequest(text="Pan", place="top", brand=BRAND)
    before = request.job_id()
    monkeypatch.setattr(vt, "config_digest", lambda *_: "0" * 16)
    assert request.job_id() != before


# ---------------------------------------------------------------- ED-13 (m-25029108)

FONT = TextFont.of(b"\x00\x01\x00\x00" + b"fake-truetype" * 8, key="t/x/brand/heading.ttf")


#: The default text's job id before ED-13 centred every line: v1, left-aligned.
V1_JOB_ID = "87fc619a-f66d-59c4-aad7-564d6a86df26"


def test_a_default_text_gets_a_new_job_now_that_it_is_centred() -> None:
    """Deivid 2026-11-24 «que siempre esté centrado»: the plain «Sombra» text too is drawn
    centred, by v2 — another image, so another job id: the left-aligned PNG cached under v1's
    id is never served for it again."""
    plain = VideoTextRequest(text="Pan fresco", place="top", brand=BRAND)
    assert plain.template_version == TEMPLATE_VERSION_V2
    assert plain.job_id() != V1_JOB_ID
    scrim = VideoTextRequest(
        text="Pan fresco", place="bottom", brand=BRAND, layout_id="scrim", layout_version=3
    )
    assert scrim.job_id() != "aab8f2ee-65ed-5e81-a447-1db4fb4d86a2"


def test_a_background_a_font_file_or_typed_letters_take_v2_and_a_job_of_their_own() -> None:
    base = VideoTextRequest(text="Pan fresco", place="top", brand=BRAND)
    assert base.template_version == TEMPLATE_VERSION_V2 == TEMPLATE_VERSION + 1
    variants = [
        VideoTextRequest(
            text="Pan fresco", place="top", brand=BRAND, layout_id=layout, layout_version=3
        )
        for layout in ("band", "brand_fill", "shadow")
    ]
    with_font = VideoTextRequest(
        text="Pan fresco", place="top", brand=brand_props(BRAND, FONT), font=FONT
    )
    typed = VideoTextRequest(text="Pan fresco", place="top", brand=BRAND, letters=True)
    for request in (*variants, with_font, typed):
        assert request.template_version == TEMPLATE_VERSION_V2
        assert request.props()["meta"]["version"] == 2
    assert typed.ports == (PORT, BACKDROP_PORT, LETTERS_PORT)
    ids = {r.job_id() for r in (base, *variants, with_font, typed)}
    assert len(ids) == 6
    # another font file is another job
    other = TextFont.of(FONT.data + b"x")
    assert (
        VideoTextRequest(
            text="Pan fresco", place="top", brand=brand_props(BRAND, other), font=other
        ).job_id()
        != with_font.job_id()
    )


def test_brand_props_name_the_font_file_by_its_content_and_keep_the_family() -> None:
    kit = _kit(font_heading="Mi Letra", palette_rgb=("#112233",))
    plain = brand_props(kit)
    assert "fontFiles" not in plain
    withfile = brand_props(BrandText(kit, FONT))
    assert withfile["fontFiles"] == {"heading": f"asset://{FONT.sha256}"}
    assert withfile["fonts"] == plain["fonts"] == {"heading": "Mi Letra", "body": "Mi Letra"}
    # the wrapper reads as the kit
    assert BrandText(kit, FONT).brand_id == kit.brand_id
    assert heading_font_of(BrandText(kit, FONT)) == FONT and heading_font_of(kit) is None


def test_a_font_file_is_uploaded_before_the_v2_job_and_recorded() -> None:
    service = FakeVideoTextService()
    request = VideoTextRequest(
        text="Pan fresco",
        place="bottom",
        brand=brand_props(BRAND, FONT),
        font=FONT,
        layout_id="brand_fill",
        layout_version=3,
    )
    image = render_video_text(service, request)  # type: ignore[arg-type]
    assert service.assets == {FONT.sha256: FONT.data}
    assert service.health_calls == 1
    props = service.calls[0]["props"]
    assert props["brand"]["fontFiles"] == {"heading": f"asset://{FONT.sha256}"}
    assert service.calls[0]["version"] == 2
    assert image.provenance["template"] == "video_text@2"
    assert image.provenance["font_source"] == "file"
    assert image.provenance["font_sha256"] == FONT.sha256
    assert image.provenance["layout_id"] == "brand_fill"


def test_typed_letters_come_back_as_three_layers_with_the_letter_boxes() -> None:
    service = FakeVideoTextService()
    request = VideoTextRequest(text="Hola", place="top", brand=BRAND, letters=True)
    image = render_video_text(service, request)  # type: ignore[arg-type]
    assert service.calls[0]["outputs"] == [PORT, BACKDROP_PORT, LETTERS_PORT]
    assert image.png.endswith(b"overlay")
    assert image.backdrop_png is not None and image.backdrop_png.endswith(b"backdrop")
    assert image.letters_png is not None and image.letters_png.endswith(b"letters")
    assert len(image.report["letter_boxes"]) == 4


def test_a_service_without_v2_is_a_service_down_not_our_bug() -> None:
    """Deploy order: an app that asks for v2 of a render service still on v1 waits (503,
    an outage), nothing is submitted."""
    service = FakeVideoTextService(versions=1)
    request = VideoTextRequest(
        text="Pan", place="top", brand=BRAND, layout_id="shadow", layout_version=3
    )
    with pytest.raises(RenderServiceError) as caught:
        render_video_text(service, request)  # type: ignore[arg-type]
    assert caught.value.status == 503
    assert service.calls == []
    # the plain text too: it is drawn by v2 now (centred), so it waits as well
    with pytest.raises(RenderServiceError) as plain:
        render_video_text(service, VideoTextRequest(text="Pan", place="top", brand=BRAND))  # type: ignore[arg-type]
    assert plain.value.status == 503 and service.calls == []


def test_a_font_without_its_bytes_is_refused_before_any_call() -> None:
    service = FakeVideoTextService()
    with pytest.raises(RenderServiceError):
        render_video_text(
            service,  # type: ignore[arg-type]
            VideoTextRequest(text="Pan", place="top", brand=brand_props(BRAND, FONT)),
        )
    assert service.calls == [] and service.assets == {}


def test_the_supported_backgrounds_are_the_schemas() -> None:
    assert SUPPORTED_LAYOUTS == VIDEO_TEXT_LAYOUTS
    assert BOX_COLOR_LAYOUTS == VIDEO_TEXT_BOX_COLOR_LAYOUTS


def test_a_picked_box_colour_travels_and_takes_a_job_of_its_own() -> None:
    """ED-13 (Deivid, 2026-11-23): «Franja» / «Recuadro de tu color» in the owner's colour —
    sent as `texts.box_color`, in the pixel digest and the job id; a text on its default (or
    a colour on a background without a box) keeps the job it had."""
    for layout in ("band", "brand_fill"):
        plain = VideoTextRequest(
            text="Pan fresco", place="top", brand=BRAND, layout_id=layout, layout_version=3
        )
        picked = VideoTextRequest(
            text="Pan fresco",
            place="top",
            brand=BRAND,
            layout_id=layout,
            layout_version=3,
            box_color="#FFE600",
        )
        assert "box_color" not in plain.props()["texts"]
        assert picked.props()["texts"]["box_color"] == "#FFE600"
        assert picked.pixel_digest() != plain.pixel_digest()
        assert picked.job_id() != plain.job_id()
        other = VideoTextRequest(
            text="Pan fresco",
            place="top",
            brand=BRAND,
            layout_id=layout,
            layout_version=3,
            box_color="#2563EB",
        )
        assert other.job_id() != picked.job_id()
    for layout in ("scrim", "shadow"):
        plain = VideoTextRequest(
            text="Pan fresco", place="top", brand=BRAND, layout_id=layout, layout_version=3
        )
        ignored = VideoTextRequest(
            text="Pan fresco",
            place="top",
            brand=BRAND,
            layout_id=layout,
            layout_version=3,
            box_color="#FFE600",
        )
        assert ignored.effective_box_color is None
        assert "box_color" not in ignored.props()["texts"]
        assert ignored.job_id() == plain.job_id()


def test_a_picked_letters_colour_travels_only_without_a_background() -> None:
    """ED-13 round 3 (Deivid, 2026-11-23): «Sin fondo»'s letters in the owner's colour —
    `texts.text_color`, in the digest and the job id, recorded with the piece; white (none)
    or another background keeps the job it had; a bad one is refused before any call."""
    plain = VideoTextRequest(
        text="Pan fresco", place="top", brand=BRAND, layout_id="shadow", layout_version=3
    )
    picked = VideoTextRequest(
        text="Pan fresco",
        place="top",
        brand=BRAND,
        layout_id="shadow",
        layout_version=3,
        text_color="#111111",
    )
    assert "text_color" not in plain.props()["texts"]
    assert picked.props()["texts"]["text_color"] == "#111111"
    assert picked.pixel_digest() != plain.pixel_digest()
    assert picked.job_id() != plain.job_id()
    for layout in ("scrim", "band", "brand_fill"):
        base = VideoTextRequest(
            text="Pan fresco", place="top", brand=BRAND, layout_id=layout, layout_version=3
        )
        ignored = VideoTextRequest(
            text="Pan fresco",
            place="top",
            brand=BRAND,
            layout_id=layout,
            layout_version=3,
            text_color="#111111",
        )
        assert ignored.effective_text_color is None
        assert "text_color" not in ignored.props()["texts"]
        assert ignored.job_id() == base.job_id()
    service = FakeVideoTextService()
    image = render_video_text(service, picked)  # type: ignore[arg-type]
    assert image.provenance["text_color"] == "#111111"
    assert service.calls[0]["props"]["texts"]["text_color"] == "#111111"
    assert "text_color" not in render_video_text(FakeVideoTextService(), plain).provenance  # type: ignore[arg-type]
    bad = FakeVideoTextService()
    with pytest.raises(RenderServiceError) as caught:
        render_video_text(
            bad,  # type: ignore[arg-type]
            VideoTextRequest(
                text="Pan",
                place="top",
                brand=BRAND,
                layout_id="shadow",
                layout_version=3,
                text_color="#111",
            ),
        )
    assert caught.value.code == "invalid_parameters"
    assert bad.calls == []


def test_a_picked_box_colour_is_recorded_and_a_bad_one_refused_before_any_call() -> None:
    service = FakeVideoTextService()
    request = VideoTextRequest(
        text="Pan fresco",
        place="top",
        brand=BRAND,
        layout_id="band",
        layout_version=3,
        box_color="#FFE600",
    )
    image = render_video_text(service, request)  # type: ignore[arg-type]
    assert image.provenance["box_color"] == "#FFE600"
    assert service.calls[0]["props"]["texts"]["box_color"] == "#FFE600"
    plain = render_video_text(
        FakeVideoTextService(),  # type: ignore[arg-type]
        VideoTextRequest(
            text="Pan fresco", place="top", brand=BRAND, layout_id="band", layout_version=3
        ),
    )
    assert "box_color" not in plain.provenance
    bad = FakeVideoTextService()
    with pytest.raises(RenderServiceError) as caught:
        render_video_text(
            bad,  # type: ignore[arg-type]
            VideoTextRequest(
                text="Pan",
                place="top",
                brand=BRAND,
                layout_id="brand_fill",
                layout_version=3,
                box_color="#ffe600",
            ),
        )
    assert caught.value.code == "invalid_parameters"
    assert bad.calls == []


def test_a_picked_size_takes_a_job_of_its_own_and_mediana_is_the_plain_text() -> None:
    """ED-13 round 4 (Deivid, 2026-11-23: «3 tamaños»): «Pequeña» / «Grande» travel as
    `texts.text_size`, in the pixel digest and the job id; «Mediana» sends nothing, so it is
    the plain text's job."""
    medium = VideoTextRequest(text="Pan fresco", place="top", brand=BRAND, text_size="medium")
    assert medium.job_id() == VideoTextRequest(text="Pan fresco", place="top", brand=BRAND).job_id()
    assert medium.template_version == TEMPLATE_VERSION_V2
    assert "text_size" not in medium.props()["texts"]
    ids = {medium.job_id()}
    for size in ("small", "large"):
        picked = VideoTextRequest(text="Pan fresco", place="top", brand=BRAND, text_size=size)
        assert picked.template_version == 2
        assert picked.props()["texts"]["text_size"] == size
        assert picked.pixel_digest() != medium.pixel_digest()
        ids.add(picked.job_id())
    assert len(ids) == 3
