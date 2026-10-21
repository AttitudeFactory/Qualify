"""The one place the real creative implementations get wired together — same contract
as ``connections/composition.py``: one function to audit, cached because callers arrive
per request/event, and nothing here does network work at import or compose time.

D4 (design §4.1): only the PLATFORM credential path exists in the MVP — Qualify pays,
the key comes from the process environment: ``QUALIFY_ANTHROPIC_API_KEY`` for copy,
``QUALIFY_BYTEPLUS_ARK_API_KEY`` for Seedream and Seedance, and — the talking presenter
since 2026-10-16, HeyGen retired — ``QUALIFY_BYTEPLUS_SPEECH_API_KEY`` for Seed Speech (the
voice) and ``QUALIFY_BYTEPLUS_CV_API_KEY`` for OmniHuman (one env var per vendor product).
The resolver raises ``MissingPlatformKey`` at RESOLVE time, not at import or compose time, so a
process without the key can still serve every read path and fails loudly exactly when a
generation is attempted.

The DB-backed kit/voice readers below are interim wiring: they satisfy the
``BrandService`` / ``VoiceService`` Protocols by reading the MC-01 tables through
``tenant_session`` and mapping rows onto the pure ``qualify_creative`` schemas. When the
dedicated ``BrandKitService`` / ``VoiceProfileService`` land, they replace these here —
one file, no service change.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from qualify_creative.adapters.anthropic_copy import AnthropicCopyAdapter
from qualify_creative.adapters.byteplus_ark import (
    BASE_URL as ARK_BASE_URL,
)
from qualify_creative.adapters.byteplus_ark import (
    DEFAULT_SEEDANCE_MODEL,
    DEFAULT_SEEDREAM_MODEL,
    SeedanceVideoAdapter,
    SeedreamImageAdapter,
    seedance_family,
)
from qualify_creative.adapters.byteplus_omnihuman import (
    API_KEY_ENV as OMNIHUMAN_KEY_ENV,
)
from qualify_creative.adapters.byteplus_omnihuman import (
    DEFAULT_POLL_TIMEOUT_SECONDS as OMNIHUMAN_POLL_TIMEOUT_SECONDS,
)
from qualify_creative.adapters.byteplus_omnihuman import (
    DEFAULT_REQ_KEY as DEFAULT_OMNIHUMAN_REQ_KEY,
)
from qualify_creative.adapters.byteplus_omnihuman import (
    MAX_AUDIO_SECONDS as OMNIHUMAN_MAX_AUDIO_SECONDS,
)
from qualify_creative.adapters.byteplus_omnihuman import (
    REQ_KEY_ENV as OMNIHUMAN_REQ_KEY_ENV,
)
from qualify_creative.adapters.byteplus_omnihuman import (
    OmniHumanVideoAdapter,
)
from qualify_creative.adapters.byteplus_speech import API_KEY_ENV as SPEECH_KEY_ENV
from qualify_creative.adapters.byteplus_speech import SeedSpeechVoiceoverAdapter
from qualify_creative.angles import AngleBrand, AnglePreset, AngleProduct, CreativeAngle
from qualify_creative.enums import PaidBy
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import ResolvedKey
from qualify_creative.render.adapter import RemotionTemplateAdapter
from qualify_creative.render.client import RemotionRenderClient
from qualify_creative.render.registry import TemplateRegistry
from qualify_creative.router import CreativeRouter
from qualify_creative.schemas import BrandKit, BrandVoiceProfile
from qualify_creative.video import PyAvVideoFitter

from qualify_api.catalog.read import DbProductCatalog
from qualify_api.claude_tools import CallStats
from qualify_api.creative.brand_context import DbBrandContextReader
from qualify_api.creative.brand_names import DbBrandNames
from qualify_api.creative.brand_service import BrandKitService
from qualify_api.creative.dispatch import InlineDispatcher
from qualify_api.creative.media import LocalMediaStore, MediaProducer, R2ReadingMediaStore
from qualify_api.creative.observed import traced_providers
from qualify_api.creative.pieces import DbPieceFiles
from qualify_api.creative.service import ContentService
from qualify_api.creative.voice_access import BrandVoiceResolver
from qualify_api.creative.voice_clone import VoiceCloneService
from qualify_api.creative.voice_service import VoiceProfileService

if TYPE_CHECKING:
    # `angle_sets` imports `catalog.service`, which imports this package: loaded at
    # call time in `production_angle_set_service`, like `CatalogService`
    from qualify_api.creative.angle_sets import AngleSetService

logger = logging.getLogger(__name__)

#: The environment variable carrying the platform's Anthropic key (D4: Qualify pays).
PLATFORM_KEY_ENV = "QUALIFY_ANTHROPIC_API_KEY"
#: One platform key per provider. Before the video lane every provider got the Anthropic
#: key, which would have handed it to another vendor.
#: Seedream and Seedance are two router links over ONE BytePlus ModelArk key; Seed Speech
#: and OmniHuman are other BytePlus products, each with its own key (§ 2026-10-16).
ARK_KEY_ENV = "QUALIFY_BYTEPLUS_ARK_API_KEY"
PROVIDER_KEY_ENVS = {
    "anthropic": PLATFORM_KEY_ENV,
    "seedream": ARK_KEY_ENV,
    "seedance": ARK_KEY_ENV,
    "seed_speech": SPEECH_KEY_ENV,
    "omnihuman": OMNIHUMAN_KEY_ENV,
}
#: OmniHuman's output resolution (720 | 1080; 1.5 bills both the same per second).
OMNIHUMAN_RESOLUTION_ENV = "QUALIFY_OMNIHUMAN_RESOLUTION"
#: BytePlus ModelArk (§ request 2026-10-07): the regional base URL and the models. The
#: defaults are the founder's test pair — Seedance 1.0 pro (silent video) and Seedream
#: 5.0 lite; a 2.x Seedance model id here makes the avatar speak its script.
ARK_BASE_URL_ENV = "QUALIFY_BYTEPLUS_ARK_BASE_URL"
SEEDANCE_MODEL_ENV = "QUALIFY_SEEDANCE_MODEL"
SEEDREAM_MODEL_ENV = "QUALIFY_SEEDREAM_MODEL"
#: Seedance's output resolution: 720p by default (1.0 pro bills the same per token at
#: every resolution, so 1080p is ~2.4x the cost of 720p for the same seconds).
SEEDANCE_RESOLUTION_ENV = "QUALIFY_SEEDANCE_RESOLUTION"
#: The model a clip with references runs on (§ 2026-10-14): only Seedance 2.x takes
#: them, and 2.0 mini is the cheapest (docs read 2026-10-14). Activating 2.x on the
#: account needs a balance over USD 30.
SEEDANCE_REFERENCE_MODEL_ENV = "QUALIFY_SEEDANCE_REFERENCE_MODEL"
DEFAULT_SEEDANCE_REFERENCE_MODEL = "dreamina-seedance-2-0-mini-260615"


PUBLIC_MEDIA_BASE_URL_ENV = "QUALIFY_PUBLIC_MEDIA_BASE_URL"
#: How long a reference link stays fetchable. Meta's 15 min (`TOKEN_TTL_SECONDS`) is too
#: short here: OmniHuman runs one task at a time, so a queued presenter may download its
#: photo and voice long after it was submitted — its whole poll window plus a margin.
REFERENCE_LINK_TTL_SECONDS = int(OMNIHUMAN_POLL_TIMEOUT_SECONDS) + 20 * 60
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def public_media_ready() -> bool:
    """Whether a vendor on the internet can fetch a reference link: an ``https`` public
    base URL (never localhost — a vendor cannot reach it) and R2 configured. Read before
    anything is paid for, so a missing tunnel fails as a setting, not after a spend."""
    from urllib.parse import urlparse

    from qualify_shared.objects.config import R2Settings

    parsed = urlparse(os.environ.get(PUBLIC_MEDIA_BASE_URL_ENV, "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    if host in _LOCAL_HOSTS or host.endswith(".localhost"):
        return False
    try:
        R2Settings.from_env()
    except Exception:  # noqa: BLE001 — any missing R2 setting means "not ready"
        return False
    return True


class PublicReferenceLinks:
    """A clip's reference video/audio, or the presenter's photo and voice, as a URL the
    vendor can fetch (neither ModelArk nor OmniHuman takes Base64 for them): the bytes go
    under the tenant's R2 prefix and a public-media token points at them — the same door
    QUA-68 opened for Meta's image fetcher, never a presigned R2 URL (ADR 28e). Built
    lazily: R2 and the public base URL are only required when a piece actually carries
    such a reference."""

    def __init__(self, *, ttl_seconds: int = REFERENCE_LINK_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds

    def ready(self) -> bool:
        return public_media_ready()

    def __call__(self, *, tenant_id: UUID, key: str, data: bytes, content_type: str) -> str:
        import hashlib
        import io

        import redis
        from qualify_shared.objects.config import R2Settings
        from qualify_shared.objects.gate import ObjectGate
        from qualify_shared.objects.keys import tenant_prefix
        from qualify_shared.objects.s3 import R2ObjectStore

        from qualify_api.config import PublicMediaSettings, redis_url
        from qualify_api.publishing.media_token import MediaTokenStore

        settings = PublicMediaSettings.from_env()
        gate = ObjectGate(R2ObjectStore(R2Settings.from_env()))
        digest = hashlib.sha256(data).hexdigest()[:32]
        suffix = key.rsplit(".", 1)[-1].lower() if "." in key else "bin"
        object_key = f"{tenant_prefix(tenant_id)}creative-refs/{digest}.{suffix}"
        gate.put_media(tenant_id, object_key, io.BytesIO(data), content_type)
        tokens = MediaTokenStore(
            redis.Redis.from_url(redis_url(), decode_responses=True), ttl_seconds=self._ttl
        )
        token = tokens.issue(tenant_id=tenant_id, object_key=object_key, content_type=content_type)
        return settings.public_media_url(token)


DEFAULT_SEEDANCE_RESOLUTION = "720p"
#: The Remotion render service (packages/render, CONTRACT.md §4). `just up` starts it in
#: compose on 3200; in the VPS it is the same container next to the app.
RENDER_URL_ENV = "QUALIFY_RENDER_URL"
DEFAULT_RENDER_URL = "http://localhost:3200"

#: v4 (2026-10-13) adds claude-opus-5-5 — the copy model since that day — and
#: claude-opus-4-8, a server-side fallback target, to everything v3 had (v3 added the
#: BytePlus ModelArk rates). v5 (2026-10-16) adds OmniHuman and Seed Speech — the talking
#: presenter after HeyGen. A published version is never edited.
PRICING_VERSION = "v5"

#: Where uploads and generated media live — the app's upload directory, the same one
#: Reflex serves (`rx.get_upload_dir()`, overridable with `REFLEX_UPLOADED_FILES_DIR`).
MEDIA_DIR_ENV = "REFLEX_UPLOADED_FILES_DIR"


def media_root() -> Path:
    return Path(os.environ.get(MEDIA_DIR_ENV) or "uploaded_files")


class MissingPlatformKey(Exception):
    """The platform key is absent from the environment at resolve time."""


class PlatformKeyResolver:
    """``CredentialResolver`` for D4: every brand resolves to the ONE platform key, and
    every usage event it produces is marked ``paid_by=platform`` so the subsidy is
    measured rather than invisible. The env var is read per resolve, never cached at
    construction — rotating the key is an env change plus nothing."""

    def resolve(self, *, tenant_id: UUID, brand_id: UUID, provider: str) -> ResolvedKey:
        env = PROVIDER_KEY_ENVS.get(provider)
        if env is None:
            raise MissingPlatformKey(f"no platform key is configured for provider {provider!r}")
        raw = os.environ.get(env, "").strip()
        if not raw:
            raise MissingPlatformKey(
                f"{env} is not set. The MVP runs on the platform's {provider} key (D4 — "
                "Qualify pays for generation); export it in this process's environment "
                "to enable this kind of generation. Read paths work without it."
            )
        fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        return ResolvedKey(api_key=raw, paid_by=PaidBy.PLATFORM, fingerprint=fingerprint)


class DbBrandKitReader:
    """``BrandService`` adapter over the real ``BrandKitService`` (MC-02). The interim
    row-mapping that used to live here is gone: two rehydration implementations of the
    same kit is exactly the drift the integration pass kept catching, so the single
    mapping now lives in ``brand_service.kit_from_row`` and this class only bridges the
    method-name gap between the narrow ``BrandService`` Protocol (``kit``) and the full
    service (``get_kit``)."""

    def __init__(self) -> None:
        self._service = BrandKitService()

    def kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit | None:
        return self._service.get_kit(tenant_id=tenant_id, brand_id=brand_id)


class DbVoiceProfileReader:
    """``VoiceService`` adapter over the real ``VoiceProfileService`` — same rationale as
    ``DbBrandKitReader``."""

    def __init__(self) -> None:
        self._service = VoiceProfileService()

    def active(self, *, tenant_id: UUID, brand_id: UUID) -> BrandVoiceProfile | None:
        return self._service.active_profile(tenant_id=tenant_id, brand_id=brand_id)


def _check_seedance(model: str, resolution: str) -> None:
    """Refuse a Seedance model / resolution pair the family cannot render HERE, at wiring
    (PR #100 review): left to the pre-flight, a typo in the env var or `-fast` + `1080p`
    would fail every video while the service came up fine."""
    family = seedance_family(model)  # raises on an unknown family
    if resolution not in family.resolutions:
        raise ValueError(
            f"{SEEDANCE_RESOLUTION_ENV}={resolution!r} is not one {model} renders: "
            f"{sorted(family.resolutions)}"
        )


def _stamp_brand_voice(tenant_id: UUID, brand_id: UUID, voice_id: str) -> None:
    VoiceCloneService().mark_activated(tenant_id=tenant_id, brand_id=brand_id, voice_id=voice_id)


@cache
def production_content_service() -> ContentService:
    """Wire the real router (Anthropic copy adapter, v1 pricing, platform key), the
    Postgres repository (the service's default), the DB kit/voice readers and the
    ``InlineDispatcher``, once.

    The dispatcher is wired POST-construction because it wraps the service's own
    ``run_generation`` — the two-UUID seam §7.4 makes the whole Celery migration.
    """
    pricing = JsonPricingTable(PRICING_VERSION)
    credentials = PlatformKeyResolver()
    omnihuman = OmniHumanVideoAdapter(
        req_key=os.environ.get(OMNIHUMAN_REQ_KEY_ENV) or DEFAULT_OMNIHUMAN_REQ_KEY
    )
    ark_base_url = os.environ.get(ARK_BASE_URL_ENV) or ARK_BASE_URL
    seedream = SeedreamImageAdapter(
        model=os.environ.get(SEEDREAM_MODEL_ENV) or DEFAULT_SEEDREAM_MODEL,
        base_url=ark_base_url,
    )
    seedance_model = os.environ.get(SEEDANCE_MODEL_ENV) or DEFAULT_SEEDANCE_MODEL
    seedance_resolution = os.environ.get(SEEDANCE_RESOLUTION_ENV) or DEFAULT_SEEDANCE_RESOLUTION
    _check_seedance(seedance_model, seedance_resolution)
    seedance = SeedanceVideoAdapter(model=seedance_model, base_url=ark_base_url)
    # the brand's logo may live in R2 (Brand Kit, 2026-10-01): read it there
    store = R2ReadingMediaStore(LocalMediaStore(media_root()))
    remotion = RemotionTemplateAdapter(
        RemotionRenderClient(os.environ.get(RENDER_URL_ENV) or DEFAULT_RENDER_URL),
        read_media=store.read,
    )
    router = CreativeRouter(
        # the models under test are traced in Langfuse (Claude, Seedream, Seedance —
        # not Remotion, 2026-10-13); a no-op without LANGFUSE_* keys
        providers=traced_providers(
            {
                "anthropic": AnthropicCopyAdapter(),
                "seed_speech": SeedSpeechVoiceoverAdapter(),
                "omnihuman": omnihuman,
                "remotion": remotion,
                "seedream": seedream,
                "seedance": seedance,
            },
            pricing,
        ),
        pricing=pricing,
        credentials=credentials,
    )
    service = ContentService(
        router=router,
        pricing=pricing,
        credentials=credentials,
        voice_service=DbVoiceProfileReader(),
        brand_service=DbBrandKitReader(),
        # what the Brand Kit saved beyond the kit (§ 2026-10-01): rubro, location,
        # hashtags, the account, the brandboard's elements, referentes, competitors
        context_reader=DbBrandContextReader(),
        media=MediaProducer(
            store=store,
            router=router,
            credentials=credentials,
            pricing=pricing,
            # the talking presenter (§ 2026-10-16): a brand reads only in its own cloned
            # voice or a public one (§ 2026-10-05), and a clone's first real synthesis
            # is stamped — Seed Speech charges its slot then and fixes the voice
            voices=BrandVoiceResolver(),
            on_brand_voice_used=_stamp_brand_voice,
            omnihuman_resolution=int(os.environ.get(OMNIHUMAN_RESOLUTION_ENV) or 720),
            omnihuman_max_seconds=OMNIHUMAN_MAX_AUDIO_SECONDS[omnihuman.req_key],
            omnihuman_req_key=omnihuman.req_key,
            # the template engine (plan-mvp-plantillas-remotion.md §2): the published
            # manifests in packages/render/templates, the render service over HTTP, the
            # brand's name for the composition and the catalog's products
            remotion=remotion,
            templates=TemplateRegistry.from_dir(),
            brand_names=DbBrandNames(),
            catalog=DbProductCatalog(),
            # § 2026-10-07: the advertising image's scene by Seedream, the avatar videos
            # (VideoEngine.SEEDANCE) by Seedream + Seedance
            generated_ad_images=True,
            seedance_resolution=seedance_resolution,
            # § 2026-10-09: a carousel reuses only THIS brand's pieces, and fits its
            # video slides to the feed with PyAV (no ffmpeg binary in the image)
            pieces=DbPieceFiles(),
            fitter=PyAvVideoFitter(),
            # § 2026-10-14: a clip with references runs on Seedance 2.x, and its
            # video/audio references reach ModelArk through a public-media token URL
            seedance_reference_model=(
                os.environ.get(SEEDANCE_REFERENCE_MODEL_ENV) or DEFAULT_SEEDANCE_REFERENCE_MODEL
            ),
            reference_links=PublicReferenceLinks(),
        ),
    )
    service.dispatcher = InlineDispatcher(service.run_generation)
    return service


# ---------------------------------------------------------------------------
# «10 variaciones» (ticket 24803289): the angle-set service over the content service


class _DbBrandFacts:
    """The brand as the angles prompt needs it: its name (tenancy), its positioning and
    audience and palette (the kit), its rubro and location (the context)."""

    def __init__(self) -> None:
        self._names = DbBrandNames()
        self._kits = DbBrandKitReader()
        self._context = DbBrandContextReader()

    def __call__(self, *, tenant_id: UUID, brand_id: UUID) -> AngleBrand:
        kit = self._kits.kit(tenant_id=tenant_id, brand_id=brand_id)
        try:
            context = self._context.context(tenant_id=tenant_id, brand_id=brand_id)
        except Exception as exc:  # noqa: BLE001 — the context is decoration for the prompt
            logger.info("brand context unreadable for %s: %s", brand_id, type(exc).__name__)
            context = None
        return AngleBrand(
            name=self._names(tenant_id=tenant_id, brand_id=brand_id),
            positioning=kit.positioning if kit is not None else "",
            audience=kit.audience if kit is not None else "",
            sector=context.sector if context is not None else "",
            location=context.location if context is not None else "",
            palette=tuple(kit.palette_rgb) if kit is not None else (),
        )


class _PlatformAngleGenerator:
    """`angles_ai.generate_angles` on the platform's Anthropic key, resolved per call
    (`MissingAPIKey` surfaces as a failed set, never at import or compose time)."""

    def __call__(
        self,
        product: AngleProduct,
        brand: AngleBrand,
        preset: AnglePreset,
        *,
        count: int,
        avoid: Sequence[CreativeAngle] = (),
    ) -> tuple[tuple[CreativeAngle, ...], CallStats, str]:
        from qualify_api.claude_tools import api_key_from_env
        from qualify_api.creative.angles_ai import generate_angles

        return generate_angles(
            product, brand, preset, api_key=api_key_from_env(), count=count, avoid=avoid
        )


class _DbCampaignOps:
    def create(
        self, *, tenant_id: UUID, brand_id: UUID, name: str, created_by: UUID | None
    ) -> UUID:
        from qualify_api.creative.campaigns import create_campaign

        return create_campaign(tenant_id, brand_id, name, created_by=created_by).id

    def assign(self, *, tenant_id: UUID, draft_id: UUID, campaign_id: UUID) -> None:
        from qualify_api.creative.campaigns import set_post_campaign

        set_post_campaign(tenant_id, draft_id, campaign_id)


@cache
def production_angle_set_service() -> AngleSetService:
    """The «10 variaciones» service over the composed content service: the catalog's
    read door, the platform Anthropic key for the angles, the Postgres repository and
    the campaigns module. The image rate shown before generating is Seedream's."""
    from qualify_api.catalog.service import CatalogService
    from qualify_api.creative.angle_sets import AngleSetService, PostgresAngleSetRepository

    return AngleSetService(
        repository=PostgresAngleSetRepository(),
        catalog=CatalogService(store=LocalMediaStore(media_root())),
        brand_facts=_DbBrandFacts(),
        kit_reader=DbBrandKitReader(),
        generator=_PlatformAngleGenerator(),
        drafts=production_content_service(),
        campaigns=_DbCampaignOps(),
        pricing=JsonPricingTable(PRICING_VERSION),
        image_model_id=os.environ.get(SEEDREAM_MODEL_ENV) or DEFAULT_SEEDREAM_MODEL,
    )
