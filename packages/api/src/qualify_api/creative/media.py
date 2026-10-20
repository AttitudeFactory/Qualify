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
- `AVATAR_VIDEO` / `ANIMATED_AVATAR_VIDEO` with `VideoEngine.OMNIHUMAN` (§ request
  2026-10-16, the move from HeyGen to ByteDance), through the `GenerationProvider` seam
  and the `CreativeRouter` (credential resolution + the budget pre-flight):
  1. the voice resolved server-side (`voice_access.BrandVoiceResolver`): the brand's own
     cloned voice or a public one — refused before any spend otherwise;
  2. the presenter composed by Seedream (described, or the operator's image) with the
     products and the background;
  3. the script read by Seed Speech in that voice (MP3);
  4. OmniHuman makes the presenter say it, lips in sync, from the photo and the voice as
     public-media token URLs; the video is DOWNLOADED at once (its URL lives 1 h).
- `VideoEngine.HEYGEN` is RETIRED (2026-10-16): a brief stored with it is refused with a
  message, nothing is rendered.
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

import io
import json
import logging
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from qualify_creative.adapters.byteplus_ark import (
    output_dimensions,
    seedance_family,
    video_cost_usd,
)
from qualify_creative.adapters.byteplus_omnihuman import (
    DEFAULT_REQ_KEY as DEFAULT_OMNIHUMAN_REQ_KEY,
)
from qualify_creative.adapters.byteplus_omnihuman import MODEL_IDS, omnihuman_cost_usd
from qualify_creative.adapters.byteplus_speech import VOICE_SLOT_MODEL, speech_cost_usd
from qualify_creative.compose import (
    FlyerText,
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
from qualify_creative.schemas import (
    SCRIPT_MAX,
    BrandKit,
    CarouselSlide,
    ContentBrief,
    CopyPayload,
)
from qualify_creative.video import VideoFitter

from qualify_api.stock.guard import stock_problems
from qualify_api.stock.keys import is_stock_key

from . import trace
from .pieces import PieceFile, PieceFiles
from .voice_access import ResolvedVoice, VoiceRefused, default_public_voice

logger = logging.getLogger(__name__)

REMOTION = "remotion"
#: ByteDance's talking presenter (§ 2026-10-16): two more router links, two more keys.
SEED_SPEECH = "seed_speech"
OMNIHUMAN = "omnihuman"
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
MP3 = "audio/mpeg"
#: Spanish read aloud runs ~14-16 characters a second: the fallback length of a voice
#: track whose duration PyAV cannot read.
_CHARS_PER_SECOND = 15.0
#: Render jobs are named deterministically from the draft and the recipe, so a retry of
#: the same draft re-uses the service's job (CONTRACT §4: `POST /render` is idempotent on
#: the id) instead of rendering twice.
TEMPLATE_JOB_NAMESPACE = UUID("6f1c2d3e-4a5b-4c6d-8e9f-0a1b2c3d4e5f")


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
    #: Whether this file is AI imagery (a Seedream scene, a Seedance or HeyGen video),
    #: said by the code that MADE it, at the write site — not looked up by vendor name
    #: afterwards (PR #100 review). The draft's `requires_ai_disclosure` is recomputed
    #: from this after every generation: a flyer stored before `ad_mode` existed is still
    #: rendered by Seedream when it is wired, and the brief alone cannot know that.
    ai_generated: bool = False


def ai_generated_media(media: tuple[MediaWrite, ...]) -> bool:
    """Whether any file of a generation is AI imagery."""
    return any(item.ai_generated for item in media)


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
        # The resolved path must stay inside the key's OWN tenant directory
        # (`<root>/<tenant>/`), not merely inside the store (PR #100 review). One
        # `resolve()`: the resolved path's first two components under the store root are
        # compared with the key's own, which also defeats a drive-letter segment on Windows.
        parts = parse_tenant_key(key)
        if parts is None:
            raise ValueError(f"media key is not a tenant-rooted path: {key!r}")
        path = (self.root / key).resolve()
        try:
            inside = path.relative_to(self.root).parts
        except ValueError:
            inside = ()
        if len(inside) < 3 or not _same_segments(inside[:2], parts[:2]):
            raise ValueError(f"media key escapes its tenant's directory: {key!r}")
        return path

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


#: Windows and macOS file systems are case-insensitive by default and `resolve()` returns
#: the on-disk spelling, so a key that differs from its directory only in case names the
#: same file there — the tenant-directory comparison folds case on those platforms.
_FOLD_CASE = sys.platform in ("win32", "darwin")


def _same_segments(found: tuple[str, ...], wanted: tuple[str, ...]) -> bool:
    if found == wanted:
        return True
    return _FOLD_CASE and tuple(s.casefold() for s in found) == tuple(s.casefold() for s in wanted)


#: Where a brand's files live: R2 (`t/` — the Brand Kit, generated pieces) and the local
#: store (`uploads/` — what the operator uploads, the catalog; `generated/` — pieces made
#: before 2026-10-06). Each is followed by the tenant id.
_TENANT_ROOTS = ("t", "uploads", "generated")
_FOREIGN_FILE = "Uno de los archivos de la pieza no es de tu marca."
_BAD_KEY = "Uno de los archivos de la pieza tiene una ruta que no es válida. Vuelve a elegirlo."
_MISSING_PIECE = "La pieza de la diapositiva {n} ya no está disponible. Elige otra."
_MISSING_STOCK = "El video de stock de la diapositiva {n} ya no está disponible. Elige otro."


def parse_tenant_key(key: str) -> tuple[str, ...] | None:
    """The segments of a tenant-rooted POSIX key, `<root>/<tenant>/<…>/<file>`, or None
    when `key` is not one. The ONE grammar `owned_by` and `LocalMediaStore` share (PR
    #100 review): at least three segments, none empty, `.` or `..`, and no backslash —
    keys are POSIX, a backslash never belongs in one, and on Windows `Path` reads it as
    a separator, so `uploads/<a>/..\\<b>/x.jpg` once slipped past a `/`-only `..` check
    and read tenant b's file (reproduced 2026-10-10)."""
    if not key or "\\" in key:
        return None
    parts = tuple(key.split("/"))
    if len(parts) < 3 or any(part in ("", ".", "..") for part in parts):
        return None
    return parts


def owned_by(tenant_id: UUID, key: str) -> bool:
    """Whether `key` is one of this tenant's files — the check a read must pass before
    it happens (PR #100 review): a key in a brief can come from the browser, and a key
    another brand's id is in must never be read into this brand's piece."""
    parts = parse_tenant_key(key)
    return parts is not None and parts[0] in _TENANT_ROOTS and parts[1] == str(tenant_id)


def _key_problems(
    tenant_id: UUID, brief: ContentBrief, kit: BrandKit
) -> tuple[list[str], list[str]]:
    """The files the piece would read that it must not: `(malformed, foreign)`. A key that
    is not a tenant-rooted path at all is told apart from one that is another brand's —
    the operator and the log must not read «not your brand's» for a bad path (PR #100
    review)."""
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
        media.clip_first_frame_key,
        media.clip_last_frame_key,
        *media.clip_image_keys,
        *media.clip_video_keys,
        *media.clip_audio_keys,
    ]
    present = [key for key in keys if key]
    malformed = [key for key in present if parse_tenant_key(key) is None]
    foreign = [key for key in present if key not in malformed and not owned_by(tenant_id, key)]
    return malformed, foreign


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

#: A brief stored with the retired HeyGen engine (2026-10-16).
RETIRED_ENGINE_TEXT = (
    "Este video se pidió con un motor de avatar que ya no usamos. Vuelve a crearlo desde "
    "Crear pieza."
)
#: The voice track is longer than OmniHuman takes (1.5: under 60 s).
AVATAR_SCRIPT_TOO_LONG = (
    "El guion es demasiado largo para un video con avatar: acórtalo a menos de un minuto."
)
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

#: The talking presenter's vendors (Seed Speech, OmniHuman — § 2026-10-16), by meaning:
#: error codes from their docs, read 2026-10-16. Matched on the text the adapters carry.
_AVATAR_FAILURES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "QUALIFY_BYTEPLUS_SPEECH_API_KEY",
            "QUALIFY_BYTEPLUS_CV_API_KEY",
            "MissingPlatformKey",
            "SeedSpeechNotConfigured",
        ),
        UNAVAILABLE_TEXT,
    ),
    (("code 50510", "code 50511", "code 50512"), FILTERED_TEXT),  # content pre-filter
    (("code 50400", "code 50401", "HTTP 401", "HTTP 403"), UNAVAILABLE_TEXT),
    (("code 45000000", "permission denied"), UNAVAILABLE_TEXT),
    (("OmniHumanTimeout",), SLOW_TEXT),
    (("concurrency", "HTTP 429", "code 50429"), RATE_LIMITED_TEXT),
    (("provider not registered",), UNAVAILABLE_TEXT),
)


