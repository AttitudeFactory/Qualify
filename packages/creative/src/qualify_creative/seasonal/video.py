"""Recipe B — a silent short MP4 from the brand's approved images (m-24976892).

Four motions, all made by FFmpeg from stills Pillow prepared at the exact output size:

| recipe    | sources | what moves                                              | length |
|-----------|---------|---------------------------------------------------------|--------|
| `b-zoom`  | 1       | slow push-in to 112 % (`zoompan`, still pre-scaled ×2)  | 4 s    |
| `b-pan`   | 1       | the still, 20 % wider than the frame, slides left→right | 4 s    |
| `b-xfade` | 2–3     | 2 s per still, 0.5 s cross-fades (`xfade=fade`)         | 3.5–5 s|
| `b-logo`  | 0–1+logo| the still (or, with none, the brand's two colours as a  | 4 s    |
|           |         | gradient), then the logo on a white card fades in       |        |

Output: H.264 Main profile WITHOUT B-frames (`libx264 -preset veryfast -profile:v main
-bf 0` — what Meta's WhatsApp video spec asks; bench STICKERS-001), `yuv420p` in limited
range, `+faststart`, **no audio track**
(`-an`), 24 fps, 720 px wide and as tall as the first still's aspect allows between 1:1
and 9:16 (a landscape still is cropped to 1:1). Quality: `-crf 28`, then 30 and 32 while
the file is over the 1 MB target; over 16 MB at crf 32 it is `too_large` and nothing is
returned. FFmpeg runs with `-threads 1` under `nice` and a timeout (`ffmpeg.py`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from qualify_creative.seasonal.errors import (
    FFMPEG_FAILED,
    FFMPEG_MISSING,
    NO_SOURCE,
    TOO_LARGE,
    UNKNOWN_RECIPE,
    RecipeError,
)
from qualify_creative.seasonal.ffmpeg import OUTPUT_THREAD_ARGS, has_encoder, run_ffmpeg
from qualify_creative.seasonal.look import BrandLook

VIDEO_RECIPES = ("b-zoom", "b-pan", "b-xfade", "b-logo")
VIDEO_WIDTH = 720
#: The tallest frame: 9:16 at 720 px wide.
VIDEO_MAX_HEIGHT = 1280
FPS = 24
#: x264 quality steps tried in order while the file is over `TARGET_VIDEO_BYTES`.
CRF_STEPS = (28, 30, 32)
X264_PRESET = "veryfast"
#: The target: a WhatsApp video under 1 MB arrives fast on a prepaid phone plan.
TARGET_VIDEO_BYTES = 1_000_000
#: The hard ceiling: WhatsApp's own limit for a video message is 16 MB.
MAX_VIDEO_BYTES = 16 * 1024 * 1024
SINGLE_SECONDS = 4.0
XFADE_STILL_SECONDS = 2.0
XFADE_SECONDS = 0.5
ZOOM_END = 1.12
PAN_WIDTH_SHARE = 1.2
LOGO_FADE_SECONDS = 0.8
#: The logo starts fading in this long before the end, so it rests ~0.8 s fully shown.
LOGO_FADE_LEAD = 1.6
MIN_SECONDS, MAX_SECONDS = 3.0, 5.0


@dataclass(frozen=True)
class VideoResult:
    path: Path
    width: int
    height: int
    duration_ms: int
    frames: int
    bytes: int
    crf: int
    #: Over the 1 MB target (but under the 16 MB ceiling) at the last crf tried.
    over_target: bool


def frame_size(first: Image.Image) -> tuple[int, int]:
    """720 px wide; as tall as the still's own aspect allows between 1:1 and 9:16, even."""
    aspect = first.height / max(1, first.width)
    aspect = min(max(aspect, 1.0), VIDEO_MAX_HEIGHT / VIDEO_WIDTH)
    height = int(round(VIDEO_WIDTH * aspect / 2.0)) * 2
    return VIDEO_WIDTH, min(height, VIDEO_MAX_HEIGHT)


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, Image.Resampling.LANCZOS)


