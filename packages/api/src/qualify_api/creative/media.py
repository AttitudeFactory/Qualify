"""The media half of a draft: turn a brief and its winning copy into the artifact the
brief's `ContentKind` asks for (§ request 2026-09-25).

- `CREATOR_SCRIPT` — nothing: the script IS the artifact, and it lives in the copy.
- `STATIC_FLYER` — since 2026-10-07 Seedream (BytePlus ModelArk) generates the scene
  with the operator's product / background photos as references (one scene, or one per
  carousel slide), and `qualify_creative.compose.render_ad_slides` sets the hook, the
  CTA and the real logo on top. Without Seedream wired (`generated_ad_images=False`) it
  is the old local composition, `render_flyer`. Rendered as PNG and STORED AS JPEG
  (§ 2026-10-05): Meta accepts only JPEG images, and so does the publisher — every image
  this module writes goes through `to_meta_jpeg`.
- `AVATAR_VIDEO` / `ANIMATED_AVATAR_VIDEO` with `VideoEngine.SEEDANCE` (§ 2026-10-07):
  Seedream composes the presenter (described, or the operator's image), the products
  and the background into the video's first frame, and Seedance animates it. Seedance
  1.0 makes silent video; the 2.x models speak the script (a quoted line in the prompt).
- `AVATAR_VIDEO` / `ANIMATED_AVATAR_VIDEO` with `VideoEngine.HEYGEN` — HeyGen, through
  the `GenerationProvider` seam and the `CreativeRouter` (credential resolution + the
  budget pre-flight):
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
- `CAROUSEL` (§ request 2026-10-09): the operator's slides in order — a Seedream scene
  with the words chosen for it (`compose.render_carousel_slide`), that scene animated by
  Seedance and fitted to the feed with its words laid over every frame
  (`video.PyAvVideoFitter`), or a file of one of the BRAND's own pieces (checked against
  `pieces.PieceFiles` before it is read) fitted the same way; then, optionally, a
  closing slide with the CTA. Instagram publishes any mix of the two (QUA-103).

Every vendor call that costs money is written as a usage row with its provenance, also
when a later step fails. The store is a seam (`MediaStore`). Every generated file lives
in R2 only (§ 2026-10-06, `docs/pendientes-generador-contenido.md` §1), under the tenant's
prefix and unique per generation (`generated_object_key`): it is both
`image_assets.media_url` (what the app shows, through `/r2media`) and `object_key` (what
the Planificador publishes). A file R2 refuses fails the piece, saying so.

Every write carries its MIME type (`MediaWrite.content_type` → `image_assets.content_type`,
0029), which the Planificador requires: NULL means "not publishable".
"""

from __future__ import annotations

import hashlib
import io
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from qualify_creative.adapters.byteplus_ark import output_dimensions, video_cost_usd
from qualify_creative.compose import (
    FlyerText,
    compose_scene,
    render_ad_slides,
    render_carousel_slide,
    render_closing_slide,
    render_flyer,
    text_layer,
)
from qualify_creative.enums import (
    AdImageMode,
    AvatarSource,
    ContentFormat,
    ContentKind,
    FailureReason,
    GenerationTask,
    SlideSource,
    SlideText,
    VideoEngine,
)
from qualify_creative.photo.normalize import to_meta_jpeg, to_reference_jpeg
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
from qualify_creative.render.props import ProductFacts, PropsProblem, fit_text
from qualify_creative.render.recipes import Engine
from qualify_creative.render.registry import TemplateNotFound
from qualify_creative.router import BudgetContext, CreativeRouter, HopAction
from qualify_creative.schemas import SCRIPT_MAX, BrandKit, ContentBrief, CopyPayload
from qualify_creative.video import VideoFitter

from . import trace
from .pieces import PieceFile, PieceFiles
from .voice_access import VoiceGuard

logger = logging.getLogger(__name__)

HEYGEN = "heygen"
REMOTION = "remotion"
#: BytePlus ModelArk (§ 2026-10-07): one key, two router links.
SEEDREAM = "seedream"
SEEDANCE = "seedance"
#: The Seedance aspect ratio of each format: Seedance has no 4:5, so the feed post is
#: rendered 3:4 (the closest it takes — Instagram shows a 3:4 video inside a 4:5 slot).
SEEDANCE_RATIOS: dict[ContentFormat, str] = {
    ContentFormat.REELS_9_16: "9:16",
    ContentFormat.STORY_9_16: "9:16",
    ContentFormat.FEED_4_5: "3:4",
    ContentFormat.FEED_1_1: "1:1",
}
#: The size Seedream is asked for, per aspect ratio: inside BOTH pixel ranges of the
#: Seedream family (5.0 lite / 4.5 take >= 3,686,400 px; 5.0 pro / flash <= 4,624,220),
#: so switching the model never makes a size invalid. The flyer is then fitted to the
#: format's 1080-wide canvas, the video's first frame to its resolution.
SCENE_SIZES: dict[str, str] = {
    "4:5": "1728x2160",
    "1:1": "2048x2048",
    "9:16": "1440x2560",
    "3:4": "1728x2304",
}
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


#: Where a brand's files live: R2 (`t/` — the Brand Kit, generated pieces) and the local
#: store (`uploads/` — what the operator uploads, the catalog; `generated/` — pieces made
#: before 2026-10-06). Each is followed by the tenant id.
_TENANT_ROOTS = ("t", "uploads", "generated")
_FOREIGN_FILE = "Uno de los archivos de la pieza no es de tu marca."
_MISSING_PIECE = "La pieza de la diapositiva {n} ya no está disponible. Elige otra."


def owned_by(tenant_id: UUID, key: str) -> bool:
    """Whether `key` is one of this tenant's files — the check a read must pass before
    it happens (PR #100 review): a key in a brief can come from the browser, and a key
    another brand's id is in must never be read into this brand's piece."""
    if not key or ".." in key.split("/"):
        return False
    return any(key.startswith(f"{root}/{tenant_id}/") for root in _TENANT_ROOTS)


def _foreign_keys(tenant_id: UUID, brief: ContentBrief, kit: BrandKit) -> list[str]:
    """Every file the piece would read that is not this tenant's."""
    media = brief.media
    keys = [
        brief.source_media_key,
        media.background_key,
        *media.product_keys,
        media.avatar_image_key,
        media.brand_logo_key,
        *media.brand_element_keys,
        kit.logo_asset_key,
        *(slide.object_key for slide in media.slides),
    ]
    return [key for key in keys if key and not owned_by(tenant_id, key)]


class R2ReadingMediaStore:
    """`LocalMediaStore` plus R2 (§ 2026-10-01, 2026-10-06): a key under a tenant's R2
    prefix (`t/{tenant}/…` — the Brand Kit's files, a generated piece's durable copy) is
    read from R2 through the tenant-checking `ObjectGate`; everything else stays local
    (the operator's uploads). `keep` puts a generated file in R2 — its only copy."""

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
        # The tenant is taken from the key, so the gate's prefix check alone cannot tell
        # brands apart: `MediaProducer.produce` refuses any key that is not the caller's
        # (`owned_by`) before a single read, so here it IS the caller's tenant.
        if key.startswith("t/"):
            tenant = key.split("/", 2)[1]
            with self._r2().open_object(UUID(tenant), key) as stream:
                return stream.read()
        return self._local.read(key)

    def write(self, key: str, data: bytes) -> None:
        self._local.write(key, data)

    def keep(self, tenant_id: UUID, key: str, data: bytes, content_type: str) -> bool:
        """Put a generated file in R2 (`ObjectGate.put_media`: the tenant prefix is
        checked, the type is stored with the object). False — logged, never raised —
        when R2 is not configured or the write fails; the caller fails the piece."""
        try:
            self._r2().put_media(tenant_id, key, io.BytesIO(data), content_type)
        except Exception as exc:  # no R2 configured, R2 down: the draft is not lost
            logger.warning("generated media not kept in R2 (%s): %s", key, type(exc).__name__)
            return False
        return True


