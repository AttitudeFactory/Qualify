"""Product stickers (m-25017372): an approved «tierno» character above a short message,
drawn by the Remotion `sticker` template **v2** («caption» mode) — Remotion composes, Python
only slices the sheet and encodes (founder 2026-11-12: no Pillow composition, and no Pillow
fallback for these stickers: if the render service is down the job retries later).

Two outputs per (character, message), both free (our own render service, `remotion_selfhost`
= 0 in the pricing table):

- **animated** — every frame of the 2 s loop, recipe C's encoder, quality ladder and
  `validate_sticker` (512×512, ≤ 500 KB, transparent);
- **static** — frame 0 (every motion starts at rest), a single-frame WebP ≤ 100 KB
  (`validate_static_sticker`): «Más liviano: llega rápido aunque la señal sea mala».

The motion follows the message: a short one (one line) hops (`rebote`); a long one, which
needs two lines and leaves less room above, beats in place (`latido`) — the bench showed a
2-line `rebote` shrinks the character to ~120 px. The caption ink follows `backing.py`'s
contrast rule for words on the white die-cut (the brand's first colour that reads on white,
else a dark backing with an ink that reads on it).
"""

from __future__ import annotations

import functools
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from qualify_creative.seasonal.backing import (
    REASON_UNMEASURED,
    WHITE,
    Backing,
    art_backing,
    text_backing,
)
from qualify_creative.seasonal.errors import NO_SOURCE, TOO_LARGE, RecipeError
from qualify_creative.seasonal.look import BrandLook
from qualify_creative.seasonal.sticker import SIZE, StickerResult, _encode_pillow, encode_sticker
from qualify_creative.seasonal.sticker_c import (
    ALPHA_QUALITY_C,
    SHEET_PORT,
    TEMPLATE_ID,
    RemotionStickerRenderer,
    StickerRenderError,
    _hex,
    art_png,
)

#: The template version with the caption mode.
CAPTION_TEMPLATE_VERSION = 2
#: Provenance of a product sticker's drawing (template v2 + encoders); bump when it changes.
PIPELINE_VERSION_PRODUCT = "kawaii-sticker-1"
#: The owner's message: presets or their own, at most this many characters (UX doc §2).
MAX_MESSAGE_CHARS = 25
#: A message up to this long fits one caption line in the widest faces: it hops.
ONE_LINE_CHARS = 12
MOTION_SHORT = "rebote"
MOTION_LONG = "latido"
CAPTION_MOTIONS = ("latido", "rebote", "giro", "brillo")
#: WhatsApp's static sticker limit.
MAX_STATIC_BYTES = 100 * 1024
STATIC_QUALITIES = (90, 80, 70, 60, 50)
STATIC_ALPHA_QUALITY = 90
ENGINE = "remotion"


def clean_message(message: str) -> str:
    """The message as drawn: spaces collapsed. Raises `ValueError` when empty or too long
    (the service turns it into Spanish)."""
    words = " ".join((message or "").split())
    if not words:
        raise ValueError("empty message")
    if len(words) > MAX_MESSAGE_CHARS:
        raise ValueError(f"message over {MAX_MESSAGE_CHARS} characters")
    return words


def motion_for(message: str) -> str:
    """`rebote` for a one-line message, `latido` for a two-line one (module docstring)."""
    return MOTION_SHORT if len(clean_message(message)) <= ONE_LINE_CHARS else MOTION_LONG


def caption_colors(palette: tuple[str, ...] | list[str]) -> Backing:
    """The caption's ink and die-cut fill (`backing.text_backing`: WCAG 3:1, large text)."""
    return text_backing(palette)


def caption_props(
    look: BrandLook,
    *,
    motion: str,
    message: str,
    art_ref: str,
    font_ref: str | None,
    art_fill: Backing,
    caption: Backing,
) -> dict[str, Any]:
    """The `sticker` v2 props: the art with its die-cut fill, the message with its ink."""
    if motion not in CAPTION_MOTIONS:
        raise RecipeError(NO_SOURCE, f"no caption motion {motion!r}")
    brand: dict[str, Any] = {
        "name": "",
        "palette": list(look.palette or (_hex(look.primary), _hex(look.secondary))),
        "fonts": {"heading": look.family} if look.family else {},
    }
    if font_ref:
        brand["fontFiles"] = {"heading": font_ref}
    texts: dict[str, Any] = {"motion": motion, "text": message, "backing": art_fill.fill}
    if caption.ink:
        texts["captionInk"] = caption.ink
    if caption.dark:
        texts["captionBacking"] = caption.fill
    return {
        "meta": {
            "templateId": TEMPLATE_ID,
            "version": CAPTION_TEMPLATE_VERSION,
            "port": SHEET_PORT,
        },
        "brand": brand,
        "texts": texts,
        "art": art_ref,
    }


