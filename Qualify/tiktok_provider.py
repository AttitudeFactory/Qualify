"""The seam between the app and the TikTok backend (m-24921091).

Same split as `connections_provider`:

- **Reads this module owns**, through `tenant_session` (RLS) or the connections read model:
  the tenant's TikTok accounts, a piece's last draft, how many sends failed.
- **Writes it delegates** to the published seams: `connections.composition.
  start_tiktok_connect` / `disconnect_tiktok` and `publishing.tiktok_composition.
  send_tiktok_draft` / `refresh_tiktok_draft`. Those async seams do blocking work inside
  (Postgres, Redis, the R2 read of the video), so they run on a worker thread with their own
  event loop (`_off_loop`) — never on Reflex's, which every other session's websocket shares.

Nothing credential-bearing crosses this module: `oauth_credentials` is never read here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from qualify_api.config import TikTokSettings
from qualify_api.connections.read import list_connections
from qualify_api.connections.tiktok_service import tiktok_access_notice
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from .connections_provider import NoActingUser, acting_user_id
from .tiktok_vm import (
    NO_DRAFT,
    NOT_A_TARGET,
    PLATFORM,
    STATUS_FAILED,
    TikTokAccountVM,
    TikTokDraftVM,
    TikTokTarget,
    build_account_vm,
    build_draft_vm,
    pick_target,
    refused_vm,
)


async def _off_loop[T](make: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run an async backend seam on a worker thread with its own loop (see module doc)."""
    return await asyncio.to_thread(lambda: asyncio.run(make()))


def tiktok_available() -> bool:
    """TikTok can be connected here only when the deployment has its app configured."""
    return TikTokSettings.is_configured()


def tiktok_accounts(tenant_id: UUID) -> list[TikTokAccountVM]:
    """The tenant's TikTok accounts, newest first. Blocking DB — run off the event loop."""
    return [
        build_account_vm(
            connection_id=str(row.connection_id),
            display_name=row.external_username,
            status=row.status,
            granted_scopes=row.granted_scopes,
            reconnect_reason=row.reconnect_reason,
            access_notice=tiktok_access_notice(row.access_posture),
        )
        for row in list_connections(tenant_id)
        if row.platform == PLATFORM
    ]


def begin_tiktok_connect(tenant_id: UUID, connection_id: UUID | None = None) -> str:
    """The TikTok consent URL (one-shot `state` + PKCE verifier in Redis). With
    `connection_id` it is a reconnect of THAT account. Blocking — run off the event loop.
    Raises `NoActingUser` like `connections_provider.begin_connect`."""
    from qualify_api.connections.composition import start_tiktok_connect

    user_id = acting_user_id(tenant_id)
    if user_id is None:
        raise NoActingUser(f"tenant {tenant_id} has no user to attribute the grant to")
    return start_tiktok_connect(
        tenant_id=tenant_id, brand_id=None, user_id=user_id, connection_id=connection_id
    )


async def disconnect_tiktok_account(tenant_id: UUID, connection_id: UUID) -> bool:
    """Disconnect: TikTok is asked to drop the token (best effort, needs the app configured),
    then the shared FSM revoke. Returns whether the status changed. Raises
    `ConnectionNotFound` for an id this tenant cannot see — never reported as success."""
    from qualify_api.connections.composition import disconnect_tiktok, revoke_connection

    if TikTokSettings.is_configured():
        result = await _off_loop(
            lambda: disconnect_tiktok(tenant_id=tenant_id, connection_id=connection_id)
        )
    else:
        result = await asyncio.to_thread(
            revoke_connection, tenant_id=tenant_id, connection_id=connection_id
        )
    return result.changed


def tiktok_target(tenant_id: UUID, post_id: UUID) -> TikTokTarget:
    """Whether this piece is one video TikTok can take, and from which template output.
    Read through the Planificador's post reader (RLS). Blocking — run off the event loop."""
    from qualify_api.planner.composition import production_post_reader

    summary = production_post_reader().get_many(tenant_id=tenant_id, post_ids=[post_id])
    post = summary.get(post_id)
    if post is None:
        return NOT_A_TARGET
    return pick_target(
        [(output.port, output.media_types) for output in post.outputs],
        post.media_types,
    )


def _draft_rows(tenant_id: UUID, post_id: UUID, output_port: str):  # type: ignore[no-untyped-def]
    from qualify_api.publishing.models import TikTokDraft

    port = (
        TikTokDraft.output_port.is_(None)
        if not output_port
        else (TikTokDraft.output_port == output_port)
    )
    return TikTokDraft, (TikTokDraft.tenant_id == tenant_id, TikTokDraft.post_id == post_id, port)


def latest_draft(tenant_id: UUID, post_id: UUID, output_port: str = "") -> TikTokDraftVM:
    """The last draft of this piece (that output) sent to TikTok, or `NO_DRAFT`."""
    from qualify_api.publishing.tiktok_drafts import IN_INBOX_TEXT, failure_text

    model, where = _draft_rows(tenant_id, post_id, output_port)
    with tenant_session(tenant_id) as session:
        row = session.scalars(
            select(model).where(*where).order_by(model.started_at.desc()).limit(1)
        ).first()
        if row is None:
            return NO_DRAFT
        message = (
            failure_text(row.platform_error_code)
            if row.status == STATUS_FAILED
            else IN_INBOX_TEXT
            if row.status == "in_inbox"
            else ""
        )
        return build_draft_vm(draft_id=str(row.id), status=row.status, message=message)


def failed_attempts(tenant_id: UUID, connection_id: UUID, post_id: UUID, output_port: str) -> int:
    """How many sends of this piece to this account failed — the next `attempt` follows."""
    model, where = _draft_rows(tenant_id, post_id, output_port)
    with tenant_session(tenant_id) as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(*where, model.connection_id == connection_id, model.status == STATUS_FAILED)
            )
            or 0
        )


async def send_to_tiktok_drafts(
    *,
    tenant_id: UUID,
    user_id: UUID,
    connection_id: UUID,
    post_id: UUID,
    output_port: str,
    attempt: int,
) -> TikTokDraftVM:
    """Send the approved piece to the account's TikTok drafts. A refusal (not approved,
    not a video, account to reconnect) comes back as a `refused` VM with its Spanish
    reason; nothing is published and nothing is scheduled."""
    from qualify_api.publishing.tiktok_composition import send_tiktok_draft
    from qualify_api.publishing.tiktok_drafts import DraftRefused

    try:
        state = await _off_loop(
            lambda: send_tiktok_draft(
                tenant_id=tenant_id,
                user_id=user_id,
                connection_id=connection_id,
                post_id=post_id,
                output_port=output_port or None,
                attempt=attempt,
            )
        )
    except DraftRefused as refused:
        return refused_vm(refused.message)
    return build_draft_vm(draft_id=str(state.draft_id), status=state.status, message=state.message)


async def refresh_draft(*, tenant_id: UUID, connection_id: UUID, draft_id: UUID) -> TikTokDraftVM:
    """One status read of a draft already sent."""
    from qualify_api.publishing.tiktok_composition import refresh_tiktok_draft
    from qualify_api.publishing.tiktok_drafts import DraftRefused

    try:
        state = await _off_loop(
            lambda: refresh_tiktok_draft(
                tenant_id=tenant_id, connection_id=connection_id, draft_id=draft_id
            )
        )
    except DraftRefused as refused:
        return refused_vm(refused.message)
    return build_draft_vm(draft_id=str(state.draft_id), status=state.status, message=state.message)
