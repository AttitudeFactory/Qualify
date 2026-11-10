"""«Crear con IA» for seasonal short videos (m-24976893; founder's decision 2026-11-08,
`docs/opciones-stickers-videos-cortos.md` §3 row D and §9): Seedance animates ONE approved
photo of the business. An option the owner picks per batch, never the default; the
estimated cost is shown BEFORE anything is generated; the paid call goes through
`creative-worker` (ADR 41 slots and price guard); IA makes VIDEOS only.

Pure helpers here (no network, no database): the cost estimate from the versioned price
table, what the screen shows («unos US$X por video»), the request's params and the ratio
of a photo. The executor that pays is `qualify_api.creative.seasonal_ai`.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from PIL import Image

from qualify_creative.adapters.byteplus_ark import (
    estimate_video_tokens,
    output_dimensions,
    video_cost_usd,
)
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import PricingTable

#: The cheapest Seedance for the beta: 1.0 pro fast, US$1.0 per million video tokens
#: (pricing v7) — a 5 s 480p clip ≈ 49k tokens ≈ US$0.05 [S] (2.5 measured US$0.53 [V]).
DEFAULT_AI_VIDEO_MODEL = "seedance-1-0-pro-fast-251015"
AI_VIDEO_SECONDS = 5
AI_VIDEO_RESOLUTION = "480p"
#: The pricing table the estimate and the real cost are read from (same as the generator).
AI_PRICING_VERSION = "v7"
#: Ratios a photo is animated in; the estimate prices the largest frame among them.
AI_RATIOS = ("1:1", "3:4", "9:16")
#: Provenance of the request (prompt + params); bump when either changes.
AI_PROMPT_VERSION = "seasonal-ai-1"
#: The prompt: natural motion that keeps the business's photo as it is (Seedance 1.0 is
#: silent and reads English best; the photo's text and product must not change).
AI_PROMPT = (
    "Subtle, natural motion of this exact photo: a slow, gentle camera push-in, soft "
    "light movement, steam or fabric moving slightly if present. Keep the product, the "
    "people, any text and logos exactly as they are; no new objects, no text changes, "
    "no scene change."
)
#: The photo sent as the first frame: its long side at most this (a data URL, not a link
#: — client data never leaves through a public URL).
FIRST_FRAME_MAX_SIDE = 1280
FIRST_FRAME_JPEG_QUALITY = 90
CENT = Decimal("0.01")


def pricing_table(version: str = AI_PRICING_VERSION) -> PricingTable:
    return JsonPricingTable(version)


def estimate_ai_video_cost_usd(
    model: str = DEFAULT_AI_VIDEO_MODEL,
    seconds: int = AI_VIDEO_SECONDS,
    resolution: str = AI_VIDEO_RESOLUTION,
    *,
    ratio: str | None = None,
    pricing: PricingTable | None = None,
) -> Decimal:
    """The estimated cost of ONE AI video, from the versioned price table and ModelArk's
    token formula (`width × height × 24 × seconds / 1024`). Without a `ratio` it prices
    the largest frame among `AI_RATIOS`, so the estimate never undercounts."""
    table = pricing or pricing_table()
    ratios = (ratio,) if ratio else AI_RATIOS
    tokens = max(estimate_video_tokens(model, resolution, r, seconds) for r in ratios)
    return video_cost_usd(table, model, resolution, tokens)


@dataclass(frozen=True)
class AiQuote:
    """What the owner reads before confirming: «unos US$0,05 por video» and the total."""

    videos: int
    per_video_usd: Decimal  # rounded UP to the cent
    total_usd: Decimal
    model: str
    pricing_version: str


def quote(
    videos: int, *, per_video_usd: Decimal | None = None, model: str = DEFAULT_AI_VIDEO_MODEL
) -> AiQuote:
    """The estimate as the screen shows it: per video rounded up to the cent, times the
    number of videos the batch will make."""
    raw = per_video_usd if per_video_usd is not None else estimate_ai_video_cost_usd(model)
    per = raw.quantize(CENT, rounding=ROUND_CEILING)
    return AiQuote(
        videos=videos,
        per_video_usd=per,
        total_usd=per * videos,
        model=model,
        pricing_version=AI_PRICING_VERSION,
    )


def ratio_for(image: Image.Image) -> str:
    """The `AI_RATIOS` ratio closest to the photo's own (height / width)."""
    aspect = image.height / max(1, image.width)

    def distance(ratio: str) -> float:
        w, h = (int(x) for x in ratio.split(":"))
        return abs(aspect - h / w)

    return min(AI_RATIOS, key=distance)


def first_frame_data_url(image: Image.Image) -> str:
    """The photo as a JPEG data URL, its long side at most `FIRST_FRAME_MAX_SIDE`."""
    frame = image.convert("RGB")
    frame.thumbnail((FIRST_FRAME_MAX_SIDE, FIRST_FRAME_MAX_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    frame.save(buf, format="JPEG", quality=FIRST_FRAME_JPEG_QUALITY)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def ai_video_params(
    first_frame: str,
    ratio: str,
    *,
    model: str = DEFAULT_AI_VIDEO_MODEL,
    seconds: int = AI_VIDEO_SECONDS,
    resolution: str = AI_VIDEO_RESOLUTION,
) -> dict[str, object]:
    """`SeedanceVideoAdapter` params for one seasonal AI video (image-to-video)."""
    output_dimensions(model, resolution, ratio)  # an unsupported combination fails here
    return {
        "model": model,
        "prompt": AI_PROMPT,
        "first_frame": first_frame,
        "ratio": ratio,
        "resolution": resolution,
        "duration_seconds": seconds,
        "camera_fixed": False,
        "return_last_frame": False,
    }
