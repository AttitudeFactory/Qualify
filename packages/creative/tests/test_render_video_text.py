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
    CANVAS,
    DEFAULT_LAYOUT_ID,
    MAX_RENDER_ATTEMPTS,
    PORT,
    SUPPORTED_LAYOUTS,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    VideoTextRefused,
    VideoTextRequest,
    brand_props,
    config_digest,
    layout_version,
    overlay_revision,
    render_video_text,
)
from qualify_creative.schemas import (
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

    def __init__(self, outcome: Any = "completed") -> None:
        self.outcomes = list(outcome) if isinstance(outcome, list) else None
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []
        self.pngs: dict[str, bytes] = {}
        self.jobs: dict[str, RenderJob] = {}

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
                "outputs": {PORT: {"kind": "still", "status": "pending"}},
            }
        )

    def _new_job(self, **kwargs: Any) -> RenderJob:
        texts = kwargs["props"]["texts"]
        place = texts["place"]
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
                "outputs": {PORT: out},
            }
        )

    def wait(self, job_id: str, **_: Any) -> RenderJob:
        return self.jobs[job_id]

    def download(self, job_id: str, port: str) -> tuple[bytes, str]:
        assert port == PORT
        return self.pngs[job_id], "image/png"


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
    assert manifest.inputs["layout_id"].enum == SUPPORTED_LAYOUTS == (DEFAULT_LAYOUT_ID,)
    # never picked by a post recipe
    assert manifest.serves_angles == ("video_text_overlay",)
    assert overlay_revision() >= 1
    # the catalog the render draws is the layer stage's own (drift test in test_layer_catalog_drift)
    assert layout_version() == 3


def test_props_carry_the_text_place_and_default_design() -> None:
    props = VideoTextRequest(text="  Pan fresco ", place="middle", brand=BRAND).props()
    assert props["meta"] == {"templateId": TEMPLATE_ID, "version": TEMPLATE_VERSION, "port": PORT}
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
        "template": "video_text@1",
        "layout_id": "scrim",
        "layout_version": layout_version(),
        "engine_revision": 3,
        "overlay_revision": 1,
        "job_id": request.job_id(),
        "render_attempt": 0,
        "config_digest": config_digest(),
        "cost_usd": "0",
    }


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
    monkeypatch.setattr(vt, "config_digest", lambda: "0" * 16)
    assert request.job_id() != before
