"""Seasonal recipes B (short silent MP4) and E (animated WebP sticker), m-24976892.

Placeholder images are drawn here — never a client's. The Pillow-only half (frames,
bases, the quality search, the weight checks, the Pillow writer) runs everywhere; the
FFmpeg half is skipped cleanly where `ffmpeg` (with `libx264` / `libwebp_anim`) is not on
PATH — the CI `test` job has no FFmpeg, the `app` image and developer Macs do.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from qualify_creative.seasonal import (
    PIPELINE_VERSION_B,
    PIPELINE_VERSION_E,
    BrandLook,
    RecipeError,
    pipeline_version,
    run_recipe,
)
from qualify_creative.seasonal.errors import (
    FFMPEG_FAILED,
    FFMPEG_MISSING,
    NO_SOURCE,
    TOO_LARGE,
    UNKNOWN_RECIPE,
    UNREADABLE_SOURCE,
)
from qualify_creative.seasonal.ffmpeg import has_encoder, run_ffmpeg
from qualify_creative.seasonal.look import load_image
from qualify_creative.seasonal.sticker import (
    FRAMES,
    MARGIN,
    MAX_STICKER_BYTES,
    QUALITY_STEPS,
    SIZE,
    SOFT_STICKER_BYTES,
    _encode_ffmpeg,
    _encode_pillow,
    default_encoder,
    draw_frames,
    encode_sticker,
    image_base,
    make_sticker,
    text_base,
    validate_sticker,
)
from qualify_creative.seasonal.video import MAX_VIDEO_BYTES, frame_size, make_video

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_x264 = pytest.mark.skipif(
    not (HAS_FFMPEG and has_encoder("libx264")), reason="ffmpeg with libx264 not on PATH"
)
needs_webp = pytest.mark.skipif(
    not (HAS_FFMPEG and has_encoder("libwebp_anim")),
    reason="ffmpeg with libwebp_anim not on PATH",
)


def _logo() -> Image.Image:
    logo = Image.new("RGBA", (600, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logo)
    draw.rounded_rectangle((10, 10, 590, 290), 40, fill=(200, 30, 30, 255))
    draw.ellipse((60, 80, 200, 220), fill=(255, 255, 255, 255))
    return logo


def _photo(color: tuple[int, int, int], size: tuple[int, int] = (1080, 1350)) -> Image.Image:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    for x in range(0, size[0], 60):
        draw.line((x, 0, size[0] - x, size[1]), fill=(255, 255, 255), width=6)
    draw.ellipse((300, 400, 800, 900), fill=(240, 200, 40))
    return image


@pytest.fixture
def look() -> BrandLook:
    return BrandLook(primary=(200, 30, 30), secondary=(20, 120, 90), logo=_logo())


# --- the look and its sources -------------------------------------------------------------


def test_brand_look_from_the_kit() -> None:
    buf = io.BytesIO()
    _logo().save(buf, format="PNG")
    look = BrandLook.from_kit(palette=["#112233", "#ABC"], logo=buf.getvalue())
    assert look.primary == (0x11, 0x22, 0x33) and look.secondary == (0xAA, 0xBB, 0xCC)
    assert look.logo is not None and look.logo.mode == "RGBA"


def test_unreadable_source() -> None:
    with pytest.raises(RecipeError) as err:
        load_image(b"not an image", rgba=False)
    assert err.value.code == UNREADABLE_SOURCE


def test_sources_are_shrunk_on_the_way_in() -> None:
    buf = io.BytesIO()
    _photo((10, 20, 30), (4000, 3000)).save(buf, format="JPEG")
    image = load_image(buf.getvalue(), rgba=False)
    assert max(image.size) <= 1600 and image.mode == "RGB"


def test_a_photo_without_transparency_is_no_sticker() -> None:
    with pytest.raises(RecipeError) as err:
        image_base(_photo((10, 20, 30)).convert("RGBA"))
    assert err.value.code == NO_SOURCE


# --- recipe E: frames -----------------------------------------------------------------


@pytest.mark.parametrize("recipe", ["e-latido", "e-rebote", "e-giro", "e-brillo", "e-texto"])
def test_frames_are_transparent_512_and_inside_the_margin(recipe: str, look: BrandLook) -> None:
    base = (
        text_base("¡Gracias por tu pedido!", look) if recipe == "e-texto" else image_base(look.logo)
    )
    frames = draw_frames(recipe, base)
    assert len(frames) == FRAMES and 24 <= FRAMES <= 36
    for frame in frames:
        assert frame.size == (SIZE, SIZE) and frame.mode == "RGBA"
        assert frame.getpixel((0, 0))[3] == 0
        box = frame.getchannel("A").getbbox()
        if box is None:
            continue
        left, top, right, bottom = box
        assert left >= MARGIN and top >= MARGIN, (recipe, box)
        assert right <= SIZE - MARGIN and bottom <= SIZE - MARGIN, (recipe, box)
    # it moves: not every frame is the same
    assert len({f.tobytes() for f in frames}) > 1


def test_text_keeps_spanish_glyphs_and_wraps(look: BrandLook) -> None:
    art = text_base("¡Feliz Día de la Madre para todas!", look)
    assert art.width <= 440 and art.height <= 300


def test_empty_text_is_no_source(look: BrandLook) -> None:
    with pytest.raises(RecipeError) as err:
        text_base("   ", look)
    assert err.value.code == NO_SOURCE


def test_logo_sticker_without_a_logo(tmp_path: Path) -> None:
    look = BrandLook(primary=(1, 2, 3), secondary=(4, 5, 6))
    with pytest.raises(RecipeError) as err:
        make_sticker("e-latido", look, tmp_path, encoder=_encode_pillow)
    assert err.value.code == NO_SOURCE


def test_unknown_recipe(look: BrandLook, tmp_path: Path) -> None:
    with pytest.raises(RecipeError) as err:
        run_recipe("e-confeti", look, tmp_path)
    assert err.value.code == UNKNOWN_RECIPE


def test_pipeline_versions() -> None:
    assert pipeline_version("b-zoom") == PIPELINE_VERSION_B == "seasonal-b-1"
    assert pipeline_version("e-giro") == PIPELINE_VERSION_E == "seasonal-e-1"


# --- recipe E: encoding, weight and the quality search ----------------------------------


def test_pillow_writer_makes_a_valid_sticker(look: BrandLook, tmp_path: Path) -> None:
    out = run_recipe(
        "e-rebote", look, tmp_path, sticker_encoder=_encode_pillow, sticker_encoder_name="pillow"
    )
    assert out.bytes == len(out.data) <= MAX_STICKER_BYTES
    assert (out.width, out.height, out.ext, out.content_type) == (512, 512, "webp", "image/webp")
    assert out.encoding == "pillow q=70" and out.cost_usd == 0
    assert out.frames > 1 and 1500 <= out.duration_ms <= 2500
    validate_sticker(out.data)


def _real(frames: list[Image.Image], quality: int) -> bytes:
    return _encode_pillow(frames, 15, quality, Path("."))


def test_quality_is_searched_downward_until_it_fits(look: BrandLook, tmp_path: Path) -> None:
    frames = draw_frames("e-latido", image_base(look.logo))
    asked: list[int] = []

    def heavy_until_60(subset, fps, quality, work):  # noqa: ANN001, ANN202
        asked.append(quality)
        data = _real(list(subset), quality)
        return data if quality <= 60 else data + b"\0" * SOFT_STICKER_BYTES

    out = encode_sticker(frames, tmp_path, encoder=heavy_until_60, name="fake")
    assert asked == [70, 60] and out.quality == 60


def test_frames_are_halved_after_the_lowest_quality(look: BrandLook, tmp_path: Path) -> None:
    frames = draw_frames("e-latido", image_base(look.logo))
    counts: list[int] = []

    def heavy_until_halved(subset, fps, quality, work):  # noqa: ANN001, ANN202
        counts.append(len(subset))
        data = _real(list(subset), quality)
        return data if len(subset) < FRAMES else data + b"\0" * SOFT_STICKER_BYTES

    out = encode_sticker(frames, tmp_path, encoder=heavy_until_halved, name="fake")
    assert counts == [FRAMES] * len(QUALITY_STEPS) + [FRAMES // 2]
    assert out.quality == QUALITY_STEPS[-1]


def test_between_the_soft_and_hard_limit_only_the_last_try_is_kept(
    look: BrandLook, tmp_path: Path
) -> None:
    frames = draw_frames("e-rebote", image_base(look.logo))
    sizes: list[int] = []

    def just_over_soft(subset, fps, quality, work):  # noqa: ANN001, ANN202
        data = _real(list(subset), quality)
        padded = data + b"\0" * (SOFT_STICKER_BYTES + 10 - len(data))
        sizes.append(len(padded))
        return padded

    out = encode_sticker(frames, tmp_path, encoder=just_over_soft, name="fake")
    assert len(sizes) == len(QUALITY_STEPS) + 1  # every rung tried before settling
    assert SOFT_STICKER_BYTES < out.bytes <= MAX_STICKER_BYTES


def _anim_background(data: bytes) -> bytes:
    """The ANIM chunk's background colour (4 bytes, BGRA) of an animated WebP."""
    at = data.index(b"ANIM")
    return data[at + 8 : at + 12]


