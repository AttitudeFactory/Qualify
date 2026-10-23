"""Production assembly for the Conversaciones module (QUA-226) — the analogue of
`whatsapp/chats.production_chat_service` and `inbox/composition.py`.

## The one switch: which implementation answers for channel `dm`

`QUALIFY_CONVERSATIONS_DM_CHANNEL` selects the pair the `ChannelRegistry` holds for
`CHANNEL_DM`:

- `instagram` (default, and the only value in production): `instagram_source.
  InstagramDirectSource` / `InstagramDirectSender` over the Messenger Platform, with
  credentials resolved per connection through `CredentialResolver` (R3: no token here).
- `memory`: `memory_source.MemoryConversationSource` / `MemoryConversationSender`, the
  second channel of E1. **Development only.** It lets the whole loop — seed → inbox →
  reply → outbox → sender → outbound bubble — run on localhost without Meta and without
  sending anything real (`devseed.py` fills it). It is NOT a simulation of Instagram:
  the UI and the flow are validated, the API is not.

Every other function here is the Postgres wiring: repositories under `tenant_session`,
the sync service, the sender with QUA-90's degrader, and the two connection reads the
adapter and the sender need (ids only).
"""

from __future__ import annotations

import logging
import os
from functools import cache
from typing import Final
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.connections.models import SocialConnection
from qualify_api.connections.resolver import AuthenticatedClient
from qualify_api.conversations.contracts import ChannelRegistry, SourceConnection
from qualify_api.conversations.drafts import PostgresDraftRepository
from qualify_api.conversations.memory_source import (
    MemoryConversationSender,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import PostgresConversationOutboxRepository
from qualify_api.conversations.repository import PostgresConversationRepository
from qualify_api.conversations.sender import ConversationOutboxSender
from qualify_api.conversations.service import ConversationService
from qualify_api.conversations.suggest import (
    ClaudeDraftGenerator,
    ConversationDraftService,
    Grounding,
    grounding_from_products,
)
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.templates import (
    PostgresReplyTemplateRepository,
    ReplyTemplateService,
)

logger = logging.getLogger("qualify_api.conversations.composition")

DM_CHANNEL_ENV: Final = "QUALIFY_CONVERSATIONS_DM_CHANNEL"
DM_CHANNEL_INSTAGRAM: Final = "instagram"
DM_CHANNEL_MEMORY: Final = "memory"
PLATFORM_INSTAGRAM: Final = "instagram"
STATUS_ACTIVE: Final = "active"


def dm_channel_mode() -> str:
    """`instagram` unless the environment says `memory`; any other value is `instagram`
    (a typo must never silently route production through the in-memory pair)."""
    raw = os.environ.get(DM_CHANNEL_ENV, DM_CHANNEL_INSTAGRAM).strip().lower()
    return DM_CHANNEL_MEMORY if raw == DM_CHANNEL_MEMORY else DM_CHANNEL_INSTAGRAM


# --- the in-memory pair (development) ----------------------------------------------------

_MEMORY_SOURCE: MemoryConversationSource | None = None
_MEMORY_SENDER: MemoryConversationSender | None = None


def memory_pair() -> tuple[MemoryConversationSource, MemoryConversationSender]:
    """One source + sender per process, so the seed and the registry share them."""
    global _MEMORY_SOURCE, _MEMORY_SENDER  # noqa: PLW0603
    if _MEMORY_SOURCE is None or _MEMORY_SENDER is None:
        _MEMORY_SOURCE, _MEMORY_SENDER = MemoryConversationSource(), MemoryConversationSender()
    return _MEMORY_SOURCE, _MEMORY_SENDER


# --- connection reads (ids only, under RLS) ----------------------------------------------


def source_connection_for(tenant_id: UUID, connection_id: UUID) -> SourceConnection | None:
    """The ids a channel needs for one connection — `None` when the row is not visible
    to this tenant (RLS) or is not an active Instagram connection."""
    with tenant_session(tenant_id) as session:
        row = session.execute(
            select(
                SocialConnection.id,
                SocialConnection.external_account_id,
                SocialConnection.linked_page_id,
            ).where(
                SocialConnection.id == connection_id,
                SocialConnection.platform == PLATFORM_INSTAGRAM,
                SocialConnection.status == STATUS_ACTIVE,
            )
        ).one_or_none()
    if row is None:
        return None
    return SourceConnection(
        tenant_id=tenant_id,
        connection_id=row.id,
        external_account_id=row.external_account_id,
        linked_page_id=row.linked_page_id,
    )


def instagram_connections_for(tenant_id: UUID) -> list[SourceConnection]:
    """Every active Instagram connection of the tenant, as the sync sees them."""
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(
                SocialConnection.id,
                SocialConnection.external_account_id,
                SocialConnection.linked_page_id,
            )
            .where(
                SocialConnection.platform == PLATFORM_INSTAGRAM,
                SocialConnection.status == STATUS_ACTIVE,
            )
            .order_by(SocialConnection.connected_at)
        ).all()
    return [
        SourceConnection(
            tenant_id=tenant_id,
            connection_id=r.id,
            external_account_id=r.external_account_id,
            linked_page_id=r.linked_page_id,
        )
        for r in rows
    ]


