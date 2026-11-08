"""Recipe E — an animated WebP sticker drawn by code from the Brand Kit (m-24976892).

The base is the brand's logo (RGBA), a product photo that is already cut out (it must
carry transparency; a photo on a solid background is `no_source`), or a short seasonal
text in the brand's type face and primary colour. Pillow draws `FRAMES` RGBA frames at
512×512 with one fixed motion; Pillow's own WebP writer encodes them (bench STICKERS-001:
FFmpeg's `libwebp_anim` writes the animation's background colour as OPAQUE white, Pillow
as transparent — a sticker must not risk a white square). FFmpeg's `libwebp_anim` is only
the fallback for a Pillow built without animated WebP.

| recipe      | base            | motion (one loop = 2 s, 30 frames at 15 fps)         |
|-------------|-----------------|------------------------------------------------------|
| `e-latido`  | logo or cut-out | two quick heartbeats (+10 %, +7 %), then rest        |
| `e-rebote`  | logo or cut-out | one hop of 60 px, squashed where it lands            |
| `e-giro`    | logo or cut-out | a coin flip on its vertical axis, then rest          |
| `e-brillo`  | logo or cut-out | a diagonal shine sweeps across it, then rest         |
| `e-texto`   | text            | pops in (overshoot), one ±4° wiggle, then rest       |

WhatsApp's sticker rules (512×512, ≤ 500 KB animated, transparent background, a 16 px
margin) are checked on the encoded file BEFORE it is returned: a file that does not
meet them is never handed back. Lossy WebP with alpha, `method=4` (never 6: 8–23× the CPU
for 3–13 % fewer bytes), `loop=0`, transparent animation background. Quality 70; a file
over the 450 KB soft limit is encoded again at 60, then with half the frames at 60; the
first one under 450 KB wins, else the last one if it is under the 500 KB hard limit, else
`too_large`. The result says which encoder (`pillow` / `ffmpeg-libwebp_anim`) and quality.
"""

from __future__ import annotations

import io
import math
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, features

from qualify_creative.seasonal.errors import (
    FFMPEG_FAILED,
    FFMPEG_MISSING,
    NO_SOURCE,
    TOO_LARGE,
    UNKNOWN_RECIPE,
    RecipeError,
)
from qualify_creative.seasonal.ffmpeg import OUTPUT_THREAD_ARGS, has_encoder, run_ffmpeg
from qualify_creative.seasonal.look import BrandLook, has_transparency

STICKER_RECIPES = ("e-latido", "e-rebote", "e-giro", "e-brillo", "e-texto")
#: The recipes whose base is an image (the logo or a cut-out); `e-texto` draws words.
IMAGE_STICKERS = ("e-latido", "e-rebote", "e-giro", "e-brillo")
SIZE = 512
#: WhatsApp: an animated sticker is at most 500 KB.
MAX_STICKER_BYTES = 500 * 1024
#: WhatsApp's guideline: 16 px clear around the art.
MARGIN = 16
FRAMES = 30
FPS = 15
#: A file over this is encoded again (a 50 KB margin under the hard limit, bench STICKERS-001).
SOFT_STICKER_BYTES = 450 * 1024
QUALITY_STEPS = (70, 60)
#: libwebp `method` / FFmpeg `-compression_level`: 6 took 36 s (FFmpeg) / 92 s (Pillow)
#: for 30 frames locally for ~7 % fewer bytes than 4 (0.35 s / 1.0 s).
COMPRESSION_LEVEL = 4
#: The base's longest side: leaves room for +10 % scale and a 60 px hop inside the margin.
BASE_BOX = 380
OUTLINE_PX = 10
TEXT_BOX = (440, 300)
TEXT_MAX_LINES = 3
DEFAULT_TEXT = "¡Gracias por tu pedido!"

Frame = Image.Image


@dataclass(frozen=True)
class StickerResult:
    data: bytes
    width: int
    height: int
    duration_ms: int
    frames: int
    bytes: int
    quality: int
    #: `pillow`, or `ffmpeg-libwebp_anim` when this Pillow cannot write animated WebP.
    encoder: str


# --- the base -------------------------------------------------------------------------


def _trim(image: Image.Image) -> Image.Image:
    bbox = image.getchannel("A").getbbox()
    return image.crop(bbox) if bbox else image