@dataclass(frozen=True)
class ProductSticker:
    """One drawn product sticker: the file and what the library row records."""

    data: bytes
    animated: bool
    width: int
    height: int
    duration_ms: int
    frames: int
    quality: int
    motion: str
    pipeline_version: str = PIPELINE_VERSION_PRODUCT
    engine: str = ENGINE

    @property
    def bytes(self) -> int:
        return len(self.data)


def caption_frames(
    renderer: RemotionStickerRenderer,
    look: BrandLook,
    *,
    art: Image.Image,
    message: str,
    motion: str | None = None,
) -> tuple[list[Image.Image], str]:
    """The sheet's frames of the character `art` (RGBA cut-out) over `message`, and the
    motion used. `StickerRenderError` when the service cannot draw it."""
    words = clean_message(message)
    chosen = motion or motion_for(words)
    palette = tuple(look.palette or (_hex(look.primary), _hex(look.secondary)))
    art_bytes = art_png(art)
    try:
        art_fill = art_backing(art, palette)
    except Exception:  # noqa: BLE001 — measuring is a nicety, never a failure
        art_fill = Backing(WHITE, 0.0, 0.0, REASON_UNMEASURED)
    caption = caption_colors(palette)
    frames = renderer.sheet(
        art_bytes=art_bytes,
        font=look.font,
        build_props=lambda art_ref, font_ref: caption_props(
            look,
            motion=chosen,
            message=words,
            art_ref=art_ref or "",
            font_ref=font_ref,
            art_fill=art_fill,
            caption=caption,
        ),
        version=CAPTION_TEMPLATE_VERSION,
    )
    return frames, chosen


def static_sticker(frame: Image.Image) -> tuple[bytes, int]:
    """Frame 0 as a single-frame WebP ≤ `MAX_STATIC_BYTES` (Pillow encodes, never draws)."""
    for quality in STATIC_QUALITIES:
        buf = io.BytesIO()
        frame.convert("RGBA").save(
            buf, format="WEBP", quality=quality, method=6, alpha_quality=STATIC_ALPHA_QUALITY
        )
        if buf.tell() <= MAX_STATIC_BYTES:
            data = buf.getvalue()
            validate_static_sticker(data)
            return data, quality
    raise RecipeError(TOO_LARGE, "static sticker over 100 KB at every quality")


def validate_static_sticker(data: bytes) -> None:
    """A still WhatsApp sticker: one frame, 512×512, ≤ 100 KB, a transparent corner."""
    if len(data) > MAX_STATIC_BYTES:
        raise RecipeError(TOO_LARGE, f"{len(data)} bytes")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "WEBP" or image.size != (SIZE, SIZE):
            raise RecipeError(TOO_LARGE, "not a 512x512 WebP")
        if getattr(image, "n_frames", 1) != 1:
            raise RecipeError(TOO_LARGE, "a still sticker has one frame")
        corner = image.convert("RGBA").getpixel((0, 0))
        if not isinstance(corner, tuple) or corner[3] != 0:
            raise RecipeError(TOO_LARGE, "the background is not transparent")


def make_product_sticker(
    renderer: RemotionStickerRenderer,
    look: BrandLook,
    work: Path,
    *,
    art: Image.Image,
    message: str,
    animated: bool,
    motion: str | None = None,
) -> ProductSticker:
    """Draw one product sticker (module docstring). Raises `StickerRenderError` (the
    service; transient for the job) or `RecipeError` (too large, no source)."""
    frames, chosen = caption_frames(renderer, look, art=art, message=message, motion=motion)
    if not animated:
        data, quality = static_sticker(frames[0])
        return ProductSticker(
            data=data,
            animated=False,
            width=SIZE,
            height=SIZE,
            duration_ms=0,
            frames=1,
            quality=quality,
            motion=chosen,
        )
    result: StickerResult = encode_sticker(
        frames,
        work,
        encoder=functools.partial(_encode_pillow, alpha_quality=ALPHA_QUALITY_C),
        name="pillow",
        fps=renderer.spec.fps,
    )
    return ProductSticker(
        data=result.data,
        animated=True,
        width=result.width,
        height=result.height,
        duration_ms=result.duration_ms,
        frames=result.frames,
        quality=result.quality,
        motion=chosen,
    )


__all__ = [
    "CAPTION_TEMPLATE_VERSION",
    "MAX_MESSAGE_CHARS",
    "PIPELINE_VERSION_PRODUCT",
    "ProductSticker",
    "StickerRenderError",
    "caption_frames",
    "caption_props",
    "clean_message",
    "make_product_sticker",
    "motion_for",
    "static_sticker",
    "validate_static_sticker",
]