def granted_scopes_for(tenant_id: UUID, connection_id: UUID) -> tuple[str, ...] | None:
    from qualify_api.connections.read import connection_scopes  # noqa: PLC0415

    return connection_scopes(tenant_id=tenant_id, connection_id=connection_id)


# --- the Instagram pair (production) -----------------------------------------------------


async def _authenticated_client(tenant_id: UUID, connection_id: UUID) -> AuthenticatedClient:
    """`CredentialResolver.client_for` for THIS connection: the token is injected into
    the HTTP client it returns and never reaches this module (R3)."""
    from qualify_api.config import MetaOAuthSettings  # noqa: PLC0415
    from qualify_api.connections.credential_reader import DbCredentialReader  # noqa: PLC0415
    from qualify_api.connections.crypto import DevEncryptor  # noqa: PLC0415
    from qualify_api.connections.resolver import InjectingCredentialResolver  # noqa: PLC0415

    settings = MetaOAuthSettings.from_env()
    resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), DevEncryptor())
    return await resolver.client_for(connection_id, scheme=settings.graph_auth_scheme)


def _story_replies_enabled() -> bool:
    """m-24789646: whether the poll asks Meta which story a DM replies to (the
    `story_reply_context` capability, off until R3)."""
    from qualify_api.followups.capabilities import Capabilities, Capability  # noqa: PLC0415

    return Capabilities.from_env().enabled(Capability.STORY_REPLY_CONTEXT)


def _instagram_pair() -> tuple[object, object]:
    from qualify_api.config import MetaOAuthSettings  # noqa: PLC0415
    from qualify_api.conversations.instagram_source import (  # noqa: PLC0415
        InstagramDirectSender,
        InstagramDirectSource,
    )

    graph_url = MetaOAuthSettings.from_env().graph_url
    return (
        InstagramDirectSource(
            client_factory=_authenticated_client,
            graph_url=graph_url,
            scope_reader=granted_scopes_for,
            story_replies=_story_replies_enabled(),
        ),
        InstagramDirectSender(client_factory=_authenticated_client, graph_url=graph_url),
    )


@cache
def production_registry() -> ChannelRegistry:
    """The registry every process shares. Built once; the mode is read once."""
    registry = ChannelRegistry()
    mode = dm_channel_mode()
    if mode == DM_CHANNEL_MEMORY:
        source, sender = memory_pair()
        logger.warning(
            "conversations: channel 'dm' is served by the IN-MEMORY pair (%s=memory) — "
            "development only, nothing reaches Instagram",
            DM_CHANNEL_ENV,
        )
    else:
        source, sender = _instagram_pair()
    registry.register(source=source, sender=sender)  # type: ignore[arg-type]
    return registry


# --- Postgres wiring ---------------------------------------------------------------------


def production_repository() -> PostgresConversationRepository:
    return PostgresConversationRepository()


def production_outbox() -> PostgresConversationOutboxRepository:
    return PostgresConversationOutboxRepository()


def production_conversation_service() -> ConversationService:
    return ConversationService(
        repository=production_repository(),
        outbox=production_outbox(),
        registry=production_registry(),
    )


def production_sync_service() -> ConversationSyncService:
    return ConversationSyncService(repository=production_repository())


# --- E4: assisted replies ----------------------------------------------------------------


