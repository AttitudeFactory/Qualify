"""EF-05 (m-25026573): `video_pipeline.compose` — the owner's texts over an assembled video.

Offline: a fake render service draws the layers; the overlay itself is the real PyAV code on
a small synthetic 9:16 video. The pixels of the real render (fonts, safe zones, the same look
as an ADR 49 image) are covered by `packages/render/server/video-text.test.mjs` and the EF-05
evidence renders."""

from __future__ import annotations

import io
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from qualify_creative.render.client import RenderJob, RenderServiceError
from qualify_creative.schemas import VideoTextLayer
from qualify_creative.video.text_overlay import decoded_frame_hashes

from qualify_api.creative.video_pipeline.compose import (
    COMPOSE_VERSION,
    FADE_IN_SECONDS,
    OWNER_MESSAGE_REJECTED,
    OWNER_MESSAGE_UNAVAILABLE,
    ComposeRejected,
    ComposeUnavailable,
    TextLayerRefused,
    compose_text_layers,
    fade_in_seconds,
)

av = pytest.importorskip("av")
httpx = pytest.importorskip("httpx")

BRAND = {"name": "La Espiga", "palette": ["#B5532A"], "fonts": {"heading": "Poppins"}}
ROWS = {"top": (300, 380), "middle": (920, 1000), "bottom": (1440, 1520)}
EIGHTY = "Pan de masa madre recién horneado, café de origen y postres caseros todos los días"


def _png(place: str) -> bytes:
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    y0, y1 = ROWS[place]
    img.paste((0, 0, 0, 153), (0, y0 - 40, 1080, y1 + 40))
    img.paste((255, 255, 255, 255), (64, y0, 600, y1))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class FakeService:
    def __init__(self, outcome: Any = "completed") -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []
        self.pngs: dict[str, bytes] = {}
        self.jobs: dict[str, RenderJob] = {}

    def render(self, **kw: Any) -> RenderJob:
        self.calls.append(kw)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if kw["job_id"] in self.jobs:  # as the service: a known id gets its job back
            return self.jobs[kw["job_id"]]
        texts = kw["props"]["texts"]
        if self.outcome == "failed":
            out = {"kind": "still", "status": "failed", "failureReason": "render_error"}
            status = "failed"
        elif self.outcome == "refused":
            out = {
                "kind": "still",
                "status": "failed",
                "failureReason": "invalid_parameters",
                "errorMessage": "refused",
                "refusal": {"slot": "text", "reason": "word_too_wide", "detail": "x"},
            }
            status = "failed"
        else:
            self.pngs[kw["job_id"]] = _png(texts["place"])
            out = {
                "kind": "still",
                "status": "completed",
                "width": 1080,
                "height": 1920,
                "report": {
                    "layout_rendered": texts["layout_id"],
                    "place": texts["place"],
                    "lines": [texts["text"]],
                    "size": 112,
                    "cover": 0.45,
                    "engine_revision": 3,
                    "overlay_revision": 1,
                },
            }
            status = "completed"
        self.jobs[kw["job_id"]] = RenderJob.from_payload(
            {
                "jobId": kw["job_id"],
                "templateId": kw["template_id"],
                "version": kw["version"],
                "status": status,
                "outputs": {"overlay": out},
            }
        )
        # a new job starts pending, as on the service; `wait` gives its final state
        return RenderJob.from_payload(
            {
                "jobId": kw["job_id"],
                "templateId": kw["template_id"],
                "version": kw["version"],
                "status": "pending",
                "outputs": {"overlay": {"kind": "still", "status": "pending"}},
            }
        )

    def wait(self, job_id: str, **_: Any) -> RenderJob:
        return self.jobs[job_id]

    def download(self, job_id: str, port: str) -> tuple[bytes, str]:
        return self.pngs[job_id], "image/png"


def _video(path: Path, seconds: float = 2.0) -> Path:
    with av.open(str(path), mode="w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=30)
        stream.width, stream.height = 216, 384
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "18", "preset": "fast", "threads": "1"}
        stream.codec_context.time_base = Fraction(1, 30)
        for i in range(round(seconds * 30)):
            frame = av.VideoFrame.from_ndarray(
                np.full((384, 216, 3), 40 + i % 20, dtype=np.uint8), format="rgb24"
            )
            frame.pts = i
            frame.time_base = Fraction(1, 30)
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return path


