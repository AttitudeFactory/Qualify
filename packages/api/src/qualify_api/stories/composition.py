"""Production assembly for the stories module (QUA-106) — the analogue of
`replies/composition.py`. `StoryProposalService` is built around the EXISTING, already
`@cache`d `production_publish_service()` (`publishing/composition.py`) rather than a
second copy of its credential/gate/repository wiring — publishing a Story is exactly
`PublishService.start(media_product_type=STORIES)`, never a parallel path.
"""

from __future__ import annotations

import asyncio
from functools import cache
from typing import IO
from uuid import UUID, uuid4

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import DevEncryptor, Encryptor
from qualify_api.connections.resolver import InjectingCredentialResolver
from qualify_api.publishing.composition import (
    PostgresConnectionTargetReader,
    production_publish_service,
    production_staging_service,
)
from qualify_api.stories.repository import PostgresStoryProposalRepository, ProposalRecord
from qualify_api.stories.service import StoryProposalService
from qualify_api.stories.trend_audio_client import HttpTrendAudioClient, TrendAudioClient


class ResolverTrendAudioClientFactory:
    """One authenticated client per lookup — resolved at call time, same seam
    `ResolverPublishClientFactory`/`ResolverReplyClientFactory` already establish for
    their own Meta calls. Nothing here ever holds a token."""

    def __init__(self, settings: MetaOAuthSettings, encryptor: Encryptor) -> None:
        self._settings = settings
        self._encryptor = encryptor

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> TrendAudioClient:
        resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), self._encryptor)
        graph = await resolver.client_for(connection_id, scheme=self._settings.graph_auth_scheme)
        return HttpTrendAudioClient(graph_client=graph, graph_url=self._settings.graph_url)


@cache
def production_story_proposal_service() -> StoryProposalService:
    settings = MetaOAuthSettings.from_env()
    return StoryProposalService(
        repository=PostgresStoryProposalRepository(),
        publish_service=production_publish_service(),
        connections=PostgresConnectionTargetReader(),
        trend_client_factory=ResolverTrendAudioClientFactory(settings, DevEncryptor()),
    )


async def stage_and_propose_story(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    fileobj: IO[bytes],
    content_type: str,
    caption: str | None,
    trend_audio_id: str | None = None,
    trend_audio_title: str | None = None,
) -> ProposalRecord:
    """The published seam for Reflex/HTTP: stage the operator's own uploaded media
    (the ONLY media source in this v1 — QUA-106 decision, no AI generation, no
    third-party reuse) then write the proposal row. Mirrors `publishing.composition.
    stage_and_start_publish`'s split: the blocking R2 upload runs in `asyncio.
    to_thread`, `propose()` itself is a plain, synchronous DB write.

    `media_product_type="STORIES"` is passed to staging so the object key/size gate
    applies the SAME rules a real Story publish will later need — staging does not
    know yet whether this proposal will be approved, only that it must be stored
    exactly as a Story's media would be.
    """
    from qualify_api.publishing.client import MEDIA_TYPE_STORIES  # noqa: PLC0415

    staged = await asyncio.to_thread(
        production_staging_service().stage_media,
        tenant_id=tenant_id,
        connection_id=connection_id,
        media_id=uuid4().hex,
        fileobj=fileobj,
        content_type=content_type,
        media_product_type=MEDIA_TYPE_STORIES,
    )
    return production_story_proposal_service().propose(
        tenant_id=tenant_id,
        connection_id=connection_id,
        media_object_key=staged.media_object_key,
        media_content_type=staged.content_type,
        caption=caption or None,
        trend_audio_id=trend_audio_id,
        trend_audio_title=trend_audio_title,
    )


def list_proposals(*, tenant_id: UUID) -> tuple[ProposalRecord, ...]:
    return production_story_proposal_service().list_proposals(tenant_id=tenant_id)


def get_proposal(*, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord:
    return production_story_proposal_service().get(tenant_id=tenant_id, proposal_id=proposal_id)


def decide_proposal(
    *,
    tenant_id: UUID,
    proposal_id: UUID,
    decision: str,
    final_caption: str | None,
    decided_by_user_id: UUID,
) -> ProposalRecord:
    return production_story_proposal_service().decide(
        tenant_id=tenant_id,
        proposal_id=proposal_id,
        decision=decision,
        final_caption=final_caption,
        decided_by_user_id=decided_by_user_id,
    )


async def publish_proposal(*, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord:
    return await production_story_proposal_service().publish(
        tenant_id=tenant_id, proposal_id=proposal_id
    )


async def refresh_proposal(*, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord:
    return await production_story_proposal_service().refresh(
        tenant_id=tenant_id, proposal_id=proposal_id
    )


async def suggest_trend_audio(*, tenant_id: UUID, connection_id: UUID, audio_type: str = "music"):
    return await production_story_proposal_service().suggest_trend_audio(
        tenant_id=tenant_id, connection_id=connection_id, audio_type=audio_type
    )
