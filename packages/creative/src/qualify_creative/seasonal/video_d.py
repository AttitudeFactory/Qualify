"""Recipe D — the seasonal short video drawn by the Remotion render service (m-25016848;
founder 2026-11-12: «los videos cortos también con Remotion, como los stickers»).

The render service (`packages/render`, template `seasonal_video` v1) draws the same four
slots recipe B fills — with eased camera moves instead of FFmpeg's linear `zoompan`, a
brand-colour wipe between photos instead of a plain cross-fade, and a logo card that
springs in on the brand's gradient (or closes a photo video as a small sign-off):

| slot      | motion     | photos | |
|-----------|------------|--------|-|
| `b-zoom`  | `acercar`  | 1      | push-in drifting to the upper third, sign-off |
| `b-pan`   | `recorrer` | 1      | pan across a 1.22× photo with a slow zoom, sign-off |
| `b-xfade` | `fundido`  | 2–3    | Ken Burns per photo, wipe with the brand's bands, sign-off |
| `b-logo`  | `logo`     | 0–1    | logo card, ring pulse and shine on the brand gradient |

The logo's card is white, or the brand's dark colour behind a light logo — the sticker's
contrast measure (`backing.art_backing`), with one more condition: the dark card must keep
at least 75 % of the logo legible (`MAX_LOST_ON_CARD`). A mixed logo — a dark wordmark
beside a gold emblem — loses its wordmark on the dark card, so it stays on white (bench
VIDEOS-D-001); a logo without transparency keeps white too (its own plate blends in).

The service renders a 720 px wide H.264 at 24 fps; this module re-encodes it with recipe
B's own settings (`clip_from_video`: H.264 Main without B-frames, `yuv420p`, `+faststart`,
no audio, the crf 28→32 ladder under the 1 MB target) and validates it with B's ffprobe
checks.

The slot names stay (they are part of each row's unique key). The provenance says which
engine drew it: `seasonal-d-1` when Remotion did, `seasonal-b-1` when recipe B did. **B
stays the fallback** (`run_recipe`): service off, unreachable, not ready, failed, timed
out, or an output that does not pass the checks — the reason is logged and kept on the
output (`RecipeOutput.fallback`).

Memory: the template asks the service for ONE Chromium tab (`render.concurrency` in its
manifest), photos are sent already cropped to 1.3× the frame, the logo ≤ 720 px. No paid
call: our own server, Remotion's free license (`remotion_selfhost` = 0).
"""

from __future__ import annotations

import io
import logging
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from qualify_creative.seasonal.backing import MAX_LOST_ON_WHITE, WHITE, art_backing
from qualify_creative.seasonal.errors import NO_SOURCE, UNKNOWN_RECIPE, RecipeError
from qualify_creative.seasonal.look import BrandLook, has_transparency
from qualify_creative.seasonal.sticker_c import RenderClient
from qualify_creative.seasonal.video import (
    VIDEO_RECIPES,
    VIDEO_WIDTH,
    VideoResult,
    _needed,
    clip_from_video,
    frame_size,
)

logger = logging.getLogger("qualify_creative.seasonal.video_d")

PIPELINE_VERSION_D = "seasonal-d-1"
TEMPLATE_ID = "seasonal_video"
TEMPLATE_VERSION = 1
CLIP_PORT = "clip"
#: The slot's recipe → the template's motion.
MOTION_OF: dict[str, str] = {
    "b-zoom": "acercar",
    "b-pan": "recorrer",
    "b-xfade": "fundido",
    "b-logo": "logo",
}
#: The logo slot without a photo: a 4:5 frame (recipe B used 1:1; a taller card reads
#: better in a phone's chat).
LOGO_ONLY_HEIGHT = 900
#: Photos travel cropped to the frame's aspect at this multiple of its size: the deepest
#: zoom is 1.26×, so the frame never upsamples them.
PHOTO_SCALE = 1.3
PHOTO_JPEG_QUALITY = 90
LOGO_MAX_SIDE = 720
#: The whole Remotion attempt (uploads + render wait + download) gets this long from the
#: health check on: a 4–5 s clip took 7–11 s in an arm64 container with 2 CPUs and one
#: Chromium tab (bench VIDEOS-D-001; production's CAX21 is ~2–3× slower). The wait gets
#: what is left of it, so D never holds the job past ~3.5 min (+ one call timeout and the
#: re-encode); B then has the rest of media-worker's 10-minute lease.
RENDER_TIMEOUT_SECONDS = 180.0
#: The render wait never gets less than this, even after slow uploads.
MIN_WAIT_SECONDS = 20.0
#: Each HTTP call (upload, submit, poll, download).
CALL_TIMEOUT_SECONDS = 20.0
HEALTH_TIMEOUT_SECONDS = 3.0
#: The service's own MP4 (crf 18) is a few MB; anything this large is not ours.
MAX_RAW_BYTES = 64 * 1024 * 1024
#: The dark card is used only while it loses less than this share of the logo's weight.
MAX_LOST_ON_CARD = MAX_LOST_ON_WHITE
ENGINE_REMOTION = "remotion"
ENGINE_FFMPEG = "ffmpeg"


