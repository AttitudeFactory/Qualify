"""Reflex state for `/whatsapp` → Plantillas (WA-18, QUA-217).

Holds only the frozen VMs of `whatsapp_templates_vm.py` — never an ORM row, never a Graph
client, never a token. The number on screen is `WhatsAppState.selected_connection_id`
(the shell's), the tenant `AuthState.session_tenant_id`.

**Loading.** The tab's root `on_mount` calls `ensure_loaded`; the shell keys the tab by
the selected number, so it fires on tab entry and on every number switch. Guarded by
`loaded_for`/`loading_for` (React may mount twice in dev). The list is the Postgres
mirror (no Graph call); «Sincronizar con Meta» is the only read that reaches Meta.

**The form** is local and synchronous: every keystroke is a foreground handler and the
preview/validation are computed vars over plain strings. Nothing reaches Meta until
«Enviar a revisión», and a duplicate `(name, language)` is refused by the service before
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
    CATEGORY_KEYS,
    CATEGORY_MARKETING,
    DEFAULT_LANGUAGE,
    LANGUAGE_KEYS,
    REVIEW_NOTICE,
    ExampleFieldVM,
    TemplateForm,
    TemplateVM,
    body_variables,
    example_fields,
    preview_body,
    preview_buttons,
    suggest_name,
    sync_report_message,
    validate_template_form,
)
from .whatsapp_vm import graph_error_notice

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LOAD_FAILED = (
    "No se pudieron cargar las plantillas de este número. Vuelve a intentarlo en un momento."
)
_NO_NUMBER = "Este número ya no está conectado. Actualizamos la lista de números."
_NO_CREDENTIAL = (
    "Falta el acceso de Meta para este número. Pide al equipo de Qualify que vuelva a conectarlo."
)
_ALREADY_EXISTS = "Ya hay una plantilla con ese nombre e idioma en este número."
_GONE = "Esa plantilla ya no está en este número. Actualizamos la lista."
_CREATED = "Plantilla enviada a revisión. " + REVIEW_NOTICE
_DELETED = "Plantilla eliminada en Meta (con todos sus idiomas)."
_INVALID = "Revisa la plantilla: Meta no la aceptaría así."

_TEXT_FIELDS = frozenset({"name", "header", "body", "footer", "url_text", "url"})
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

    # -- «Nueva plantilla» -------------------------------------------------------------
    form_open: bool = False
    form_category: str = CATEGORY_MARKETING
    form_name: str = ""
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
    form_examples: dict[str, str] = {}
    form_error: str = ""
    form_error_tone: str = "warn"
    submitting: bool = False

    # ==================================================================================
    # Computed vars
    # ==================================================================================

    def _form(self) -> TemplateForm:
        return TemplateForm(
            category=self.form_category,
            name=self.form_name,
            language=self.form_language,
            header=self.form_header,
            body=self.form_body,
            footer=self.form_footer,
            button_kind=self.form_button_kind,
            quick_replies=(self.form_quick_1, self.form_quick_2, self.form_quick_3),
            url_text=self.form_url_text,
            url=self.form_url,
            examples=dict(self.form_examples),
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
    def form_examples_fields(self) -> list[ExampleFieldVM]:
        return example_fields(self._form())

    @rx.var
    def preview_header(self) -> str:
        return self.form_header.strip()

    @rx.var
    def preview_text(self) -> str:
        return preview_body(self.form_body, self.form_examples)

    @rx.var
    def preview_footer(self) -> str:
        return self.form_footer.strip()

    @rx.var
    def preview_button_labels(self) -> list[str]:
        return preview_buttons(self._form())

    @rx.var
    def body_count(self) -> str:
        return f"{len(self.form_body.strip())}/1024"

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
        self.form_category = CATEGORY_MARKETING
        self.form_name = ""
        self.form_language = DEFAULT_LANGUAGE
        self.form_header = ""
        self.form_body = ""
        self.form_footer = ""
        self.form_button_kind = BUTTONS_NONE
        self.form_quick_1 = self.form_quick_2 = self.form_quick_3 = ""
        self.form_url_text = ""
        self.form_url = ""
        self.form_examples = {}
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
        if isinstance(category, str) and category in CATEGORY_KEYS:
            self.form_category = category
            self.form_error = ""

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
        The name is folded to Meta's alphabet as it is typed («Promo Octubre» →
        «promo_octubre»), so the rule is shown, not just enforced."""
        if field not in _TEXT_FIELDS or not isinstance(value, str):
            return
        if field == "name":
            value = suggest_name(value) if value.strip() else ""
        setattr(self, f"form_{field}", value)
        if field == "body":
            names = set(body_variables(value))
            self.form_examples = {k: v for k, v in self.form_examples.items() if k in names}
        self.form_error = ""

    @rx.event
    def set_quick_reply(self, index: int, value: str) -> None:
        if index in (1, 2, 3) and isinstance(value, str):
            setattr(self, f"form_quick_{index}", value)

    @rx.event
    def set_example(self, name: str, value: str) -> None:
        if name in body_variables(self.form_body) and isinstance(value, str):
            self.form_examples = {**self.form_examples, name: value}

    @rx.event(background=True)
    async def submit(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Enviar a revisión»: validate, create at Meta, mirror, list."""
        async with self:
            if self.submitting:
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
            self._close_form()
            self.templates = [
                created,
                *[t for t in self.templates if t.template_id != created.template_id],
            ]
            self.banner, self.banner_tone = _CREATED, "ok"
        await self._load(force=True)