# -- what the operator reads when a piece fails ------------------------------------------
#
# Product rule (2026-10-08): the visible failure text (`content_drafts.failure_detail`,
# shown in the generator and in Borradores) names no vendor, model, env var or cost, and
# never carries the vendor's raw error — that goes to the log, where it is produced.

#: A key missing or refused, a model not activated, an account with no balance, a lane
#: not wired: nothing the operator can fix — the team has to.
UNAVAILABLE_TEXT = "La generación no está disponible ahora mismo. Avisa al equipo."
FILTERED_TEXT = "La pieza no pasó el filtro de contenido. Cambia la descripción o las fotos."
REAL_PERSON_TEXT = "No podemos usar fotos de personas reales como referencia. Usa otra foto."
SLOW_TEXT = "Está tardando más de lo normal. Revisa Borradores en un rato."
RATE_LIMITED_TEXT = "Hay muchas generaciones en curso. Inténtalo en unos minutos."
GENERIC_FAILURE_TEXT = "No se pudo generar la pieza. Inténtalo de nuevo."
BUDGET_TEXT = "Se alcanzó el límite de gasto de la marca."
NO_TEMPLATE_TEXT = "No hay una plantilla para esta pieza."

#: The avatar-video vendor's failures, by meaning. Matched on the error text the adapter /
#: router carry; the first match wins, so the content filter precedes the generic failure.
_HEYGEN_FAILURES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("insufficient_credit", "HTTP 402"), UNAVAILABLE_TEXT),
    (("HeyGenRenderTimeout",), SLOW_TEXT),
    (("moderation_failed",), FILTERED_TEXT),
    (("HTTP 401", "HTTP 403"), UNAVAILABLE_TEXT),
    (("HTTP 429",), RATE_LIMITED_TEXT),
    (("QUALIFY_HEYGEN_API_KEY", "no HeyGen key"), UNAVAILABLE_TEXT),
    (("HeyGen is not configured",), UNAVAILABLE_TEXT),
)


def heygen_failure_text(raw: str) -> str:
    """What the operator reads when an avatar video fails: the known cases by meaning,
    in plain Spanish, else the generic failure. `raw` (the vendor's own text) is never
    part of the result — the caller logs it."""
    for needles, text in _HEYGEN_FAILURES:
        if any(needle in raw for needle in needles):
            return text
    return GENERIC_FAILURE_TEXT


#: The generated image / video vendor's failures (error codes from its docs, read
#: 2026-10-07), by meaning. A moderated or failed generation is not billed.
_ARK_FAILURES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("QUALIFY_BYTEPLUS_ARK_API_KEY", "MissingPlatformKey"), UNAVAILABLE_TEXT),
    (("AuthenticationError", "HTTP 401"), UNAVAILABLE_TEXT),
    (("ModelNotOpen", "ServiceNotOpen", "InvalidEndpointOrModel"), UNAVAILABLE_TEXT),
    (("AccountOverdue", "ServiceOverdue", "InvalidAccountStatus"), UNAVAILABLE_TEXT),
    (("PrivacyInformation",), REAL_PERSON_TEXT),
    (("SensitiveContentDetected",), FILTERED_TEXT),
    (("ArkTaskTimeout",), SLOW_TEXT),
    (("RateLimit", "HTTP 429"), RATE_LIMITED_TEXT),
    (("provider not registered",), UNAVAILABLE_TEXT),
)


def ark_failure_text(raw: str) -> str:
    """What the operator reads when a generated image or video fails: the known cases
    by meaning, in plain Spanish, else the generic failure. `raw` (the vendor's own text)
    is never part of the result — the caller logs it."""
    for needles, text in _ARK_FAILURES:
        if any(needle in raw for needle in needles):
            return text
    return GENERIC_FAILURE_TEXT


#: What a template port is called in the operator's words.
_PORT_NAMES: dict[str, str] = {
    "hook": "gancho",
    "cta": "llamado a la acción",
    "price_line": "precio",
    "caption": "texto",
}


def _props_problem_text(problem: PropsProblem) -> str:
    """One `PropsProblem` in the operator's words (the manifest's English message is
    for the log and the run row)."""
    name = _PORT_NAMES.get(problem.port, "texto")
    if problem.code == "too_long":
        return f"El {name} es demasiado largo para la plantilla."
    if problem.code == "too_few" and problem.port == "photos":
        return "Faltan fotos para la plantilla."
    if problem.code == "too_many" and problem.port == "photos":
        return "Sobran fotos para la plantilla."
    if problem.code == "missing":
        if problem.port == "photos":
            return "Faltan fotos para la plantilla."
        return f"Falta {name} para la plantilla."
    return "La pieza no encaja en la plantilla."


def props_failure_text(problems: list[PropsProblem]) -> str:
    """The template validation problems in Spanish, distinct messages joined by a space."""
    texts = list(dict.fromkeys(_props_problem_text(p) for p in problems))
    return " ".join(texts)


def _data_url(image: bytes) -> str:
    """A reference image as the `data:` URL ModelArk takes (normalized, <=2048 px)."""
    import base64

    encoded = base64.b64encode(to_reference_jpeg(image)).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def generated_key(tenant_id: UUID, draft_id: UUID, name: str) -> str:
    """The local copy the app shows (overwritten by a regeneration: it shows the latest)."""
    return f"generated/{tenant_id}/{draft_id}/{name}"


def generated_object_key(tenant_id: UUID, draft_id: UUID, revision: int, name: str) -> str:
    """The durable R2 copy: under the tenant's prefix and UNIQUE per generation — an
    approved revision must never point at an object a later regeneration overwrites
    (QUA-111 coordination note of 2026-09-27, point 6)."""
    return f"t/{tenant_id}/generated/{draft_id}/r{revision}/{name}"


def template_port(manifest: TemplateManifest, fmt: ContentFormat) -> str | None:
    """The ONE output of `manifest` a brief of format `fmt` renders (§ request 2026-10-06:
    a template gives one piece, not the Reel + feed + story package). A Reel is the
    template's video output; any other format is the still of the same proportions.
    None when the template has no output of that format."""
    want_video = fmt is ContentFormat.REELS_9_16
    width, height = fmt.dimensions
    for port, out in manifest.outputs.items():
        is_video = out.media_type == "video"
        if is_video != want_video:
            continue
        if want_video or out.width * height == out.height * width:
            return port
    return None


# ---------------------------------------------------------------------------
# the producer


class _Saver:
    """Writes one generated file for a draft's generation and returns its key. With a
    store that has R2 (`R2ReadingMediaStore.keep`) the file goes ONLY to R2 — no local
    copy (§ request 2026-10-06: "no me sirve tenerlo en local") — under the tenant's
    prefix, unique per generation; if R2 refuses it the piece fails, saying so, rather
    than living somewhere nothing publishes from. A store without R2 (the tests' memory
    store, a dev `LocalMediaStore`) keeps the local key it always had."""

    def __init__(self, store: MediaStore, tenant_id: UUID, draft_id: UUID, revision: int):
        self._store = store
        self._tenant_id = tenant_id
        self._draft_id = draft_id
        self._revision = revision

    def __call__(self, name: str, data: bytes, content_type: str) -> str:
        keep = getattr(self._store, "keep", None)
        if keep is None:
            local = generated_key(self._tenant_id, self._draft_id, name)
            self._store.write(local, data)
            return local
        key = generated_object_key(self._tenant_id, self._draft_id, self._revision, name)
        if not keep(self._tenant_id, key, data, content_type):
            raise _MediaFailed(
                FailureReason.PROVIDER_ERROR.value,
                "No pudimos guardar la pieza en R2. Inténtalo de nuevo en un momento.",
            )
        return key


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


