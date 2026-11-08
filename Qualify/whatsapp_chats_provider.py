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

**Approved messages from an expired chat (m-24848535).** `template_options` and
`send_template` go through `qualify_api.whatsapp.template_reply.TemplateReplyService`,
scoped to the number like every other thread call: the service decides which approved
templates this person may receive (follow-ups after a chat, promotions only with an
explicit opt-in) and refuses the rest server-side; the send is a `template_reply` outbox
row keyed by the screen's `request_key`, so a double tap queues once.

**The send panel — the composer's «+» (m-24945888, m-24955785).**
`list_products_for_chat`, `list_pieces_for_chat`, `menu_preview` and
the four sends (`send_product`, `send_piece`, `send_menu_list`, `send_photo`) are thin
wrappers over `qualify_api.whatsapp.attachments.ChatAttachmentService`, scoped to the
number like every other thread call. The service owns every rule (window, takeover, R2
copy, size/type, caption length, provenance); a refusal is its `AttachmentRefused`
(`reason`), `ProductNotFound` / `PieceNotFound`, or the chat's `WindowClosed`. A
product photo's `thumb_url` is "" when it lives in the local upload store — the page
resolves `thumb_key` with `rx.get_upload_url`, like the catalog screen.

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
from qualify_api.whatsapp.attachments import (
    ChatAttachmentService,
    MenuPreview,
    PaymentPick,
    PiecePick,
    ProductPick,
)
from qualify_api.whatsapp.chats import (
    ButtonsSend,
    ChatService,
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
from qualify_api.whatsapp.payment_status import PaymentStatus, PaymentStatusService
from qualify_api.whatsapp.template_reply import TemplateReplyOptions, TemplateReplyService
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from .whatsapp_chats_vm import (
    MESSAGES_PAGE,
    THREADS_LIMIT,
    AgentVM,
    DirectionsVM,
    SeasonalPickVM,
    UnsentItem,
    build_agent_vm,
    build_seasonal_picks,
    clean_titles,
    map_href,
    outbox_text,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/Bogota"
UNSENT_STATUSES = ("pending", "sending", "failed", "dead")
#: A refused reply stays visible this long; older failures are history, not a to-do.
FAILED_VISIBLE_FOR = timedelta(days=7)
UNSENT_LIMIT = 20


class SeasonalSendNotConnected(RuntimeError):
    """m-24976894 is not wired yet: the chat cannot send a seasonal medium."""


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
                    WhatsAppOutboxItem.preview_text,
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
                # 0087: a template reply carries the text the person reads.
                text=r.preview_text or outbox_text(r.payload or {}),
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


@dataclass(frozen=True)
class PickerScope:
    """What the send panel needs about the number: the business whose products and pieces
    it lists (`None` when the number has none), and its rubro as «Tu marca» saved it —
    the niche key and the owner's own words — so the caption asks the right question."""

    brand_id: UUID | None
    sector: str = ""
    rubro: str = ""


def picker_scope(tenant_id: UUID, connection_id: UUID) -> PickerScope:
    """Postgres only, under RLS (`number_scope`, `BrandKitStore`): no Graph call."""
    from qualify_api.creative.brand_kit_store import BrandKitStore  # noqa: PLC0415

    from .whatsapp_menu_provider import number_scope  # noqa: PLC0415
    from .whatsapp_provider import UnknownWhatsAppNumber  # noqa: PLC0415

    try:
        scope = number_scope(tenant_id, connection_id)
    except UnknownWhatsAppNumber:
        return PickerScope(brand_id=None)
    if scope.brand_id is None:
        return PickerScope(brand_id=None)
    connect = BrandKitStore().load_details(tenant_id=tenant_id, brand_id=scope.brand_id).connect
    connect = connect if isinstance(connect, dict) else {}
    return PickerScope(
        brand_id=scope.brand_id,
        sector=str(connect.get("sector") or "").strip(),
        rubro=str(connect.get("rubro_text") or "").strip(),
    )


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
        template_replies: TemplateReplyService | None = None,
        attachments: ChatAttachmentService | None = None,
        payments: PaymentStatusService | None = None,
        promotions: Any = None,
        directions: Any = None,
    ) -> None:
        self._attachments = attachments
        self._payments = payments
        self._promotions = promotions
        self._directions = directions
        self._service = service
        self._store: ChatsStore = store or PostgresChatsStore()
        self._clock = clock
        self._media_locator = media_locator
        self._template_replies = template_replies

    @property
    def template_replies(self) -> TemplateReplyService:
        if self._template_replies is None:
            from qualify_api.whatsapp.template_reply import (  # noqa: PLC0415
                production_template_reply_service,
            )

            self._template_replies = production_template_reply_service()
        return self._template_replies

    @property
    def service(self) -> ChatService:
        if self._service is None:
            from qualify_api.whatsapp.chats import production_chat_service  # noqa: PLC0415

            self._service = production_chat_service()
        return self._service

    @property
    def attachments(self) -> ChatAttachmentService:
        if self._attachments is None:
            from qualify_api.whatsapp.attachments import (  # noqa: PLC0415
                production_attachment_service,
            )

            self._attachments = production_attachment_service(self.service)
        return self._attachments

    @property
    def payments(self) -> PaymentStatusService:
        if self._payments is None:
            from qualify_api.whatsapp.payment_status import (  # noqa: PLC0415
                production_payment_status_service,
            )

            self._payments = production_payment_status_service(self.service)
        return self._payments

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

    # --- the send panel («+», m-24945888 / m-24955785) -------------------------------

    @property
    def promotions(self) -> Any:
        """`WeeklyPromotionService` (m-24945889): the business's marked offer."""
        if self._promotions is None:
            from qualify_api.whatsapp.promotions import (  # noqa: PLC0415
                production_weekly_promotion_service,
            )

            self._promotions = production_weekly_promotion_service()
        return self._promotions

    @property
    def directions(self) -> Any:
        """`DirectionsService` (m-24945889): the number's map point and «Cómo llegar»."""
        if self._directions is None:
            from qualify_api.whatsapp.directions import (  # noqa: PLC0415
                production_directions_service,
            )

            self._directions = production_directions_service(self.service)
        return self._directions

    def picker_scope(self, tenant_id: UUID, connection_id: UUID) -> PickerScope:
        return picker_scope(tenant_id, connection_id)

    # --- stickers and videos of the brand (m-24976895, `docs/ux-stickers-videos.md` §3) ---

    def approved_seasonal(self, tenant_id: UUID, brand_id: UUID) -> list[SeasonalPickVM]:
        """Only `approved` media of unarchived seasons, current season first (the
        backend's `list_approved_for_chat`), each with its signed preview."""
        from .seasonal_provider import gateway as seasonal_gateway  # noqa: PLC0415

        seasonal = seasonal_gateway()
        rows = seasonal.approved_for_chat(tenant_id, brand_id)
        return build_seasonal_picks(rows, lambda row: seasonal.preview_src(tenant_id, row))

    def send_seasonal_media(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        media_id: UUID,
        caption: str,
        request_key: str | None = None,
    ) -> UUID:
        """STUB until m-24976894 (the WhatsApp send of a sticker or a video through the
        approved outbox): the coordinator connects it. Refuses plainly meanwhile."""
        self._owned(tenant_id, connection_id, thread_id)
        raise SeasonalSendNotConnected(str(media_id))

    # --- Tu oferta and Cómo llegar (m-24945889, `docs/ux-whatsapp-atajos.md`) ----------

    def weekly_promotion(self, tenant_id: UUID, brand_id: UUID) -> Any:
        """The business's marked offer (`WeeklyPromotion`: draft_id, marked_at) or None."""
        return self.promotions.get_weekly_promotion(tenant_id=tenant_id, brand_id=brand_id)

    def directions_preview(self, tenant_id: UUID, connection_id: UUID) -> DirectionsVM:
        """What «Cómo llegar» would send: the pin, or the backend's own address text."""
        from qualify_api.whatsapp.directions import (  # noqa: PLC0415
            DIRECTIONS_TEXT,
            NumberNotFound,
            maps_link,
        )

        try:
            found = self.directions.get_location(tenant_id=tenant_id, connection_id=connection_id)
        except NumberNotFound:
            return DirectionsVM(present=True)
        address = found.address or ""
        if found.has_point:
            return DirectionsVM(
                present=True,
                empty=False,
                has_point=True,
                name=found.name or "",
                address=address,
                map_href=map_href(found.latitude, found.longitude),
            )
        if not address:
            return DirectionsVM(present=True)
        return DirectionsVM(
            present=True,
            empty=False,
            name=found.name or "",
            address=address,
            text=DIRECTIONS_TEXT.format(address=address, link=maps_link(address)),
        )

    def send_directions(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        request_key: str | None = None,
    ) -> UUID:
        """«Cómo llegar» › «Enviar» — only ever the owner's tap."""
        self._owned(tenant_id, connection_id, thread_id)
        return self.directions.send_directions(
            tenant_id, thread_id, user_id, request_key=request_key
        )

    def list_products_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[ProductPick]:
        return self.attachments.list_products_for_chat(tenant_id, brand_id)

    def list_pieces_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[PiecePick]:
        return self.attachments.list_pieces_for_chat(tenant_id, brand_id)

    def menu_preview(self, tenant_id: UUID, connection_id: UUID) -> MenuPreview:
        return self.attachments.menu_preview(tenant_id, connection_id)

    def send_product(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        product_id: UUID,
        caption: str,
        request_key: str | None = None,
    ) -> UUID:
        self._owned(tenant_id, connection_id, thread_id)
        return self.attachments.send_product(
            tenant_id, thread_id, user_id, product_id, caption, request_key=request_key
        )

    def send_piece(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        draft_id: UUID,
        caption: str,
        request_key: str | None = None,
    ) -> UUID:
        self._owned(tenant_id, connection_id, thread_id)
        return self.attachments.send_piece(
            tenant_id, thread_id, user_id, draft_id, caption, request_key=request_key
        )

    def send_menu_list(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        request_key: str | None = None,
    ) -> UUID:
        self._owned(tenant_id, connection_id, thread_id)
        return self.attachments.send_menu_list(
            tenant_id, thread_id, user_id, request_key=request_key
        )

    def send_photo(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        content: bytes,
        content_type: str,
        filename: str,
        caption: str,
        request_key: str | None = None,
    ) -> UUID:
        self._owned(tenant_id, connection_id, thread_id)
        return self.attachments.send_photo(
            tenant_id,
            thread_id,
            user_id,
            content,
            content_type,
            filename,
            caption,
            request_key=request_key,
        )

    # --- payment (m-24955648, spec `docs/ux-paso-de-pago.md` §4–§5) --------------------

    def list_payment_methods_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[PaymentPick]:
        return self.attachments.list_payment_methods_for_chat(tenant_id, brand_id)

    def payment_card_preview(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, method_id: UUID
    ) -> str:
        self._owned(tenant_id, connection_id, thread_id)
        return self.attachments.payment_card_preview(tenant_id, connection_id, thread_id, method_id)

    def send_payment_method(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        method_id: UUID,
        request_key: str | None = None,
    ) -> UUID:
        self._owned(tenant_id, connection_id, thread_id)
        return self.attachments.send_payment_method(
            tenant_id, thread_id, user_id, method_id, request_key=request_key
        )

    def payment_status(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID
    ) -> PaymentStatus | None:
        self._owned(tenant_id, connection_id, thread_id)
        return self.payments.payment_for(tenant_id, thread_id)

    def payment_statuses(
        self, tenant_id: UUID, thread_ids: Sequence[UUID]
    ) -> dict[UUID, PaymentStatus]:
        """For the chats list (RLS bounds it to the tenant; the ids come from `threads`)."""
        return self.payments.payments_for(tenant_id, thread_ids)

    def confirm_payment(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        message: str,
        request_key: str | None = None,
    ) -> UUID:
        """«Enviar y marcar pagado» — only ever the owner's tap."""
        self._owned(tenant_id, connection_id, thread_id)
        return self.payments.confirm_payment(
            tenant_id, thread_id, user_id, message, request_key=request_key
        )

    def mark_paid_without_message(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, user_id: UUID
    ) -> None:
        """«Marcar pagado sin avisar» (the 24 h window is closed)."""
        self._owned(tenant_id, connection_id, thread_id)
        self.payments.mark_paid_without_message(tenant_id, thread_id, user_id)

    # --- approved messages from an expired chat (m-24848535) ---------------------------

    def template_options(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID
    ) -> TemplateReplyOptions:
        self._owned(tenant_id, connection_id, thread_id)
        return self.template_replies.options(tenant_id, thread_id)

    def send_template(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        template_id: UUID,
        values: dict[str, str],
        request_key: str,
    ) -> UUID:
        """Only ever called from the owner's «Enviar» (N13). The service re-checks the
        template and the permission; nothing the browser sends becomes the body."""
        self._owned(tenant_id, connection_id, thread_id)
        return self.template_replies.send(
            tenant_id,
            thread_id,
            user_id,
            template_id=template_id,
            values=values,
            request_key=request_key,
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