def _outlined(art: Image.Image, px: int = OUTLINE_PX) -> Image.Image:
    """The art with a white outline `px` wide around its shape (the classic sticker edge:
    it keeps a dark logo readable on WhatsApp's dark theme)."""
    canvas = Image.new("RGBA", (art.width + 2 * px, art.height + 2 * px), (0, 0, 0, 0))
    alpha = Image.new("L", canvas.size, 0)
    alpha.paste(art.getchannel("A"), (px, px))
    grown = alpha.point(lambda a: 255 if a > 24 else 0)
    size = 2 * (px // 2) + 1
    for _ in range(2):
        grown = grown.filter(ImageFilter.MaxFilter(size))
    grown = grown.filter(ImageFilter.GaussianBlur(1))
    canvas.paste((255, 255, 255, 255), (0, 0), grown)
    canvas.alpha_composite(art, (px, px))
    return canvas


def image_base(art: Image.Image) -> Image.Image:
    """A logo or cut-out, trimmed to its shape, fitted in `BASE_BOX` and outlined."""
    if not has_transparency(art):
        raise RecipeError(NO_SOURCE, "the image has no transparent background to cut by")
    trimmed = _trim(art.convert("RGBA"))
    box = BASE_BOX - 2 * OUTLINE_PX
    scale = min(box / trimmed.width, box / trimmed.height)
    size = (max(1, round(trimmed.width * scale)), max(1, round(trimmed.height * scale)))
    return _outlined(trimmed.resize(size, Image.Resampling.LANCZOS))


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ink(look: BrandLook) -> tuple[int, int, int]:
    """The text's fill: the primary colour, unless it is too light to read inside a white
    outline — then the secondary, then near-black."""
    for color in (look.primary, look.secondary):
        if _luminance(color) < 0.6:
            return color
    return (17, 24, 39)


def text_base(text: str, look: BrandLook) -> Image.Image:
    """The words in the brand's face, in its ink, with a white stroke, wrapped to at most
    `TEXT_MAX_LINES` lines inside `TEXT_BOX`; the largest size that fits."""
    words = " ".join(text.split())
    if not words:
        raise RecipeError(NO_SOURCE, "e-texto needs a text")
    max_w, max_h = TEXT_BOX
    ink = _ink(look)
    for px in range(96, 27, -4):
        font = look.font_at(px)
        stroke = max(3, px // 9)
        for width in range(max(4, len(words) // TEXT_MAX_LINES), len(words) + 1):
            lines = textwrap.wrap(words, width=width) or [words]
            if len(lines) > TEXT_MAX_LINES:
                continue
            block = "\n".join(lines)
            probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            box = probe.multiline_textbbox(
                (0, 0), block, font=font, align="center", spacing=px // 6, stroke_width=stroke
            )
            w, h = math.ceil(box[2] - box[0]), math.ceil(box[3] - box[1])
            if w <= max_w and h <= max_h:
                art = Image.new("RGBA", (w + 4, h + 4), (0, 0, 0, 0))
                ImageDraw.Draw(art).multiline_text(
                    (2 - box[0], 2 - box[1]),
                    block,
                    font=font,
                    fill=(*ink, 255),
                    align="center",
                    spacing=px // 6,
                    stroke_width=stroke,
                    stroke_fill=(255, 255, 255, 255),
                )
                return art
            if w > max_w:
                break  # wider lines only get wider
    raise RecipeError(NO_SOURCE, "the text does not fit in a sticker")


# --- the motions (t in [0, 1): one loop) ------------------------------------------------


def _place(
    base: Image.Image,
    *,
    sx: float = 1.0,
    sy: float = 1.0,
    dx: float = 0.0,
    dy: float = 0.0,
    angle: float = 0.0,
    anchor_bottom: bool = False,
) -> Frame:
    frame = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    w = max(1, round(base.width * sx))
    h = max(1, round(base.height * sy))
    art = base if (w, h) == base.size else base.resize((w, h), Image.Resampling.BICUBIC)
    if angle:
        art = art.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    cx = SIZE / 2 + dx
    if anchor_bottom:
        bottom = SIZE / 2 + base.height / 2 + dy
        top = bottom - art.height
    else:
        top = SIZE / 2 + dy - art.height / 2
    frame.alpha_composite(art, (round(cx - art.width / 2), round(top)))
    return frame


def _bump(t: float, at: float, width: float) -> float:
    return math.exp(-(((t - at) / width) ** 2))


def _ease_in_out(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * x)


def latido(base: Image.Image, t: float) -> Frame:
    s = 1 + 0.10 * _bump(t, 0.12, 0.05) + 0.07 * _bump(t, 0.30, 0.05)
    return _place(base, sx=s, sy=s)


def rebote(base: Image.Image, t: float) -> Frame:
    lift = math.sin(math.pi * t)
    squash = max(0.0, 1 - lift / 0.2)  # only near the ground
    return _place(
        base,
        sx=1 + 0.08 * squash,
        sy=1 - 0.08 * squash,
        dy=30 - 60 * lift,
        anchor_bottom=True,
    )


def giro(base: Image.Image, t: float) -> Frame:
    turn = _ease_in_out(t / 0.6)  # the flip takes 60 % of the loop, then it rests
    return _place(base, sx=max(0.04, abs(math.cos(2 * math.pi * turn))))


def _shine(base: Image.Image, t: float) -> Image.Image:
    sweep = _ease_in_out(t / 0.6)
    band = Image.new("L", base.size, 0)
    span = base.width + base.height
    x = -base.height * 0.6 + sweep * (span + base.height * 0.6) - base.height * 0.3
    half = max(12, base.width // 10)
    ImageDraw.Draw(band).polygon(
        [(x - half, base.height), (x + half, base.height), (x + half + base.height, 0),
         (x - half + base.height, 0)],
        fill=170,
    )  # fmt: skip
    band = band.filter(ImageFilter.GaussianBlur(half / 2))
    mask = ImageChops.multiply(band, base.getchannel("A"))
    lit = base.copy()
    lit.paste((255, 255, 255, 255), (0, 0), mask)
    lit.putalpha(base.getchannel("A"))
    return lit


def brillo(base: Image.Image, t: float) -> Frame:
    s = 1 + 0.03 * math.sin(math.pi * t)
    return _place(_shine(base, t), sx=s, sy=s)


def texto(base: Image.Image, t: float) -> Frame:
    pop = min(1.0, t / 0.25)
    # ease-out-back: overshoots to ~1.08 and settles at 1
    c = 1.70158
    s = 0.3 + 0.7 * (1 + (c + 1) * (pop - 1) ** 3 + c * (pop - 1) ** 2)
    # one wiggle after the pop, then still: rotated sharp letters change every pixel of
    # a frame, and a sway over the whole loop weighed 474 KB of the 500 (local, q=80)
    wiggle = (t - 0.3) / 0.3
    sway = 4 * math.sin(2 * math.pi * wiggle) if 0.0 <= wiggle < 1.0 else 0.0
    return _place(base, sx=s, sy=s, angle=sway)


MOTIONS: dict[str, Callable[[Image.Image, float], Frame]] = {
    "e-latido": latido,
    "e-rebote": rebote,
    "e-giro": giro,
    "e-brillo": brillo,
    "e-texto": texto,
}


def draw_frames(recipe: str, base: Image.Image, frames: int = FRAMES) -> list[Frame]:
    motion = MOTIONS.get(recipe)
    if motion is None:
        raise RecipeError(UNKNOWN_RECIPE, recipe)
    return [motion(base, i / frames) for i in range(frames)]


# --- encoding -------------------------------------------------------------------------


def _encode_ffmpeg(frames: Sequence[Frame], fps: float, quality: int, work: Path) -> bytes:
    folder = work / "frames"
    if folder.exists():
        for old in folder.iterdir():
            old.unlink()
    folder.mkdir(exist_ok=True)
    for i, frame in enumerate(frames):
        frame.save(folder / f"f{i:03d}.png", format="PNG", compress_level=1)
    out = work / "sticker.webp"
    run_ffmpeg(
        [
            "-framerate", f"{fps:g}",
            "-i", str(folder / "f%03d.png"),
            "-an",
            "-c:v", "libwebp_anim",
            "-lossless", "0",
            "-quality", str(quality),
            "-compression_level", str(COMPRESSION_LEVEL),
            "-pix_fmt", "yuva420p",
            "-loop", "0",
            *OUTPUT_THREAD_ARGS,
            str(out),
        ]
    )  # fmt: skip
    return out.read_bytes()


def _encode_pillow(frames: Sequence[Frame], fps: float, quality: int, work: Path) -> bytes:
    del work
    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="WEBP",
        save_all=True,
        append_images=list(frames[1:]),
        duration=round(1000 / fps),
        loop=0,
        lossless=False,
        quality=quality,
        method=COMPRESSION_LEVEL,
        background=(0, 0, 0, 0),
    )
    return buf.getvalue()


def validate_sticker(data: bytes) -> tuple[int, int]:
    """Raise unless `data` is an animated WebP, 512×512, ≤ 500 KB, with a transparent
    background (its corner is clear on the first frame). Returns (frames, duration_ms)."""
    if len(data) > MAX_STICKER_BYTES:
        raise RecipeError(TOO_LARGE, f"{len(data)} bytes")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "WEBP" or image.size != (SIZE, SIZE):
            raise RecipeError(FFMPEG_FAILED, f"not a {SIZE}x{SIZE} WebP")
        frames = getattr(image, "n_frames", 1)
        if frames < 2:
            raise RecipeError(FFMPEG_FAILED, "not animated")
        duration = 0
        for i in range(frames):
            image.seek(i)
            duration += int(image.info.get("duration") or 0)
        image.seek(0)
        first = image.convert("RGBA")
    if first.getpixel((2, 2))[3] > 8:
        raise RecipeError(FFMPEG_FAILED, "background is not transparent")
    return frames, duration


Encoder = Callable[[Sequence[Frame], float, int, Path], bytes]


def encode_sticker(
    frames: Sequence[Frame], work: Path, *, encoder: Encoder | None = None, name: str = ""
) -> StickerResult:
    """Encode with the quality search (module docstring); never returns a file over the
    hard limit."""
    if encoder is None:
        encoder, name = default_encoder()
    attempts: list[tuple[Sequence[Frame], float, int]] = [(frames, FPS, q) for q in QUALITY_STEPS]
    attempts.append((frames[::2], FPS / 2, QUALITY_STEPS[-1]))
    last = 0
    for index, (subset, fps, quality) in enumerate(attempts):
        data = encoder(subset, fps, quality, work)
        last = len(data)
        final = index == len(attempts) - 1
        if last <= SOFT_STICKER_BYTES or (final and last <= MAX_STICKER_BYTES):
            count, duration_ms = validate_sticker(data)
            return StickerResult(
                data=data,
                width=SIZE,
                height=SIZE,
                duration_ms=duration_ms or round(len(subset) * 1000 / fps),
                frames=count,
                bytes=len(data),
                quality=quality,
                encoder=name,
            )
    raise RecipeError(TOO_LARGE, f"{last} bytes at quality {QUALITY_STEPS[-1]}")


def default_encoder() -> tuple[Encoder, str]:
    """Pillow's WebP writer (transparent animation background); FFmpeg's `libwebp_anim`
    only when this Pillow cannot write animated WebP."""
    if features.check("webp"):
        return _encode_pillow, "pillow"
    if has_encoder("libwebp_anim"):
        return _encode_ffmpeg, "ffmpeg-libwebp_anim"
    raise RecipeError(FFMPEG_MISSING, "no animated WebP writer")


def make_sticker(
    recipe: str,
    look: BrandLook,
    work: Path,
    *,
    art: Image.Image | None = None,
    text: str | None = None,
    encoder: Encoder | None = None,
    encoder_name: str = "",
) -> StickerResult:
    """Run recipe E `recipe`. Image recipes draw `art` (a cut-out) or, without it, the
    brand's logo; `e-texto` draws `text` (default «¡Gracias por tu pedido!»)."""
    if recipe not in STICKER_RECIPES:
        raise RecipeError(UNKNOWN_RECIPE, recipe)
    if recipe == "e-texto":
        base = text_base(text or DEFAULT_TEXT, look)
    else:
        source = art if art is not None else look.logo
        if source is None:
            raise RecipeError(NO_SOURCE, f"{recipe} needs the logo or a cut-out photo")
        base = image_base(source)
    frames = draw_frames(recipe, base)
    return encode_sticker(frames, work, encoder=encoder, name=encoder_name)
