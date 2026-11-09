"""Tenant-scoped cached results and explicit pause confirmation; no automatic spending."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.ads.results import ResultsUnavailable
from qualify_api.tenancy.acting import acting_login

from .ad_results_provider import confirm_edit, load_ad, load_ads, pause_ad, prepare_edit, refresh_ad
from .ad_results_vm import (
    EDIT_ACTION_LABELS,
    EDIT_EXPIRED,
    EDIT_PREPARE_FAILED,
    EDIT_UNKNOWN,
    LOAD_FAILED,
    NO_SESSION,
    PAUSE_FAILED,
    REFRESH_FAILED,
    AdDetailVM,
    AdEditReviewVM,
    AdResultVM,
    EditInputError,
    edit_budget,
    edit_end,
)
from .auth_state import AuthState
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)


class AdResultsState(rx.State):
    ads: list[AdResultVM] = []
    detail: AdDetailVM = AdDetailVM()
    loading: bool = True
    busy: bool = False
    error: str = ""
    notice: str = ""
    pause_open: bool = False
    edit_open: bool = False
    edit_action: str = ""
    edit_budget_total: str = ""
    edit_end_local: str = ""
    edit_review: AdEditReviewVM = AdEditReviewVM()
    edit_consent: bool = False
    edit_warning: str = ""
    change_pending: bool = False
    _context: tuple[str, str, str] = ("", "", "")
    _selected_id: str = ""
    _operation: str = ""
    _pause_request: str = ""
    _edit_request: str = ""
    _edit_token: str = ""
    _edit_expires: str = ""

    @rx.var
    def can_confirm_edit(self) -> bool:
        return (
            self.edit_review.ready
            and self.edit_consent
            and self.edit_review.action == self.edit_action
            and not self.busy
            and not self.change_pending
        )

    def _clear_edit_review(self) -> None:
        self.edit_review = AdEditReviewVM()
        self.edit_consent = False
        self._edit_token = ""
        self._edit_expires = ""

    def _mark_uncertain(self) -> None:
        self.change_pending = True
        old = self.detail.promotion
        self.detail = replace(
            self.detail,
            promotion=replace(
                old,
                can_pause=False,
                can_manage=False,
                can_resume=False,
                operation_pending=True,
                stale=True,
                tone="warn",
            ),
        )

    def _edit_snapshot(self) -> tuple[str, ...]:
        row = self.detail.promotion
        return (
            self._selected_id,
            self.edit_action,
            self.edit_budget_total,
            self.edit_end_local,
            row.currency,
            row.timezone_name,
            row.current_budget_input,
            row.current_end_input,
        )

    def _edit_allowed(self, action: str) -> bool:
        row = self.detail.promotion
        return (
            action in EDIT_ACTION_LABELS
            and not self.busy
            and not self.loading
            and not self.change_pending
            and not row.operation_pending
            and not row.stale
            and not row.refresh_failed
            and row.id == self._selected_id
            and row.currency == "COP"
            and (row.can_resume if action == "resume" else row.can_manage)
        )

    async def _session(self) -> tuple[str, str, str]:
        auth = await self.get_state(AuthState)
        return auth.session_tenant_id, auth._auth_user_id, auth._session_user_id

    def _clear(self) -> None:
        self.ads = []
        self.detail = AdDetailVM()
        self.pause_open = False
        self._pause_request = ""
        self._selected_id = ""
        self._operation = str(uuid4())
        self.error = ""
        self.notice = ""
        self.busy = False
        self.edit_open = False
        self.edit_action = ""
        self.edit_budget_total = ""
        self.edit_end_local = ""
        self._clear_edit_review()
        self._edit_request = ""
        self.edit_warning = ""
        self.change_pending = False

    @rx.event(background=True)
    async def load_list(self) -> None:
        async with self:
            self._clear()
            context = await self._session()
            self._context = context
            self.loading = True
            operation = self._operation
            if not all(tenant_uuid(value) for value in context):
                self.loading = False
                self.error = NO_SESSION
                return
        try:
            with acting_login(UUID(context[1])):
                rows = await asyncio.to_thread(load_ads, UUID(context[0]))
        except Exception as exc:
            logger.warning("ad results list failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = str(exc) if isinstance(exc, ResultsUnavailable) else LOAD_FAILED
                    self.loading = False
            return
        async with self:
            if context == await self._session() and operation == self._operation:
                self.ads = rows
                self.loading = False

    @rx.event(background=True)
    async def load_detail(self) -> None:
        async with self:
            self._clear()
            context = await self._session()
            self._context = context
            promotion = tenant_uuid(str(getattr(self, "promotion_id", "")))
            self.loading = True
            if not all(tenant_uuid(value) for value in context) or promotion is None:
                self.loading = False
                self.error = NO_SESSION if promotion else LOAD_FAILED
                return
            self._selected_id = str(promotion)
            operation = self._operation
        try:
            with acting_login(UUID(context[1])):
                result = await asyncio.to_thread(load_ad, UUID(context[0]), promotion)
        except Exception as exc:
            logger.warning("ad results detail failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = str(exc) if isinstance(exc, ResultsUnavailable) else LOAD_FAILED
                    self.loading = False
            return
        async with self:
            if context == await self._session() and operation == self._operation:
                self.detail = result
                self.change_pending = result.promotion.operation_pending
                self.loading = False

    @rx.event(background=True)
    async def refresh(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context or not all(tenant_uuid(value) for value in context):
                self._clear()
                self.loading = False
                self.error = NO_SESSION
                return
            if self.busy or self.loading or not self._selected_id:
                return
            promotion = UUID(self._selected_id)
            self.busy = True
            self.error = ""
            self.notice = ""
            self.pause_open = False
            self._pause_request = ""
            self.edit_open = False
            self._clear_edit_review()
            self._operation = operation = str(uuid4())
        try:
            with acting_login(UUID(context[1])):
                result = await asyncio.to_thread(refresh_ad, UUID(context[0]), promotion)
        except Exception as exc:
            logger.warning("ad results refresh failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = str(exc) if isinstance(exc, ResultsUnavailable) else REFRESH_FAILED
                    old = self.detail.promotion
                    self.detail = replace(
                        self.detail,
                        promotion=replace(
                            old,
                            can_pause=False,
                            can_manage=False,
                            can_resume=False,
                            stale=True,
                            refresh_failed=True,
                            tone="warn",
                            status_label=(
                                old.status_label
                                if old.status_label.startswith("Último estado:")
                                else "Último estado: " + old.status_label
                            ),
                        ),
                        insights_refresh_failed=True,
                    )
                    self.busy = False
            return
        async with self:
            if context == await self._session() and operation == self._operation:
                self.detail = result
                self.busy = False
                self.change_pending = result.promotion.operation_pending
                if not self.change_pending and not result.promotion.stale:
                    self.edit_warning = ""
                    self._edit_request = ""
                if self.change_pending:
                    self.edit_warning = EDIT_UNKNOWN
                    self.notice = ""
                else:
                    self.notice = "Consulta actualizada con Meta."

    @rx.event
    def ask_pause(self) -> None:
        if self.busy or self.loading or self.change_pending or not self.detail.promotion.can_pause:
            return
        self.pause_open = True
        self._pause_request = str(uuid4())

    @rx.event
    def dismiss_pause(self, opened: bool = False) -> None:
        if not opened:
            self.pause_open = False
            self._pause_request = ""

    @rx.event(background=True)
    async def confirm_pause(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context or not all(tenant_uuid(value) for value in context):
                self._clear()
                self.loading = False
                self.error = NO_SESSION
                return
            if (
                self.busy
                or self.loading
                or not self.pause_open
                or not self._pause_request
                or not self.detail.promotion.can_pause
                or self.change_pending
                or self.detail.promotion.id != self._selected_id
            ):
                return
            promotion = UUID(self._selected_id)
            request_key = self._pause_request
            self.busy = True
            self.pause_open = False
            self.error = ""
            self.notice = ""
            self._operation = operation = str(uuid4())
        try:
            with acting_login(UUID(context[1])):
                result = await asyncio.to_thread(pause_ad, UUID(context[0]), promotion, request_key)
        except Exception as exc:
            logger.warning("ad pause result unavailable: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = str(exc) if isinstance(exc, ResultsUnavailable) else PAUSE_FAILED
                    old = self.detail.promotion
                    self.detail = replace(
                        self.detail,
                        promotion=replace(
                            old,
                            can_pause=False,
                            stale=True,
                            refresh_failed=True,
                            tone="warn",
                            status_label=(
                                old.status_label
                                if old.status_label.startswith("Último estado:")
                                else "Último estado: " + old.status_label
                            ),
                        ),
                    )
                    self._pause_request = ""
                    self.busy = False
                    self._mark_uncertain()
            return
        async with self:
            if context == await self._session() and operation == self._operation:
                self.detail = result
                self.busy = False
                self._pause_request = ""
                self.change_pending = result.promotion.operation_pending
                if self.change_pending:
                    self.edit_warning = EDIT_UNKNOWN
                    self.notice = ""
                else:
                    self.notice = (
                        "La solicitud de pausa quedó registrada. Revisa el estado informado."
                    )

    @rx.event
    def open_edit(self, action: str) -> None:
        if not self._edit_allowed(action):
            return
        self.pause_open = False
        self._pause_request = ""
        self.edit_action = action
        self.edit_budget_total = self.detail.promotion.current_budget_input
        self.edit_end_local = self.detail.promotion.current_end_input
        self._clear_edit_review()
        self._edit_request = str(uuid4())
        self.edit_open = True
        self.error = ""
        self.notice = ""
        self.edit_warning = ""

    @rx.event
    def dismiss_edit(self, opened: bool = False) -> None:
        if not opened and not self.busy:
            self.edit_open = False
            self._clear_edit_review()
            if not self.change_pending:
                self._edit_request = ""

    @rx.event
    def set_edit_budget_total(self, value: str) -> None:
        if self.change_pending:
            return
        self.edit_budget_total = value
        self._clear_edit_review()
        self._operation = str(uuid4())
        self.busy = False

    @rx.event
    def set_edit_end_local(self, value: str) -> None:
        if self.change_pending:
            return
        self.edit_end_local = value
        self._clear_edit_review()
        self._operation = str(uuid4())
        self.busy = False

    @rx.event
    def set_edit_consent(self, checked: bool) -> None:
        self.edit_consent = checked is True and self.edit_review.ready and not self.change_pending

    @rx.event(background=True)
    async def prepare_change(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context or not all(tenant_uuid(value) for value in context):
                self._clear()
                self.loading = False
                self.error = NO_SESSION
                return
            if (
                not self.edit_open
                or not self._edit_request
                or not self._edit_allowed(self.edit_action)
            ):
                return
            row = self.detail.promotion
            try:
                budget = (
                    edit_budget(self.edit_budget_total, row.current_budget_input)
                    if self.edit_action == "budget"
                    else None
                )
                end = (
                    edit_end(self.edit_end_local, row.timezone_name)
                    if self.edit_action == "end_time"
                    else None
                )
            except EditInputError as exc:
                self.error = str(exc)
                return
            self._clear_edit_review()
            snapshot = self._edit_snapshot()
            self._operation = operation = str(uuid4())
            self.busy = True
            self.error = ""
            self.notice = ""
            promotion = UUID(self._selected_id)
            request, action = self._edit_request, self.edit_action
        try:
            with acting_login(UUID(context[1])):
                prepared = await asyncio.to_thread(
                    prepare_edit,
                    UUID(context[0]),
                    promotion,
                    request,
                    action,
                    row.timezone_name,
                    budget_minor=budget,
                    end_time=end,
                )
        except Exception as exc:
            logger.warning("ad edit preparation failed: %s", type(exc).__name__)
            async with self:
                if (
                    context == await self._session()
                    and operation == self._operation
                    and snapshot == self._edit_snapshot()
                ):
                    self.error = (
                        str(exc) if isinstance(exc, ResultsUnavailable) else EDIT_PREPARE_FAILED
                    )
                    self.busy = False
            return
        async with self:
            if (
                context == await self._session()
                and operation == self._operation
                and snapshot == self._edit_snapshot()
            ):
                self.edit_review = prepared.review
                self._edit_token = prepared.approval_token
                self._edit_expires = prepared.expires_at.isoformat()
                self.busy = False

    @rx.event(background=True)
    async def confirm_change(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context or not all(tenant_uuid(value) for value in context):
                self._clear()
                self.loading = False
                self.error = NO_SESSION
                return
            if (
                not self.edit_open
                or not self._edit_allowed(self.edit_action)
                or not self.edit_review.ready
                or not self.edit_consent
                or not self._edit_token
                or not self._edit_request
                or self.edit_review.action != self.edit_action
            ):
                return
            try:
                expiry = datetime.fromisoformat(self._edit_expires)
                fresh = expiry.utcoffset() is not None and datetime.now(UTC) < expiry
            except ValueError:
                fresh = False
            if not fresh:
                self._clear_edit_review()
                self.error = EDIT_EXPIRED
                return
            promotion = UUID(self._selected_id)
            request, action, token = self._edit_request, self.edit_action, self._edit_token
            self._operation = operation = str(uuid4())
            self.busy = True
            self.change_pending = True
            self.edit_consent = False
            self.error = ""
            self.notice = ""
        try:
            with acting_login(UUID(context[1])):
                outcome = await asyncio.to_thread(
                    confirm_edit, UUID(context[0]), promotion, request, action, token
                )
        except Exception as exc:
            logger.warning("ad edit confirmation uncertain: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = EDIT_UNKNOWN
                    self.edit_warning = EDIT_UNKNOWN
                    self._clear_edit_review()
                    self._mark_uncertain()
                    self.busy = False
            return
        async with self:
            if context != await self._session() or operation != self._operation:
                return
            self._clear_edit_review()
            self.busy = False
            if outcome.detail is not None:
                self.detail = outcome.detail
            if (
                outcome.status == "completed"
                and outcome.promotion_id == self._selected_id
                and outcome.action == action
            ):
                self.notice = outcome.message
                self.edit_warning = ""
                self.edit_open = False
                self.change_pending = self.detail.promotion.operation_pending
                if outcome.detail is None:
                    self.detail = replace(
                        self.detail,
                        promotion=replace(
                            self.detail.promotion,
                            can_manage=False,
                            can_pause=False,
                            can_resume=False,
                            stale=True,
                            current_budget="Presupuesto actual por comprobar",
                            current_end_label="Final actual por comprobar",
                            current_budget_input="",
                            current_end_input="",
                        ),
                    )
                self._edit_request = ""
            else:
                self.edit_warning = EDIT_UNKNOWN
                self._mark_uncertain()
