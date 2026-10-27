"""Shared reconnection events; screens keep their own saved content (m-24854865)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx
from qualify_api.connections import ConnectionNotFound
from qualify_api.connections.state_token import safe_return_path
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .connections_provider import NoActingUser, begin_reconnect, connections_for
from .reconnect_vm import reconnect_notice, reconnect_origin
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)


class ReconnectState(rx.State):
    connection_id: str = ""
    cause: str = ""
    origin: str = ""
    notice: str = ""
    notice_tone: str = "info"
    show_retry: bool = False
    show_help: bool = False
    is_starting: bool = False
    has_target: bool = False

    @rx.event(background=True)
    async def start_reconnect(
        self, connection_id: str, cause: str, origin: str
    ) -> AsyncIterator[rx.event.EventSpec]:
        """Open Facebook directly, with this tenant's account and origin in signed state."""
        try:
            resolved_connection = UUID(connection_id)
        except ValueError:
            return
        safe_origin = safe_return_path(origin)
        if not safe_origin:
            return
        async with self:
            if self.is_starting:
                return
            auth = await self.get_state(AuthState)
            session_tenant = auth.session_tenant_id
            resolved_tenant = tenant_uuid(session_tenant)
            if resolved_tenant is None:
                return
            self.is_starting = True
            self.notice = ""
            self.connection_id, self.cause, self.origin = connection_id, cause, safe_origin
        try:
            url = await asyncio.to_thread(
                begin_reconnect,
                resolved_tenant,
                resolved_connection,
                cause=cause,
                origin=safe_origin,
            )
        except (NoActingUser, ConnectionNotFound, RedisError, SQLAlchemyError) as exc:
            logger.error("reconnect start failed: %s", type(exc).__name__)
            async with self:
                self.is_starting = False
                self.notice = "No pudimos abrir Facebook. Intenta de nuevo o pide ayuda."
                self.notice_tone = "warn"
                self.show_retry = True
                self.show_help = True
            return
        async with self:
            self.is_starting = False
            auth = await self.get_state(AuthState)
            if auth.session_tenant_id != session_tenant:
                return
        yield rx.redirect(url)

    @rx.event(background=True)
    async def read_result(self) -> None:
        """Call on arrival alongside a screen's normal load; never accept a URL username."""
        async with self:
            self.notice = ""
            self.show_retry = False
            self.show_help = False
            self.has_target = False
            params = dict(self.router.url.query_parameters)
            origin = reconnect_origin(self.router.url.path, params)
            auth = await self.get_state(AuthState)
            session_tenant = auth.session_tenant_id
            tenant_id = tenant_uuid(session_tenant)
        raw_connection_id = str(params.get("reconnect", ""))
        try:
            connection_id = UUID(raw_connection_id) if raw_connection_id else None
        except ValueError:
            return
        if tenant_id is None or not origin:
            return
        try:
            accounts = await asyncio.to_thread(connections_for, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("reconnect result load failed: %s", type(exc).__name__)
            return
        candidates = [row for row in accounts if row.platform == "instagram"]
        account = (
            next((row for row in candidates if row.id == str(connection_id)), None)
            if connection_id is not None
            else candidates[0]
            if len(candidates) == 1
            else None
        )
        if account is None:
            return
        code = str(params.get("connect", ""))
        # The query is a presentation hint, never authority to assert a live connection.
        if code == "active" and account.status != "active":
            code = "degraded"
        result = reconnect_notice(code, account.external_username, origin=origin)
        async with self:
            auth = await self.get_state(AuthState)
            if auth.session_tenant_id != session_tenant:
                return
            self.connection_id = account.id
            self.has_target = True
            self.origin = origin
            self.cause = (
                "permission_missing"
                if code == "permission_missing"
                else account.reconnect_reason or "auth_expired"
            )
            self.notice, self.notice_tone = result.message, result.tone
            self.show_retry, self.show_help = result.retry, result.help
