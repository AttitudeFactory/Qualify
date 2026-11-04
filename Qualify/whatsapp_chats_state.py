"""Reflex state for the Chats tab of `/whatsapp` (WA-11, QUA-210).

A separate `rx.State`, not a substate of `WhatsAppState`: it only READS the shell's
selection (`selected_connection_id`, server-side through `get_state`, never as an event
argument from the browser) and owns everything else. It holds only the frozen VMs of
`whatsapp_chats_vm.py` in client vars; the raw message records the «cargar anteriores» /
refresh merge needs live in backend-only (`_`) vars and never reach the browser.

**Loading.** The shell renders the active tab inside a box keyed by the selected number,
so the tab root's `on_mount` (`enter`) fires on tab entry and on every number switch. It
resets everything tied to another number and loads the list; a double mount (React dev
mode) is absorbed by the `list_loading_for` guard.

**Refresh.** A hidden `rx.moment` heartbeat in the tab (15 s, client-side, unmounted with
the tab — the `/inbox` pattern) calls `refresh`, which re-reads the list and the open
conversation WITHOUT skeletons; `_refreshing` makes overlapping ticks a no-op. Every
action refreshes immediately after it lands. Nothing blocks the UI: every Postgres call
runs in a background event through `asyncio.to_thread`.

**Sends** pause the menu automation server-side (WA-10); the header pill flips to
«Persona» immediately (`_mark_paused`), before the refresh confirms it.

**Inbound media (0061)** is fetched on click only (`request_media`): the id must be an
inbound `has_media` message of the conversation already loaded (`_records`), so a forged
id from the browser asks for nothing. The outcome — a URL with its expiry, or the
locator's failure — lives in the backend-only `_media` and is rendered into the
`MessageVM`s; an image opens in the lightbox (`lightbox_url`, looked up server-side by
message id, never taken from the browser), a video or document opens in a new tab.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import io
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import reflex as rx
from qualify_api.whatsapp.attachments import (
    AttachmentRefused,
    PieceNotFound,
    ProductNotFound,
    product_text,
)
from qualify_api.whatsapp.chats import (
    MediaExpired,
    MediaMessageNotFound,
    MediaNotCaptured,
    MediaUnavailable,
    MessageRecord,
    ThreadNotFound,
    UnknownAgent,
    WindowClosed,
)
from qualify_api.whatsapp.template_reply import (
    MissingValues,
    NoPermission,
    PromotionNeedsConsent,
    TemplateNotAvailable,
    TemplateOption,
    TemplateReplyOptions,
    render_preview,
    variable_examples,
)
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .nav_url import (
    back_url_script,
    close_flow_script,
    conversation_href,
    flow_param,
    push_url_script,
    replace_url_script,
    thread_param,
    uuid_param,
)
from .pending_state import PendingState
from .tenant import tenant_uuid
from .ui.steps import settle_step
from .whatsapp_chats_provider import NoOrder, gateway
from .whatsapp_chats_vm import (
    COMPOSE_BUTTONS,
    COMPOSE_KEYS,
    COMPOSE_TEXT,
    DEFAULT_FILTER,
    EMPTY_MENU,
    EMPTY_ORDER,
    EMPTY_PIECE,
    EMPTY_PRODUCT,
    EMPTY_THREAD,
    FILTER_CLOSED,
    FILTER_KEYS,
    FILTER_OPEN,
    FILTER_UNREAD,
    MAX_BUTTON_TITLE_CHARS,
    MAX_CAPTION_CHARS,
    MEDIA_DOCUMENT,
    MEDIA_EXPIRED,
    MEDIA_IMAGE,
    MEDIA_NOT_CAPTURED_CODE,
    MEDIA_NOT_FOUND,
    MEDIA_UNAVAILABLE,
    MEDIA_VIDEO,
    MENU_FAILED,
    NO_PERMISSION_NOTICE,
    PHOTO_REJECTED,
    PHOTO_UNREADABLE,
    PICK_FLOW,
    PICK_MENU,
    PICK_PHOTO,
    PICK_PIECES,
    PICK_PRODUCTS,
    PICK_SOURCES,
    PICK_WINDOW_CLOSED,
    PIECE_GONE,
    PIECE_TAB_KEYS,
    PIECES_APPROVED,
    PIECES_FAILED,
    PIECES_UNAPPROVED,
    PRODUCT_GONE,
    PRODUCT_SEARCH_FROM,
    PRODUCTS_FAILED,
    PROMOTIONS_NEED_CONSENT,
    SEND_LABEL,
    SEND_MENU_LABEL,
    SENDING_LABEL,
    TEMPLATE_FILL_HINT,
    TEMPLATE_PICK_HINT,
    WINDOW_CLOSED_NOTICE,
    WINDOW_CLOSED_PILL,
    AgentVM,
    MediaResolution,
    MenuPreviewVM,
    MessageVM,
    OrderCardVM,
    PieceCardVM,
    ProductCardVM,
    TemplateChoiceVM,
    TemplateFieldVM,
    ThreadRowVM,
    UnsentItem,
    build_conversation,
    build_menu_preview,
    build_order_card,
    build_piece_cards,
    build_product_cards,
    build_template_choice,
    build_template_fields,
    build_thread_row,
    caption_count,
    caption_error,
    composer_enabled,
    filter_counts,
    filter_label,
    filter_products,
    filter_threads,
    is_food_business,
    media_control_for,
    merge_pages,
    mode_pill,
    photo_refusal,
    pick_heading,
    pick_step_help,
    pick_step_title,
    pick_total_steps,
    pieces_in,
    preview_values,
    product_caption,
    refusal_message,
    resolution_after,
    send_failed_message,
    template_fields_complete,
    validate_compose,
)
from .whatsapp_state import WhatsAppState

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LIST_FAILED = "No se pudieron cargar las conversaciones. Vuelve a intentarlo en un momento."
_CONV_FAILED = "No se pudo cargar esta conversación. Vuelve a intentarlo en un momento."
_THREAD_GONE = "Esa conversación ya no está disponible en este número."
_NO_USER = (
    "No encontramos tu usuario en este negocio, así que no podemos firmar la respuesta. "
    "Pide al equipo de Qualify que lo revise."
)
_REJECTED = (
    "WhatsApp no acepta ese mensaje tal como está. Revisa la longitud del texto o de los botones."
)
_ACTION_FAILED = "No se pudo completar la acción. Vuelve a intentarlo en un momento."
_NO_ORDER = "Esta conversación ya no tiene un pedido confirmado."
_UNKNOWN_AGENT = "Esa persona ya no forma parte del equipo."
_QUEUED = "Tu mensaje sale en unos segundos."
_TEMPLATES_FAILED = (
    "No se pudieron cargar tus mensajes aprobados. Vuelve a intentarlo en un momento."
)
_TEMPLATE_GONE = "Ese mensaje ya no está aprobado. Elige otro."
_TOAST_MS = 4000
#: The «Sin asignar» item of the «Asignar» select.
UNASSIGNED = "__none__"

_DB_ERRORS = (SQLAlchemyError,)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


# ======================================================================================
# «Foto o menú» (m-24945888): what one «Enviar» carries, and the call it makes
# ======================================================================================


@dataclass(frozen=True)
class PickSend:
    """One «Enviar» of the picker, frozen when it is tapped. `session` is the picker's
    generation: a result that comes back after the drawer closed or the chat changed is
    discarded. `request_key` is the intent's — a retry reuses it, so it queues once."""

    session: int
    source: str
    thread_id: str
    connection_id: str
    request_key: str
    item_id: str = ""
    caption: str = ""
    photo: bytes = b""
    photo_type: str = ""
    photo_name: str = ""
    as_text: bool = False