def test_default_writer_is_pillow_with_a_transparent_background(
    look: BrandLook, tmp_path: Path
) -> None:
    assert default_encoder()[1] == "pillow"
    out = run_recipe("e-latido", look, tmp_path)
    assert out.encoding.startswith("pillow")
    assert _anim_background(out.data) == b"\0\0\0\0"


def test_never_returns_an_over_limit_sticker(look: BrandLook, tmp_path: Path) -> None:
    frames = draw_frames("e-giro", image_base(look.logo))

    def always_heavy(subset, fps, quality, work):  # noqa: ANN001, ANN202
        return b"\0" * (MAX_STICKER_BYTES + 1)

    with pytest.raises(RecipeError) as err:
        encode_sticker(frames, tmp_path, encoder=always_heavy, name="fake")
    assert err.value.code == TOO_LARGE


def test_an_opaque_or_still_file_is_refused() -> None:
    opaque = Image.new("RGBA", (SIZE, SIZE), (255, 0, 0, 255))
    buf = io.BytesIO()
    opaque.save(buf, format="WEBP", save_all=True, append_images=[opaque.copy()], duration=60)
    with pytest.raises(RecipeError):
        validate_sticker(buf.getvalue())
    still = io.BytesIO()
    Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)).save(still, format="WEBP")
    with pytest.raises(RecipeError):
        validate_sticker(still.getvalue())


