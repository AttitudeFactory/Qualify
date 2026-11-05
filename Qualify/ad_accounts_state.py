"""Per-connection advertising-account actions; all service work runs off the event loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import reflex as rx
from qualify_api.auth import NotAMember
from qualify_api.connections.ad_accounts import AdAccountUnavailable
from qualify_api.tenancy.acting import acting_login
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from .ad_accounts_provider import (
    ad_accounts_for,
    begin_ads_connect,
    choose_account,
    choose_brand,
    refresh_accounts,
    with_ad_accounts,
)
from .ad_accounts_vm import BRAND_FAILED, CONNECT_FAILED, NO_SESSION, REFRESH_FAILED, SELECT_FAILED
from .ad_health_provider import refresh_health
from .ad_health_vm import HEALTH_REFRESH_FAILED
from .auth_state import AuthState
from .connections_provider import connections_for
from .connections_state import ConnectionsState
from .oauth_binding_js import bound_redirect
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)


class AdAccountsState(rx.State):
    busy_ids: list[str] = []
    errors: dict[str, str] = {}
    notices: dict[str, str] = {}
    working: dict[str, str] = {}

    @rx.event(background=True)
    async def refresh(self, connection_id: str) -> None:
        await self._change(connection_id, account_id="")

    @rx.event(background=True)
    async def choose(self, connection_id: str, account_id: str) -> None:
        await self._change(connection_id, account_id=account_id)

    @rx.event(background=True)
    async def assign_brand(self, connection_id: str, brand_id: str) -> None:
        await self._change(connection_id, account_id="", brand_id=brand_id)

    @rx.event(background=True)
    async def refresh_health(self, connection_id: str, account_id: str) -> None:
        """Only a server-projected local account on this card can be refreshed."""
        async with self:
            if connection_id in self.busy_ids:
                return
            auth = await self.get_state(AuthState)
            context = (auth.session_tenant_id, auth._auth_user_id)
            connections = await self.get_state(ConnectionsState)
            card = next((row for row in connections.connections if row.id == connection_id), None)
            account = (
                next((row for row in card.ad_accounts.accounts if row.id == account_id), None)
                if card is not None
                else None
            )
            if account is None:
                return
            self.busy_ids.append(connection_id)
            self.errors[connection_id] = ""
            self.notices[connection_id] = ""
            self.working[connection_id] = "Comprobando el estado de la cuenta con Meta…"
            zone = account.timezone
        try:
            tenant_id = tenant_uuid(context[0])
            if tenant_id is None or not context[1]:
                raise AdAccountUnavailable(NO_SESSION)
            with acting_login(UUID(context[1])):
                health = await asyncio.to_thread(refresh_health, tenant_id, UUID(account_id), zone)
                panel = await asyncio.to_thread(
                    ad_accounts_for, tenant_id, UUID(connection_id), False
                )
        except Exception as exc:
            logger.warning("advertising account health failed: %s", type(exc).__name__)
            async with self:
                auth = await self.get_state(AuthState)
                if context == (auth.session_tenant_id, auth._auth_user_id):
                    self.errors[connection_id] = (
                        str(exc)
                        if isinstance(exc, AdAccountUnavailable | NotAMember)
                        else HEALTH_REFRESH_FAILED
                    )
        else:
            async with self:
                auth = await self.get_state(AuthState)
                if context == (auth.session_tenant_id, auth._auth_user_id):
                    connections = await self.get_state(ConnectionsState)
                    connections.connections = [
                        with_ad_accounts(row, panel) if row.id == connection_id else row
                        for row in connections.connections
                    ]
                    if health.refresh_failed:
                        self.errors[connection_id] = HEALTH_REFRESH_FAILED
                    else:
                        self.notices[connection_id] = "Estado de la cuenta actualizado."
        finally:
            async with self:
                auth = await self.get_state(AuthState)
                if context == (auth.session_tenant_id, auth._auth_user_id):
                    if connection_id in self.busy_ids:
                        self.busy_ids.remove(connection_id)
                    self.working[connection_id] = ""

    async def _change(self, connection_id: str, *, account_id: str, brand_id: str = "") -> None:
        async with self:
            if connection_id in self.busy_ids:
                return
            self.busy_ids.append(connection_id)
            self.errors[connection_id] = ""
            self.notices[connection_id] = ""
            self.working[connection_id] = (
                "Guardando tu elección…" if account_id or brand_id else "Comprobando tus cuentas…"
            )
            auth = await self.get_state(AuthState)
            session_tenant = auth.session_tenant_id
            session_login = auth._auth_user_id
        failed = BRAND_FAILED if brand_id else SELECT_FAILED if account_id else REFRESH_FAILED
        updated_connections = None
        try:
            tenant_id = tenant_uuid(session_tenant)
            if tenant_id is None or not session_login:
                raise AdAccountUnavailable(NO_SESSION)
            connection_uuid = UUID(connection_id)
            with acting_login(UUID(session_login)):
                if brand_id:
                    await asyncio.to_thread(
                        choose_brand, tenant_id, connection_uuid, UUID(brand_id)
                    )
                    updated_connections = await asyncio.to_thread(connections_for, tenant_id)
                elif account_id:
                    await asyncio.to_thread(
                        choose_account, tenant_id, connection_uuid, UUID(account_id)
                    )
                    # A brand may have another Instagram connection. Re-read all cards so
                    # the previously selected account never remains shown as selected there.
                    updated_connections = await asyncio.to_thread(connections_for, tenant_id)
                else:
                    await asyncio.to_thread(refresh_accounts, tenant_id, connection_uuid)
                if not brand_id and not account_id:
                    panel = await asyncio.to_thread(ad_accounts_for, tenant_id, connection_uuid)
        except (
            AdAccountUnavailable,
            NotAMember,
            SQLAlchemyError,
            httpx.HTTPError,
            ValueError,
        ) as exc:
            logger.warning("advertising account action failed: %s", type(exc).__name__)
            async with self:
                auth = await self.get_state(AuthState)
                if session_tenant == auth.session_tenant_id and session_login == auth._auth_user_id:
                    self.errors[connection_id] = (
                        str(exc) if isinstance(exc, AdAccountUnavailable | NotAMember) else failed
                    )
        else:
            async with self:
                auth = await self.get_state(AuthState)
                if session_tenant == auth.session_tenant_id and session_login == auth._auth_user_id:
                    connections = await self.get_state(ConnectionsState)
                    connections.connections = (
                        updated_connections
                        if updated_connections is not None
                        else [
                            with_ad_accounts(row, panel) if row.id == connection_id else row
                            for row in connections.connections
                        ]
                    )
                    self.notices[connection_id] = (
                        "Marca elegida. Ahora puedes conectar el acceso para anuncios."
                        if brand_id
                        else "Cuenta elegida para este negocio."
                        if account_id
                        else "Cuentas actualizadas."
                    )
        finally:
            async with self:
                auth = await self.get_state(AuthState)
                if session_tenant == auth.session_tenant_id and session_login == auth._auth_user_id:
                    if connection_id in self.busy_ids:
                        self.busy_ids.remove(connection_id)
                    self.working[connection_id] = ""

    @rx.event(background=True)
    async def connect(self, connection_id: str) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if connection_id in self.busy_ids:
                return
            self.busy_ids.append(connection_id)
            self.errors[connection_id] = ""
            self.notices[connection_id] = ""
            self.working[connection_id] = "Abriendo la conexión con Facebook…"
            auth = await self.get_state(AuthState)
            session_tenant = auth.session_tenant_id
            session_user = auth._session_user_id
            session_login = auth._auth_user_id
        started = None
        try:
            tenant_id = tenant_uuid(session_tenant)
            if tenant_id is None or not session_user or not session_login:
                raise AdAccountUnavailable(NO_SESSION)
            with acting_login(UUID(session_login)):
                started = await asyncio.to_thread(
                    begin_ads_connect, tenant_id, UUID(connection_id), UUID(session_user)
                )
        except (AdAccountUnavailable, NotAMember, SQLAlchemyError, RedisError, ValueError) as exc:
            logger.warning("advertising consent start failed: %s", type(exc).__name__)
            async with self:
                auth = await self.get_state(AuthState)
                if session_tenant == auth.session_tenant_id and session_login == auth._auth_user_id:
                    self.errors[connection_id] = (
                        str(exc)
                        if isinstance(exc, AdAccountUnavailable | NotAMember)
                        else CONNECT_FAILED
                    )
        finally:
            async with self:
                auth = await self.get_state(AuthState)
                same_session = (
                    session_tenant == auth.session_tenant_id
                    and session_user == auth._session_user_id
                    and session_login == auth._auth_user_id
                )
                if same_session:
                    if connection_id in self.busy_ids:
                        self.busy_ids.remove(connection_id)
                    self.working[connection_id] = ""
        if started is not None and same_session:
            yield bound_redirect(started)