def _three() -> tuple[VideoTextLayer, ...]:
    return (
        VideoTextLayer(text="Pan fresco", place="top", start_s=0.0, end_s=1.2),
        VideoTextLayer(
            text="Abrimos a las 7", place="middle", start_s=0.5, layout_id="scrim", layout_version=3
        ),
        VideoTextLayer(text=EIGHTY, place="bottom", start_s=1.0),
    )


def test_without_text_the_stage_does_not_run(tmp_path: Path) -> None:
    src = _video(tmp_path / "in.mp4", 0.5)
    before = src.read_bytes()
    out = tmp_path / "out.mp4"

    def factory() -> Any:
        raise AssertionError("no render client without a text")

    result = compose_text_layers(src, out, (), BRAND, render_client=factory)
    assert result.composed is False
    assert result.path == src
    assert result.params == {}
    assert not out.exists()
    assert src.read_bytes() == before


def test_three_texts_are_composed_with_their_provenance_and_no_cost(tmp_path: Path) -> None:
    src = _video(tmp_path / "in.mp4")
    service = FakeService()
    result = compose_text_layers(
        src, tmp_path / "out.mp4", _three(), BRAND, render_client=lambda: service
    )
    assert result.composed and result.path == tmp_path / "out.mp4" and result.path.exists()
    assert len(service.calls) == 3
    assert [c["props"]["texts"]["place"] for c in service.calls] == ["top", "middle", "bottom"]
    # a text without a design is drawn with the default one, the scrim at the catalog version
    assert service.calls[0]["props"]["texts"]["layout_id"] == "scrim"
    assert service.calls[0]["props"]["texts"]["layout_version"] == 3
    block = result.params["text_layers"]
    assert block["compose_version"] == COMPOSE_VERSION
    assert block["fade_default_s"] == FADE_IN_SECONDS == 0.5
    assert block["cost_usd"] == "0"
    assert block["x264"]["threads"] == "1"
    assert block["frames"] == 60
    first = block["layers"][0]
    for key in (
        "template",
        "layout_id",
        "layout_version",
        "engine_revision",
        "overlay_revision",
        "job_id",
    ):
        assert key in first, key
    assert first["template"] == "video_text@2"  # every text is drawn centred, by v2
    assert first["provider"] == "remotion" and first["cost_usd"] == "0"
    assert [layer["place"] for layer in block["layers"]] == ["top", "middle", "bottom"]
    assert block["layers"][2]["end_s"] is None
    # each text is identified by its hash, its PNG too, and the line breaks drawn are kept
    assert len(block["layers"][2]["text_sha256"]) == 64
    assert len(block["layers"][2]["png_sha256"]) == 64
    assert block["layers"][2]["lines"] == [EIGHTY]


def test_the_same_video_and_recipe_composed_twice_give_the_same_frames(tmp_path: Path) -> None:
    src = _video(tmp_path / "in.mp4")
    a = compose_text_layers(src, tmp_path / "a.mp4", _three(), BRAND, render_client=FakeService())
    b = compose_text_layers(src, tmp_path / "b.mp4", _three(), BRAND, render_client=FakeService())
    assert decoded_frame_hashes(a.path) == decoded_frame_hashes(b.path)
    assert a.params == b.params


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        RenderServiceError("timeout", 504, "not finished after 180s"),
        RenderServiceError("render_error", 500, "Chromium crashed"),
    ],
    ids=["down", "timeout", "render_error"],
)
def test_with_the_render_service_failing_the_piece_fails_without_charging(
    tmp_path: Path, error: Exception
) -> None:
    src = _video(tmp_path / "in.mp4", 0.5)
    before = src.read_bytes()
    out = tmp_path / "out.mp4"
    with pytest.raises(ComposeUnavailable) as caught:
        compose_text_layers(src, out, _three(), BRAND, render_client=FakeService(error))
    exc = caught.value
    assert exc.code == "text_layer_unavailable"
    assert exc.charge is False
    assert exc.transient is True
    assert exc.owner_message == OWNER_MESSAGE_UNAVAILABLE
    # Spanish, says it is not the owner's doing and that nothing was charged
    assert "No se descontó" in exc.owner_message
    for blame in ("tu error", "revisa", "verifica", "incorrect", "inválid"):
        assert blame not in exc.owner_message.lower()
    # nothing written, the input kept as it was
    assert not out.exists() and not (tmp_path / "out.mp4.partial").exists()
    assert src.read_bytes() == before