def avatar_failure_text(raw: str) -> str:
    """What the operator reads when a talking presenter fails: the known cases by
    meaning, else the image/video ones (Seedream composes the presenter), else the
    generic failure. `raw` is never part of the result — the caller logs it."""
    for needles, text in _AVATAR_FAILURES:
        if any(needle in raw for needle in needles):
            return text
    return ark_failure_text(raw)


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


def _audio_seconds(data: bytes) -> float | None:
    """A voice track's length, read with PyAV (header only); None when it cannot tell."""
    try:
        import av  # noqa: PLC0415 — the `media` extra, already used by the video fitter

        with av.open(io.BytesIO(data)) as container:
            if container.duration:
                return container.duration / 1_000_000
            stream = container.streams.audio[0] if container.streams.audio else None
            if stream is not None and stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
    except Exception:  # noqa: BLE001 — a fallback length is computed by the caller
        return None
    return None


#: A clip frame with one of these endings is a video (§ request 2026-10-19: a video
#: can open or close the clip) — one of its frames is used.
_VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".m4v")


def _video_frame(data: bytes, *, last: bool) -> bytes:
    """A video's first frame — or its last — as a JPEG. Raises when the file has no
    video frame. For the last one it seeks to the keyframe before the final second and
    decodes from there, not the whole file (review 2026-10-19); a container that cannot
    seek is decoded from the start, as before."""
    frame = _decode_frame(data, last=last, seek=last)
    if frame is None and last:
        frame = _decode_frame(data, last=True, seek=False)
    if frame is None:
        raise ValueError("the video has no frame")
    out = io.BytesIO()
    frame.to_image().convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def _decode_frame(data: bytes, *, last: bool, seek: bool) -> Any:
    import av  # noqa: PLC0415 — the `media` extra, already used by the video fitter

    frame = None
    with av.open(io.BytesIO(data)) as container:
        if not container.streams.video:
            return None
        stream = container.streams.video[0]
        if seek and stream.duration and stream.time_base:
            target = max(0, stream.duration - int(1 / stream.time_base))
            try:
                container.seek(target, stream=stream, backward=True)
            except av.FFmpegError:
                return None
        for decoded in container.decode(stream):
            frame = decoded
            if not last:
                break
    return frame


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


def template_port(
    manifest: TemplateManifest, fmt: ContentFormat, *, video: bool | None = None
) -> str | None:
    """The ONE output of `manifest` a brief of format `fmt` renders (§ request 2026-10-06:
    a template gives one piece, not the Reel + feed + story package): its video output of
    the format's proportions when `video` (a Reel always is; a Story video is the 9:16
    one, § 2026-10-13), else its still of those proportions. None when the template has
    no such output."""
    want_video = fmt is ContentFormat.REELS_9_16 if video is None else video
    width, height = fmt.dimensions
    for port, out in manifest.outputs.items():
        is_video = out.media_type == "video"
        if is_video != want_video:
            continue
        # the same proportions, video or still: a 4:5 post video is not the 9:16 Reel
        if out.width * height == out.height * width:
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


