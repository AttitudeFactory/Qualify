"""Reflex state for `/whatsapp` → Plantillas (WA-18, QUA-217).

Holds only the frozen VMs of `whatsapp_templates_vm.py` — never an ORM row, never a Graph
client, never a token. The number on screen is `WhatsAppState.selected_connection_id`
(the shell's), the tenant `AuthState.session_tenant_id`.

**Loading.** The tab's root `on_mount` calls `ensure_loaded`; the shell keys the tab by
the selected number, so it fires on tab entry and on every number switch. Guarded by
`loaded_for`/`loading_for` (React may mount twice in dev). The list is the Postgres
mirror (no Graph call); «Ver si ya las aprobaron» is the only read that reaches Meta.

**The form** (m-24842997) is four steps — ¿Qué quieres avisar? → Escribe el mensaje →
Botones → Así lo verá tu cliente — local and synchronous: every keystroke is a foreground
handler and the preview/validation are computed vars over plain strings. The owner never
types `{{…}}` nor an underscore: the name button inserts «[nombre]», Meta's example and
internal name are filled in by `whatsapp_templates_vm`. Nothing reaches Meta until
«Enviar a aprobación», and a duplicate `(name, language)` is refused by the service before
it spends one of the WABA's 100 creations/hour.

Every Postgres or Graph call runs in a background event (same rule as `WhatsAppState`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import reflex as rx
from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.whatsapp.client import WhatsAppApiError
from qualify_api.whatsapp.templates import (
    NoWhatsAppNumber,
    TemplateAlreadyExists,
    TemplateNotFound,
)
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .tenant import tenant_uuid
from .whatsapp_state import WhatsAppState
from .whatsapp_templates_provider import (
    create_template,
    delete_template,
    list_templates,
    sync_templates,
)
from .whatsapp_templates_vm import (
    BUTTON_KIND_KEYS,
    BUTTONS_NONE,
    CATEGORY_MARKETING,
    DEFAULT_LANGUAGE,
    GUIDED_CATEGORIES,
    GUIDED_CATEGORY_KEYS,
    LANGUAGE_KEYS,
    MAX_BODY_CHARS,
    STEP_KIND,
    STEP_REVIEW,
    STEPS,
    SUBMITTED_MESSAGE,
    TemplateForm,
    TemplateVM,
    auto_label,
    display_name,
    insert_name,
    language_label,
    preview_body,
    preview_buttons,
    sync_report_message,
    template_name,
    validate_step,
    validate_template_form,
)
from .whatsapp_vm import TAB_CONTACTS, graph_error_notice

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LOAD_FAILED = (
    "No se pudieron cargar las plantillas de este número. Vuelve a intentarlo en un momento."
)
_NO_NUMBER = "Este número ya no está conectado. Actualizamos la lista de números."
_NO_CREDENTIAL = (
    "Falta el acceso de Meta para este número. Pide al equipo de Qualify que vuelva a conectarlo."
)
_ALREADY_EXISTS = (
    "Ya hay un mensaje con ese nombre en este número. Cámbialo en «Más opciones» del paso 2."
)
_GONE = "Esa plantilla ya no está en este número. Actualizamos la lista."
_CREATED = SUBMITTED_MESSAGE
_DELETED = "Plantilla eliminada en Meta (con todos sus idiomas)."
_INVALID = "Revisa el mensaje: Meta no lo aceptaría así. Vuelve al paso 2 y corrígelo."

_TEXT_FIELDS = frozenset({"label", "header", "body", "footer", "url_text", "url"})
_CATEGORY_TITLE: dict[str, str] = {key: label for key, label, _h in GUIDED_CATEGORIES}
_INFRA_ERRORS = (httpx.HTTPError, SQLAlchemyError)


def _failure_notice(exc: Exception) -> tuple[str, str]:
    """Any failure of a Graph-backed action → (message, tone). Meta's code only."""
    if isinstance(exc, WhatsAppApiError):
        return graph_error_notice(
            code=exc.code, is_auth_error=exc.is_auth_error, is_transport=exc.is_transport
        )
    if isinstance(exc, NoWhatsAppNumber):
        return _NO_NUMBER, "warn"
    if isinstance(exc, CredentialNotFound):
        return _NO_CREDENTIAL, "error"
    if isinstance(exc, TemplateAlreadyExists):
        return _ALREADY_EXISTS, "warn"
    if isinstance(exc, TemplateNotFound):
        return _GONE, "warn"
    return _LOAD_FAILED, "error"


