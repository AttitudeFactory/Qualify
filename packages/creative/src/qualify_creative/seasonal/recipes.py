"""One entry point for both families: `run_recipe(name, ...)` → `RecipeOutput` (bytes +
metadata), with the pipeline version the row records as provenance.

Stickers have two engines (m-24987158): recipe C (the Remotion render service,
`sticker_c.py`) when a `sticker_renderer` is given, and recipe E (Pillow, `sticker.py`) —
the fallback whenever C cannot deliver. Videos likewise (m-25016848): recipe D (Remotion,
`video_d.py`) when a `video_renderer` is given, recipe B (FFmpeg, `video.py`) otherwise
or when D cannot deliver. The output says which one ran (`engine`, `pipeline_version`)
and why it fell back (`fallback`).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from qualify_creative.seasonal.errors import UNKNOWN_RECIPE, RecipeError
from qualify_creative.seasonal.look import BrandLook
from qualify_creative.seasonal.sticker import (
    STICKER_RECIPES,
    Encoder,
    StickerResult,
    make_sticker,
)
from qualify_creative.seasonal.sticker_c import (
    ENGINE_PILLOW,
    ENGINE_REMOTION,
    PIPELINE_VERSION_C,
    RemotionStickerRenderer,
    StickerRenderError,
    make_sticker_c,
)
from qualify_creative.seasonal.video import VIDEO_RECIPES, VideoResult, make_video
from qualify_creative.seasonal.video_d import (
    ENGINE_FFMPEG,
    PIPELINE_VERSION_D,
    RemotionVideoRenderer,
    VideoRenderError,
    make_video_d,
)

logger = logging.getLogger("qualify_creative.seasonal.recipes")

#: Provenance of the recipe that drew a medium: bump when a recipe's output changes for
#: the same inputs (a new motion curve, a new quality ladder…). It travels on
#: `RecipeOutput.pipeline_version` into the job's `result` and log line; the row's own
#: `brand_seasonal_media.pipeline_version` is the library's (`seasonal-v1`).
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
    #: How it was encoded: `libx264 crf=30`, `pillow q=70`, `remotion+pillow q=70`.
    encoding: str
    #: A video over the 1 MB target (still under WhatsApp's 16 MB).
    over_target: bool = False
    #: Provider cost — always 0: no paid call happens here (creative rule 1 has nothing
    #: to guard). Kept explicit so the row's provenance says so (creative rule 6).
    cost_usd: float = 0.0
    #: Who drew it: `remotion` (sticker recipe C, video recipe D), `pillow` (recipe E),
    #: `ffmpeg` (recipe B).
    engine: str = ""
    #: Why the Remotion recipe (C for a sticker, D for a video) was not used for a medium
    #: drawn by its fallback (`unreachable`, `not_ready`, `render_failed`, `too_large`…);
    #: "" when it ran or was not asked for.
    fallback: str = ""


def kind_of(recipe: str) -> str:
    if recipe in VIDEO_RECIPES:
        return KIND_VIDEO
    if recipe in STICKER_RECIPES:
        return KIND_STICKER
    raise RecipeError(UNKNOWN_RECIPE, recipe)


def pipeline_version(recipe: str) -> str:
    """The version recipe E/B would record; a sticker drawn by C records
    `PIPELINE_VERSION_C` and a video drawn by D `PIPELINE_VERSION_D` (see
    `RecipeOutput.pipeline_version`)."""
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
    sticker_renderer: RemotionStickerRenderer | None = None,
    video_renderer: RemotionVideoRenderer | None = None,
) -> RecipeOutput:
    """Run `recipe` in the temp dir `work` (the caller owns and removes it). Videos take
    `images` (RGB, the approved stills, best first); image stickers take `images[0]` as a
    cut-out when given, else the logo; `e-texto` takes `text`. A sticker goes through
    `sticker_renderer` (recipe C) when one is given, and through recipe E otherwise or
    when C fails; a video through `video_renderer` (recipe D) when one is given, and
    through recipe B otherwise or when D fails."""
    kind = kind_of(recipe)
    if kind == KIND_VIDEO:
        fallback = ""
        if video_renderer is not None:
            try:
                drawn = make_video_d(recipe, images, look, work, renderer=video_renderer)
            except VideoRenderError as exc:
                fallback = exc.code
                logger.warning(
                    "seasonal.video_fallback recipe=%s engine=%s reason=%s",
                    recipe,
                    ENGINE_FFMPEG,
                    exc,
                )
            else:
                return _video_output(
                    recipe, drawn, PIPELINE_VERSION_D, "remotion+libx264", ENGINE_REMOTION
                )
        video = make_video(recipe, images, look, work)
        return _video_output(recipe, video, PIPELINE_VERSION_B, "libx264", ENGINE_FFMPEG, fallback)
    art = images[0] if images else None
    fallback = ""
    if sticker_renderer is not None and sticker_encoder is None:
        try:
            drawn = make_sticker_c(
                recipe, look, work, renderer=sticker_renderer, art=art, text=text
            )
        except StickerRenderError as exc:
            fallback = exc.code
            logger.warning(
                "seasonal.sticker_fallback recipe=%s engine=%s reason=%s",
                recipe,
                ENGINE_PILLOW,
                exc,
            )
        else:
            return _sticker_output(
                recipe, drawn, PIPELINE_VERSION_C, f"remotion+{drawn.encoder}", ENGINE_REMOTION
            )
    sticker = make_sticker(
        recipe,
        look,
        work,
        art=art,
        text=text,
        encoder=sticker_encoder,
        encoder_name=sticker_encoder_name,
    )
    return _sticker_output(
        recipe, sticker, PIPELINE_VERSION_E, sticker.encoder, ENGINE_PILLOW, fallback
    )


def _video_output(
    recipe: str,
    video: VideoResult,
    version: str,
    encoder: str,
    engine: str,
    fallback: str = "",
) -> RecipeOutput:
    return RecipeOutput(
        data=video.path.read_bytes(),
        kind=KIND_VIDEO,
        recipe=recipe,
        content_type="video/mp4",
        ext="mp4",
        width=video.width,
        height=video.height,
        duration_ms=video.duration_ms,
        frames=video.frames,
        bytes=video.bytes,
        pipeline_version=version,
        encoding=f"{encoder} crf={video.crf}",
        over_target=video.over_target,
        engine=engine,
        fallback=fallback,
    )


def _sticker_output(
    recipe: str,
    sticker: StickerResult,
    version: str,
    encoder: str,
    engine: str,
    fallback: str = "",
) -> RecipeOutput:
    return RecipeOutput(
        data=sticker.data,
        kind=KIND_STICKER,
        recipe=recipe,
        content_type="image/webp",
        ext="webp",
        width=sticker.width,
        height=sticker.height,
        duration_ms=sticker.duration_ms,
        frames=sticker.frames,
        bytes=sticker.bytes,
        pipeline_version=version,
        encoding=f"{encoder} q={sticker.quality}",
        engine=engine,
        fallback=fallback,
    )