class VoiceResolver(Protocol):
    """Which voice reads a brand's script (`voice_access.BrandVoiceResolver`)."""

    def __call__(self, *, tenant_id: UUID, brand_id: UUID, choice: str) -> ResolvedVoice: ...


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


class ReferenceLinks(Protocol):
    """A clip's reference video or audio as a public ``https`` URL ModelArk can fetch —
    it takes no Base64 for them (§ 2026-10-14). The production linker stores the bytes
    under the tenant's R2 prefix and hands out a short-lived public-media token URL."""

    def __call__(self, *, tenant_id: UUID, key: str, data: bytes, content_type: str) -> str: ...


def _links_ready(links: ReferenceLinks | None) -> bool:
    """Whether reference links can be handed to a vendor right now. A linker without a
    `ready()` (a test double) is taken as ready; the production one checks the public base
    URL and R2 (`composition.public_media_ready`)."""
    if links is None:
        return False
    ready = getattr(links, "ready", None)
    return bool(ready()) if callable(ready) else True


#: A clip's reference media types, by the file's extension.
_REFERENCE_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}

CLIP_NO_PUBLIC_URL = (
    "Para usar videos o audios de referencia, el servidor necesita una dirección pública "
    "desde la que el generador pueda descargarlos, y no está configurada. Quita esas "
    "referencias o pide que la configuren."
)
#: The talking presenter needs the same public URL: OmniHuman fetches the photo and the
#: voice from it, and takes no Base64.
AVATAR_NO_PUBLIC_URL = (
    "El video con avatar necesita una dirección pública desde la que el generador pueda "
    "descargar la foto y la voz, y no está configurada. Avisa al equipo."
)


