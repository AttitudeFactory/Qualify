"""Production assembly for the inbox module (Reflex caller, B2 UI slice) — the analogue
of `publishing/composition.py`.

One structural difference from `publishing`'s composition, and it drives everything
below: `PublishService` takes a `client_factory` and resolves credentials PER CALL,
internally — so `production_publish_service()` can be a single `@cache`d instance.
`InboxService.__init__` takes fixed, already-authenticated `comments_client`/
`media_client` instead (no factory indirection inside the service). That means a cached,
no-arg `production_inbox_service()` is not an option here: the client each `InboxService`
holds is only valid for one connection's credentials, so a fresh service is built per
`(tenant_id, connection_id)` call instead. `PostgresInboxRepository`/`PostgresIgUserIdReader`
are cheap to construct (no connection pool of their own — they open sessions via
`tenant_session` per call, same as every other repository in this codebase), so rebuilding
around them costs nothing.

Blocking-call posture matches `publishing/composition.py`'s, not `stage_and_start_publish`'s:
`resolver.client_for()` already does a synchronous Postgres read for the credential
INSIDE an `async def` without `asyncio.to_thread` (see `connections/resolver.py`), and
that is the one already-shipped, already-tested precedent — `ResolverPublishClientFactory.
client_for` calls it the same way. `PostgresIgUserIdReader.read` and every
`PostgresInboxRepository` method are the same class of operation (a single-row Postgres
read/write), so they are left un-wrapped here too, for consistency with that precedent —
only genuinely heavy I/O (R2 uploads, in `publishing`) gets `asyncio.to_thread` in this
codebase's established convention.
"""

from __future__ import annotations

from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.models import SocialConnection
from qualify_api.connections.resolver import InjectingCredentialResolver
from qualify_api.inbox.client import HttpCommentsClient
from qualify_api.inbox.media_client import HttpMediaClient
from qualify_api.inbox.repository import PostgresInboxRepository
from qualify_api.inbox.service import CandidateMedia, InboxService, SyncSummary


class UnknownInboxConnection(Exception):
    """No connection with this id is visible to this tenant.

    Deliberately covers "belongs to another tenant" too — `PostgresIgUserIdReader` reads
    through `tenant_session`, so RLS filters that row out before this code ever sees it,
    same posture `connections_provider.disconnect`'s `ConnectionNotFound` and
    `publishing.service.UnknownConnection` already establish for this exact ambiguity.
    """


class PostgresIgUserIdReader:
    """Reads only `external_account_id` from `social_connections` — duplicated from
    `publishing.composition.PostgresConnectionTargetReader` rather than imported, same
    self-containment discipline every client module in `inbox/` already follows (see
    `media_client.py`'s `_error_codes`)."""

    def read(self, *, tenant_id: UUID, connection_id: UUID) -> str:
        with tenant_session(tenant_id) as session:
            ig_user_id = session.scalar(
                select(SocialConnection.external_account_id).where(
                    SocialConnection.id == connection_id
                )
            )
        if ig_user_id is None:
            raise UnknownInboxConnection(
                f"connection {connection_id} is not visible to tenant {tenant_id}"
            )
        return ig_user_id


def production_ig_user_id_for(*, tenant_id: UUID, connection_id: UUID) -> str:
    """Module-level function (not inlined) so offline tests can monkeypatch it without
    touching Postgres — same reasoning `test_publishing_composition.py` monkeypatches
    `production_publish_service`/`production_staging_service` rather than their internals."""
    return PostgresIgUserIdReader().read(tenant_id=tenant_id, connection_id=connection_id)


async def production_inbox_service_for(*, tenant_id: UUID, connection_id: UUID) -> InboxService:
    """Build an `InboxService` with credentials resolved fresh for THIS connection. See
    the module docstring for why this cannot be `@cache`d the way `production_publish_
    service()` is."""
    settings = MetaOAuthSettings.from_env()
    encryptor = DevEncryptor()
    resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), encryptor)
    graph_client = await resolver.client_for(connection_id, scheme=settings.graph_auth_scheme)
    return InboxService(
        repository=PostgresInboxRepository(),
        comments_client=HttpCommentsClient(graph_client=graph_client, graph_url=settings.graph_url),
        media_client=HttpMediaClient(graph_client=graph_client, graph_url=settings.graph_url),
    )


async def list_candidate_media(
    *, tenant_id: UUID, connection_id: UUID
) -> tuple[CandidateMedia, ...]:
    """The published seam for Reflex — the inbox analogue of `stage_and_start_publish`/
    `advance_publish`: a plain async function over ids, no HTTP hop.

    Raises `UnknownInboxConnection` when the connection id is not visible to this tenant.
    """
    ig_user_id = production_ig_user_id_for(tenant_id=tenant_id, connection_id=connection_id)
    service = await production_inbox_service_for(tenant_id=tenant_id, connection_id=connection_id)
    return await service.list_candidate_media(
        tenant_id=tenant_id, connection_id=connection_id, ig_user_id=ig_user_id
    )


async def set_media_monitored(
    *, tenant_id: UUID, connection_id: UUID, external_media_id: str, monitored: bool
) -> None:
    """The published seam for the monitoring toggle.

    Raises `UnknownInboxConnection` when the connection id is not visible to this tenant
    — checked explicitly via `production_ig_user_id_for` even though the id itself is
    unused here, so both seam functions in this module fail the same way for the same
    condition (without this check, an unknown connection would instead surface as
    `CredentialNotFound` from inside credential resolution — a different, unexported
    exception type callers have no reason to know about). Also raises `MediaNotEligible`
    (propagates from `InboxService`, same as every other seam in this codebase lets its
    service's typed exceptions through rather than swallowing them).
    """
    production_ig_user_id_for(tenant_id=tenant_id, connection_id=connection_id)
    service = await production_inbox_service_for(tenant_id=tenant_id, connection_id=connection_id)
    await service.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=external_media_id,
        monitored=monitored,
    )


async def sync_comments(*, tenant_id: UUID, connection_id: UUID) -> SyncSummary:
    """The published seam for a sync pass — the third and last of this module's seam
    functions, completing the trio alongside `list_candidate_media`/`set_media_monitored`.

    This is ONLY the wiring: `InboxService.sync_comments` (already real, already tested
    against a live comment in `packages/api/tests/test_inbox_service.py`) becomes
    reachable through the same credential-resolved seam its siblings use. Its caller is
    `qualify_api.http.inbox_routes.sync_inbox` (`POST /api/inbox/sync`, B2's
    acceptance-criterion route) — no scheduler exists yet; that remains out of scope
    here.

    Raises `UnknownInboxConnection` when the connection id is not visible to this tenant,
    checked the same way `set_media_monitored` does (via `production_ig_user_id_for`,
    even though `sync_comments` itself never needs `ig_user_id` — B1's comments edge is
    addressed directly by media id, not by IG user), so all three seam functions in this
    module fail identically for the same unknown-connection condition.
    """
    production_ig_user_id_for(tenant_id=tenant_id, connection_id=connection_id)
    service = await production_inbox_service_for(tenant_id=tenant_id, connection_id=connection_id)
    return await service.sync_comments(tenant_id=tenant_id, connection_id=connection_id)
