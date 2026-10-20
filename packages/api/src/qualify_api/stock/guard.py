"""Where a stock file may go in a piece, checked before any read or spend (plan §5.2,
STK-05; founder's review R2 of 2026-10-16).

Both licences forbid publishing stock «standalone»: it must be combined into a new work.
Every route that takes a stock key today produces one (Seedream scenes, the flyer's
composition, Seedance clips, the template's composition), so the rule is about WHICH
fields may carry such a key:

- always: the background, the clip's references (images in any role, videos, frames)
  and the product photos — since 2026-10-19 «Inspiración» feeds every slot (founder:
  «en todos lados quiero la opción desde las inspiraciones»), so a stock product photo
  no longer needs `media.product_source == "stock"`. That field stays as provenance (the
  operator chose the inspiration as the product), not as a permission: a flag the client
  sets cannot be what lets a file through;
- a gallery's «Video de stock» slide (`SlideSource.STOCK`): always — the producer fits
  it with the slide's words and the logo over it, locally, no model involved;
- an animated slide's motion reference (`CarouselSlide.reference_video_key`, 2026-10-19):
  always — like a clip's reference video, it is followed, never shown;
- the reference video of Avatar and Ad (2026-10-19, founder: «en el video de referencia
  de los avatar me hace falta la opción de inspiraciones»): always — it guides, it is
  never shown;
- never: the avatar's own image, the brand's logo and elements, the source media of the
  «from upload» routes (they publish the file as is), the audio, and a «De una pieza»
  slide (`EXISTING`: reused as it is).

A clip whose only visual material is stock is refused: a clip carries no text or logo on
top, so it would be stock animated. And a stock key from a provider outside the closed
list of AI-allowed banks, or with the AI flag off (`QUALIFY_STOCK_AI_REFERENCE`, F1 —
default on while the founder tests with his own brands), never reaches a model.
"""

from __future__ import annotations

import os

from qualify_creative.enums import SlideSource
from qualify_creative.schemas import ContentBrief

from qualify_api.stock.keys import is_stock_key, stock_key_provider

AI_REFERENCE_ENV = "QUALIFY_STOCK_AI_REFERENCE"
#: Banks whose files may be sent to Seedream/Seedance as a reference — closed in code.
AI_REFERENCE_PROVIDERS: frozenset[str] = frozenset({"pixabay", "pexels"})

MISPLACED_TEXT = "Esa imagen de stock no puede usarse ahí. Elige una foto de tu marca."
STOCK_ONLY_CLIP_TEXT = (
    "Un clip no puede hacerse solo con imágenes de stock: añade al menos una foto o un video tuyo."
)
OFF_TEXT = "Las imágenes de stock no están disponibles ahora mismo. Elige otra foto."


def ai_reference_on() -> bool:
    return os.environ.get(AI_REFERENCE_ENV, "on").strip().casefold() not in ("off", "0", "false")


def stock_problems(brief: ContentBrief) -> str | None:
    """The operator-facing reason the piece must not use its stock files, or None."""
    media = brief.media
    never = [
        brief.source_media_key,
        media.avatar_image_key,
        media.brand_logo_key,
        *media.brand_element_keys,
        *media.clip_audio_keys,
        *(s.object_key for s in media.slides if s.source is SlideSource.EXISTING),
    ]
    stock_slides = [s.object_key for s in media.slides if s.source is SlideSource.STOCK]
    if any(not is_stock_key(k) for k in stock_slides):
        return MISPLACED_TEXT  # a «Video de stock» slide only takes a stock video
    product = list(media.product_keys)
    clip_images = media.clip_image_keys
    if any(is_stock_key(k) for k in never):
        return MISPLACED_TEXT

    allowed = [
        media.background_key,
        media.reference_video_key,
        *clip_images,
        *media.clip_video_keys,
        *(s.reference_video_key for s in media.slides if s.reference_video_key),
        media.clip_first_frame_key,
        media.clip_last_frame_key,
        *product,
    ]
    stock = [k for k in allowed if k and is_stock_key(k)]
    if not stock:
        return None
    if not ai_reference_on() or any(
        stock_key_provider(k) not in AI_REFERENCE_PROVIDERS for k in stock
    ):
        return OFF_TEXT

    visual = [
        k
        for k in (
            *clip_images,
            *media.clip_video_keys,
            media.clip_first_frame_key,
            media.clip_last_frame_key,
        )
        if k
    ]
    if brief.kind.value == "clip" and visual and all(is_stock_key(k) for k in visual):
        return STOCK_ONLY_CLIP_TEXT
    return None
