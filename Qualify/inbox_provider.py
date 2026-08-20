"""The seam between the inbox content screen and the real inbox backend (Fase 1 Parte
4-B, B2 UI slice).

Same split `publishing_provider.py` documents, with one deliberate exception:

- **Reads this module reuses.** `instagram_connections` reuses `connections_provider.
  connections_for` exactly as it is, filtered to `platform == "instagram"`, `status ==
  "active"` and the `READ_COMMENTS` capability (C-05) being enabled — this module adds
  zero new database access for that list.
- **In-process writes/reads.** `candidate_media`/`toggle_monitoring` are thin async
  projections over `qualify_api.inbox.composition`'s published seam
  (`list_candidate_media`/`set_media_monitored`, re-exported from `qualify_api.inbox`),
  same role `publishing_provider.py` has over `qualify_api.publishing.composition` — no
  HTTP hop, same posture `http/app.py`'s own module docstring documents for the Reflex
  CRM in general.
- **The one exception: `sync_now` goes through HTTP.** B2's acceptance criteria (`docs/
  backlog-sprint3-meta-publishing-inbox.md`) explicitly requires `POST /api/inbox/sync`
  as sync's production route — unlike candidate listing and the toggle, which were never
  asked for one. `sync_now` reaches `qualify_api.inbox.composition.sync_comments`
  through that real route, via an in-process ASGI transport (`httpx.ASGITransport`) —
  real HTTP semantics (status codes, JSON (de)serialization, the route's own error
  mapping), no socket, no second process to run/manage. See `_inbox_sync_asgi_client`
  below for what that buys and what it costs (a single dev-tenant scope, see its
  docstring).

`sync_now` (2026-08-15, wired to HTTP 2026-08-16) is the transport both the manual button
and the automatic poll share (QUA-89, 2026-08-19) — see `inbox_page.py`'s module
docstring for the UI side. It adds no sync logic of its own: `InboxService.sync_comments`
already reads ONLY `InboxRepository.list_monitored_media_ids` (media with
`is_monitored=True`), so which Reels get synced is entirely decided by the toggle, not
by anything in this module.

`candidate_media`/`toggle_monitoring` are already `async def` (the whole chain down to
`InjectingCredentialResolver.client_for` is), so neither needs `asyncio.to_thread` — same
posture `publishing_provider.start_publish`/`poll_publish` already have over their own
already-async seam. `sync_now` is `async def` for the same reason `httpx.AsyncClient` is.
"""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

import httpx
from qualify_api.inbox import (
    CommentsAuthExpired,
    CommentsPermissionMissing,
    SyncBudgetExhausted,
    list_candidate_media,
    set_media_monitored,
)
from qualify_api.inbox.composition import UnknownInboxConnection
from qualify_api.inbox.service import CandidateMedia

from .capabilities import Capability
from .connections_provider import connections_for
from .inbox_vm import CandidateMediaVM, SyncSummaryVM
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


# Matches the single `QUALIFY_DEV_PRINCIPALS` entry added to `.env` on 2026-08-16 — the
# ONLY tenant this temporary bridge can authenticate as (PuntoServis, the real
# qualifymkt.co demo tenant). Adding more dev tenants means adding more entries to that
# env var, not changing this module — see `.env`'s comment for the format.
_DEV_SYNC_BEARER_TOKEN = "dev-inbox-sync-puntoservis"  # noqa: S105 - a local dev credential, not a secret
_DEV_SYNC_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")  # PuntoServis