class WhatsAppTemplatesState(rx.State):
    """State for the Plantillas tab."""

    templates: list[TemplateVM] = []
    loaded_for: str = ""
    loading_for: str = ""
    banner: str = ""
    banner_tone: str = "info"
    syncing: bool = False
    deleting_id: str = ""

    # -- «Crear un mensaje» (m-24842997: four steps, nothing technical to type) ------
    form_open: bool = False
    step: int = STEP_KIND
    form_done: bool = False  # sent to Meta: the drawer shows the notice + next step (N3)
    form_category: str = CATEGORY_MARKETING
    form_label: str = ""  # the owner's own name for the message ("" → `auto_label`)
    form_language: str = DEFAULT_LANGUAGE
    form_header: str = ""
    form_body: str = ""
    form_footer: str = ""
    form_button_kind: str = BUTTONS_NONE
    form_quick_1: str = ""
    form_quick_2: str = ""
    form_quick_3: str = ""
    form_url_text: str = ""
    form_url: str = ""
    form_error: str = ""
    form_error_tone: str = "warn"
    submitting: bool = False

    # ==================================================================================
    # Computed vars
    # ==================================================================================

    def _name(self) -> str:
        """Meta's internal name, from the owner's words; never one this number used."""
        taken = {t.name for t in self.templates}
        return template_name(self.form_label, self.form_category, self.form_body, taken)

    def _form(self) -> TemplateForm:
        return TemplateForm(
            category=self.form_category,
            name=self._name(),
            language=self.form_language,
            header=self.form_header,
            body=self.form_body,
            footer=self.form_footer,
            button_kind=self.form_button_kind,
            quick_replies=(self.form_quick_1, self.form_quick_2, self.form_quick_3),
            url_text=self.form_url_text,
            url=self.form_url,
        )

    @rx.var
    def has_templates(self) -> bool:
        return len(self.templates) > 0

    @rx.var
    def ready(self) -> bool:
        return self.loaded_for != ""

    @rx.var
    def failed(self) -> bool:
        return self.loaded_for == "" and self.loading_for == "" and self.banner != ""

    @rx.var
    def form_problem(self) -> str:
        return validate_template_form(self._form())

    @rx.var
    def step_problem(self) -> str:
        return validate_step(self._form(), self.step)

    @rx.var
    def completed_steps(self) -> list[bool]:
        return [index < self.step for index in range(len(STEPS))]

    @rx.var
    def label_placeholder(self) -> str:
        """What the message is called if the owner names nothing in «Más opciones»."""
        return auto_label(self.form_category, self.form_body)

    @rx.var
    def form_display_name(self) -> str:
        return display_name(self._name())

    @rx.var
    def form_kind_label(self) -> str:
        return _CATEGORY_TITLE.get(self.form_category, "")

    @rx.var
    def form_language_label(self) -> str:
        return language_label(self.form_language)

    @rx.var
    def preview_header(self) -> str:
        return self.form_header.strip()

    @rx.var
    def preview_text(self) -> str:
        return preview_body(self.form_body)

    @rx.var
    def preview_footer(self) -> str:
        return self.form_footer.strip()

    @rx.var
    def preview_button_labels(self) -> list[str]:
        return preview_buttons(self._form())

    @rx.var
    def body_count(self) -> str:
        return f"{len(self.form_body.strip())}/{MAX_BODY_CHARS}"

    # ==================================================================================
    # Loading
    # ==================================================================================

    async def _scope(self) -> tuple[str, UUID | None]:
        """(connection_id, tenant_id) of the number on screen."""
        shell = await self.get_state(WhatsAppState)
        auth = await self.get_state(AuthState)
        tenant = tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None
        return shell.selected_connection_id, tenant

    @rx.event(background=True)
    async def ensure_loaded(self) -> None:
        await self._load(force=False)

    @rx.event(background=True)
    async def reload(self) -> None:
        await self._load(force=True)

    async def _load(self, *, force: bool) -> None:
        async with self:
            connection_id, tenant_id = await self._scope()
            if not connection_id or self.loading_for == connection_id:
                return
            if not force and self.loaded_for == connection_id:
                return
            if self.loaded_for != connection_id:
                self.templates = []
                self.loaded_for = ""
                self.banner = ""
                self._close_form()
            self.loading_for = connection_id
        if tenant_id is None:
            async with self:
                self.loading_for = ""
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        try:
            templates = await list_templates(tenant_id, UUID(connection_id))
        except (NoWhatsAppNumber, *_INFRA_ERRORS) as exc:
            if not isinstance(exc, NoWhatsAppNumber):
                logger.error("whatsapp templates load failed: %s", type(exc).__name__)
            async with self:
                self.loading_for = ""
                self.banner, self.banner_tone = _failure_notice(exc)
            return
        async with self:
            current, _tenant = await self._scope()
            if current != connection_id:
                self.loading_for = ""
                return
            self.templates = templates
            self.loaded_for = connection_id
            self.loading_for = ""

    # ==================================================================================
    # Sync / delete
    # ==================================================================================

    @rx.event(background=True)
    async def sync(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.syncing:
                return
            connection_id, tenant_id = await self._scope()
            if not connection_id:
                return
            self.syncing = True
            self.banner = ""
        if tenant_id is None:
            async with self:
                self.syncing = False
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        try:
            report = await sync_templates(tenant_id, UUID(connection_id))
        except (WhatsAppApiError, NoWhatsAppNumber, CredentialNotFound, *_INFRA_ERRORS) as exc:
            if isinstance(exc, _INFRA_ERRORS):
                logger.error("whatsapp templates sync failed: %s", type(exc).__name__)
            async with self:
                self.syncing = False
                self.banner, self.banner_tone = _failure_notice(exc)
            if isinstance(exc, WhatsAppApiError) and exc.is_auth_error:
                yield WhatsAppState.load_numbers
            return
        async with self:
            self.syncing = False
            self.banner = sync_report_message(report.listed, report.created, report.updated)
            self.banner_tone = "ok"
        await self._load(force=True)

    @rx.event(background=True)
    async def delete(self, template_id: str) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.deleting_id or template_id not in {t.template_id for t in self.templates}:
                return  # arrived over the wire; only templates on screen can be deleted
            connection_id, tenant_id = await self._scope()
            if not connection_id:
                return
            self.deleting_id = template_id
            self.banner = ""
        if tenant_id is None:
            async with self:
                self.deleting_id = ""
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        try:
            await delete_template(tenant_id, UUID(connection_id), UUID(template_id))
        except (
            WhatsAppApiError,
            NoWhatsAppNumber,
            CredentialNotFound,
            TemplateNotFound,
            *_INFRA_ERRORS,
        ) as exc:
            if isinstance(exc, _INFRA_ERRORS):
                logger.error("whatsapp template delete failed: %s", type(exc).__name__)
            async with self:
                self.deleting_id = ""
                self.banner, self.banner_tone = _failure_notice(exc)
            if isinstance(exc, WhatsAppApiError) and exc.is_auth_error:
                yield WhatsAppState.load_numbers
            return
        async with self:
            self.deleting_id = ""
            self.banner, self.banner_tone = _DELETED, "ok"
        await self._load(force=True)

    # ==================================================================================
    # The form
    # ==================================================================================

    def _close_form(self) -> None:
        self.form_open = False
        self.step = STEP_KIND
        self.form_done = False
        self.form_category = CATEGORY_MARKETING
        self.form_label = ""
        self.form_language = DEFAULT_LANGUAGE
        self.form_header = ""
        self.form_body = ""
        self.form_footer = ""
        self.form_button_kind = BUTTONS_NONE
        self.form_quick_1 = self.form_quick_2 = self.form_quick_3 = ""
        self.form_url_text = ""
        self.form_url = ""
        self.form_error = ""

    @rx.event
    def open_form(self) -> None:
        self._close_form()
        self.form_open = True

    @rx.event
    def set_form_open(self, is_open: bool) -> None:
        """The drawer's `on_open_change` (Esc, backdrop, ✕). Closing discards the draft."""
        if not is_open and not self.submitting:
            self._close_form()

    @rx.event
    def set_category(self, category: str | list[str]) -> None:
        if isinstance(category, str) and category in GUIDED_CATEGORY_KEYS:
            self.form_category = category
            self.form_error = ""

    # -- the steps (N6: «Atrás» never loses an answer) ---------------------------------

    def _busy(self) -> bool:
        return self.submitting or self.form_done

    @rx.event
    def next_step(self) -> None:
        if self._busy() or self.step >= STEP_REVIEW:
            return
        problem = validate_step(self._form(), self.step)
        if problem:
            self.form_error, self.form_error_tone = problem, "warn"
            return
        self.form_error = ""
        self.step += 1

    @rx.event
    def back(self) -> None:
        if self.step > STEP_KIND and not self._busy():
            self.step -= 1
            self.form_error = ""

    @rx.event
    def go_to_step(self, index: int) -> None:
        """The stepper: only back to a step already completed."""
        if isinstance(index, int) and 0 <= index < self.step and not self._busy():
            self.step = index
            self.form_error = ""

    @rx.event
    def add_name(self) -> None:
        """«Agregar el nombre del cliente»: the owner never types the variable."""
        self.form_body = insert_name(self.form_body)
        self.form_error = ""

    @rx.event
    def see_contacts(self) -> rx.event.EventSpec:
        """N3 after «Enviar a aprobación»: close the drawer, open «Contactos» (the
        clients who accepted your promotions)."""
        self._close_form()
        return WhatsAppState.select_tab(TAB_CONTACTS)

    @rx.event
    def set_language(self, language: str) -> None:
        if language in LANGUAGE_KEYS:
            self.form_language = language

    @rx.event
    def set_button_kind(self, kind: str | list[str]) -> None:
        if isinstance(kind, str) and kind in BUTTON_KIND_KEYS:
            self.form_button_kind = kind

    @rx.event
    def set_field(self, field: str, value: str) -> None:
        """One setter for the free-text fields; anything outside the whitelist is junk.
        `label` is the owner's own name for the message, in their words: Meta's
        internal name is derived from it (`template_name`), never typed."""
        if field not in _TEXT_FIELDS or not isinstance(value, str):
            return
        setattr(self, f"form_{field}", value)
        self.form_error = ""

    @rx.event
    def set_quick_reply(self, index: int, value: str) -> None:
        if index in (1, 2, 3) and isinstance(value, str):
            setattr(self, f"form_quick_{index}", value)

    @rx.event(background=True)
    async def submit(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Enviar a aprobación»: validate, create at Meta, mirror, list. The drawer stays
        open on the exact notice and the next step (N3)."""
        async with self:
            if self.submitting or self.form_done or self.step != STEP_REVIEW:
                return
            form = self._form()
            problem = validate_template_form(form)
            if problem:
                self.form_error, self.form_error_tone = problem, "warn"
                return
            connection_id, tenant_id = await self._scope()
            if not connection_id:
                return
            self.submitting = True
            self.form_error = ""
        if tenant_id is None:
            async with self:
                self.submitting = False
                self.form_error, self.form_error_tone = _NO_SESSION, "error"
            return
        try:
            created = await create_template(tenant_id, UUID(connection_id), form)
        except ValueError:
            # The client's own local check — `validate_template_form` should have caught
            # it first; its English message is for engineers and is not shown.
            async with self:
                self.submitting = False
                self.form_error, self.form_error_tone = _INVALID, "warn"
            return
        except (
            WhatsAppApiError,
            NoWhatsAppNumber,
            CredentialNotFound,
            TemplateAlreadyExists,
            *_INFRA_ERRORS,
        ) as exc:
            if isinstance(exc, _INFRA_ERRORS):
                logger.error("whatsapp template create failed: %s", type(exc).__name__)
            async with self:
                self.submitting = False
                self.form_error, self.form_error_tone = _failure_notice(exc)
            if isinstance(exc, WhatsAppApiError) and exc.is_auth_error:
                yield WhatsAppState.load_numbers
            return
        async with self:
            self.submitting = False
            self.form_done = True
            self.templates = [
                created,
                *[t for t in self.templates if t.template_id != created.template_id],
            ]
            self.banner, self.banner_tone = _CREATED, "ok"
        await self._load(force=True)
