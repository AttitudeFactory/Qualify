"""The media half of a draft: turn a brief and its winning copy into the artifact the
brief's `ContentKind` asks for (§ request 2026-09-25).

- `CREATOR_SCRIPT` — nothing: the script IS the artifact, and it lives in the copy.
- `STATIC_FLYER` — `qualify_creative.compose.render_flyer` over the operator's own
  images: one PNG, or the carousel's slides. Local, deterministic, free.
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
uploads today (`LocalMediaStore`, served by the app), the tenant's R2 prefix later.
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
from qualify_creative.providers import (
    CredentialResolver,
    GenerationRequest,
    PricingTable,
    RenderedPrompt,
)
from qualify_creative.router import BudgetContext, CreativeRouter, HopAction
from qualify_creative.schemas import BrandKit, ContentBrief, CopyPayload

logger = logging.getLogger(__name__)

HEYGEN = "heygen"
COMPOSE_MODEL = "qualify-compose-v1"
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
    def __init__(self, failure: str, detail: str) -> None:
        super().__init__(detail)
        self.failure = failure
        self.detail = detail


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
    ) -> None:
        self._store = store
        self._router = router
        self._credentials = credentials
        self._pricing = pricing
        self._heygen = heygen
        self._download = download

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
            else:
                media = ()
        except _MediaFailed as exc:
            logger.warning("creative media for draft %s failed: %s", draft_id, exc.detail)
            return MediaOutcome(usage=tuple(usage), failure=exc.failure, detail=exc.detail)
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
        except (OSError, ValueError):
            return None  # a logo kept elsewhere is not a reason to fail the flyer

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
            key = generated_key(tenant_id, draft_id, f"slide-{position + 1}.png")
            self._store.write(key, png)
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
                    params={
                        "carousel": brief.media.carousel,
                        "slides": len(slides),
                        "products": len(brief.media.product_keys),
                        "background": bool(brief.media.background_key),
                    },
                )
            )
        return out

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
