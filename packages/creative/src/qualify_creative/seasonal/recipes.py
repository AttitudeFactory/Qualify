"""One entry point for both families: `run_recipe(name, ...)` → `RecipeOutput` (bytes +
metadata), with the pipeline version the row records as provenance."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from qualify_creative.seasonal.errors import UNKNOWN_RECIPE, RecipeError
from qualify_creative.seasonal.look import BrandLook
from qualify_creative.seasonal.sticker import STICKER_RECIPES, Encoder, make_sticker
from qualify_creative.seasonal.video import VIDEO_RECIPES, make_video

#: Provenance (`brand_seasonal_media.pipeline_version`): bump when a recipe's output
#: changes for the same inputs (a new motion curve, a new quality ladder…).
PIPELINE_VERSION_B = "seasonal-b-1"
PIPELINE_VERSION_E = "seasonal-e-1"
RECIPES = (*VIDEO_RECIPES, *STICKER_RECIPES)
KIND_VIDEO = "video"
KIND_STICKER = "sticker"


@dataclass(frozen=True)
class RecipeOutput:
    data: bytes
    kind: str  # video | sticker
    recipe: str
    content_type: str
    ext: str
    width: int
    height: int
    duration_ms: int
    frames: int
    bytes: int
    pipeline_version: str
    #: How it was encoded: `libx264 crf=30`, `ffmpeg-libwebp_anim q=70`, `pillow q=80`.
    encoding: str
    #: A video over the 1 MB target (still under WhatsApp's 16 MB).
    over_target: bool = False
    #: Provider cost — always 0: no paid call happens here (creative rule 1 has nothing
    #: to guard). Kept explicit so the row's provenance says so (creative rule 6).
    cost_usd: float = 0.0


def kind_of(recipe: str) -> str:
    if recipe in VIDEO_RECIPES:
        return KIND_VIDEO
    if recipe in STICKER_RECIPES:
        return KIND_STICKER
    raise RecipeError(UNKNOWN_RECIPE, recipe)


def pipeline_version(recipe: str) -> str:
    return PIPELINE_VERSION_B if kind_of(recipe) == KIND_VIDEO else PIPELINE_VERSION_E


def run_recipe(
    recipe: str,
    look: BrandLook,
    work: Path,
    *,
    images: Sequence[Image.Image] = (),
    text: str | None = None,
    sticker_encoder: Encoder | None = None,
    sticker_encoder_name: str = "",
) -> RecipeOutput:
    """Run `recipe` in the temp dir `work` (the caller owns and removes it). Videos take
    `images` (RGB, the approved stills, best first); image stickers take `images[0]` as a
    cut-out when given, else the logo; `e-texto` takes `text`."""
    kind = kind_of(recipe)
    if kind == KIND_VIDEO:
        video = make_video(recipe, images, look, work)
        return RecipeOutput(
            data=video.path.read_bytes(),
            kind=kind,
            recipe=recipe,
            content_type="video/mp4",
            ext="mp4",
            width=video.width,
            height=video.height,
            duration_ms=video.duration_ms,
            frames=video.frames,
            bytes=video.bytes,
            pipeline_version=PIPELINE_VERSION_B,
            encoding=f"libx264 crf={video.crf}",
            over_target=video.over_target,
        )
    sticker = make_sticker(
        recipe,
        look,
        work,
        art=images[0] if images else None,
        text=text,
        encoder=sticker_encoder,
        encoder_name=sticker_encoder_name,
    )
    return RecipeOutput(
        data=sticker.data,
        kind=kind,
        recipe=recipe,
        content_type="image/webp",
        ext="webp",
        width=sticker.width,
        height=sticker.height,
        duration_ms=sticker.duration_ms,
        frames=sticker.frames,
        bytes=sticker.bytes,
        pipeline_version=PIPELINE_VERSION_E,
        encoding=f"{sticker.encoder} q={sticker.quality}",
    )
