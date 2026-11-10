"""Recipe C — the seasonal sticker drawn by the Remotion render service (m-24987158;
founder 2026-11-09, `docs/opciones-stickers-videos-cortos.md` §9: recipe E's Pillow frames
looked poor).

The render service (`packages/render`, template `sticker` v1) draws the die-cut sticker —
a thick rounded white outline around the art's own shape, a soft drop shadow, the Brand
Kit's colours and heading face, spring motions that start and end at rest — and returns
EVERY frame of the 2 s loop as one transparent PNG grid (`sheet` port, a still: the
service's stills keep alpha, its videos are H.264 and would not). This module slices the
grid and encodes the animated WebP with recipe E's own encoder, quality ladder and
`validate_sticker` (WhatsApp's rules do not change: 512×512, ≤ 500 KB, transparent).

The slot names stay the same (`e-latido`, `e-rebote`, `e-giro`, `e-brillo`, `e-texto`):
they are part of each `brand_seasonal_media` row's identity (`uq_brand_seasonal_media_slot`),
so a new name would plan a second batch next to the old one. What changes is the engine
and the recipe version recorded as provenance: `seasonal-c-1` when Remotion drew it,
`seasonal-e-1` when recipe E did.

**Recipe E stays as the fallback** (`run_recipe`): while the `render` compose profile is
off in production, or whenever the service is unreachable, not ready, fails, times out or
yields something WhatsApp would refuse, the same slot is drawn by Pillow and the reason is
logged and kept on the output (`RecipeOutput.fallback`).

No paid call: the service runs on our own machine under Remotion's free license (pricing
table `remotion_selfhost` = 0, founder 2026-11-09).
"""

from __future__ import annotations

import functools
import io
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from qualify_creative.seasonal.errors import NO_SOURCE, UNKNOWN_RECIPE, RecipeError
from qualify_creative.seasonal.look import BrandLook
from qualify_creative.seasonal.sticker import (
    DEFAULT_TEXT,
    MARGIN,
    STICKER_RECIPES,
    StickerResult,
    _encode_pillow,
    _trim,
    default_encoder,
    encode_sticker,
    image_base,
)

logger = logging.getLogger("qualify_creative.seasonal.sticker_c")

PIPELINE_VERSION_C = "seasonal-c-1"
TEMPLATE_ID = "sticker"
TEMPLATE_VERSION = 1
SHEET_PORT = "sheet"
#: The slot's recipe → the template's motion.
MOTION_OF: dict[str, str] = {
    "e-latido": "latido",
    "e-rebote": "rebote",
    "e-giro": "giro",
    "e-brillo": "brillo",
    "e-texto": "texto",
}
#: The manifest's `text` port.
MAX_TEXT_CHARS = 80
#: The art is sent trimmed to its shape and no larger than this (the sticker draws it at
#: ≤ 360 px; twice that keeps the edge crisp without shipping a 1600 px upload).
ART_MAX_SIDE = 720
#: One sticker renders in ~5–11 s warm (bench STICKERS-002); past this the render job is
#: cancelled and E draws it.
RENDER_TIMEOUT_SECONDS = 120.0
#: Each HTTP call (upload, submit, poll, download). With the render wait above, the worst
#: stall before E takes over is ~4 min — well inside media-worker's 10-minute job lease.
CALL_TIMEOUT_SECONDS = 20.0
#: `/health` must answer fast: a stopped profile means a DNS failure, not a hang.
HEALTH_TIMEOUT_SECONDS = 3.0
#: libwebp's alpha-plane quality for recipe C (bench m-24987158: the lossless alpha of
#: the soft shadow and outline was ~35 % of a 450 KB sticker; 70 cut it with no visible
#: change on WhatsApp's light and dark backgrounds). Recipe E keeps lossless alpha.
ALPHA_QUALITY_C = 70
#: Engine names recorded on the output.
ENGINE_REMOTION = "remotion"
ENGINE_PILLOW = "pillow"


@dataclass(frozen=True)
class SheetSpec:
    """The grid the `sheet` still holds: `frames` cells of `cell` px, `columns` per row,
    sampled at `fps` (the manifest's `sheet` block)."""

    cell: int = 512
    columns: int = 6
    frames: int = 30
    fps: int = 15

    @classmethod
    def from_manifest(cls, path: Path | None = None) -> SheetSpec:
        """Read from `packages/render/templates/sticker/manifest.json` (the same numbers the
        composition draws with); the defaults above when the file is not there."""
        from qualify_creative.render.registry import default_templates_dir  # noqa: PLC0415

        path = path or default_templates_dir() / TEMPLATE_ID / "manifest.json"
        try:
            sheet = json.loads(path.read_text(encoding="utf-8"))["sheet"]
        except (OSError, KeyError, ValueError):
            return cls()
        return cls(
            cell=int(sheet["cell"]),
            columns=int(sheet["columns"]),
            frames=int(sheet["frames"]),
            fps=int(sheet["fps"]),
        )


