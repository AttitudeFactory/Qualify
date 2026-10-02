"""State for the Canva round trip on the generator's result (/create) and the two pages
Canva sends the user back to (`/canva/callback` after consent, `/canva/return` after
editing).

Everything happens in the SAME browser tab: the login (`AuthState.session_tenant_id`) and
the PKCE verifier live in this session's state, and a new tab would be a new session.
Leaving for canva.com and coming back keeps the session (Reflex's client token lives in
the tab's sessionStorage).

Not exercised against the live Canva API yet (§ request 2026-09-28).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .canva_provider import (
    CanvaNotConfigured,
    CanvaNotConnected,
    NothingToSend,
    UnknownReturn,
    canva_configured,
    canva_connected,
    canva_disconnect,
    canva_finish_connect,
    canva_links,
    canva_pull,
    canva_return,
    canva_send,
    canva_start_connect,
)
from .connections_provider import acting_user_id
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NOT_CONFIGURED = (
    "Canva todavía no está configurado: faltan las credenciales de la integración "
    "(QUALIFY_CANVA_CLIENT_ID / QUALIFY_CANVA_CLIENT_SECRET)."
)
_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NOT_CONNECTED = "Tu conexión con Canva caducó. Conéctala de nuevo."
_CANVA_DOWN = "Canva no respondió. Inténtalo de nuevo en un momento."
_DB_ERROR = "No se pudo leer la base de datos."
#: Where the user lands after connecting or returning from Canva.
_HOME = "/create"


class CanvaState(rx.State):
    configured: bool = False
    connected: bool = False
    busy: bool = False
    error: str = ""
    notice: str = ""
    canva_draft_id: str = ""
    #: The pieces of `canva_draft_id` sent to Canva (`canva_provider.link_item`), newest first.
    links: list[dict[str, str]] = []
    #: The status line of the callback/return pages.
    landing_message: str = ""
    # Backend-only: never sent to the browser.
    _oauth_state: str = ""
    _pkce_verifier: str = ""

    @rx.var
    def has_links(self) -> bool:
        return len(self.links) > 0

    async def _ids(self) -> tuple[UUID, UUID] | None:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            return None
        user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        return (tenant_id, user_id) if user_id is not None else None

    # -- the card on the generator's result ---------------------------------------------

    @rx.event(background=True)
    async def load(self, draft_id: str) -> None:
        async with self:
            self.canva_draft_id = draft_id
            self.error = ""
            self.configured = canva_configured()
            if not self.configured:
                self.links = []
                return
        ids = await self._ids()
        if ids is None:
            async with self:
                self.error = _NO_SESSION
            return
        tenant_id, user_id = ids
        draft = tenant_uuid(draft_id)
        try:
            connected = await asyncio.to_thread(canva_connected, tenant_id, user_id)
            links = await asyncio.to_thread(canva_links, tenant_id, draft) if draft else []
        except SQLAlchemyError as exc:
            logger.error("canva load failed: %s", type(exc).__name__)
            async with self:
                self.error = _DB_ERROR
            return
        async with self:
            if self.canva_draft_id == draft_id:
                self.connected = connected
                self.links = links

    @rx.event
    def connect(self) -> rx.event.EventSpec | None:
        """Leave for Canva's consent page, in this same tab."""
        self.error = ""
        state = secrets.token_urlsafe(24)
        try:
            start = canva_start_connect(state)
        except CanvaNotConfigured:
            self.error = _NOT_CONFIGURED
            return None
        self._oauth_state = start.state
        self._pkce_verifier = start.code_verifier
        return rx.redirect(start.url)

    @rx.event(background=True)
    async def disconnect(self) -> None:
        ids = await self._ids()
        if ids is None:
            return
        await asyncio.to_thread(canva_disconnect, *ids)
        async with self:
            self.connected = False
            self.notice = "Canva desconectado de Qualify."

    @rx.event(background=True)
    async def send(self) -> AsyncIterator[rx.event.EventSpec]:
        """Upload the draft's piece to the user's Canva and open the design there."""
        async with self:
            if self.busy:
                return
            self.busy = True
            self.error = ""
            self.notice = ""
            draft_id = self.canva_draft_id
        ids = await self._ids()
        draft = tenant_uuid(draft_id)
        if ids is None or draft is None:
            async with self:
                self.busy = False
                self.error = _NO_SESSION
            return
        try:
            sent = await asyncio.to_thread(canva_send, *ids, draft)
        except CanvaNotConnected:
            async with self:
                self.busy = False
                self.connected = False
                self.error = _NOT_CONNECTED
            return
        except NothingToSend:
            async with self:
                self.busy = False
                self.error = "Esta pieza todavía no tiene imagen ni video que enviar."
            return
        except Exception as exc:  # Canva's own errors, network
            logger.warning("canva send failed: %s", exc)
            async with self:
                self.busy = False
                self.error = _CANVA_DOWN
            return
        async with self:
            self.busy = False
        yield rx.redirect(sent.open_url)

    @rx.event(background=True)
    async def pull(self, link_id: str) -> None:
        """ "Traer de Canva": export the design again and store it."""
        async with self:
            if self.busy:
                return
            self.busy = True
            self.error = ""
        ids = await self._ids()
        link = tenant_uuid(link_id)
        if ids is None or link is None:
            async with self:
                self.busy = False
                self.error = _NO_SESSION
            return
        try:
            item = await asyncio.to_thread(canva_pull, *ids, link)
        except CanvaNotConnected:
            async with self:
                self.busy = False
                self.connected = False
                self.error = _NOT_CONNECTED
            return
        except Exception as exc:
            logger.warning("canva pull failed: %s", exc)
            async with self:
                self.busy = False
                self.error = _CANVA_DOWN
            return
        async with self:
            self.busy = False
            self.links = [item if old["id"] == item["id"] else old for old in self.links]
            if item["status"] == "exported" and not item["error"]:
                self.notice = "Traída la última versión de Canva."
            else:
                self.error = item["error"] or "No se pudo traer la edición de Canva."

    # -- the pages Canva sends the user back to -----------------------------------------

    @rx.event(background=True)
    async def finish_connect(self) -> AsyncIterator[rx.event.EventSpec]:
        """`/canva/callback`: check `state`, exchange the code, go back to the generator."""
        async with self:
            params = self.router.url.query_parameters
            code = params.get("code", "")
            state = params.get("state", "")
            denied = params.get("error", "")
            expected, verifier = self._oauth_state, self._pkce_verifier
            # single use, whatever happens next
            self._oauth_state = self._pkce_verifier = ""
            self.landing_message = "Conectando tu Canva…"
        if denied:
            async with self:
                self.landing_message = "Cancelaste la conexión con Canva."
            return
        if not code or not expected or not secrets.compare_digest(state, expected):
            async with self:
                self.landing_message = (
                    "Esta conexión con Canva no se inició desde esta pestaña o ya se usó. "
                    "Vuelve al generador y pulsa «Conectar Canva» otra vez."
                )
            return
        ids = await self._ids()
        if ids is None:
            async with self:
                self.landing_message = _NO_SESSION
            return
        try:
            await asyncio.to_thread(canva_finish_connect, *ids, code, verifier)
        except Exception as exc:
            logger.warning("canva connect failed: %s", exc)
            async with self:
                self.landing_message = "Canva no aceptó la conexión. Inténtalo de nuevo."
            return
        async with self:
            self.connected = True
            self.notice = "Canva conectado. Ya puedes editar tus piezas allí."
        yield rx.redirect(_HOME)

    @rx.event(background=True)
    async def finish_return(self) -> AsyncIterator[rx.event.EventSpec]:
        """`/canva/return`: Canva's "Return" button — bring the edit back."""
        async with self:
            token = self.router.url.query_parameters.get("correlation_jwt", "")
            self.landing_message = "Trayendo tu edición de Canva…"
        ids = await self._ids()
        if ids is None:
            async with self:
                self.landing_message = _NO_SESSION
            return
        if not token:
            async with self:
                self.landing_message = "Canva no nos dijo qué diseño editaste."
            return
        try:
            item = await asyncio.to_thread(canva_return, *ids, token)
        except UnknownReturn:
            async with self:
                self.landing_message = (
                    "Este diseño no corresponde a ninguna pieza que hayas enviado a Canva."
                )
            return
        except CanvaNotConnected:
            async with self:
                self.landing_message = _NOT_CONNECTED
            return
        except Exception as exc:
            logger.warning("canva return failed: %s", exc)
            async with self:
                self.landing_message = _CANVA_DOWN
            return
        async with self:
            self.canva_draft_id = item["draft_id"]
            self.links = [item, *[old for old in self.links if old["id"] != item["id"]]]
            if item["status"] == "exported" and not item["error"]:
                self.notice = "Tu edición de Canva ya está en Qualify."
            else:
                self.error = item["error"] or "No se pudo traer la edición de Canva."
        yield rx.redirect(_HOME)
