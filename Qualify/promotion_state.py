"""Guided promotion draft; only the separate, explicit confirmation can authorize a charge."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import reflex as rx
from qualify_api.ads.wizard import WizardUnavailable
from qualify_api.tenancy.acting import acting_login

from .auth_state import AuthState
from .planner_vm import back_to_week_href
from .promotion_provider import confirm_review, load_sources, prepare_preview
from .promotion_vm import (
    CONFIRM_FAILED,
    LOAD_FAILED,
    NO_SESSION,
    PREVIEW_FAILED,
    STEP_TITLES,
    PromotionDraftVM,
    PromotionReviewVM,
    PromotionSourceVM,
    cop_label,
    first_problem,
    readable_date,
    step_problem,
)
from .tenant import tenant_uuid
from .ui import go_to_step, settle_step
from .ui.steps_vm import guard_step, parse_step_param, step_direction

logger = logging.getLogger(__name__)


class PromotionState(rx.State):
    sources: list[PromotionSourceVM] = []
    form: PromotionDraftVM = PromotionDraftVM()
    review: PromotionReviewVM = PromotionReviewVM()
    step: int = 1
    direction: str = "next"
    timezone_name: str = ""
    loading: bool = False
    busy: bool = False
    error: str = ""
    success: str = ""
    reviewed: bool = False
    confirm_charge: bool = False
    entry_available: bool = False
    back_href: str = "/drafts"
    back_label: str = "Por aprobar"
    _loaded_context: tuple[str, str, str] = ("", "", "")
    _piece_id: str = ""
    _request_key: str = ""
    _operation: str = ""
    _return_params: dict[str, str] = {}
    _tenant_timezone: str = ""

    @rx.var
    def title(self) -> str:
        if self.reviewed:
            return "Revisa tu anuncio antes de autorizarlo"
        return STEP_TITLES[min(max(self.step, 1), 4) - 1]

    @rx.var
    def selected_source(self) -> PromotionSourceVM:
        return next(
            (row for row in self.sources if row.id == self.form.source_id),
            PromotionSourceVM(id="", account_label="", caption=""),
        )

    @rx.var
    def execution_reason(self) -> str:
        return self.selected_source.unavailable_reason

    @rx.var
    def budget_label(self) -> str:
        return cop_label(self.form.budget)

    @rx.var
    def charge_button(self) -> str:
        return "Autorizar hasta " + self.budget_label

    @rx.var
    def start_label(self) -> str:
        return readable_date(self.form.start_local)

    @rx.var
    def end_label(self) -> str:
        return readable_date(self.form.end_local)

    @rx.var
    def has_remote_review(self) -> bool:
        return bool(self.review.review_id and self.review.preview_url)

    def _invalidate_review(self) -> None:
        self.review = PromotionReviewVM()
        self.reviewed = False
        self.confirm_charge = False
        self.success = ""
        self._request_key = str(uuid4())

    @rx.event
    def edit(self, name: str, value: str) -> None:
        if self.busy or name not in {
            "link_url",
            "city_name",
            "radius_km",
            "age_min",
            "age_max",
            "budget",
            "start_local",
            "end_local",
        }:
            return
        if getattr(self.form, name) != value:
            self.form = replace(self.form, **{name: value})
            self.error = ""
            self._invalidate_review()

    @rx.event
    def option(self, name: str, value: bool) -> None:
        if self.busy or name not in {"housing", "advantage_audience"}:
            return
        self.form = replace(self.form, **{name: value})
        self.error = ""
        self._invalidate_review()

    @rx.event
    def accept_charge(self, value: bool) -> None:
        self.confirm_charge = (
            bool(value) if self.has_remote_review and not self.busy and not self.success else False
        )

    @rx.event
    def choose_source(self, source_id: str) -> None:
        if self.busy:
            return
        source = next((row for row in self.sources if row.id == source_id), None)
        if source is None:
            return
        zone = source.timezone_name or self._tenant_timezone
        changed_zone = zone != self.timezone_name
        self.form = replace(
            self.form,
            source_id=source.id,
            link_url=source.default_link_url,
            **({"start_local": "", "end_local": ""} if changed_zone else {}),
        )
        self.timezone_name = zone
        self.error = ""
        self._invalidate_review()

    def _step_completeness(self) -> list[bool]:
        return [not step_problem(self.form, n, self.timezone_name) for n in range(1, 5)]

    @rx.event
    def read_step(self) -> rx.event.EventSpec:
        params = self.router.url.query_parameters
        target = guard_step(parse_step_param(params.get("paso"), 4), self._step_completeness())
        self.direction = step_direction(self.step, target, self.direction)
        reviewed = (
            target == 4
            and params.get("revision") == "1"
            and not first_problem(self.form, self.timezone_name)
        )
        if target != self.step or reviewed != self.reviewed:
            self.confirm_charge = False
        self.reviewed = reviewed
        self.step = target
        return settle_step()

    @rx.event
    def next_step(self) -> rx.event.EventSpec | None:
        if self.busy or self.loading or not self.sources:
            return None
        problem = step_problem(self.form, self.step, self.timezone_name)
        if problem:
            self.error = problem
            return None
        self.error = ""
        if self.step == 4:
            self.reviewed = True
            self.confirm_charge = False
            return go_to_step(
                f"/drafts/{self._piece_id}/promote", 4, revision="1", **self._return_params
            )
        self.step += 1
        self.direction = "next"
        return go_to_step(f"/drafts/{self._piece_id}/promote", self.step, **self._return_params)

    @rx.event
    def back_step(self) -> rx.event.EventSpec | None:
        if self.busy:
            return None
        self.error = ""
        self.confirm_charge = False
        if self.reviewed:
            self.reviewed = False
            return go_to_step(
                f"/drafts/{self._piece_id}/promote", 4, back=True, **self._return_params
            )
        self.step = max(1, self.step - 1)
        self.direction = "back"
        return go_to_step(
            f"/drafts/{self._piece_id}/promote", self.step, back=True, **self._return_params
        )

    async def _session(self) -> tuple[str, str, str]:
        auth = await self.get_state(AuthState)
        return auth.session_tenant_id, auth._auth_user_id, auth._session_user_id

    @rx.event(background=True)
    async def load_entry(self) -> None:
        async with self:
            self.entry_available = False
            context = await self._session()
            piece = tenant_uuid(str(getattr(self, "draft_id", "")))
        if piece is None or not all(tenant_uuid(value) for value in context):
            return
        try:
            with acting_login(UUID(context[1])):
                rows, _ = await asyncio.to_thread(load_sources, UUID(context[0]), piece)
        except Exception as exc:
            logger.warning("promotion entry read failed: %s", type(exc).__name__)
            return
        async with self:
            if context == await self._session() and str(piece) == str(
                getattr(self, "draft_id", "")
            ):
                self.entry_available = bool(rows)

    @rx.event(background=True)
    async def load(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            context = await self._session()
            piece = tenant_uuid(str(getattr(self, "draft_id", "")))
            params = dict(self.router.url.query_parameters)
            if piece is None or not all(tenant_uuid(value) for value in context):
                self.loading = False
                self.error = NO_SESSION if piece else LOAD_FAILED
                return
            if self._loaded_context == context and self._piece_id == str(piece) and self.sources:
                self.read_step()
                return
            self.sources = []
            self.form = PromotionDraftVM()
            self._invalidate_review()
            self._loaded_context = context
            self._piece_id = str(piece)
            self.loading = True
            self.error = ""
            self.busy = False
            self.step = 1
            self._operation = operation = str(uuid4())
            self._return_params = {
                key: str(params[key])
                for key in ("desde", "semana", "vista", "evento")
                if params.get(key)
            }
            week = back_to_week_href(params)
            self.back_href = week or f"/drafts/{piece}"
            self.back_label = "Tu semana" if week else "Revisar publicación"
            event_id = tenant_uuid(str(params.get("evento", "")))
        try:
            with acting_login(UUID(context[1])):
                rows, zone = await asyncio.to_thread(
                    load_sources, UUID(context[0]), piece, event_id
                )
        except Exception as exc:
            logger.warning("promotion sources read failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = str(exc) if isinstance(exc, WizardUnavailable) else LOAD_FAILED
        else:
            async with self:
                if context != await self._session() or operation != self._operation:
                    return
                self.sources = rows
                self._tenant_timezone = zone
                self.timezone_name = zone
                if len(rows) == 1:
                    self.choose_source(rows[0].id)
                try:
                    start = datetime.now(ZoneInfo(self.timezone_name)) + timedelta(hours=1)
                    self.form = replace(
                        self.form,
                        start_local=start.strftime("%Y-%m-%dT%H:%M"),
                        end_local=(start + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M"),
                    )
                except (ValueError, ZoneInfoNotFoundError):
                    pass
                self.read_step()
        finally:
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.loading = False
        yield settle_step()

    @rx.event(background=True)
    async def create_preview(self) -> None:
        await self._remote(confirm=False)

    @rx.event(background=True)
    async def confirm(self) -> None:
        await self._remote(confirm=True)

    async def _remote(self, *, confirm: bool) -> None:
        async with self:
            context = await self._session()
            if self.busy or self.loading or not self.reviewed or self.success:
                return
            if context != self._loaded_context or not all(tenant_uuid(v) for v in context):
                self.error = NO_SESSION
                return
            problem = first_problem(self.form, self.timezone_name)
            if problem or self.execution_reason:
                self.error = problem or self.execution_reason
                return
            if confirm and not (self.has_remote_review and self.confirm_charge):
                self.error = "Revisa la vista previa y acepta el importe antes de autorizarlo."
                return
            self.busy = True
            self.error = ""
            self._operation = operation = str(uuid4())
            form, zone, review = self.form, self.timezone_name, self.review
            piece, request_key = self._piece_id, self._request_key
        try:
            with acting_login(UUID(context[1])):
                if confirm:
                    message = await asyncio.to_thread(
                        confirm_review, UUID(context[0]), UUID(context[2]), review, True
                    )
                else:
                    prepared = await asyncio.to_thread(
                        prepare_preview,
                        UUID(context[0]),
                        UUID(piece),
                        UUID(context[2]),
                        form,
                        zone,
                        request_key,
                    )
        except Exception as exc:
            logger.warning("promotion command failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = (
                        str(exc)
                        if isinstance(exc, WizardUnavailable)
                        else CONFIRM_FAILED
                        if confirm
                        else PREVIEW_FAILED
                    )
        else:
            async with self:
                if context == await self._session() and operation == self._operation:
                    if confirm:
                        self.success = message
                        self.confirm_charge = False
                    else:
                        self.review = prepared
                        self.confirm_charge = False
        finally:
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.busy = False