class StickerRenderError(Exception):
    """The render service could not draw this sticker; `code` says why (logged, kept on
    the output as the fallback's reason)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class RenderClient(Protocol):
    """The `RemotionRenderClient` methods used here (CONTRACT §4)."""

    def health(self) -> Mapping[str, Any]: ...

    def upload_asset(self, data: bytes, *, filename: str, content_type: str) -> Any: ...

    def render(
        self,
        *,
        job_id: str,
        template_id: str,
        version: int,
        props: Mapping[str, Any],
        outputs: list[str] | None = None,
    ) -> Any: ...

    def wait(self, job_id: str, *, timeout_seconds: float = ...) -> Any: ...

    def download(self, job_id: str, port: str) -> tuple[bytes, str]: ...


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _font_type(data: bytes) -> str:
    head = data[:4]
    if head == b"wOF2":
        return "font/woff2"
    if head == b"OTTO":
        return "font/otf"
    return "font/ttf"


def art_png(art: Image.Image) -> bytes:
    """The art as the template wants it: trimmed to its shape, ≤ `ART_MAX_SIDE`, PNG.
    Refuses (like recipe E) an image with no transparency to cut by."""
    image_base(art)  # the same `no_source` check recipe E makes, before any network
    trimmed = _trim(art.convert("RGBA"))
    trimmed.thumbnail((ART_MAX_SIDE, ART_MAX_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    trimmed.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def slice_sheet(sheet: Image.Image, spec: SheetSpec) -> list[Image.Image]:
    """The grid's cells, left to right, top to bottom, as RGBA frames. A frame whose art
    reaches into WhatsApp's 16 px margin is refused (`margin`): the template keeps its
    motions inside it, so this only trips on a template bug."""
    rows = -(-spec.frames // spec.columns)
    expected = (spec.columns * spec.cell, rows * spec.cell)
    if sheet.size != expected:
        raise StickerRenderError("bad_sheet", f"{sheet.size} != {expected}")
    rgba = sheet.convert("RGBA")
    frames = []
    for i in range(spec.frames):
        x, y = (i % spec.columns) * spec.cell, (i // spec.columns) * spec.cell
        frame = rgba.crop((x, y, x + spec.cell, y + spec.cell))
        if _crosses_margin(frame):
            raise StickerRenderError("margin", f"frame {i}")
        frames.append(frame)
    return frames


#: Alpha above this inside the margin is art, not the soft shadow (≤ 35 % opaque).
_MARGIN_ALPHA = 128


def _crosses_margin(frame: Image.Image) -> bool:
    solid = frame.getchannel("A").point(lambda a: 255 if a > _MARGIN_ALPHA else 0)
    box = solid.getbbox()
    if box is None:
        return False
    left, top, right, bottom = box
    edge = frame.width - MARGIN
    return left < MARGIN or top < MARGIN or right > edge or bottom > edge


class RemotionStickerRenderer:
    """Draws a sticker's frames through the render service. Every failure is a
    `StickerRenderError` (the caller falls back to recipe E)."""

    def __init__(
        self,
        client: RenderClient,
        *,
        health_client: RenderClient | None = None,
        spec: SheetSpec | None = None,
        timeout_seconds: float = RENDER_TIMEOUT_SECONDS,
        job_ids: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._client = client
        self._health = health_client or client
        self.spec = spec or SheetSpec.from_manifest()
        self._timeout = timeout_seconds
        self._job_ids = job_ids

    @classmethod
    def from_url(cls, base_url: str) -> RemotionStickerRenderer:
        from qualify_creative.render.client import RemotionRenderClient  # noqa: PLC0415

        return cls(
            RemotionRenderClient(base_url, timeout_seconds=CALL_TIMEOUT_SECONDS),
            health_client=RemotionRenderClient(base_url, timeout_seconds=HEALTH_TIMEOUT_SECONDS),
        )

    def _check_ready(self) -> None:
        try:
            health = self._health.health()
        except Exception as exc:  # noqa: BLE001 — DNS, refused, timeout: all "not there"
            raise StickerRenderError("unreachable", type(exc).__name__) from exc
        try:
            ready = bool(health.get("ok")) and bool(health.get("bundleReady"))
            templates = health.get("templates") or []
            has_sticker = any(
                t.get("id") == TEMPLATE_ID and int(t.get("version") or 0) >= TEMPLATE_VERSION
                for t in templates
                if isinstance(t, Mapping)
            )
        except Exception as exc:  # noqa: BLE001 — an odd /health body is "not ready", never a crash
            raise StickerRenderError("not_ready", type(exc).__name__) from exc
        if not ready:
            raise StickerRenderError("not_ready")
        if not has_sticker:
            raise StickerRenderError("no_template", "the service has no sticker v1")

    def props(
        self,
        recipe: str,
        look: BrandLook,
        *,
        art_ref: str | None,
        font_ref: str | None,
        text: str | None,
    ) -> dict[str, Any]:
        brand: dict[str, Any] = {
            "name": "",
            "palette": [_hex(look.primary), _hex(look.secondary)],
            "fonts": {"heading": look.family} if look.family else {},
        }
        if font_ref:
            brand["fontFiles"] = {"heading": font_ref}
        texts: dict[str, Any] = {"motion": MOTION_OF[recipe]}
        if text:
            texts["text"] = text
        props: dict[str, Any] = {
            "meta": {"templateId": TEMPLATE_ID, "version": TEMPLATE_VERSION, "port": SHEET_PORT},
            "brand": brand,
            "texts": texts,
        }
        if art_ref:
            props["art"] = art_ref
        return props

    def frames(
        self,
        recipe: str,
        look: BrandLook,
        *,
        art: Image.Image | None = None,
        text: str | None = None,
    ) -> list[Image.Image]:
        """The sticker's frames (RGBA, `spec.cell` px). Source problems raise
        `RecipeError(no_source)` exactly like recipe E (no fallback would fix them);
        everything else raises `StickerRenderError`."""
        if recipe not in MOTION_OF:
            raise RecipeError(UNKNOWN_RECIPE, recipe)
        words: str | None = None
        art_bytes: bytes | None = None
        if recipe == "e-texto":
            words = " ".join((text or DEFAULT_TEXT).split())
            if not words:
                raise RecipeError(NO_SOURCE, "e-texto needs a text")
            if len(words) > MAX_TEXT_CHARS:
                raise StickerRenderError("text_too_long", f"{len(words)} chars")
        else:
            source = art if art is not None else look.logo
            if source is None:
                raise RecipeError(NO_SOURCE, f"{recipe} needs the logo or a cut-out photo")
            art_bytes = art_png(source)
        self._check_ready()
        job_id = self._job_ids()
        try:
            art_ref = (
                self._client.upload_asset(
                    art_bytes, filename="art.png", content_type="image/png"
                ).ref
                if art_bytes
                else None
            )
            font_ref = (
                self._client.upload_asset(
                    look.font, filename="heading-font", content_type=_font_type(look.font)
                ).ref
                if look.font
                else None
            )
            props = self.props(recipe, look, art_ref=art_ref, font_ref=font_ref, text=words)
            self._client.render(
                job_id=job_id,
                template_id=TEMPLATE_ID,
                version=TEMPLATE_VERSION,
                props=props,
                outputs=[SHEET_PORT],
            )
            job = self._client.wait(job_id, timeout_seconds=self._timeout)
            status = str(getattr(getattr(job, "status", None), "value", getattr(job, "status", "")))
            if status != "completed":
                failure = getattr(job, "first_failure", None)
                reason = getattr(failure, "failure_reason", None) or status
                raise StickerRenderError("render_failed", str(reason))
            data, _mime = self._client.download(job_id, SHEET_PORT)
        except StickerRenderError:
            raise
        except Exception as exc:  # noqa: BLE001 — the client's errors, timeouts, I/O
            code = getattr(exc, "code", None) or type(exc).__name__
            raise StickerRenderError("render_failed", str(code)) from exc
        try:
            with Image.open(io.BytesIO(data)) as sheet:
                sheet.load()
                return slice_sheet(sheet, self.spec)
        except StickerRenderError:
            raise
        except Exception as exc:  # noqa: BLE001 — not a PNG
            raise StickerRenderError("bad_sheet", type(exc).__name__) from exc


def make_sticker_c(
    recipe: str,
    look: BrandLook,
    work: Path,
    *,
    renderer: RemotionStickerRenderer,
    art: Image.Image | None = None,
    text: str | None = None,
) -> StickerResult:
    """Recipe C for slot `recipe`: Remotion frames, recipe E's encoder and checks. An
    output WhatsApp would refuse (too large even at the lowest rung) is a
    `StickerRenderError` too — E's simpler frames may still fit."""
    if recipe not in STICKER_RECIPES:
        raise RecipeError(UNKNOWN_RECIPE, recipe)
    frames = renderer.frames(recipe, look, art=art, text=text)
    try:
        default_encoder()  # `webp_unavailable` before any work
        return encode_sticker(
            frames,
            work,
            encoder=functools.partial(_encode_pillow, alpha_quality=ALPHA_QUALITY_C),
            name="pillow",
            fps=renderer.spec.fps,
        )
    except RecipeError as exc:
        if exc.code == NO_SOURCE:
            raise
        raise StickerRenderError(exc.code, exc.detail) from exc
