"""Reflex state for the connections screen (C-06).

Holds only whitelisted `ConnectionVM`s (never ORM rows), so nothing credential-bearing
can be serialized to the client. The active tenant comes from `AuthState` — set only
by a real login (QUA-66), per-session, so two browser sessions logged into different
businesses naturally see disjoint data — that is what makes the "session A never
paints tenant B" criterion (QUA-18) exercisable from the UI.

The connections come from Postgres, so they are loaded in a background event and run
off the event loop (`asyncio.to_thread`) — SQLAlchemy here is synchronous, and a
blocking call inside a background task would stall every other session's websocket.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import reflex as rx
from qualify_api.connections import ConnectionNotFound
from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.connections.token_health import TokenHealthError
from qualify_api.support import InvalidSupportRequest
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .connections_provider import (
    NoActingUser,
    begin_connect,
    check_health,
    connections_for,
    disconnect,
    request_support,
)
from .connections_vm import ConnectionVM, connect_result_guidance, connect_result_notice
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

# m-24840590: the DOM id of the connection guide card, the target of «Ver el paso N».
GUIDE_ELEMENT_ID = "guia-conexion"

# QUA-202: "Pedir ayuda 1:1" copy. Two success notices, because the two outcomes are not
# the same promise: a ticket the channel accepted gets a callback window; a ticket saved
# while no channel was configured (or the channel was down) is only "registrada".
_SUPPORT_SENT = (
    "Recibimos tu solicitud #{reference}. Una persona del equipo te escribirá a {email} "
    "en menos de un día hábil."
)
_SUPPORT_SAVED = (
    "Tu solicitud #{reference} quedó registrada. Te escribiremos a {email} en cuanto una "
    "persona del equipo la tome."
)
_SUPPORT_EMAIL_REQUIRED = "Escribe un correo válido para que podamos contactarte."
_SUPPORT_FAILED = (
    "No pudimos registrar tu solicitud. Vuelve a intentarlo en un momento o escríbenos a "
    "contacto@attitudefactory.co."
)

_LOAD_FAILED = "No se pudieron cargar las conexiones. Revisa la conexión con la base de datos."
_NO_TENANTS = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_DISCONNECT_FAILED = "No se pudo desconectar la cuenta. Revisa la conexión con la base de datos."
# Deliberately says "not found", never "revoked": `ConnectionNotFound` also covers
# "belongs to another tenant" (RLS makes them the same read), and answering "listo,
# revocada" to an id the operator does not own is precisely the bug being fixed.
_NOT_FOUND = "Esa conexión ya no existe. Actualizamos la lista con el estado real."
_CONNECT_FAILED = "No se pudo iniciar la conexión con Meta. Vuelve a intentarlo en un momento."
_NO_ACTING_USER = "Este tenant no tiene ningún usuario al que atribuir la conexión."
_HEALTH_CHECK_FAILED = (
    "No se pudo verificar el estado de la conexión con Meta. Vuelve a intentarlo en un momento."
)


class ConnectionsState(rx.State):
    """State for the tenant's connected-accounts screen."""

    connections: list[ConnectionVM] = []
    is_loading: bool = False
    load_error: str = ""
    # Errors from an ACTION (connect / disconnect), kept apart from `load_error`:
    # a failed disconnect must not blank the list the operator is looking at.
    action_error: str = ""
    # QUA-91: per-connection, NOT page-wide (unlike `is_loading` above) — multiple
    # cards render at once, and only the ONE "Verificar ahora" actually in flight may
    # show its spinner. Same shape and the same reason `InboxState.toggling_media_ids`
    # is per-row: `.contains(conn.id)` on the frontend, `list[str]` (not `bool`) because
    # more than one card exists on screen simultaneously.
    checking_connection_ids: list[str] = []
    # QUA-123: the result of the OAuth round trip, read from `?connect=` on arrival.
    connect_notice: str = ""
    connect_notice_tone: str = "info"
    # QUA-202: the guided panel for a dead-end result (`link_required` /
    # `page_access_required`). `guidance_code == ""` means "no panel". The raw counts
    # are kept as ints (-1 = not in the URL) only to attach them to a support request.
    guidance_code: str = ""
    guidance_title: str = ""
    guidance_summary: str = ""
    guidance_steps: list[str] = []
    guidance_rerequest: bool = False
    guidance_pages: int = -1
    guidance_linked: int = -1
    # QUA-202: the pre-flight checklist. Which requirement has its steps open, and
    # whether the operator unfolded the whole card on a screen that folds it (one that
    # already has connections — §6.5: configuration folds once configured).
    expanded_requirement: str = ""
    checklist_open: bool = False
    # QUA-202: "Pedir ayuda 1:1" drawer + its form. Nothing here is credential-adjacent:
    # a contact the operator typed and a free-text message.
    support_open: bool = False
    support_email: str = ""
    support_whatsapp: str = ""
    support_message: str = ""
    support_sending: bool = False
    support_error: str = ""
    support_notice: str = ""

    @rx.var
    def has_connections(self) -> bool:
        return len(self.connections) > 0

    @rx.var
    def show_empty_state(self) -> bool:
        # Only after loading finishes, and never on top of an error.
        return not self.is_loading and not self.load_error and len(self.connections) == 0

    @rx.var
    def has_guidance(self) -> bool:
        return self.guidance_code != ""

    @rx.var
    def show_checklist(self) -> bool:
        """The checklist is open for whoever still has to connect (no connections, or a
        failed attempt on screen) and folded to one line for a tenant whose accounts
        already work — unless they unfold it."""
        if self.is_loading or self.load_error:
            return False
        return self.checklist_open or not self.connections or self.guidance_code != ""

    @rx.event
    def read_connect_result(self) -> None:
        """Turn the callback's `?connect=<code>` into a notice above the list — or, for
        the two dead ends, into the guided panel (QUA-202) that replaces the notice.
        Runs on every load, so arriving without the parameter clears stale state."""
        self.apply_connect_result(dict(self.router.url.query_parameters))

    def apply_connect_result(self, params: dict[str, object]) -> None:
        """The part of `read_connect_result` that does not need a live router — split so
        it can be exercised without an `EventContext` (see `test_connections_state.py`)."""
        code = str(params.get("connect", "") or "")
        pages = str(params.get("pages", "") or "")
        linked = str(params.get("linked", "") or "")
        guidance = connect_result_guidance(code, pages, linked)
        self.guidance_code = guidance.code
        self.guidance_title = guidance.title
        self.guidance_summary = guidance.summary
        self.guidance_steps = list(guidance.steps)
        self.guidance_rerequest = guidance.rerequest
        self.guidance_pages = int(pages) if pages.isdigit() and len(pages) <= 4 else -1
        self.guidance_linked = int(linked) if linked.isdigit() and len(linked) <= 4 else -1
        if guidance.code:
            self.connect_notice, self.connect_notice_tone = "", "info"
        else:
            self.connect_notice, self.connect_notice_tone = connect_result_notice(code)
        if code:
            # Arriving back from Meta: whatever a support request said earlier in this
            # session is stale next to a fresh result.
            self.support_notice = ""

    @rx.event
    def toggle_requirement(self, key: str) -> None:
        self.expanded_requirement = "" if self.expanded_requirement == key else key

    @rx.event
    def toggle_checklist(self) -> None:
        self.checklist_open = not self.checklist_open

    @rx.event
    def show_guide_step(self, key: str) -> rx.event.EventSpec:
        """«Ver el paso N» on a card hint (m-24840590): unfold the guide with exactly that
        step open and bring it into view — on a phone the guide is a long scroll away."""
        self.checklist_open = True
        self.expanded_requirement = key
        return rx.scroll_to(GUIDE_ELEMENT_ID)

    @rx.event
    async def open_support(self) -> None:
        """Open the "Pedir ayuda 1:1" drawer with the session's email already in place —
        the operator should only have to press «Enviar»."""
        auth = await self.get_state(AuthState)
        if not self.support_email:
            self.support_email = auth.user_email
        self.support_error = ""
        self.support_notice = ""
        self.support_open = True

    @rx.event
    def set_support_open(self, open: bool) -> None:
        self.support_open = open

    @rx.event
    def set_support_email(self, value: str) -> None:
        self.support_email = value

    @rx.event
    def set_support_whatsapp(self, value: str) -> None:
        self.support_whatsapp = value

    @rx.event
    def set_support_message(self, value: str) -> None:
        self.support_message = value

    @rx.event(background=True)
    async def submit_support(self) -> None:
        """Create the support ticket (QUA-202). The row is saved before the channel is
        told, so the notice is honest about which of the two happened."""
        async with self:
            if self.support_sending:
                return  # a double-click must not file two tickets
            if "@" not in self.support_email:
                self.support_error = _SUPPORT_EMAIL_REQUIRED
                return
            self.support_sending = True
            self.support_error = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            email = self.support_email.strip()
            whatsapp = self.support_whatsapp
            message = self.support_message
            context: dict[str, str | int] = {"screen": "connections"}
            if self.guidance_code:
                context["outcome"] = self.guidance_code
            if self.guidance_pages >= 0:
                context["pages"] = self.guidance_pages
            if self.guidance_linked >= 0:
                context["linked"] = self.guidance_linked

        resolved_tenant = tenant_uuid(session_tenant_id)
        if resolved_tenant is None:
            async with self:
                self.support_sending = False
                self.support_error = _NO_TENANTS
            return

        try:
            ticket = await asyncio.to_thread(
                request_support,
                resolved_tenant,
                contact_email=email,
                contact_whatsapp=whatsapp,
                message=message,
                context=context,
            )
        except InvalidSupportRequest:
            async with self:
                self.support_sending = False
                self.support_error = _SUPPORT_EMAIL_REQUIRED
            return
        except SQLAlchemyError as exc:
            logger.error("support request failed: %s", type(exc).__name__)
            async with self:
                self.support_sending = False
                self.support_error = _SUPPORT_FAILED
            return

        template = _SUPPORT_SENT if ticket.notified else _SUPPORT_SAVED
        async with self:
            self.support_sending = False
            self.support_open = False
            self.support_message = ""
            self.support_notice = template.format(reference=ticket.reference, email=email)

    @rx.event(background=True)
    async def load_connections(self) -> None:
        """Load the authenticated tenant's connections."""
        async with self:
            self.is_loading = True
            self.load_error = ""
            self.connections = []
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        resolved = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if resolved is None:
            async with self:
                self.is_loading = False
                self.load_error = _NO_TENANTS
            return

        try:
            data = await asyncio.to_thread(connections_for, resolved)
        except SQLAlchemyError as exc:
            # Only the exception type is logged: a SQLAlchemy error's text can carry
            # connection details, and nothing credential-adjacent may reach a log.
            logger.error("connections load failed: %s", type(exc).__name__)
            async with self:
                self.is_loading = False
                self.load_error = _LOAD_FAILED
            return

        async with self:
            # Guard against a logout/login that raced this load.
            auth = await self.get_state(AuthState)
            if session_tenant_id == auth.session_tenant_id:
                self.connections = data
                self.is_loading = False

    @rx.event(background=True)
    async def start_connect_flow(self) -> AsyncIterator[rx.event.EventSpec]:
        """Begin the real C-04 OAuth flow and send the browser to Meta.

        The authorization URL is minted here rather than precomputed per row: every
        call registers a one-shot `state` jti in Redis, so it is produced at the moment
        the operator actually clicks. Blocking (Redis + Postgres), hence off-thread.
        """
        async for event in self._launch_connect(rerequest=False):
            yield event

    @rx.event(background=True)
    async def retry_connect(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Volver a conectar» from the guided panel (QUA-202). Same flow as
        `start_connect_flow`; the only difference is `rerequest`, taken from the
        guidance on screen: after `page_access_required` Meta must show the Page picker
        again (`auth_type=rerequest`), after `link_required` a plain retry is right."""
        async with self:
            rerequest = self.guidance_rerequest
        async for event in self._launch_connect(rerequest=rerequest):
            yield event

    @rx.event(background=True)
    async def reconnect_for_permissions(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Volver a conectar» from a card hint (m-24840590): the account is missing a
        permission, so Meta must ask again for what was left unticked
        (`auth_type=rerequest`) — a plain retry would silently skip it."""
        async for event in self._launch_connect(rerequest=True):
            yield event

    async def _launch_connect(self, *, rerequest: bool) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            self.action_error = ""
            self.connect_notice = ""
            self.support_notice = ""

        resolved_tenant = tenant_uuid(session_tenant_id)
        if resolved_tenant is None:
            async with self:
                self.action_error = _NO_TENANTS
            return

        try:
            authorization_url = await asyncio.to_thread(
                begin_connect, resolved_tenant, rerequest=rerequest
            )
        except NoActingUser:
            async with self:
                self.action_error = _NO_ACTING_USER
            return
        except (RedisError, SQLAlchemyError) as exc:
            # Infrastructure, not the operator's fault. Only the exception TYPE is
            # logged: a Redis/SQLAlchemy error's text can carry connection details.
            logger.error("start_connect failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _CONNECT_FAILED
            return

        yield rx.redirect(authorization_url)

    @rx.event(background=True)
    async def disconnect_connection(self, connection_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """Disconnect a connection, then reload so the UI shows the reconciled state.

        `changed is False` (already revoked) is a successful no-op, not an error — a
        double-click must not break the screen. `ConnectionNotFound` is reported as
        not-found and NEVER as success: it is indistinguishable from "belongs to
        another tenant", so claiming a revoke succeeded would confirm the existence of
        a row the operator has no right to know about.

        `InvalidTransition` / `ValueError` are deliberately NOT caught — they mean the
        FSM and the stored status disagree, which is a bug to surface, not a message to
        show.
        """
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        resolved_tenant = tenant_uuid(session_tenant_id)
        if resolved_tenant is None:
            return
        try:
            resolved_connection = UUID(connection_id)
        except ValueError:
            return  # the id arrived over the wire; refuse junk rather than query with it

        try:
            await asyncio.to_thread(disconnect, resolved_tenant, resolved_connection)
        except ConnectionNotFound:
            async with self:
                self.action_error = _NOT_FOUND
            # Still reload: the list on screen is stale by definition if this fired.
            yield ConnectionsState.load_connections
            return
        except SQLAlchemyError as exc:
            logger.error("disconnect failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _DISCONNECT_FAILED
            return

        async with self:
            self.action_error = ""
        yield ConnectionsState.load_connections

    @rx.event(background=True)
    async def check_health_now(self, connection_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """ "Verificar ahora" (QUA-91): one on-demand `/debug_token` call, then reload so
        the list reflects whatever it found — a fresh `data_access_expires_at`, or a
        `degraded` status if Meta reported the token invalid.

        This is the ONLY trigger for a real health-check in this codebase — there is no
        timer, no auto-check on page load, nothing else that calls `check_health`. See
        `token_health.py`'s module docstring for why.

        `checking_connection_ids` drives the button's own `loading=` (spinner + disabled,
        `connections_page.py::verify_now_button`) and doubles as the double-click guard —
        membership is checked and appended in the SAME `async with self` block below, so
        a second click that arrives before the first `async with` releases sees itself
        already present and returns immediately. Removed on every exit path BEFORE any
        `yield`, never after — same convention `action_error` already follows in this
        method, so the spinner never lingers past its own reload.
        """
        async with self:
            if connection_id in self.checking_connection_ids:
                return  # THIS card already has a check in flight; ignore a double-click
            self.checking_connection_ids.append(connection_id)
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            self.action_error = ""

        resolved_tenant = tenant_uuid(session_tenant_id)
        if resolved_tenant is None:
            async with self:
                self.checking_connection_ids.remove(connection_id)
            return
        try:
            resolved_connection = UUID(connection_id)
        except ValueError:
            async with self:
                self.checking_connection_ids.remove(connection_id)
            return  # the id arrived over the wire; refuse junk rather than query with it

        try:
            await asyncio.to_thread(check_health, resolved_tenant, resolved_connection)
        except (CredentialNotFound, TokenHealthError, httpx.HTTPError, SQLAlchemyError) as exc:
            # Infra/lookup failures, not a verdict about the token — same posture
            # `start_connect_flow` already has for its own infra exceptions. Only the
            # exception TYPE is logged; a Meta error body can echo request parameters.
            logger.error("check_health_now failed: %s", type(exc).__name__)
            async with self:
                self.checking_connection_ids.remove(connection_id)
                self.action_error = _HEALTH_CHECK_FAILED
            return

        async with self:
            self.checking_connection_ids.remove(connection_id)
            self.action_error = ""
        yield ConnectionsState.load_connections
