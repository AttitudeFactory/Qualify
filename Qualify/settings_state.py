"""Configuración › «País y moneda» (m-24842967, MARCA-3): the business's country — its
timezone follows — and the currency prices are shown in. The signup only asks for the
country; this is where the owner changes either one afterwards.

Configuración › «Tu plan» (m-24852145): the plan's name and what it brings a month.
Read-only: the owner never changes a plan, never sees a price. «Pedir más a Qualify»
next to it is `AskMoreState` (m-24852129), shared with Crear.

Tenant data, so `AuthState.logout` resets this state with the others."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .settings_provider import LocaleInvalid, read_locale, read_plan, save_locale
from .settings_vm import (
    PLAN_FAILED,
    currency_after_country_change,
    currency_options,
    plan_label,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_LOAD_FAILED = "No pudimos leer el país y la moneda de tu negocio. Recarga la página."
_SAVE_FAILED = "No pudimos guardar el cambio. Revisa tu conexión y vuelve a intentarlo."
_NO_SESSION = "Tu sesión terminó. Vuelve a entrar para cambiar el país o la moneda."


class SettingsState(rx.State):
    country: str = ""
    currency: str = ""
    locale_loading: bool = False
    locale_saving: bool = False
    locale_saved: bool = False
    locale_error: str = ""
    # «Tu plan» (m-24852145)
    plan_text: str = ""
    plan_code: str = ""
    plan_error: str = ""

    @rx.var
    def currency_choices(self) -> list[dict[str, str]]:
        return currency_options(self.country)

    @rx.event
    def set_country(self, value: str) -> None:
        self.country = value
        self.currency = currency_after_country_change(value, self.currency)
        self.locale_saved = False
        self.locale_error = ""

    @rx.event
    def set_currency(self, value: str) -> None:
        self.currency = value
        self.locale_saved = False
        self.locale_error = ""

    async def _tenant(self) -> UUID | None:
        async with self:
            auth = await self.get_state(AuthState)
            return tenant_uuid(auth.session_tenant_id)

    @rx.event(background=True)
    async def load_locale(self):
        async with self:
            self.locale_loading = True
            self.locale_saved = False
            self.locale_error = ""
        tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.locale_loading = False
                self.locale_error = _NO_SESSION
            return
        try:
            locale = await asyncio.to_thread(read_locale, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("business locale unreadable: %s", type(exc).__name__)
            locale = None
        async with self:
            self.locale_loading = False
            if locale is None:
                self.locale_error = _LOAD_FAILED
                return
            self.country = locale.country
            self.currency = locale.currency

    @rx.event(background=True)
    async def save_locale(self):
        async with self:
            country, currency = self.country, self.currency
            self.locale_saving = True
            self.locale_saved = False
            self.locale_error = ""
        tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.locale_saving = False
                self.locale_error = _NO_SESSION
            return
        try:
            locale = await asyncio.to_thread(
                save_locale, tenant_id, country=country, currency=currency
            )
        except LocaleInvalid as exc:
            async with self:
                self.locale_saving = False
                self.locale_error = exc.message
            return
        except (SQLAlchemyError, LookupError) as exc:
            logger.error("business locale not saved: %s", type(exc).__name__)
            async with self:
                self.locale_saving = False
                self.locale_error = _SAVE_FAILED
            return
        async with self:
            self.locale_saving = False
            self.country = locale.country
            self.currency = locale.currency
            self.locale_saved = True

    @rx.event(background=True)
    async def load_plan(self):
        async with self:
            self.plan_error = ""
        tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.plan_error = _NO_SESSION
            return
        try:
            plan = await asyncio.to_thread(read_plan, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("business plan unreadable: %s", type(exc).__name__)
            async with self:
                self.plan_error = PLAN_FAILED
            return
        async with self:
            self.plan_text = plan_label(plan)
            self.plan_code = plan.code
