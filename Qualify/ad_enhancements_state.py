"""Brand-scoped persisted permissions, with optimistic locking and late-response guards."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.tenancy.acting import acting_login

from .ad_enhancements_provider import load_policy, save_policy
from .ad_enhancements_vm import (
    FEATURES,
    READ_FAILED,
    SAVE_FAILED,
    SESSION_REQUIRED,
    BrandEnhancementsVM,
    all_off,
    permission_summary,
)
from .auth_state import AuthState
from .creative_state import CreativeState
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .promotion_state import PromotionState


def apply_policy_to_current_draft(
    promotion: PromotionState, context: tuple[str, str, str, str], policy: BrandEnhancementsVM
) -> bool:
    """A local saved preference invalidates only this session's same-brand draft consent."""
    if promotion._loaded_context != context[:3] or promotion.selected_source.brand_id != context[3]:
        return False
    promotion._invalidate_enhancements()
    promotion.sources = [
        replace(row, enhancements=policy) if row.brand_id == context[3] else row
        for row in promotion.sources
    ]
    promotion.form = replace(promotion.form, enhancements=policy)
    promotion._invalidate_review()
    promotion.enhancements_notice = (
        "Los permisos de la marca cambiaron. Revisa el resumen y prepara otra vista previa."
    )
    return True


class AdEnhancementsState(rx.State):
    editing: bool = False
    loading: bool = False
    saving: bool = False
    policy: BrandEnhancementsVM = BrandEnhancementsVM()
    values: dict[str, bool] = all_off()
    error: str = ""
    notice: str = ""
    _context: tuple[str, str, str, str] = ("", "", "", "")
    _operation: str = ""

    async def _session(self) -> tuple[str, str, str, str]:
        auth = await self.get_state(AuthState)
        creative = await self.get_state(CreativeState)
        return (
            auth.session_tenant_id,
            auth._auth_user_id,
            auth._session_user_id,
            creative._brand_id,
        )

    async def _invalidate_prepared(
        self, context: tuple[str, str, str, str], policy: BrandEnhancementsVM
    ) -> None:
        from .promotion_state import PromotionState

        promotion = await self.get_state(PromotionState)
        apply_policy_to_current_draft(promotion, context, policy)

    @rx.var(cache=False)
    async def in_current_brand(self) -> bool:
        return self._context == await self._session()

    @rx.var
    def dirty(self) -> bool:
        return self.policy.loaded and self.values != self.policy.values

    @rx.var
    def summary(self) -> str:
        return permission_summary(self.policy)

    def _clear(self) -> None:
        self.policy = BrandEnhancementsVM()
        self.values = all_off()
        self.error = self.notice = ""
        self.loading = self.saving = False
        self.editing = False
        self._operation = str(uuid4())

    @rx.event(background=True)
    async def open(self) -> None:
        async with self:
            if self.saving:
                return
            self._clear()
            self._context = context = await self._session()
            self.editing = True
            if not all(tenant_uuid(value) for value in context):
                self.error = SESSION_REQUIRED
                return
            self.loading = True
            operation = self._operation
        try:
            with acting_login(UUID(context[1])):
                policy = await asyncio.to_thread(load_policy, UUID(context[0]), UUID(context[3]))
        except Exception as exc:
            logger.warning("advertisement permissions read failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = READ_FAILED
                    self.loading = False
            return
        async with self:
            if context == await self._session() and operation == self._operation:
                self.policy = policy
                self.values = dict(policy.values)
                self.loading = False

    @rx.event
    def change(self, name: str, value: bool) -> None:
        if self.loading or self.saving or not self.editing or not self.policy.loaded:
            return
        if name not in FEATURES or type(value) is not bool:
            return
        self.values = {**self.values, name: value}
        self.notice = ""

    @rx.event
    def cancel(self) -> None:
        if self.saving:
            return
        self._operation = str(uuid4())
        self.values = dict(self.policy.values)
        self.editing = self.loading = False
        self.error = self.notice = ""

    @rx.event(background=True)
    async def save(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context or not all(tenant_uuid(value) for value in context):
                self._clear()
                self._context = context
                self.editing = True
                self.error = SESSION_REQUIRED
                return
            if self.loading or self.saving or not self.editing or not self.dirty:
                return
            values, version = dict(self.values), self.policy.version
            self.saving = True
            self.error = self.notice = ""
            self._operation = operation = str(uuid4())
        try:
            with acting_login(UUID(context[1])):
                policy = await asyncio.to_thread(
                    save_policy, UUID(context[0]), UUID(context[3]), values, version
                )
        except Exception as exc:
            logger.warning("advertisement permissions save failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = SAVE_FAILED
                    self.policy = BrandEnhancementsVM()
                    self.saving = False
            return
        async with self:
            if context == await self._session() and operation == self._operation:
                self.policy = policy
                self.values = dict(policy.values)
                self.saving = False
                await self._invalidate_prepared(context, policy)
                self.notice = "Permisos guardados para las promociones nuevas de esta marca."