# --- recipe B: pure parts ---------------------------------------------------------------


def test_frame_size_clamps_between_square_and_vertical() -> None:
    assert frame_size(Image.new("RGB", (1600, 900))) == (720, 720)
    assert frame_size(Image.new("RGB", (1080, 1350))) == (720, 900)
    assert frame_size(Image.new("RGB", (900, 3000))) == (720, 1280)


def test_video_without_images_is_no_source(look: BrandLook, tmp_path: Path) -> None:
    for recipe, images in (("b-zoom", []), ("b-xfade", [_photo((1, 2, 3))])):
        with pytest.raises(RecipeError) as err:
            make_video(recipe, images, look, tmp_path)
        assert err.value.code == NO_SOURCE


def test_end_card_without_a_logo_is_no_source(tmp_path: Path) -> None:
    look = BrandLook(primary=(1, 2, 3), secondary=(4, 5, 6))
    with pytest.raises(RecipeError) as err:
        make_video("b-logo", [_photo((1, 2, 3))], look, tmp_path)
    assert err.value.code == NO_SOURCE


def test_missing_ffmpeg_is_ffmpeg_failed() -> None:
    with pytest.raises(RecipeError) as err:
        run_ffmpeg(["-version"], binary="ffmpeg-that-does-not-exist")
    assert err.value.code == FFMPEG_MISSING and not err.value.transient


# --- with FFmpeg ----------------------------------------------------------------------


@needs_webp
@pytest.mark.parametrize("recipe", ["e-latido", "e-rebote", "e-giro", "e-brillo", "e-texto"])
def test_ffmpeg_fallback_sticker(recipe: str, look: BrandLook, tmp_path: Path) -> None:
    out = run_recipe(
        recipe,
        look,
        tmp_path,
        text="¡Gracias por tu pedido!",
        sticker_encoder=_encode_ffmpeg,
        sticker_encoder_name="ffmpeg-libwebp_anim",
    )
    assert out.bytes <= MAX_STICKER_BYTES and out.encoding.startswith("ffmpeg-libwebp_anim")
    with Image.open(io.BytesIO(out.data)) as sticker:
        assert sticker.format == "WEBP" and sticker.size == (512, 512)
        assert sticker.n_frames > 1 and sticker.info.get("loop", 0) == 0
        assert sticker.convert("RGBA").getpixel((2, 2))[3] == 0


@needs_x264
def test_ffmpeg_failure_is_ffmpeg_failed(tmp_path: Path) -> None:
    with pytest.raises(RecipeError) as err:
        run_ffmpeg(["-i", str(tmp_path / "missing.png"), str(tmp_path / "out.mp4")])
    assert err.value.code == FFMPEG_FAILED and not err.value.transient


def _probe(data: bytes, tmp_path: Path) -> dict:
    path = tmp_path / "probe.mp4"
    path.write_bytes(data)
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


@needs_x264
@pytest.mark.parametrize(
    ("recipe", "count", "seconds"),
    [("b-zoom", 1, 4.0), ("b-pan", 1, 4.0), ("b-xfade", 3, 5.0), ("b-xfade", 2, 3.5),
     ("b-logo", 1, 4.0), ("b-logo", 0, 4.0)],
)  # fmt: skip
def test_ffmpeg_video(
    recipe: str, count: int, seconds: float, look: BrandLook, tmp_path: Path
) -> None:
    photos = [_photo(c) for c in ((30, 90, 160), (160, 60, 30), (40, 140, 60))][:count]
    work = tmp_path / "work"
    work.mkdir()
    out = run_recipe(recipe, look, work, images=photos)
    assert out.bytes <= MAX_VIDEO_BYTES and out.ext == "mp4" and out.cost_usd == 0
    assert out.encoding.startswith("libx264 crf=")
    info = _probe(out.data, tmp_path)
    streams = info["streams"]
    assert [s["codec_type"] for s in streams] == ["video"]  # no audio track
    video = streams[0]
    assert video["codec_name"] == "h264" and video["pix_fmt"] == "yuv420p"
    # Meta's WhatsApp video spec: Main/Baseline, no B-frames (bench STICKERS-001)
    assert video["profile"] == "Main" and int(video["has_b_frames"]) == 0
    assert (video["width"], video["height"]) == (out.width, out.height)
    assert 3.0 <= float(info["format"]["duration"]) <= 5.0
    assert abs(out.duration_ms - seconds * 1000) <= 100
