"""Production wiring of Fase C (m-24789646): the followup service and the
«Consultas desde comentarios» workspace over Postgres, the conversations registry every
process shares, the public-notice poster the conversations worker runs, and this
deployment's capability switches (read once, here — nothing below the composition reads
the environment). The Claude client of the drafts is built on the first draft, so
composing this without `QUALIFY_ANTHROPIC_API_KEY` is fine."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from uuid import UUID

from qualify_api.conversations.composition import (
    DM_CHANNEL_ENV,
    DM_CHANNEL_MEMORY,
    dm_channel_mode,
    grounding_for,
    production_outbox,
    production_registry,
    production_repository,
)
from qualify_api.conversations.drafts import PostgresDraftRepository
from qualify_api.conversations.suggest import ClaudeDraftGenerator
from qualify_api.followups.capabilities import Capabilities, Capability
from qualify_api.followups.notice import (
    MemoryNoticeClientFactory,
    NoticeClientFactory,
    PostgresNoticeRepository,
    PublicNoticePoster,
)
from qualify_api.followups.origins import PostgresCommercialIntentReader, PostgresOriginReader
from qualify_api.followups.repository import PostgresFollowupRepository
from qualify_api.followups.service import FollowupService
from qualify_api.followups.workspace import FollowupWorkspace
from qualify_api.intent import (
    CURRENT_INTENT_VERSION,
    IntentClass,
    IntentSignal,
    class_reliability,
    current_signals,
)

logger = logging.getLogger("qualify_api.followups.composition")


def production_capabilities() -> Capabilities:
    return Capabilities.from_env()


def production_followup_service() -> FollowupService:
    return FollowupService(
        followups=PostgresFollowupRepository(),
        origins=PostgresOriginReader(),
        conversations=production_repository(),
        outbox=production_outbox(),
        registry=production_registry(),
        capabilities=production_capabilities(),
    )


def _signals(tenant_id: UUID, message_ids: Sequence[UUID]) -> Mapping[UUID, IntentSignal]:
    return current_signals(tenant_id=tenant_id, message_ids=message_ids)


def _reliability() -> Mapping[IntentClass, bool]:
    return class_reliability(CURRENT_INTENT_VERSION.detector_version)


def production_workspace() -> FollowupWorkspace:
    return FollowupWorkspace(
        service=production_followup_service(),
        followups=PostgresFollowupRepository(),
        origins=PostgresOriginReader(),
        commercial=PostgresCommercialIntentReader(),
        drafts=PostgresDraftRepository(),
        generator=ClaudeDraftGenerator(),
        grounding=grounding_for,
        signals=_signals,
        reliability=_reliability,
        intent_version=CURRENT_INTENT_VERSION,
    )


def _notice_clients() -> NoticeClientFactory:
    """The client the notice is posted with: `replies`' resolver-backed factory (one
    authenticated `HttpCommentReplyClient` per post, no token here), or — when the DM
    channel runs in memory — a client that publishes nothing, so a localhost loop never
    reaches Instagram's public comments either."""
    if dm_channel_mode() == DM_CHANNEL_MEMORY:
        logger.warning(
            "followups: public notices go to an IN-MEMORY client (%s=memory) — "
            "development only, nothing is published",
            DM_CHANNEL_ENV,
        )
        return MemoryNoticeClientFactory()
    from qualify_api.config import MetaOAuthSettings  # noqa: PLC0415
    from qualify_api.connections.crypto import DevEncryptor  # noqa: PLC0415
    from qualify_api.replies.composition import ResolverReplyClientFactory  # noqa: PLC0415

    return ResolverReplyClientFactory(MetaOAuthSettings.from_env(), DevEncryptor())


def production_notice_poster(*, worker_id: str) -> PublicNoticePoster:
    """The public-notice step of the conversations worker (PR 4). It posts only while
    `public_notice` is on in THIS process — the same rule as the sender's private
    replies."""
    return PublicNoticePoster(
        notices=PostgresNoticeRepository(),
        clients=_notice_clients(),
        enabled=production_capabilities().enabled(Capability.PUBLIC_NOTICE),
        worker_id=worker_id,
    )