def test_a_text_the_render_refuses_names_which_one(tmp_path: Path) -> None:
    src = _video(tmp_path / "in.mp4", 0.5)
    with pytest.raises(TextLayerRefused) as caught:
        compose_text_layers(
            src, tmp_path / "out.mp4", _three()[:1], BRAND, render_client=FakeService("refused")
        )
    assert caught.value.index == 0
    assert caught.value.reason == "word_too_wide"
    assert caught.value.charge is False
    assert caught.value.owner_message == (
        "El texto 1 («Pan fresco») tiene una palabra demasiado larga para la pantalla. "
        "Cámbiala por una más corta o pártela en dos, y vuelve a intentarlo."
    )
    assert not (tmp_path / "out.mp4").exists()


def test_the_fade_lasts_its_fixed_time_or_a_third_of_a_short_text() -> None:
    """ED-13 (Deivid, 2026-11-23): an animation takes at most a THIRD of the text's time on
    screen (the fade in used to take up to half)."""
    assert 0.3 <= FADE_IN_SECONDS <= 1.0
    assert fade_in_seconds(VideoTextLayer(text="a", start_s=0, end_s=3)) == FADE_IN_SECONDS
    assert fade_in_seconds(VideoTextLayer(text="a", start_s=1, end_s=1.6)) == pytest.approx(0.2)
    late = VideoTextLayer(text="a", start_s=2)
    assert fade_in_seconds(late, video_seconds=2.4) == pytest.approx(0.4 / 3, abs=1e-6)
    assert fade_in_seconds(VideoTextLayer(text="a", start_s=2)) == FADE_IN_SECONDS


def test_a_text_refused_for_another_reason_is_named_by_number_and_text() -> None:
    exc = TextLayerRefused(1, "title_does_not_fit", "", "Abrimos  a las 7")
    assert exc.owner_message == (
        "El texto 2 («Abrimos a las 7») no cabe en la pantalla. Acórtalo y vuelve a intentarlo."
    )


@pytest.mark.parametrize(
    "error",
    [
        RenderServiceError("invalid_parameters", 422, "texts.layout_version: stale"),
        RenderServiceError("not_found", 422, "unknown asset"),
    ],
    ids=["invalid_parameters", "http_422"],
)
def test_a_render_rejection_is_not_transient_and_promises_no_retry(
    tmp_path: Path, error: Exception
) -> None:
    src = _video(tmp_path / "in.mp4", 0.5)
    with pytest.raises(ComposeRejected) as caught:
        compose_text_layers(
            src, tmp_path / "out.mp4", _three(), BRAND, render_client=FakeService(error)
        )
    exc = caught.value
    assert isinstance(exc, ComposeUnavailable)
    assert exc.code == "text_layer_rejected"
    assert exc.transient is False and exc.charge is False
    assert exc.owner_message == OWNER_MESSAGE_REJECTED
    assert "intent" not in exc.owner_message.lower()
    assert "No se descontó de tus creaciones" in exc.owner_message
    assert not (tmp_path / "out.mp4").exists()


def test_a_render_client_factory_that_fails_is_a_failure_without_charging(tmp_path: Path) -> None:
    src = _video(tmp_path / "in.mp4", 0.5)

    def factory() -> Any:
        raise RuntimeError("QUALIFY_RENDER_URL is not set")

    with pytest.raises(ComposeUnavailable) as caught:
        compose_text_layers(src, tmp_path / "out.mp4", _three(), BRAND, render_client=factory)
    assert caught.value.charge is False and caught.value.transient is True
    assert not (tmp_path / "out.mp4").exists()


