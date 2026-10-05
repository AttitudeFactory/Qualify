"""The media half of a draft: turn a brief and its winning copy into the artifact the
brief's `ContentKind` asks for (§ request 2026-09-25).

- `CREATOR_SCRIPT` — nothing: the script IS the artifact, and it lives in the copy.
- `STATIC_FLYER` — `qualify_creative.compose.render_flyer` over the operator's own
  images: one image, or the carousel's slides. Local, deterministic, free. Rendered as
  PNG and STORED AS JPEG (§ 2026-10-05): Meta accepts only JPEG images, and so does the
  publisher — every image this module writes goes through `to_meta_jpeg`.
- `AVATAR_VIDEO` / `ANIMATED_AVATAR_VIDEO` — HeyGen, through the `GenerationProvider`
  seam and the `CreativeRouter` (credential resolution + the budget pre-flight):
  1. background + products composed into ONE background image
     (`compose.compose_scene`) — HeyGen has no native product placement — uploaded as a
     HeyGen asset;
  2. the subject: the library look the operator picked (`AVATAR_VIDEO`), a synthetic
     avatar generated from their description (`AvatarSource.AI`, a prompt avatar —
     created, then polled until ready; photoreal for `AVATAR_VIDEO`, animated for
     `ANIMATED_AVATAR_VIDEO`) or their uploaded image animated as-is
     (`AvatarSource.IMAGE`, HeyGen's image mode, animated kind only);
  3. the render, reading the copy's `script` with the chosen voice;
  4. the video DOWNLOADED into our store at once: HeyGen's `video_url` is a pre-signed
     link with an undocumented expiry, and a draft must never depend on it.

Every vendor call that costs money is written as a usage row with its provenance, also
when a later step fails. The store is a seam (`MediaStore`): local files next to the
uploads today (`LocalMediaStore`, served by the app), the tenant's R2 prefix later —
pending, see `docs/pendientes-generador-contenido.md` §1 (a generated POST is not
publishable by the Planificador until its media is in R2).

Every write carries its MIME type (`MediaWrite.content_type` → `image_assets.content_type`,
0029), which the Planificador requires: NULL means "not publishable".
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from qualify_creative.compose import (
    FlyerText,
    compose_scene,
    render_flyer,
)
from qualify_creative.enums import (
    AvatarSource,
    ContentKind,
    FailureReason,
    GenerationTask,
)
from qualify_creative.photo.normalize import to_meta_jpeg
from qualify_creative.providers import (
    CredentialResolver,
    GenerationRequest,
    PricingTable,
    RenderedPrompt,
)
from qualify_creative.render import (
    PostFacts,
    TemplateRegistry,
    build_props,
    suggest_recipes,
    validate_props,
)
from qualify_creative.render.adapter import MODEL_ID as REMOTION_MODEL
from qualify_creative.render.adapter import RemotionTemplateAdapter
from qualify_creative.render.client import RenderServiceError
from qualify_creative.render.manifest import TemplateManifest
from qualify_creative.render.props import ProductFacts
from qualify_creative.render.recipes import Engine
from qualify_creative.render.registry import TemplateNotFound
from qualify_creative.router import BudgetContext, CreativeRouter, HopAction
from qualify_creative.schemas import BrandKit, ContentBrief, CopyPayload

from .voice_access import VoiceGuard

logger = logging.getLogger(__name__)

HEYGEN = "heygen"
REMOTION = "remotion"
COMPOSE_MODEL = "qualify-compose-v1"
#: The MIME types this module stores, and that the publisher accepts.
JPEG = "image/jpeg"
MP4 = "video/mp4"
#: Render jobs are named deterministically from the draft and the recipe, so a retry of
#: the same draft re-uses the service's job (CONTRACT §4: `POST /render` is idempotent on
#: the id) instead of rendering twice.
TEMPLATE_JOB_NAMESPACE = UUID("6f1c2d3e-4a5b-4c6d-8e9f-0a1b2c3d4e5f")
PROMPT_AVATAR_MODEL = "heygen_prompt_avatar"
VIDEO_RESOLUTION = "1080p"

#: How an animated character is asked of HeyGen's prompt avatar: the operator describes
#: WHO; the style is what makes it "animated" rather than a photoreal person.
ANIMATED_STYLE = (
    "Personaje animado estilo 3D tipo película de animación, colores vivos, expresivo, "
    "de frente a cámara, plano medio, fondo liso. "
)
#: The same prompt avatar for a custom HUMAN presenter (`AVATAR_VIDEO`, source AI): a
#: synthetic photoreal person — nobody's likeness, so no consent question applies.
HUMAN_STYLE = (
    "Persona real fotorrealista, presentadora de video para redes sociales, expresión "
    "natural y cercana, de frente a cámara, plano medio, iluminación suave, fondo liso. "
)


# ---------------------------------------------------------------------------
# write shapes (mirrored by the repository)


@dataclass(frozen=True)
class MediaWrite:
    """One ``image_assets`` row: an image or a video of the draft, in order."""

    position: int
    media_type: str  # "image" | "video"
    media_url: str  # the store key the app serves
    object_key: str
    width: int | None
    height: int | None
    aspect_ratio: str | None
    model_id: str
    provider: str
    params: dict[str, Any] = field(default_factory=dict)
    #: Template kind: which output port of the run this is (`reel`, `feed`, `story`) and
    #: the run it came from — the provenance "template × metrics" needs (design D16).
    output_port: str | None = None
    template_run_id: UUID | None = None
    #: The MIME type the file was stored with (`image_assets.content_type`, 0029): what
    #: the Planificador checks before it lets a POST be published.
    content_type: str | None = None


@dataclass(frozen=True)
class TemplateRunWrite:
    """One ``template_runs`` row (migration 0038): the render job as Python saw it. Its
    ``id`` IS the render service's ``jobId``."""

    id: UUID
    template_id: str
    template_version: int
    engine: str
    status: str  # pending | generating | completed | failed | cancelled
    router_rule: str | None
    outputs: dict[str, Any]
    props: dict[str, Any]
    estimated_eta_sec: Decimal | None = None
    actual_sec: Decimal | None = None
    estimated_cost_usd: Decimal | None = None
    actual_cost_usd: Decimal | None = None
    failure_reason: str | None = None
    error_message: str | None = None
    prompt_id: str | None = None
    prompt_version: int | None = None