def call_pick(
    gw: Any, plan: PickSend, tenant: UUID, connection: UUID, thread: UUID, user: UUID
) -> UUID:
    """The gateway call for one `PickSend` (blocking: run it in a thread)."""
    caption = plan.caption.strip()
    key = plan.request_key
    if plan.source == PICK_PRODUCTS:
        return gw.send_product(
            tenant, connection, thread, user, UUID(plan.item_id), caption, request_key=key
        )
    if plan.source == PICK_PIECES:
        return gw.send_piece(
            tenant, connection, thread, user, UUID(plan.item_id), caption, request_key=key
        )
    if plan.source == PICK_MENU:
        return gw.send_menu_list(tenant, connection, thread, user, request_key=key)
    return gw.send_photo(
        tenant,
        connection,
        thread,
        user,
        plan.photo,
        plan.photo_type,
        plan.photo_name,
        caption,
        request_key=key,
    )


def pick_send_error(exc: BaseException, plan: PickSend) -> str:
    """The owner's words for a refused or failed send (never the exception's text)."""
    if isinstance(exc, WindowClosed):
        return PICK_WINDOW_CLOSED
    if isinstance(exc, AttachmentRefused):
        return refusal_message(exc.reason, plan.source)
    if isinstance(exc, ProductNotFound):
        return PRODUCT_GONE
    if isinstance(exc, PieceNotFound):
        return PIECE_GONE
    if isinstance(exc, ThreadNotFound):
        return _THREAD_GONE
    return send_failed_message(plan.source, as_text=plan.as_text)


#: The phone photo's preview: a small JPEG in a data URL, so the browser never needs a
#: public address for a photo that is not sent yet (the bytes stay backend-only).
_PREVIEW_SIDE = 640


def photo_preview(content: bytes) -> str:
    from PIL import Image  # noqa: PLC0415 — Pillow is the catalog's dependency already

    with Image.open(io.BytesIO(content)) as image:
        image = image.convert("RGB")
        image.thumbnail((_PREVIEW_SIDE, _PREVIEW_SIDE))
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


