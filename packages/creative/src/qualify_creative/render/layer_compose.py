"""Compose one still from a layer (ADR 49 §2 «Remotion compone», m-25017285).

The Python half of the `layer_still` template (``packages/render/templates/layer_still``):
a `LayerSpec` (the layer Claude wrote, or the owner's edit), the base photo and the brand kit
become ONE render job for ONE port — a carousel of N slides is N jobs (ADR 49 §2.2). The
service runs the catalog's checks and its fixed fallback chain, renders, and reports the
layout it actually drew; this module hands that back so the caller records it with the piece.

Keys (ADR 49 §2.2 and §2.4, and the R2 rule that the bucket refuses to overwrite under
``t/``):

- **job id** = ``uuid5`` over the template version, ``version_id``, ``position``,
  ``spec_sha256``, ``layout_version``, the base photo's sha256, the port and a digest of every
  other input that changes pixels (brand kit, price line, slide). Same inputs → same job (a
  retry is idempotent on the service); any edit → a new job, never the old image.
- **object key** = ``t/{tenant}/generated/{draft}/compose/{layer_id}/{spec_sha256[:16]}/
  {job_id}/slide-{position+1}.jpg``: a re-compose after an edit is a new layer row and a new
  sha, so it lands on a new key and never overwrites.

Not wired into the pipeline: ``qualify_api/creative/image_pipeline/compose.py`` keeps the
current compositor until m-25017293. Nothing here imports Pillow; the caller's ``store``
converts the PNG to the publication JPEG (``to_meta_jpeg``) before writing it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from qualify_creative.render.client import (
    JobStatus,
    RemotionRenderClient,
    RenderServiceError,
)

TEMPLATE_ID = "layer_still"
TEMPLATE_VERSION = 1
#: The catalog version this template draws (manifest ``layer_catalog.layout_version``).
LAYOUT_VERSION = 1
MODEL_ID = "remotion_selfhost"

Format = Literal["4:5", "1:1", "9:16"]
#: Catalog format → the template's output port.
PORT_FOR_FORMAT: dict[str, str] = {"4:5": "feed", "1:1": "square", "9:16": "story"}

#: Fixed namespace of the compose job ids (never change it: ids would stop matching).
_JOB_NAMESPACE = uuid.UUID("6f1c2b9e-5d3a-4e7b-9a41-0c8d2f7e1b55")

MediaReader = Callable[[str], bytes]
#: ``store(object_key, png_bytes)``: converts and writes the still (R2: an object that already
#: exists with the same sha256 counts as stored).
StillStore = Callable[[str, bytes], None]


def canonical_json(value: Any) -> str:
    """The one serialisation the hashes are taken over (sorted keys, no spaces, UTF-8)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def spec_sha256(spec: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SlideInfo:
    """A carousel slide: 1-based ``index`` of ``total`` (2–10), with its catalog role."""

    index: int
    total: int
    role: Literal["cover", "body", "closing"]

    def to_payload(self) -> dict[str, Any]:
        return {"index": self.index, "total": self.total, "role": self.role}


@dataclass(frozen=True)
class LayerComposeRequest:
    """Everything one still needs. ``spec`` is the LayerSpec as stored in ``piece_layers.spec``
    (its ``info_blocks[].value`` already filled from the business's saved data — never by the
    model); ``base_key``/``logo_key`` are store keys, read and uploaded by the adapter."""

    tenant_id: str
    draft_id: str
    version_id: str
    layer_id: str
    position: int
    format: Format
    spec: Mapping[str, Any]
    brand: Mapping[str, Any]
    base_key: str | None = None
    base_sha256: str | None = None
    logo_key: str | None = None
    #: the catalog price of ``spec.price_ref``, already formatted whole in the business's
    #: currency (catalog §4); empty = no price line
    price_text: str = ""
    is_food: bool = False
    slide: SlideInfo | None = None
    #: ``piece_layers.spec_sha256`` when the caller has it; computed from ``spec`` otherwise
    spec_digest: str | None = None

    @property
    def port(self) -> str:
        try:
            return PORT_FOR_FORMAT[self.format]
        except KeyError:
            raise ValueError(f"unknown format {self.format!r}") from None

    @property
    def layout_version(self) -> int:
        raw = self.spec.get("layout_version", LAYOUT_VERSION)
        return int(raw) if isinstance(raw, int | str) else LAYOUT_VERSION

    @property
    def digest(self) -> str:
        return self.spec_digest or spec_sha256(self.spec)

    def _pixel_inputs(self) -> str:
        """A digest of the inputs outside the spec that change pixels."""
        brand = {k: v for k, v in self.brand.items() if k != "logo"}
        return hashlib.sha256(
            canonical_json(
                {
                    "brand": brand,
                    "logo_key": self.logo_key,
                    "price_text": self.price_text,
                    "is_food": self.is_food,
                    "slide": self.slide.to_payload() if self.slide else None,
                }
            ).encode("utf-8")
        ).hexdigest()

    def job_id(self) -> str:
        """ADR 49 §2.2: uuid5(version_id, position, spec_sha256, layout_version, base sha256),
        plus the template version, the port and the other pixel inputs."""
        name = "|".join(
            [
                f"{TEMPLATE_ID}@{TEMPLATE_VERSION}",
                self.version_id,
                str(self.position),
                self.digest,
                str(self.layout_version),
                self.base_sha256 or "-",
                self.port,
                self._pixel_inputs(),
            ]
        )
        return str(uuid.uuid5(_JOB_NAMESPACE, name))

    def object_key(self) -> str:
        return (
            f"t/{self.tenant_id}/generated/{self.draft_id}/compose/{self.layer_id}/"
            f"{self.digest[:16]}/{self.job_id()}/slide-{self.position + 1}.jpg"
        )


@dataclass(frozen=True)
class ComposedStill:
    job_id: str
    object_key: str
    png: bytes
    width: int | None
    height: int | None
    layout_requested: str
    #: the layout actually drawn — record THIS with the piece, not the requested one
    layout_rendered: str
    anchor: str | None
    fallbacks: tuple[str, ...]
    report: Mapping[str, Any]
    stored: bool
    warnings: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)


