"""The seam between `/conversations` (QUA-226, E2) and the real backend.

**In process, not over HTTP** — same posture as `whatsapp_chats_provider.py` and
`connections_provider.py`: the Reflex app calls `qualify_api.conversations.
ConversationService` with the session's tenant, and RLS (`tenant_session`, the
`qualify_app` role) scopes every statement. Nothing here sends a message: a reply is a
`conversation_outbox` row the sender (`conversations.worker`) drains, and the service
refuses it BEFORE writing when the 24 h window is closed (`WindowClosed`) or the channel
has no sender (`UnknownChannel`).

What this module adds on top of the service — small reads it does not expose, all
through `tenant_session` (`PostgresConversationsStore`):

- the **accounts** the inbox can show: `connections_provider.connections_for` (the same
  credential-free `ConnectionVM` the Conexiones screen renders), narrowed to Instagram and
  carrying the C-05 verdict on the messages scope;
- the **access and sync state** of one account (`conversation_sync_state`, E1's repo);
- per thread, the counterpart's **handle** and the last message's **preview** (from
  `messages`; the profile — name, picture — travels on `ThreadRecord` itself since the
  sync fetches it);
- the thread's **unsent outbox rows** (pending / sending / failed / dead) so a person sees
  what they queued and why it did not go out — through E1's `list_for_thread`;
- the **acting user** (`AuthState` carries the login email, not a user id) and the
  tenant's **IANA zone**.

**Media.** An attachment the person adds is staged in R2 FIRST (`stage_attachment`,
through `ObjectGate.put_media` under the tenant's own prefix) and only its object key
travels to the outbox (`reply_media`); the sender mints the public URL Meta fetches at
send time. What the screen renders comes from `media_sources`: an inbound attachment by
the channel's CDN URL the message row carries, an outbound one by the `/r2media/<token>`
path `r2_media.issue_view_path` issues for THIS tenant — never a raw R2 URL. A sticker
(`reply_sticker`) has no object: it is the channel's own.

**Text of any length.** `reply` goes through `ConversationService.reply_text`, which cuts
the text into consecutive messages of at most 1000 characters (Instagram's limit), each
queued with the same approval. The screen says in how many before the person sends.

**Presence.** `signal` is the one call that touches the channel inline: `mark_seen` when
a person opens the thread, `typing_on` while they write. Best-effort (the service swallows
channel errors), ephemeral, never queued — it carries no content, so ADR 21c's approval
does not apply to it.

**Assisted replies (E4).** `suggest` asks `ConversationDraftService` for ONE draft of the
thread's last inbound (gate → Claude → grounding verdict), `decide_draft` records the
person's verdict, and `reply(..., draft_id=…)` carries it into the outbox's approval.
Nothing here sends a draft: the approval is still the person pressing «Responder».

**Account scoping.** The screen shows ONE account at a time. Every thread-level call
re-reads the thread and refuses (`ThreadNotFound`) one that belongs to another account of
the same tenant, so a stale or forged thread id from the browser can never act across
accounts — RLS already stops it across tenants.

**Approval.** `reply` / `reply_media` / `reply_sticker` build the `HumanApproval` from
the resolved user id and the gateway's clock, and hand it to the service — the only way
into the outbox.

All functions but `signal` are blocking (SQLAlchemy is synchronous): the state runs them
through `asyncio.to_thread`. `ConversationsGateway` takes every dependency by injection so
`test_conversations_provider.py` drives it with the in-memory repositories.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_api.conversations.contracts import CHANNEL_DM, STICKER_LIKE_HEART, SourceConnection
from qualify_api.conversations.drafts import ConversationDraft, DraftStatus
from qualify_api.conversations.outbox import (
    ConversationOutboxRepository,
    HumanApproval,
    OutboxMedia,
)
from qualify_api.conversations.repository import (
    ConversationRepository,
    MessageRecord,
    SyncStateRecord,
)
from qualify_api.conversations.service import ConversationService, ThreadNotFound, ThreadView
from qualify_api.conversations.suggest import ConversationDraftService
from qualify_api.inbox.models import Message
from qualify_api.tenancy.models import Tenant, User
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.keys import media_key
from sqlalchemy import func, select

from .connections_provider import connections_for
from .conversations_vm import (
    MESSAGES_PAGE,
    THREADS_LIMIT,
    AccountVM,
    AttachmentVM,
    ThreadExtra,
    UnsentItem,
    inbox_accounts,
    outbox_text,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/Bogota"
UNSENT_STATUSES = frozenset({"pending", "sending", "failed", "dead"})
#: A refused reply stays visible this long; older failures are history, not a to-do.
FAILED_VISIBLE_FOR = timedelta(days=7)
UNSENT_LIMIT = 20


# ======================================================================================
# Store: the reads the ConversationService does not expose
# ======================================================================================


class ConversationsStore(Protocol):
    def thread_extras(
        self, tenant_id: UUID, thread_ids: Iterable[UUID]
    ) -> dict[str, ThreadExtra]: ...

    def user_id_for_email(self, tenant_id: UUID, email: str) -> UUID | None: ...

    def timezone(self, tenant_id: UUID) -> str: ...


class PostgresConversationsStore:
    """`tenant_session(tenant_id)` per call — the only sanctioned door."""

    def thread_extras(self, tenant_id: UUID, thread_ids: Iterable[UUID]) -> dict[str, ThreadExtra]:
        ids = list(thread_ids)
        if not ids:
            return {}
        posted = func.coalesce(Message.posted_at, Message.ingested_at)
        with tenant_session(tenant_id) as session:
            latest = session.execute(
                select(Message.thread_id, Message.direction, Message.text, Message.media_type)
                .distinct(Message.thread_id)
                .where(Message.thread_id.in_(ids), Message.deleted_at.is_(None))
                .order_by(Message.thread_id, posted.desc(), Message.id.desc())
            ).all()
            handles = session.execute(
                select(Message.thread_id, Message.author_username)
                .distinct(Message.thread_id)
                .where(
                    Message.thread_id.in_(ids),
                    Message.direction == "inbound",
                    Message.author_username.is_not(None),
                )
                .order_by(Message.thread_id, posted.desc(), Message.id.desc())
            ).all()
        by_thread = {str(r.thread_id): r.author_username for r in handles}
        extras: dict[str, ThreadExtra] = {}
        for r in latest:
            key = str(r.thread_id)
            extras[key] = ThreadExtra(
                username=by_thread.get(key),
                preview=r.text,
                preview_direction=r.direction,
                preview_media_type=r.media_type,
            )
        for key, username in by_thread.items():
            extras.setdefault(key, ThreadExtra(username=username))
        return extras

    def user_id_for_email(self, tenant_id: UUID, email: str) -> UUID | None:
        if not email.strip():
            return None
        with tenant_session(tenant_id) as session:
            return session.execute(
                select(User.id).where(func.lower(User.email) == email.strip().lower())
            ).scalar_one_or_none()

    def timezone(self, tenant_id: UUID) -> str:
        with tenant_session(tenant_id) as session:
            zone = session.execute(
                select(Tenant.timezone).where(Tenant.id == tenant_id)
            ).scalar_one_or_none()
        return zone or DEFAULT_TIMEZONE


# ======================================================================================
# Media doors (R2 in, /r2media out), injectable
# ======================================================================================


class MediaSink(Protocol):
    def put_media(
        self, tenant_id: UUID, object_key: str, fileobj: Any, content_type: str
    ) -> None: ...


#: `(tenant_id, object_key, media_type, content_type) -> "/r2media/<token>"` or "".
MediaViewer = Callable[[UUID, str, str, str | None], str]
ConnectionResolver = Callable[[UUID, UUID], SourceConnection | None]


def _production_sink() -> MediaSink:
    from qualify_api.conversations.composition import production_media_gate  # noqa: PLC0415

    return production_media_gate()


def _production_viewer(
    tenant_id: UUID, object_key: str, media_type: str, content_type: str | None
) -> str:
    from .r2_media import issue_view_path  # noqa: PLC0415

    try:
        return issue_view_path(tenant_id, object_key, media_type, content_type)
    except Exception as exc:  # noqa: BLE001 — a missing token store hides the media, not the thread
        logger.warning("conversations media view path unavailable: %s", type(exc).__name__)
        return ""


def _production_connection(tenant_id: UUID, connection_id: UUID) -> SourceConnection | None:
    from qualify_api.conversations.composition import source_connection_for  # noqa: PLC0415

    return source_connection_for(tenant_id, connection_id)


# ======================================================================================
# Read shapes
# ======================================================================================


@dataclass(frozen=True)
class ThreadListing:
    view: ThreadView
    extra: ThreadExtra


@dataclass(frozen=True)
class Conversation:
    view: ThreadView
    messages: list[MessageRecord]
    unsent: list[UnsentItem]
    # message id → the URL the screen may render its media from ("" = not shown).
    media_sources: dict[str, str]
    # A model's suggestion still waiting for the person's verdict, if any (E4).
    pending_draft: ConversationDraft | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


AccountsReader = Callable[[UUID], list[AccountVM]]


def _production_accounts(tenant_id: UUID) -> list[AccountVM]:
    return inbox_accounts(connections_for(tenant_id))


class ConversationsGateway:
    """Everything the screen does, scoped to (tenant, account)."""

    def __init__(
        self,
        service: ConversationService | None = None,
        repository: ConversationRepository | None = None,
        outbox: ConversationOutboxRepository | None = None,
        store: ConversationsStore | None = None,
        accounts: AccountsReader | None = None,
        sink: MediaSink | None = None,
        viewer: MediaViewer | None = None,
        connections: ConnectionResolver | None = None,
        drafts: ConversationDraftService | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._service = service
        self._repository = repository
        self._outbox = outbox
        self._store: ConversationsStore = store or PostgresConversationsStore()
        self._accounts: AccountsReader = accounts or _production_accounts
        self._sink = sink
        self._viewer: MediaViewer = viewer or _production_viewer
        self._connections: ConnectionResolver = connections or _production_connection
        self._drafts = drafts
        self._clock = clock

    # --- lazy production wiring --------------------------------------------------------

    @property
    def service(self) -> ConversationService:
        if self._service is None:
            from qualify_api.conversations.composition import (  # noqa: PLC0415
                production_conversation_service,
            )

            self._service = production_conversation_service()
        return self._service

    @property
    def repository(self) -> ConversationRepository:
        if self._repository is None:
            from qualify_api.conversations.composition import (  # noqa: PLC0415
                production_repository,
            )

            self._repository = production_repository()
        return self._repository

    @property
    def outbox(self) -> ConversationOutboxRepository:
        if self._outbox is None:
            from qualify_api.conversations.composition import production_outbox  # noqa: PLC0415

            self._outbox = production_outbox()
        return self._outbox

    @property
    def sink(self) -> MediaSink:
        if self._sink is None:
            self._sink = _production_sink()
        return self._sink

    @property
    def drafts(self) -> ConversationDraftService:
        if self._drafts is None:
            from qualify_api.conversations.composition import (  # noqa: PLC0415
                production_draft_service,
            )

            self._drafts = production_draft_service()
        return self._drafts

    # --- context -----------------------------------------------------------------------

    def timezone(self, tenant_id: UUID) -> str:
        return self._store.timezone(tenant_id)

    def acting_user(self, tenant_id: UUID, email: str) -> UUID | None:
        return self._store.user_id_for_email(tenant_id, email)

    def accounts(self, tenant_id: UUID) -> list[AccountVM]:
        """The tenant's Instagram connections that are not revoked (degraded ones stay:
        their threads are still readable, and the banner says what to do)."""
        return self._accounts(tenant_id)

    def access(self, tenant_id: UUID, connection_id: UUID) -> SyncStateRecord | None:
        return self.repository.get_sync_state(
            tenant_id=tenant_id, connection_id=connection_id, channel=CHANNEL_DM
        )

    # --- reads -------------------------------------------------------------------------

    def threads(self, tenant_id: UUID, connection_id: UUID) -> list[ThreadListing]:
        views = self.service.list_threads(
            tenant_id=tenant_id,
            channels=[CHANNEL_DM],
            connection_id=connection_id,
            limit=THREADS_LIMIT,
        )
        extras = self._store.thread_extras(tenant_id, [v.thread.id for v in views])
        return [
            ThreadListing(view=v, extra=extras.get(str(v.thread.id), ThreadExtra())) for v in views
        ]

    def _owned(self, tenant_id: UUID, connection_id: UUID, thread_id: UUID) -> ThreadView:
        view = self.service.get_thread(tenant_id=tenant_id, thread_id=thread_id)
        if view.thread.connection_id != connection_id or view.thread.channel != CHANNEL_DM:
            raise ThreadNotFound(str(thread_id))
        return view

    def _media_source(self, tenant_id: UUID, record: MessageRecord) -> str:
        if not record.media_type:
            return ""
        if record.media_object_key:
            return self._viewer(tenant_id, record.media_object_key, record.media_type, None)
        # Inbound, or an outbound ECHO the sync ingested (sent from the Instagram app or a
        # retry Meta accepted): the channel's own CDN URL is all there is.
        return record.media_url or ""

    def _unsent(self, tenant_id: UUID, thread_id: UUID) -> list[UnsentItem]:
        horizon = self._clock() - FAILED_VISIBLE_FOR
        rows = [
            r
            for r in self.outbox.list_for_thread(tenant_id=tenant_id, thread_id=thread_id)
            if r.status in UNSENT_STATUSES and r.created_at >= horizon
        ]
        return [
            UnsentItem(
                id=str(r.id),
                status=r.status,
                text=outbox_text(r.payload),
                created_at=r.created_at,
                error_code=r.error_code,
                media_type=r.media_type,
                media_src=(
                    self._viewer(tenant_id, r.media_object_key, r.media_type, None)
                    if r.media_object_key and r.media_type
                    else ""
                ),
            )
            for r in rows[-UNSENT_LIMIT:]
        ]

    def conversation(self, tenant_id: UUID, connection_id: UUID, thread_id: UUID) -> Conversation:
        view = self._owned(tenant_id, connection_id, thread_id)
        messages = list(
            self.service.list_messages(
                tenant_id=tenant_id, thread_id=thread_id, limit=MESSAGES_PAGE
            )
        )
        return Conversation(
            view=view,
            messages=messages,
            unsent=self._unsent(tenant_id, thread_id),
            media_sources={str(m.id): self._media_source(tenant_id, m) for m in messages},
            pending_draft=self.drafts.pending_for(tenant_id=tenant_id, thread_id=thread_id),
        )

    # --- writes ------------------------------------------------------------------------

    def mark_read(self, tenant_id: UUID, connection_id: UUID, thread_id: UUID) -> ThreadView:
        self._owned(tenant_id, connection_id, thread_id)
        return self.service.mark_read(tenant_id=tenant_id, thread_id=thread_id)

    def hide_message(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, message_id: UUID
    ) -> bool:
        """«Eliminar para mí» — local only; Instagram's API has no unsend and no edit."""
        self._owned(tenant_id, connection_id, thread_id)
        return self.service.hide_message(
            tenant_id=tenant_id, thread_id=thread_id, message_id=message_id
        )

    def _approval(self, user_id: UUID, draft_id: UUID | None = None) -> HumanApproval:
        return HumanApproval(user_id=user_id, approved_at=self._clock(), draft_id=draft_id)

    def reply(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        text: str,
        draft_id: UUID | None = None,
    ) -> list[UUID]:
        """Queue a human-approved reply — one outbox row per ≤ 1000-char part. The
        approval is THIS user, NOW, carrying the draft it came from when it did."""
        self._owned(tenant_id, connection_id, thread_id)
        return self.service.reply_text(
            tenant_id=tenant_id,
            thread_id=thread_id,
            text=text,
            approval=self._approval(user_id, draft_id),
        )

    def reply_sticker(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, user_id: UUID
    ) -> UUID:
        """Queue a human-approved heart (`like_heart`): the one sticker Instagram sends."""
        self._owned(tenant_id, connection_id, thread_id)
        return self.service.reply_sticker(
            tenant_id=tenant_id,
            thread_id=thread_id,
            sticker=STICKER_LIKE_HEART,
            approval=self._approval(user_id),
        )

    def stage_attachment(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        *,
        name: str,
        content_type: str,
        media_type: str,
        data: bytes,
    ) -> AttachmentVM:
        """Put the file in R2 under this tenant's prefix (`media_key`, keyed by the
        account it will be sent from). Nothing is queued yet: the person still has to
        press «Responder»."""
        key = media_key(tenant_id, connection_id, f"dm-{uuid4().hex}")
        self.sink.put_media(tenant_id, key, io.BytesIO(data), content_type)
        return AttachmentVM(
            object_key=key,
            media_type=media_type,
            content_type=content_type,
            name=name,
            preview_src=self._viewer(tenant_id, key, media_type, content_type),
        )

    def reply_media(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        attachment: AttachmentVM,
    ) -> UUID:
        """Queue a human-approved media reply (the attachment already staged in R2)."""
        self._owned(tenant_id, connection_id, thread_id)
        media = OutboxMedia(
            object_key=attachment.object_key,
            media_type=attachment.media_type,
            content_type=attachment.content_type,
        )
        return self.service.reply_media(
            tenant_id=tenant_id, thread_id=thread_id, media=media, approval=self._approval(user_id)
        )

    # --- assisted replies (E4) ---------------------------------------------------------

    def suggest(self, tenant_id: UUID, connection_id: UUID, thread_id: UUID) -> ConversationDraft:
        """One model-written draft for the thread's last inbound (or the one already
        pending). Raises `ThreadNotFound`, `SuggestionRefused`, `ClaudeToolError`."""
        self._owned(tenant_id, connection_id, thread_id)
        return self.drafts.suggest(tenant_id=tenant_id, thread_id=thread_id)

    def decide_draft(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        *,
        status: DraftStatus,
        final_text: str | None,
        user_id: UUID,
    ) -> ConversationDraft:
        return self.drafts.decide(
            tenant_id=tenant_id,
            draft_id=draft_id,
            status=status,
            final_text=final_text,
            user_id=user_id,
        )

    # --- presence ----------------------------------------------------------------------

    async def signal(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, action: str
    ) -> bool:
        """`mark_seen` / `typing_on` / `typing_off` to the counterpart. Best-effort."""
        import asyncio  # noqa: PLC0415

        connection = await asyncio.to_thread(self._connections, tenant_id, connection_id)
        if connection is None:
            return False
        return await self.service.signal(
            tenant_id=tenant_id, thread_id=thread_id, connection=connection, action=action
        )


_GATEWAY: ConversationsGateway | None = None


def gateway() -> ConversationsGateway:
    """The production gateway (Postgres repositories), built once per process."""
    global _GATEWAY  # noqa: PLW0603
    if _GATEWAY is None:
        _GATEWAY = ConversationsGateway()
    return _GATEWAY