def _save(image: Image.Image, path: Path) -> Path:
    image.save(path, format="PNG", compress_level=1)
    return path


def _logo_card(look: BrandLook, size: tuple[int, int]) -> Image.Image:
    """The end card's layer (RGBA, full frame): the logo on a white rounded card with a
    border in the brand's primary colour, centred; transparent elsewhere."""
    if look.logo is None:
        raise RecipeError(NO_SOURCE, "b-logo needs the brand's logo")
    width, height = size
    card_w = int(width * 0.62)
    logo = look.logo.copy()
    bbox = logo.getchannel("A").getbbox()
    if bbox:
        logo = logo.crop(bbox)
    inner = int(card_w * 0.78)
    logo.thumbnail((inner, inner), Image.Resampling.LANCZOS)
    pad = (card_w - inner) // 2
    card_h = logo.height + 2 * pad
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    left, top = (width - card_w) // 2, (height - card_h) // 2
    border = max(4, width // 120)
    draw.rounded_rectangle(
        (left, top, left + card_w, top + card_h),
        radius=card_w // 10,
        fill=(255, 255, 255, 242),
        outline=(*look.primary, 255),
        width=border,
    )
    layer.alpha_composite(logo, (left + (card_w - logo.width) // 2, top + pad))
    return layer


def _encode_args(seconds: float, crf: int, out: Path) -> list[str]:
    return [
        "-an",
        "-r", str(FPS),
        "-t", f"{seconds:.3f}",
        "-c:v", "libx264",
        "-preset", X264_PRESET,
        "-crf", str(crf),
        "-profile:v", "main",
        "-bf", "0",
        "-pix_fmt", "yuv420p",
        "-color_range", "tv",
        "-movflags", "+faststart",
        *OUTPUT_THREAD_ARGS,
        str(out),
    ]  # fmt: skip


def _graph(
    recipe: str, stills: Sequence[Path], size: tuple[int, int], work: Path, look: BrandLook
) -> tuple[list[str], float]:
    """The inputs + filter of one recipe, and its length in seconds."""
    width, height = size
    loop = ["-loop", "1", "-framerate", str(FPS)]
    if recipe == "b-zoom":
        frames = int(SINGLE_SECONDS * FPS)
        zoom = (
            f"zoompan=z='1+{ZOOM_END - 1:.3f}*on/{frames}'"
            ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={width}x{height}:fps={FPS},format=yuv420p"
        )
        return ["-i", str(stills[0]), "-vf", zoom], SINGLE_SECONDS
    if recipe == "b-pan":
        seconds = SINGLE_SECONDS
        pan = f"crop={width}:{height}:x='(iw-{width})*t/{seconds}':y=0,format=yuv420p"
        return [*loop, "-t", f"{seconds}", "-i", str(stills[0]), "-vf", pan], seconds
    if recipe == "b-xfade":
        count = len(stills)
        seconds = count * XFADE_STILL_SECONDS - (count - 1) * XFADE_SECONDS
        inputs: list[str] = []
        for still in stills:
            inputs += [*loop, "-t", f"{XFADE_STILL_SECONDS}", "-i", str(still)]
        parts = [f"[{i}]fps={FPS},settb=AVTB,format=yuv420p[s{i}]" for i in range(count)]
        last = "s0"
        for i in range(1, count):
            offset = i * (XFADE_STILL_SECONDS - XFADE_SECONDS)
            parts.append(
                f"[{last}][s{i}]xfade=transition=fade:duration={XFADE_SECONDS}"
                f":offset={offset:.3f}[x{i}]"
            )
            last = f"x{i}"
        return [*inputs, "-filter_complex", ";".join(parts), "-map", f"[{last}]"], seconds
    if recipe == "b-logo":
        seconds = SINGLE_SECONDS
        card = _save(_logo_card(look, size), work / "card.png")
        start = seconds - LOGO_FADE_LEAD
        graph = (
            f"[1]format=rgba,fade=t=in:st={start:.3f}:d={LOGO_FADE_SECONDS}:alpha=1[o];"
            "[0][o]overlay=0:0,format=yuv420p[v]"
        )
        inputs = [*loop, "-t", f"{seconds}", "-i", str(stills[0])]
        inputs += [*loop, "-t", f"{seconds}", "-i", str(card)]
        return [*inputs, "-filter_complex", graph, "-map", "[v]"], seconds
    raise RecipeError(UNKNOWN_RECIPE, recipe)


def _prepare(
    recipe: str, images: Sequence[Image.Image], size: tuple[int, int], work: Path
) -> list[Path]:
    width, height = size
    if recipe == "b-zoom":
        # zoompan rounds x/y to whole pixels: a still twice the frame keeps it from jittering
        return [_save(_cover(images[0], (width * 2, height * 2)), work / "still0.png")]
    if recipe == "b-pan":
        wide = (int(round(width * PAN_WIDTH_SHARE / 2.0)) * 2, height)
        return [_save(_cover(images[0], wide), work / "still0.png")]
    if recipe == "b-xfade":
        return [_save(_cover(im, size), work / f"still{i}.png") for i, im in enumerate(images)]
    return [_save(_cover(images[0], size), work / "still0.png")]


def _needed(recipe: str) -> tuple[int, int]:
    if recipe == "b-xfade":
        return 2, 3
    return (0, 1) if recipe == "b-logo" else (1, 1)


def brand_backdrop(look: BrandLook, size: tuple[int, int]) -> Image.Image:
    """The end card's background when `b-logo` has no still (its source is the logo
    alone, `STANDARD_BATCH`): a vertical gradient from the primary to the secondary."""
    width, height = size
    top, bottom = look.primary, look.secondary
    column = Image.new("RGB", (1, height))
    for y in range(height):
        k = y / max(1, height - 1)
        column.putpixel((0, y), tuple(round(a + (b - a) * k) for a, b in zip(top, bottom)))
    return column.resize(size)


def probe(path: Path) -> dict:
    """ffprobe's view of the output (streams + format). Fails CLOSED (review of
    58855151): without ffprobe, on a non-zero exit, a timeout or output that is not JSON
    it raises `ffmpeg_failed` (transient) — an unchecked MP4 is never marked ready."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise RecipeError(FFMPEG_FAILED, "ffprobe not on PATH", transient=True)
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecipeError(FFMPEG_FAILED, f"ffprobe {type(exc).__name__}", transient=True) from exc
    if proc.returncode != 0:
        raise RecipeError(FFMPEG_FAILED, f"ffprobe exit {proc.returncode}", transient=True)
    try:
        info = json.loads(proc.stdout)
    except ValueError as exc:
        raise RecipeError(FFMPEG_FAILED, "ffprobe output is not JSON", transient=True) from exc
    if not isinstance(info, dict):
        raise RecipeError(FFMPEG_FAILED, "ffprobe output is not an object", transient=True)
    return info


def make_video(
    recipe: str, images: Sequence[Image.Image], look: BrandLook, work: Path
) -> VideoResult:
    """Run recipe B `recipe` on `images` (RGB, already bounded by `look.load_image`) inside
    the temp dir `work`; returns the MP4 there, validated against the limits above."""
    if recipe not in VIDEO_RECIPES:
        raise RecipeError(UNKNOWN_RECIPE, recipe)
    low, high = _needed(recipe)
    if len(images) < low:
        raise RecipeError(NO_SOURCE, f"{recipe} needs {low} approved image(s)")
    images = list(images)[:high]
    if recipe == "b-logo" and look.logo is None:
        raise RecipeError(NO_SOURCE, "b-logo needs the brand's logo")
    if not has_encoder("libx264"):
        raise RecipeError(FFMPEG_MISSING, "ffmpeg without libx264")
    if not images:  # b-logo from the logo alone
        size = (VIDEO_WIDTH, VIDEO_WIDTH)
        images = [brand_backdrop(look, size)]
    else:
        size = frame_size(images[0])
    stills = _prepare(recipe, images, size, work)
    inputs, seconds = _graph(recipe, stills, size, work, look)
    out = work / "out.mp4"
    nbytes, crf = 0, CRF_STEPS[0]
    for crf in CRF_STEPS:
        run_ffmpeg([*inputs, *_encode_args(seconds, crf, out)])
        nbytes = out.stat().st_size
        if nbytes <= TARGET_VIDEO_BYTES:
            break
    if nbytes > MAX_VIDEO_BYTES:
        raise RecipeError(TOO_LARGE, f"{nbytes} bytes at crf {crf}")
    return _validated(out, size, seconds, nbytes, crf)


def _validated(
    out: Path, size: tuple[int, int], seconds: float, nbytes: int, crf: int
) -> VideoResult:
    """Every check runs on what ffprobe READ from the file — never on the planned values."""
    del size, seconds
    info = probe(out)
    streams = info.get("streams") or []
    if any(s.get("codec_type") == "audio" for s in streams):
        raise RecipeError(FFMPEG_FAILED, "output has an audio track")
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise RecipeError(FFMPEG_FAILED, "output has no video track")
    if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        raise RecipeError(FFMPEG_FAILED, "output is not H.264 yuv420p")
    if video.get("profile") != "Main" or int(video.get("has_b_frames") or 0):
        raise RecipeError(FFMPEG_FAILED, "output is not Main profile without B-frames")
    try:
        width, height = int(video["width"]), int(video["height"])
        duration_ms = int(round(float((info.get("format") or {})["duration"]) * 1000))
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeError(FFMPEG_FAILED, "ffprobe gave no size or duration") from exc
    frames = int(video.get("nb_frames") or round(duration_ms * FPS / 1000))
    if not MIN_SECONDS * 1000 - 100 <= duration_ms <= MAX_SECONDS * 1000 + 100:
        raise RecipeError(FFMPEG_FAILED, f"duration {duration_ms} ms out of range")
    return VideoResult(
        path=out,
        width=width,
        height=height,
        duration_ms=duration_ms,
        frames=frames,
        bytes=nbytes,
        crf=crf,
        over_target=nbytes > TARGET_VIDEO_BYTES,
    )


def clip_from_video(raw: Path, work: Path, *, max_seconds: float = MAX_SECONDS) -> VideoResult:
    """A vendor's clip (Seedance, «Crear con IA», m-24976893) made into the same MP4 as
    recipe B: its audio dropped, cut to `max_seconds`, 720 px wide (even height, its own
    aspect), 24 fps, H.264 Main without B-frames, crf 28→32 under the 1 MB target — and
    validated by ffprobe exactly like B (Main, no B-frames, no audio, 3–5 s, ≤ 16 MB)."""
    if not has_encoder("libx264"):
        raise RecipeError(FFMPEG_MISSING, "ffmpeg without libx264")
    out = work / "clip.mp4"
    vf = f"scale={VIDEO_WIDTH}:-2:flags=lanczos,fps={FPS},format=yuv420p"
    nbytes, crf = 0, CRF_STEPS[0]
    for crf in CRF_STEPS:
        run_ffmpeg(["-i", str(raw), "-vf", vf, *_encode_args(max_seconds, crf, out)])
        nbytes = out.stat().st_size
        if nbytes <= TARGET_VIDEO_BYTES:
            break
    if nbytes > MAX_VIDEO_BYTES:
        raise RecipeError(TOO_LARGE, f"{nbytes} bytes at crf {crf}")
    return _validated(out, (VIDEO_WIDTH, 0), max_seconds, nbytes, crf)
