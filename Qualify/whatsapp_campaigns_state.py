"""Reflex state for `/whatsapp` → Campañas (WA-20, QUA-219): the number's campaigns, the
«Nueva campaña» wizard and the campaign detail.

Holds only the frozen VMs of `whatsapp_campaigns_vm.py` / `whatsapp_templates_vm.py`. The
templates' raw Meta components (needed to know which variables a send must fill) live
in a backend-only var (`_components`) and never reach the browser.

**The wizard** (m-24842996, three steps: Mensaje → A quién → Revisar). «Mensaje» is the
approved message plus its blanks and an optional name; «A quién» is everyone who
accepted by default, «solo desde…» a day, the rest folded in «Más filtros» and the pace
in «Más opciones» (a choice, 30 per minute by default — never a number to type). A step
is left only when it is valid, and the reason is shown next to «Siguiente». Every
audience change recounts the live opt-ins in the background (`build_audience`).
Entering «Revisar» saves the campaign as a DRAFT and asks the service for the estimate
(`estimate` needs a campaign). «Atrás» from «Revisar» keeps every answer; entering it
again reuses that draft when nothing changed, otherwise the old draft is cancelled and a
new one created — a draft is never silently rewritten. Nothing is sent until «Enviar
ahora» (N13); closing the panel leaves the draft in the list.

**Launch** goes through `CampaignService.launch` (resumes, never resends); the sends
leave later through the outbox sender, so Meta's verdicts show up in the detail on
«Actualizar» (in words, never as codes), next to «Ver respuestas en Chats» (N3).

Every Postgres call runs in a background event, off-thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import reflex as rx
from qualify_api.whatsapp.campaigns import (
    CampaignNotFound,
    CampaignStateError,
    TemplateNotSendable,
)
from qualify_api.whatsapp.templates import TemplateNotFound
from sqlalchemy.exc import SQLAlchemyError

from . import inbox_provider
from .auth_state import AuthState
from .nav_url import close_flow_script, flow_param
from .tenant import tenant_uuid
from .whatsapp_campaigns_provider import (
    UnknownUser,
    brands_for,
    campaign_detail,
    campaign_rows,
    cancel,
    count_audience,
    create_draft,
    estimate,
    launch,
    wizard_templates,
)
from .whatsapp_campaigns_vm import (
    ALL_BRANDS,
    AUDIENCE_NONE,
    DEFAULT_MAX_PER_MINUTE,
    EMPTY_DETAIL,
    EMPTY_ESTIMATE,
    EMPTY_TEMPLATE,
    PACE_KEYS,
    SCOPE_ALL,
    SCOPES,
    STEP_AUDIENCE,
    STEP_MESSAGE,
    STEP_REVIEW,
    STEPS,
    AudienceForm,
    CampaignDetailVM,
    CampaignRowVM,
    EstimateVM,
    OptionVM,
    SendVM,
    VariableFieldVM,
    audience_count_label,
    audience_filter_json,
    audience_form_for,
    campaign_name,
    everyone_label,
    launch_message,
    pace_explanation,
    pace_value,
    sending_time,
    validate_basics,
    validate_scope,
    validate_variables,
    variable_fields,
)
from .whatsapp_contacts_vm import SOURCE_KEYS
from .whatsapp_state import WhatsAppState
from .whatsapp_templates_vm import (
    TemplateVM,
    build_send_components,
    send_variables,
)
from .whatsapp_vm import TAB_CHATS, TAB_TEMPLATES

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudieron cargar las campañas. Vuelve a intentarlo en un momento."
_DETAIL_FAILED = "No se pudo leer la campaña. Vuelve a intentarlo en un momento."
_SAVE_FAILED = "No se pudo guardar la campaña. Vuelve a intentarlo en un momento."
_UNKNOWN_USER = (
    "Tu usuario no figura en este negocio, y una campaña necesita a quien la crea. Pide al "
    "equipo de Qualify que te agregue."
)
_NOT_SENDABLE = (
    "Ese mensaje ya no está aprobado (o no es de este número). Revisa su estado en "
    "Plantillas y elige otro."
)
_STATE_CHANGED = "La promoción cambió de estado mientras tanto. Actualizamos el detalle."
_GONE = "Esa promoción ya no existe. Actualizamos la lista."
_CANCELLED = "Promoción detenida: {n} envíos pendientes retirados."
_DRAFT_SAVED = (
    "Tu promoción quedó guardada sin enviar. Ábrela en la lista y toca «Enviar ahora» "
    "cuando quieras."
)
LAUNCHED = frozenset({"running", "paused", "done"})


def draft_key(
    template_id: str, components: Any, audience: dict[str, Any], rate: int, name: str
) -> str:
    """What a draft was created from: equal keys → the same draft is reused."""
    return json.dumps([template_id, components, audience, rate, name], sort_keys=True, default=str)


def _campaign_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, UnknownUser):
        return _UNKNOWN_USER, "error"
    if isinstance(exc, (TemplateNotSendable, TemplateNotFound)):
        return _NOT_SENDABLE, "warn"
    if isinstance(exc, CampaignStateError):
        return _STATE_CHANGED, "warn"
    if isinstance(exc, CampaignNotFound):
        return _GONE, "warn"
    if isinstance(exc, ValueError):
        return "Revisa los datos de la promoción.", "warn"
    return _SAVE_FAILED, "error"


_ACTION_ERRORS = (
    UnknownUser,
    TemplateNotSendable,
    TemplateNotFound,
    CampaignStateError,
    CampaignNotFound,
    ValueError,
    SQLAlchemyError,
)


class WhatsAppCampaignsState(rx.State):
    """State for the Campañas tab."""

    campaigns: list[CampaignRowVM] = []
    loaded_for: str = ""
    loading_for: str = ""
    banner: str = ""
    banner_tone: str = "info"

    # -- detail --------------------------------------------------------------------------
    detail_open: bool = False
    detail_id: str = ""
    detail: CampaignDetailVM = EMPTY_DETAIL
    detail_sends: list[SendVM] = []
    detail_estimate: EstimateVM = EMPTY_ESTIMATE
    detail_has_estimate: bool = False
    detail_loading: bool = False
    detail_banner: str = ""
    detail_banner_tone: str = "info"
    launching: bool = False
    cancelling: bool = False

    # -- wizard --------------------------------------------------------------------------
    wizard_open: bool = False
    flow_ready: bool = False
    step: int = STEP_MESSAGE
    templates: list[TemplateVM] = []
    templates_loading: bool = False
    brand_options: list[OptionVM] = []
    w_name: str = ""
    w_template_id: str = ""
    w_values: dict[str, str] = {}
    w_scope: str = SCOPE_ALL
    w_brand: str = ALL_BRANDS
    w_sources: list[str] = []
    w_from: str = ""
    w_to: str = ""
    w_prefixes: str = ""
    w_pace: str = str(DEFAULT_MAX_PER_MINUTE)
    total_count: int = -1
    audience_count: int = -1
    counting: bool = False
    w_error: str = ""
    w_error_tone: str = "warn"
    w_busy: bool = False
    w_campaign_id: str = ""
    w_estimate: EstimateVM = EMPTY_ESTIMATE
    # Backend-only: template id → (category, Meta components).
    _components: dict[str, Any] = {}
    # Backend-only: what the current draft was created from (reused when unchanged).
    _draft_key: str = ""
    # Backend-only: the business's zone, so a default name never shifts day at night.
    _zone_name: str = "UTC"

    # ==================================================================================
    # Computed vars
    # ==================================================================================

    @rx.var
    def has_campaigns(self) -> bool:
        return len(self.campaigns) > 0

    @rx.var
    def ready(self) -> bool:
        return self.loaded_for != ""

    @rx.var
    def failed(self) -> bool:
        return self.loaded_for == "" and self.loading_for == "" and self.banner != ""

    def _selected(self) -> TemplateVM:
        for template in self.templates:
            if template.template_id == self.w_template_id:
                return template
        return EMPTY_TEMPLATE

    @rx.var
    def selected_template(self) -> TemplateVM:
        return self._selected()

    @rx.var
    def has_sendable_templates(self) -> bool:
        return any(t.sendable for t in self.templates)

    def _variables(self) -> list[Any]:
        _category, components = self._components.get(self.w_template_id, ("", []))
        return send_variables(components)

    @rx.var
    def variable_inputs(self) -> list[VariableFieldVM]:
        return variable_fields(self._variables(), self.w_values)

    def _audience_form(self) -> AudienceForm:
        return audience_form_for(
            scope=self.w_scope,
            since=self.w_from,
            brand_id=self.w_brand,
            sources=self.w_sources,
            until=self.w_to,
            phone_prefixes=self.w_prefixes,
        )

    def _step_problem(self, step: int) -> str:
        if step == STEP_MESSAGE:
            chosen = self._selected()
            problem = validate_basics(self.w_name, chosen if chosen.template_id else None)
            return problem or validate_variables(self._variables(), self.w_values)
        if step == STEP_AUDIENCE:
            problem = validate_scope(self.w_scope, self.w_from)
            if problem:
                return problem
            _json, problem = audience_filter_json(self._audience_form())
            if problem:
                return problem
            if self.counting or self.audience_count < 0:
                return "Contando contactos…"
            if self.audience_count == 0:
                return AUDIENCE_NONE
            return ""
        return ""

    @rx.var
    def step_problem(self) -> str:
        return self._step_problem(self.step)

    @rx.var
    def completed_steps(self) -> list[bool]:
        return [index < self.step for index in range(len(STEPS))]

    @rx.var
    def audience_label(self) -> str:
        return audience_count_label(self.audience_count)

    @rx.var
    def everyone_text(self) -> str:
        return everyone_label(self.total_count)

    @rx.var
    def pace_text(self) -> str:
        """The review's «Se envían de a poco (30 por minuto)…: tarda unos 3 minutos.»"""
        return pace_explanation(self.audience_count, pace_value(self.w_pace))

    @rx.var
    def review_duration(self) -> str:
        """«unos 3 minutos» — the review's «Tarda» tile."""
        return sending_time(self.audience_count, pace_value(self.w_pace)) or "—"

    def _today(self) -> date:
        """Today in the business's own zone (the default name's date)."""
        return datetime.now(ZoneInfo(self._zone_name)).date()

    @rx.var
    def review_name(self) -> str:
        """The name the list will show: «Promoción del 23 de octubre» when left blank."""
        return campaign_name(self.w_name, self._today())

    @rx.var
    def has_more_filters(self) -> bool:
        """A folded filter is in use: «Más filtros» says so on its header."""
        return bool(
            (self.w_brand and self.w_brand != ALL_BRANDS)
            or self.w_sources
            or self.w_to
            or self.w_prefixes.strip()
        )

    @rx.var
    def detail_launched(self) -> bool:
        """The promotion already started: its replies arrive in Chats (N3)."""
        return self.detail.row.status in LAUNCHED

    # ==================================================================================
    # Scope
    # ==================================================================================

    async def _scope(self) -> tuple[str, UUID | None, str]:
        """(connection_id, tenant_id, user email) of the screen."""
        shell = await self.get_state(WhatsAppState)
        auth = await self.get_state(AuthState)
        tenant = tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None
        return shell.selected_connection_id, tenant, auth.user_email

    # ==================================================================================
    # The list
    # ==================================================================================

    @rx.event(background=True)
    async def ensure_loaded(self) -> None:
        await self._load(force=False)

    @rx.event(background=True)
    async def reload(self) -> None:
        await self._load(force=True)

    async def _load(self, *, force: bool) -> None:
        async with self:
            connection_id, tenant_id, _email = await self._scope()
            if not connection_id or self.loading_for == connection_id:
                return
            if not force and self.loaded_for == connection_id:
                return
            if self.loaded_for != connection_id:
                self.campaigns = []
                self.loaded_for = ""
                self.banner = ""
                self.detail_open = False
                self.templates = []
                self.templates_loading = False
                self._components = {}
                self._reset_wizard()
                self.wizard_open = False
                self.flow_ready = False
            self.loading_for = connection_id
        if tenant_id is None:
            async with self:
                self.loading_for = ""
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        try:
            rows = await asyncio.to_thread(campaign_rows, tenant_id, UUID(connection_id))
        except (SQLAlchemyError, CampaignNotFound) as exc:
            logger.error("whatsapp campaigns load failed: %s", type(exc).__name__)
            async with self:
                self.loading_for = ""
                self.banner, self.banner_tone = _LOAD_FAILED, "error"
            return
        async with self:
            current, _tenant, _email = await self._scope()
            self.loading_for = ""
            if current != connection_id:
                return
            self.campaigns = rows
            self.loaded_for = connection_id

    # ==================================================================================
    # Detail
    # ==================================================================================

    @rx.event(background=True)
    async def open_detail(self, campaign_id: str) -> None:
        async with self:
            if campaign_id not in {c.campaign_id for c in self.campaigns}:
                return  # arrived over the wire
            self.detail_id = campaign_id
            self.detail_open = True
            self.detail = EMPTY_DETAIL
            self.detail_sends = []
            self.detail_has_estimate = False
            self.detail_banner = ""
        await self._load_detail()

    @rx.event(background=True)
    async def refresh_detail(self) -> None:
        await self._load_detail()
        await self._load(force=True)

    async def _load_detail(self) -> None:
        async with self:
            if not self.detail_id or self.detail_loading:
                return
            campaign_id = self.detail_id
            self.detail_loading = True
            _connection, tenant_id, _email = await self._scope()
        if tenant_id is None:
            async with self:
                self.detail_loading = False
                self.detail_banner, self.detail_banner_tone = _NO_SESSION, "error"
            return
        try:
            result = await asyncio.to_thread(campaign_detail, tenant_id, UUID(campaign_id))
        except (CampaignNotFound, TemplateNotFound, SQLAlchemyError) as exc:
            logger.error("whatsapp campaign detail failed: %s", type(exc).__name__)
            async with self:
                self.detail_loading = False
                self.detail_banner, self.detail_banner_tone = _DETAIL_FAILED, "error"
            return
        async with self:
            self.detail_loading = False
            if self.detail_id != campaign_id:
                return
            self.detail = result.detail
            self.detail_sends = result.sends
            self.detail_has_estimate = result.estimate is not None
            self.detail_estimate = result.estimate or EMPTY_ESTIMATE

    @rx.event
    def set_detail_open(self, is_open: bool) -> None:
        if not is_open:
            self.detail_open = False
            self.detail_id = ""

    @rx.event(background=True)
    async def launch_campaign(self, campaign_id: str) -> rx.event.EventSpec | None:
        """«Lanzar» — from the wizard's last step or from the detail."""
        async with self:
            if self.launching:
                return
            known = {c.campaign_id for c in self.campaigns} | {self.w_campaign_id}
            if not campaign_id or campaign_id not in known:
                return
            self.launching = True
            self.detail_banner = ""
            self.w_error = ""
            _connection, tenant_id, email = await self._scope()
        if tenant_id is None:
            async with self:
                self.launching = False
                self.detail_banner, self.detail_banner_tone = _NO_SESSION, "error"
            return
        try:
            report = await asyncio.to_thread(launch, tenant_id, UUID(campaign_id), email=email)
        except _ACTION_ERRORS as exc:
            if isinstance(exc, SQLAlchemyError):
                logger.error("whatsapp campaign launch failed: %s", type(exc).__name__)
            async with self:
                self.launching = False
                message, tone = _campaign_error(exc)
                if self.wizard_open:
                    self.w_error, self.w_error_tone = message, tone
                else:
                    self.detail_banner, self.detail_banner_tone = message, tone
            return
        async with self:
            self.launching = False
            self.wizard_open = False
            self.flow_ready = False
            self.detail_id = campaign_id
            self.detail_open = True
            self.detail_banner = launch_message(
                enqueued=report.enqueued, skipped=report.skipped, audience=report.audience
            )
            self.detail_banner_tone = "ok"
        await self._load(force=True)
        await self._load_detail()
        if flow_param(self.router.url.query_parameters, "promocion", len(STEPS)):
            return rx.call_script(close_flow_script("promocion"))
        return None

    @rx.event(background=True)
    async def cancel_campaign(self) -> None:
        async with self:
            if self.cancelling or not self.detail_id:
                return
            campaign_id = self.detail_id
            self.cancelling = True
            self.detail_banner = ""
            _connection, tenant_id, _email = await self._scope()
        if tenant_id is None:
            async with self:
                self.cancelling = False
                self.detail_banner, self.detail_banner_tone = _NO_SESSION, "error"
            return
        try:
            withdrawn = await asyncio.to_thread(cancel, tenant_id, UUID(campaign_id))
        except _ACTION_ERRORS as exc:
            if isinstance(exc, SQLAlchemyError):
                logger.error("whatsapp campaign cancel failed: %s", type(exc).__name__)
            async with self:
                self.cancelling = False
                self.detail_banner, self.detail_banner_tone = _campaign_error(exc)
            return
        async with self:
            self.cancelling = False
            self.detail_banner = _CANCELLED.format(n=withdrawn)
            self.detail_banner_tone = "ok"
        await self._load_detail()
        await self._load(force=True)

    # ==================================================================================
    # Wizard
    # ==================================================================================

    def _reset_wizard(self) -> None:
        self.step = STEP_MESSAGE
        self.w_name = ""
        self.w_template_id = ""
        self.w_values = {}
        self.w_scope = SCOPE_ALL
        self.w_brand = ALL_BRANDS
        self.w_sources = []
        self.w_from = ""
        self.w_to = ""
        self.w_prefixes = ""
        self.w_pace = str(DEFAULT_MAX_PER_MINUTE)
        self.total_count = -1
        self.audience_count = -1
        self._draft_key = ""
        self.w_error = ""
        self.w_busy = False
        self.w_campaign_id = ""
        self.w_estimate = EMPTY_ESTIMATE

    def _apply_flow_step(self) -> None:
        requested = flow_param(self.router.url.query_parameters, "promocion", len(STEPS))
        if not requested:
            return
        target = requested - 1
        for index in range(target):
            if self._step_problem(index):
                target = index
                break
        # Reviewing an existing draft is safe; restoring must never create one.
        if target == STEP_REVIEW and not self.w_campaign_id:
            target = STEP_AUDIENCE
        self.step = target
        self.wizard_open = True
        self.flow_ready = True

    @rx.event
    def restore_flow(self) -> rx.event.EventSpec | None:
        requested = flow_param(self.router.url.query_parameters, "promocion", len(STEPS))
        if not requested:
            self.wizard_open = False
            self.flow_ready = False
            return None
        if self.templates_loading:
            return None
        if not self.templates:
            return WhatsAppCampaignsState.open_wizard
        self._apply_flow_step()
        return None

    @rx.event(background=True)
    async def open_wizard(self) -> None:
        async with self:
            if self.templates_loading:
                return
            self.wizard_open = True
            self.flow_ready = True
            self.templates_loading = True
            connection_id, tenant_id, _email = await self._scope()
        if tenant_id is None or not connection_id:
            async with self:
                self.templates_loading = False
                self.w_error, self.w_error_tone = _NO_SESSION, "error"
            return
        try:
            templates = await asyncio.to_thread(wizard_templates, tenant_id, UUID(connection_id))
            brands = await asyncio.to_thread(brands_for, tenant_id)
            total = await asyncio.to_thread(count_audience, tenant_id, {})
            zone = await asyncio.to_thread(inbox_provider.tenant_zone, tenant_id)
        except (ValueError, SQLAlchemyError) as exc:
            logger.error("whatsapp campaign wizard load failed: %s", type(exc).__name__)
            async with self:
                self.templates_loading = False
                self.w_error, self.w_error_tone = _LOAD_FAILED, "error"
            return
        async with self:
            current, _tenant, _email = await self._scope()
            if current != connection_id:
                return
            self.templates_loading = False
            self.total_count = total
            self._zone_name = zone.key
            self.templates = [t.vm for t in templates]
            self._components = {t.vm.template_id: (t.category, t.components) for t in templates}
            self.brand_options = [
                OptionVM(value=ALL_BRANDS, label="Todas las marcas"),
                *[OptionVM(value=bid, label=name) for bid, name in brands],
            ]
        await self._count()
        async with self:
            self._apply_flow_step()

    @rx.event
    def set_wizard_open(self, is_open: bool) -> rx.event.EventSpec | None:
        if is_open or self.w_busy or self.launching:
            return None
        return self._close_wizard()

    def _close_wizard(self) -> rx.event.EventSpec:
        self.wizard_open = False
        self.flow_ready = False
        if self.w_campaign_id:
            self.banner, self.banner_tone = _DRAFT_SAVED, "info"
        return rx.call_script(close_flow_script("promocion"))

    @rx.event
    def set_w_name(self, value: str) -> None:
        self.w_name = value
        self.w_error = ""

    @rx.event
    def select_template(self, template_id: str) -> None:
        if template_id in {t.template_id for t in self.templates}:
            self.w_template_id = template_id
            self.w_values = {}
            self.w_error = ""

    @rx.event
    def set_value(self, variable: str, value: str) -> None:
        if variable in {f.id for f in variable_fields(self._variables(), {})}:
            self.w_values = {**self.w_values, variable: value}

    @rx.event
    def set_scope(self, value: str) -> rx.event.EventSpec | None:
        """«¿A quién?»: everyone who accepted, or only those who joined since a day."""
        if value in SCOPES and value != self.w_scope:
            self.w_scope = value
            self.w_error = ""
            return WhatsAppCampaignsState.recount
        return None

    @rx.event
    def set_brand(self, value: str) -> rx.event.EventSpec | None:
        if value in {o.value for o in self.brand_options}:
            self.w_brand = value
            return WhatsAppCampaignsState.recount
        return None

    @rx.event
    def toggle_source(self, source: str) -> rx.event.EventSpec | None:
        if source not in SOURCE_KEYS:
            return None
        current = set(self.w_sources)
        current ^= {source}
        self.w_sources = sorted(current)
        return WhatsAppCampaignsState.recount

    @rx.event
    def set_w_from(self, value: str) -> rx.event.EventSpec:
        self.w_from = value
        return WhatsAppCampaignsState.recount

    @rx.event
    def set_w_to(self, value: str) -> rx.event.EventSpec:
        self.w_to = value
        return WhatsAppCampaignsState.recount

    @rx.event
    def set_w_prefixes(self, value: str) -> rx.event.EventSpec:
        self.w_prefixes = value
        return WhatsAppCampaignsState.recount

    @rx.event
    def set_w_pace(self, value: str) -> None:
        if value in PACE_KEYS:
            self.w_pace = value

    @rx.event(background=True)
    async def recount(self) -> None:
        await self._count()

    async def _count(self) -> None:
        """Live opt-ins matching the audience filter. A newer recount wins: the result is
        dropped when the filter changed while this one ran."""
        async with self:
            form = self._audience_form()
            audience, problem = audience_filter_json(form)
            if problem:
                self.audience_count = -1
                self.counting = False
                return
            self.counting = True
            _connection, tenant_id, _email = await self._scope()
        if tenant_id is None:
            async with self:
                self.counting = False
            return
        try:
            count = await asyncio.to_thread(count_audience, tenant_id, audience)
        except (ValueError, SQLAlchemyError) as exc:
            logger.error("whatsapp audience count failed: %s", type(exc).__name__)
            count = -1
        async with self:
            if self._audience_form() != form:
                return
            self.audience_count = count
            self.counting = False

    @rx.event
    def go_to_step(self, index: int) -> None:
        """The stepper: only back to a step already completed (N6: nothing is lost)."""
        if 0 <= index < self.step and not (self.w_busy or self.launching):
            self.step = index
            self.w_error = ""

    @rx.event
    def back(self) -> None:
        """«Atrás» keeps every answer; from «Revisar» the draft stays until something
        changes (see `save_draft`)."""
        if self.step > STEP_MESSAGE and not (self.w_busy or self.launching):
            self.step -= 1
            self.w_error = ""

    @rx.event
    def next_step(self) -> rx.event.EventSpec | None:
        problem = self._step_problem(self.step)
        if problem:
            self.w_error, self.w_error_tone = problem, "warn"
            return None
        self.w_error = ""
        if self.step == STEP_MESSAGE:
            self.step = STEP_AUDIENCE
            return None
        if self.step == STEP_AUDIENCE:
            return WhatsAppCampaignsState.save_draft
        return None

    @rx.event(background=True)
    async def save_draft(self) -> None:
        """«Revisar» from «A quién»: create the draft (or reuse it when nothing changed
        since it was created), then estimate it. Sends nothing (N13)."""
        async with self:
            if self.w_busy:
                return
            for step in (STEP_MESSAGE, STEP_AUDIENCE):
                problem = self._step_problem(step)
                if problem:
                    self.step = step
                    self.w_error, self.w_error_tone = problem, "warn"
                    return
            audience, _problem = audience_filter_json(self._audience_form())
            rate = pace_value(self.w_pace)
            components = build_send_components(self._variables(), self.w_values)
            name = campaign_name(self.w_name, self._today())
            template_id = self.w_template_id
            key = draft_key(template_id, components, audience, rate, self.w_name.strip())
            previous = self.w_campaign_id
            if previous and key == self._draft_key:
                self.step = STEP_REVIEW  # unchanged: same draft, same estimate
                return
            self.w_busy = True
            connection_id, tenant_id, email = await self._scope()
        if tenant_id is None or not connection_id:
            async with self:
                self.w_busy = False
                self.w_error, self.w_error_tone = _NO_SESSION, "error"
            return
        if previous:
            # The answers changed after «Atrás»: the old draft goes, never rewritten.
            try:
                await asyncio.to_thread(cancel, tenant_id, UUID(previous))
            except _ACTION_ERRORS as exc:
                logger.warning("whatsapp stale draft cancel failed: %s", type(exc).__name__)
            async with self:
                self.w_campaign_id = ""
                self._draft_key = ""
        try:
            campaign_id = await asyncio.to_thread(
                lambda: create_draft(
                    tenant_id,
                    UUID(connection_id),
                    email=email,
                    name=name,
                    template_id=UUID(template_id),
                    send_components=components,
                    audience=audience,
                    max_per_minute=rate,
                )
            )
            result = await asyncio.to_thread(estimate, tenant_id, campaign_id)
        except _ACTION_ERRORS as exc:
            if isinstance(exc, SQLAlchemyError):
                logger.error("whatsapp campaign draft failed: %s", type(exc).__name__)
            async with self:
                self.w_busy = False
                self.w_error, self.w_error_tone = _campaign_error(exc)
            return
        async with self:
            self.w_busy = False
            self.w_campaign_id = str(campaign_id)
            self._draft_key = key
            self.w_estimate = result
            self.step = STEP_REVIEW
        await self._load(force=True)

    @rx.event
    def see_replies(self) -> rx.event.EventSpec:
        """«Ver respuestas en Chats» (N3): close the promotion, open the Chats tab."""
        self.detail_open = False
        self.detail_id = ""
        return WhatsAppState.select_tab(TAB_CHATS)

    @rx.event
    def create_approved_message(self) -> list[rx.event.EventSpec]:
        """«Crear un mensaje aprobado» (N3) from the wizard without any: close the
        wizard the way its own close does (a saved draft stays), open «Mensajes
        aprobados»."""
        events: list[rx.event.EventSpec] = []
        if not (self.w_busy or self.launching):
            follow_up = self._close_wizard()
            if follow_up is not None:
                events.append(follow_up)
        events.append(WhatsAppState.select_tab(TAB_TEMPLATES))
        return events
