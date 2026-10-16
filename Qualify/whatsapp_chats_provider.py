"""The seam between the Chats tab of `/whatsapp` (WA-11, QUA-210) and the real backend.

**In process, not over HTTP** — same posture as `connections_provider.py` and
`inbox_provider.py`: the Reflex app calls `qualify_api.whatsapp.chats.ChatService` (the
very service `http/whatsapp_routes.py` wraps, WA-10) with the session's tenant, and RLS
(`tenant_session`, the `qualify_app` role) scopes every statement. Nothing here talks to
Meta: a send is a `whatsapp_outbox` row that the WA-08 sender drains, and the service
refuses it BEFORE writing when the 24 h window is closed (`WindowClosed`).

What this module adds on top of the service — four small reads the service does not
expose, all through `tenant_session` (`PostgresChatsStore`):

- the tenant's **team** (`users`, RLS-scoped: 1 login = 1 tenant, migration 0008) for
  «Asignar» and the row initials;
- the **acting user**: `AuthState` carries the login email, not a user id, so it is
  resolved here against `users (tenant_id, email)` (`uq_users_tenant_email`) — the id the
  service records as `paused_by_user_id` / `created_by_user_id`;
- the thread's **`whatsapp_thread_state.context`**, from which `orders.read_order` builds
  the order card and `orders.order_ready_text` the «Pedido listo» reply (WA-15);
- the thread's **unsent `whatsapp_outbox` rows** (pending / sending / failed / dead): a
  person's reply is not a `messages` row until the sender delivers it, and a refused one
  (`window_closed`, Meta `131047`) never becomes one — the backend docs say «WA-11 shows
  it», and this is where it comes from;
- the tenant's **IANA zone**, so every time on screen is local (same rule as the
  Planificador's `tenant_timezone`).

**Inbound media (0061)** goes through the very `MediaLocator` the HTTP route
`GET /api/whatsapp/media/{message_id}` uses (`whatsapp.media.production_media_locator`:
download from Meta on the first request, copy to R2, answer a 15-minute public-media
URL), called in process: `media_url` returns that URL or raises the locator's own
`MediaMessageNotFound` / `MediaNotCaptured` / `MediaExpired` / `MediaUnavailable`. The
locator is built lazily, once; a build failure (R2 / Redis / public base URL / Meta env
missing) surfaces as `MediaUnavailable` and is retried on the next request instead of
being cached. Number scoping is the state's: it only asks for message ids of the
conversation it loaded through `conversation` (which `_owned` already scoped to the
number); RLS bounds the read to the tenant either way.

**Number scoping.** The tab shows ONE number (`WhatsAppState.selected_connection_id`).
Every thread-level call re-reads the thread and refuses (`ThreadNotFound`) one that
belongs to another number of the same tenant, so a stale or forged thread id from the
browser can never act across numbers — RLS already stops it across tenants.

All functions are blocking (SQLAlchemy is synchronous): the state runs them through
`asyncio.to_thread`. `ChatsGateway` takes the service and the store by injection so
`test_whatsapp_chats_provider.py` drives it with the in-memory repositories.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from qualify_api.tenancy.models import Tenant, User
from qualify_api.whatsapp.chats import (
    ButtonsSend,
    ChatService,
    ImageSend,
    MediaLocator,
    MediaUnavailable,
    MessageRecord,
    ReplyButton,
    TextSend,
    ThreadNotFound,
    ThreadSummary,
)
from qualify_api.whatsapp.models import WhatsAppOutboxItem, WhatsAppThreadState
from qualify_api.whatsapp.orders import OrderSummary, order_ready_text, read_order
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from .whatsapp_chats_vm import (
    MESSAGES_PAGE,
    THREADS_LIMIT,
    AgentVM,
    UnsentItem,
    build_agent_vm,
    clean_titles,
    outbox_text,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/Bogota"
UNSENT_STATUSES = ("pending", "sending", "failed", "dead")
#: A refused reply stays visible this long; older failures are history, not a to-do.
FAILED_VISIBLE_FOR = timedelta(days=7)
UNSENT_LIMIT = 20


class NoOrder(LookupError):
    """«Pedido listo» on a thread whose state holds no confirmed order."""


# ======================================================================================
# Store: the reads the ChatService does not expose
# ======================================================================================


class ChatsStore(Protocol):
    def agents(self, tenant_id: UUID) -> list[AgentVM]: ...

    def user_id_for_email(self, tenant_id: UUID, email: str) -> UUID | None: ...

    def thread_context(self, tenant_id: UUID, thread_id: UUID) -> dict[str, Any]: ...

    def unsent(self, tenant_id: UUID, thread_id: UUID, now: datetime) -> list[UnsentItem]: ...

    def timezone(self, tenant_id: UUID) -> str: ...


class PostgresChatsStore:
    """`tenant_session(tenant_id)` per call — the only sanctioned door."""

    def agents(self, tenant_id: UUID) -> list[AgentVM]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(User.id, User.display_name, User.email).order_by(
                    func.lower(User.display_name), User.id
                )
            ).all()
        return [build_agent_vm(str(r.id), r.display_name, r.email) for r in rows]

    def user_id_for_email(self, tenant_id: UUID, email: str) -> UUID | None:
        if not email.strip():
            return None
        with tenant_session(tenant_id) as session:
            return session.execute(
                select(User.id).where(func.lower(User.email) == email.strip().lower())
            ).scalar_one_or_none()

    def thread_context(self, tenant_id: UUID, thread_id: UUID) -> dict[str, Any]:
        with tenant_session(tenant_id) as session:
            context = session.execute(
                select(WhatsAppThreadState.context).where(
                    WhatsAppThreadState.thread_id == thread_id
                )
            ).scalar_one_or_none()
        return dict(context) if isinstance(context, dict) else {}

    def unsent(self, tenant_id: UUID, thread_id: UUID, now: datetime) -> list[UnsentItem]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(
                    WhatsAppOutboxItem.id,
                    WhatsAppOutboxItem.status,
                    WhatsAppOutboxItem.payload,
                    WhatsAppOutboxItem.created_at,
                    WhatsAppOutboxItem.error_code,
                )
                .where(
                    WhatsAppOutboxItem.thread_id == thread_id,
                    WhatsAppOutboxItem.status.in_(UNSENT_STATUSES),
                    WhatsAppOutboxItem.created_at >= now - FAILED_VISIBLE_FOR,
                )
                .order_by(WhatsAppOutboxItem.created_at.desc())
                .limit(UNSENT_LIMIT)
            ).all()
        return [
            UnsentItem(
                id=str(r.id),
                status=r.status,
                text=outbox_text(r.payload or {}),
                created_at=r.created_at,
                error_code=r.error_code,
            )
            for r in reversed(rows)
        ]

    def timezone(self, tenant_id: UUID) -> str:
        with tenant_session(tenant_id) as session:
            zone = session.execute(
                select(Tenant.timezone).where(Tenant.id == tenant_id)
            ).scalar_one_or_none()
        return zone or DEFAULT_TIMEZONE


# ======================================================================================
# Read shapes
# ======================================================================================


@dataclass(frozen=True)
class Conversation:
    """One thread's newest page, plus what decorates it."""

    summary: ThreadSummary
    messages: list[MessageRecord]
    unsent: list[UnsentItem]
    order: OrderSummary | None
    has_more: bool


