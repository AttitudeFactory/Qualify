"""The seam between the inbox content screen and the real inbox backend (Fase 1 Parte
4-B, B2 UI slice — the monitoring toggle only; `sync_comments` is deliberately not wired
here, that is the next slice).

Same split `publishing_provider.py` documents:

- **Reads this module reuses.** `instagram_connections` reuses `connections_provider.
  connections_for` exactly as it is, filtered to `platform == "instagram"`, `status ==
  "active"` and the `READ_COMMENTS` capability (C-05) being enabled — this module adds
  zero new database access for that list.
- **Writes/reads this module delegates.** `candidate_media`/`toggle_monitoring` are thin
  async projections over `qualify_api.inbox.composition`'s published seam
  (`list_candidate_media`/`set_media_monitored`, re-exported from `qualify_api.inbox`),
  same role `publishing_provider.py` has over `qualify_api.publishing.composition`.

Both `list_candidate_media`/`set_media_monitored` are already `async def` (the whole
chain down to `InjectingCredentialResolver.client_for` is), so neither function below
needs `asyncio.to_thread` — same posture `publishing_provider.start_publish`/
`poll_publish` already have over their own already-async seam.
"""

from __future__ import annotations

from uuid import UUID

from qualify_api.inbox import list_candidate_media, set_media_monitored
from qualify_api.inbox.service import CandidateMedia

from .capabilities import Capability
from .connections_provider import connections_for
from .inbox_vm import CandidateMediaVM
from .publishing_vm import ConnectionOptionVM


def instagram_connections(tenant_id: UUID) -> list[ConnectionOptionVM]:
    """Active Instagram connections that can actually list/monitor comments right now —
    same 'active status' filter `publishing_provider.active_connections` uses, narrowed
    further to `platform == "instagram"` and `READ_COMMENTS` (C-05) enabled.

    Blocking DB call (via `connections_for`) — callers on the event loop must run it
    off-thread, same as `connections_for` itself.
    """
    return [
        ConnectionOptionVM(
            id=connection.id,
            external_username=connection.external_username,
            platform=connection.platform,
        )
        for connection in connections_for(tenant_id)
        if connection.status == "active"
        and connection.platform == "instagram"
        and any(
            cap.key == Capability.READ_COMMENTS.value and cap.enabled
            for cap in connection.enabled_capabilities
        )
    ]


def _to_vm(media: CandidateMedia) -> CandidateMediaVM:
    return CandidateMediaVM(
        external_media_id=media.external_media_id,
        posted_at=media.timestamp.strftime("%d %b %Y, %H:%M"),
        is_monitored=media.is_monitored,
        caption=media.caption or "",
        permalink=media.permalink or "",
        thumbnail_url=media.thumbnail_url or "",
    )


async def candidate_media(*, tenant_id: UUID, connection_id: UUID) -> list[CandidateMediaVM]:
    """The last-2-weeks Reels for this connection, newest first, cross-referenced against
    what is already monitored. Delegates entirely to `qualify_api.inbox`'s published seam.

    Raises `UnknownInboxConnection` (propagates — same posture `publishing_provider.
    active_connections` has for whatever `connections_for` raises) and any exception the
    Meta call itself can raise (`MediaReadError`, wrapped inside the service as "no
    candidates" only in the sense that the caller must handle it, never silently as an
    empty list — an empty list means "really nothing in the window", not "failed").
    """
    media = await list_candidate_media(tenant_id=tenant_id, connection_id=connection_id)
    return [_to_vm(m) for m in sorted(media, key=lambda m: m.timestamp, reverse=True)]


async def toggle_monitoring(
    *, tenant_id: UUID, connection_id: UUID, external_media_id: str, monitored: bool
) -> None:
    """Flip one Reel's monitoring toggle through the real B2 service.

    Raises `MediaNotEligible` (the 2-week re-validation refused it) and
    `UnknownInboxConnection` (connection not visible to this tenant) — both propagate,
    never swallowed, same posture `connections_provider.disconnect` already has for
    `ConnectionNotFound`. The caller (`InboxState`) maps these to Spanish messages and
    ALWAYS reloads the candidate list afterward regardless of outcome — see
    `inbox_state.py`'s module docstring for why this is never an optimistic update.
    """
    await set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=external_media_id,
        monitored=monitored,
    )