class VideoRenderError(Exception):
    """The render service could not draw this video; `code` says why (logged, kept on the
    output as the fallback's reason)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class Card:
    """The logo card's fill and why (logged)."""

    fill: str
    reason: str


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def card_for(look: BrandLook) -> Card:
    """White, or the brand's dark colour behind a light logo (`backing.art_backing`) when
    that keeps the logo legible (`MAX_LOST_ON_CARD`). A logo with no transparency keeps
    white: its own background is a plate already."""
    if look.logo is None:
        return Card(WHITE, "no_logo")
    if not has_transparency(look.logo, min_share=0.02):
        return Card(WHITE, "opaque_logo")
    palette = look.palette or (_hex(look.primary), _hex(look.secondary))
    try:
        backing = art_backing(look.logo, palette)
    except Exception as exc:  # noqa: BLE001 — measuring is a nicety, never a failure
        logger.warning("video_d.card_unmeasured %s", type(exc).__name__)
        return Card(WHITE, "unmeasured")
    if backing.dark and backing.lost_on_fill >= MAX_LOST_ON_CARD:
        return Card(WHITE, "mixed_logo")
    return Card(backing.fill, backing.reason)


def photo_jpeg(image: Image.Image, size: tuple[int, int]) -> bytes:
    """The photo cropped to the frame's aspect, `PHOTO_SCALE`× the frame (never upscaled
    past the source), as a JPEG."""
    width, height = size
    target = (round(width * PHOTO_SCALE), round(height * PHOTO_SCALE))
    rgb = image.convert("RGB")
    shrink = min(1.0, rgb.width / target[0], rgb.height / target[1])
    if shrink < 1.0:  # a small source: crop to the aspect at its own resolution
        target = (max(2, round(target[0] * shrink)), max(2, round(target[1] * shrink)))
    fitted = ImageOps.fit(rgb, target, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    fitted.save(buf, format="JPEG", quality=PHOTO_JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def logo_png(logo: Image.Image) -> bytes:
    """The logo trimmed to its visible pixels, ≤ `LOGO_MAX_SIDE`, PNG with alpha."""
    rgba = logo.convert("RGBA")
    box = rgba.getchannel("A").getbbox()
    if box:
        rgba = rgba.crop(box)
    rgba.thumbnail((LOGO_MAX_SIDE, LOGO_MAX_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    rgba.save(buf, format="PNG")
    return buf.getvalue()


def plan(
    recipe: str, images: Sequence[Image.Image], look: BrandLook
) -> tuple[list[Image.Image], tuple[int, int]]:
    """The photos the slot uses and the frame size — the same source rules as recipe B
    (`no_source` before any network: no fallback would fix it)."""
    if recipe not in MOTION_OF:
        raise RecipeError(UNKNOWN_RECIPE, recipe)
    low, high = _needed(recipe)
    if len(images) < low:
        raise RecipeError(NO_SOURCE, f"{recipe} needs {low} approved image(s)")
    if recipe == "b-logo" and look.logo is None:
        raise RecipeError(NO_SOURCE, "b-logo needs the brand's logo")
    used = list(images)[:high]
    size = frame_size(used[0]) if used else (VIDEO_WIDTH, LOGO_ONLY_HEIGHT)
    return used, size


class RemotionVideoRenderer:
    """Renders a seasonal video through the render service. Every failure is a
    `VideoRenderError` (the caller falls back to recipe B)."""

    def __init__(
        self,
        client: RenderClient,
        *,
        health_client: RenderClient | None = None,
        timeout_seconds: float = RENDER_TIMEOUT_SECONDS,
        job_ids: Callable[[], str] = lambda: str(uuid.uuid4()),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._health = health_client or client
        self._timeout = timeout_seconds
        self._job_ids = job_ids
        self._clock = clock

    @classmethod
    def from_url(cls, base_url: str) -> RemotionVideoRenderer:
        from qualify_creative.render.client import RemotionRenderClient  # noqa: PLC0415

        return cls(
            RemotionRenderClient(base_url, timeout_seconds=CALL_TIMEOUT_SECONDS),
            health_client=RemotionRenderClient(base_url, timeout_seconds=HEALTH_TIMEOUT_SECONDS),
        )

    def _check_ready(self) -> None:
        try:
            health = self._health.health()
        except Exception as exc:  # noqa: BLE001 — DNS, refused, timeout: all "not there"
            raise VideoRenderError("unreachable", type(exc).__name__) from exc
        try:
            ready = bool(health.get("ok")) and bool(health.get("bundleReady"))
            has_template = any(
                t.get("id") == TEMPLATE_ID and int(t.get("version") or 0) >= TEMPLATE_VERSION
                for t in (health.get("templates") or [])
                if isinstance(t, Mapping)
            )
        except Exception as exc:  # noqa: BLE001 — an odd /health body is "not ready"
            raise VideoRenderError("not_ready", type(exc).__name__) from exc
        if not ready:
            raise VideoRenderError("not_ready")
        if not has_template:
            raise VideoRenderError("no_template", "the service has no seasonal_video v1")

    @staticmethod
    def props(
        recipe: str,
        look: BrandLook,
        *,
        height: int,
        photo_refs: Sequence[str],
        logo_ref: str | None,
        card: str,
    ) -> dict[str, Any]:
        palette = [_hex(look.primary), _hex(look.secondary)]
        palette += [c for c in look.palette if c.lower() not in {p.lower() for p in palette}]
        brand: dict[str, Any] = {
            "name": "",
            "palette": palette,
            "fonts": {"heading": look.family} if look.family else {},
        }
        if logo_ref:
            brand["logo"] = logo_ref
        return {
            "meta": {"templateId": TEMPLATE_ID, "version": TEMPLATE_VERSION, "port": CLIP_PORT},
            "brand": brand,
            "texts": {"motion": MOTION_OF[recipe], "height": height, "card": card},
            "photos": list(photo_refs),
        }

    def render(
        self, recipe: str, images: Sequence[Image.Image], look: BrandLook, work: Path
    ) -> tuple[Path, tuple[int, int]]:
        """The service's MP4 for `recipe`, written to `work/remotion.mp4`, and the frame
        size it was asked for."""
        used, size = plan(recipe, images, look)
        card = card_for(look)
        logger.info("video_d.card recipe=%s fill=%s reason=%s", recipe, card.fill, card.reason)
        try:
            photos = [photo_jpeg(im, size) for im in used]
            logo = logo_png(look.logo) if look.logo is not None else None
        except Exception as exc:  # noqa: BLE001 — an odd image: B may still draw it
            raise VideoRenderError("bad_source", type(exc).__name__) from exc
        deadline = self._clock() + self._timeout
        self._check_ready()
        job_id = self._job_ids()
        try:
            photo_refs = [
                self._client.upload_asset(
                    data, filename=f"photo{i}.jpg", content_type="image/jpeg"
                ).ref
                for i, data in enumerate(photos)
            ]
            logo_ref = (
                self._client.upload_asset(logo, filename="logo.png", content_type="image/png").ref
                if logo
                else None
            )
            props = self.props(
                recipe,
                look,
                height=size[1],
                photo_refs=photo_refs,
                logo_ref=logo_ref,
                card=card.fill,
            )
            self._client.render(
                job_id=job_id,
                template_id=TEMPLATE_ID,
                version=TEMPLATE_VERSION,
                props=props,
                outputs=[CLIP_PORT],
            )
            left = max(MIN_WAIT_SECONDS, deadline - self._clock())
            job = self._client.wait(job_id, timeout_seconds=left)
            status = str(getattr(getattr(job, "status", None), "value", getattr(job, "status", "")))
            if status != "completed":
                failure = getattr(job, "first_failure", None)
                reason = getattr(failure, "failure_reason", None) or status
                raise VideoRenderError("render_failed", str(getattr(reason, "value", reason)))
            data, _mime = self._client.download(job_id, CLIP_PORT)
        except VideoRenderError:
            raise
        except Exception as exc:  # noqa: BLE001 — the client's errors, timeouts, I/O
            code = getattr(exc, "code", None) or type(exc).__name__
            raise VideoRenderError("render_failed", str(code)) from exc
        if not data or len(data) > MAX_RAW_BYTES:
            raise VideoRenderError("bad_output", f"{len(data or b'')} bytes")
        raw = work / "remotion.mp4"
        try:
            raw.write_bytes(data)
        except OSError as exc:
            raise VideoRenderError("bad_output", type(exc).__name__) from exc
        return raw, size


def make_video_d(
    recipe: str,
    images: Sequence[Image.Image],
    look: BrandLook,
    work: Path,
    *,
    renderer: RemotionVideoRenderer,
) -> VideoResult:
    """Recipe D for slot `recipe`: Remotion's MP4, re-encoded and checked like recipe B.
    Anything but a source problem is a `VideoRenderError` (B may still make it)."""
    if recipe not in VIDEO_RECIPES:
        raise RecipeError(UNKNOWN_RECIPE, recipe)
    raw, size = renderer.render(recipe, images, look, work)
    try:
        video = clip_from_video(raw, work)
    except RecipeError as exc:
        raise VideoRenderError(exc.code, exc.detail) from exc
    if (video.width, video.height) != size:
        raise VideoRenderError("bad_output", f"{video.width}x{video.height} != {size}")
    return video