def grounding_for(tenant_id: UUID, connection_id: UUID) -> Grounding:
    """The validated facts a draft may state: the brand's name and its active products
    (`brand_products`, QUA-144's catalog), both read under RLS. A connection without a
    brand grounds on nothing — the generator is told so and must not assert products."""
    from qualify_api.catalog.models import BrandProduct  # noqa: PLC0415
    from qualify_api.catalog.read import price_label  # noqa: PLC0415
    from qualify_api.tenancy.models import Brand  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        brand_id = session.execute(
            select(SocialConnection.brand_id).where(SocialConnection.id == connection_id)
        ).scalar_one_or_none()
        if brand_id is None:
            return Grounding()
        name = session.execute(select(Brand.name).where(Brand.id == brand_id)).scalar_one_or_none()
        rows = list(
            session.scalars(
                select(BrandProduct)
                .where(BrandProduct.brand_id == brand_id, BrandProduct.is_active.is_(True))
                .order_by(BrandProduct.position, BrandProduct.name)
            )
        )
        products = [
            {
                "name": p.name,
                "price_label": price_label(p.price_amount, p.price_currency or ""),
                "category": p.category or "",
                "description": p.description or "",
            }
            for p in rows
        ]
    return grounding_from_products(name, products)


@cache
def production_draft_service() -> ConversationDraftService:
    """Built once; the Claude client is created on the first suggestion, so composing
    this without `QUALIFY_ANTHROPIC_API_KEY` is fine — only «Sugerir» fails, loudly."""
    return ConversationDraftService(
        repository=production_repository(),
        drafts=PostgresDraftRepository(),
        generator=ClaudeDraftGenerator(),
        grounding=grounding_for,
    )


# --- m-24789472: message templates -------------------------------------------------------


def brand_name_for(tenant_id: UUID, connection_id: UUID) -> str | None:
    """`{marca}` for one account: the brand it is linked to (`social_connections.brand_id`
    → `brands.name`), else the business's own name (`tenants.name` — 1 login = 1 tenant =
    1 negocio). Read under RLS; None only when neither has a name."""
    from qualify_api.tenancy.models import Brand, Tenant  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        brand_id = session.execute(
            select(SocialConnection.brand_id).where(SocialConnection.id == connection_id)
        ).scalar_one_or_none()
        if brand_id is not None:
            name = session.scalar(select(Brand.name).where(Brand.id == brand_id))
            if name and name.strip():
                return name.strip()
        tenant_name = session.scalar(select(Tenant.name).where(Tenant.id == tenant_id))
    return tenant_name.strip() if tenant_name and tenant_name.strip() else None


def production_template_service() -> ReplyTemplateService:
    """The composer's template library. Holds no outbox and no channel: it cannot send."""
    return ReplyTemplateService(
        repository=PostgresReplyTemplateRepository(),
        threads=production_repository(),
        brand_name=brand_name_for,
    )


class _LazyMediaLinker:
    """QUA-68's public-media linker, built on first use: a worker without
    `QUALIFY_PUBLIC_MEDIA_BASE_URL` still sends text replies and fails only a media one
    (`PublicMediaConfigurationError` → the sender retries the row, never the batch)."""

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        from qualify_api.publishing.composition import (  # noqa: PLC0415
            production_public_media_linker,
        )

        return production_public_media_linker().link(
            tenant_id=tenant_id, object_key=object_key, content_type=content_type
        )


def production_sender(*, worker_id: str) -> ConversationOutboxSender:
    from qualify_api.connections.composition import (  # noqa: PLC0415
        degrade_connection_on_auth_error,
    )
    from qualify_api.followups.capabilities import (  # noqa: PLC0415
        Capabilities,
        Capability,
    )

    return ConversationOutboxSender(
        outbox=production_outbox(),
        repository=production_repository(),
        registry=production_registry(),
        connections=source_connection_for,
        degrade=degrade_connection_on_auth_error,
        media_linker=_LazyMediaLinker(),
        # m-24789646: a queued private reply leaves only while its capability is on.
        private_replies=Capabilities.from_env().enabled(Capability.COMMENT_PRIVATE_REPLY),
        worker_id=worker_id,
    )


def production_media_gate():
    """The R2 door a media reply is staged through (`ObjectGate.put_media`: tenant-prefixed
    key, size ceiling, content type required). Built per call; the store is cheap."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return ObjectGate(R2ObjectStore(R2Settings.from_env()))


__all__ = [
    "DM_CHANNEL_ENV",
    "DM_CHANNEL_INSTAGRAM",
    "DM_CHANNEL_MEMORY",
    "brand_name_for",
    "dm_channel_mode",
    "granted_scopes_for",
    "grounding_for",
    "instagram_connections_for",
    "memory_pair",
    "production_conversation_service",
    "production_draft_service",
    "production_media_gate",
    "production_outbox",
    "production_registry",
    "production_repository",
    "production_sender",
    "production_sync_service",
    "production_template_service",
    "source_connection_for",
]