def build_layer_props(
    request: LayerComposeRequest, *, photo_ref: str | None, logo_ref: str | None
) -> dict[str, Any]:
    """The props of ``layer_still`` (CONTRACT §2 shape + ``layer``/``slide``)."""
    brand = dict(request.brand)
    brand["logo"] = logo_ref
    texts: dict[str, Any] = {"is_food": request.is_food}
    if request.price_text:
        texts["price_text"] = request.price_text
    return {
        "meta": {"templateId": TEMPLATE_ID, "version": TEMPLATE_VERSION, "port": request.port},
        "brand": brand,
        "texts": texts,
        "photos": [photo_ref] if photo_ref else [],
        "video": None,
        "products": [],
        "layer": dict(request.spec),
        "slide": request.slide.to_payload() if request.slide else None,
    }


def compose_layer(
    client: RemotionRenderClient,
    request: LayerComposeRequest,
    *,
    read_media: MediaReader,
    store: StillStore | None = None,
    timeout_seconds: float = 180.0,
) -> ComposedStill:
    """Upload the base and the logo, submit the one-port job, wait, download the PNG, and
    hand back the still with the layout actually rendered. A failed render raises
    ``RenderServiceError`` with the service's typed reason (``invalid_parameters`` for a layer
    that breaks the catalog); nothing is stored then, so a failed re-compose never destroys
    what the owner already had."""
    photo_ref = _upload(client, request.base_key, read_media) if request.base_key else None
    logo_ref = _upload(client, request.logo_key, read_media) if request.logo_key else None
    job_id = request.job_id()
    props = build_layer_props(request, photo_ref=photo_ref, logo_ref=logo_ref)
    job = client.render(
        job_id=job_id,
        template_id=TEMPLATE_ID,
        version=TEMPLATE_VERSION,
        props=props,
        outputs=[request.port],
    )
    if not job.status.terminal:
        job = client.wait(job_id, timeout_seconds=timeout_seconds)
    state = job.outputs.get(request.port)
    if state is None or state.status is not JobStatus.COMPLETED:
        code = (state.failure_reason if state else None) or job.status.value
        raise RenderServiceError(
            code,
            500,
            (state.error_message if state else None) or f"compose job {job_id} did not complete",
        )
    report = dict(state.report or {})
    if not report.get("layout_rendered"):
        raise RenderServiceError(
            "internal_error", 500, f"compose job {job_id} completed without a layout report"
        )
    png, _mime = client.download(job_id, request.port)
    key = request.object_key()
    stored = False
    if store is not None:
        store(key, png)
        stored = True
    return ComposedStill(
        job_id=job_id,
        object_key=key,
        png=png,
        width=state.width,
        height=state.height,
        layout_requested=str(report.get("layout_requested", request.spec.get("layout_id", ""))),
        layout_rendered=str(report["layout_rendered"]),
        anchor=report.get("anchor"),
        fallbacks=tuple(str(f) for f in report.get("fallbacks") or ()),
        report=report,
        stored=stored,
        warnings=tuple(job.warnings),
        provenance={
            "provider": "remotion",
            "model_id": MODEL_ID,
            "template": f"{TEMPLATE_ID}@{TEMPLATE_VERSION}",
            "layout_version": request.layout_version,
            "layer_id": request.layer_id,
            "spec_sha256": request.digest,
            "base_sha256": request.base_sha256,
            "job_id": job_id,
            "cost_usd": "0",
        },
    )


def _upload(client: RemotionRenderClient, key: str, read_media: MediaReader) -> str:
    data = read_media(key)
    lower = key.lower()
    if lower.endswith(".png"):
        content_type = "image/png"
    elif lower.endswith(".webp"):
        content_type = "image/webp"
    elif lower.endswith(".svg"):
        content_type = "image/svg+xml"
    else:
        content_type = "image/jpeg"
    return client.upload_asset(data, filename=key.rsplit("/", 1)[-1], content_type=content_type).ref
