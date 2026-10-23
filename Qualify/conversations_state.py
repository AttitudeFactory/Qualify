"""Reflex state for `/conversations` (QUA-226, E2): the multichannel private inbox.

Custody, inherited from `whatsapp_chats_state.py`: the tenant comes from `AuthState`
(server-side, through `get_state`, never as an event argument); the state holds only the
frozen VMs of `conversations_vm.py` in client vars; the raw records a refresh merges live
in backend-only (`_`) vars and never reach the browser. Every Postgres call runs in a
background event through `asyncio.to_thread`.

**Loading.** `enter_page` (the route's `on_load`) loads the tenant's Instagram accounts,
selects the first one that can read messages and loads its access state and thread list.
Switching the account resets everything tied to the previous one. A thread id or an
account id arriving from the browser is accepted only if the lists already hold it.

**Reading.** Opening a thread loads its messages, marks it read (`mark_read` is the
service's, `GREATEST` on `last_read_at`) and shows the counterpart «Visto» on Instagram
(`mark_seen`, best-effort). The row's attention flips to «Leída» locally before the
refresh confirms it. `close_conversation` leaves the pane (the ✕ on desktop, ← on a
phone).

**Writing.** While the person types, `typing_on` goes to the counterpart at most once
every `_TYPING_EVERY` seconds (Instagram clears it by itself). `send_reply` resolves the
logged-in person's `users.id` once per session, then `gateway().reply(...)` (one outbox
row per ≤ 1000-char part), `reply_media(...)` and/or `reply_sticker(...)` — the human
approval is that id and the instant. The service refuses before writing when the window
is closed (`WindowClosed`) or the channel has no sender (`UnknownChannel`); both are
worded, never a 500. Nothing is sent inline: the row waits in the outbox for the worker,
and the bubble says «Enviando» until then.

**Attachments.** A dropped file (photo, audio, video, PDF) is staged in R2 right away
(`stage_attachment`) and shown as a chip; it is queued only when «Responder» is pressed.
One attachment per reply; text and attachment together become two replies (Instagram
takes one body per message). A **voice note** is recorded by `assets/qualify-voice.js`
(WAV, in the browser) and handed over in base64 parts under the websocket's 1 MB limit:
`stop_recording` → `voice_stopped` (how many parts) → `voice_part` × n → staged like any
other audio.

**Assisted replies (E4).** «Sugerir respuesta» asks the gateway for ONE draft of the
last inbound; its text lands in the box with a chip that says it is a suggestion (and
«requiere revisión» when the generator could not ground something). The person edits or
not; on «Responder» the draft is decided (`accepted` / `edited`) and its id travels in
the approval. «Descartar» decides `discarded`. A gate refusal is a toast, never an error.

**Message templates (m-24789472, PR 1).** «Plantillas», beside the tools, opens the
account's library (loaded once per account, the four defaults seeded on first use).
Picking one asks the gateway to render it for THIS thread (`{nombre}`, `{marca}`) and
puts the text in the box, REPLACING what was there — the same as «Sugerir respuesta»; a
suggestion in the box is set aside (`discarded`). A line over the box then names what is
still to be completed (a `{variable}` with no value, a `[fill-in]`) until the person
replaces it. Picking never sends and never queues: the text leaves only through
`send_reply`. «Administrar plantillas» opens a drawer to create, edit, delete (with
confirmation) and reorder; the service's refusals (`ReplyTemplateError.message`) are
shown inline as they come.

**Refresh.** A hidden `rx.moment` heartbeat in the page (15 s) calls `refresh`, which
re-reads the access state, the list and the open conversation without skeletons. A thread
whose newest inbound arrived since the last read pulses and is announced with a toast. A
failed sync is a short toast too — once per failure, never a banner.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import dataclasses
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import reflex as rx
from qualify_api.claude_tools import ClaudeToolError, MissingAPIKey
from qualify_api.conversations.contracts import (
    ACTION_MARK_SEEN,
    ACTION_TYPING_OFF,
    ACTION_TYPING_ON,
    UnknownChannel,
)
from qualify_api.conversations.drafts import DraftStatus, InvalidDraftTransition, UnknownDraft
from qualify_api.conversations.outbox import ApprovalRequired
from qualify_api.conversations.repository import MessageRecord
from qualify_api.conversations.service import ThreadNotFound, WindowClosed
from qualify_api.conversations.suggest import SuggestionRefused
from qualify_api.conversations.templates import (
    ERR_TEMPLATE_NOT_FOUND,
    ReplyTemplateError,
    ReplyTemplateNotFound,
)
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .conversations_provider import gateway
from .conversations_vm import (
    DEFAULT_FILTER,
    EMPTY_ACCESS,
    EMPTY_ACCOUNT,
    EMPTY_ATTACHMENT,
    EMPTY_DRAFT,
    EMPTY_THREAD,
    FILTER_ALL,
    FILTER_ANSWERED,
    FILTER_KEYS,
    FILTER_PENDING,
    FILTER_READ,
    HEART_TEXT,
    MAX_TEMPLATE_BODY_CHARS,
    MAX_TEMPLATE_TITLE_CHARS,
    MAX_TEMPLATES_PER_ACCOUNT,
    MEDIA_AUDIO,
    QUIET_ACCESS_KINDS,
    VOICE_CONTENT_TYPE,
    WINDOW_CLOSED_NOTICE,
    AccessVM,
    AccountVM,
    AttachmentVM,
    DraftVM,
    MessageVM,
    TemplateVM,
    ThreadRowVM,
    UnsentItem,
    attention_pill,
    build_access_vm,
    build_conversation,
    build_draft_vm,
    build_template_rows,
    build_thread_row,
    char_counter,
    classify_attachment,
    composer_enabled,
    filter_counts,
    filter_label,
    filter_threads,
    moved_order,
    newly_pending,
    reply_as_label,
    reply_parts_hint,
    reply_sent_message,
    suggestion_refusal_label,
    template_counter,
    template_notice,
    validate_reply,
    voice_note_name,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_ACCOUNTS_FAILED = (
    "No se pudieron cargar las cuentas conectadas. Vuelve a intentarlo en un momento."
)
_LIST_FAILED = "No se pudieron cargar las conversaciones. Vuelve a intentarlo en un momento."
_CONV_FAILED = "No se pudo cargar esta conversación. Vuelve a intentarlo en un momento."
_THREAD_GONE = "Esa conversación ya no está disponible en esta cuenta."
_NO_USER = (
    "No encontramos tu usuario en este negocio, así que no podemos firmar la respuesta. "
    "Pide al equipo de Qualify que lo revise."
)
_NO_SENDER = (
    "Todavía no podemos enviar mensajes por este canal desde Qualify. "
    "Responde desde Instagram por ahora."
)
_REJECTED = "Instagram no acepta esa respuesta tal como está."
_ACTION_FAILED = "No se pudo completar la acción. Vuelve a intentarlo en un momento."
_NEEDS_APPROVAL = "La respuesta no salió: falta que la apruebes."
_ATTACH_FAILED = "No se pudo guardar el adjunto. Vuelve a intentarlo en un momento."
_ATTACH_UNREADABLE = "No se pudo leer el archivo."
_HIDDEN = "Mensaje eliminado para ti. La otra persona sigue viéndolo en Instagram."
_HEART_QUEUED = "Listo, le enviaste un corazón. Sale en unos segundos."
_SYNC_FAILED_TOAST = (
    "No pudimos traer los mensajes nuevos de Instagram. Lo intentamos de nuevo enseguida."
)
_SUGGEST_UNAVAILABLE = "Ahora no podemos sugerirte una respuesta. Escríbela tú."
_SUGGEST_FAILED = "No se pudo generar la sugerencia. Vuelve a intentarlo en un momento."
_SUGGEST_READY = "Sugerencia lista. Revísala, edítala si hace falta y envíala."
_MIC_DENIED = "No se pudo usar el micrófono. Revisa el permiso del navegador."
_VOICE_EMPTY = "La grabación quedó vacía."
_VOICE_BROKEN = "No se pudo recibir la grabación. Vuelve a intentarlo."
_TEMPLATES_FAILED = "No se pudieron cargar las plantillas. Vuelve a intentarlo en un momento."
_TEMPLATE_FAILED = "No se pudo usar la plantilla. Vuelve a intentarlo en un momento."
_TEMPLATE_SAVE_FAILED = "No se pudo guardar la plantilla. Vuelve a intentarlo en un momento."
_TEMPLATE_ACTION_FAILED = "No se pudo cambiar la plantilla. Vuelve a intentarlo en un momento."
_TEMPLATE_CREATED = "Plantilla creada."
_TEMPLATE_SAVED = "Cambios guardados."
_TEMPLATE_DELETED = "Plantilla borrada."
_TOAST_MS = 4000


def _suggest_failure_words(exc: Exception) -> str:
    """The vendor's error, in the person's words when it is one they can act on."""
    text = str(exc).lower()
    if "credit balance" in text or "billing" in text:
        return (
            "Ahora no podemos sugerirte una respuesta por un problema de nuestro lado. "
            "Escríbela tú y avisa al equipo de Qualify."
        )
    if "rate" in text and "limit" in text:
        return "Hay mucha demanda ahora mismo. Vuelve a intentarlo en un momento."
    return _SUGGEST_FAILED


#: `typing_on` is re-sent at most this often while the person keeps typing.
_TYPING_EVERY_S = 6.0

_DB_ERRORS = (SQLAlchemyError,)

_JS_VOICE_START = "window.qualifyVoice ? window.qualifyVoice.start() : false"
_JS_VOICE_STOP = (
    'window.qualifyVoice ? window.qualifyVoice.stop() : \'{"seconds":0,"bytes":0,"parts":0}\''
)
_JS_VOICE_CANCEL = "window.qualifyVoice && window.qualifyVoice.cancel()"
_JS_VOICE_CLEAR = "window.qualifyVoice && window.qualifyVoice.clear()"


def _js_voice_part(index: int) -> str:
    return f"window.qualifyVoice ? window.qualifyVoice.part({int(index)}) : ''"


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


def default_account(accounts: list[AccountVM]) -> str:
    """Which account the inbox opens on: the first one that can actually read messages
    (scope granted, connection alive); failing that, the first one — its banner then says
    what to fix. "" without accounts."""
    for account in accounts:
        if account.can_manage_dms and not account.is_degraded:
            return account.connection_id
    return accounts[0].connection_id if accounts else ""


class ConversationsState(rx.State):
    """State for `/conversations`."""

    # -- accounts -----------------------------------------------------------------------
    accounts: list[AccountVM] = []
    selected_connection_id: str = ""
    accounts_loaded: bool = False
    accounts_loading: bool = False
    load_error: str = ""

    # -- access (the banner over the list) ----------------------------------------------
    access: AccessVM = EMPTY_ACCESS

    # -- list ---------------------------------------------------------------------------
    rows: list[ThreadRowVM] = []
    filter_key: str = DEFAULT_FILTER
    list_loaded_for: str = ""
    list_loading_for: str = ""
    list_error: str = ""

    # -- conversation -------------------------------------------------------------------
    open_thread_id: str = ""
    messages: list[MessageVM] = []
    conv_loaded_for: str = ""
    conv_loading_for: str = ""
    conv_error: str = ""

    # -- composer -----------------------------------------------------------------------
    draft_text: str = ""
    attachment: AttachmentVM = EMPTY_ATTACHMENT
    attaching: bool = False
    sending: bool = False
    banner: str = ""
    banner_tone: str = "info"
    # E4: the suggestion the box holds, if any.
    suggestion: DraftVM = EMPTY_DRAFT
    suggesting: bool = False
    # Voice note: recording / receiving its parts.
    recording: bool = False
    receiving_voice: bool = False

    # -- message templates (m-24789472) -------------------------------------------------
    templates: list[TemplateVM] = []
    templates_loaded_for: str = ""  # the account whose library `templates` holds
    templates_loading: bool = False
    templates_error: str = ""
    templates_menu_open: bool = False
    applying_template_id: str = ""
    # What the last picked template left to complete (the notice re-checks the box).
    applied_unresolved: list[str] = []
    applied_blanks: list[str] = []
    # The manager drawer and its form.
    templates_manager_open: bool = False
    template_form_open: bool = False
    template_editing_id: str = ""  # "" while creating
    template_form_title: str = ""
    template_form_body: str = ""
    template_form_error: str = ""
    template_saving: bool = False
    template_confirm_delete_id: str = ""
    templates_working: bool = False

    # -- backend only -------------------------------------------------------------------
    _zone_name: str = ""
    _user_id: str = ""
    _records: list[MessageRecord] = []
    _unsent: list[UnsentItem] = []
    _media_sources: dict[str, str] = {}
    _refreshing: bool = False
    _typing_sent_at: float = 0.0
    _sync_failure_key: str = ""
    _voice_parts: list[str] = []
    _voice_total: int = 0
    _voice_seconds: int = 0

    # ==================================================================================
    # Computed vars
    # ==================================================================================

    @rx.var
    def has_accounts(self) -> bool:
        return len(self.accounts) > 0

    @rx.var
    def has_many_accounts(self) -> bool:
        return len(self.accounts) > 1

    @rx.var
    def show_no_accounts(self) -> bool:
        return self.accounts_loaded and not self.accounts

    @rx.var
    def selected_account(self) -> AccountVM:
        for account in self.accounts:
            if account.connection_id == self.selected_connection_id:
                return account
        return EMPTY_ACCOUNT

    @rx.var
    def show_access_banner(self) -> bool:
        return self.selected_connection_id != "" and self.access.kind not in QUIET_ACCESS_KINDS

    @rx.var
    def visible_rows(self) -> list[ThreadRowVM]:
        return filter_threads(self.rows, self.filter_key)

    @rx.var
    def filter_all_label(self) -> str:
        return filter_label(FILTER_ALL, filter_counts(self.rows)[FILTER_ALL])

    @rx.var
    def filter_pending_label(self) -> str:
        return filter_label(FILTER_PENDING, filter_counts(self.rows)[FILTER_PENDING])

    @rx.var
    def filter_read_label(self) -> str:
        return filter_label(FILTER_READ, filter_counts(self.rows)[FILTER_READ])

    @rx.var
    def filter_answered_label(self) -> str:
        return filter_label(FILTER_ANSWERED, filter_counts(self.rows)[FILTER_ANSWERED])

    @rx.var
    def pending_count(self) -> int:
        return filter_counts(self.rows)[FILTER_PENDING]

    @rx.var
    def list_ready(self) -> bool:
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
    def account_can_reply(self) -> bool:
        account = self.selected_account
        return account.can_manage_dms and not account.is_degraded

    @rx.var
    def can_compose(self) -> bool:
        return composer_enabled(
            self.open_thread.window_open, self.open_thread_id != "", self.account_can_reply
        )

    @rx.var
    def has_attachment(self) -> bool:
        return self.attachment.object_key != ""

    @rx.var
    def has_suggestion(self) -> bool:
        return self.suggestion.draft_id != ""

    @rx.var
    def busy(self) -> bool:
        """Anything in flight that should hold the composer's other actions."""
        return self.sending or self.attaching or self.suggesting or self.receiving_voice

    @rx.var
    def compose_error(self) -> str:
        if self.attachment.object_key and not self.draft_text.strip():
            return ""
        return validate_reply(self.draft_text)

    @rx.var
    def compose_hint(self) -> str:
        """What sits under the box: in how many messages a long text goes out, else the
        validation message once the person typed something (an empty box needs no
        scolding: «Responder» is off)."""
        parts = reply_parts_hint(self.draft_text)
        if parts:
            return parts
        return self.compose_error if self.draft_text.strip() else ""

    @rx.var
    def can_send(self) -> bool:
        return (
            self.can_compose and self.compose_error == "" and not self.busy and not self.recording
        )

    @rx.var
    def can_suggest(self) -> bool:
        return self.can_compose and not self.busy and not self.recording

    @rx.var
    def reply_as(self) -> str:
        return reply_as_label(self.selected_account)

    @rx.var
    def window_notice(self) -> str:
        """The sentence over the composer: when the person can still answer, or why not."""
        if not self.open_thread_id:
            return ""
        return self.open_thread.window_label

    @rx.var
    def window_closed_notice(self) -> str:
        if self.open_thread_id and not self.open_thread.window_open:
            return WINDOW_CLOSED_NOTICE
        return ""

    # -- message templates --------------------------------------------------------------

    @rx.var
    def templates_ready(self) -> bool:
        return (
            self.selected_connection_id != ""
            and self.templates_loaded_for == self.selected_connection_id
        )

    @rx.var
    def templates_empty(self) -> bool:
        return self.templates_ready and len(self.templates) == 0

    @rx.var
    def templates_counter(self) -> str:
        return template_counter(len(self.templates))

    @rx.var
    def templates_at_limit(self) -> bool:
        return len(self.templates) >= MAX_TEMPLATES_PER_ACCOUNT

    @rx.var
    def can_open_templates(self) -> bool:
        """The picker opens with a conversation on screen; using a template also needs
        the composer (`can_use_template`), managing the library does not."""
        return self.open_thread_id != "" and not self.busy and not self.recording

    @rx.var
    def can_use_template(self) -> bool:
        return self.can_compose and not self.busy and not self.recording

    @rx.var
    def template_fill_notice(self) -> str:
        return template_notice(self.draft_text, self.applied_unresolved, self.applied_blanks)

    @rx.var
    def template_form_heading(self) -> str:
        return "Editar plantilla" if self.template_editing_id else "Nueva plantilla"

    @rx.var
    def template_title_counter(self) -> str:
        return char_counter(self.template_form_title, MAX_TEMPLATE_TITLE_CHARS)

    @rx.var
    def template_body_counter(self) -> str:
        return char_counter(self.template_form_body, MAX_TEMPLATE_BODY_CHARS)

    @rx.var
    def templates_account_label(self) -> str:
        label = self.selected_account.label
        return f"Plantillas de {label}" if label else "Plantillas de esta cuenta"

    @rx.var
    def account_blocked_notice(self) -> str:
        """Why the composer is off for reasons of the account, not of the window."""
        if not self.open_thread_id or self.account_can_reply:
            return ""
        if self.selected_account.is_degraded:
            return "La conexión de esta cuenta caducó: reconéctala para responder."
        return "Esta cuenta no tiene el permiso de mensajes: reconéctala concediéndolo."

    # ==================================================================================
    # Plumbing
    # ==================================================================================

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _reset_templates(self) -> None:
        """Everything tied to one account's library (the account changed)."""
        self.templates = []
        self.templates_loaded_for = ""
        self.templates_loading = False
        self.templates_error = ""
        self.templates_menu_open = False
        self.templates_manager_open = False
        self._close_template_form()
        self.template_confirm_delete_id = ""
        self.templates_working = False

    def _close_template_form(self) -> None:
        self.template_form_open = False
        self.template_editing_id = ""
        self.template_form_title = ""
        self.template_form_body = ""
        self.template_form_error = ""
        self.template_saving = False

    def _reset_list(self) -> None:
        self._reset_templates()
        self.rows = []
        self.list_loaded_for = ""
        self.list_loading_for = ""
        self.list_error = ""
        self.access = EMPTY_ACCESS
        self.open_thread_id = ""
        self._reset_conversation()

    def _reset_conversation(self) -> None:
        self.messages = []
        self.conv_loaded_for = ""
        self.conv_loading_for = ""
        self.conv_error = ""
        self._records = []
        self._unsent = []
        self._media_sources = {}
        self.draft_text = ""
        self.attachment = EMPTY_ATTACHMENT
        self.attaching = False
        self.suggestion = EMPTY_DRAFT
        self.suggesting = False
        self.recording = False
        self.receiving_voice = False
        self._voice_parts = []
        self._voice_total = 0
        self.banner = ""
        self._typing_sent_at = 0.0
        self.applying_template_id = ""
        self.applied_unresolved = []
        self.applied_blanks = []
        self.templates_menu_open = False

    def _render_conversation(self) -> None:
        self.messages = build_conversation(
            self._records,
            self._unsent,
            now=self._now(),
            zone=_zone(self._zone_name),
            media_sources=self._media_sources,
        )

    def _set_banner(self, message: str, tone: str) -> None:
        self.banner, self.banner_tone = message, tone

    def _mark_row_read(self, thread_id: str) -> None:
        """The optimistic flip of the row: pending → read, before the refresh confirms."""
        label, tone = attention_pill("read")
        self.rows = [
            dataclasses.replace(
                r, attention="read", attention_label=label, attention_tone=tone, fresh=False
            )
            if r.thread_id == thread_id and r.attention == "pending"
            else r
            for r in self.rows
        ]

    # ==================================================================================
    # Entry and accounts
    # ==================================================================================

    @rx.event
    def enter_page(self) -> rx.event.EventSpec | None:
        """The route's `on_load`, after `AuthState.require_login`."""
        if self.accounts_loading:
            return None
        return ConversationsState.load_accounts

    @rx.event(background=True)
    async def load_accounts(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            self.accounts_loading = True
            self.load_error = ""
            tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.accounts_loading = False
                self.accounts_loaded = True
                self.load_error = _NO_SESSION
            return
        gw = gateway()
        try:
            zone_name = await asyncio.to_thread(gw.timezone, tenant_id)
            accounts = await asyncio.to_thread(gw.accounts, tenant_id)
        except _DB_ERRORS as exc:
            logger.error("conversations accounts failed: %s", type(exc).__name__)
            async with self:
                self.accounts_loading = False
                self.accounts_loaded = True
                self.load_error = _ACCOUNTS_FAILED
            return
        async with self:
            self._zone_name = zone_name
            self.accounts = accounts
            self.accounts_loading = False
            self.accounts_loaded = True
            ids = {a.connection_id for a in accounts}
            if self.selected_connection_id not in ids:
                self.selected_connection_id = default_account(accounts)
                self._reset_list()
            selected = self.selected_connection_id
        if selected:
            failed = await self._read_access(silent=False)
            await self._read_list(silent=False)
            if failed:
                yield rx.toast.warning(_SYNC_FAILED_TOAST, duration=_TOAST_MS)

    @rx.event
    def select_account(self, connection_id: str) -> rx.event.EventSpec | None:
        """The header's account selector."""
        if not isinstance(connection_id, str) or connection_id == self.selected_connection_id:
            return None
        if connection_id not in {a.connection_id for a in self.accounts}:
            return None  # arrived over the wire; refuse an id the list does not hold
        self.selected_connection_id = connection_id
        self._reset_list()
        self._sync_failure_key = ""
        return ConversationsState.load_list

    # ==================================================================================
    # Access + list
    # ==================================================================================

    @rx.event
    def set_filter(self, key: str | list[str]) -> None:
        if isinstance(key, str) and key in FILTER_KEYS:
            self.filter_key = key

    @rx.event(background=True)
    async def load_list(self) -> AsyncIterator[rx.event.EventSpec]:
        failed = await self._read_access(silent=False)
        await self._read_list(silent=False)
        if failed:
            yield rx.toast.warning(_SYNC_FAILED_TOAST, duration=_TOAST_MS)

    async def _read_access(self, *, silent: bool) -> bool:
        """Re-read the account's access/sync state. Returns True when a sync failure not
        yet announced is on the row (the caller toasts it, once)."""
        async with self:
            connection_id = self.selected_connection_id
            account = self.selected_account
            tenant_id = await self._tenant()
        connection = _uuid(connection_id)
        if tenant_id is None or connection is None:
            return False
        try:
            state = await asyncio.to_thread(gateway().access, tenant_id, connection)
        except _DB_ERRORS as exc:
            logger.error("conversations access failed: %s", type(exc).__name__)
            return False
        async with self:
            if self.selected_connection_id != connection_id:
                return False
            self.access = build_access_vm(
                state, account=account, now=self._now(), zone=_zone(self._zone_name)
            )
            key = self.access.failure_key
            if key and key != self._sync_failure_key:
                self._sync_failure_key = key
                return True
            return False

    async def _read_list(self, *, silent: bool) -> list[ThreadRowVM]:
        """Re-read this account's threads. Returns the rows that became pending since
        the previous read (what a refresh announces); [] when nothing new or on error."""
        async with self:
            connection_id = self.selected_connection_id
            account_label = self.selected_account.label
            if not connection_id:
                return []
            if not silent:
                self.list_loading_for = connection_id
                self.list_error = ""
            tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.list_loading_for = ""
                self.list_error = _NO_SESSION
            return []
        connection = _uuid(connection_id)
        if connection is None:
            return []
        try:
            listing = await asyncio.to_thread(gateway().threads, tenant_id, connection)
        except _DB_ERRORS as exc:
            logger.error("conversations list failed: %s", type(exc).__name__)
            async with self:
                if self.selected_connection_id == connection_id:
                    self.list_loading_for = ""
                    if not silent or not self.list_loaded_for:
                        self.list_error = _LIST_FAILED
            return []
        async with self:
            if self.selected_connection_id != connection_id:
                return []  # the person switched accounts meanwhile
            zone, now = _zone(self._zone_name), self._now()
            previous = self.rows if silent else []
            rows = [
                build_thread_row(
                    item.view, item.extra, now=now, zone=zone, account_label=account_label
                )
                for item in listing
            ]
            fresh_ids = set(newly_pending(previous, rows))
            if fresh_ids:
                rows = [
                    dataclasses.replace(r, fresh=True) if r.thread_id in fresh_ids else r
                    for r in rows
                ]
            self.rows = rows
            self.list_loaded_for = connection_id
            self.list_loading_for = ""
            self.list_error = ""
            if self.open_thread_id and self.open_thread_id not in {r.thread_id for r in self.rows}:
                self.open_thread_id = ""
                self._reset_conversation()
            return [r for r in rows if r.thread_id in fresh_ids]

    # ==================================================================================
    # Conversation
    # ==================================================================================

    @rx.event
    def open_conversation(self, thread_id: str) -> rx.event.EventSpec | None:
        if not isinstance(thread_id, str) or thread_id == self.open_thread_id:
            return None
        if thread_id not in {r.thread_id for r in self.rows}:
            return None  # arrived over the wire; refuse an id the list does not hold
        self.open_thread_id = thread_id
        self._reset_conversation()
        return ConversationsState.load_conversation

    @rx.event
    def close_conversation(self) -> rx.event.EventSpec | None:
        """Leave the conversation pane (✕ on desktop, ← on a phone). A recording in
        progress is dropped."""
        was_recording = self.recording
        self.open_thread_id = ""
        self._reset_conversation()
        return rx.call_script(_JS_VOICE_CANCEL) if was_recording else None

    @rx.event
    def back_to_list(self) -> rx.event.EventSpec | None:
        return self.close_conversation()

    @rx.event(background=True)
    async def load_conversation(self) -> None:
        await self._read_conversation(silent=False, mark_read=True)

    async def _read_conversation(self, *, silent: bool, mark_read: bool = False) -> None:
        async with self:
            thread_id = self.open_thread_id
            connection_id = self.selected_connection_id
            if not thread_id or (not silent and self.conv_loading_for == thread_id):
                return
            if not silent:
                self.conv_loading_for = thread_id
                self.conv_error = ""
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        if tenant_id is None or thread is None or connection is None:
            async with self:
                self.conv_loading_for = ""
                self.conv_error = _NO_SESSION if tenant_id is None else _CONV_FAILED
            return
        gw = gateway()
        try:
            conv = await asyncio.to_thread(gw.conversation, tenant_id, connection, thread)
            if mark_read and conv.view.thread.last_inbound_at is not None:
                await asyncio.to_thread(gw.mark_read, tenant_id, connection, thread)
        except ThreadNotFound:
            async with self:
                if self.open_thread_id == thread_id:
                    self.open_thread_id = ""
                    self._reset_conversation()
                    self._set_banner(_THREAD_GONE, "warn")
            return
        except _DB_ERRORS as exc:
            logger.error("conversations conversation failed: %s", type(exc).__name__)
            async with self:
                if self.open_thread_id == thread_id:
                    self.conv_loading_for = ""
                    if not silent or not self.conv_loaded_for:
                        self.conv_error = _CONV_FAILED
            return
        async with self:
            if self.open_thread_id != thread_id:
                return  # another conversation was opened meanwhile
            self._records = list(conv.messages)
            self._unsent = conv.unsent
            self._media_sources = dict(conv.media_sources)
            self._render_conversation()
            self.conv_loaded_for = thread_id
            self.conv_loading_for = ""
            self.conv_error = ""
            if mark_read:
                self._mark_row_read(thread_id)
                # A suggestion left pending on a previous visit comes back into the box.
                if conv.pending_draft is not None and not self.draft_text.strip():
                    self.suggestion = build_draft_vm(conv.pending_draft)
                    self.draft_text = self.suggestion.text
        if mark_read and conv.view.thread.last_inbound_at is not None:
            # The counterpart sees «Visto» on Instagram. Best-effort, after the screen.
            await gw.signal(tenant_id, connection, thread, ACTION_MARK_SEEN)

    # ==================================================================================
    # Refresh (15 s heartbeat + after every action)
    # ==================================================================================

    @rx.event(background=True)
    async def refresh(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self._refreshing or not self.list_loaded_for or self.list_loading_for:
                return
            self._refreshing = True
        try:
            failed = await self._read_access(silent=True)
            fresh = await self._read_list(silent=True)
            await self._read_conversation(silent=True)
        finally:
            async with self:
                self._refreshing = False
        if failed:
            yield rx.toast.warning(_SYNC_FAILED_TOAST, duration=_TOAST_MS)
        for row in fresh[:3]:
            yield rx.toast.info(f"Nuevo mensaje de {row.title}", duration=_TOAST_MS)

    # ==================================================================================
    # Composer: text
    # ==================================================================================

    @rx.event
    def set_draft_text(self, value: str) -> rx.event.EventSpec | None:
        self.draft_text = value if isinstance(value, str) else ""
        if not self.draft_text.strip() or not self.can_compose:
            return None
        if time.monotonic() - self._typing_sent_at < _TYPING_EVERY_S:
            return None
        self._typing_sent_at = time.monotonic()
        return ConversationsState.signal_typing

    @rx.event(background=True)
    async def signal_typing(self) -> None:
        async with self:
            thread_id, connection_id = self.open_thread_id, self.selected_connection_id
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        if tenant_id is None or thread is None or connection is None:
            return
        await gateway().signal(tenant_id, connection, thread, ACTION_TYPING_ON)

    @rx.event
    def dismiss_banner(self) -> None:
        self.banner = ""

    @rx.event(background=True)
    async def hide_message(self, message_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """«Eliminar para mí»: the bubble leaves this inbox, nothing reaches Instagram
        (its API cannot unsend or edit). Only a real message; a queued row is not one."""
        if not isinstance(message_id, str) or message_id.startswith("outbox-"):
            return
        async with self:
            thread_id, connection_id = self.open_thread_id, self.selected_connection_id
            known = {m.message_id for m in self.messages}
            tenant_id = await self._tenant()
        thread, connection, message = _uuid(thread_id), _uuid(connection_id), _uuid(message_id)
        if tenant_id is None or thread is None or connection is None or message is None:
            return
        if message_id not in known:
            return  # arrived over the wire; refuse an id the screen does not hold
        try:
            hidden = await asyncio.to_thread(
                gateway().hide_message, tenant_id, connection, thread, message
            )
        except (ThreadNotFound, *_DB_ERRORS) as exc:
            logger.error("conversations hide failed: %s", type(exc).__name__)
            yield rx.toast.error(_ACTION_FAILED, duration=_TOAST_MS)
            return
        if hidden:
            async with self:
                self._records = [r for r in self._records if str(r.id) != message_id]
                self._render_conversation()
            yield rx.toast.info(_HIDDEN, duration=_TOAST_MS)

    @rx.event
    def clear_attachment(self) -> None:
        self.attachment = EMPTY_ATTACHMENT

    # ==================================================================================
    # Composer: attachments (files)
    # ==================================================================================

    @rx.event
    async def handle_attachment(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """A dropped photo, audio, video or PDF: read, classify, stage in R2, show as a
        chip. One at a time — the first file wins."""
        if not files or not self.open_thread_id or not self.can_compose or self.attaching:
            return None
        upload = files[0]
        try:
            data = await upload.read()
        except Exception:  # noqa: BLE001 — the browser's stream, not ours
            self._set_banner(_ATTACH_UNREADABLE, "warn")
            return None
        content_type = (upload.content_type or "").strip()
        name = (upload.name or "archivo").split("/")[-1].split("\\")[-1]
        return await self._stage(data, content_type, name)

    async def _stage(self, data: bytes, content_type: str, name: str) -> rx.event.EventSpec | None:
        media_type, error = classify_attachment(content_type, len(data))
        if error:
            self._set_banner(error, "warn")
            return None
        auth = await self.get_state(AuthState)
        tenant_id = tenant_uuid(auth.session_tenant_id)
        connection = _uuid(self.selected_connection_id)
        if tenant_id is None or connection is None:
            self._set_banner(_NO_SESSION, "error")
            return None
        self.attaching = True
        self.banner = ""
        try:
            staged = await asyncio.to_thread(
                gateway().stage_attachment,
                tenant_id,
                connection,
                name=name,
                content_type=content_type,
                media_type=media_type,
                data=data,
            )
        except Exception as exc:  # noqa: BLE001 — R2 / gate errors are worded, never shown raw
            logger.error("conversations attachment failed: %s", type(exc).__name__)
            self.attaching = False
            self._set_banner(_ATTACH_FAILED, "error")
            return None
        self.attaching = False
        self.attachment = staged
        return None

    # ==================================================================================
    # Composer: voice note (assets/qualify-voice.js)
    # ==================================================================================

    @rx.event
    def start_recording(self) -> rx.event.EventSpec | None:
        if not self.can_compose or self.busy or self.recording or self.has_attachment:
            return None
        self.banner = ""
        return rx.call_script(_JS_VOICE_START, callback=ConversationsState.recording_started)

    @rx.event
    def recording_started(self, ok: bool) -> None:
        if ok is True:
            self.recording = True
            return
        self.recording = False
        self._set_banner(_MIC_DENIED, "warn")

    @rx.event
    def cancel_recording(self) -> rx.event.EventSpec:
        self.recording = False
        self.receiving_voice = False
        self._voice_parts = []
        self._voice_total = 0
        return rx.call_script(_JS_VOICE_CANCEL)

    @rx.event
    def stop_recording(self) -> rx.event.EventSpec | None:
        if not self.recording:
            return None
        self.recording = False
        self.receiving_voice = True
        return rx.call_script(_JS_VOICE_STOP, callback=ConversationsState.voice_stopped)

    @rx.event
    def voice_stopped(self, meta: str) -> rx.event.EventSpec | None:
        """The recorder says how many base64 parts there are; fetch them one by one."""
        try:
            info = json.loads(meta) if isinstance(meta, str) else {}
            total = int(info.get("parts", 0))
            seconds = int(info.get("seconds", 0))
        except (ValueError, TypeError, AttributeError):
            total, seconds = 0, 0
        if total <= 0:
            self.receiving_voice = False
            self._set_banner(_VOICE_EMPTY, "warn")
            return rx.call_script(_JS_VOICE_CLEAR)
        self._voice_parts = []
        self._voice_total = total
        self._voice_seconds = seconds
        return rx.call_script(_js_voice_part(0), callback=ConversationsState.voice_part)

    @rx.event
    async def voice_part(self, payload: str) -> rx.event.EventSpec | None:
        """One base64 part. The last one assembles the WAV and stages it like a file."""
        try:
            part = json.loads(payload) if isinstance(payload, str) else {}
            index = int(part.get("index", -1))
            data = str(part.get("data", ""))
        except (ValueError, TypeError, AttributeError):
            index, data = -1, ""
        if index != len(self._voice_parts) or not data:
            self.receiving_voice = False
            self._voice_parts = []
            self._set_banner(_VOICE_BROKEN, "warn")
            return rx.call_script(_JS_VOICE_CLEAR)
        self._voice_parts = [*self._voice_parts, data]
        if len(self._voice_parts) < self._voice_total:
            return rx.call_script(
                _js_voice_part(len(self._voice_parts)), callback=ConversationsState.voice_part
            )
        try:
            raw = b"".join(base64.b64decode(p) for p in self._voice_parts)
        except (binascii.Error, ValueError):
            self.receiving_voice = False
            self._voice_parts = []
            self._set_banner(_VOICE_BROKEN, "warn")
            return rx.call_script(_JS_VOICE_CLEAR)
        self._voice_parts = []
        self.receiving_voice = False
        name = voice_note_name(self._voice_seconds, self._now(), _zone(self._zone_name))
        await self._stage(raw, VOICE_CONTENT_TYPE, name)
        if self.attachment.object_key and self.attachment.media_type != MEDIA_AUDIO:
            self.attachment = EMPTY_ATTACHMENT
        return rx.call_script(_JS_VOICE_CLEAR)

    # ==================================================================================
    # Composer: assisted reply (E4)
    # ==================================================================================

    @rx.event(background=True)
    async def suggest_reply(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if not self.can_suggest or not self.open_thread_id:
                return
            self.suggesting = True
            self.banner = ""
            thread_id, connection_id = self.open_thread_id, self.selected_connection_id
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        if tenant_id is None or thread is None or connection is None:
            async with self:
                self.suggesting = False
                self._set_banner(_NO_SESSION, "error")
            return
        gw = gateway()
        try:
            draft = await asyncio.to_thread(gw.suggest, tenant_id, connection, thread)
        except SuggestionRefused as refusal:
            async with self:
                self.suggesting = False
            yield rx.toast.info(suggestion_refusal_label(refusal.reason), duration=_TOAST_MS)
            return
        except ThreadNotFound:
            async with self:
                self.suggesting = False
                self._set_banner(_THREAD_GONE, "warn")
            return
        except MissingAPIKey:
            async with self:
                self.suggesting = False
            yield rx.toast.warning(_SUGGEST_UNAVAILABLE, duration=_TOAST_MS)
            return
        except (ClaudeToolError, OSError, *_DB_ERRORS) as exc:
            logger.error("conversations suggest failed: %s", type(exc).__name__)
            async with self:
                self.suggesting = False
            yield rx.toast.error(_SUGGEST_FAILED, duration=_TOAST_MS)
            return
        except Exception as exc:  # noqa: BLE001 — the vendor SDK's own errors (billing, 5xx…)
            # Worded, never a stuck spinner: an `anthropic.APIStatusError` is not a
            # `ClaudeToolError`, and the person must be able to try again.
            logger.error("conversations suggest failed: %s: %s", type(exc).__name__, exc)
            async with self:
                self.suggesting = False
            yield rx.toast.error(_suggest_failure_words(exc), duration=_TOAST_MS * 2)
            return
        async with self:
            self.suggesting = False
            if self.open_thread_id != thread_id:
                return
            self.suggestion = build_draft_vm(draft)
            self.draft_text = self.suggestion.text
            self.applied_unresolved = []
            self.applied_blanks = []
        yield rx.toast.success(_SUGGEST_READY, duration=_TOAST_MS)

    @rx.event(background=True)
    async def discard_suggestion(self) -> None:
        async with self:
            draft_id = _uuid(self.suggestion.draft_id)
            self.suggestion = EMPTY_DRAFT
            self.draft_text = ""
            tenant_id = await self._tenant()
        if draft_id is None or tenant_id is None:
            return
        await self._discard_draft(tenant_id, draft_id)

    async def _discard_draft(self, tenant_id: UUID, draft_id: UUID) -> None:
        """Record `discarded` on a suggestion the person set aside. Best-effort."""
        user = await self._acting_user(tenant_id)
        if user is None:
            return
        try:
            await asyncio.to_thread(
                gateway().decide_draft,
                tenant_id,
                draft_id,
                status=DraftStatus.DISCARDED,
                final_text=None,
                user_id=user,
            )
        except (InvalidDraftTransition, UnknownDraft, *_DB_ERRORS) as exc:
            logger.info("conversations discard draft skipped: %s", type(exc).__name__)

    async def _decide_sent_draft(
        self, tenant_id: UUID, user: UUID, suggestion: DraftVM, text: str
    ) -> UUID | None:
        """Record the person's verdict on the suggestion they are sending: `accepted`
        when the text is the model's, `edited` otherwise. Returns the draft id to carry
        into the approval, or None when the draft is gone (the send still goes)."""
        draft_id = _uuid(suggestion.draft_id)
        if draft_id is None:
            return None
        edited = text.strip() != suggestion.text.strip()
        try:
            await asyncio.to_thread(
                gateway().decide_draft,
                tenant_id,
                draft_id,
                status=DraftStatus.EDITED if edited else DraftStatus.ACCEPTED,
                final_text=text if edited else None,
                user_id=user,
            )
        except (InvalidDraftTransition, UnknownDraft) as exc:
            logger.info("conversations draft decision skipped: %s", type(exc).__name__)
            return None
        return draft_id

    # ==================================================================================
    # Composer: send
    # ==================================================================================

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
    async def send_heart(self) -> AsyncIterator[rx.event.EventSpec]:
        """The ❤️ — one tap, queued like any reply, with this person's approval. It goes
        out as the emoji text (`HEART_TEXT`): the API's `like_heart` sticker shows as a
        white heart in the person's Instagram, the emoji as the big red one."""
        async with self:
            if self.busy or self.recording or not self.open_thread_id or not self.can_compose:
                return
            self.sending = True
            self.banner = ""
            thread_id, connection_id = self.open_thread_id, self.selected_connection_id
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
            await asyncio.to_thread(
                gateway().reply, tenant_id, connection, thread, user, HEART_TEXT
            )
        except PermissionError:
            async with self:
                self.sending = False
                self._set_banner(_NO_SESSION, "error")
            return
        except WindowClosed:
            async with self:
                self.sending = False
                self._set_banner(WINDOW_CLOSED_NOTICE, "warn")
            yield ConversationsState.refresh
            return
        except (ThreadNotFound, UnknownChannel, ApprovalRequired, ValueError, *_DB_ERRORS) as exc:
            logger.error("conversations heart failed: %s", type(exc).__name__)
            async with self:
                self.sending = False
                self._set_banner(_ACTION_FAILED, "error")
            return
        async with self:
            self.sending = False
        yield rx.toast.success(_HEART_QUEUED, duration=_TOAST_MS)
        yield ConversationsState.refresh

    @rx.event(background=True)
    async def send_reply(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.sending or not self.open_thread_id or not self.can_send:
                return
            self.sending = True
            self.banner = ""
            text = self.draft_text.strip()
            attachment = self.attachment
            suggestion = self.suggestion
            thread_id, connection_id = self.open_thread_id, self.selected_connection_id
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        gw = gateway()
        try:
            if tenant_id is None or thread is None or connection is None:
                raise PermissionError
            user = await self._acting_user(tenant_id)
            if user is None:
                async with self:
                    self.sending = False
                    self._set_banner(_NO_USER, "error")
                return
            draft_id: UUID | None = None
            if text and suggestion.draft_id:
                draft_id = await self._decide_sent_draft(tenant_id, user, suggestion, text)
            if attachment.object_key:
                await asyncio.to_thread(
                    gw.reply_media, tenant_id, connection, thread, user, attachment
                )
            if text:
                await asyncio.to_thread(
                    gw.reply, tenant_id, connection, thread, user, text, draft_id
                )
        except PermissionError:
            async with self:
                self.sending = False
                self._set_banner(_NO_SESSION, "error")
            return
        except WindowClosed:
            async with self:
                self.sending = False
                self._set_banner(WINDOW_CLOSED_NOTICE, "warn")
            yield ConversationsState.refresh
            return
        except ThreadNotFound:
            async with self:
                self.sending = False
                self._set_banner(_THREAD_GONE, "warn")
            yield ConversationsState.refresh
            return
        except UnknownChannel:
            async with self:
                self.sending = False
                self._set_banner(_NO_SENDER, "warn")
            return
        except ApprovalRequired:
            # Unreachable from here (the provider always builds the approval); worded
            # rather than swallowed so a regression is visible, never silent.
            async with self:
                self.sending = False
                self._set_banner(_NEEDS_APPROVAL, "error")
            return
        except ValueError:
            async with self:
                self.sending = False
                self._set_banner(_REJECTED, "error")
            return
        except _DB_ERRORS as exc:
            logger.error("conversations reply failed: %s", type(exc).__name__)
            async with self:
                self.sending = False
                self._set_banner(_ACTION_FAILED, "error")
            return
        async with self:
            self.sending = False
            if self.open_thread_id == thread_id:
                self.draft_text = ""
                self.attachment = EMPTY_ATTACHMENT
                self.suggestion = EMPTY_DRAFT
                self.applied_unresolved = []
                self.applied_blanks = []
                self._typing_sent_at = 0.0
            row = self.open_thread if self.open_thread_id == thread_id else EMPTY_THREAD
            who = row.handle or row.title
        yield rx.toast.success(reply_sent_message(who), duration=_TOAST_MS)
        yield ConversationsState.refresh
        await gw.signal(tenant_id, connection, thread, ACTION_TYPING_OFF)

    # ==================================================================================
    # Message templates (m-24789472): the picker
    # ==================================================================================

    @rx.event
    def set_templates_menu_open(self, value: bool) -> rx.event.EventSpec | None:
        """The «Plantillas» popover. Opening it loads the account's library once."""
        self.templates_menu_open = bool(value) and self.can_open_templates
        if self.templates_menu_open and not self.templates_ready and not self.templates_loading:
            return ConversationsState.load_templates
        return None

    @rx.event(background=True)
    async def load_templates(self) -> None:
        async with self:
            connection_id = self.selected_connection_id
            if not connection_id:
                return
            self.templates_loading = True
            self.templates_error = ""
            tenant_id = await self._tenant()
        connection = _uuid(connection_id)
        if tenant_id is None or connection is None:
            async with self:
                self.templates_loading = False
                self.templates_error = _NO_SESSION
            return
        try:
            library = await asyncio.to_thread(gateway().templates, tenant_id, connection)
        except ReplyTemplateError as refusal:
            async with self:
                if self.selected_connection_id == connection_id:
                    self.templates_loading = False
                    self.templates_error = refusal.message
            return
        except _DB_ERRORS as exc:
            logger.error("conversations templates failed: %s", type(exc).__name__)
            async with self:
                if self.selected_connection_id == connection_id:
                    self.templates_loading = False
                    self.templates_error = _TEMPLATES_FAILED
            return
        async with self:
            if self.selected_connection_id != connection_id:
                return  # the person switched accounts meanwhile
            self.templates = build_template_rows(library)
            self.templates_loaded_for = connection_id
            self.templates_loading = False
            self.templates_error = ""

    @rx.event(background=True)
    async def apply_template(self, template_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """Render the template for the open thread and put its text in the box, replacing
        what was there. Never sends, never queues: the person reviews and presses
        «Responder» — the same `send_reply` as any text."""
        async with self:
            if not isinstance(template_id, str) or not self.can_use_template:
                return
            if template_id not in {t.template_id for t in self.templates}:
                return  # arrived over the wire; refuse an id the library does not hold
            if self.applying_template_id:
                return
            self.applying_template_id = template_id
            self.banner = ""
            thread_id, connection_id = self.open_thread_id, self.selected_connection_id
            suggestion_id = _uuid(self.suggestion.draft_id)
            tenant_id = await self._tenant()
        thread, connection, template = _uuid(thread_id), _uuid(connection_id), _uuid(template_id)
        if tenant_id is None or thread is None or connection is None or template is None:
            async with self:
                self.applying_template_id = ""
                self._set_banner(_NO_SESSION, "error")
            return
        try:
            rendered = await asyncio.to_thread(
                gateway().render_template, tenant_id, connection, thread, template
            )
        except ThreadNotFound:
            async with self:
                self.applying_template_id = ""
                self.templates_menu_open = False
                self._set_banner(_THREAD_GONE, "warn")
            return
        except ReplyTemplateNotFound as missing:
            async with self:
                self.applying_template_id = ""
                self.templates_menu_open = False
                self._set_banner(missing.message, "warn")
                self.templates_loaded_for = ""
            yield ConversationsState.load_templates
            return
        except ReplyTemplateError as refusal:
            async with self:
                self.applying_template_id = ""
                self.templates_menu_open = False
                self._set_banner(refusal.message, "warn")
            return
        except _DB_ERRORS as exc:
            logger.error("conversations template render failed: %s", type(exc).__name__)
            async with self:
                self.applying_template_id = ""
                self._set_banner(_TEMPLATE_FAILED, "error")
            return
        async with self:
            self.applying_template_id = ""
            if self.open_thread_id != thread_id:
                return  # another conversation was opened meanwhile
            # A suggestion in the box is set aside: the text is no longer the model's.
            self.suggestion = EMPTY_DRAFT
            self.draft_text = rendered.text
            self.applied_unresolved = list(rendered.unresolved)
            self.applied_blanks = list(rendered.blanks)
            self.templates_menu_open = False
        if suggestion_id is not None:
            await self._discard_draft(tenant_id, suggestion_id)

    # ==================================================================================
    # Message templates: the manager (drawer)
    # ==================================================================================

    @rx.event
    def open_templates_manager(self) -> rx.event.EventSpec | None:
        if not self.selected_connection_id:
            return None
        self.templates_menu_open = False
        self.templates_manager_open = True
        self.template_confirm_delete_id = ""
        self._close_template_form()
        if not self.templates_ready and not self.templates_loading:
            return ConversationsState.load_templates
        return None

    @rx.event
    def set_templates_manager_open(self, value: bool) -> None:
        self.templates_manager_open = bool(value)
        if not self.templates_manager_open:
            self._close_template_form()
            self.template_confirm_delete_id = ""

    @rx.event
    def start_new_template(self) -> None:
        if self.templates_at_limit:
            return
        self._close_template_form()
        self.template_confirm_delete_id = ""
        self.template_form_open = True

    @rx.event
    def start_edit_template(self, template_id: str) -> None:
        for t in self.templates:
            if t.template_id == template_id:
                self._close_template_form()
                self.template_confirm_delete_id = ""
                self.template_form_open = True
                self.template_editing_id = t.template_id
                self.template_form_title = t.title
                self.template_form_body = t.body
                return

    @rx.event
    def cancel_template_form(self) -> None:
        self._close_template_form()

    @rx.event
    def set_template_form_title(self, value: str) -> None:
        self.template_form_title = value if isinstance(value, str) else ""
        self.template_form_error = ""

    @rx.event
    def set_template_form_body(self, value: str) -> None:
        self.template_form_body = value if isinstance(value, str) else ""
        self.template_form_error = ""

    async def _template_context(self) -> tuple[UUID, UUID] | None:
        """(tenant, account) — call under `async with self`. None without a session."""
        tenant_id = await self._tenant()
        connection = _uuid(self.selected_connection_id)
        if tenant_id is None or connection is None:
            return None
        return tenant_id, connection

    @rx.event(background=True)
    async def save_template(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Guardar»: create or edit. The service validates; its sentence shows inline."""
        async with self:
            if self.template_saving or not self.template_form_open:
                return
            self.template_saving = True
            self.template_form_error = ""
            editing = self.template_editing_id
            title, body = self.template_form_title, self.template_form_body
            context = await self._template_context()
            connection_id = self.selected_connection_id
        if context is None:
            async with self:
                self.template_saving = False
                self.template_form_error = _NO_SESSION
            return
        tenant_id, connection = context
        gw = gateway()
        try:
            user = await self._acting_user(tenant_id)
            if editing:
                template = _uuid(editing)
                if template is None:
                    raise ReplyTemplateNotFound(ERR_TEMPLATE_NOT_FOUND)
                await asyncio.to_thread(
                    gw.update_template, tenant_id, connection, template, user, title, body
                )
            else:
                await asyncio.to_thread(
                    gw.create_template, tenant_id, connection, user, title, body
                )
            library = await asyncio.to_thread(gw.templates, tenant_id, connection)
        except ReplyTemplateError as refusal:
            async with self:
                self.template_saving = False
                self.template_form_error = refusal.message
            return
        except _DB_ERRORS as exc:
            logger.error("conversations template save failed: %s", type(exc).__name__)
            async with self:
                self.template_saving = False
                self.template_form_error = _TEMPLATE_SAVE_FAILED
            return
        async with self:
            if self.selected_connection_id != connection_id:
                return
            self.templates = build_template_rows(library)
            self.templates_loaded_for = connection_id
            self.templates_error = ""
            self._close_template_form()
        yield rx.toast.success(
            _TEMPLATE_SAVED if editing else _TEMPLATE_CREATED, duration=_TOAST_MS
        )

    @rx.event
    def ask_delete_template(self, template_id: str) -> None:
        if template_id in {t.template_id for t in self.templates}:
            self._close_template_form()
            self.template_confirm_delete_id = template_id

    @rx.event
    def cancel_delete_template(self) -> None:
        self.template_confirm_delete_id = ""

    @rx.event(background=True)
    async def confirm_delete_template(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            template = _uuid(self.template_confirm_delete_id)
            if template is None or self.templates_working:
                return
            self.templates_working = True
            context = await self._template_context()
            connection_id = self.selected_connection_id
        if context is None:
            async with self:
                self.templates_working = False
                self.templates_error = _NO_SESSION
            return
        tenant_id, connection = context
        gw = gateway()
        try:
            try:
                await asyncio.to_thread(gw.delete_template, tenant_id, connection, template)
            except ReplyTemplateNotFound:
                pass  # already gone (a double tap, another device): the list catches up
            library = await asyncio.to_thread(gw.templates, tenant_id, connection)
        except ReplyTemplateError as refusal:
            async with self:
                self.templates_working = False
                self.template_confirm_delete_id = ""
                self.templates_error = refusal.message
            return
        except _DB_ERRORS as exc:
            logger.error("conversations template delete failed: %s", type(exc).__name__)
            async with self:
                self.templates_working = False
                self.template_confirm_delete_id = ""
                self.templates_error = _TEMPLATE_ACTION_FAILED
            return
        async with self:
            self.templates_working = False
            self.template_confirm_delete_id = ""
            if self.selected_connection_id != connection_id:
                return
            self.templates = build_template_rows(library)
            self.templates_loaded_for = connection_id
            self.templates_error = ""
        yield rx.toast.success(_TEMPLATE_DELETED, duration=_TOAST_MS)

    @rx.event(background=True)
    async def move_template(self, template_id: str, step: int) -> None:
        """«Subir» (-1) / «Bajar» (+1): the whole library in its new order goes to the
        service; a list that changed meanwhile comes back reloaded, with its words."""
        async with self:
            if self.templates_working or not isinstance(template_id, str):
                return
            ids = [t.template_id for t in self.templates]
            order = moved_order(ids, template_id, step if isinstance(step, int) else 0)
            if order is None:
                return
            self.templates_working = True
            self.templates_error = ""
            context = await self._template_context()
            connection_id = self.selected_connection_id
        wanted = [u for u in (_uuid(i) for i in order) if u is not None]
        if context is None or len(wanted) != len(order):
            async with self:
                self.templates_working = False
                self.templates_error = _NO_SESSION if context is None else _TEMPLATE_ACTION_FAILED
            return
        tenant_id, connection = context
        gw = gateway()
        try:
            library = await asyncio.to_thread(gw.reorder_templates, tenant_id, connection, wanted)
        except ReplyTemplateError as refusal:
            try:
                fresh = await asyncio.to_thread(gw.templates, tenant_id, connection)
            except (ReplyTemplateError, *_DB_ERRORS):
                fresh = None
            async with self:
                self.templates_working = False
                self.templates_error = refusal.message
                if fresh is not None and self.selected_connection_id == connection_id:
                    self.templates = build_template_rows(fresh)
            return
        except _DB_ERRORS as exc:
            logger.error("conversations template reorder failed: %s", type(exc).__name__)
            async with self:
                self.templates_working = False
                self.templates_error = _TEMPLATE_ACTION_FAILED
            return
        async with self:
            self.templates_working = False
            if self.selected_connection_id != connection_id:
                return
            self.templates = build_template_rows(library)
            self.templates_loaded_for = connection_id