#: The largest vendor file we take (PR #100 review): a 30 s 1080p clip is ~20-40 MB.
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_DOWNLOAD_REDIRECTS = 3


class DownloadRefused(ValueError):
    """A vendor result URL that is not https, or a file over `MAX_DOWNLOAD_BYTES`."""


def _http_download(url: str) -> bytes:
    """The vendor's result file, fetched with guard rails (PR #100 review): the URL — and
    every redirect it takes — must be https, the redirects are few, and the body is read
    in chunks up to `MAX_DOWNLOAD_BYTES` instead of trusting its `Content-Length`."""
    import httpx  # lazy: only the video kinds need it

    def https_only(request: httpx.Request) -> None:
        if request.url.scheme != "https":
            raise DownloadRefused(f"vendor media URL is not https: {request.url.scheme}")

    if httpx.URL(url).scheme != "https":
        raise DownloadRefused("vendor media URL is not https")
    with httpx.Client(
        timeout=120.0,
        follow_redirects=True,
        max_redirects=MAX_DOWNLOAD_REDIRECTS,
        event_hooks={"request": [https_only]},
    ) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            buffer = bytearray()
            for chunk in response.iter_bytes():
                buffer.extend(chunk)
                if len(buffer) > MAX_DOWNLOAD_BYTES:
                    raise DownloadRefused(f"vendor media is over {MAX_DOWNLOAD_BYTES} bytes")
            return bytes(buffer)


