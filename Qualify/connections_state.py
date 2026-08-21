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
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .connections_provider import (
    NoActingUser,
    begin_connect,
    check_health,
    connections_for,
    disconnect,
)
from .connections_vm import ConnectionVM
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

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

    @rx.var
    def has_connections(self) -> bool:
        return len(self.connections) > 0

    @rx.var
    def show_empty_state(self) -> bool:
        # Only after loading finishes, and never on top of an error.
        return not self.is_loading and not self.load_error and len(self.connections) == 0

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
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            self.action_error = ""

        resolved_tenant = tenant_uuid(session_tenant_id)
        if resolved_tenant is None:
            async with self:
                self.action_error = _NO_TENANTS
            return

        try:
            authorization_url = await asyncio.to_thread(begin_connect, resolved_tenant)
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
        """
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            self.action_error = ""

        resolved_tenant = tenant_uuid(session_tenant_id)
        if resolved_tenant is None:
            return
        try:
            resolved_connection = UUID(connection_id)
        except ValueError:
            return  # the id arrived over the wire; refuse junk rather than query with it

        try:
            await asyncio.to_thread(check_health, resolved_tenant, resolved_connection)
        except (CredentialNotFound, TokenHealthError, httpx.HTTPError, SQLAlchemyError) as exc:
            # Infra/lookup failures, not a verdict about the token — same posture
            # `start_connect_flow` already has for its own infra exceptions. Only the
            # exception TYPE is logged; a Meta error body can echo request parameters.
            logger.error("check_health_now failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _HEALTH_CHECK_FAILED
            return

        async with self:
            self.action_error = ""
        yield ConnectionsState.load_connections