def test_a_retry_after_a_failed_render_composes(tmp_path: Path) -> None:
    """The service keeps the failed job under its id: «inténtalo de nuevo» must render again."""
    src = _video(tmp_path / "in.mp4", 0.5)
    service = FakeService("failed")
    layers = _three()[:1]
    with pytest.raises(ComposeUnavailable) as first:
        compose_text_layers(src, tmp_path / "out.mp4", layers, BRAND, render_client=service)
    assert first.value.transient is True
    service.outcome = "completed"
    result = compose_text_layers(src, tmp_path / "out.mp4", layers, BRAND, render_client=service)
    assert result.composed
    layer = result.params["text_layers"]["layers"][0]
    assert layer["render_attempt"] == 1
    assert layer["job_id"] != service.calls[0]["job_id"]


def test_the_input_video_is_fingerprinted_in_the_provenance(tmp_path: Path) -> None:
    import hashlib

    src = _video(tmp_path / "in.mp4", 0.5)
    result = compose_text_layers(
        src, tmp_path / "out.mp4", _three()[:1], BRAND, render_client=FakeService()
    )
    assert (
        result.params["text_layers"]["source_sha256"]
        == hashlib.sha256(src.read_bytes()).hexdigest()
    )


def test_the_fade_counts_until_the_video_ends_when_that_comes_first() -> None:
    late = VideoTextLayer(text="a", start_s=2.0, end_s=10.0)
    assert fade_in_seconds(late, video_seconds=2.4) == pytest.approx(0.4 / 3, abs=1e-6)
    assert fade_in_seconds(late, video_seconds=20.0) == FADE_IN_SECONDS


def test_each_text_fades_over_its_own_chosen_time_recorded_in_the_provenance(
    tmp_path: Path,
) -> None:
    """Deivid, 2026-11-16 («Que el dueño elija»): the owner picks 0.3-1.0 s per text."""
    src = _video(tmp_path / "in.mp4", 3.0)
    layers = (
        VideoTextLayer(text="Pan fresco", place="top", start_s=0.0, fade_s=0.3),
        VideoTextLayer(text="Abrimos a las 7", place="bottom", start_s=0.0, end_s=3.0, fade_s=1.0),
        VideoTextLayer(text="Hoy", place="middle", start_s=2.0, end_s=2.6, fade_s=1.0),
    )
    result = compose_text_layers(
        src, tmp_path / "out.mp4", layers, BRAND, render_client=FakeService()
    )
    block = result.params["text_layers"]["layers"]
    assert [(x["fade_s"], x["fade_in_s"]) for x in block] == [(0.3, 0.3), (1.0, 1.0), (1.0, 0.2)]
    # a text from before ED-13 enters with a fade and is cut at its end
    assert {(x["motion_in"], x["motion_out"], x["fade_out_s"]) for x in block} == {
        ("fade", "none", 0.0)
    }
    # the fade never reaches the render: same PNG job for any fade
    other = compose_text_layers(
        src,
        tmp_path / "other.mp4",
        (layers[0].model_copy(update={"fade_s": 0.8}),),
        BRAND,
        render_client=FakeService(),
    )
    assert other.params["text_layers"]["layers"][0]["job_id"] == block[0]["job_id"]


def _block_level(path: Path, rows: slice) -> list[float]:
    with av.open(str(path)) as src:
        return [
            float(f.to_ndarray(format="gray")[rows, 20:110].mean())
            for f in src.decode(src.streams.video[0])
        ]


def test_a_different_fade_gives_a_different_alpha_ramp(tmp_path: Path) -> None:
    # 3 s: the 1.0 s fade fits in a third of the text's time (ED-13)
    src = _video(tmp_path / "in.mp4", 3.0)
    rows = slice(62, 74)  # the fake's white block of «top» (canvas 300-380) at 216×384
    levels = {}
    for fade in (0.3, 1.0):
        out = compose_text_layers(
            src,
            tmp_path / f"out-{fade}.mp4",
            (VideoTextLayer(text="Pan", place="top", start_s=0.0, fade_s=fade),),
            BRAND,
            render_client=FakeService(),
        )
        levels[fade] = _block_level(out.path, rows)
    # at 0.4 s (frame 12) the 0.3 s fade is complete, the 1.0 s one is under half way
    assert levels[0.3][12] > 230
    assert levels[1.0][12] < 200 < levels[0.3][12]
    # the slow ramp keeps rising until 1 s, then both are full
    assert levels[1.0][6] < levels[1.0][12] < levels[1.0][24]
    assert levels[1.0][32] > 230 and levels[0.3][32] > 230
