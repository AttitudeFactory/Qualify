"""Reflex state for `/whatsapp` → Campañas (WA-20, QUA-219): the number's campaigns, the
«Nueva campaña» wizard and the campaign detail.

Holds only the frozen VMs of `whatsapp_campaigns_vm.py` / `whatsapp_templates_vm.py`. The
templates' raw Meta components (needed to know which variables a send must fill) live
in a backend-only var (`_components`) and never reach the browser.

**The wizard** (Plantilla → Variables → Audiencia → Ritmo → Revisar). Steps 1-4 are
local; a step is left only when it is valid, and the reason is shown next to
«Siguiente». Every audience change recounts the live opt-ins in the background
(`build_audience`). Entering «Revisar» saves the campaign as a DRAFT and asks the
service for the estimate (`estimate` needs a campaign) — from then on the wizard can
only launch or close: the draft stays in the list, where it can be launched or cancelled
later. A draft is never silently rewritten.

**Launch** goes through `CampaignService.launch` (resumes, never resends); the sends
leave later through the outbox sender, so Meta's verdicts (codes 131049, 131042…) show
up in the detail on «Actualizar».

Every Postgres call runs in a background event, off-thread.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

import reflex as rx
from qualify_api.whatsapp.campaigns import (
    CampaignNotFound,
    CampaignStateError,
    TemplateNotSendable,
)
from qualify_api.whatsapp.templates import TemplateNotFound
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
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
    DEFAULT_MAX_PER_MINUTE,
    EMPTY_DETAIL,
    EMPTY_ESTIMATE,
    EMPTY_TEMPLATE,
    STEP_AUDIENCE,
    STEP_PACING,
    STEP_REVIEW,
    STEP_TEMPLATE,
    STEP_VARIABLES,
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
    launch_message,
    pacing_hint,
    validate_basics,
    validate_pacing,
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
    "La plantilla ya no está aprobada (o no es de este número). Revisa su estado en "
    "Plantillas y vuelve a intentarlo."
)
_STATE_CHANGED = "La campaña cambió de estado mientras tanto. Actualizamos el detalle."
_GONE = "Esa campaña ya no existe. Actualizamos la lista."
_CANCELLED = "Campaña cancelada: {n} envíos pendientes retirados."
_DRAFT_SAVED = "Campaña guardada como borrador. Lánzala desde la lista cuando quieras."


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
        return "Revisa los datos de la campaña.", "warn"
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
    step: int = STEP_TEMPLATE
    templates: list[TemplateVM] = []
    templates_loading: bool = False
    brand_options: list[OptionVM] = []
    w_name: str = ""
    w_template_id: str = ""
    w_values: dict[str, str] = {}
    w_brand: str = ALL_BRANDS
    w_sources: list[str] = []
    w_from: str = ""
    w_to: str = ""
    w_prefixes: str = ""
    w_rate: str = str(DEFAULT_MAX_PER_MINUTE)
    audience_count: int = -1
    counting: bool = False
    w_error: str = ""
    w_error_tone: str = "warn"
    w_busy: bool = False
    w_campaign_id: str = ""
    w_estimate: EstimateVM = EMPTY_ESTIMATE
    # Backend-only: template id → (category, Meta components).
    _components: dict[str, Any] = {}

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
        return AudienceForm(
            brand_id=self.w_brand,
            sources=tuple(self.w_sources),
            captured_from=self.w_from,
            captured_to=self.w_to,
            phone_prefixes=self.w_prefixes,
        )

    def _step_problem(self, step: int) -> str:
        if step == STEP_TEMPLATE:
            chosen = self._selected()
            return validate_basics(self.w_name, chosen if chosen.template_id else None)
        if step == STEP_VARIABLES:
            return validate_variables(self._variables(), self.w_values)
        if step == STEP_AUDIENCE:
            _json, problem = audience_filter_json(self._audience_form())
            if problem:
                return problem
            if self.counting or self.audience_count < 0:
                return "Contando contactos…"
            if self.audience_count == 0:
                return "Ningún contacto con opt-in activo cumple estos filtros."
            return ""
        if step == STEP_PACING:
            return validate_pacing(self.w_rate)[1]
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
    def pacing_label(self) -> str:
        rate, problem = validate_pacing(self.w_rate)
        return "" if problem else pacing_hint(self.audience_count, rate)

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
                self.wizard_open = False
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
    async def launch_campaign(self, campaign_id: str) -> None:
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
            self.detail_id = campaign_id
            self.detail_open = True
            self.detail_banner = launch_message(
                enqueued=report.enqueued, skipped=report.skipped, audience=report.audience
            )
            self.detail_banner_tone = "ok"
        await self._load(force=True)
        await self._load_detail()

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
        self.step = STEP_TEMPLATE
        self.w_name = ""
        self.w_template_id = ""
        self.w_values = {}
        self.w_brand = ALL_BRANDS
        self.w_sources = []
        self.w_from = ""
        self.w_to = ""
        self.w_prefixes = ""
        self.w_rate = str(DEFAULT_MAX_PER_MINUTE)
        self.audience_count = -1
        self.w_error = ""
        self.w_busy = False
        self.w_campaign_id = ""
        self.w_estimate = EMPTY_ESTIMATE

    @rx.event(background=True)
    async def open_wizard(self) -> None:
        async with self:
            self._reset_wizard()
            self.wizard_open = True
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
        except SQLAlchemyError as exc:
            logger.error("whatsapp campaign wizard load failed: %s", type(exc).__name__)
            async with self:
                self.templates_loading = False
                self.w_error, self.w_error_tone = _LOAD_FAILED, "error"
            return
        async with self:
            self.templates_loading = False
            self.templates = [t.vm for t in templates]
            self._components = {t.vm.template_id: (t.category, t.components) for t in templates}
            self.brand_options = [
                OptionVM(value=ALL_BRANDS, label="Todas las marcas"),
                *[OptionVM(value=bid, label=name) for bid, name in brands],
            ]
        await self._count()

    @rx.event
    def set_wizard_open(self, is_open: bool) -> rx.event.EventSpec | None:
        if is_open or self.w_busy or self.launching:
            return None
        self.wizard_open = False
        if self.w_campaign_id:
            # The draft stays: it is in the list, launchable or cancellable from there.
            self.banner, self.banner_tone = _DRAFT_SAVED, "info"
            self._reset_wizard()
            return WhatsAppCampaignsState.reload
        self._reset_wizard()
        return None

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
    def set_w_rate(self, value: str) -> None:
        self.w_rate = value

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
        """The stepper: only back to a step already completed, and never out of «Revisar»
        (the draft exists from there on)."""
        if 0 <= index < self.step and self.step != STEP_REVIEW:
            self.step = index
            self.w_error = ""

    @rx.event
    def back(self) -> None:
        if STEP_TEMPLATE < self.step < STEP_REVIEW:
            self.step -= 1
            self.w_error = ""

    @rx.event
    def next_step(self) -> rx.event.EventSpec | None:
        problem = self._step_problem(self.step)
        if problem:
            self.w_error, self.w_error_tone = problem, "warn"
            return None
        self.w_error = ""
        if self.step == STEP_TEMPLATE and not self._variables():
            self.step = STEP_AUDIENCE  # nothing to fill: skip «Variables»
            return None
        if self.step < STEP_PACING:
            self.step += 1
            return None
        if self.step == STEP_PACING:
            return WhatsAppCampaignsState.save_draft
        return None

    @rx.event(background=True)
    async def save_draft(self) -> None:
        """«Siguiente» on «Ritmo»: create the draft, then estimate it."""
        async with self:
            if self.w_busy or self.w_campaign_id:
                return
            for step in (STEP_TEMPLATE, STEP_VARIABLES, STEP_AUDIENCE, STEP_PACING):
                problem = self._step_problem(step)
                if problem:
                    self.step = step
                    self.w_error, self.w_error_tone = problem, "warn"
                    return
            audience, _problem = audience_filter_json(self._audience_form())
            rate, _ = validate_pacing(self.w_rate)
            components = build_send_components(self._variables(), self.w_values)
            name = self.w_name.strip()
            template_id = self.w_template_id
            self.w_busy = True
            connection_id, tenant_id, email = await self._scope()
        if tenant_id is None or not connection_id:
            async with self:
                self.w_busy = False
                self.w_error, self.w_error_tone = _NO_SESSION, "error"
            return
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
            self.w_estimate = result
            self.step = STEP_REVIEW
        await self._load(force=True)