class MediaProducer:
    def __init__(
        self,
        *,
        store: MediaStore,
        router: CreativeRouter,
        credentials: CredentialResolver,
        pricing: PricingTable,
        download: Downloader = _http_download,
        voices: VoiceResolver | None = None,
        on_brand_voice_used: Callable[[UUID, UUID, str], None] | None = None,
        omnihuman_resolution: int = 720,
        omnihuman_max_seconds: float = 59.0,
        omnihuman_req_key: str = DEFAULT_OMNIHUMAN_REQ_KEY,
        remotion: RemotionTemplateAdapter | None = None,
        templates: TemplateRegistry | None = None,
        brand_names: BrandNames | None = None,
        catalog: ProductCatalog | None = None,
        generated_ad_images: bool = False,
        seedance_resolution: str = "720p",
        pieces: PieceFiles | None = None,
        fitter: VideoFitter | None = None,
        seedance_reference_model: str | None = None,
        reference_links: ReferenceLinks | None = None,
    ) -> None:
        self._store = store
        self._router = router
        self._credentials = credentials
        self._pricing = pricing
        self._download = download
        #: The talking presenter (§ 2026-10-16): which voice reads the script (the
        #: brand's own clone or a public one, `voice_access`), the stamp of a cloned
        #: voice's first real synthesis, and OmniHuman's resolution and audio ceiling.
        #: No resolver = the presenter is unavailable.
        self._voices = voices
        self._on_brand_voice_used = on_brand_voice_used
        self._omnihuman_resolution = omnihuman_resolution
        self._omnihuman_max_seconds = omnihuman_max_seconds
        self._omnihuman_req_key = omnihuman_req_key
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
        #: A clip with references (§ 2026-10-14) needs a Seedance 2.x model, and its
        #: video/audio references a public URL. None = a clip takes frames only.
        self._seedance_reference_model = seedance_reference_model
        self._reference_links = reference_links

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
        malformed, foreign = _key_problems(tenant_id, brief, kit)
        if malformed:
            # before any read, spend or vendor call — a key that is not a path we serve
            logger.warning(
                "creative media for draft %s refused: malformed keys: %s", draft_id, malformed
            )
            return MediaOutcome(failure=FailureReason.INVALID_PARAMETERS.value, detail=_BAD_KEY)
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
        misplaced_stock = stock_problems(brief)
        if misplaced_stock:
            # before any read, spend or vendor call — stock only where a piece may use it
            logger.warning("creative media for draft %s refused: stock misplaced", draft_id)
            return MediaOutcome(
                failure=FailureReason.ROUTE_BLOCKED_BY_POLICY.value, detail=misplaced_stock
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
            elif brief.kind.is_video and brief.media.video_engine is VideoEngine.OMNIHUMAN:
                media = self._omnihuman_video(
                    tenant_id, draft_id, brief, kit, copy, budget, usage, save
                )
            elif brief.kind.is_video:
                # HeyGen, retired 2026-10-16: nothing is rendered nor paid
                raise _MediaFailed(
                    FailureReason.PROVIDER_ERROR.value,
                    RETIRED_ENGINE_TEXT,
                    raw=f"retired video engine {brief.media.video_engine}",
                )
            elif brief.kind is ContentKind.TEMPLATE:
                return self._template(tenant_id, draft_id, brief, kit, copy, budget, usage, save)
            elif brief.kind is ContentKind.CAROUSEL:
                media = self._carousel(tenant_id, draft_id, brief, kit, copy, budget, usage, save)
            elif brief.kind is ContentKind.CLIP:
                media = self._clip(tenant_id, draft_id, brief, kit, copy, budget, usage, save)
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
            presenter = brief.kind.is_video and (brief.media.video_engine is VideoEngine.OMNIHUMAN)
            return MediaOutcome(
                usage=tuple(usage),
                failure=FailureReason.PROVIDER_ERROR.value,
                detail=avatar_failure_text(raw) if presenter else ark_failure_text(raw),
            )
        return MediaOutcome(media=tuple(media), usage=tuple(usage))

    # -- inputs ------------------------------------------------------------------------

    def _read(self, key: str | None) -> bytes | None:
        return self._store.read(key) if key else None

    def _clip_frame(self, key: str | None, *, last: bool) -> bytes | None:
        """A clip's opening or closing frame: an image as it is; a video (§ request
        2026-10-19) lends its first frame to open the clip and its last to close it."""
        data = self._read(key)
        if data is None or not str(key).lower().endswith(_VIDEO_SUFFIXES):
            return data
        try:
            return _video_frame(data, last=last)
        except Exception as exc:  # noqa: BLE001 — a broken file: say which, never a crash
            logger.warning("clip frame from video failed: %s", type(exc).__name__)
            raise _MediaFailed(
                FailureReason.INVALID_PARAMETERS.value,
                "No pudimos sacar el fotograma del video que abre o cierra el clip. "
                "Prueba con otro video o con una imagen.",
            ) from exc

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
        failure_text: Callable[[str], str] | None = None,
    ) -> Any:
        """One vendor call through the router (key + budget pre-flight); the failure in
        the operator's words (`failure_text`, ModelArk's by default)."""
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
                BUDGET_TEXT if blocked else (failure_text or ark_failure_text)(detail),
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
        own product and/or background as references (one per carousel slide) — or from
        the described scene alone when they uploaded none (§ 2026-10-12) — and the
        words and the real logo are set on top locally."""
        media = brief.media
        mode = media.ad_mode or (
            AdImageMode.BOTH
            if media.product_keys and media.background_key
            else AdImageMode.BACKGROUND
            if media.background_key
            else AdImageMode.PRODUCT
            if media.product_keys
            else AdImageMode.SCENE
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
        if brief.format is ContentFormat.REELS_9_16:
            # § 2026-10-13: Instagram publishes only a video as a Reel — the composed
            # image (words and logo on it) gets a slow push-in; nothing is generated twice
            return [
                self._ad_reel(
                    slides[0],
                    brief=brief,
                    model_id=model_id,
                    params={
                        "ad_mode": mode.value,
                        "scene_prompt": media.scene_prompt,
                        "generated_scenes": len(scenes),
                        "products": len(products),
                        "background": background is not None,
                    },
                    save=save,
                )
            ]
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
                    ai_generated=True,
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

    def _ad_reel(
        self,
        still: bytes,
        *,
        brief: ContentBrief,
        model_id: str,
        params: dict[str, Any],
        save: _Saver,
    ) -> MediaWrite:
        """The advertising image as a Reel: the composed still animated into a short
        H.264 video, its poster the still itself."""
        reel = self._require_fitter().animate_still(still, size=brief.format.dimensions)
        video_key = save("reel.mp4", reel.data, MP4)
        poster_key = save("reel-poster.jpg", to_meta_jpeg(reel.poster or still), JPEG)
        return MediaWrite(
            position=0,
            media_type="video",
            media_url=video_key,
            object_key=video_key,
            width=reel.width,
            height=reel.height,
            aspect_ratio=brief.format.aspect_ratio,
            model_id=model_id,
            provider=SEEDREAM,
            content_type=MP4,
            ai_generated=True,
            params={
                **params,
                "duration_seconds": round(reel.duration_sec, 2),
                "thumbnail_key": poster_key,
                "animated_still": True,
            },
        )

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
                ai_generated=True,
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

    # -- clip (§ request 2026-10-14) -------------------------------------------------------

    def _clip(
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
        """A generated video with no presenter. With references, a Seedance 2.x model
        follows them — the frames go first among the reference images and the prompt
        names them, because ModelArk does not mix the frame roles with references; with
        frames alone, the default model animates from the opening frame to the closing
        one; with neither, from the words alone."""
        media = brief.media
        ratio = SEEDANCE_RATIOS[brief.format]
        first = self._clip_frame(media.clip_first_frame_key, last=False)
        last = self._clip_frame(media.clip_last_frame_key, last=True)
        images = [self._store.read(key) for key in media.clip_image_keys]
        params: dict[str, object] = {
            "ratio": ratio,
            "duration_seconds": media.duration_seconds,
        }
        resolution = self._seedance_resolution
        if media.clip_has_references:
            model = self._seedance_reference_model
            if not model:
                raise _MediaFailed(
                    FailureReason.INVALID_PARAMETERS.value,
                    "Las referencias necesitan un modelo de video que las acepte, y no hay "
                    "uno configurado.",
                )
            frames = [frame for frame in (first, last) if frame is not None]
            params["model"] = model
            params["reference_images"] = [_data_url(image) for image in (*frames, *images)]
            params["reference_videos"] = self._reference_urls(tenant_id, media.clip_video_keys)
            params["reference_audios"] = self._reference_urls(tenant_id, media.clip_audio_keys)
            family = seedance_family(model)
            if resolution not in family.resolutions:
                resolution = "720p"
        else:
            if first is not None:
                params["first_frame"] = _data_url(first)
            if last is not None:
                params["last_frame"] = _data_url(last)
        params["resolution"] = resolution
        prompt = clip_prompt(
            brief=brief,
            kit=kit,
            copy=copy,
            image_roles=media.clip_image_roles,
            first_frame=first is not None,
            last_frame=last is not None,
            images=len(images),
            videos=len(media.clip_video_keys),
            audios=len(media.clip_audio_keys),
        )
        params["prompt"] = prompt
        request = GenerationRequest(
            task=GenerationTask.SCENE_VIDEO,
            rendered_prompt=RenderedPrompt("", "", ""),
            params=params,
        )
        trace.media_request(
            draft_id=draft_id,
            provider="Seedance",
            what="clip",
            fields={
                "prompt": prompt,
                "modelo": str(params.get("model") or "el predeterminado"),
                "fotogramas": f"inicial {'sí' if first else 'no'} · final {'sí' if last else 'no'}",
                "referencias": (
                    f"{len(images)} imágenes · {len(media.clip_video_keys)} videos · "
                    f"{len(media.clip_audio_keys)} audios"
                ),
                "formato": f"{ratio} · {resolution}",
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
        out_resolution = str(payload.get("resolution") or resolution)
        tokens = int(result.usage.output_tokens)
        usage.append(
            MediaUsage(
                provider=result.provider,
                model_id=result.model_id,
                unit="second",
                quantity=math.ceil(result.usage.media_seconds),
                cost_usd=video_cost_usd(self._pricing, result.model_id, out_resolution, tokens),
            )
        )
        video_key = save("clip.mp4", self._download(str(result.media_url)), MP4)
        thumbnail_key = save("first-frame.jpg", to_meta_jpeg(first), JPEG) if first else None
        width, height = output_dimensions(result.model_id, out_resolution, ratio)
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
                ai_generated=True,
                params={
                    "task_id": payload.get("task_id"),
                    "duration_seconds": payload.get("duration_seconds"),
                    "resolution": out_resolution,
                    "tokens": tokens,
                    "spoken": bool(payload.get("generate_audio")),
                    "references": {
                        "images": len(images),
                        "videos": len(media.clip_video_keys),
                        "audios": len(media.clip_audio_keys),
                    },
                    "thumbnail_key": thumbnail_key,
                    "model_revision": result.model_revision,
                },
            )
        ]

    def _reference_urls(self, tenant_id: UUID, keys: tuple[str, ...]) -> list[str]:
        """Each reference video/audio as the public URL ModelArk fetches."""
        if not keys:
            return []
        if self._reference_links is None:
            raise _MediaFailed(FailureReason.INVALID_PARAMETERS.value, CLIP_NO_PUBLIC_URL)
        urls: list[str] = []
        for key in keys:
            suffix = Path(key).suffix.lower()
            content_type = _REFERENCE_TYPES.get(suffix)
            if content_type is None:
                raise _MediaFailed(
                    FailureReason.INVALID_PARAMETERS.value,
                    f"El archivo de referencia «{Path(key).name}» no es MP4, MOV, MP3 ni WAV.",
                )
            try:
                urls.append(
                    self._reference_links(
                        tenant_id=tenant_id,
                        key=key,
                        data=self._store.read(key),
                        content_type=content_type,
                    )
                )
            except _MediaFailed:
                raise
            except Exception as exc:  # R2 or the public-media config
                raise _MediaFailed(
                    FailureReason.INVALID_PARAMETERS.value,
                    CLIP_NO_PUBLIC_URL,
                    raw=f"{type(exc).__name__}: {exc}",
                ) from exc
        return urls

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
        # the same for every stock video: read up front, before anything is paid
        stock_videos = self._stock_videos(brief)
        out: list[MediaWrite] = []
        for position, slide in enumerate(media.slides):
            number = position + 1
            if slide.source is SlideSource.EXISTING:
                out.append(self._existing_slide(brief, pieces[position], position, save))
                continue
            if slide.source is SlideSource.STOCK:
                out.append(
                    self._stock_slide(
                        brief, kit, copy, slide, stock_videos[position], position, logo, save
                    )
                )
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
                        ai_generated=True,
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
                    reference_video_key=slide.reference_video_key,
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
        reference_video_key: str | None = None,
    ) -> MediaWrite:
        """Seedance animates the slide's scene (silent, nobody talking), then the clip is
        fitted to the feed with the slide's words over every frame. With a reference
        video (§ request 2026-10-19) a Seedance 2.x model follows its camera and rhythm —
        the scene goes as reference image 1, since ModelArk does not mix a first frame
        with references."""
        fitter = self._require_fitter()
        number = position + 1
        ratio = SEEDANCE_RATIOS[brief.format]
        motion = carousel_motion_prompt(brief)
        resolution = self._seedance_resolution
        request_params: dict[str, Any] = {
            "ratio": ratio,
            "duration_seconds": seconds,
            "generate_audio": False,
        }
        if reference_video_key:
            model = self._seedance_reference_model
            if not model:
                raise _MediaFailed(
                    FailureReason.INVALID_PARAMETERS.value,
                    "El video de referencia necesita un modelo de video que lo acepte, y no "
                    "hay uno configurado.",
                )
            if resolution not in seedance_family(model).resolutions:
                resolution = "720p"
            motion = (
                f"{motion} Image 1 is the scene: keep its content, product and look. Follow "
                "the camera movement, pacing and rhythm of the reference video, not its "
                "content."
            )
            request_params.update(
                model=model,
                reference_images=[_data_url(scene)],
                reference_videos=self._reference_urls(tenant_id, (reference_video_key,)),
            )
        else:
            request_params["first_frame"] = _data_url(scene)
        request_params.update(prompt=motion, resolution=resolution)
        request = GenerationRequest(
            task=GenerationTask.SCENE_VIDEO,
            rendered_prompt=RenderedPrompt("", "", ""),
            params=request_params,
        )
        trace.media_request(
            draft_id=draft_id,
            provider="Seedance",
            what=f"video de la diapositiva {number}/{total}",
            fields={
                "prompt de movimiento": motion,
                "video de referencia": "sí" if reference_video_key else "no",
                "formato": f"{ratio} · {resolution}",
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
        resolution = str(payload.get("resolution") or resolution)
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
            ai_generated=True,
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

    def _stock_videos(self, brief: ContentBrief) -> dict[int, bytes]:
        """The stock video behind every `STOCK` slide, by slide position — read before
        any provider is paid. Only a stock key (`t/{tenant}/stock/…`, ownership already
        checked by `_key_problems`) is taken; a file gone from R2 fails the carousel."""
        found: dict[int, bytes] = {}
        for position, slide in enumerate(brief.media.slides):
            if slide.source is not SlideSource.STOCK:
                continue
            number = position + 1
            key = slide.object_key or ""
            try:
                if not is_stock_key(key):
                    raise ValueError("not a stock key")
                found[position] = self._store.read(key)
            except Exception as exc:  # R2 down, the object retired, a forged key
                logger.warning("carousel slide %s: stock video unreadable: %s", number, exc)
                raise _MediaFailed(
                    FailureReason.ROUTE_BLOCKED_BY_POLICY.value, _MISSING_STOCK.format(n=number)
                ) from exc
        return found

    def _stock_slide(
        self,
        brief: ContentBrief,
        kit: BrandKit,
        copy: CopyPayload,
        slide: CarouselSlide,
        data: bytes,
        position: int,
        logo: bytes | None,
        save: _Saver,
    ) -> MediaWrite:
        """A stock video fitted to the format with the slide's words and the brand's
        logo over every frame (`compose.text_layer`) — a new work, never the stock file
        as it is (plan-integracion-stock §5.2). Composed here, no model involved."""
        number = position + 1
        size = brief.format.dimensions
        hook = copy.hook if slide.text is SlideText.HOOK else ""
        cta = copy.cta if slide.text is SlideText.CTA else ""
        overlay = text_layer(size=size, hook=hook, cta=cta, palette=kit.palette_rgb, logo=logo)
        fitted = self._require_fitter().fit(data, size=size, overlay=overlay)
        key = save(f"slide-{number}.mp4", fitted.data, MP4)
        params: dict[str, Any] = {
            "slide": number,
            "source": SlideSource.STOCK.value,
            "text": slide.text.value,
            "from_key": slide.object_key,
            "duration_seconds": round(fitted.duration_sec, 2),
        }
        if fitted.poster:
            params["thumbnail_key"] = save(
                f"slide-{number}-poster.jpg", to_meta_jpeg(fitted.poster), JPEG
            )
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
        port = template_port(manifest, brief.format, video=brief.wants_template_video)
        if port is None:
            raise _MediaFailed(
                FailureReason.INVALID_PARAMETERS.value,
                f"la plantilla «{manifest.name}» no tiene "
                f"{'video' if brief.wants_template_video else 'imagen'} en {brief.format.value}",
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

    # -- the talking presenter over ByteDance (§ request 2026-10-16) ---------------------

    def _omnihuman_video(
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
        """Seedream composes the presenter (described, or the operator's image) with the
        products and the background; Seed Speech reads the exact script in the chosen
        voice — the brand's own clone or a public one, resolved HERE, never taken from
        the browser — and OmniHuman makes the presenter say it, lips in sync. The photo
        and the voice reach OmniHuman as public-media token URLs (it takes no Base64);
        its result URL lives one hour, so the video is copied at once."""
        # before anything is paid for: OmniHuman fetches the photo and the voice from a
        # public URL, so without one every step after this would be money lost
        if not _links_ready(self._reference_links):
            raise _MediaFailed(FailureReason.INVALID_PARAMETERS.value, AVATAR_NO_PUBLIC_URL)
        assert self._reference_links is not None
        if self._voices is None:
            raise _MediaFailed(
                FailureReason.PROVIDER_ERROR.value, UNAVAILABLE_TEXT, raw="no voice resolver"
            )
        media = brief.media
        script = (
            media.own_script.strip() or copy.script or f"{copy.hook} {copy.caption} {copy.cta}"
        ).strip()
        if len(script) > SCRIPT_MAX:
            script = fit_text(script, SCRIPT_MAX)
        # the voice first: a voice this brand may not use is refused before any spend
        try:
            voice = self._voices(
                tenant_id=tenant_id,
                brand_id=brief.brand_id,
                choice=media.voice_id or default_public_voice(),
            )
        except VoiceRefused as exc:
            raise _MediaFailed(FailureReason.ROUTE_BLOCKED_BY_POLICY.value, str(exc)) from exc

        # 1. the presenter, composed by Seedream
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
            what="presentador del video",
        )
        presenter = to_meta_jpeg(frame)
        frame_key = save("presenter.jpg", presenter, JPEG)

        # 2. the voice, read by Seed Speech
        trace.media_request(
            draft_id=draft_id,
            provider="Seed Speech",
            what="voz del video",
            fields={
                "guion (lo que dice el presentador)": script,
                "voz": "la de la marca" if voice.brand_clone else voice.speaker,
            },
        )
        spoken = self._run(
            tenant_id=tenant_id,
            brand_id=brief.brand_id,
            link=SEED_SPEECH,
            request=GenerationRequest(
                task=GenerationTask.VOICEOVER,
                rendered_prompt=RenderedPrompt("", "", ""),
                params={
                    "text": script,
                    "speaker": voice.speaker,
                    "resource_id": voice.resource_id,
                    "language": voice.language,
                },
            ),
            budget=budget,
            usage=usage,
            failure_text=avatar_failure_text,
        )
        audio = bytes(spoken.payload) if isinstance(spoken.payload, bytes | bytearray) else b""
        characters = int(spoken.usage.input_tokens)
        usage.append(
            MediaUsage(
                provider=spoken.provider,
                model_id=spoken.model_id,
                unit="character",
                quantity=characters,
                cost_usd=speech_cost_usd(self._pricing, spoken.model_id, characters),
            )
        )
        if voice.brand_clone and voice.charges_slot:
            # the clone's first real synthesis: BytePlus charges its post-paid slot now
            usage.append(
                MediaUsage(
                    provider=spoken.provider,
                    model_id=VOICE_SLOT_MODEL,
                    unit="piece",
                    quantity=1,
                    cost_usd=self._pricing.unit_price(model_id=VOICE_SLOT_MODEL, unit="per_piece"),
                )
            )
        if voice.brand_clone and self._on_brand_voice_used is not None:
            # the first real synthesis fixes the voice (Seed Speech charges its slot)
            try:
                self._on_brand_voice_used(tenant_id, brief.brand_id, voice.speaker)
            except Exception as exc:  # the stamp is bookkeeping; the video goes on
                logger.warning("brand voice activation not stamped: %s", type(exc).__name__)
        voice_key = save("voice.mp3", audio, MP3)
        seconds = _audio_seconds(audio) or len(script) / _CHARS_PER_SECOND
        if seconds > self._omnihuman_max_seconds:
            raise _MediaFailed(
                FailureReason.INVALID_PARAMETERS.value,
                AVATAR_SCRIPT_TOO_LONG,
                raw=f"voice track {seconds:.1f}s > {self._omnihuman_max_seconds}s",
            )

        # 3. the talking video, by OmniHuman
        try:
            image_url = self._reference_links(
                tenant_id=tenant_id, key=frame_key, data=presenter, content_type=JPEG
            )
            audio_url = self._reference_links(
                tenant_id=tenant_id, key=voice_key, data=audio, content_type=MP3
            )
        except Exception as exc:  # R2 or the public-media config
            raise _MediaFailed(
                FailureReason.INVALID_PARAMETERS.value,
                AVATAR_NO_PUBLIC_URL,
                raw=f"{type(exc).__name__}: {exc}",
            ) from exc
        motion = motion_prompt(brief=brief, products=len(products))
        trace.media_request(
            draft_id=draft_id,
            provider="OmniHuman",
            what="video con avatar",
            fields={
                "prompt de gestos": motion,
                "duración de la voz": f"{seconds:.1f} s",
                "resolución": f"{self._omnihuman_resolution}p",
            },
        )
        billed = Decimal(str(round(seconds, 2)))
        try:
            result = self._run(
                tenant_id=tenant_id,
                brand_id=brief.brand_id,
                link=OMNIHUMAN,
                request=GenerationRequest(
                    task=GenerationTask.AVATAR_VIDEO,
                    rendered_prompt=RenderedPrompt("", "", ""),
                    params={
                        "image_url": image_url,
                        "audio_url": audio_url,
                        "prompt": motion,
                        "resolution": self._omnihuman_resolution,
                        "audio_seconds": round(seconds, 2),
                    },
                ),
                budget=budget,
                usage=usage,
                failure_text=avatar_failure_text,
            )
        except _MediaFailed as exc:
            if "OmniHumanTimeout" in (exc.raw or ""):
                # the window closed but the render goes on — and is billed when it ends:
                # record what it will cost, so the budget is not blind to it
                usage.append(
                    MediaUsage(
                        provider=OMNIHUMAN,
                        model_id=MODEL_IDS.get(self._omnihuman_req_key, self._omnihuman_req_key),
                        unit="second",
                        quantity=math.ceil(seconds),
                        cost_usd=omnihuman_cost_usd(
                            self._pricing,
                            self._omnihuman_req_key,
                            self._omnihuman_resolution,
                            billed,
                        ),
                    )
                )
                logger.warning("omnihuman timed out, billed render recorded: %s", exc.raw)
            raise
        payload = dict(result.payload) if isinstance(result.payload, dict) else {}
        req_key = str(payload.get("req_key") or result.model_revision or "")
        usage.append(
            MediaUsage(
                provider=result.provider,
                model_id=result.model_id,
                unit="second",
                quantity=math.ceil(seconds),
                cost_usd=omnihuman_cost_usd(
                    self._pricing,
                    req_key,
                    int(payload.get("resolution") or self._omnihuman_resolution),
                    billed,
                ),
            )
        )
        video_key = save("video.mp4", self._download(str(result.media_url)), MP4)
        width, height = brief.format.dimensions
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
                ai_generated=True,
                params={
                    "task_id": payload.get("task_id"),
                    "duration_seconds": round(seconds, 2),
                    "resolution": payload.get("resolution"),
                    "avatar_source": media.avatar_source.value if media.avatar_source else None,
                    # provenance of the voice: which one read it, never another brand's id
                    "voice": "brand" if voice.brand_clone else "public",
                    "voice_id": None if voice.brand_clone else voice.speaker,
                    "voice_resource": voice.resource_id,
                    "voice_key": voice_key,
                    "thumbnail_key": frame_key,
                    "model_revision": result.model_revision,
                },
            )
        ]


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


#: How much of the «Datos clave» JSON (§ request 2026-10-14) goes into a media prompt:
#: the facts that fit, in the operator's order — the vendor's cap is 3,000 characters.
_FACTS_MAX = 500

#: What a media prompt does with the facts: an image or a clip never draws them (the
#: words are laid over afterwards, or the post carries them) — they shape what is shown.
_FACTS_IN_IMAGE = (
    "Let them shape what the scene shows (a 2x1 shows two, a weekend offer feels like a"
    " weekend) — never draw them: the words are laid over afterwards."
)
_FACTS_IN_CLIP = (
    "Let them shape the story — what is shown and how urgent it feels — never write them"
    " on screen: the post's text carries them."
)
_FACTS_IN_MOTION = "The presenter's words carry them; let the gestures and the product shown match."


def _facts_line(brief: ContentBrief, use: str) -> str:
    """«Datos clave» as the JSON the operator's facts are (§ request 2026-10-14): every
    prompt gets them, each told what to do with them. "" without facts."""
    data: dict[str, str] = {}
    for name, fact in brief.constraints.highlights:
        candidate = {**data, name: fact}
        if len(json.dumps(candidate, ensure_ascii=False)) > _FACTS_MAX:
            break
        data = candidate
    if not data:
        return ""
    facts = json.dumps(data, ensure_ascii=False)
    return f"Key facts of this offer (the client's own data, as JSON): {facts}. {use}"


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
    order: the product photos first, the background (the operator's place) last. With
    no photo at all (`AdImageMode.SCENE`) the scene is invented from the words."""
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
    elif not products and not has_background:
        lines.append(
            "There are no reference images: compose the product and the setting from the "
            "scene described below, plausible for this brand."
        )
    if brief.media.scene_prompt.strip():
        scene = _quoted(brief.media.scene_prompt)
        lines.append(f'Scene the client asked for (in Spanish): "{scene}".')
    lines.append(f'The post is about (in Spanish): "{_quoted(brief.topic, _PROMPT_TOPIC_MAX)}".')
    lines.append(_facts_line(brief, _FACTS_IN_IMAGE))
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
    lines.append(_facts_line(brief, _FACTS_IN_IMAGE))
    if has_text:
        lines.append(
            "Keep the top quarter and the bottom fifth of the frame calm and uncluttered: "
            "a headline or a button is laid over them afterwards."
        )
    lines.append(_palette_line(kit))
    lines.append(_NO_TEXT)
    return " ".join(line for line in lines if line)


def carousel_motion_prompt(brief: ContentBrief | None = None) -> str:
    """What Seedance does with a carousel slide's scene: a short, silent, product-led
    shot — nobody talks, nothing is written. The «Datos clave» ride along (2026-10-14)."""
    lines = [
        "Bring this photograph to life as a short cinematic product shot: a slow, smooth "
        "camera move (gentle push-in or slight orbit), subtle natural motion in the scene "
        "(steam, light, a hand, the background), the product keeps its exact look and "
        "label. Nobody talks to the camera. No text on screen.",
        _facts_line(brief, _FACTS_IN_CLIP) if brief is not None else "",
    ]
    return " ".join(line for line in lines if line)


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
    lines.append(_facts_line(brief, _FACTS_IN_IMAGE))
    lines.append(_palette_line(kit))
    lines.append(_NO_TEXT)
    return " ".join(line for line in lines if line)


#: What each clip reference image is told to be (§ request 2026-10-14), by its role.
_CLIP_ROLE_LINES = {
    "product": "the client's real product — keep it exactly as it is (shape, colors, label)",
    "place": "the client's real place — the story happens there, keep it recognisable",
    "style": "a style reference — borrow its look, light, framing and mood, not its content",
}
#: How long each shot's description may be in the prompt.
_SHOT_MAX = 260


def _numbered(numbers: list[int]) -> str:
    if len(numbers) == 1:
        return f"Image {numbers[0]}"
    return "Images " + ", ".join(str(n) for n in numbers[:-1]) + f" and {numbers[-1]}"


def _story_lines(copy: CopyPayload | None, seconds: int) -> list[str]:
    """The clip's story (§ request 2026-10-14: «el clip cuenta una historia» and «los
    ganchos ya se tienen, quiero usarlos»): the copy's own three shots — hook,
    development, payoff — timed to the clip; without them, the same three beats built
    on the copy's hook and CTA."""
    shots = [shot for shot in (copy.shots if copy else ()) if shot.visual.strip()][:4]
    lines: list[str] = []
    if copy and copy.hook.strip():
        lines.append(
            "It opens on this hook, shown — never written (in Spanish): "
            f'"{_quoted(copy.hook, 160)}".'
        )
    if shots:
        total = sum(shot.seconds for shot in shots) or 1
        lines.append("The story, shot by shot (in Spanish):")
        start = 0
        for number, shot in enumerate(shots, 1):
            end = seconds if number == len(shots) else round(start + shot.seconds * seconds / total)
            lines.append(f'Shot {number} ({start}-{end} s): "{_quoted(shot.visual, _SHOT_MAX)}".')
            start = end
        return lines
    hook_end = max(2, round(seconds * 0.2))
    middle_end = max(hook_end + 2, round(seconds * 0.7))
    cta = copy.cta.strip() if copy else ""
    lines.extend(
        (
            f"Shot 1 (0-{hook_end} s): the hook — the moment that makes people stop scrolling.",
            f"Shot 2 ({hook_end}-{middle_end} s): the development — the product in action and "
            "what it gives.",
            f"Shot 3 ({middle_end}-{seconds} s): the payoff — the product as the hero"
            + (
                f', leading to the call to action (in Spanish): "{_quoted(cta, 120)}".'
                if cta
                else "."
            ),
        )
    )
    return lines


def clip_prompt(
    *,
    brief: ContentBrief,
    kit: BrandKit,
    first_frame: bool,
    last_frame: bool,
    images: int,
    videos: int,
    audios: int,
    copy: CopyPayload | None = None,
    image_roles: tuple[str, ...] = (),
) -> str:
    """What a clip is asked for (§ 2026-10-14): an advertising video that tells a story
    in three shots on the copy's hook, each reference named by the number the API gives
    it and told its role (the product, the place, a style), the «Datos clave», the
    palette. With references, the frames are the first reference images and the prompt
    says so (ModelArk's documented way: «the opening frame is Image 1»)."""
    ratio = SEEDANCE_RATIOS[brief.format]
    seconds = brief.media.duration_seconds
    topic_max = 300 if copy and copy.shots else _PROMPT_TOPIC_MAX
    lines = [
        f"A {_ORIENTATION.get(ratio, ratio)} advertising video for social media that tells a "
        "short story, cinematic and well lit, with no presenter talking to the camera.",
        f'It is about (in Spanish): "{_quoted(brief.topic, topic_max)}".',
    ]
    if brief.product_ref:
        lines.append(
            f'It shows the client\'s real product, "{_quoted(brief.product_ref, 120)}", '
            "exactly as it is: shape, colors, label."
        )
    lines.extend(_story_lines(copy, seconds))
    references = images or videos or audios
    if references:
        index = 1
        if first_frame:
            lines.append(f"The opening frame is Image {index}.")
            index += 1
        if last_frame:
            lines.append(f"The closing frame is Image {index}.")
            index += 1
        if images:
            roles = list(image_roles) if len(image_roles) == images else ["product"] * images
            by_role: dict[str, list[int]] = {}
            for offset, role in enumerate(roles):
                by_role.setdefault(role if role in _CLIP_ROLE_LINES else "product", []).append(
                    index + offset
                )
            for role, numbers in by_role.items():
                lines.append(f"{_numbered(numbers)}: {_CLIP_ROLE_LINES[role]}.")
        if videos:
            named = "Video 1" if videos == 1 else f"Videos 1 to {videos}"
            lines.append(
                f"Refer to the camera movement, motion and pacing of {named}, keeping the "
                "motion details consistent, with the client's product and scene."
            )
        if audios:
            named = "Audio 1" if audios == 1 else f"Audios 1 to {audios}"
            lines.append(f"Use {named} as the soundtrack and match the rhythm to it.")
    elif first_frame and last_frame:
        lines.append(
            "It moves from the opening frame (shot 1) to the closing frame (the last shot)."
        )
    elif first_frame:
        lines.append("It starts on the opening frame and brings it to life.")
    lines.append(_facts_line(brief, _FACTS_IN_CLIP))
    lines.append(_palette_line(kit))
    lines.append("No text on screen.")
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
    lines.append(_facts_line(brief, _FACTS_IN_MOTION))
    return " ".join(line for line in lines if line)


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
