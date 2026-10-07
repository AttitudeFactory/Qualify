"""The one place the real creative implementations get wired together — same contract
as ``connections/composition.py``: one function to audit, cached because callers arrive
per request/event, and nothing here does network work at import or compose time.

D4 (design §4.1): only the PLATFORM credential path exists in the MVP — Qualify pays,
the key comes from the process environment: ``QUALIFY_ANTHROPIC_API_KEY`` for copy and
``QUALIFY_HEYGEN_API_KEY`` for the avatar videos (one env var per provider). The resolver
raises ``MissingPlatformKey`` at RESOLVE time, not at import or compose time, so a
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
from functools import cache
from pathlib import Path
from uuid import UUID

from qualify_creative.adapters.anthropic_copy import AnthropicCopyAdapter
from qualify_creative.adapters.heygen_video import HeyGenAvatarVideoAdapter
from qualify_creative.enums import PaidBy
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import ResolvedKey
from qualify_creative.render.adapter import RemotionTemplateAdapter
from qualify_creative.render.client import RemotionRenderClient
from qualify_creative.render.registry import TemplateRegistry
from qualify_creative.router import CreativeRouter
from qualify_creative.schemas import BrandKit, BrandVoiceProfile

from qualify_api.catalog.read import DbProductCatalog
from qualify_api.creative.brand_context import DbBrandContextReader
from qualify_api.creative.brand_names import DbBrandNames
from qualify_api.creative.brand_service import BrandKitService
from qualify_api.creative.dispatch import InlineDispatcher
from qualify_api.creative.media import LocalMediaStore, MediaProducer, R2ReadingMediaStore
from qualify_api.creative.service import ContentService
from qualify_api.creative.voice_access import BrandVoiceGuard
from qualify_api.creative.voice_service import VoiceProfileService

logger = logging.getLogger(__name__)

#: The environment variable carrying the platform's Anthropic key (D4: Qualify pays).
PLATFORM_KEY_ENV = "QUALIFY_ANTHROPIC_API_KEY"
#: One platform key per provider. Before the video lane every provider got the Anthropic
#: key, which would have handed it to HeyGen.
PROVIDER_KEY_ENVS = {"anthropic": PLATFORM_KEY_ENV, "heygen": "QUALIFY_HEYGEN_API_KEY"}
#: The Remotion render service (packages/render, CONTRACT.md §4). `just up` starts it in
#: compose on 3200; in the VPS it is the same container next to the app.
RENDER_URL_ENV = "QUALIFY_RENDER_URL"
DEFAULT_RENDER_URL = "http://localhost:3200"

#: v2 carries the HeyGen per-second rates (and everything v1 had).
PRICING_VERSION = "v2"

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
    heygen = HeyGenAvatarVideoAdapter()
    # the brand's logo may live in R2 (Brand Kit, 2026-10-01): read it there
    store = R2ReadingMediaStore(LocalMediaStore(media_root()))
    remotion = RemotionTemplateAdapter(
        RemotionRenderClient(os.environ.get(RENDER_URL_ENV) or DEFAULT_RENDER_URL),
        read_media=store.read,
    )
    router = CreativeRouter(
        providers={"anthropic": AnthropicCopyAdapter(), "heygen": heygen, "remotion": remotion},
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
            heygen=heygen,
            # a brand renders only in its own cloned voice or a public one (§ 2026-10-05)
            voice_guard=BrandVoiceGuard(heygen),
            # the template engine (plan-mvp-plantillas-remotion.md §2): the published
            # manifests in packages/render/templates, the render service over HTTP, the
            # brand's name for the composition and the catalog's products
            remotion=remotion,
            templates=TemplateRegistry.from_dir(),
            brand_names=DbBrandNames(),
            catalog=DbProductCatalog(),
        ),
    )
    service.dispatcher = InlineDispatcher(service.run_generation)
    return service