@dataclass(frozen=True)
class OlderPage:
    messages: list[MessageRecord]
    has_more: bool


# ======================================================================================
# Gateway
# ======================================================================================


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ChatsGateway:
    """Everything the Chats tab does, scoped to (tenant, number)."""

    def __init__(
        self,
        service: ChatService | None = None,
        store: ChatsStore | None = None,
        clock: Callable[[], datetime] = _utcnow,
        media_locator: MediaLocator | None = None,
    ) -> None:
        self._service = service
        self._store: ChatsStore = store or PostgresChatsStore()
        self._clock = clock
        self._media_locator = media_locator

    @property
    def service(self) -> ChatService:
        if self._service is None:
            from qualify_api.whatsapp.chats import production_chat_service  # noqa: PLC0415

            self._service = production_chat_service()
        return self._service

    def _locator(self) -> MediaLocator:
        if self._media_locator is None:
            from qualify_api.whatsapp.media import production_media_locator  # noqa: PLC0415

            try:
                self._media_locator = production_media_locator()
            except Exception as exc:  # missing R2/Redis/public-URL/Meta env: retry next time
                logger.error("whatsapp media locator unavailable: %s", type(exc).__name__)
                raise MediaUnavailable("media locator is not configured") from exc
        return self._media_locator

    async def media_url(self, tenant_id: UUID, message_id: UUID) -> str:
        """A short-lived URL for an inbound media message's bytes (module docstring,
        "Inbound media"). Async: the locator is; it runs its own blocking steps off the
        event loop."""
        return await self._locator().locate(tenant_id=tenant_id, message_id=message_id)

    # --- context -----------------------------------------------------------------------

    def timezone(self, tenant_id: UUID) -> str:
        return self._store.timezone(tenant_id)

    def agents(self, tenant_id: UUID) -> list[AgentVM]:
        return self._store.agents(tenant_id)

    def acting_user(self, tenant_id: UUID, email: str) -> UUID | None:
        return self._store.user_id_for_email(tenant_id, email)

    # --- reads -------------------------------------------------------------------------

    def threads(self, tenant_id: UUID, connection_id: UUID) -> list[ThreadSummary]:
        """All of this number's conversations (both statuses: the filters are local)."""
        return self.service.list_threads(
            tenant_id, connection_id=connection_id, status=None, limit=THREADS_LIMIT
        )

    def _owned(self, tenant_id: UUID, connection_id: UUID, thread_id: UUID) -> ThreadSummary:
        summary = self.service.get_thread_summary(tenant_id, thread_id)
        if summary.connection_id != connection_id:
            raise ThreadNotFound(str(thread_id))
        return summary

    def conversation(self, tenant_id: UUID, connection_id: UUID, thread_id: UUID) -> Conversation:
        summary = self._owned(tenant_id, connection_id, thread_id)
        messages = list(
            self.service.list_messages(tenant_id, thread_id, before=None, limit=MESSAGES_PAGE)
        )
        return Conversation(
            summary=summary,
            messages=messages,
            unsent=self._store.unsent(tenant_id, thread_id, self._clock()),
            order=read_order(self._store.thread_context(tenant_id, thread_id)),
            has_more=len(messages) >= MESSAGES_PAGE,
        )

    def older(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, before: datetime
    ) -> OlderPage:
        self._owned(tenant_id, connection_id, thread_id)
        messages = list(
            self.service.list_messages(tenant_id, thread_id, before=before, limit=MESSAGES_PAGE)
        )
        return OlderPage(messages=messages, has_more=len(messages) >= MESSAGES_PAGE)

    # --- sends (each pauses the automation server-side, WA-10) ------------------------

    def send_text(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, user_id: UUID, text: str
    ) -> UUID:
        self._owned(tenant_id, connection_id, thread_id)
        return self.service.send(tenant_id, thread_id, user_id, TextSend(text=text.strip()))

    def send_buttons(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        text: str,
        titles: Sequence[str],
    ) -> UUID:
        self._owned(tenant_id, connection_id, thread_id)
        buttons = [
            ReplyButton(id=f"btn_{i}", title=title)
            for i, title in enumerate(clean_titles(titles), start=1)
        ]
        body = ButtonsSend(text=text.strip(), buttons=buttons)
        return self.service.send(tenant_id, thread_id, user_id, body)

    def send_image(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        link: str,
        caption: str,
    ) -> UUID:
        self._owned(tenant_id, connection_id, thread_id)
        body = ImageSend(link=link.strip(), caption=caption.strip() or None)  # type: ignore[arg-type]
        return self.service.send(tenant_id, thread_id, user_id, body)

    def send_order_ready(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, user_id: UUID
    ) -> UUID:
        """«Pedido listo»: the text is built server-side from the stored order, never
        taken from the browser."""
        self._owned(tenant_id, connection_id, thread_id)
        order = read_order(self._store.thread_context(tenant_id, thread_id))
        if order is None:
            raise NoOrder(str(thread_id))
        return self.service.send(
            tenant_id, thread_id, user_id, TextSend(text=order_ready_text(order))
        )

    # --- actions -----------------------------------------------------------------------

    def assign(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, agent_id: UUID | None
    ) -> None:
        self._owned(tenant_id, connection_id, thread_id)
        self.service.assign(tenant_id, thread_id, agent_id)

    def close(self, tenant_id: UUID, connection_id: UUID, thread_id: UUID) -> None:
        self._owned(tenant_id, connection_id, thread_id)
        self.service.close(tenant_id, thread_id)

    def reopen(self, tenant_id: UUID, connection_id: UUID, thread_id: UUID) -> None:
        self._owned(tenant_id, connection_id, thread_id)
        self.service.reopen(tenant_id, thread_id)

    def takeover(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, user_id: UUID
    ) -> None:
        self._owned(tenant_id, connection_id, thread_id)
        self.service.takeover(tenant_id, thread_id, user_id)

    def resume(self, tenant_id: UUID, connection_id: UUID, thread_id: UUID) -> None:
        self._owned(tenant_id, connection_id, thread_id)
        self.service.resume(tenant_id, thread_id)


_GATEWAY: ChatsGateway | None = None


def gateway() -> ChatsGateway:
    """The production gateway (Postgres repositories), built once per process."""
    global _GATEWAY  # noqa: PLW0603
    if _GATEWAY is None:
        _GATEWAY = ChatsGateway()
    return _GATEWAY
