"""The owner's text over a video, drawn by Remotion (EF-05, m-25026573; D1 of ADR 50).

The Python half of the `video_text` template (``packages/render/templates/video_text``): one
text (what it says, its place, its ADR 49 design) and the brand kit become ONE render job whose
only output is a transparent 1080×1920 PNG — the layer that
``qualify_creative.video.text_overlay`` lays over the frames. Remotion never encodes the
video; PyAV does.

The layer is ADR 49's ``scrim`` drawn by ``layer_still``'s own engine and components (CONTRACT
§1, `video_text` v1): the same text in the same design looks the same in a 9:16 image and in a
video. Nothing here imports Pillow or draws anything.

Keys: the **job id** is ``uuid5`` over the template version, BOTH pixel revisions (the shared
engine's ``layer_catalog.engine_revision`` and this template's ``video_text.overlay_revision``),
the layout and its catalog version, the place, the text and the brand's fonts and palette. Same
inputs → same job (a retry is idempotent on the service, and the PNG is the same); any change
→ a new job, never «same key, different pixels».
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from qualify_creative.render.client import (
    JobStatus,
    RemotionRenderClient,
    RenderJob,
    RenderServiceError,
)
from qualify_creative.render.layer_compose import (
    TEMPLATE_ID as LAYER_TEMPLATE_ID,
)
from qualify_creative.render.layer_compose import (
    TEMPLATE_VERSION as LAYER_TEMPLATE_VERSION,
)
from qualify_creative.render.layer_compose import engine_revision

TEMPLATE_ID = "video_text"
TEMPLATE_VERSION = 1
PORT = "overlay"
#: The canvas of the layer: a 9:16 Reel.
CANVAS = (1080, 1920)
MODEL_ID = "remotion_selfhost"
#: The design a text without one is drawn with (`VideoTextLayer.layout_id` None): the scrim,
#: the only one the editor offers and the only one a video text supports in v1.
DEFAULT_LAYOUT_ID = "scrim"
#: The designs `video_text` v1 draws (its manifest's `layout_id` enum).
SUPPORTED_LAYOUTS: tuple[str, ...] = ("scrim",)

#: Fixed namespace of the job ids (never change it: ids would stop matching).
_JOB_NAMESPACE = uuid.UUID("0b7f5d2e-9c41-4a8e-8e2d-5f3a7c1e6b90")


@cache
def _manifest_block() -> Mapping[str, Any]:
    from qualify_creative.render.registry import TemplateRegistry  # noqa: PLC0415

    block = TemplateRegistry.from_dir().get(TEMPLATE_ID, TEMPLATE_VERSION).video_text or {}
    if not block:
        raise ValueError("video_text manifest has no video_text block")
    return block


@cache
def overlay_revision() -> int:
    """This template's own pixel revision (manifest ``video_text.overlay_revision``)."""
    rev = _manifest_block().get("overlay_revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        raise ValueError("video_text manifest has no overlay_revision")
    return rev


@cache
def config_digest() -> str:
    """A digest of the manifest's ``video_text`` block (title lines, scrim heights, the centre
    of «middle»…): it moves pixels, so it is part of the job id — a change to it is a new job
    even if nobody bumped ``overlay_revision``."""
    return hashlib.sha256(_canonical(dict(_manifest_block())).encode("utf-8")).hexdigest()[:16]


@cache
def layout_version() -> int:
    """The ADR 49 catalog version the render draws (``layer_still``'s
    ``layer_catalog.layout_version``): a text naming another one is refused."""
    from qualify_creative.render.registry import TemplateRegistry  # noqa: PLC0415

    catalog = (
        TemplateRegistry.from_dir().get(LAYER_TEMPLATE_ID, LAYER_TEMPLATE_VERSION).layer_catalog
        or {}
    )
    version = catalog.get("layout_version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("layer_still manifest has no layout_version")
    return version


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def brand_props(brand: Any) -> dict[str, Any]:
    """The CONTRACT §2 ``brand`` of a video text from a ``BrandKit`` (``typeface`` as the
    heading face — the SAME resolved face the images use, see ``layer_compose`` —, the body
    face or that one, the palette) or from a mapping already in that shape. No logo: the
    layer is only the scrim and the letters."""
    if isinstance(brand, Mapping):
        fonts = dict(brand.get("fonts") or {})
        return {
            "name": str(brand.get("name") or ""),
            "palette": [str(c) for c in brand.get("palette") or ()],
            "fonts": {k: str(v) for k, v in fonts.items() if v},
            "logo": None,
        }
    heading = str(getattr(brand, "typeface", "") or "")
    body = str(getattr(brand, "font_body", "") or "").strip() or heading
    fonts = {k: v for k, v in (("heading", heading), ("body", body)) if v}
    return {
        "name": "",
        "palette": [str(c) for c in getattr(brand, "palette_rgb", ()) or ()],
        "fonts": fonts,
        "logo": None,
    }


@dataclass(frozen=True)
class VideoTextRequest:
    """One text to draw. ``layout_id``/``layout_version`` None = the default design
    (``DEFAULT_LAYOUT_ID`` at the current catalog version)."""

    text: str
    place: str
    brand: Mapping[str, Any]
    layout_id: str | None = None
    layout_version: int | None = None

    @property
    def layout(self) -> str:
        return self.layout_id or DEFAULT_LAYOUT_ID

    @property
    def version(self) -> int:
        return self.layout_version if self.layout_version is not None else layout_version()

    def props(self) -> dict[str, Any]:
        return {
            "meta": {"templateId": TEMPLATE_ID, "version": TEMPLATE_VERSION, "port": PORT},
            "brand": dict(self.brand),
            "texts": {
                "text": self.text.strip(),
                "place": self.place,
                "layout_id": self.layout,
                "layout_version": self.version,
            },
            "photos": [],
            "video": None,
            "products": [],
        }

    def pixel_digest(self) -> str:
        """A digest of everything that changes the layer's pixels."""
        brand = {"palette": self.brand.get("palette") or [], "fonts": self.brand.get("fonts") or {}}
        return hashlib.sha256(
            _canonical(
                {
                    "text": self.text.strip(),
                    "place": self.place,
                    "layout_id": self.layout,
                    "layout_version": self.version,
                    "brand": brand,
                }
            ).encode("utf-8")
        ).hexdigest()

    def attempt_job_id(self, attempt: int) -> str:
        """The job id of render attempt ``attempt`` (0 = ``job_id()``). The service keeps a
        finished job — a failed or cancelled one too — under its id for up to a day and hands
        it back on a resubmit; a later attempt uses the next derived id so it renders afresh.
        Deterministic: the pixels still depend only on the inputs."""
        base = self.job_id()
        if attempt == 0:
            return base
        return str(uuid.uuid5(uuid.UUID(base), f"attempt-{attempt}"))

    def job_id(self) -> str:
        name = "|".join(
            [
                f"{TEMPLATE_ID}@{TEMPLATE_VERSION}",
                f"engine{engine_revision()}",
                f"overlay{overlay_revision()}",
                f"config{config_digest()}",
                self.pixel_digest(),
            ]
        )
        return str(uuid.uuid5(_JOB_NAMESPACE, name))


#: How many derived job ids a render may walk past (each one a job the service still holds
#: as failed or cancelled from an earlier try) before it gives up.
MAX_RENDER_ATTEMPTS = 5
_STALE = (JobStatus.FAILED, JobStatus.CANCELLED)


def _submit(
    client: RemotionRenderClient, request: VideoTextRequest, timeout_seconds: float
) -> tuple[str, int, RenderJob]:
    """Submit under the first attempt id whose job is not an old failure. A job the service
    answers already failed or cancelled at submission is an earlier try (a new job starts
    `pending`): unless it was a refusal — the same text is refused again, deterministically —
    the next derived id is tried, so «inténtalo de nuevo» really renders again. A job that
    fails during THIS call is returned as it is (the caller fails; its next call moves on)."""
    props = request.props()
    job: RenderJob | None = None
    for attempt in range(MAX_RENDER_ATTEMPTS):
        job_id = request.attempt_job_id(attempt)
        job = client.render(
            job_id=job_id,
            template_id=TEMPLATE_ID,
            version=TEMPLATE_VERSION,
            props=props,
            outputs=[PORT],
        )
        state = job.outputs.get(PORT)
        stale = job.status in _STALE and not (state is not None and state.refusal)
        if stale:
            continue
        if not job.status.terminal:
            job = client.wait(job_id, timeout_seconds=timeout_seconds)
        return job_id, attempt, job
    assert job is not None
    return request.attempt_job_id(MAX_RENDER_ATTEMPTS - 1), MAX_RENDER_ATTEMPTS - 1, job


class VideoTextRefused(RenderServiceError):
    """The service could not draw this text in its place (``invalid_parameters`` with a
    ``refusal``): ``reason`` says why (``word_too_wide`` — a word wider than the safe zone at
    the minimum size —, ``title_does_not_fit``, ``outside_safe_zone``). Retrying the same text
    returns the same failed job: the fix is another text."""

    def __init__(self, refusal: Mapping[str, Any], message: str) -> None:
        super().__init__("invalid_parameters", 422, message)
        self.refusal = dict(refusal)
        self.reason = str(refusal.get("reason", ""))
        self.detail = str(refusal.get("detail", ""))


@dataclass(frozen=True)
class VideoTextImage:
    job_id: str
    png: bytes
    width: int | None
    height: int | None
    report: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)


def render_video_text(
    client: RemotionRenderClient, request: VideoTextRequest, *, timeout_seconds: float = 180.0
) -> VideoTextImage:
    """Submit the one-port job, wait, download the transparent PNG. A failed render raises
    ``RenderServiceError`` with the service's typed reason — ``VideoTextRefused`` (a subclass)
    when the text cannot be drawn in its place. An unreachable service raises whatever the
    HTTP client raises (``httpx.TransportError``); the caller treats both alike."""
    if request.layout not in SUPPORTED_LAYOUTS:
        raise RenderServiceError(
            "invalid_parameters",
            422,
            f"video_text v1 draws {SUPPORTED_LAYOUTS}, not {request.layout!r}",
        )
    job_id, attempt, job = _submit(client, request, timeout_seconds)
    state = job.outputs.get(PORT)
    if state is None or state.status is not JobStatus.COMPLETED:
        code = (state.failure_reason if state else None) or job.status.value
        message = (state.error_message if state else None) or f"video text job {job_id} failed"
        if state is not None and state.refusal:
            raise VideoTextRefused(state.refusal, message)
        raise RenderServiceError(code, 500, message)
    report = dict(state.report or {})
    if report.get("layout_rendered") != request.layout or report.get("place") != request.place:
        raise RenderServiceError(
            "internal_error",
            500,
            f"video text job {job_id} reports {report.get('layout_rendered')!r}/"
            f"{report.get('place')!r}, asked {request.layout!r}/{request.place!r}",
        )
    png, _mime = client.download(job_id, PORT)
    return VideoTextImage(
        job_id=job_id,
        png=png,
        width=state.width,
        height=state.height,
        report=report,
        warnings=tuple(job.warnings),
        provenance={
            "provider": "remotion",
            "model_id": MODEL_ID,
            "template": f"{TEMPLATE_ID}@{TEMPLATE_VERSION}",
            "layout_id": request.layout,
            "layout_version": request.version,
            "engine_revision": report.get("engine_revision", engine_revision()),
            "overlay_revision": report.get("overlay_revision", overlay_revision()),
            "job_id": job_id,
            "render_attempt": attempt,
            "config_digest": config_digest(),
            "cost_usd": "0",
        },
    )


__all__ = [
    "CANVAS",
    "DEFAULT_LAYOUT_ID",
    "MAX_RENDER_ATTEMPTS",
    "MODEL_ID",
    "PORT",
    "SUPPORTED_LAYOUTS",
    "TEMPLATE_ID",
    "TEMPLATE_VERSION",
    "VideoTextImage",
    "VideoTextRefused",
    "VideoTextRequest",
    "brand_props",
    "config_digest",
    "layout_version",
    "overlay_revision",
    "render_video_text",
]
