"""`GenerationProvider` over the render service, so the existing router, budget check and
usage events treat a template render like any other engine (CONTRACT.md §6).

`request.params` carries everything the service needs — the manifest is validated and
the props built by the caller (`qualify_creative.render.props`), the adapter only moves
bytes: upload the media the props reference, submit the job with the draft-derived
`job_id` (idempotent), poll, download each completed output.

The payload is a mapping (not bytes) because a run yields several files:
`{"job_id", "status", "duration_sec", "warnings", "outputs": {port: {"bytes", "mime_type",
"width", "height", "duration_sec", "kind"}}}`. A partially failed job is NOT an
exception: the completed outputs come back, and `failed_ports` names the rest with their
typed reason — the draft keeps what rendered (plan §2.2).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from qualify_creative.enums import GenerationTask
from qualify_creative.providers import GenerationRequest, GenerationResult, PricingTable, Usage
from qualify_creative.render.client import (
    JobStatus,
    RemotionRenderClient,
    RenderJob,
    RenderServiceError,
    to_failure_reason,
)
from qualify_creative.render.props import ASSET_SCHEME, KEY_SCHEME, RenderProps

logger = logging.getLogger(__name__)

MODEL_ID = "remotion_selfhost"
PRICE_UNIT = "per_render"

MediaReader = Callable[[str], bytes]


@dataclass(frozen=True)
class _Spec:
    job_id: str
    template_id: str
    version: int
    props: RenderProps
    outputs: list[str] | None
    render_count: int
    timeout_seconds: float

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> _Spec:
        try:
            job_id = str(params["job_id"])
            template_id = str(params["template_id"])
            version = int(params["version"])  # type: ignore[arg-type]
            raw_props = params["props"]
        except KeyError as exc:
            raise ValueError(f"template render params missing {exc}") from None
        if isinstance(raw_props, RenderProps):
            props = raw_props
        else:
            props = RenderProps.model_validate(raw_props)
        outputs = params.get("outputs")
        out_list = [str(o) for o in outputs] if isinstance(outputs, list | tuple) else None
        count = params.get("render_count")
        if isinstance(count, int) and not isinstance(count, bool):
            render_count = count
        elif out_list:
            render_count = len(out_list)
        else:
            render_count = 1
        timeout = params.get("timeout_seconds")
        return cls(
            job_id=job_id,
            template_id=template_id,
            version=version,
            props=props,
            outputs=out_list,
            render_count=max(render_count, 1),
            timeout_seconds=float(timeout) if isinstance(timeout, int | float) else 600.0,
        )


class RemotionTemplateAdapter:
    """One engine, one implementation. `api_key` is accepted and ignored: our own service
    has no key (the credential resolver still hands one over for signature parity)."""

    name = "remotion"
    supports = frozenset({GenerationTask.TEMPLATE_RENDER})

    def __init__(
        self,
        client: RemotionRenderClient,
        *,
        read_media: MediaReader,
        content_type_for: Callable[[str], str] | None = None,
        on_progress: Callable[[RenderJob], None] | None = None,
    ) -> None:
        self._client = client
        self._read = read_media
        self._content_type_for = content_type_for or _guess_content_type
        self._on_progress = on_progress

    # -- GenerationProvider ------------------------------------------------------------

    def estimate_cost_usd(self, request: GenerationRequest, pricing: PricingTable) -> Decimal:
        spec = _Spec.from_params(request.params)
        rate = pricing.unit_price(model_id=MODEL_ID, unit=PRICE_UNIT)
        return rate * spec.render_count

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        spec = _Spec.from_params(request.params)
        props = self._upload_media(spec.props)
        leaked = props.unresolved()
        if leaked:
            raise ValueError(f"media references not uploaded to the render service: {leaked}")

        job = self._client.render(
            job_id=spec.job_id,
            template_id=spec.template_id,
            version=spec.version,
            props=props.to_payload(),
            outputs=spec.outputs,
        )
        if not job.status.terminal:
            job = self._client.wait(
                spec.job_id, timeout_seconds=spec.timeout_seconds, on_update=self._on_progress
            )

        outputs: dict[str, dict[str, Any]] = {}
        failed: dict[str, dict[str, str | None]] = {}
        for port, state in job.outputs.items():
            if state.status is JobStatus.COMPLETED:
                data, mime = self._client.download(job.job_id, port)
                outputs[port] = {
                    "bytes": data,
                    "mime_type": state.mime_type or mime,
                    "width": state.width,
                    "height": state.height,
                    "duration_sec": state.duration_sec,
                    "kind": state.kind,
                }
            elif state.status is JobStatus.FAILED:
                failed[port] = {
                    "failure_reason": to_failure_reason(state.failure_reason).value,
                    "error_message": state.error_message,
                }
            else:  # cancelled / never started
                failed[port] = {
                    "failure_reason": to_failure_reason("cancelled").value,
                    "error_message": state.error_message,
                }

        if not outputs:
            first = job.first_failure
            code = first.failure_reason if first else job.status.value
            raise RenderServiceError(
                code or "render_error",
                500,
                (first.error_message if first else None) or f"job {job.job_id} produced nothing",
            )

        duration = Decimal(str(job.duration_sec or 0))
        payload: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status.value,
            "duration_sec": float(duration),
            "warnings": list(job.warnings),
            "outputs": outputs,
            "failed_ports": failed,
            "template_id": spec.template_id,
            "template_version": spec.version,
        }
        return GenerationResult(
            payload=payload,
            model_id=MODEL_ID,
            provider=self.name,
            usage=Usage(pieces=len(outputs), media_seconds=duration),
            model_revision=f"{spec.template_id}@{spec.version}",
            media_url=None,
            media_expires_at_seconds=None,
        )

    # -- media -------------------------------------------------------------------------

    def _upload_media(self, props: RenderProps) -> RenderProps:
        """Upload every `key://` reference once and rewrite it to `asset://`."""
        mapping: dict[str, str] = {}
        for ref in props.media_refs():
            if ref in mapping or not ref.startswith(KEY_SCHEME):
                continue
            key = ref[len(KEY_SCHEME) :]
            data = self._read(key)
            asset = self._client.upload_asset(
                data, filename=key.rsplit("/", 1)[-1], content_type=self._content_type_for(key)
            )
            mapping[ref] = asset.ref
            logger.debug("uploaded %s → %s (%d bytes)", key, asset.ref, asset.bytes)
        return props.with_media(mapping)


def _guess_content_type(key: str) -> str:
    lower = key.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith((".mp4", ".m4v")):
        return "video/mp4"
    if lower.endswith(".mov"):
        return "video/quicktime"
    if lower.endswith(".svg"):
        return "image/svg+xml"
    return "application/octet-stream"


def is_asset_ref(ref: str) -> bool:
    return ref.startswith(ASSET_SCHEME)
