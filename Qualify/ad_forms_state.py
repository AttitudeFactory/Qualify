"""Explicit form publishing, with actor/session and operation fences at every await."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.ads.lead_forms import LeadFormUnavailable
from qualify_api.tenancy.acting import acting_login

from .ad_forms_provider import form_screen, publish_form, receive_form, save_form, sync_form
from .ad_forms_vm import (
    FORM_ROUTE,
    FORM_STEPS,
    FORM_UNCERTAIN,
    AdFormDraftVM,
    AdFormVM,
    FormConnectionVM,
    form_problem,
    form_step_problem,
    question_summary,
)
from .auth_state import AuthState
from .tenant import tenant_uuid
from .ui import go_to_step, settle_step
from .ui.steps_vm import guard_step, parse_step_param, step_direction

logger = logging.getLogger(__name__)


class AdFormsState(rx.State):
    connections: list[FormConnectionVM] = []
    forms: list[AdFormVM] = []
    draft: AdFormDraftVM = AdFormDraftVM()
    selected: AdFormVM = AdFormVM()
    editing: bool = False
    step: int = 1
    direction: str = "next"
    loading: bool = True
    busy: bool = False
    error: str = ""
    notice: str = ""
    publish_consent: bool = False
    receive_consent: bool = False
    discard_open: bool = False
    _context: tuple[str, str, str] = ("", "", "")
    _operation: str = ""
    _pending_form_id: str = ""

    @rx.var
    def title(self) -> str:
        return FORM_STEPS[max(0, min(self.step - 1, len(FORM_STEPS) - 1))]

    @rx.var
    def has_available_page(self) -> bool:
        return any(row.available for row in self.connections)

    @rx.var
    def questions_label(self) -> str:
        return question_summary(self.draft)

    @rx.var
    def page_label(self) -> str:
        return next(
            (row.label for row in self.connections if row.id == self.draft.connection_id),
            "Página por comprobar",
        )

    @rx.var
    def has_unfinished(self) -> bool:
        return (
            not self.editing
            and (not self.selected.id or self.selected.editable)
            and self.draft != AdFormDraftVM()
        )

    @rx.var
    def saved_current(self) -> bool:
        return bool(self.selected.id and self.selected.draft == self.draft)

    @rx.var
    def can_publish(self) -> bool:
        return (
            self.saved_current
            and self.selected.editable
            and self.publish_consent
            and self.step == 5
            and not self.busy
            and not self.loading
        )

    async def _session(self) -> tuple[str, str, str]:
        auth = await self.get_state(AuthState)
        return auth.session_tenant_id, auth._auth_user_id, auth._session_user_id

    async def _current(self, context: tuple[str, str, str], operation: str) -> bool:
        return context == await self._session() and operation == self._operation

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            if self.busy:
                return
            context = await self._session()
            preserve = context == self._context and self.editing
            self._operation = operation = str(uuid4())
            self.loading = True
            self.error = ""
            if context != self._context:
                self.connections, self.forms = [], []
                self.draft, self.selected = AdFormDraftVM(), AdFormVM()
                self.editing, self.publish_consent, self.receive_consent = False, False, False
                self.notice = ""
                self.discard_open = False
            self._context = context
        if not all(tenant_uuid(value) for value in context):
            async with self:
                if await self._current(context, operation):
                    self.error = "Vuelve a iniciar sesión para ver los formularios de tu negocio."
                    self.loading = False
            return
        try:
            with acting_login(UUID(context[1])):
                connections, forms = await asyncio.to_thread(form_screen, UUID(context[0]))
        except Exception as exc:
            logger.warning("lead forms load failed: %s", type(exc).__name__)
            async with self:
                if await self._current(context, operation):
                    self.error = "No pudimos consultar tus formularios. Vuelve a intentarlo."
                    self.loading = False
            return
        async with self:
            if await self._current(context, operation):
                self.connections, self.forms = connections, forms
                self.loading = False
                if not preserve:
                    self.editing = False

    @rx.event
    def new_form(self) -> rx.event.EventSpec | None:
        if self.loading or self.busy:
            return None
        self.draft, self.selected = AdFormDraftVM(), AdFormVM()
        self.editing, self.publish_consent = True, False
        self.receive_consent = False
        self.step, self.direction = 1, "next"
        self.error, self.notice = "", ""
        self.discard_open = False
        return go_to_step(FORM_ROUTE, 1)

    @rx.event
    def resume_editor(self) -> rx.event.EventSpec | None:
        if self.loading or self.busy or not self.has_unfinished:
            return None
        self.editing, self.publish_consent, self.receive_consent = True, False, False
        return go_to_step(FORM_ROUTE, self.step)

    @rx.event
    def ask_discard(self) -> None:
        if not self.busy:
            self.discard_open = True
            self._pending_form_id = ""

    @rx.event
    def keep_draft(self) -> None:
        self.discard_open = False
        self._pending_form_id = ""

    @rx.event
    def discard_draft(self) -> rx.event.EventSpec | None:
        if self.busy or not self.discard_open:
            return None
        pending = self._pending_form_id
        if pending:
            self.draft, self.selected = AdFormDraftVM(), AdFormVM()
            self.discard_open, self._pending_form_id = False, ""
            return AdFormsState.open_form.fn(self, pending)
        return AdFormsState.new_form.fn(self)

    @rx.event
    def open_form(self, form_id: str) -> rx.event.EventSpec | None:
        if self.loading or self.busy:
            return None
        row = next((row for row in self.forms if row.id == form_id), None)
        if row is None:
            return None
        if self.has_unfinished and self.selected.id != form_id:
            self.discard_open, self._pending_form_id = True, form_id
            return None
        self.selected, self.draft = row, row.draft
        self.editing, self.publish_consent = True, False
        self.receive_consent = False
        self.step, self.direction = 5, "next"
        self.error, self.notice = "", ""
        return go_to_step(FORM_ROUTE, 5)

    @rx.event
    def close_editor(self) -> rx.event.EventSpec | None:
        if self.busy:
            return None
        self.editing, self.publish_consent = False, False
        self.receive_consent = False
        self.error, self.notice = "", ""
        return rx.redirect(FORM_ROUTE, replace=True)

    @rx.event
    def edit(self, name: str, value: str) -> None:
        if self.busy or (self.selected.id and not self.selected.editable):
            return
        allowed = {
            "name",
            "privacy_url",
            "thank_you_title",
            "thank_you_body",
            "thank_you_url",
            "custom_questions",
        }
        if name in allowed and len(value) <= 2000:
            self.draft = replace(self.draft, **{name: value})
            self.publish_consent = False
            self.notice = ""

    @rx.event
    def choose_connection(self, connection_id: str) -> None:
        if self.busy or self.selected.id:
            return
        if any(row.id == connection_id and row.available for row in self.connections):
            self.draft = replace(self.draft, connection_id=connection_id)
            self.publish_consent = False

    @rx.event
    def ask(self, name: str, enabled: bool) -> None:
        if self.busy or (self.selected.id and not self.selected.editable):
            return
        if name in {"ask_name", "ask_email", "ask_phone"} and isinstance(enabled, bool):
            self.draft = replace(self.draft, **{name: enabled})
            self.publish_consent = False

    @rx.event
    def consent(self, enabled: bool) -> None:
        if not self.busy:
            self.publish_consent = enabled is True

    @rx.event
    def consent_to_receive(self, enabled: bool) -> None:
        if not self.busy:
            self.receive_consent = enabled is True

    @rx.event
    def next_step(self) -> rx.event.EventSpec | None:
        if self.busy or self.loading:
            return None
        self.error = form_step_problem(self.draft, self.step)
        if self.error:
            return None
        self.step = min(5, self.step + 1)
        self.direction, self.publish_consent = "next", False
        return go_to_step(FORM_ROUTE, self.step)

    @rx.event
    def back_step(self) -> rx.event.EventSpec | None:
        if self.busy or (self.selected.id and not self.selected.editable):
            return None
        self.step = max(1, self.step - 1)
        self.direction, self.publish_consent, self.error = "back", False, ""
        return go_to_step(FORM_ROUTE, self.step, back=True)

    @rx.event
    def read_step(self) -> rx.event.EventSpec:
        requested = parse_step_param(self.router.url.query_parameters.get("paso"), 5)
        target = guard_step(requested, [not form_step_problem(self.draft, n) for n in range(1, 5)])
        if self.selected.id and not self.selected.editable:
            target = 5
        if target != self.step:
            self.publish_consent = False
        self.direction = step_direction(self.step, target, self.direction)
        self.step = target
        return settle_step()

    @rx.event(background=True)
    async def save(self) -> None:
        async with self:
            context = await self._session()
            if self.busy or self.loading or context != self._context or not self.editing:
                return
            if self.selected.id and not self.selected.editable:
                return
            self.error = form_problem(self.draft)
            if self.error or not all(tenant_uuid(value) for value in context):
                return
            snapshot, form_id, revision = self.draft, self.selected.id, self.selected.revision
            self._operation = operation = str(uuid4())
            self.busy, self.publish_consent = True, False
            self.notice = ""
        try:
            with acting_login(UUID(context[1])):
                row = await asyncio.to_thread(
                    save_form, UUID(context[0]), snapshot, form_id, revision
                )
        except Exception as exc:
            logger.warning("lead form save failed: %s", type(exc).__name__)
            async with self:
                if await self._current(context, operation):
                    self.error = (
                        str(exc)
                        if isinstance(exc, LeadFormUnavailable)
                        else ("No pudimos guardar el borrador. Vuelve a intentarlo.")
                    )
                    self.busy = False
            return
        async with self:
            if await self._current(context, operation):
                row = replace(row, page_label=self.page_label)
                self.selected, self.draft = row, row.draft
                self.forms = [row] + [item for item in self.forms if item.id != row.id]
                self.busy = False
                self.notice = "Borrador guardado en Qualify. Todavía no se ha creado en Meta."

    @rx.event(background=True)
    async def publish(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context or not self.can_publish:
                return
            if not all(tenant_uuid(value) for value in context):
                return
            row = self.selected
            self._operation = operation = str(uuid4())
            self.busy, self.publish_consent = True, False
            self.error, self.notice = "", ""
        try:
            with acting_login(UUID(context[1])):
                result = await asyncio.to_thread(
                    publish_form, UUID(context[0]), UUID(row.id), row.revision
                )
        except Exception as exc:
            logger.warning("lead form publish failed: %s", type(exc).__name__)
            async with self:
                if await self._current(context, operation):
                    self.busy = False
                    if isinstance(exc, LeadFormUnavailable):
                        self.error = str(exc)
                    else:
                        self.selected = replace(
                            row,
                            status="unknown",
                            status_label="Por comprobar en Meta",
                            tone="warn",
                            editable=False,
                        )
                        self.forms = [self.selected] + [
                            item for item in self.forms if item.id != row.id
                        ]
                        self.error = FORM_UNCERTAIN
            return
        async with self:
            if await self._current(context, operation):
                result = replace(result, page_label=self.page_label)
                self.selected, self.busy = result, False
                self.forms = [result] + [item for item in self.forms if item.id != result.id]
                self.notice = (
                    "Formulario creado en Meta. Todavía no hay un anuncio asociado."
                    if result.published
                    else FORM_UNCERTAIN
                )

    @rx.event(background=True)
    async def refresh_answers(self, form_id: str) -> None:
        async with self:
            context = await self._session()
            if self.busy or self.loading or context != self._context:
                return
            if not all(tenant_uuid(value) for value in context):
                return
            if not any(row.id == form_id and row.published for row in self.forms):
                return
            self._operation = operation = str(uuid4())
            self.busy, self.error, self.notice = True, "", ""
        try:
            with acting_login(UUID(context[1])):
                await asyncio.to_thread(sync_form, UUID(context[0]), UUID(form_id))
        except Exception as exc:
            logger.warning("lead form answers refresh failed: %s", type(exc).__name__)
            message = (
                str(exc)
                if isinstance(exc, LeadFormUnavailable)
                else ("No pudimos consultar las respuestas. Vuelve a intentarlo.")
            )
            async with self:
                if await self._current(context, operation):
                    self.error, self.busy = message, False
            return
        async with self:
            if await self._current(context, operation):
                self.busy = False
                self.notice = (
                    "Consulta terminada. Revisa los clientes interesados en Por responder."
                )

    @rx.event(background=True)
    async def receive_answers(self) -> None:
        async with self:
            context = await self._session()
            if (
                self.busy
                or self.loading
                or context != self._context
                or not self.receive_consent
                or not self.selected.published
                or not all(tenant_uuid(value) for value in context)
            ):
                return
            form_id = self.selected.id
            self._operation = operation = str(uuid4())
            self.busy, self.receive_consent = True, False
            self.error, self.notice = "", ""
        try:
            with acting_login(UUID(context[1])):
                await asyncio.to_thread(receive_form, UUID(context[0]), UUID(form_id))
        except Exception as exc:
            logger.warning("lead form subscription failed: %s", type(exc).__name__)
            async with self:
                if await self._current(context, operation):
                    self.busy = False
                    self.error = (
                        str(exc)
                        if isinstance(exc, LeadFormUnavailable)
                        else (
                            "No pudimos comprobar la recepción. Revisa tus cuentas en Tus redes "
                            "antes de volver a intentarlo."
                        )
                    )
            return
        async with self:
            if await self._current(context, operation):
                self.busy = False
                self.notice = (
                    "Meta confirmó la solicitud de recepción para esta página. "
                    "Todavía falta comprobar una respuesta de prueba."
                )
