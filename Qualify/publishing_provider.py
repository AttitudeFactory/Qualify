"""The seam between the publish screen and the real publishing backend (A5).

Mirrors `connections_provider.py`'s split between reads this module owns/reuses and
writes it delegates:

- **Reads this module reuses.** `active_connections` reuses `connections_provider.
  connections_for` exactly as it is — the tenant's connections come from the same
  Postgres query C-06 already runs; this module adds zero new database access, only a
  filter and a narrower projection.
- **Writes this module delegates.** `start_publish`/`poll_publish` are thin async
  projections over `qualify_api.publishing`'s published seam (`stage_and_start_publish`/
  `advance_publish`). Those are already `async def` (they `await` an `httpx.AsyncClient`
  and wrap their one blocking call in `asyncio.to_thread` INSIDE the seam), so this
  module — and `publishing_state.py` above it — never needs `asyncio.to_thread` for
  publishing, unlike `connections_provider`'s synchronous `begin_connect`/`disconnect`.

`UnknownConnection`/`UnknownAttempt` are NOT caught here — they propagate to the caller,
same posture as `connections_provider.disconnect` letting `ConnectionNotFound` through.
"""

from __future__ import annotations

from typing import IO
from uuid import UUID

from qualify_api.publishing import (
    PendingUpload,
    advance_publish,
    get_child_statuses,
    stage_and_start_many_publish,
    stage_and_start_publish,
)
from qualify_api.publishing.failure_text import failure_text
from qualify_api.publishing.service import PublishState as ServicePublishState

from .connections_provider import connections_for
from .publish_wizard_vm import connection_label
from .publishing_vm import ChildStatusVM, ConnectionOptionVM, PublishAttemptVM


def active_connections(tenant_id: UUID) -> list[ConnectionOptionVM]:
    """The tenant's connections that can actually receive a publish right now.

    Blocking DB call (via `connections_for`) — callers on the event loop must run it
    off-thread, same as `connections_for` itself.
    """
    return [
        ConnectionOptionVM(
            id=connection.id,
            external_username=connection.external_username,
            platform=connection.platform,
            label=connection_label(connection.external_username, connection.platform),
        )
        for connection in connections_for(tenant_id)
        if connection.status == "active"
    ]


def _to_vm(state: ServicePublishState) -> PublishAttemptVM:
    return PublishAttemptVM(
        attempt_id=str(state.attempt_id),
        status=state.status,
        settled=state.settled,
        published_media_id=state.published_media_id or "",
        # NAV-11 (m-24849129): the owner reads why in plain Spanish; the diagnostic code
        # (`platform_error_code`) stays in the database and the logs.
        reason=failure_text(state.reason) if state.settled and state.status != "published" else "",
        awaiting_confirmation=state.awaiting_confirmation,
        poll_interval_seconds=state.poll_interval_seconds,
    )


async def start_publish(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    fileobj: IO[bytes],
    content_type: str,
    media_product_type: str,
    caption: str,
    idempotency_key: str,
) -> PublishAttemptVM:
    """Stage the uploaded file and start a publish attempt.

    `media_product_type` (QUA-103) is the caller's to decide — `"REELS"` for the single
    video that was this slice's only case (decision 1 of the approved plan, still true:
    there is no Stories/carousel selector in the UI), or `"IMAGE"` for a single JPEG.
    NEVER hardcoded here anymore: `publishing_state.py` resolves it from the one pending
    item's own type before calling this, and forwards it verbatim — the exact hardcode
    this signature used to have (`media_product_type="REELS"`, unconditionally) is what
    made publishing a single image from `/publish` structurally impossible before this
    ticket, even though `PublishService._start_image` (QUA-68) already existed. An empty
    caption is sent as `None`, matching what a caption-less publish means to
    `PublishService`.
    """
    state = await stage_and_start_publish(
        tenant_id=tenant_id,
        connection_id=connection_id,
        fileobj=fileobj,
        content_type=content_type,
        media_product_type=media_product_type,
        idempotency_key=idempotency_key,
        caption=caption or None,
    )
    return _to_vm(state)


async def start_many_publish(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    items: list[PendingUpload],
    caption: str,
    idempotency_key: str,
) -> PublishAttemptVM:
    """The multi-video counterpart of `start_publish` above (QUA-99, 5/6) — the interface
    Commit 6 wires up once the gallery holds 2-10 items. `start_publish` itself is
    UNCHANGED: a single video keeps using it exactly as before, never this function.

    `PublishService.start_many` (the seam this delegates to) decides internally whether
    `items` is one video (delegates to `start()`, unchanged) or 2-10 (the carousel path,
    QUA-99 4/6) — so Commit 6 does not need its own branching here either, only a
    decision about which of these two provider functions to call. `caption` flows
    straight through to `start_many(caption=...)`, the same "empty string means no
    caption" convention `start_publish` already uses — the caption is not silently
    dropped for a multi-item publish (QUA-99, 4.5/6 persists it end to end).

    `UnknownConnection`/`TooManyItems` are NOT caught here — same posture `start_publish`
    already has for `UnknownConnection`, propagated to the caller.
    """
    state = await stage_and_start_many_publish(
        tenant_id=tenant_id,
        connection_id=connection_id,
        items=items,
        idempotency_key=idempotency_key,
        caption=caption or None,
    )
    return _to_vm(state)


async def poll_publish(*, tenant_id: UUID, attempt_id: UUID) -> PublishAttemptVM:
    """One `advance()` step. The caller is the client that drives the cadence — see
    `PublishService.advance` for why there is no loop on the backend side."""
    state = await advance_publish(tenant_id=tenant_id, attempt_id=attempt_id)
    return _to_vm(state)


def carousel_children_status(*, tenant_id: UUID, attempt_id: UUID) -> list[ChildStatusVM]:
    """Read-only carousel-progress projection (QUA-99 UX follow-up) — call this ALONGSIDE
    `poll_publish`, never instead of it: it changes nothing about the attempt, only lets
    the polling screen show which child is still uploading/processing instead of one
    generic spinner. Blocking DB call (via `get_child_statuses`) — same posture
    `active_connections` already documents for itself; callers on the event loop must run
    it off-thread."""
    return [
        ChildStatusVM(position=c.position, status=c.status)
        for c in get_child_statuses(tenant_id=tenant_id, attempt_id=attempt_id)
    ]
