"""Brand stickers and short videos for a season (m-24976892; founder's decision
2026-11-08, `docs/opciones-stickers-videos-cortos.md` §9): the zero-cost beta B + E.

- **B** (`video.py`): a silent 3–5 s MP4 (H.264, 720 px short side) from the business's
  already-approved images with one simple motion — slow push-in, pan, cross-fade between
  2–3 stills, or a still with the logo fading in at the end.
- **E** (`sticker.py`): an animated WebP sticker, 512×512, ≤ 500 KB, transparent
  background, its frames drawn with Pillow from the Brand Kit logo, a cut-out product
  photo or a short seasonal text, in one of four fixed motions — encoded by FFmpeg's
  `libwebp_anim` (Pillow's WebP writer when the binary lacks it).

Every recipe is a pure function of local files + a `BrandLook`: no database, no R2, no
network and no paid call. `media-worker` runs them (`qualify_api.creative.seasonal_job`)
one at a time, inside its 1 CPU / 768 MB container, with FFmpeg on `-threads 1`. WHICH
recipes a season's batch holds is data in `qualify_api.whatsapp.seasonal.STANDARD_BATCH`
(the single source; the service plans from it).
"""

from qualify_creative.seasonal.errors import RecipeError
from qualify_creative.seasonal.look import BrandLook
from qualify_creative.seasonal.recipes import (
    PIPELINE_VERSION_B,
    PIPELINE_VERSION_E,
    RECIPES,
    RecipeOutput,
    pipeline_version,
    run_recipe,
)

__all__ = [
    "PIPELINE_VERSION_B",
    "PIPELINE_VERSION_E",
    "RECIPES",
    "BrandLook",
    "RecipeError",
    "RecipeOutput",
    "pipeline_version",
    "run_recipe",
]