class _MediaFailed(Exception):
    """`detail` is what the operator reads; `raw` (the vendor's / service's own text,
    when there is one) only reaches the log."""

    def __init__(
        self,
        failure: str,
        detail: str,
        *,
        template_run: TemplateRunWrite | None = None,
        raw: str | None = None,
    ) -> None:
        self.template_run = template_run
        super().__init__(detail)
        self.failure = failure
        self.detail = detail
        self.raw = raw


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
        generated_ad_images: bool = False,
        seedance_resolution: str = "720p",
        pieces: PieceFiles | None = None,
        fitter: VideoFitter | None = None,
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
        #: The advertising image's scene is generated by Seedream (§ 2026-10-07); off,
        #: it is the local composition it was before (the tests' default).
        self._generated_ad_images = generated_ad_images
        #: Seedance's output resolution (`QUALIFY_SEEDANCE_RESOLUTION`).
        self._seedance_resolution = seedance_resolution
        #: The carousel (§ 2026-10-09): which files are this brand's pieces, and the
        #: fitting of a video slide to the feed. None = a carousel takes neither an
        #: existing piece nor a video slide.
        self._pieces = pieces
        self._fitter = fitter

    def produce(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        brief: ContentBrief,
        kit: BrandKit,
        copy: CopyPayload,
        budget: BudgetContext,
        revision: int = 1,
    ) -> MediaOutcome:
        """Never raises for a vendor or file problem: the outcome carries the failure,
        and the usage of whatever was already paid for. `revision` is the draft's — what
        keeps each generation's R2 copy apart."""
        usage: list[MediaUsage] = []
        foreign = _foreign_keys(tenant_id, brief, kit)
        if foreign:
            # before any read, spend or vendor call — a key from another brand
            logger.warning(
                "creative media for draft %s refused: keys not of tenant %s: %s",
                draft_id,
                tenant_id,
                foreign,
            )
            return MediaOutcome(
                failure=FailureReason.ROUTE_BLOCKED_BY_POLICY.value, detail=_FOREIGN_FILE
            )
        save = _Saver(self._store, tenant_id, draft_id, revision)
        try:
            if brief.kind is ContentKind.STATIC_FLYER and self._generated_ad_images:
                media = self._ad_image(tenant_id, draft_id, brief, kit, copy, budget, usage, save)
            elif brief.kind is ContentKind.STATIC_FLYER:
                media = self._flyer(save, brief, kit, copy)
            elif brief.kind.is_video and brief.media.video_engine is VideoEngine.SEEDANCE:
                media = self._seedance_video(
                    tenant_id, draft_id, brief, kit, copy, budget, usage, save
                )
            elif brief.kind.is_video:
                media = self._video(tenant_id, draft_id, brief, kit, copy, budget, usage, save)
            elif brief.kind is ContentKind.TEMPLATE:
                return self._template(tenant_id, draft_id, brief, kit, copy, budget, usage, save)
            elif brief.kind is ContentKind.CAROUSEL:
                media = self._carousel(tenant_id, draft_id, brief, kit, copy, budget, usage, save)
            else:
                media = ()
        except _MediaFailed as exc:
            logger.warning(
                "creative media for draft %s failed: %s", draft_id, exc.raw or exc.detail
            )
            return MediaOutcome(
                usage=tuple(usage),
                failure=exc.failure,
                detail=exc.detail,
                template_run=exc.template_run,
            )
        except Exception as exc:  # a vendor error, a missing upload, a bad image file
            logger.warning("creative media for draft %s failed: %s", draft_id, exc)
            raw = f"{type(exc).__name__}: {exc}"
            on_ark = (
                (brief.kind is ContentKind.STATIC_FLYER and self._generated_ad_images)
                or (brief.kind.is_video and brief.media.video_engine is VideoEngine.SEEDANCE)
                or brief.kind is ContentKind.CAROUSEL
            )
            return MediaOutcome(
                usage=tuple(usage),
                failure=FailureReason.PROVIDER_ERROR.value,
                detail=ark_failure_text(raw) if on_ark else heygen_failure_text(raw),
            )
        return MediaOutcome(media=tuple(media), usage=tuple(usage))

    # -- inputs ------------------------------------------------------------------------

    def _read(self, key: str | None) -> bytes | None:
        return self._store.read(key) if key else None

    def _products(self, brief: ContentBrief) -> list[bytes]:
        return [self._store.read(key) for key in brief.media.product_keys]

    def _logo(self, kit: BrandKit, key: str | None = None) -> bytes | None:
        key = key or kit.logo_asset_key
        if not key:
            return None
        try:
            return self._store.read(key)
        except Exception as exc:  # R2 down, a missing object: never a reason to fail the flyer
            logger.warning("brand logo %s unreadable: %s", key, type(exc).__name__)
            return None

    # -- flyer -------------------------------------------------------------------------

    def _flyer(
        self, save: _Saver, brief: ContentBrief, kit: BrandKit, copy: CopyPayload
    ) -> list[MediaWrite]:
        slides = render_flyer(
            text=FlyerText(hook=copy.hook, cta=copy.cta),
            products=self._products(brief),
            background=self._read(brief.media.background_key),
            palette=kit.palette_rgb,
            # the logo the piece was given (§ 2026-10-06), else the kit's main one
            logo=self._logo(kit, brief.media.brand_logo_key),
            carousel=brief.media.carousel,
            size=brief.format.dimensions,
        )
        width, height = brief.format.dimensions
        out: list[MediaWrite] = []
        for position, png in enumerate(slides):
            # rendered as PNG, stored as JPEG: the only image format Meta takes
            key = save(f"slide-{position + 1}.jpg", to_meta_jpeg(png), JPEG)
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

    # -- generated images and video (BytePlus ModelArk, § 2026-10-07) --------------------

    def _brand_name(self, tenant_id: UUID, brand_id: UUID) -> str:
        if self._brand_names is None:
            return ""
        try:
            return self._brand_names(tenant_id=tenant_id, brand_id=brand_id)
        except Exception as exc:  # a name is decoration: never a reason to fail the piece
            logger.info("brand name unreadable: %s", type(exc).__name__)
            return ""

    def _remaining(self, budget: BudgetContext, usage: list[MediaUsage]) -> BudgetContext:
        spent = sum((u.cost_usd for u in usage), Decimal(0))
        return BudgetContext(remaining_usd=budget.remaining_usd - spent, hard_stop=budget.hard_stop)

    def _run(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        link: str,
        request: GenerationRequest,
        budget: BudgetContext,
        usage: list[MediaUsage],
    ) -> Any:
        """One ModelArk call through the router (key + budget pre-flight); the failure
        in the operator's words."""
        outcome = self._router.run(
            tenant_id=tenant_id,
            brand_id=brand_id,
            chain=(link,),
            request=request,
            budget=self._remaining(budget, usage),
        )
        if outcome.result is None:
            blocked = any(h.action is HopAction.BUDGET_BLOCKED for h in outcome.hops)
            detail = "; ".join(h.reason or h.action.value for h in outcome.hops)
            raise _MediaFailed(
                FailureReason.BUDGET_EXCEEDED.value
                if blocked
                else FailureReason.PROVIDER_ERROR.value,
                BUDGET_TEXT if blocked else ark_failure_text(detail),
                raw=detail,
            )
        return outcome.result

    def _scene_image(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        brand_id: UUID,
        prompt: str,
        references: list[bytes],
        ratio: str,
        budget: BudgetContext,
        usage: list[MediaUsage],
        what: str,
    ) -> bytes:
        """One Seedream image (the ad's scene, or a video's first frame), its cost
        recorded the moment it is paid for."""
        request = GenerationRequest(
            task=GenerationTask.PRODUCT_IMAGE,
            rendered_prompt=RenderedPrompt("", "", ""),
            params={
                "prompt": prompt,
                "images": [_data_url(image) for image in references],
                "size": SCENE_SIZES[ratio],
            },
        )
        trace.media_request(
            draft_id=draft_id,
            provider="Seedream",
            what=what,
            fields={
                "prompt": prompt,
                "imágenes de referencia": len(references),
                "tamaño": SCENE_SIZES[ratio],
            },
        )
        result = self._run(
            tenant_id=tenant_id,
            brand_id=brand_id,
            link=SEEDREAM,
            request=request,
            budget=budget,
            usage=usage,
        )
        pieces = max(result.usage.pieces, 1)
        price = self._pricing.unit_price(model_id=result.model_id, unit="per_piece")
        usage.append(
            MediaUsage(
                provider=result.provider,
                model_id=result.model_id,
                unit="piece",
                quantity=pieces,
                cost_usd=price * pieces,
            )
        )
        payload = result.payload if isinstance(result.payload, dict) else {}
        images = payload.get("images") or ()
        if not images:
            raise _MediaFailed(
                FailureReason.PROVIDER_ERROR.value,
                "No se pudo generar la imagen. Inténtalo de nuevo.",
                raw=f"{result.model_id} returned no image",
            )
        return bytes(images[0])

    def _ad_image(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        brief: ContentBrief,
        kit: BrandKit,
        copy: CopyPayload,
        budget: BudgetContext,
        usage: list[MediaUsage],
        save: _Saver,
    ) -> list[MediaWrite]:
        """The advertising image: Seedream generates the photograph with the operator's
        own product and/or background as references (one per carousel slide), and the
        words and the real logo are set on top locally."""
        media = brief.media
        mode = media.ad_mode or (
            AdImageMode.BOTH
            if media.product_keys and media.background_key
            else AdImageMode.BACKGROUND
            if media.background_key
            else AdImageMode.PRODUCT
        )
        products = self._products(brief) if mode.needs_product else []
        background = self._read(media.background_key) if mode.needs_background else None
        ratio = brief.format.aspect_ratio
        brand = self._brand_name(tenant_id, brief.brand_id)
        # one scene with every product, or — a carousel — one scene per product
        groups = [[p] for p in products[:9]] if media.carousel and products else [products]
        scenes: list[bytes] = []
        for index, group in enumerate(groups):
            prompt = ad_scene_prompt(
                brief=brief,
                kit=kit,
                brand=brand,
                mode=mode,
                products=len(group),
                has_background=background is not None,
            )
            references = [*group, *([background] if background is not None else [])]
            scenes.append(
                self._scene_image(
                    tenant_id=tenant_id,
                    draft_id=draft_id,
                    brand_id=brief.brand_id,
                    prompt=prompt,
                    references=references,
                    ratio=ratio,
                    budget=budget,
                    usage=usage,
                    what=f"escena de la imagen publicitaria {index + 1}/{len(groups)}",
                )
            )
        slides = render_ad_slides(
            scenes=scenes,
            text=FlyerText(hook=copy.hook, cta=copy.cta),
            palette=kit.palette_rgb,
            logo=self._logo(kit, media.brand_logo_key),
            carousel=media.carousel,
            size=brief.format.dimensions,
        )
        width, height = brief.format.dimensions
        model_id = usage[-1].model_id if usage else SEEDREAM
        out: list[MediaWrite] = []
        for position, png in enumerate(slides):
            key = save(f"slide-{position + 1}.jpg", to_meta_jpeg(png), JPEG)
            out.append(
                MediaWrite(
                    position=position,
                    media_type="image",
                    media_url=key,
                    object_key=key,
                    width=width,
                    height=height,
                    aspect_ratio=brief.format.aspect_ratio,
                    model_id=model_id,
                    provider=SEEDREAM,
                    content_type=JPEG,
                    params={
                        "ad_mode": mode.value,
                        "scene_prompt": media.scene_prompt,
                        "carousel": media.carousel,
                        "slides": len(slides),
                        "generated_scenes": len(scenes),
                        "products": len(products),
                        "background": background is not None,
                    },
                )
            )
        return out

    def _seedance_video(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        brief: ContentBrief,
        kit: BrandKit,
        copy: CopyPayload,
        budget: BudgetContext,
        usage: list[MediaUsage],
        save: _Saver,
    ) -> list[MediaWrite]:
        """Seedream composes the presenter, the products and the background into the
        first frame; Seedance animates it. The script rides along: Seedance 1.0 is silent
        (the script stays in the post's copy), the 2.x models speak it."""
        media = brief.media
        script = (
            media.own_script.strip() or copy.script or f"{copy.hook} {copy.caption} {copy.cta}"
        ).strip()
        if len(script) > SCRIPT_MAX:
            # a generated script has no stored cap (founder, 2026-10-06); the line Seedance
            # speaks is bounded like `own_script`, so motion prompt + line stay well under
            # the vendor's `MAX_PROMPT_CHARS` (PR #100 review)
            script = fit_text(script, SCRIPT_MAX)
        ratio = SEEDANCE_RATIOS[brief.format]
        products = self._products(brief)
        background = self._read(media.background_key)
        character = (
            self._store.read(media.avatar_image_key)
            if media.avatar_source is AvatarSource.IMAGE and media.avatar_image_key
            else None
        )
        references = [
            *([character] if character is not None else []),
            *products,
            *([background] if background is not None else []),
        ]
        frame = self._scene_image(
            tenant_id=tenant_id,
            draft_id=draft_id,
            brand_id=brief.brand_id,
            prompt=first_frame_prompt(
                brief=brief,
                kit=kit,
                has_character_image=character is not None,
                products=len(products),
                has_background=background is not None,
            ),
            references=references,
            ratio=ratio,
            budget=budget,
            usage=usage,
            what="primer fotograma del video",
        )
        frame_key = save("first-frame.jpg", to_meta_jpeg(frame), JPEG)

        motion = motion_prompt(brief=brief, products=len(products))
        request = GenerationRequest(
            task=GenerationTask.SCENE_VIDEO,
            rendered_prompt=RenderedPrompt("", "", ""),
            params={
                "prompt": motion,
                "first_frame": _data_url(frame),
                "ratio": ratio,
                "resolution": self._seedance_resolution,
                "duration_seconds": media.duration_seconds,
                "dialogue": script,
            },
        )
        trace.media_request(
            draft_id=draft_id,
            provider="Seedance",
            what="video desde el primer fotograma",
            fields={
                "prompt de movimiento": motion,
                "guion (solo lo dicen los modelos 2.x)": script,
                "formato": f"{ratio} · {self._seedance_resolution}",
                "duración pedida": f"{media.duration_seconds} s",
            },
        )
        result = self._run(
            tenant_id=tenant_id,
            brand_id=brief.brand_id,
            link=SEEDANCE,
            request=request,
            budget=budget,
            usage=usage,
        )
        payload = dict(result.payload) if isinstance(result.payload, dict) else {}
        resolution = str(payload.get("resolution") or self._seedance_resolution)
        tokens = int(result.usage.output_tokens)
        usage.append(
            MediaUsage(
                provider=result.provider,
                model_id=result.model_id,
                unit="second",
                quantity=math.ceil(result.usage.media_seconds),
                cost_usd=video_cost_usd(self._pricing, result.model_id, resolution, tokens),
            )
        )
        video_key = save("video.mp4", self._download(str(result.media_url)), MP4)
        width, height = output_dimensions(result.model_id, resolution, ratio)
        return [
            MediaWrite(
                position=0,
                media_type="video",
                media_url=video_key,
                object_key=video_key,
                width=width,
                height=height,
                aspect_ratio=ratio,
                model_id=result.model_id,
                provider=result.provider,
                content_type=MP4,
                params={
                    "task_id": payload.get("task_id"),
                    "duration_seconds": payload.get("duration_seconds"),
                    "resolution": resolution,
                    "tokens": tokens,
                    "spoken": bool(payload.get("generate_audio")),
                    "avatar_source": media.avatar_source.value if media.avatar_source else None,
                    "thumbnail_key": frame_key,
                    "model_revision": result.model_revision,
                },
            )
        ]

    # -- carousel (§ request 2026-10-09) -------------------------------------------------

    def _carousel(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        brief: ContentBrief,
        kit: BrandKit,
        copy: CopyPayload,
        budget: BudgetContext,
        usage: list[MediaUsage],
        save: _Saver,
    ) -> list[MediaWrite]:
        """The operator's slides in order, then the closing slide when asked for. Every
        slide is fitted to the format's exact size: Instagram crops a carousel to its
        first item, and a reused Reel or a Seedance 3:4 would otherwise be cut there."""
        media = brief.media
        size = brief.format.dimensions
        total = len(media.slides) + int(media.closing_slide)
        products = self._products(brief)
        background = self._read(media.background_key)
        logo = self._logo(kit, media.brand_logo_key)
        brand = self._brand_name(tenant_id, brief.brand_id)
        # every reused piece is resolved BEFORE the first paid call (PR #100 review): a
        # piece gone from slide 4 must not cost slides 1-3 first
        pieces = self._existing_pieces(tenant_id, brief)
        out: list[MediaWrite] = []
        for position, slide in enumerate(media.slides):
            number = position + 1
            if slide.source is SlideSource.EXISTING:
                out.append(self._existing_slide(brief, pieces[position], position, save))
                continue
            hook = copy.hook if slide.text is SlideText.HOOK else ""
            cta = copy.cta if slide.text is SlideText.CTA else ""
            product = products[slide.product_index] if slide.product_index is not None else None
            place = background if slide.use_background else None
            animated = slide.source is SlideSource.ANIMATED
            # a video's first frame is drawn at the ratio Seedance renders (it has no 4:5)
            ratio = SEEDANCE_RATIOS[brief.format] if animated else brief.format.aspect_ratio
            scene = self._scene_image(
                tenant_id=tenant_id,
                draft_id=draft_id,
                brand_id=brief.brand_id,
                prompt=carousel_scene_prompt(
                    brief=brief,
                    kit=kit,
                    brand=brand,
                    scene=slide.scene_prompt,
                    ratio=ratio,
                    has_product=product is not None,
                    has_background=place is not None,
                    has_text=bool(hook or cta),
                ),
                references=[image for image in (product, place) if image is not None],
                ratio=ratio,
                budget=budget,
                usage=usage,
                what=f"escena de la diapositiva {number}/{total}",
            )
            still = render_carousel_slide(
                scene=scene, hook=hook, cta=cta, palette=kit.palette_rgb, logo=logo, size=size
            )
            params: dict[str, Any] = {
                "slide": number,
                "slides": total,
                "source": slide.source.value,
                "text": slide.text.value,
                "scene_prompt": slide.scene_prompt,
            }
            if not animated:
                key = save(f"slide-{number}.jpg", to_meta_jpeg(still), JPEG)
                out.append(
                    MediaWrite(
                        position=position,
                        media_type="image",
                        media_url=key,
                        object_key=key,
                        width=size[0],
                        height=size[1],
                        aspect_ratio=brief.format.aspect_ratio,
                        model_id=usage[-1].model_id,
                        provider=SEEDREAM,
                        content_type=JPEG,
                        params=params,
                    )
                )
                continue
            overlay = (
                text_layer(size=size, hook=hook, cta=cta, palette=kit.palette_rgb, logo=logo)
                if hook or cta
                else None
            )
            out.append(
                self._animated_slide(
                    tenant_id=tenant_id,
                    draft_id=draft_id,
                    brief=brief,
                    scene=scene,
                    still=still,
                    overlay=overlay,
                    seconds=slide.seconds,
                    position=position,
                    total=total,
                    params=params,
                    budget=budget,
                    usage=usage,
                    save=save,
                )
            )
        if media.closing_slide:
            closing = render_closing_slide(
                line=copy.cta or copy.hook, palette=kit.palette_rgb, logo=logo, size=size
            )
            key = save(f"slide-{total}.jpg", to_meta_jpeg(closing), JPEG)
            out.append(
                MediaWrite(
                    position=total - 1,
                    media_type="image",
                    media_url=key,
                    object_key=key,
                    width=size[0],
                    height=size[1],
                    aspect_ratio=brief.format.aspect_ratio,
                    model_id=COMPOSE_MODEL,
                    provider="qualify",
                    content_type=JPEG,
                    params={"slide": total, "slides": total, "source": "closing"},
                )
            )
        return out

    def _require_fitter(self) -> VideoFitter:
        if self._fitter is None:
            raise _MediaFailed(
                FailureReason.PROVIDER_ERROR.value,
                UNAVAILABLE_TEXT,
                raw="carousel video slide without a VideoFitter wired",
            )
        return self._fitter

    def _animated_slide(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        brief: ContentBrief,
        scene: bytes,
        still: bytes,
        overlay: bytes | None,
        seconds: int,
        position: int,
        total: int,
        params: dict[str, Any],
        budget: BudgetContext,
        usage: list[MediaUsage],
        save: _Saver,
    ) -> MediaWrite:
        """Seedance animates the slide's scene (silent, nobody talking), then the clip is
        fitted to the feed with the slide's words over every frame."""
        fitter = self._require_fitter()
        number = position + 1
        ratio = SEEDANCE_RATIOS[brief.format]
        motion = carousel_motion_prompt()
        request = GenerationRequest(
            task=GenerationTask.SCENE_VIDEO,
            rendered_prompt=RenderedPrompt("", "", ""),
            params={
                "prompt": motion,
                "first_frame": _data_url(scene),
                "ratio": ratio,
                "resolution": self._seedance_resolution,
                "duration_seconds": seconds,
                "generate_audio": False,
            },
        )
        trace.media_request(
            draft_id=draft_id,
            provider="Seedance",
            what=f"video de la diapositiva {number}/{total}",
            fields={
                "prompt de movimiento": motion,
                "formato": f"{ratio} · {self._seedance_resolution}",
                "duración pedida": f"{seconds} s",
                "texto encima": "sí" if overlay else "no",
            },
        )
        result = self._run(
            tenant_id=tenant_id,
            brand_id=brief.brand_id,
            link=SEEDANCE,
            request=request,
            budget=budget,
            usage=usage,
        )
        payload = dict(result.payload) if isinstance(result.payload, dict) else {}
        resolution = str(payload.get("resolution") or self._seedance_resolution)
        tokens = int(result.usage.output_tokens)
        usage.append(
            MediaUsage(
                provider=result.provider,
                model_id=result.model_id,
                unit="second",
                quantity=math.ceil(result.usage.media_seconds),
                cost_usd=video_cost_usd(self._pricing, result.model_id, resolution, tokens),
            )
        )
        fitted = fitter.fit(
            self._download(str(result.media_url)), size=brief.format.dimensions, overlay=overlay
        )
        video_key = save(f"slide-{number}.mp4", fitted.data, MP4)
        poster_key = save(f"slide-{number}-poster.jpg", to_meta_jpeg(fitted.poster or still), JPEG)
        return MediaWrite(
            position=position,
            media_type="video",
            media_url=video_key,
            object_key=video_key,
            width=fitted.width,
            height=fitted.height,
            aspect_ratio=brief.format.aspect_ratio,
            model_id=result.model_id,
            provider=result.provider,
            content_type=MP4,
            params={
                **params,
                "task_id": payload.get("task_id"),
                "duration_seconds": round(fitted.duration_sec, 2),
                "resolution": resolution,
                "tokens": tokens,
                "thumbnail_key": poster_key,
                "model_revision": result.model_revision,
            },
        )

    def _existing_pieces(self, tenant_id: UUID, brief: ContentBrief) -> dict[int, PieceFile]:
        """The piece behind every `EXISTING` slide, by slide position — all of them
        resolved up front, so a missing or foreign one fails the carousel before any
        provider is paid. Refused unless it IS one of this brand's pieces (a regenerated
        source draft, 0048, no longer has its old files)."""
        found: dict[int, PieceFile] = {}
        for position, slide in enumerate(brief.media.slides):
            if slide.source is not SlideSource.EXISTING:
                continue
            number = position + 1
            piece = (
                self._pieces.file(
                    tenant_id=tenant_id, brand_id=brief.brand_id, object_key=slide.object_key
                )
                if self._pieces is not None and slide.object_key
                else None
            )
            if piece is None:
                logger.warning(
                    "carousel slide %s refused: %s is not a piece of brand %s",
                    number,
                    slide.object_key,
                    brief.brand_id,
                )
                raise _MediaFailed(
                    FailureReason.ROUTE_BLOCKED_BY_POLICY.value, _MISSING_PIECE.format(n=number)
                )
            found[position] = piece
        return found

    def _existing_slide(
        self, brief: ContentBrief, piece: PieceFile, position: int, save: _Saver
    ) -> MediaWrite:
        """A file of one of the brand's own pieces, copied into this draft (its own R2
        object: regenerating the source never breaks the carousel) and fitted to the
        format."""
        number = position + 1
        size = brief.format.dimensions
        data = self._store.read(piece.object_key)
        params: dict[str, Any] = {
            "slide": number,
            "source": SlideSource.EXISTING.value,
            "from_draft": str(piece.draft_id),
            "from_key": piece.object_key,
        }
        if piece.media_type == "video":
            fitted = self._require_fitter().fit(data, size=size)
            key = save(f"slide-{number}.mp4", fitted.data, MP4)
            if fitted.poster:
                params["thumbnail_key"] = save(
                    f"slide-{number}-poster.jpg", to_meta_jpeg(fitted.poster), JPEG
                )
            params["duration_seconds"] = round(fitted.duration_sec, 2)
            return MediaWrite(
                position=position,
                media_type="video",
                media_url=key,
                object_key=key,
                width=fitted.width,
                height=fitted.height,
                aspect_ratio=brief.format.aspect_ratio,
                model_id=COMPOSE_MODEL,
                provider="qualify",
                content_type=MP4,
                params=params,
            )
        key = save(f"slide-{number}.jpg", to_meta_jpeg(_cover_png(data, size)), JPEG)
        return MediaWrite(
            position=position,
            media_type="image",
            media_url=key,
            object_key=key,
            width=size[0],
            height=size[1],
            aspect_ratio=brief.format.aspect_ratio,
            model_id=COMPOSE_MODEL,
            provider="qualify",
            content_type=JPEG,
            params=params,
        )

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
        save: _Saver,
    ) -> MediaOutcome:
        """One run, several outputs (plan §2.2). The recipe router picks the template
        unless the operator pinned one; the props are validated against the manifest
        before the service is asked for anything; what rendered is kept even when a
        sibling output failed; the run row is written in every case — it is the evidence
        the cost and the "template × metrics" loop read."""
        if self._remotion is None or self._templates is None:
            raise _MediaFailed(
                FailureReason.PROVIDER_ERROR.value,
                UNAVAILABLE_TEXT,
                raw="the render service is not configured",
            )
        products = (
            self._catalog.products_for(
                tenant_id=tenant_id, brand_id=brief.brand_id, product_ref=brief.product_ref
            )
            if self._catalog is not None
            else ()
        )
        manifest, rule = self._pick_template(brief, products, budget)
        port = template_port(manifest, brief.format)
        if port is None:
            raise _MediaFailed(
                FailureReason.INVALID_PARAMETERS.value,
                f"la plantilla «{manifest.name}» no tiene salida {brief.format.value}",
            )
        selected = {port: manifest.outputs[port]}
        if brief.media.brand_logo_key:
            # the logo the piece was given (§ 2026-10-06) takes the template's logo slot
            kit = kit.model_copy(update={"logo_asset_key": brief.media.brand_logo_key})
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
        eta = manifest.cost_model.eta_seconds(selected, _expected_duration(manifest, props))
        per_render = self._pricing.unit_price(model_id=REMOTION_MODEL, unit="per_render")
        estimated_cost = per_render * len(selected)
        run = TemplateRunWrite(
            id=job_id,
            template_id=manifest.id,
            template_version=manifest.version,
            engine=Engine.REMOTION.value,
            status="pending",
            router_rule=str(rule) if rule is not None else None,
            outputs={
                name: {"kind": out.kind.value, "status": "pending"}
                for name, out in selected.items()
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
                props_failure_text(problems),
                template_run=_finished(
                    run, "failed", FailureReason.INVALID_PARAMETERS.value, detail
                ),
                raw=detail,
            )
        if budget.hard_stop and estimated_cost > budget.remaining_usd:
            detail = f"template render would cost {estimated_cost} with {budget.remaining_usd} left"
            raise _MediaFailed(
                FailureReason.BUDGET_EXCEEDED.value,
                BUDGET_TEXT,
                template_run=_finished(run, "failed", FailureReason.BUDGET_EXCEEDED.value, detail),
                raw=detail,
            )

        request = GenerationRequest(
            task=GenerationTask.TEMPLATE_RENDER,
            rendered_prompt=RenderedPrompt("", "", ""),
            params={
                "job_id": str(job_id),
                "template_id": manifest.id,
                "version": manifest.version,
                "props": props,
                "outputs": list(selected),
                "render_count": len(selected),
            },
        )
        trace.media_request(
            draft_id=draft_id,
            provider="Remotion",
            what=f"plantilla {manifest.id} v{manifest.version}, regla {rule}",
            fields={
                "salidas": ", ".join(selected),
                "textos que imprime": "\n".join(
                    f"  {port}: {text}" for port, text in props.texts.items()
                ),
                "marca": props.brand.name,
                "paleta": ", ".join(props.brand.palette),
                "fuentes": props.brand.fonts or "por defecto",
                "fotos": len(props.photos),
                "costo estimado": f"USD {estimated_cost:.4f}",
                "ETA": f"{eta:.0f} s",
            },
        )
        try:
            result = self._remotion.generate(request, api_key="")
        except RenderServiceError as exc:
            reason = _reason_from_service(exc.code)
            raise _MediaFailed(
                reason,
                GENERIC_FAILURE_TEXT,
                template_run=_finished(run, "failed", reason, exc.message),
                raw=f"render service {exc.code}: {exc.message}",
            ) from exc

        payload = result.payload
        assert isinstance(payload, dict)
        outputs: dict[str, dict[str, Any]] = payload["outputs"]
        failed: dict[str, dict[str, Any]] = dict(payload.get("failed_ports") or {})
        writes: list[MediaWrite] = []
        for position, (port, out) in enumerate(selected.items()):
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
            key = save(f"{port}.{extension}", data, content_type)
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
            name: {
                "kind": out.kind.value,
                "status": "completed" if name in outputs else "failed",
                **({} if name in outputs else failed.get(name, {})),
            }
            for name, out in selected.items()
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
            logger.warning(
                "template run %s: outputs not rendered: %s",
                job_id,
                ", ".join(
                    f"{port} ({info.get('failure_reason')})" for port, info in failed.items()
                ),
            )
            detail = "No se pudo generar el video con la plantilla."
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
                    FailureReason.INVALID_PARAMETERS.value,
                    NO_TEMPLATE_TEXT,
                    raw=f"unknown template {exc}",
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
        # The operator chose a template, so it is Remotion's option even when the router
        # would suggest another engine (§ 2026-10-06: «¿Cómo la hacemos?», where they
        # could say otherwise, left the wizard). It still has to be available.
        chosen = next((o for o in options if o.engine is Engine.REMOTION), None)
        if chosen is None or chosen.template_id is None or not chosen.available:
            # the recipe router's reasons are Spanish and vendor-free («la plantilla
            # «Promo de producto» necesita 2 fotos»): they reach the operator as they are
            reason = chosen.reason if chosen is not None else ""
            raise _MediaFailed(
                FailureReason.ROUTE_BLOCKED_BY_POLICY.value,
                (reason[:1].upper() + reason[1:] + ".") if reason else NO_TEMPLATE_TEXT,
                raw=reason or "no published template serves this post",
            )
        return self._templates.get(chosen.template_id, chosen.template_version), chosen.rule

    # -- video -------------------------------------------------------------------------

    def _key(self, tenant_id: UUID, brand_id: UUID) -> str:
        try:
            resolved = self._credentials.resolve(
                tenant_id=tenant_id, brand_id=brand_id, provider=HEYGEN
            )
        except Exception as exc:  # the resolver's own error types are adapter-specific
            raise _MediaFailed(
                FailureReason.PROVIDER_ERROR.value, UNAVAILABLE_TEXT, raw=f"no HeyGen key: {exc}"
            ) from exc
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
            raise _MediaFailed(
                FailureReason.PROVIDER_ERROR.value,
                GENERIC_FAILURE_TEXT,
                raw=f"HeyGen upload: no asset_id ({asset!r:.200})",
            )
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
        save: _Saver,
    ) -> list[MediaWrite]:
        if self._heygen is None:
            raise _MediaFailed(
                FailureReason.PROVIDER_ERROR.value,
                UNAVAILABLE_TEXT,
                raw="HeyGen is not configured",
            )
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
                "tu propia voz clonada o una de las voces disponibles.",
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
            # only the logo the piece was GIVEN: an avatar video had none before
            logo=self._logo(kit, media.brand_logo_key) if media.brand_logo_key else None,
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
                "avatar_id": self._prompt_avatar(
                    key, brief, stamp, budget, usage, draft_id=draft_id
                ),
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
        trace.media_request(
            draft_id=draft_id,
            provider="HeyGen",
            what="video con avatar",
            fields={
                "guion (lo que dice el avatar)": params.get("script"),
                "voz": params.get("voice_id"),
                "avatar": params.get("avatar_id"),
                "motor": params.get("engine"),
                "foto animada": "sí" if "image_asset_id" in params else None,
                "fondo compuesto": "sí" if "background_image_asset_id" in params else None,
                "formato": f"{params.get('aspect_ratio')} · {params.get('resolution')}",
                "locale": params.get("locale"),
            },
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
                BUDGET_TEXT if blocked else heygen_failure_text(detail),
                raw=detail,
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

        video_key = save("video.mp4", self._download(str(result.media_url)), MP4)
        extra: dict[str, Any] = {}
        thumbnail = payload.get("thumbnail_url")
        if thumbnail:
            try:
                extra["thumbnail_key"] = save("thumbnail.jpg", self._download(str(thumbnail)), JPEG)
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
        *,
        draft_id: UUID,
    ) -> str:
        """A synthetic avatar from the operator's description — a photoreal person for
        `AVATAR_VIDEO`, an animated character otherwise: created, then waited for — its
        look id is the video's avatar."""
        assert self._heygen is not None
        price = self._pricing.unit_price(model_id=PROMPT_AVATAR_MODEL, unit="per_piece")
        if budget.hard_stop and price > budget.remaining_usd:
            raise _MediaFailed(
                FailureReason.BUDGET_EXCEEDED.value,
                BUDGET_TEXT,
                raw=f"prompt avatar over budget ({price} > {budget.remaining_usd})",
            )
        style = HUMAN_STYLE if brief.kind is ContentKind.AVATAR_VIDEO else ANIMATED_STYLE
        prompt = (style + brief.media.avatar_prompt.strip())[:1000]
        trace.media_request(
            draft_id=draft_id,
            provider="HeyGen",
            what="avatar a partir de una descripción",
            fields={"prompt": prompt, "costo": f"USD {price:.4f}"},
        )
        look_id = self._heygen.create_prompt_avatar(
            api_key=key,
            name=f"qualify-{stamp[:8]}",
            prompt=prompt,
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
# prompts for the generated media (§ 2026-10-07)
#
# Seedream 5.0 lite reads Chinese and English, so the scaffolding is English; what the
# operator wrote travels quoted, in their words. No model is ever asked for text or a
# logo: the words and the real logo are set afterwards (`render_ad_slides`) — a model
# misspells a brand.

_NO_TEXT = (
    "Do not draw any text, letters, numbers, captions, logos or watermarks anywhere in the image."
)
_ORIENTATION = {
    "4:5": "vertical 4:5",
    "3:4": "vertical 3:4",
    "9:16": "vertical 9:16",
    "1:1": "square 1:1",
}


def _palette_line(kit: BrandKit) -> str:
    colors = ", ".join(kit.palette_rgb[:4])
    return f"Use the brand colors as accents where natural: {colors}." if colors else ""


#: How much of the operator's topic (no stored cap: `content_briefs.topic` is TEXT) goes
#: into an image prompt — the gist is enough, and with the scene at its own cap of 600
#: the prompt stays near 2,100 of the vendor's 3,000 characters.
_PROMPT_TOPIC_MAX = 600


def _quoted(text: str, limit: int | None = None) -> str:
    text = text.strip()
    if limit is not None and len(text) > limit:
        text = fit_text(text, limit)
    return text.replace('"', "'")


def ad_scene_prompt(
    *,
    brief: ContentBrief,
    kit: BrandKit,
    brand: str,
    mode: AdImageMode,
    products: int,
    has_background: bool,
) -> str:
    """The advertising photograph Seedream is asked for. Reference images come in this
    order: the product photos first, the background (the operator's place) last."""
    ratio = brief.format.aspect_ratio
    lines = [
        f"Professional advertising photograph for a social media ad"
        f"{f' of the brand {brand}' if brand else ''}, {_ORIENTATION.get(ratio, ratio)} "
        "composition, photorealistic, appetizing and premium, natural light, sharp focus.",
    ]
    product_refs = "image 1" if products == 1 else f"images 1 to {products}"
    if mode is AdImageMode.PRODUCT and products:
        lines.append(
            f"The product in {product_refs} is the client's real product: keep it exactly as "
            "it is (shape, colors, label and packaging) and make it the hero of a new, "
            "attractive scene that fits it."
        )
    elif mode is AdImageMode.BACKGROUND and has_background:
        lines.append(
            "The reference image is the client's real place: keep it recognisable as the "
            "setting, and invent an attractive moment in front of it."
        )
    elif products and has_background:
        lines.append(
            f"Place the client's real product ({product_refs}, keep it exactly as it is: "
            "shape, colors, label) naturally inside the client's real place (the last "
            "image, keep it recognisable), as if photographed there."
        )
    if brief.media.scene_prompt.strip():
        scene = _quoted(brief.media.scene_prompt)
        lines.append(f'Scene the client asked for (in Spanish): "{scene}".')
    lines.append(f'The post is about (in Spanish): "{_quoted(brief.topic, _PROMPT_TOPIC_MAX)}".')
    lines.append(
        "Keep the top quarter and the bottom fifth of the frame calm and uncluttered: the "
        "headline and a button are laid over them afterwards."
    )
    lines.append(_palette_line(kit))
    lines.append(_NO_TEXT)
    return " ".join(line for line in lines if line)


def carousel_scene_prompt(
    *,
    brief: ContentBrief,
    kit: BrandKit,
    brand: str,
    scene: str,
    ratio: str,
    has_product: bool,
    has_background: bool,
    has_text: bool,
) -> str:
    """One carousel slide's photograph (§ 2026-10-09). References in this order: the
    product photo first, the background (the operator's place) last."""
    lines = [
        f"Professional advertising photograph for a social media carousel"
        f"{f' of the brand {brand}' if brand else ''}, {_ORIENTATION.get(ratio, ratio)} "
        "composition, photorealistic, appetizing and premium, natural light, sharp focus.",
    ]
    if has_product and has_background:
        lines.append(
            "Place the client's real product (image 1, keep it exactly as it is: shape, "
            "colors, label) naturally inside the client's real place (image 2, keep it "
            "recognisable), as if photographed there."
        )
    elif has_product:
        lines.append(
            "The product in image 1 is the client's real product: keep it exactly as it is "
            "(shape, colors, label and packaging) and make it the hero of the scene."
        )
    elif has_background:
        lines.append(
            "The reference image is the client's real place: keep it recognisable as the setting."
        )
    if scene.strip():
        lines.append(f'This slide shows (in Spanish): "{_quoted(scene)}".')
    topic = _quoted(brief.topic, _PROMPT_TOPIC_MAX)
    lines.append(f'The carousel is about (in Spanish): "{topic}".')
    if has_text:
        lines.append(
            "Keep the top quarter and the bottom fifth of the frame calm and uncluttered: "
            "a headline or a button is laid over them afterwards."
        )
    lines.append(_palette_line(kit))
    lines.append(_NO_TEXT)
    return " ".join(line for line in lines if line)


def carousel_motion_prompt() -> str:
    """What Seedance does with a carousel slide's scene: a short, silent, product-led
    shot — nobody talks, nothing is written."""
    return (
        "Bring this photograph to life as a short cinematic product shot: a slow, smooth "
        "camera move (gentle push-in or slight orbit), subtle natural motion in the scene "
        "(steam, light, a hand, the background), the product keeps its exact look and "
        "label. Nobody talks to the camera. No text on screen."
    )


def _cover_png(data: bytes, size: tuple[int, int]) -> bytes:
    """An image cover-cropped to `size`, centred — a reused piece fitted to the slide."""
    from PIL import Image, ImageOps  # noqa: PLC0415

    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    out = io.BytesIO()
    ImageOps.fit(image, size, Image.LANCZOS).save(out, format="PNG")
    return out.getvalue()


def _presenter(brief: ContentBrief, *, has_character_image: bool) -> str:
    media = brief.media
    if has_character_image:
        return "The character is the one in image 1: keep its exact design, colors and proportions."
    description = _quoted(media.avatar_prompt) or "a friendly presenter"
    if brief.kind is ContentKind.ANIMATED_AVATAR_VIDEO:
        return (
            "An expressive 3D animated character in the style of an animated feature film, "
            f'described by the client (in Spanish) as: "{description}".'
        )
    return (
        "A photorealistic, natural-looking person (a synthetic presenter, nobody real), "
        f'described by the client (in Spanish) as: "{description}".'
    )


def first_frame_prompt(
    *,
    brief: ContentBrief,
    kit: BrandKit,
    has_character_image: bool,
    products: int,
    has_background: bool,
) -> str:
    """The video's opening frame. Reference images: the character's image first (when
    the operator uploaded one), then the products, then the background."""
    ratio = SEEDANCE_RATIOS[brief.format]
    first_product = 2 if has_character_image else 1
    lines = [
        f"Opening frame of a {_ORIENTATION.get(ratio, ratio)} social media video, "
        "cinematic and well lit.",
        _presenter(brief, has_character_image=has_character_image),
        "Medium shot, facing the camera, mid-sentence with a natural expression, as if "
        "talking to the viewer.",
    ]
    if products:
        last = first_product + products - 1
        refs = f"image {first_product}" if products == 1 else f"images {first_product} to {last}"
        lines.append(
            f"The client's real product ({refs}) is clearly visible in the scene — held or "
            "on the table in front of them — exactly as it is: shape, colors, label."
        )
    if has_background:
        lines.append("The scene takes place in the client's real place (the last image).")
    lines.append(f'The video is about (in Spanish): "{_quoted(brief.topic, _PROMPT_TOPIC_MAX)}".')
    lines.append(_palette_line(kit))
    lines.append(_NO_TEXT)
    return " ".join(line for line in lines if line)


def motion_prompt(*, brief: ContentBrief, products: int) -> str:
    """What Seedance animates from the first frame. The script is passed apart
    (`dialogue`): the 2.x models speak it, 1.0 ignores it."""
    who = (
        "The animated character"
        if brief.kind is ContentKind.ANIMATED_AVATAR_VIDEO
        else "The presenter"
    )
    lines = [
        f"{who} talks to the camera with natural lip movement, gestures and facial "
        "expressions, enthusiastic and warm.",
    ]
    if products:
        lines.append(
            "They show the product to the camera; the product keeps its exact look and label."
        )
    lines.append("Smooth, slight handheld camera movement, natural light. No text on screen.")
    return " ".join(lines)


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