class WhatsAppChatsState(rx.State):
    """State for the Chats tab."""

    # -- list ---------------------------------------------------------------------------
    rows: list[ThreadRowVM] = []
    agents: list[AgentVM] = []
    filter_key: str = DEFAULT_FILTER
    list_loaded_for: str = ""
    list_loading_for: str = ""
    list_error: str = ""

    # -- conversation -------------------------------------------------------------------
    open_thread_id: str = ""
    messages: list[MessageVM] = []
    order: OrderCardVM = EMPTY_ORDER
    has_more: bool = False
    conv_loaded_for: str = ""
    conv_loading_for: str = ""
    loading_older: bool = False
    conv_error: str = ""

    # -- composer and actions -----------------------------------------------------------
    compose_mode: str = COMPOSE_TEXT
    draft_text: str = ""
    button_1: str = ""
    button_2: str = ""
    button_3: str = ""
    sending: bool = False
    acting: str = ""
    banner: str = ""
    banner_tone: str = "info"

    # -- media lightbox (an image's fresh URL; "" = closed) -----------------------------
    lightbox_url: str = ""

    # -- approved message from an expired chat (m-24848535) -----------------------------
    tpl_open: bool = False
    flow_ready: bool = False
    tpl_loading: bool = False
    tpl_error: str = ""
    tpl_choices: list[TemplateChoiceVM] = []
    tpl_selected: str = ""
    #: Step 2 of the drawer («Completa y revisa») is showing; «Atrás» goes back to the
    #: list keeping the choice and what was typed.
    tpl_reviewing: bool = False
    tpl_fields: list[TemplateFieldVM] = []
    tpl_preview: str = ""
    tpl_promotions_blocked: bool = False
    tpl_consent_id: str = ""
    tpl_has_followups: bool = True
    tpl_no_permission: bool = False
    tpl_sending: bool = False

    # -- «Foto o menú» (m-24945888) -----------------------------------------------------
    pick_open: bool = False
    pick_step: int = 1
    pick_source: str = ""
    pick_loading: bool = False
    #: A list that could not be read (shown with «Reintentar»).
    pick_error: str = ""
    pick_products: list[ProductCardVM] = []
    pick_products_loaded: bool = False
    pick_query: str = ""
    pick_pieces: list[PieceCardVM] = []
    pick_pieces_loaded: bool = False
    pick_piece_tab: str = PIECES_APPROVED
    pick_menu: MenuPreviewVM = EMPTY_MENU
    pick_selected: str = ""
    pick_caption: str = ""
    pick_photo_preview: str = ""
    pick_photo_name: str = ""
    pick_photo_error: str = ""
    pick_sending: bool = False
    #: Why the last «Enviar» did not go (above the button; what was written is kept).
    pick_send_error: str = ""
    #: The 24 h closed while choosing: the drawer offers «Enviar un mensaje aprobado».
    pick_window_closed: bool = False

    # -- backend only -------------------------------------------------------------------
    _connection_id: str = ""
    _zone_name: str = ""
    _user_id: str = ""
    _records: list[MessageRecord] = []
    _unsent: list[UnsentItem] = []
    _order_raw: Any = None
    _refreshing: bool = False
    # message id → what the media locator answered (URL + expiry, or the failure code).
    _media: dict[str, MediaResolution] = {}
    _media_loading: list[str] = []
    # The service's options (with each template's components) and the values typed so
    # far; the request key of the «Enviar» intent, reused by a retry so it queues once.
    _tpl_options: list[TemplateOption] = []
    _tpl_values: dict[str, str] = {}
    _tpl_request_key: str = ""
    # The picker's generation (bumped on every open and close), the chat it opened on,
    # the «Enviar» intent's key, and what the number's business is (read once per number).
    _pick_session: int = 0
    _pick_thread: str = ""
    _pick_request_key: str = ""
    _pick_scope_for: str = ""
    _pick_brand: str = ""
    _pick_food: bool = False
    # The phone photo itself: never sent to the browser (it gets `pick_photo_preview`).
    _pick_photo: bytes = b""
    _pick_photo_type: str = ""

    # ==================================================================================
    # Computed vars
    # ==================================================================================

    @rx.var
    def visible_rows(self) -> list[ThreadRowVM]:
        return filter_threads(self.rows, self.filter_key)

    @rx.var
    def filter_open_label(self) -> str:
        return filter_label(FILTER_OPEN, filter_counts(self.rows)[FILTER_OPEN])

    @rx.var
    def filter_closed_label(self) -> str:
        return filter_label(FILTER_CLOSED, filter_counts(self.rows)[FILTER_CLOSED])

    @rx.var
    def filter_unread_label(self) -> str:
        return filter_label(FILTER_UNREAD, filter_counts(self.rows)[FILTER_UNREAD])

    @rx.var
    def list_ready(self) -> bool:
        """`enter` clears `list_loaded_for` on a number switch, so set = this number."""
        return self.list_loaded_for != ""

    @rx.var
    def list_empty(self) -> bool:
        return self.list_loaded_for != "" and len(self.rows) == 0

    @rx.var
    def has_open_thread(self) -> bool:
        return self.open_thread_id != ""

    @rx.var
    def open_thread(self) -> ThreadRowVM:
        for row in self.rows:
            if row.thread_id == self.open_thread_id:
                return row
        return EMPTY_THREAD

    @rx.var
    def conv_ready(self) -> bool:
        return self.open_thread_id != "" and self.conv_loaded_for == self.open_thread_id

    @rx.var
    def can_compose(self) -> bool:
        return composer_enabled(self.open_thread.window_open, self.open_thread_id != "")

    @rx.var
    def compose_error(self) -> str:
        return validate_compose(
            self.compose_mode, self.draft_text, [self.button_1, self.button_2, self.button_3]
        )

    @rx.var
    def compose_hint(self) -> str:
        """The validation message, shown only once the person started filling the
        Botones form (an empty text box needs no scolding: «Enviar» is off)."""
        if self.compose_mode == COMPOSE_TEXT:
            return ""
        touched = any(v.strip() for v in (self.button_1, self.button_2, self.button_3))
        return self.compose_error if touched else ""

    @rx.var
    def button_counts(self) -> list[str]:
        return [
            f"{len(b.strip())}/{MAX_BUTTON_TITLE_CHARS}"
            for b in (self.button_1, self.button_2, self.button_3)
        ]

    @rx.var
    def window_closed_notice(self) -> str:
        if self.open_thread_id and not self.open_thread.window_open:
            return WINDOW_CLOSED_NOTICE
        return ""

    @rx.var
    def show_send_approved(self) -> bool:
        """The expired chat's way out: «Enviar un mensaje aprobado» (m-24848535)."""
        return self.open_thread_id != "" and not self.open_thread.window_open

    @rx.var
    def tpl_hint(self) -> str:
        if self.tpl_no_permission:
            return ""
        if not self.tpl_selected or not self.tpl_reviewing:
            return TEMPLATE_PICK_HINT if self.tpl_choices else ""
        return "" if template_fields_complete(self.tpl_fields) else TEMPLATE_FILL_HINT

    @rx.var
    def can_send_template(self) -> bool:
        return (
            self.tpl_selected != ""
            and self.tpl_reviewing
            and not self.tpl_sending
            and template_fields_complete(self.tpl_fields)
        )

    # ==================================================================================
    # Plumbing
    # ==================================================================================

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _reset_conversation(self) -> None:
        self.messages = []
        self.order = EMPTY_ORDER
        self.has_more = False
        self.conv_loaded_for = ""
        self.conv_loading_for = ""
        self.loading_older = False
        self.conv_error = ""
        self._records = []
        self._unsent = []
        self._order_raw = None
        self._media = {}
        self._media_loading = []
        self.lightbox_url = ""
        self._reset_composer()
        self._reset_templates()
        self._reset_picker()
        self.banner = ""

    def _reset_templates(self) -> None:
        self.tpl_open = False
        self.tpl_loading = False
        self.tpl_error = ""
        self.tpl_choices = []
        self.tpl_promotions_blocked = False
        self.tpl_consent_id = ""
        self.tpl_has_followups = True
        self.tpl_no_permission = False
        self.tpl_sending = False
        self._tpl_options = []
        self._clear_template_choice()

    def _clear_template_choice(self) -> None:
        self.tpl_selected = ""
        self.tpl_reviewing = False
        self.tpl_fields = []
        self.tpl_preview = ""
        self._tpl_values = {}
        self._tpl_request_key = ""

    def _tpl_option(self, template_id: str) -> TemplateOption | None:
        return next((o for o in self._tpl_options if str(o.template_id) == template_id), None)

    def _render_template_choice(self) -> None:
        option = self._tpl_option(self.tpl_selected)
        if option is None:
            self._clear_template_choice()
            return
        self.tpl_fields = build_template_fields(
            option.variables, self._tpl_values, variable_examples(option.components)
        )
        self.tpl_preview = render_preview(
            option.components, preview_values(option.variables, self._tpl_values)
        )

    def _apply_template_options(self, options: TemplateReplyOptions) -> None:
        self._tpl_options = list(options.options)
        self.tpl_choices = [
            build_template_choice(
                o, render_preview(o.components, preview_values(o.variables, o.prefill))
            )
            for o in options.options
        ]
        self.tpl_promotions_blocked = options.promotions_blocked
        consent = options.consent_request
        self.tpl_consent_id = str(consent.template_id) if consent is not None else ""
        self.tpl_has_followups = options.has_followups
        self.tpl_no_permission = options.permission.value == "none"
        if self._tpl_option(self.tpl_selected) is None:
            self._clear_template_choice()
        else:
            self._render_template_choice()

    def _reset_composer(self) -> None:
        self.draft_text = ""
        self.button_1 = self.button_2 = self.button_3 = ""

    def _render_conversation(self) -> None:
        zone = _zone(self._zone_name)
        now = self._now()
        self.messages = build_conversation(
            self._records,
            self._unsent,
            now=now,
            zone=zone,
            media=self._media,
            loading=self._media_loading,
        )
        self.order = build_order_card(self._order_raw, now=now, zone=zone)

    def _mark_paused(self, thread_id: str, paused: bool) -> None:
        label, tone = mode_pill(paused)
        self.rows = [
            dataclasses.replace(r, automation_paused=paused, mode_label=label, mode_tone=tone)
            if r.thread_id == thread_id
            else r
            for r in self.rows
        ]

    def _set_banner(self, message: str, tone: str) -> None:
        self.banner, self.banner_tone = message, tone

    # ==================================================================================
    # Entry, list, filters
    # ==================================================================================

    @rx.event
    async def enter(self) -> rx.event.EventSpec | None:
        """Tab root `on_mount`: entry or number switch."""
        # m-24842990: «Por responder» › «Ver» opens the chats on «Sin leer» (N11).
        if self.router.url.query_parameters.get("filtro") == "sin-leer":
            self.filter_key = FILTER_UNREAD
        if self.pick_open:
            self._reset_picker()  # back from Tus productos: the drawer does not reopen
        shell = await self.get_state(WhatsAppState)
        connection_id = shell.selected_connection_id
        if not connection_id:
            return None
        if connection_id != self._connection_id:
            self._connection_id = connection_id
            self.rows = []
            self.agents = []
            self.list_loaded_for = ""
            self.list_loading_for = ""
            self.list_error = ""
            self.open_thread_id = ""
            self._reset_conversation()
        elif self.list_loading_for == connection_id:
            return None  # a double mount while the first load is in flight
        return WhatsAppChatsState.load_list

    @rx.event
    def set_filter(self, key: str | list[str]) -> None:
        if isinstance(key, str) and key in FILTER_KEYS:
            self.filter_key = key

    @rx.event(background=True)
    async def load_list(self) -> None:
        await self._read_list(silent=False)

    async def _read_list(self, *, silent: bool) -> bool:
        """Re-read this number's threads. Returns False when it could not."""
        async with self:
            connection_id = self._connection_id
            if not connection_id:
                return False
            if not silent:
                self.list_loading_for = connection_id
                self.list_error = ""
            need_context = not self._zone_name or not self.agents
            tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.list_loading_for = ""
                self.list_error = _NO_SESSION
            return False
        connection = _uuid(connection_id)
        if connection is None:
            return False
        gw = gateway()
        try:
            if need_context:
                zone_name = await asyncio.to_thread(gw.timezone, tenant_id)
                agents = await asyncio.to_thread(gw.agents, tenant_id)
            threads = await asyncio.to_thread(gw.threads, tenant_id, connection)
        except _DB_ERRORS as exc:
            logger.error("whatsapp chats list failed: %s", type(exc).__name__)
            async with self:
                if self._connection_id == connection_id:
                    self.list_loading_for = ""
                    if not silent or not self.list_loaded_for:
                        self.list_error = _LIST_FAILED
            return False
        async with self:
            if self._connection_id != connection_id:
                return False  # the operator switched numbers meanwhile
            if need_context:
                self._zone_name = zone_name
                self.agents = agents
            by_id = {a.user_id: a for a in self.agents}
            zone = _zone(self._zone_name)
            now = self._now()
            self.rows = [build_thread_row(t, now=now, zone=zone, agents=by_id) for t in threads]
            self.list_loaded_for = connection_id
            self.list_loading_for = ""
            self.list_error = ""
        return True

    # ==================================================================================
    # Conversation
    # ==================================================================================

    @rx.event
    async def restore_address(self) -> rx.event.EventSpec | None:
        """Read only internal IDs; the provider enforces tenant + connection ownership."""
        shell = await self.get_state(WhatsAppState)
        connection = shell.selected_connection_id
        if not connection:
            return None
        if connection != self._connection_id:
            self._connection_id = connection
            self.rows = []
            self.list_loaded_for = ""
            self._reset_conversation()
        params = self.router.url.query_parameters
        thread = thread_param(params, connection)
        if thread == self.open_thread_id:
            return None
        self.open_thread_id = thread
        self._reset_conversation()
        return WhatsAppChatsState.load_conversation if thread else None

    @rx.event
    def open_conversation(
        self, thread_id: str
    ) -> list[rx.event.EventSpec | rx.event.EventHandler] | None:
        if not isinstance(thread_id, str) or thread_id == self.open_thread_id:
            return None
        if thread_id not in {r.thread_id for r in self.rows}:
            return None  # arrived over the wire; refuse an id the list does not hold
        writer = replace_url_script if self.open_thread_id else push_url_script
        self.open_thread_id = thread_id
        self._reset_conversation()
        self.compose_mode = COMPOSE_TEXT
        return [
            rx.call_script(writer(conversation_href("whatsapp", self._connection_id, thread_id))),
            WhatsAppChatsState.load_conversation,
        ]

    @rx.event
    def back_to_list(self) -> rx.event.EventSpec:
        """Mobile: leave the conversation pane."""
        self.open_thread_id = ""
        self._reset_conversation()
        return rx.call_script(back_url_script(conversation_href("whatsapp", self._connection_id)))

    @rx.event(background=True)
    async def load_conversation(self) -> AsyncIterator[rx.event.EventSpec]:
        await self._read_conversation(silent=False)
        yield WhatsAppChatsState.restore_flow

    async def _read_conversation(self, *, silent: bool) -> None:
        async with self:
            thread_id = self.open_thread_id
            connection_id = self._connection_id
            if not thread_id or (not silent and self.conv_loading_for == thread_id):
                return
            if not silent:
                self.conv_loading_for = thread_id
                self.conv_error = ""
            tenant_id = await self._tenant()
            older = list(self._records)
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        if tenant_id is None or thread is None or connection is None:
            async with self:
                self.conv_loading_for = ""
                self.conv_error = _NO_SESSION if tenant_id is None else _CONV_FAILED
            return
        try:
            conv = await asyncio.to_thread(gateway().conversation, tenant_id, connection, thread)
        except ThreadNotFound:
            async with self:
                if self.open_thread_id == thread_id:
                    self.open_thread_id = ""
                    self._reset_conversation()
                    self._set_banner(_THREAD_GONE, "warn")
            return
        except _DB_ERRORS as exc:
            logger.error("whatsapp chats conversation failed: %s", type(exc).__name__)
            async with self:
                if self.open_thread_id == thread_id:
                    self.conv_loading_for = ""
                    if not silent or not self.conv_loaded_for:
                        self.conv_error = _CONV_FAILED
            return
        async with self:
            if self.open_thread_id != thread_id:
                return  # another conversation was opened meanwhile
            self._records = merge_pages(older, conv.messages) if silent else conv.messages
            if not silent:
                self.has_more = conv.has_more
            self._unsent = conv.unsent
            self._order_raw = conv.order
            self._render_conversation()
            self.conv_loaded_for = thread_id
            self.conv_loading_for = ""
            self.conv_error = ""

    @rx.event(background=True)
    async def load_older(self) -> None:
        async with self:
            thread_id = self.open_thread_id
            connection_id = self._connection_id
            if not thread_id or self.loading_older or not self._records:
                return
            before = self._records[0].posted_at
            self.loading_older = True
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        if tenant_id is None or thread is None or connection is None or before is None:
            async with self:
                self.loading_older = False
            return
        try:
            page = await asyncio.to_thread(gateway().older, tenant_id, connection, thread, before)
        except (ThreadNotFound, *_DB_ERRORS) as exc:
            logger.error("whatsapp chats older page failed: %s", type(exc).__name__)
            async with self:
                self.loading_older = False
                self._set_banner(_CONV_FAILED, "error")
            return
        async with self:
            self.loading_older = False
            if self.open_thread_id != thread_id:
                return
            seen = {m.id for m in self._records}
            self._records = [m for m in page.messages if m.id not in seen] + self._records
            self.has_more = page.has_more
            self._render_conversation()

    # ==================================================================================
    # Inbound media (0061)
    # ==================================================================================

    def _media_record(self, message_id: str) -> MessageRecord | None:
        """The loaded inbound `has_media` record with this id, else None."""
        for record in self._records:
            if str(record.id) == message_id:
                if record.direction == "inbound" and record.has_media:
                    return record
                return None
        return None

    def _open_media(self, control: str, url: str) -> rx.event.EventSpec | None:
        """Show a resolved URL: the lightbox for an image, a new tab for a video or a
        document; an audio needs nothing (its player renders in the bubble)."""
        if control == MEDIA_IMAGE:
            self.lightbox_url = url
        elif control in (MEDIA_VIDEO, MEDIA_DOCUMENT):
            return rx.redirect(url, is_external=True)
        return None

    @rx.event(background=True)
    async def request_media(self, message_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """«Ver imagen» / «Escuchar audio» / «Ver video» / «Descargar» / «Reintentar»."""
        if not isinstance(message_id, str):
            return
        async with self:
            record = self._media_record(message_id)
            if record is None or message_id in self._media_loading:
                return
            control = media_control_for(record.media_kind)
            cached = self._media.get(message_id, MediaResolution()).fresh_url(self._now())
            cached_event = self._open_media(control, cached) if cached else None
        if cached:
            if cached_event is not None:
                yield cached_event
            return
        async with self:
            if message_id in self._media_loading:
                return
            self._media_loading = [*self._media_loading, message_id]
            self._render_conversation()
            thread_id = self.open_thread_id
            tenant_id = await self._tenant()
        message = _uuid(message_id)
        outcome = MediaResolution(error=MEDIA_UNAVAILABLE)
        if tenant_id is not None and message is not None:
            try:
                url = await gateway().media_url(tenant_id, message)
                outcome = resolution_after(url, self._now())
            except MediaExpired:
                outcome = MediaResolution(error=MEDIA_EXPIRED)
            except MediaNotCaptured:
                outcome = MediaResolution(error=MEDIA_NOT_CAPTURED_CODE)
            except MediaMessageNotFound:
                outcome = MediaResolution(error=MEDIA_NOT_FOUND)
            except MediaUnavailable:
                pass
            except Exception as exc:  # the locator maps its own; anything else is transient
                logger.error("whatsapp chats media failed: %s", type(exc).__name__)
        event = None
        async with self:
            self._media_loading = [m for m in self._media_loading if m != message_id]
            if self.open_thread_id != thread_id:
                return  # another conversation was opened meanwhile
            self._media = {**self._media, message_id: outcome}
            self._render_conversation()
            if outcome.url:
                event = self._open_media(control, outcome.url)
        if event is not None:
            yield event

    @rx.event
    def open_lightbox(self, message_id: str) -> None:
        """Click on a thumbnail: the URL comes from the server-side cache, never from
        the browser."""
        if not isinstance(message_id, str):
            return
        self.lightbox_url = self._media.get(message_id, MediaResolution()).fresh_url(self._now())

    @rx.event
    def set_lightbox_open(self, is_open: bool) -> None:
        if not is_open:
            self.lightbox_url = ""

    # ==================================================================================
    # Refresh (15 s heartbeat + after every action)
    # ==================================================================================

    @rx.event(background=True)
    async def refresh(self) -> None:
        async with self:
            if self._refreshing or not self.list_loaded_for or self.list_loading_for:
                return
            self._refreshing = True
        try:
            await self._read_list(silent=True)
            await self._read_conversation(silent=True)
        finally:
            async with self:
                self._refreshing = False

    # ==================================================================================
    # Composer
    # ==================================================================================

    @rx.event
    def set_compose_mode(self, mode: str | list[str]) -> None:
        if isinstance(mode, str) and mode in COMPOSE_KEYS:
            self.compose_mode = mode

    @rx.event
    def set_draft_text(self, value: str) -> None:
        self.draft_text = value if isinstance(value, str) else ""

    @rx.event
    def set_button(self, index: int, value: str) -> None:
        if index in (1, 2, 3) and isinstance(value, str):
            setattr(self, f"button_{index}", value[: MAX_BUTTON_TITLE_CHARS + 10])

    @rx.event
    def dismiss_banner(self) -> None:
        self.banner = ""

    async def _acting_user(self, tenant_id: UUID) -> UUID | None:
        """The logged-in person's `users.id`, resolved once per session."""
        async with self:
            cached = self._user_id
            auth = await self.get_state(AuthState)
            email = auth.user_email
        if cached:
            return _uuid(cached)
        user_id = await asyncio.to_thread(gateway().acting_user, tenant_id, email)
        if user_id is not None:
            async with self:
                self._user_id = str(user_id)
        return user_id

    @rx.event(background=True)
    async def send_message(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.sending or not self.open_thread_id or not self.can_compose:
                return
            if self.compose_error:
                self._set_banner(self.compose_error, "warn")
                return
            mode = self.compose_mode
            text = self.draft_text
            titles = [self.button_1, self.button_2, self.button_3]
        gw = gateway()

        def call(tenant: UUID, connection: UUID, thread: UUID, user: UUID) -> object:
            if mode == COMPOSE_BUTTONS:
                return gw.send_buttons(tenant, connection, thread, user, text, titles)
            return gw.send_text(tenant, connection, thread, user, text)

        async for event in self._send(call, clear_composer=True):
            yield event

    @rx.event(background=True)
    async def send_order_ready(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.sending or not self.order.present or not self.can_compose:
                return
        gw = gateway()

        def call(tenant: UUID, connection: UUID, thread: UUID, user: UUID) -> object:
            return gw.send_order_ready(tenant, connection, thread, user)

        async for event in self._send(call, clear_composer=False):
            yield event

    async def _send(
        self,
        call: Callable[[UUID, UUID, UUID, UUID], object],
        *,
        clear_composer: bool,
    ) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            self.sending = True
            self.banner = ""
            thread_id, connection_id = self.open_thread_id, self._connection_id
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        try:
            if tenant_id is None or thread is None or connection is None:
                raise PermissionError
            user = await self._acting_user(tenant_id)
            if user is None:
                async with self:
                    self.sending = False
                    self._set_banner(_NO_USER, "error")
                return
            await asyncio.to_thread(call, tenant_id, connection, thread, user)
        except PermissionError:
            async with self:
                self.sending = False
                self._set_banner(_NO_SESSION, "error")
            return
        except WindowClosed:
            async with self:
                self.sending = False
                self._set_banner(WINDOW_CLOSED_NOTICE, "warn")
            yield WhatsAppChatsState.refresh
            return
        except (ThreadNotFound, NoOrder) as exc:
            async with self:
                self.sending = False
                self._set_banner(
                    _THREAD_GONE if isinstance(exc, ThreadNotFound) else _NO_ORDER, "warn"
                )
            yield WhatsAppChatsState.refresh
            return
        except ValueError:
            # Meta's limits (client builders) or Pydantic's shape — never echo their text.
            async with self:
                self.sending = False
                self._set_banner(_REJECTED, "error")
            return
        except _DB_ERRORS as exc:
            logger.error("whatsapp chats send failed: %s", type(exc).__name__)
            async with self:
                self.sending = False
                self._set_banner(_ACTION_FAILED, "error")
            return
        async with self:
            self.sending = False
            if clear_composer and self.open_thread_id == thread_id:
                self._reset_composer()
            self._mark_paused(thread_id, True)
        if flow_param(self.router.url.query_parameters, "mensaje-chat", 2):
            yield rx.call_script(close_flow_script("mensaje-chat"))
        yield rx.toast.success(_QUEUED, duration=_TOAST_MS)
        yield WhatsAppChatsState.refresh
        yield PendingState.refresh_now  # m-24842963: the menu's count drops now

    # ==================================================================================
    # Approved message from an expired chat (m-24848535)
    # ==================================================================================

    def _apply_flow_step(self) -> None:
        params = self.router.url.query_parameters
        requested = flow_param(params, "mensaje-chat", 2)
        if not requested:
            return
        chosen = uuid_param(params, "objeto")
        if chosen and self._tpl_option(chosen) is not None:
            self._choose(chosen)
        self.tpl_reviewing = requested == 2 and bool(self.tpl_selected)
        self.tpl_open = True
        self.flow_ready = True

    @rx.event
    def restore_flow(self) -> rx.event.EventSpec | None:
        requested = flow_param(self.router.url.query_parameters, "mensaje-chat", 2)
        if not requested:
            self.tpl_open = False
            self.flow_ready = False
            return None
        if not self.open_thread_id:
            return None
        if not self._tpl_options:
            self.tpl_open = True
            return WhatsAppChatsState.load_templates
        self._apply_flow_step()
        return None

    @rx.event
    def open_templates(self) -> rx.event.EventSpec | None:
        """«Enviar un mensaje aprobado»: open the picker and (re)load what this person
        may receive. Nothing is sent here."""
        if not self.show_send_approved:
            return None
        self.tpl_open = True
        self.flow_ready = True
        return WhatsAppChatsState.load_templates

    @rx.event
    def set_templates_open(self, is_open: bool) -> rx.event.EventSpec | None:
        if not is_open:
            self.tpl_open = False
            self.flow_ready = False
            return rx.call_script(close_flow_script("mensaje-chat"))
        return None

    @rx.event(background=True)
    async def load_templates(self) -> None:
        await self._read_templates(keep_error=False)

    async def _read_templates(self, *, keep_error: bool) -> None:
        async with self:
            thread_id, connection_id = self.open_thread_id, self._connection_id
            if not thread_id or self.tpl_loading:
                return
            self.tpl_loading = True
            if not keep_error:
                self.tpl_error = ""
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        if tenant_id is None or thread is None or connection is None:
            async with self:
                self.tpl_loading = False
                self.tpl_error = _NO_SESSION
            return
        try:
            options = await asyncio.to_thread(
                gateway().template_options, tenant_id, connection, thread
            )
        except ThreadNotFound:
            async with self:
                self.tpl_loading = False
                self.tpl_open = False
                self._set_banner(_THREAD_GONE, "warn")
            return
        except _DB_ERRORS as exc:
            logger.error("whatsapp chats templates failed: %s", type(exc).__name__)
            async with self:
                self.tpl_loading = False
                self.tpl_error = _TEMPLATES_FAILED
            return
        async with self:
            self.tpl_loading = False
            if self.open_thread_id != thread_id:
                return
            self._apply_template_options(options)
            self._apply_flow_step()

    def _choose(self, template_id: str) -> None:
        """Pick one listed message (an id the list does not hold is ignored). A new pick
        starts a new «Enviar» intent, so it gets a new request key."""
        if not isinstance(template_id, str):
            return
        if template_id and template_id == self.tpl_selected:
            # The same message again (after «Atrás»): back to step 2, values intact.
            self.tpl_reviewing = True
            return
        option = self._tpl_option(template_id)
        if option is None:
            return
        self.tpl_selected = template_id
        self.tpl_reviewing = True
        self.tpl_error = ""
        self._tpl_values = dict(option.prefill)
        self._tpl_request_key = str(uuid4())
        self._render_template_choice()

    @rx.event
    def choose_template(self, template_id: str) -> None:
        self._choose(template_id)

    @rx.event
    def back_to_templates(self) -> None:
        """«Atrás»: step 1 again; the choice and what was typed are kept."""
        self.tpl_reviewing = False
        self.tpl_error = ""

    @rx.event
    def ask_consent(self) -> None:
        """«Pedirle que acepte»: picks the approved message that asks; the owner still
        reads it and presses «Enviar» (N13)."""
        if self.tpl_consent_id:
            self._choose(self.tpl_consent_id)

    @rx.event
    def set_template_value(self, field_id: str, value: str) -> None:
        if not isinstance(field_id, str) or not isinstance(value, str):
            return
        if field_id not in {f.id for f in self.tpl_fields}:
            return
        self._tpl_values = {**self._tpl_values, field_id: value[:1024]}
        self._render_template_choice()

    @rx.event(background=True)
    async def send_template(self) -> AsyncIterator[rx.event.EventSpec]:
        """The owner's «Enviar» — the only path that queues an approved message."""
        async with self:
            if not self.can_send_template or not self.open_thread_id:
                return
            option = self._tpl_option(self.tpl_selected)
            if option is None:
                return
            if not self._tpl_request_key:
                self._tpl_request_key = str(uuid4())
            request_key = self._tpl_request_key
            values = dict(self._tpl_values)
            template_id = option.template_id
            self.tpl_sending = True
            self.tpl_error = ""
            thread_id, connection_id = self.open_thread_id, self._connection_id
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        error = ""
        try:
            if tenant_id is None or thread is None or connection is None:
                raise PermissionError
            user = await self._acting_user(tenant_id)
            if user is None:
                error = _NO_USER
            else:
                await asyncio.to_thread(
                    gateway().send_template,
                    tenant_id,
                    connection,
                    thread,
                    user,
                    template_id,
                    values,
                    request_key,
                )
        except PermissionError:
            error = _NO_SESSION
        except ThreadNotFound:
            error = _THREAD_GONE
        except PromotionNeedsConsent:
            error = PROMOTIONS_NEED_CONSENT
        except NoPermission:
            error = NO_PERMISSION_NOTICE
        except TemplateNotAvailable:
            error = _TEMPLATE_GONE
        except MissingValues:
            error = TEMPLATE_FILL_HINT
        except ValueError:
            error = _REJECTED
        except _DB_ERRORS as exc:
            # The key is kept: «Enviar» again retries the SAME intent and queues once.
            logger.error("whatsapp chats template send failed: %s", type(exc).__name__)
            error = _ACTION_FAILED
        if error:
            async with self:
                self.tpl_sending = False
                self.tpl_error = error
            if error in (PROMOTIONS_NEED_CONSENT, _TEMPLATE_GONE, NO_PERMISSION_NOTICE):
                # The list on screen was stale: re-read it, keeping the reason visible.
                await self._read_templates(keep_error=True)
            return
        async with self:
            self.tpl_sending = False
            self.tpl_open = False
            self.flow_ready = False
            self._clear_template_choice()
            self._mark_paused(thread_id, True)
        yield rx.toast.success(_QUEUED, duration=_TOAST_MS)
        yield WhatsAppChatsState.refresh

    # ==================================================================================
    # «Foto o menú» (m-24945888, docs/ux-whatsapp-enviar-imagen.md)
    # ==================================================================================
    #
    # ① what to send → ② which one → ③ «Revisa y envía» (Tu menú: ① → ②). Nothing is
    # queued until `send_pick`; the lists are read in background events, scoped to the
    # number's business; a result that lands after the drawer closed or the chat changed
    # (`_pick_session`) is dropped.

    @rx.var
    def pick_total(self) -> int:
        return pick_total_steps(self.pick_source)

    @rx.var
    def pick_title(self) -> str:
        return pick_step_title(
            self.pick_step, self.pick_source, pick_heading(self.open_thread.title)
        )

    @rx.var
    def pick_help(self) -> str:
        return pick_step_help(self.pick_step, self.pick_source)

    @rx.var
    def pick_reviewing(self) -> bool:
        """The step with «Enviar»: the third, or the menu's second."""
        return self.pick_step >= self.pick_total and self.pick_source != ""

    @rx.var
    def pick_closing_soon(self) -> bool:
        """Less than an hour left: the chat's own pill goes under the title (spec §2)."""
        return self.open_thread.window_tone == "warn"

    @rx.var
    def pick_selected_product(self) -> ProductCardVM:
        if self.pick_source == PICK_PRODUCTS:
            for card in self.pick_products:
                if card.id == self.pick_selected:
                    return card
        return EMPTY_PRODUCT

    @rx.var
    def pick_selected_piece(self) -> PieceCardVM:
        if self.pick_source == PICK_PIECES:
            for card in self.pick_pieces:
                if card.id == self.pick_selected:
                    return card
        return EMPTY_PIECE

    @rx.var
    def pick_visible_products(self) -> list[ProductCardVM]:
        return filter_products(self.pick_products, self.pick_query)

    @rx.var
    def pick_show_search(self) -> bool:
        return len(self.pick_products) > PRODUCT_SEARCH_FROM

    @rx.var
    def pick_all_without_photo(self) -> bool:
        return bool(self.pick_products) and not any(c.has_photo for c in self.pick_products)

    @rx.var
    def pick_visible_pieces(self) -> list[PieceCardVM]:
        return pieces_in(self.pick_pieces, self.pick_piece_tab)

    @rx.var
    def pick_has_approved(self) -> bool:
        return bool(pieces_in(self.pick_pieces, PIECES_APPROVED))

    @rx.var
    def pick_has_unapproved(self) -> bool:
        return bool(pieces_in(self.pick_pieces, PIECES_UNAPPROVED))

    @rx.var
    def pick_as_text(self) -> bool:
        """A product without a photo goes as a text (name, price, the caption)."""
        card = self.pick_selected_product
        return self.pick_source == PICK_PRODUCTS and card.id != "" and not card.has_photo

    @rx.var
    def pick_preview_text(self) -> str:
        """The bubble's text exactly as it arrives (the backend's own text builder for a
        product without a photo)."""
        if self.pick_as_text:
            card = self.pick_selected_product
            return product_text(card.name, card.price_label, card.description, self.pick_caption)
        return self.pick_caption.strip()

    @rx.var
    def pick_caption_count(self) -> str:
        return caption_count(self.pick_caption)

    @rx.var
    def pick_caption_error(self) -> str:
        return caption_error(self.pick_caption)

    @rx.var
    def pick_can_send(self) -> bool:
        if not self.pick_reviewing or self.pick_sending or self.pick_window_closed:
            return False
        if self.pick_source == PICK_MENU:
            return self.pick_menu.present and not self.pick_menu.empty
        if self.pick_caption_error:
            return False
        if self.pick_source == PICK_PHOTO:
            return self.pick_photo_preview != ""
        if self.pick_source == PICK_PRODUCTS:
            return self.pick_selected_product.id != ""
        return self.pick_selected_piece.id != ""

    @rx.var
    def pick_send_label(self) -> str:
        if self.pick_sending:
            return SENDING_LABEL
        return SEND_MENU_LABEL if self.pick_source == PICK_MENU else SEND_LABEL

    @rx.var
    def pick_flow_object(self) -> str:
        """The address's `objeto`: the chosen product or piece (a UUID, else nothing)."""
        return self.pick_selected if _uuid(self.pick_selected) is not None else ""

    # --- plumbing ----------------------------------------------------------------------

    def _reset_picker(self) -> None:
        self._pick_session += 1
        self.pick_open = False
        self.pick_step = 1
        self.pick_source = ""
        self.pick_loading = False
        self.pick_error = ""
        self.pick_products = []
        self.pick_products_loaded = False
        self.pick_query = ""
        self.pick_pieces = []
        self.pick_pieces_loaded = False
        self.pick_piece_tab = PIECES_APPROVED
        self.pick_menu = EMPTY_MENU
        self.pick_sending = False
        self.pick_send_error = ""
        self.pick_window_closed = False
        self._pick_thread = ""
        self._clear_pick_choice()
        self._clear_pick_photo()

    def _clear_pick_choice(self) -> None:
        self.pick_selected = ""
        self.pick_caption = ""
        self._pick_request_key = ""

    def _clear_pick_photo(self) -> None:
        self.pick_photo_preview = ""
        self.pick_photo_name = ""
        self.pick_photo_error = ""
        self._pick_photo = b""
        self._pick_photo_type = ""

    def _new_pick_intent(self) -> None:
        """A new thing to send is a new «Enviar» intent: a new request key."""
        self._pick_request_key = str(uuid4())
        self.pick_send_error = ""

    def _close_picker(self) -> rx.event.EventSpec:
        self._reset_picker()
        return rx.call_script(close_flow_script(PICK_FLOW))

    # --- open, steps, close ------------------------------------------------------------

    @rx.event
    def open_picker(self) -> None:
        """«Foto o menú»: only while this chat may get a free-form message."""
        if not self.can_compose or self.sending:
            return
        self._reset_picker()
        self.pick_open = True
        self._pick_thread = self.open_thread_id

    @rx.event
    def set_picker_open(self, is_open: bool) -> rx.event.EventSpec | None:
        """The drawer's ✕, Esc or the backdrop."""
        if not is_open and self.pick_open:
            return self._close_picker()
        return None

    @rx.event
    def close_picker(self) -> rx.event.EventSpec:
        """«Volver al chat»."""
        return self._close_picker()

    @rx.event
    def choose_pick_source(
        self, source: str
    ) -> list[rx.event.EventSpec | rx.event.EventHandler] | None:
        if not self.pick_open or not isinstance(source, str) or source not in PICK_SOURCES:
            return None
        if source != self.pick_source:
            self._clear_pick_choice()
            self.pick_send_error = ""
            self.pick_window_closed = False
            self.pick_error = ""
        self.pick_source = source
        self.pick_step = 2
        events: list[rx.event.EventSpec | rx.event.EventHandler] = [settle_step("drawer")]
        if source == PICK_PRODUCTS and not self.pick_products_loaded:
            events.append(WhatsAppChatsState.load_pick_products)
        elif source == PICK_PIECES and not self.pick_pieces_loaded:
            events.append(WhatsAppChatsState.load_pick_pieces)
        elif source == PICK_MENU:
            self._new_pick_intent()
            events.append(WhatsAppChatsState.load_pick_menu)
        return events

    def _step_back_to(self, step: int) -> None:
        """Back keeps what was chosen and written (a step forward again finds it)."""
        self.pick_step = max(1, step)
        self.pick_error = "" if self.pick_step == 1 else self.pick_error
        self.pick_send_error = ""

    @rx.event
    def pick_back(self) -> rx.event.EventSpec:
        """«Atrás»; on step 1 it is «Volver al chat»."""
        if self.pick_step <= 1:
            return self._close_picker()
        self._step_back_to(self.pick_step - 1)
        return settle_step("drawer")

    @rx.event
    def restore_picker(self) -> rx.event.EventSpec | None:
        """The phone's «atrás» (the address moved under the drawer): one step back, or
        closed on step 1. An address that names the drawer while it is closed (a reload)
        is cleaned — nothing reopens by itself."""
        requested = flow_param(self.router.url.query_parameters, PICK_FLOW, 3)
        if not self.pick_open:
            return rx.call_script(close_flow_script(PICK_FLOW)) if requested else None
        if not requested:
            self._reset_picker()
            return None
        if requested < self.pick_step:
            self._step_back_to(requested)
            return settle_step("drawer")
        return None

    @rx.event
    def set_pick_query(self, value: str) -> None:
        self.pick_query = value[:80] if isinstance(value, str) else ""

    @rx.event
    def set_piece_tab(self, key: str | list[str]) -> None:
        if isinstance(key, str) and key in PIECE_TAB_KEYS:
            self.pick_piece_tab = key

    @rx.event
    def show_unapproved(self) -> None:
        self.pick_piece_tab = PIECES_UNAPPROVED

    @rx.event
    def choose_product(self, product_id: str) -> rx.event.EventSpec | None:
        if not isinstance(product_id, str) or self.pick_source != PICK_PRODUCTS:
            return None
        card = next((c for c in self.pick_products if c.id == product_id), None)
        if card is None:
            return None  # arrived over the wire; refuse an id the grid does not hold
        if product_id != self.pick_selected:
            self.pick_selected = product_id
            self.pick_caption = product_caption(
                card.name, card.price_label, food=self._pick_food, description=card.description
            )
            self._new_pick_intent()
        self.pick_step = 3
        return settle_step("drawer")

    @rx.event
    def choose_piece(self, piece_id: str) -> rx.event.EventSpec | None:
        if not isinstance(piece_id, str) or self.pick_source != PICK_PIECES:
            return None
        card = next((c for c in self.pick_pieces if c.id == piece_id), None)
        if card is None:
            return None
        if piece_id != self.pick_selected:
            self.pick_selected = piece_id
            self.pick_caption = card.caption
            self._new_pick_intent()
        self.pick_step = 3
        return settle_step("drawer")

    @rx.event
    def set_pick_caption(self, value: str) -> None:
        # A little over the limit, so the count and «El texto admite…» can show it.
        self.pick_caption = value[: MAX_CAPTION_CHARS + 200] if isinstance(value, str) else ""

    @rx.event
    async def handle_pick_photo(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """A photo from the phone: checked here (type, 5 MB) and again by the backend;
        the bytes stay backend-only, the browser gets a small preview."""
        if not self.pick_open or self.pick_source != PICK_PHOTO or self.pick_sending:
            return None
        if not files:
            return None
        upload = files[0]
        try:
            data = await upload.read()
        except Exception:  # noqa: BLE001 — the browser's stream, not ours
            self.pick_photo_error = PHOTO_UNREADABLE
            return None
        content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
        refusal = photo_refusal(content_type, len(data))
        if refusal:
            self.pick_photo_error = refusal
            return None
        try:
            preview = await asyncio.to_thread(photo_preview, data)
        except Exception as exc:  # noqa: BLE001 — a corrupt file is the owner's to replace
            logger.warning("whatsapp chats photo preview failed: %s", type(exc).__name__)
            self.pick_photo_error = PHOTO_UNREADABLE
            return None
        name = (getattr(upload, "name", "") or "foto").split("/")[-1].split("\\")[-1]
        self._pick_photo = data
        self._pick_photo_type = content_type
        self.pick_photo_preview = preview
        self.pick_photo_name = name[:120]
        self.pick_photo_error = ""
        self._new_pick_intent()
        self.pick_step = 3
        return settle_step("drawer")

    @rx.event
    def pick_photo_rejected(self, _files: Any = None) -> None:
        self.pick_photo_error = PHOTO_REJECTED

    @rx.event
    def pick_to_templates(self) -> list[rx.event.EventSpec | rx.event.EventHandler] | None:
        """The window closed while choosing: «Enviar un mensaje aprobado» closes the
        drawer and opens that list (one drawer at a time)."""
        if not self.pick_window_closed:
            return None
        thread_id = self._pick_thread
        self._reset_picker()
        self._mark_window_closed(thread_id)
        return [rx.call_script(close_flow_script(PICK_FLOW)), WhatsAppChatsState.open_templates]

    def _mark_window_closed(self, thread_id: str) -> None:
        self.rows = [
            dataclasses.replace(
                r, window_open=False, window_label=WINDOW_CLOSED_PILL, window_tone="neutral"
            )
            if r.thread_id == thread_id
            else r
            for r in self.rows
        ]

    @rx.event
    def retry_pick_list(self) -> rx.event.EventHandler | None:
        loaders = {
            PICK_PRODUCTS: WhatsAppChatsState.load_pick_products,
            PICK_PIECES: WhatsAppChatsState.load_pick_pieces,
            PICK_MENU: WhatsAppChatsState.load_pick_menu,
        }
        return loaders.get(self.pick_source)

    # --- lists -------------------------------------------------------------------------

    @rx.event(background=True)
    async def load_pick_products(self) -> None:
        await self._load_pick(PICK_PRODUCTS)

    @rx.event(background=True)
    async def load_pick_pieces(self) -> None:
        await self._load_pick(PICK_PIECES)

    @rx.event(background=True)
    async def load_pick_menu(self) -> None:
        await self._load_pick(PICK_MENU)

    async def _load_pick(self, source: str) -> None:
        async with self:
            if not self.pick_open or self.pick_source != source or self.pick_loading:
                return
            session, connection_id = self._pick_session, self._connection_id
            need_scope = source != PICK_MENU and self._pick_scope_for != connection_id
            brand = self._pick_brand
            food = self._pick_food
            self.pick_loading = True
            self.pick_error = ""
            tenant_id = await self._tenant()
        failed = {PICK_PRODUCTS: PRODUCTS_FAILED, PICK_PIECES: PIECES_FAILED}.get(
            source, MENU_FAILED
        )
        connection = _uuid(connection_id)
        gw = gateway()
        products: list[ProductCardVM] = []
        pieces: list[PieceCardVM] = []
        menu = EMPTY_MENU
        try:
            if tenant_id is None or connection is None:
                raise PermissionError
            if need_scope:
                scope = await asyncio.to_thread(gw.picker_scope, tenant_id, connection)
                brand = str(scope.brand_id) if scope.brand_id else ""
                food = is_food_business(scope.sector, scope.rubro)
            brand_id = _uuid(brand)
            if source == PICK_PRODUCTS and brand_id is not None:
                picks = await asyncio.to_thread(gw.list_products_for_chat, tenant_id, brand_id)
                products = build_product_cards(picks)
            elif source == PICK_PIECES and brand_id is not None:
                found = await asyncio.to_thread(gw.list_pieces_for_chat, tenant_id, brand_id)
                pieces = build_piece_cards(found)
            elif source == PICK_MENU:
                preview = await asyncio.to_thread(gw.menu_preview, tenant_id, connection)
                menu = build_menu_preview(preview)
        except PermissionError:
            failed = _NO_SESSION
            ok = False
        except Exception as exc:  # noqa: BLE001 — Postgres or R2 links: worded, never shown
            logger.error("whatsapp chats picker %s failed: %s", source, type(exc).__name__)
            ok = False
        else:
            ok = True
        async with self:
            if self._pick_session != session or self._connection_id != connection_id:
                return  # the drawer closed or the chat changed meanwhile
            self.pick_loading = False
            if not ok:
                self.pick_error = failed
                return
            if need_scope:
                self._pick_scope_for, self._pick_brand, self._pick_food = (
                    connection_id,
                    brand,
                    food,
                )
            if source == PICK_PRODUCTS:
                self.pick_products, self.pick_products_loaded = products, True
            elif source == PICK_PIECES:
                self.pick_pieces, self.pick_pieces_loaded = pieces, True
            else:
                self.pick_menu = menu

    # --- «Enviar» ------------------------------------------------------------------------

    def _begin_pick_send(self) -> PickSend | None:
        """Freeze one «Enviar» (None while another is in flight, or when nothing valid is
        on screen). Its request key is the intent's: a retry after a failure reuses it."""
        if not self.pick_can_send or not self.pick_open:
            return None
        if self.open_thread_id == "" or self.open_thread_id != self._pick_thread:
            return None
        if not self._pick_request_key:
            self._pick_request_key = str(uuid4())
        self.pick_sending = True
        self.pick_send_error = ""
        return PickSend(
            session=self._pick_session,
            source=self.pick_source,
            thread_id=self._pick_thread,
            connection_id=self._connection_id,
            request_key=self._pick_request_key,
            item_id=self.pick_selected,
            caption=self.pick_caption,
            photo=self._pick_photo,
            photo_type=self._pick_photo_type,
            photo_name=self.pick_photo_name,
            as_text=self.pick_as_text,
        )

    def _finish_pick_send(self, plan: PickSend, error: str) -> bool:
        """Apply the outcome. False when it is stale (the drawer closed or the chat
        changed): nothing on screen moves, the refresh shows what really went."""
        if self._pick_session != plan.session or self.open_thread_id != plan.thread_id:
            return False
        self.pick_sending = False
        if error:
            self.pick_send_error = error
            self.pick_window_closed = error == PICK_WINDOW_CLOSED
            if self.pick_window_closed:
                self._mark_window_closed(plan.thread_id)
            return True
        self._reset_picker()
        self._mark_paused(plan.thread_id, True)
        return True

    @rx.event(background=True)
    async def send_pick(self) -> AsyncIterator[rx.event.EventSpec | rx.event.EventHandler]:
        """The owner's «Enviar» / «Enviar el menú» — the only path the picker queues by."""
        async for event in self._send_pick():
            yield event

    async def _send_pick(self) -> AsyncIterator[rx.event.EventSpec | rx.event.EventHandler]:
        async with self:
            plan = self._begin_pick_send()
            if plan is None:
                return
            tenant_id = await self._tenant()
        thread, connection = _uuid(plan.thread_id), _uuid(plan.connection_id)
        error = ""
        try:
            if tenant_id is None or thread is None or connection is None:
                raise PermissionError
            user = await self._acting_user(tenant_id)
            if user is None:
                error = _NO_USER
            else:
                await asyncio.to_thread(
                    call_pick, gateway(), plan, tenant_id, connection, thread, user
                )
        except PermissionError:
            error = _NO_SESSION
        except Exception as exc:  # noqa: BLE001 — every refusal is worded by `pick_send_error`
            if not isinstance(exc, (WindowClosed, AttachmentRefused, LookupError)):
                logger.error("whatsapp chats picker send failed: %s", type(exc).__name__)
            error = pick_send_error(exc, plan)
        async with self:
            current = self._finish_pick_send(plan, error)
        if error:
            if error == PICK_WINDOW_CLOSED:
                yield WhatsAppChatsState.refresh
            return
        if current:
            yield rx.call_script(close_flow_script(PICK_FLOW))
            yield rx.toast.success(_QUEUED, duration=_TOAST_MS)
        yield WhatsAppChatsState.refresh
        yield PendingState.refresh_now

    # ==================================================================================
    # Header actions
    # ==================================================================================

    @rx.event(background=True)
    async def take_over(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._act("takeover"):
            yield event

    @rx.event(background=True)
    async def resume_menu(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._act("resume"):
            yield event

    @rx.event(background=True)
    async def close_conversation(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._act("close"):
            yield event

    @rx.event(background=True)
    async def reopen_conversation(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._act("reopen"):
            yield event

    @rx.event(background=True)
    async def assign_to(self, agent_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """The «Asignar» select; `UNASSIGNED` (a Radix item cannot carry "") unassigns."""
        value = "" if agent_id == UNASSIGNED or not isinstance(agent_id, str) else agent_id
        async for event in self._act("assign", agent_id=value):
            yield event

    async def _act(self, action: str, agent_id: str = "") -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.acting or not self.open_thread_id:
                return
            if action == "assign" and agent_id and agent_id not in {a.user_id for a in self.agents}:
                return  # arrived over the wire; refuse an id the team list does not hold
            self.acting = action
            self.banner = ""
            thread_id, connection_id = self.open_thread_id, self._connection_id
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        gw = gateway()
        try:
            if tenant_id is None or thread is None or connection is None:
                raise PermissionError
            if action == "takeover":
                user = await self._acting_user(tenant_id)
                if user is None:
                    async with self:
                        self.acting = ""
                        self._set_banner(_NO_USER, "error")
                    return
                await asyncio.to_thread(gw.takeover, tenant_id, connection, thread, user)
            elif action == "resume":
                await asyncio.to_thread(gw.resume, tenant_id, connection, thread)
            elif action == "close":
                await asyncio.to_thread(gw.close, tenant_id, connection, thread)
            elif action == "reopen":
                await asyncio.to_thread(gw.reopen, tenant_id, connection, thread)
            elif action == "assign":
                await asyncio.to_thread(
                    gw.assign, tenant_id, connection, thread, _uuid(agent_id) if agent_id else None
                )
        except PermissionError:
            async with self:
                self.acting = ""
                self._set_banner(_NO_SESSION, "error")
            return
        except ThreadNotFound:
            async with self:
                self.acting = ""
                self._set_banner(_THREAD_GONE, "warn")
            yield WhatsAppChatsState.refresh
            return
        except UnknownAgent:
            async with self:
                self.acting = ""
                self._set_banner(_UNKNOWN_AGENT, "warn")
            return
        except _DB_ERRORS as exc:
            logger.error("whatsapp chats %s failed: %s", action, type(exc).__name__)
            async with self:
                self.acting = ""
                self._set_banner(_ACTION_FAILED, "error")
            return
        async with self:
            self.acting = ""
            if action in ("takeover", "resume"):
                self._mark_paused(thread_id, action == "takeover")
            elif action in ("close", "reopen"):
                closed = action == "close"
                self.rows = [
                    dataclasses.replace(r, status="closed" if closed else "open", is_closed=closed)
                    if r.thread_id == thread_id
                    else r
                    for r in self.rows
                ]
        yield WhatsAppChatsState.refresh
