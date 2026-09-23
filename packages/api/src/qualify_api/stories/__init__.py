"""Meta trending-audio reference for the Stories screen (QUA-106 V1 redesign).

**QUA-106 no longer has a `story_proposals`/`StoryProposal` concept anywhere.**
Publishing a Story is a plain `PublishService.start(media_product_type="STORIES")`
call, made directly from the Reflex layer via `qualify_api.publishing` — same seam
`/publish` already uses, just a different `media_product_type`. This package now
holds ONLY the one thing that was ever genuinely Stories-specific: showing Meta's
trending-audio suggestion (`GET /ig_audio`) as a reference panel. It is informational
only — nothing here is ever attached to a real publish call (`audio_configuration` is
explicitly out of scope), and a failed/empty lookup never blocks anything.

`suggest_trend_audio_using` is the pure, injectable logic (unit-tested directly,
offline); `suggest_trend_audio` is the production-wired composition Reflex calls.
Same split `qualify_api.publishing.composition`/`.service` already establish
elsewhere in this codebase, just collapsed into one module since there is no longer
enough Stories-specific surface to justify separate `service.py`/`composition.py`
files.
"""

from __future__ import annotations

from functools import cache
from typing import Protocol
from uuid import UUID

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import DevEncryptor, Encryptor
from qualify_api.connections.resolver import InjectingCredentialResolver
from qualify_api.publishing.composition import PostgresConnectionTargetReader
from qualify_api.publishing.service import ConnectionTargetReader
from qualify_api.stories.trend_audio_client import (
    AUDIO_TYPE_MUSIC,
    AUDIO_TYPE_ORIGINAL_SOUND,
    HttpTrendAudioClient,
    TrendAudioClient,
    TrendAudioError,
    TrendAudioOption,
)

__all__ = [
    "AUDIO_TYPE_MUSIC",
    "AUDIO_TYPE_ORIGINAL_SOUND",
    "ResolverTrendAudioClientFactory",
    "TrendAudioClientFactory",
    "TrendAudioError",
    "TrendAudioOption",
    "suggest_trend_audio",
    "suggest_trend_audio_using",
]


class TrendAudioClientFactory(Protocol):
    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> TrendAudioClient: ...


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


async def suggest_trend_audio_using(
    *,
    connections: ConnectionTargetReader,
    trend_clients: TrendAudioClientFactory | None,
    tenant_id: UUID,
    connection_id: UUID,
    audio_type: str = AUDIO_TYPE_MUSIC,
    search_query: str | None = None,
) -> tuple[TrendAudioOption, ...]:
    """Best-effort reference list, degrade-don't-block: returns `()` rather than
    raising for every failure mode (no client factory configured, unknown connection,
    `TrendAudioError`) — a trending-audio lookup must never block the Stories screen.
    `search_query` forwards verbatim to `TrendAudioClient.trending_audio` — `None`
    (the default) keeps Meta's own trending list; a non-empty string searches Meta's
    catalog by keyword instead. Pure/injectable so it is unit-testable offline;
    `suggest_trend_audio` below is the production-wired composition."""
    if trend_clients is None:
        return ()
    target = connections.read(tenant_id=tenant_id, connection_id=connection_id)
    if target is None:
        return ()
    try:
        client = await trend_clients.client_for(tenant_id=tenant_id, connection_id=connection_id)
        return await client.trending_audio(
            ig_user_id=target.ig_user_id, audio_type=audio_type, search_query=search_query
        )
    except TrendAudioError:
        return ()


@cache
def _production_trend_audio_client_factory() -> ResolverTrendAudioClientFactory:
    settings = MetaOAuthSettings.from_env()
    return ResolverTrendAudioClientFactory(settings, DevEncryptor())


async def suggest_trend_audio(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    audio_type: str = AUDIO_TYPE_MUSIC,
    search_query: str | None = None,
) -> tuple[TrendAudioOption, ...]:
    return await suggest_trend_audio_using(
        connections=PostgresConnectionTargetReader(),
        trend_clients=_production_trend_audio_client_factory(),
        tenant_id=tenant_id,
        connection_id=connection_id,
        audio_type=audio_type,
        search_query=search_query,
    )