@lru_cache(maxsize=1)
def _inbox_sync_asgi_client() -> httpx.AsyncClient:
    """The real, production-configured FastAPI app (`create_app()` — the same factory a
    real `uvicorn` deployment would use), reached via `httpx.ASGITransport` instead of a
    socket: real HTTP semantics (status codes, JSON (de)serialization, `inbox_routes.
    sync_inbox`'s own error mapping) with no server process to start, monitor or stop —
    there isn't one running in this dev environment (no `just` recipe, no uvicorn
    entrypoint) and standing one up is out of scope for what is explicitly a temporary
    affordance. Cached: rebuilding the app (and its `dependency_overrides`) on every
    click would be pure waste — the app is stateless and safe to reuse across requests,
    same reasoning `publishing.composition.production_publish_service` is `@cache`d.

    `create_app(configure_production=True)` is cheap to call: the OTHER dependency
    overrides it wires (`get_connect_service`, `get_publish_service`, ...) are bare
    function references, not invoked until a request actually needs them — and this
    client only ever calls `/api/inbox/sync`. The one override that DOES run eagerly is
    `current_principal`'s (`deps.build_dev_principal_dependency()` parses
    `QUALIFY_DEV_PRINCIPALS` immediately) — pure string parsing, no I/O, and `.env` is
    already loaded by the time any Reflex event handler runs (`rxconfig.py`'s
    `env_file`).
    """
    from qualify_api.http.app import create_app  # noqa: PLC0415 - see the module docstring

    app = create_app(configure_production=True)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inbox-sync.internal"
    )


async def sync_now(*, tenant_id: UUID, connection_id: UUID) -> SyncSummaryVM:
    """Trigger one `InboxService.sync_comments` pass via `POST /api/inbox/sync` — the
    temporary manual caller's provider half, now the route rather than
    `composition.sync_comments` directly (see the module docstring for why).

    Raises `UnknownInboxConnection` in two cases the caller cannot tell apart, both
    already handled identically by `InboxState.sync_comments` (which shows the same
    "esa cuenta ya no está disponible" message either way, so collapsing them is a
    correct simplification, not a lost distinction):
    - `tenant_id` is not the one tenant `QUALIFY_DEV_PRINCIPALS` authenticates as this
      temporary bridge — refused BEFORE any HTTP call, so a mismatched dev tenant never
      silently syncs against the wrong one's data.
    - the route itself answers 404 (the connection is not visible to the authenticated
      tenant) — the same condition `candidate_media`/`toggle_monitoring` already raise
      this for.

    Raises `CommentsPermissionMissing` (403 — `cannot_observe`, QUA-88) and
    `SyncBudgetExhausted` (429 — the real Meta call budget is spent, QUA-88), same
    "reconstruct a typed exception from the status code" posture the 404 branch below
    already establishes for `UnknownInboxConnection`. Neither carries the server's exact
    message back through: `InboxState.sync_comments` only branches on exception TYPE to
    pick a Spanish message, the same way it already does for `UnknownInboxConnection`.

    Raises `CommentsAuthExpired` (401 — a real runtime auth failure against Meta, QUA-90),
    same reconstruct-from-status-code posture as the other three. By the time this status
    code reaches here the connection has already been degraded server-side
    (`InboxService.sync_comments`); this is only the client-visible signal of that.

    Any other non-2xx response (502 from a failed Meta call, 500 from anything
    unexpected) raises `httpx.HTTPStatusError` via `raise_for_status()` — an ordinary
    exception `InboxState.sync_comments`'s blanket `except Exception` already catches,
    same as it already did for whatever `composition.sync_comments` could raise directly
    before this change.
    """
    if tenant_id != _DEV_SYNC_TENANT_ID:
        raise UnknownInboxConnection(
            f"tenant {tenant_id} is not wired to the temporary dev sync bridge "
            f"(QUALIFY_DEV_PRINCIPALS only authenticates tenant {_DEV_SYNC_TENANT_ID})"
        )
    client = _inbox_sync_asgi_client()
    response = await client.post(
        "/api/inbox/sync",
        json={"connection_id": str(connection_id)},
        headers={"Authorization": f"Bearer {_DEV_SYNC_BEARER_TOKEN}"},
    )
    if response.status_code == 404:
        raise UnknownInboxConnection(str(connection_id))
    if response.status_code == 401:
        raise CommentsAuthExpired(connection_id=connection_id)
    if response.status_code == 403:
        raise CommentsPermissionMissing(connection_id=connection_id)
    if response.status_code == 429:
        # The route's exact needed/remaining are not reconstructed here — the caller
        # only branches on exception TYPE, same posture as the 404/403 cases above.
        raise SyncBudgetExhausted(needed=0, remaining=0)
    response.raise_for_status()
    data = response.json()
    return SyncSummaryVM(
        media_checked=data["media_checked"],
        new_comments=data["new_comments"],
        truncated=data.get("truncated", False),
    )
