"""Recipe D — seasonal videos drawn by the Remotion render service (m-25016848), offline.

The render service is faked: a client that answers `/health`, takes uploads and hands back
an MP4. Where FFmpeg (with libx264) is on PATH the MP4 is a real one, made here, and goes
through recipe B's re-encode and checks; elsewhere those cases are skipped and the encode
is replaced by a stub. No network, no R2, no Chromium."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image, ImageDraw

from qualify_creative.render.manifest import TemplateManifest
from qualify_creative.render.registry import TemplateRegistry, default_templates_dir
from qualify_creative.seasonal import (
    PIPELINE_VERSION_B,
    PIPELINE_VERSION_D,
    BrandLook,
    RecipeError,
    run_recipe,
    video_d,
)
from qualify_creative.seasonal import recipes as recipes_mod
from qualify_creative.seasonal.errors import FFMPEG_FAILED, NO_SOURCE
from qualify_creative.seasonal.ffmpeg import has_encoder
from qualify_creative.seasonal.video import VIDEO_RECIPES, VideoResult, probe
from qualify_creative.seasonal.video_d import (
    LOGO_ONLY_HEIGHT,
    MOTION_OF,
    RemotionVideoRenderer,
    VideoRenderError,
    card_for,
    make_video_d,
    photo_jpeg,
    plan,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_x264 = pytest.mark.skipif(
    not (HAS_FFMPEG and has_encoder("libx264")), reason="ffmpeg with libx264 not on PATH"
)


def _logo(fill: tuple[int, int, int, int] = (200, 30, 30, 255)) -> Image.Image:
    logo = Image.new("RGBA", (600, 300), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rounded_rectangle((10, 10, 590, 290), 40, fill=fill)
    return logo


def _photo(color: tuple[int, int, int], size: tuple[int, int] = (1080, 1350)) -> Image.Image:
    image = Image.new("RGB", size, color)
    ImageDraw.Draw(image).ellipse((200, 200, 800, 800), fill=(250, 250, 250))
    return image


def _look(**kw: Any) -> BrandLook:
    kw.setdefault("logo", _logo())
    return BrandLook(primary=(122, 31, 92), secondary=(246, 195, 67), **kw)


def _mp4(path: Path, size: tuple[int, int], seconds: float = 4.0) -> bytes:
    """What the service sends: an H.264 MP4 (High profile, B-frames, like Remotion's)."""
    width, height = size
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate=24:duration={seconds}",
            "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path.read_bytes()


class FakeClient:
    def __init__(
        self,
        *,
        health: Mapping[str, Any] | Exception | None = None,
        status: str = "completed",
        clip: bytes = b"",
        render_error: Exception | None = None,
    ) -> None:
        self._health = health
        self._status = status
        self._clip = clip
        self._render_error = render_error
        self.uploads: list[tuple[str, str, int]] = []
        self.renders: list[dict[str, Any]] = []

    def health(self) -> Mapping[str, Any]:
        if isinstance(self._health, Exception):
            raise self._health
        return self._health or {
            "ok": True,
            "bundleReady": True,
            "templates": [{"id": "sticker", "version": 1}, {"id": "seasonal_video", "version": 1}],
        }

    def upload_asset(self, data: bytes, *, filename: str, content_type: str) -> Any:
        self.uploads.append((filename, content_type, len(data)))
        return SimpleNamespace(ref=f"asset://{len(self.uploads):064x}")

    def render(self, **kw: Any) -> Any:
        if self._render_error:
            raise self._render_error
        self.renders.append(kw)
        return SimpleNamespace(job_id=kw["job_id"])

    def wait(self, job_id: str, *, timeout_seconds: float = 0) -> Any:
        failure = SimpleNamespace(failure_reason="timeout") if self._status == "failed" else None
        return SimpleNamespace(status=SimpleNamespace(value=self._status), first_failure=failure)

    def download(self, job_id: str, port: str) -> tuple[bytes, str]:
        assert port == "clip"
        return self._clip, "video/mp4"


def _renderer(client: FakeClient) -> RemotionVideoRenderer:
    return RemotionVideoRenderer(client, job_ids=lambda: "job-1")


def _stub_result(path: Path, size: tuple[int, int]) -> VideoResult:
    path.write_bytes(b"\x00" * 1000)
    return VideoResult(path, size[0], size[1], 4000, 96, 1000, 28, False)


# --- the manifest ---------------------------------------------------------------------------


def test_the_manifest_matches_the_slots() -> None:
    path = default_templates_dir() / "seasonal_video" / "manifest.json"
    manifest = TemplateManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert manifest.outputs["clip"].composition == "seasonal-video-v1--clip"
    assert manifest.outputs["clip"].width == 720
    assert set(manifest.inputs["motion"].enum or ()) == set(MOTION_OF.values())
    assert set(MOTION_OF) == set(VIDEO_RECIPES)
    # one Chromium tab: the container's memory cap (docs/modelos-generativos/pruebas.md)
    assert manifest.render is not None and manifest.render.concurrency == 1


def test_the_video_template_is_never_offered_for_a_post() -> None:
    registry = TemplateRegistry.from_dir()
    assert registry.get("seasonal_video").version == 1
    for angle in ("product", "promotion", "price"):
        assert "seasonal_video" not in {m.id for m in registry.for_post(angle=angle, niche=None)}


# --- sources and size: the same rules as recipe B -------------------------------------------


def test_plan_follows_recipe_b() -> None:
    look = _look()
    used, size = plan("b-xfade", [_photo((1, 2, 3))] * 4, look)
    assert len(used) == 3 and size == (720, 900)  # 4:5 photo
    _, size = plan("b-zoom", [_photo((1, 2, 3), (2000, 1000))], look)
    assert size == (720, 720)  # landscape → square, like B
    _, size = plan("b-logo", [], look)
    assert size == (720, LOGO_ONLY_HEIGHT)
    with pytest.raises(RecipeError) as exc:
        plan("b-xfade", [_photo((1, 2, 3))], look)
    assert exc.value.code == NO_SOURCE
    with pytest.raises(RecipeError) as exc:
        plan("b-logo", [], _look(logo=None))
    assert exc.value.code == NO_SOURCE


def test_a_source_problem_never_calls_the_service(tmp_path: Path) -> None:
    client = FakeClient()
    with pytest.raises(RecipeError) as exc:
        make_video_d("b-zoom", [], _look(), tmp_path, renderer=_renderer(client))
    assert exc.value.code == NO_SOURCE
    assert client.uploads == [] and client.renders == []


def test_photos_travel_cropped_to_the_frame_and_never_upscaled() -> None:
    big = Image.open(io.BytesIO(photo_jpeg(_photo((9, 9, 9), (1600, 2000)), (720, 900))))
    assert big.size == (936, 1170)
    small = Image.open(io.BytesIO(photo_jpeg(_photo((9, 9, 9), (500, 500)), (720, 900))))
    assert small.size[0] <= 500 and abs(small.size[0] / small.size[1] - 0.8) < 0.01


# --- the logo card's colour: the sticker's contrast rule ------------------------------------


def test_a_dark_logo_sits_on_white_and_a_light_one_on_the_brand_dark() -> None:
    assert card_for(_look()).fill == "#FFFFFF"
    light = _look(logo=_logo((255, 255, 255, 255)), palette=("#0B1F3A", "#F6C343"))
    card = card_for(light)
    assert card.fill.lower() == "#0b1f3a" and card.reason == "light_art"
    # a dark wordmark (40 %) beside a white emblem (60 %): the dark card would hide the
    # wordmark → white
    mixed = Image.new("RGBA", (640, 340), (0, 0, 0, 0))  # a transparent margin around
    ImageDraw.Draw(mixed).rectangle((20, 20, 260, 320), fill=(11, 31, 58, 255))
    ImageDraw.Draw(mixed).rectangle((260, 20, 620, 320), fill=(255, 255, 255, 255))
    card = card_for(_look(logo=mixed, palette=("#0B1F3A", "#F6C343")))
    assert (card.fill, card.reason) == ("#FFFFFF", "mixed_logo")
    opaque = _look(logo=Image.new("RGBA", (300, 300), (255, 255, 255, 255)))
    assert card_for(opaque).reason == "opaque_logo"


# --- the props --------------------------------------------------------------------------------


def test_props_carry_motion_size_card_palette_and_font() -> None:
    look = _look(family="Fraunces", palette=("#7A1F5C", "#F6C343", "#0B1F3A"))
    props = RemotionVideoRenderer.props(
        "b-pan", look, height=900, photo_refs=["asset://p"], logo_ref="asset://l", card="#FFFFFF"
    )
    assert props["texts"] == {"motion": "recorrer", "height": 900, "card": "#FFFFFF"}
    assert props["photos"] == ["asset://p"]
    assert props["brand"]["logo"] == "asset://l"
    assert props["brand"]["fonts"] == {"heading": "Fraunces"}
    assert props["brand"]["palette"] == ["#7a1f5c", "#f6c343", "#0B1F3A"]


@needs_x264
def test_a_render_uploads_once_and_comes_back_in_whatsapps_profile(tmp_path: Path) -> None:
    clip = _mp4(tmp_path / "service.mp4", (720, 900))
    client = FakeClient(clip=clip)
    work = tmp_path / "work"
    work.mkdir()
    photos = [_photo((200, 40, 40)), _photo((40, 200, 40)), _photo((40, 40, 200))]
    video = make_video_d("b-xfade", photos, _look(), work, renderer=_renderer(client))
    assert [u[0] for u in client.uploads] == ["photo0.jpg", "photo1.jpg", "photo2.jpg", "logo.png"]
    (render,) = client.renders
    assert render["template_id"] == "seasonal_video" and render["outputs"] == ["clip"]
    assert render["props"]["texts"]["motion"] == "fundido"
    assert (video.width, video.height) == (720, 900)
    stream = next(s for s in probe(video.path)["streams"] if s["codec_type"] == "video")
    assert stream["profile"] == "Main" and int(stream.get("has_b_frames") or 0) == 0


@needs_x264
def test_through_run_recipe_d_is_recorded_as_the_engine(tmp_path: Path) -> None:
    clip = _mp4(tmp_path / "service.mp4", (720, 900))
    out = run_recipe(
        "b-zoom",
        _look(),
        tmp_path,
        images=[_photo((200, 40, 40))],
        video_renderer=_renderer(FakeClient(clip=clip)),
    )
    assert out.pipeline_version == PIPELINE_VERSION_D == "seasonal-d-1"
    assert (out.engine, out.fallback) == ("remotion", "")
    assert out.encoding.startswith("remotion+libx264 crf=")
    assert out.cost_usd == 0.0


@needs_x264
def test_a_clip_of_the_wrong_size_falls_back(tmp_path: Path) -> None:
    clip = _mp4(tmp_path / "service.mp4", (720, 1280))
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(VideoRenderError) as exc:
        make_video_d(
            "b-zoom", [_photo((1, 1, 1))], _look(), work, renderer=_renderer(FakeClient(clip=clip))
        )
    assert exc.value.code == "bad_output"


# --- falling back to recipe B -----------------------------------------------------------------


@pytest.fixture
def fake_b(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Recipe B replaced by a stub (no FFmpeg needed): records the slots it drew."""
    drawn: list[str] = []

    def make_video(recipe: str, images: Any, look: Any, work: Path) -> VideoResult:
        drawn.append(recipe)
        return _stub_result(work / "b.mp4", (720, 900))

    monkeypatch.setattr(recipes_mod, "make_video", make_video)
    return drawn


@pytest.mark.parametrize(
    ("client", "code"),
    [
        (FakeClient(health=ConnectionError("Name or service not known")), "unreachable"),
        (FakeClient(health={"ok": True, "bundleReady": False}), "not_ready"),
        (
            FakeClient(health={"ok": True, "bundleReady": True, "templates": [{"id": "sticker"}]}),
            "no_template",
        ),
        (FakeClient(status="failed"), "render_failed"),
        (FakeClient(render_error=TimeoutError("read timed out")), "render_failed"),
        (FakeClient(clip=b""), "bad_output"),
    ],
)
def test_every_service_failure_falls_back_to_b(
    client: FakeClient, code: str, fake_b: list[str], tmp_path: Path
) -> None:
    out = run_recipe(
        "b-zoom", _look(), tmp_path, images=[_photo((1, 1, 1))], video_renderer=_renderer(client)
    )
    assert fake_b == ["b-zoom"]
    assert out.pipeline_version == PIPELINE_VERSION_B
    assert (out.engine, out.fallback) == ("ffmpeg", code)
    assert out.encoding == "libx264 crf=28"


def test_an_output_that_fails_the_checks_falls_back_to_b(
    fake_b: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(raw: Path, work: Path, **_: Any) -> VideoResult:
        raise RecipeError(FFMPEG_FAILED, "output has an audio track")

    monkeypatch.setattr(video_d, "clip_from_video", broken)
    out = run_recipe(
        "b-logo",
        _look(),
        tmp_path,
        video_renderer=_renderer(FakeClient(clip=b"not really an mp4")),
    )
    assert (out.engine, out.fallback) == ("ffmpeg", FFMPEG_FAILED)
    assert fake_b == ["b-logo"]


def test_without_a_renderer_videos_stay_on_b(fake_b: list[str], tmp_path: Path) -> None:
    out = run_recipe("b-pan", _look(), tmp_path, images=[_photo((1, 1, 1))])
    assert (out.engine, out.fallback, out.pipeline_version) == ("ffmpeg", "", "seasonal-b-1")


def test_a_source_problem_is_not_hidden_by_the_fallback(fake_b: list[str], tmp_path: Path) -> None:
    with pytest.raises(RecipeError) as exc:
        run_recipe("b-logo", _look(logo=None), tmp_path, video_renderer=_renderer(FakeClient()))
    assert exc.value.code == NO_SOURCE
    assert fake_b == []


def test_d_without_ffmpeg_stubbed_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The success path where CI has no FFmpeg: the re-encode is stubbed."""
    monkeypatch.setattr(
        video_d, "clip_from_video", lambda raw, work, **_: _stub_result(work / "c.mp4", (720, 900))
    )
    client = FakeClient(clip=b"mp4 bytes")
    out = run_recipe(
        "b-xfade",
        _look(),
        tmp_path,
        images=[_photo((1, 1, 1)), _photo((2, 2, 2))],
        video_renderer=_renderer(client),
    )
    assert (out.engine, out.pipeline_version) == ("remotion", "seasonal-d-1")
    assert len(client.uploads) == 3  # two photos + the logo