@dataclass(frozen=True)
class MediaUsage:
    """Cost provenance of one media call — converted to a ``UsageWrite`` by the service."""

    provider: str
    model_id: str
    unit: str  # "second" | "piece"
    quantity: int
    cost_usd: Decimal


@dataclass(frozen=True)
class MediaOutcome:
    media: tuple[MediaWrite, ...] = ()
    usage: tuple[MediaUsage, ...] = ()
    #: A `FailureReason` value when the artifact could not be produced.
    failure: str | None = None
    detail: str = ""
    #: Template kind: the run to persist (also when it failed — the attempt is the
    #: evidence) and the outputs that did NOT render while others did.
    template_run: TemplateRunWrite | None = None
    partial_failures: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def spent_usd(self) -> Decimal:
        return sum((u.cost_usd for u in self.usage), Decimal(0))


# ---------------------------------------------------------------------------
# the store


class MediaStore(Protocol):
    def read(self, key: str) -> bytes: ...

    def write(self, key: str, data: bytes) -> None: ...


class LocalMediaStore:
    """Files under one root — the app's upload directory, so the uploads the operator
    made (`uploads/<tenant>/…`) are readable and what is generated
    (`generated/<tenant>/<draft>/…`) is served by the same route."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError(f"media key escapes the store: {key!r}")
        return path

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class R2ReadingMediaStore:
    """`LocalMediaStore` plus the brand's R2 files (§ 2026-10-01): a key under a tenant's
    R2 prefix (`t/{tenant}/…` — the Brand Kit's logo, `brand_kit_store`) is read from R2
    through the tenant-checking `ObjectGate`; everything else stays local. Writes are
    always local (what the pipeline generates is served from the upload store)."""

    def __init__(self, local: MediaStore, gate: Any = None) -> None:
        self._local = local
        self._gate = gate

    def _r2(self) -> Any:
        if self._gate is None:
            from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
            from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
            from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

            self._gate = ObjectGate(R2ObjectStore(R2Settings.from_env()))
        return self._gate

    def read(self, key: str) -> bytes:
        if key.startswith("t/"):
            tenant = key.split("/", 2)[1]
            with self._r2().open_object(UUID(tenant), key) as stream:
                return stream.read()
        return self._local.read(key)

    def write(self, key: str, data: bytes) -> None:
        self._local.write(key, data)


#: HeyGen's failures, in the operator's words (from the smoke-test panel it replaces).
#: Matched on the error text the adapter / router carry; the raw text follows.
_HEYGEN_FAILURES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("insufficient_credit", "HTTP 402"),
        "HeyGen: la cuenta no tiene créditos de API. Recárgalos en HeyGen y vuelve a generar.",
    ),
    (
        ("HeyGenRenderTimeout",),
        "HeyGen sigue renderizando el video y tardó más de lo esperado. No se canceló: se va a"
        " terminar y cobrar — búscalo en tu cuenta de HeyGen.",
    ),
    (("HeyGenRenderFailed", "moderation_failed"), "HeyGen no pudo generar el video."),
    (("HTTP 401", "HTTP 403"), "HeyGen rechazó la llave de API (QUALIFY_HEYGEN_API_KEY)."),
    (("HTTP 429",), "HeyGen está limitando las solicitudes. Espera un momento y reintenta."),
    (("QUALIFY_HEYGEN_API_KEY", "no HeyGen key"), "Falta configurar QUALIFY_HEYGEN_API_KEY."),
    (("HeyGen is not configured",), "Los videos con avatar no están configurados (HeyGen)."),
)


def heygen_failure_text(raw: str) -> str:
    """What the operator reads when a video fails: the known cases in plain Spanish,
    followed by the vendor's own text for the support ticket."""
    for needles, text in _HEYGEN_FAILURES:
        if any(needle in raw for needle in needles):
            return f"{text} ({raw[:300]})"
    return f"No se pudo generar el video: {raw[:300]}"


def generated_key(tenant_id: UUID, draft_id: UUID, name: str) -> str:
    return f"generated/{tenant_id}/{draft_id}/{name}"


# ---------------------------------------------------------------------------
# the producer


class HeyGenTools(Protocol):
    """The HeyGen calls that are not a render (`HeyGenAvatarVideoAdapter` has them)."""

    def upload_asset(
        self,
        *,
        api_key: str,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        idempotency_key: str | None = None,
    ) -> Any: ...

    def create_prompt_avatar(
        self,
        *,
        api_key: str,
        name: str,
        prompt: str,
        aspect_ratio: str = ...,
        idempotency_key: str | None = None,
    ) -> str: ...

    def wait_for_look(self, look_id: str, *, api_key: str) -> Any: ...


Downloader = Callable[[str], bytes]


def _http_download(url: str) -> bytes:
    import httpx  # lazy: only the video kinds need it

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


class _MediaFailed(Exception):
    def __init__(
        self, failure: str, detail: str, *, template_run: TemplateRunWrite | None = None
    ) -> None:
        self.template_run = template_run
        super().__init__(detail)
        self.failure = failure
        self.detail = detail


class BrandNames(Protocol):
    def __call__(self, *, tenant_id: UUID, brand_id: UUID) -> str: ...


class ProductCatalog(Protocol):
    """What the catalog (migration 0038) knows about the products a brief names."""

    def products_for(
        self, *, tenant_id: UUID, brand_id: UUID, product_ref: str | None
    ) -> tuple[ProductFacts, ...]: ...


class MediaProducer:
    def __init__(
        self,
        *,
        store: MediaStore,
        router: CreativeRouter,
        credentials: CredentialResolver,
        pricing: PricingTable,
        heygen: HeyGenTools | None,
        download: Downloader = _http_download,
        voice_guard: VoiceGuard | None = None,
        remotion: RemotionTemplateAdapter | None = None,
        templates: TemplateRegistry | None = None,
        brand_names: BrandNames | None = None,
        catalog: ProductCatalog | None = None,
    ) -> None:
        self._store = store
        self._router = router
        self._credentials = credentials
        self._pricing = pricing
        self._heygen = heygen
        self._download = download
        #: Which voices a brand may render with (`voice_access`, § 2026-10-05). None
        #: = no check — only for tests with a fake HeyGen; `composition` always wires
        #: `BrandVoiceGuard`.
        self._voice_guard = voice_guard
        self._remotion = remotion
        self._templates = templates
        self._brand_names = brand_names
        self._catalog = catalog

    def produce(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        brief: ContentBrief,
        kit: BrandKit,
        copy: CopyPayload,
        budget: BudgetContext,
    ) -> MediaOutcome:
        """Never raises for a vendor or file problem: the outcome carries the failure,
        and the usage of whatever was already paid for."""
        usage: list[MediaUsage] = []
        try:
            if brief.kind is ContentKind.STATIC_FLYER:
                media = self._flyer(tenant_id, draft_id, brief, kit, copy)
            elif brief.kind.is_video:
                media = self._video(tenant_id, draft_id, brief, kit, copy, budget, usage)
            elif brief.kind is ContentKind.TEMPLATE:
                return self._template(tenant_id, draft_id, brief, kit, copy, budget, usage)
            else:
                media = ()
        except _MediaFailed as exc:
            logger.warning("creative media for draft %s failed: %s", draft_id, exc.detail)
            return MediaOutcome(
                usage=tuple(usage),
                failure=exc.failure,
                detail=exc.detail,
                template_run=exc.template_run,
            )
        except Exception as exc:  # a vendor error, a missing upload, a bad image file
            logger.warning("creative media for draft %s failed: %s", draft_id, exc)
            return MediaOutcome(
                usage=tuple(usage),
                failure=FailureReason.PROVIDER_ERROR.value,
                detail=heygen_failure_text(f"{type(exc).__name__}: {exc}"),
            )
        return MediaOutcome(media=tuple(media), usage=tuple(usage))

    # -- inputs ------------------------------------------------------------------------

    def _read(self, key: str | None) -> bytes | None:
        return self._store.read(key) if key else None

    def _products(self, brief: ContentBrief) -> list[bytes]:
        return [self._store.read(key) for key in brief.media.product_keys]

    def _logo(self, kit: BrandKit) -> bytes | None:
        if not kit.logo_asset_key:
            return None
        try:
            return self._store.read(kit.logo_asset_key)
        except Exception as exc:  # R2 down, a missing object: never a reason to fail the flyer
            logger.warning("brand logo %s unreadable: %s", kit.logo_asset_key, type(exc).__name__)
            return None

    # -- flyer -------------------------------------------------------------------------

    def _flyer(
        self, tenant_id: UUID, draft_id: UUID, brief: ContentBrief, kit: BrandKit, copy: CopyPayload
    ) -> list[MediaWrite]:
        slides = render_flyer(
            text=FlyerText(hook=copy.hook, cta=copy.cta),
            products=self._products(brief),
            background=self._read(brief.media.background_key),
            palette=kit.palette_rgb,
            logo=self._logo(kit),
            carousel=brief.media.carousel,
            size=brief.format.dimensions,
        )
        width, height = brief.format.dimensions
        out: list[MediaWrite] = []
        for position, png in enumerate(slides):
            # rendered as PNG, stored as JPEG: the only image format Meta takes
            key = generated_key(tenant_id, draft_id, f"slide-{position + 1}.jpg")
            self._store.write(key, to_meta_jpeg(png))
            out.append(
                MediaWrite(
                    position=position,
                    media_type="image",
                    media_url=key,
                    object_key=key,
                    width=width,
                    height=height,
                    aspect_ratio=brief.format.aspect_ratio,
                    model_id=COMPOSE_MODEL,
                    provider="local",
                    content_type=JPEG,
                    params={
                        "carousel": brief.media.carousel,
                        "slides": len(slides),
                        "products": len(brief.media.product_keys),
                        "background": bool(brief.media.background_key),
                    },
                )
            )
        return out

    # -- template (Remotion) -------------------------------------------------------------

    def _template(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        brief: ContentBrief,
        kit: BrandKit,
        copy: CopyPayload,
        budget: BudgetContext,
        usage: list[MediaUsage],
    ) -> MediaOutcome:
        """One run, several outputs (plan §2.2). The recipe router picks the template
        unless the operator pinned one; the props are validated against the manifest
        before the service is asked for anything; what rendered is kept even when a
        sibling output failed; the run row is written in every case — it is the evidence
        the cost and the "template × metrics" loop read."""
        if self._remotion is None or self._templates is None:
            raise _MediaFailed(
                FailureReason.PROVIDER_ERROR.value, "the render service is not configured"
            )
        products = (
            self._catalog.products_for(
                tenant_id=tenant_id, brand_id=brief.brand_id, product_ref=brief.product_ref
            )
            if self._catalog is not None
            else ()
        )
        manifest, rule = self._pick_template(brief, products, budget)
        props = build_props(
            manifest=manifest,
            brief=brief,
            copy=copy,
            kit=kit,
            brand_name=(
                self._brand_names(tenant_id=tenant_id, brand_id=brief.brand_id)
                if self._brand_names is not None
                else ""
            ),
            products=products,
            tenant_id=tenant_id,
            draft_id=draft_id,
        )
        job_id = _template_job_id(draft_id, manifest)
        eta = manifest.cost_model.eta_seconds(manifest.outputs, _expected_duration(manifest, props))
        per_render = self._pricing.unit_price(model_id=REMOTION_MODEL, unit="per_render")
        estimated_cost = per_render * manifest.render_count
        run = TemplateRunWrite(
            id=job_id,
            template_id=manifest.id,
            template_version=manifest.version,
            engine=Engine.REMOTION.value,
            status="pending",
            router_rule=str(rule) if rule is not None else None,
            outputs={
                port: {"kind": out.kind.value, "status": "pending"}
                for port, out in manifest.outputs.items()
            },
            props=props.to_payload(),
            estimated_eta_sec=Decimal(str(eta)),
            estimated_cost_usd=estimated_cost,
        )

        problems = validate_props(manifest, props)
        if problems:
            detail = "; ".join(p.message for p in problems)
            raise _MediaFailed(
                FailureReason.INVALID_PARAMETERS.value,
                detail,
                template_run=_finished(
                    run, "failed", FailureReason.INVALID_PARAMETERS.value, detail
                ),
            )
        if budget.hard_stop and estimated_cost > budget.remaining_usd:
            detail = f"template render would cost {estimated_cost} with {budget.remaining_usd} left"
            raise _MediaFailed(
                FailureReason.BUDGET_EXCEEDED.value,
                detail,
                template_run=_finished(run, "failed", FailureReason.BUDGET_EXCEEDED.value, detail),
            )

        request = GenerationRequest(
            task=GenerationTask.TEMPLATE_RENDER,
            rendered_prompt=RenderedPrompt("", "", ""),
            params={
                "job_id": str(job_id),
                "template_id": manifest.id,
                "version": manifest.version,
                "props": props,
                "render_count": manifest.render_count,
            },
        )
        try:
            result = self._remotion.generate(request, api_key="")
        except RenderServiceError as exc:
            reason = _reason_from_service(exc.code)
            raise _MediaFailed(
                reason, exc.message, template_run=_finished(run, "failed", reason, exc.message)
            ) from exc

        payload = result.payload
        assert isinstance(payload, dict)
        outputs: dict[str, dict[str, Any]] = payload["outputs"]
        failed: dict[str, dict[str, Any]] = dict(payload.get("failed_ports") or {})
        writes: list[MediaWrite] = []
        for position, (port, out) in enumerate(manifest.outputs.items()):
            rendered = outputs.get(port)
            if rendered is None:
                continue
            # a still comes back from the render service as PNG and is stored as JPEG
            # (Meta takes no other image format); the Reel is stored as rendered
            if out.media_type == "image":
                data, extension, content_type = to_meta_jpeg(rendered["bytes"]), "jpg", JPEG
            else:
                data, extension = rendered["bytes"], out.extension
                content_type = str(rendered.get("mime_type") or MP4)
            key = generated_key(tenant_id, draft_id, f"{port}.{extension}")
            self._store.write(key, data)
            params: dict[str, Any] = {
                "template_id": manifest.id,
                "template_version": manifest.version,
                "job_id": str(job_id),
                "port": port,
                "kind": out.kind.value,
                "router_rule": rule,
                "warnings": list(payload.get("warnings") or ()),
            }
            if rendered.get("duration_sec") is not None:
                params["duration_seconds"] = rendered["duration_sec"]
            writes.append(
                MediaWrite(
                    position=position,
                    media_type=out.media_type,
                    media_url=key,
                    object_key=key,
                    width=rendered.get("width") or out.width,
                    height=rendered.get("height") or out.height,
                    aspect_ratio=out.aspect_ratio,
                    model_id=REMOTION_MODEL,
                    provider=REMOTION,
                    params=params,
                    output_port=port,
                    template_run_id=job_id,
                    content_type=content_type,
                )
            )
        actual_cost = per_render * len(writes)
        usage.append(
            MediaUsage(
                provider=REMOTION,
                model_id=REMOTION_MODEL,
                unit="render",
                quantity=len(writes),
                cost_usd=actual_cost,
            )
        )
        run_outputs = {
            port: {
                "kind": out.kind.value,
                "status": "completed" if port in outputs else "failed",
                **({} if port in outputs else failed.get(port, {})),
            }
            for port, out in manifest.outputs.items()
        }
        finished = TemplateRunWrite(
            **{
                **run.__dict__,
                "status": str(payload.get("status") or "completed"),
                "outputs": run_outputs,
                "actual_sec": Decimal(str(payload.get("duration_sec") or 0)) or None,
                "actual_cost_usd": actual_cost,
                "failure_reason": (
                    next(iter(failed.values()))["failure_reason"] if failed and not writes else None
                ),
            }
        )
        detail = ""
        if failed:
            detail = "no se renderizó: " + ", ".join(
                f"{port} ({info.get('failure_reason')})" for port, info in failed.items()
            )
        return MediaOutcome(
            media=tuple(writes),
            usage=tuple(usage),
            template_run=finished,
            partial_failures=failed,
            detail=detail,
        )

    def _pick_template(
        self, brief: ContentBrief, products: tuple[ProductFacts, ...], budget: BudgetContext
    ) -> tuple[TemplateManifest, int | None]:
        """The operator's pinned recipe wins; otherwise the recipe router's suggestion.
        Returns the manifest and the rule that chose it (None when pinned)."""
        assert self._templates is not None
        media = brief.media
        if media.template_id:
            try:
                return self._templates.get(media.template_id, media.template_version), None
            except TemplateNotFound as exc:
                raise _MediaFailed(
                    FailureReason.INVALID_PARAMETERS.value, f"unknown template {exc}"
                ) from None
        video_count = 1 if brief.source_media_key and _is_video_key(brief.source_media_key) else 0
        video_count += sum(1 for p in products if p.video_keys)
        facts = PostFacts(
            angle=brief.content_type,
            photo_count=len({*media.product_keys, *(k for p in products for k in p.photo_keys)}),
            video_count=video_count,
            product_count=max(len(products), 1),
            cap_remaining_usd=budget.remaining_usd if budget.hard_stop else None,
        )
        options = suggest_recipes(facts, self._templates)
        chosen = next((o for o in options if o.suggested and o.engine is Engine.REMOTION), None)
        if chosen is None or chosen.template_id is None:
            remotion = options[0]
            raise _MediaFailed(
                FailureReason.ROUTE_BLOCKED_BY_POLICY.value,
                remotion.reason or "no published template serves this post",
            )
        return self._templates.get(chosen.template_id, chosen.template_version), chosen.rule

    # -- video -------------------------------------------------------------------------

    def _key(self, tenant_id: UUID, brand_id: UUID) -> str:
        try:
            resolved = self._credentials.resolve(
                tenant_id=tenant_id, brand_id=brand_id, provider=HEYGEN
            )
        except Exception as exc:  # the resolver's own error types are adapter-specific
            raise _MediaFailed(FailureReason.PROVIDER_ERROR.value, f"no HeyGen key: {exc}") from exc
        return resolved.api_key

    def _upload(self, key: str, data: bytes, name: str, idempotency: str) -> str:
        assert self._heygen is not None
        asset = self._heygen.upload_asset(
            api_key=key,
            file_bytes=data,
            filename=name,
            content_type="image/png" if name.endswith(".png") else "image/jpeg",
            idempotency_key=idempotency,
        )
        asset_id = asset.get("asset_id") if isinstance(asset, dict) else None
        if not asset_id:
            raise _MediaFailed(FailureReason.PROVIDER_ERROR.value, "HeyGen upload: no asset_id")
        return str(asset_id)

    def _video(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        brief: ContentBrief,
        kit: BrandKit,
        copy: CopyPayload,
        budget: BudgetContext,
        usage: list[MediaUsage],
    ) -> list[MediaWrite]:
        if self._heygen is None:
            raise _MediaFailed(FailureReason.PROVIDER_ERROR.value, "HeyGen is not configured")
        # The operator's own script wins: it is read word for word.
        script = (
            brief.media.own_script.strip()
            or copy.script
            or f"{copy.hook} {copy.caption} {copy.cta}"
        ).strip()
        # A retry of the same script re-uses HeyGen's render (24 h idempotency window);
        # a regenerated script is a new render.
        stamp = hashlib.sha256(f"{draft_id}:{script}".encode()).hexdigest()[:24]
        key = self._key(tenant_id, brief.brand_id)
        media = brief.media
        # § request 2026-10-05: the voice must be this brand's own clone or a public
        # one — every clone sits in the same HeyGen account, so without this check a
        # brand could render in another brand's cloned voice. Before any upload or
        # render, so a refusal costs nothing.
        if self._voice_guard is not None and not self._voice_guard(
            tenant_id=tenant_id,
            brand_id=brief.brand_id,
            voice_id=media.voice_id or "",
            api_key=key,
        ):
            raise _MediaFailed(
                FailureReason.ROUTE_BLOCKED_BY_POLICY.value,
                "La voz elegida no está disponible para esta marca: solo puedes usar "
                "tu propia voz clonada o una voz pública de HeyGen.",
            )

        params: dict[str, object] = {
            "script": script,
            "voice_id": media.voice_id,
            "resolution": VIDEO_RESOLUTION,
            "aspect_ratio": brief.format.aspect_ratio,
            "idempotency_key": stamp,
            "title": f"qualify {draft_id}",
        }
        if kit.regional_variant:
            params["locale"] = kit.regional_variant

        scene = compose_scene(
            products=self._products(brief),
            background=self._read(media.background_key),
            palette=kit.palette_rgb,
            size=brief.format.dimensions,
        )
        if scene is not None:
            params["background_image_asset_id"] = self._upload(
                key, scene, "scene.png", f"{stamp}-scene"
            )

        subject: dict[str, object]
        library_look = media.avatar_source is not AvatarSource.AI
        if brief.kind is ContentKind.AVATAR_VIDEO and library_look:
            subject = {"avatar_id": media.avatar_look_id, "engine": media.engine}
        elif media.avatar_source is AvatarSource.IMAGE:
            image = self._store.read(media.avatar_image_key or "")
            name = "avatar.png" if (media.avatar_image_key or "").endswith(".png") else "avatar.jpg"
            subject = {"image_asset_id": self._upload(key, image, name, f"{stamp}-avatar")}
        else:
            subject = {
                "avatar_id": self._prompt_avatar(key, brief, stamp, budget, usage),
                "engine": media.engine,
            }
        params.update(subject)

        request = GenerationRequest(
            task=GenerationTask.AVATAR_VIDEO,
            rendered_prompt=RenderedPrompt(
                stable_prefix="", volatile_suffix="", prefix_fingerprint=""
            ),
            params=params,
        )
        spent = sum((u.cost_usd for u in usage), Decimal(0))
        outcome = self._router.run(
            tenant_id=tenant_id,
            brand_id=brief.brand_id,
            chain=(HEYGEN,),
            request=request,
            budget=BudgetContext(
                remaining_usd=budget.remaining_usd - spent, hard_stop=budget.hard_stop
            ),
        )
        if outcome.result is None:
            blocked = any(h.action is HopAction.BUDGET_BLOCKED for h in outcome.hops)
            detail = "; ".join(h.reason or h.action.value for h in outcome.hops)
            raise _MediaFailed(
                FailureReason.BUDGET_EXCEEDED.value
                if blocked
                else FailureReason.PROVIDER_ERROR.value,
                heygen_failure_text(detail),
            )
        result = outcome.result
        payload = dict(result.payload) if isinstance(result.payload, dict) else {}
        seconds = result.usage.media_seconds
        rate = self._pricing.unit_price(
            model_id=result.model_id, unit=f"per_second_{VIDEO_RESOLUTION}"
        )
        usage.append(
            MediaUsage(
                provider=result.provider,
                model_id=result.model_id,
                unit="second",
                quantity=math.ceil(seconds),
                cost_usd=(seconds * rate).quantize(Decimal("0.000001")),
            )
        )

        video_key = generated_key(tenant_id, draft_id, "video.mp4")
        self._store.write(video_key, self._download(str(result.media_url)))
        extra: dict[str, Any] = {}
        thumbnail = payload.get("thumbnail_url")
        if thumbnail:
            try:
                thumb_key = generated_key(tenant_id, draft_id, "thumbnail.jpg")
                self._store.write(thumb_key, self._download(str(thumbnail)))
                extra["thumbnail_key"] = thumb_key
            except Exception as exc:  # a missing poster frame is not a failed video
                logger.info("heygen thumbnail not kept: %s", exc)
        return [
            MediaWrite(
                position=0,
                media_type="video",
                media_url=video_key,
                object_key=video_key,
                width=brief.format.dimensions[0],
                height=brief.format.dimensions[1],
                aspect_ratio=brief.format.aspect_ratio,
                model_id=result.model_id,
                provider=result.provider,
                content_type=MP4,
                params={
                    "video_id": payload.get("video_id"),
                    "duration_seconds": payload.get("duration_seconds"),
                    "subject": "avatar" if "avatar_id" in subject else "image",
                    "avatar_source": media.avatar_source.value if media.avatar_source else None,
                    "avatar_id": subject.get("avatar_id"),
                    "voice_id": media.voice_id,
                    "background_composed": scene is not None,
                    "model_revision": result.model_revision,
                    **extra,
                },
            )
        ]

    def _prompt_avatar(
        self,
        key: str,
        brief: ContentBrief,
        stamp: str,
        budget: BudgetContext,
        usage: list[MediaUsage],
    ) -> str:
        """A synthetic avatar from the operator's description — a photoreal person for
        `AVATAR_VIDEO`, an animated character otherwise: created, then waited for — its
        look id is the video's avatar."""
        assert self._heygen is not None
        price = self._pricing.unit_price(model_id=PROMPT_AVATAR_MODEL, unit="per_piece")
        if budget.hard_stop and price > budget.remaining_usd:
            raise _MediaFailed(FailureReason.BUDGET_EXCEEDED.value, "prompt avatar over budget")
        style = HUMAN_STYLE if brief.kind is ContentKind.AVATAR_VIDEO else ANIMATED_STYLE
        look_id = self._heygen.create_prompt_avatar(
            api_key=key,
            name=f"qualify-{stamp[:8]}",
            prompt=(style + brief.media.avatar_prompt.strip())[:1000],
            aspect_ratio=brief.format.aspect_ratio,
            idempotency_key=f"{stamp}-look",
        )
        usage.append(
            MediaUsage(
                provider=HEYGEN,
                model_id=PROMPT_AVATAR_MODEL,
                unit="piece",
                quantity=1,
                cost_usd=price,
            )
        )
        self._heygen.wait_for_look(look_id, api_key=key)
        return look_id


# ---------------------------------------------------------------------------
# template helpers


def _template_job_id(draft_id: UUID, manifest: TemplateManifest) -> UUID:
    from uuid import uuid5

    return uuid5(TEMPLATE_JOB_NAMESPACE, f"{draft_id}:{manifest.key}")


def _expected_duration(manifest: TemplateManifest, props: Any) -> float:
    """What the composition will most likely derive: ~2.5 s per photo plus a hook and a
    CTA scene, clamped to the manifest. Only an ETA — the service reports the real one."""
    photos = len(getattr(props, "photos", ()))
    guess = 2.5 * max(photos, 1) + 3.0
    return float(min(max(guess, manifest.duration.min_sec), manifest.duration.max_sec))


def _finished(
    run: TemplateRunWrite, status: str, failure_reason: str | None, message: str | None
) -> TemplateRunWrite:
    return TemplateRunWrite(
        **{
            **run.__dict__,
            "status": status,
            "failure_reason": failure_reason,
            "error_message": (message or "")[:500] or None,
        }
    )


def _reason_from_service(code: str) -> str:
    from qualify_creative.render.client import to_failure_reason

    try:
        return to_failure_reason(code).value
    except ValueError:
        return FailureReason.PROVIDER_ERROR.value


def _is_video_key(key: str) -> bool:
    return key.lower().rsplit(".", 1)[-1] in {"mp4", "mov", "m4v", "webm"}
