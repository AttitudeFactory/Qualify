"""Wiring for the TikTok draft flow (m-24921091): the published seam for the UI.

`send_tiktok_draft` / `refresh_tiktok_draft` are direct async Python calls over ids (no HTTP
hop), same role as `stage_and_start_publish`. Lazy imports keep `import` free of Redis/R2.
"""

from __future__ import annotations

from functools import cache
from uuid import UUID

from qualify_api.config import TikTokSettings
from qualify_api.publishing.tiktok_client import HttpTikTokPostClient, TikTokPostClient
from qualify_api.publishing.tiktok_drafts import (
    DraftState,
    PostgresTikTokDraftRepository,
    TikTokDraftService,
)


class ResolverTikTokClientFactory:
    """Resolves the credential AT SEND TIME (refreshing it if needed); no token in here."""

    def __init__(self, settings: TikTokSettings) -> None:
        self._settings = settings

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> TikTokPostClient:
        from qualify_api.connections.composition import production_tiktok_resolver

        client, version = await production_tiktok_resolver(tenant_id).client_and_version(
            connection_id
        )
        return HttpTikTokPostClient(
            client=client, api_base_url=self._settings.api_base_url, credential_version=version
        )


@cache
def production_tiktok_draft_service() -> TikTokDraftService:
    from qualify_shared.objects.config import R2Settings
    from qualify_shared.objects.gate import ObjectGate
    from qualify_shared.objects.s3 import R2ObjectStore

    from qualify_api.connections.composition import degrade_connection_on_auth_error
    from qualify_api.connections.read import list_connections
    from qualify_api.planner.composition import production_post_reader
    from qualify_api.publishing.composition import production_public_media_linker

    settings = TikTokSettings.from_env()
    return TikTokDraftService(
        posts=production_post_reader(),
        connections=list_connections,
        repository=PostgresTikTokDraftRepository(),
        gate=ObjectGate(R2ObjectStore(R2Settings.from_env())),
        client_factory=ResolverTikTokClientFactory(settings),
        upload_mode=settings.upload_mode,
        media_linker=production_public_media_linker(),
        connection_degrader=degrade_connection_on_auth_error,
    )


async def send_tiktok_draft(
    *,
    tenant_id: UUID,
    user_id: UUID,
    connection_id: UUID,
    post_id: UUID,
    output_port: str | None = None,
    attempt: int = 1,
) -> DraftState:
    """Send an APPROVED piece to the creator's TikTok drafts. Raises `DraftRefused` (with a
    Spanish `message`) when the piece is not approved/publishable or the account needs a
    reconnect. Idempotent per approved revision. Never publishes, never schedules."""
    return await production_tiktok_draft_service().send_to_inbox(
        tenant_id=tenant_id,
        user_id=user_id,
        connection_id=connection_id,
        post_id=post_id,
        output_port=output_port,
        attempt=attempt,
    )


async def refresh_tiktok_draft(
    *, tenant_id: UUID, connection_id: UUID, draft_id: UUID
) -> DraftState:
    """One status read of a draft already sent (the UI polls this until `settled`)."""
    return await production_tiktok_draft_service().refresh(
        tenant_id=tenant_id, connection_id=connection_id, draft_id=draft_id
    )
