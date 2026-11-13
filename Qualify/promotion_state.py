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
from qualify_api.ads.audience import AudienceUnavailable
from qualify_api.ads.unpublished import UnpublishedUnavailable
from qualify_api.ads.wizard import WizardUnavailable
from qualify_api.tenancy.acting import acting_login

from .ad_custom_audiences_provider import read_custom_audiences, request_custom_audience
from .ad_custom_audiences_vm import (
    AUDIENCE_KIND_LABELS,
    CustomAudienceCatalogVM,
    CustomAudienceVM,
    audience_choices,
    creation_problem,
    selection_label,
)
from .ad_enhancements_vm import AVAILABILITY_NOTICE, BrandEnhancementsVM, permission_summary
from .auth_state import AuthState
from .planner_vm import back_to_week_href
from .promotion_audience_provider import (
    audience_scope,
    find_interests,
    find_places,
    read_reach,
    read_saved_audience,
    store_audience,
    suggest_interests,
)
from .promotion_audience_vm import (
    GENDER_LABELS,
    PLACEMENT_LABELS,
    AudienceInterestVM,
    AudiencePlaceVM,
    AudienceReachVM,
    placements_label,
)
from .promotion_provider import (
    confirm_review,
    load_sources,
    prepare_preview,
    ready_lead_forms,
    recheck_enhancement_permissions,
    recheck_messaging_destinations,
)
from .promotion_unpublished_provider import confirm_unpublished, prepare_unpublished
from .promotion_vm import (
    CONFIRM_FAILED,
    COUNTRY_LABELS,
    LEAD_CTA_LABELS,
    LOAD_FAILED,
    NO_SESSION,
    PREVIEW_FAILED,
    STORY_FORMAT,
    STORY_REVIEW_TITLE,
    UNPUBLISHED_SOURCE_TITLE,
    WEBSITE_CTA_LABELS,
    AdMediaVM,
    PromotionCheckVM,
    PromotionDraftVM,
    PromotionResultVM,
    PromotionReviewVM,
    PromotionSourceVM,
    cop_label,
    first_problem,
    promotion_checks,
    promotion_result,
    readable_date,
    step_count,
    step_counter,
    step_keys,
    step_problem,
    step_title,
    video_outcome,
    zone_label,
)
from .tenant import tenant_uuid
from .ui import go_to_step, settle_step
from .ui.steps_vm import guard_step, parse_step_param, step_direction

logger = logging.getLogger(__name__)


class PromotionState(rx.State):
    sources: list[PromotionSourceVM] = []
    form: PromotionDraftVM = PromotionDraftVM()
    review: PromotionReviewVM = PromotionReviewVM()
    result: PromotionResultVM = PromotionResultVM()
    checks: list[PromotionCheckVM] = []
    step: int = 1
    direction: str = "next"
    timezone_name: str = ""
    loading: bool = False
    busy: bool = False
    error: str = ""
    success: str = ""
    reviewed: bool = False
    confirm_charge: bool = False
    # m-24828982: Meta is still processing a video (repeat the same preparation), or an
    # upload is uncertain (ask for help; never offer to send it again).
    video_waiting: bool = False
    needs_help: bool = False
    covers_open: bool = False
    entry_available: bool = False
    entry_unpublished: bool = False
    # m-25026350: opened as «Agregar un botón con enlace» (`?formato=historia`).
    story_entry: bool = False
    back_href: str = "/drafts"
    back_label: str = "Por aprobar"
    _loaded_context: tuple[str, str, str] = ("", "", "")
    _piece_id: str = ""
    _request_key: str = ""
    _operation: str = ""
    _return_params: dict[str, str] = {}
    _tenant_timezone: str = ""
    place_query: str = ""
    interest_query: str = ""
    place_results: list[AudiencePlaceVM] = []
    interest_results: list[AudienceInterestVM] = []
    audience_reach: AudienceReachVM = AudienceReachVM()
    audience_notice: str = ""
    audience_error: str = ""
    audience_working: str = ""
    reach_loading: bool = False
    _audience_revision: str = ""
    _audience_search: str = ""
    _audience_version: int = 0
    _reach_operation: str = ""
    destinations_working: bool = False
    forms_working: bool = False
    destinations_notice: str = ""
    _destination_operation: str = ""
    enhancements_working: bool = False
    enhancements_notice: str = ""
    _enhancements_operation: str = ""
    custom_catalog: CustomAudienceCatalogVM = CustomAudienceCatalogVM()
    custom_working: bool = False
    custom_creating: bool = False
    custom_error: str = ""
    custom_notice: str = ""
    custom_name: str = ""
    custom_kind: str = "engagement"
    custom_retention: str = "365"
    custom_seed: str = ""
    custom_country: str = "CO"
    custom_confirmed: bool = False
    _custom_operation: str = ""
    _custom_request_key: str = ""

    @rx.var
    def custom_choices(self) -> list[CustomAudienceVM]:
        return audience_choices(self.custom_catalog.audiences, self.form.housing)

    @rx.var
    def custom_seed_choices(self) -> list[CustomAudienceVM]:
        return [
            row
            for row in self.custom_catalog.audiences
            if row.available and row.kind in {"engagement", "messages"}
        ]

    @rx.var
    def custom_selection_label(self) -> str:
        return selection_label(self.form.custom_audiences)

    @rx.var
    def custom_creation_enabled(self) -> bool:
        return self.custom_catalog.terms_accepted and self.custom_catalog.creation_available

    def _reset_custom_audiences(self) -> None:
        self.custom_catalog = CustomAudienceCatalogVM()
        self.custom_working = False
        self.custom_creating = False
        self.custom_error = ""
        self.custom_notice = ""
        self.custom_name = ""
        self.custom_kind = "engagement"
        self.custom_retention = "365"
        self.custom_seed = ""
        self.custom_country = "CO"
        self.custom_confirmed = False
        self._custom_operation = str(uuid4())
        self._custom_request_key = str(uuid4())

    @rx.event
    def custom_edit(self, name: str, value: str) -> None:
        if self.busy or self.custom_working:
            return
        if name == "kind":
            if value not in AUDIENCE_KIND_LABELS or (self.form.housing and value == "lookalike"):
                return
            self.custom_kind = value
            if value != "lookalike":
                self.custom_seed = ""
        elif name == "name":
            self.custom_name = value
        elif name == "retention" and value in {"30", "90", "180", "365", "730"}:
            self.custom_retention = value
        elif name == "seed" and any(row.local_id == value for row in self.custom_seed_choices):
            self.custom_seed = value
        elif name == "country" and value in {"CO", "VE", "UY"}:
            self.custom_country = value
        else:
            return
        self.custom_confirmed = False
        self.custom_error = ""
        self.custom_notice = ""
        self._custom_request_key = str(uuid4())

    @rx.event
    def confirm_custom_creation(self, checked: bool) -> None:
        if not self.busy and not self.custom_working:
            self.custom_confirmed = bool(checked) and self.custom_creation_enabled

    @rx.event
    def choose_custom_audience(self, local_id: str) -> rx.event.EventSpec | None:
        if self.busy or self.custom_working or not self.custom_catalog.terms_accepted:
            return None
        row = next((row for row in self.custom_choices if row.local_id == local_id), None)
        if row is None or not row.available:
            return None
        self.form = replace(self.form, custom_audiences=[row])
        self._invalidate_audience()
        return PromotionState.refresh_reach()

    @rx.event
    def remove_custom_audience(self) -> rx.event.EventSpec | None:
        if self.busy or self.custom_working:
            return None
        self.form = replace(self.form, custom_audiences=[])
        self._invalidate_audience()
        return PromotionState.refresh_reach()

    @rx.event(background=True)
    async def refresh_custom_audiences(self) -> None:
        await self._custom_audience_action(create=False)

    @rx.event(background=True)
    async def create_custom_audience(self) -> None:
        await self._custom_audience_action(create=True)

    async def _custom_audience_action(self, *, create: bool) -> None:
        async with self:
            if self.busy or self.loading or self.custom_working:
                return
            context = await self._session()
            try:
                scope = self._audience_scope(context)
            except ValueError:
                self.custom_error = "Vuelve a abrir la promoción para consultar sus públicos."
                return
            if create:
                if not self.custom_creation_enabled or not self.custom_confirmed:
                    self.custom_error = (
                        "Consulta los públicos y confirma la creación antes de seguir."
                    )
                    return
                problem = creation_problem(
                    name=self.custom_name,
                    kind=self.custom_kind,
                    retention=self.custom_retention,
                    seed_id=self.custom_seed,
                    country=self.custom_country,
                    housing=self.form.housing,
                )
                if problem:
                    self.custom_error = problem
                    return
            self._custom_operation = operation = str(uuid4())
            piece, source, account = self._piece_id, self.form.source_id, scope["ad_account_id"]
            payload = {
                "name": self.custom_name,
                "kind": self.custom_kind,
                "retention_days": int(self.custom_retention),
                "seed_id": self.custom_seed,
                "country": self.custom_country,
                "request_key": self._custom_request_key or str(uuid4()),
                "confirmed": self.custom_confirmed,
            }
            self._custom_request_key = payload["request_key"]
            self.custom_working = True
            self.custom_creating = create
            self.custom_error = ""
            self.custom_notice = ""
        try:
            with acting_login(UUID(context[1])):
                result = await asyncio.to_thread(
                    request_custom_audience if create else read_custom_audiences,
                    scope,
                    **(payload if create else {}),
                )
        except Exception as exc:
            logger.warning("custom audience action failed: %s", type(exc).__name__)
            result = None
            error = (
                str(exc)
                if isinstance(exc, AudienceUnavailable)
                else "No pudimos comprobar el público. Vuelve a consultar antes de intentarlo."
            )
        else:
            error = ""
        async with self:
            if (
                context != await self._session()
                or self._piece_id != piece
                or self.form.source_id != source
                or operation != self._custom_operation
                or not any(
                    row.id == source and row.ad_account_id == str(account) for row in self.sources
                )
            ):
                return
            self.custom_working = False
            self.custom_creating = False
            self.custom_error = error
            if result is None:
                self.custom_catalog = replace(
                    self.custom_catalog, terms_accepted=False, creation_available=False
                )
                if self.form.custom_audiences:
                    self.form = replace(
                        self.form,
                        custom_audiences=[
                            replace(row, available=False) for row in self.form.custom_audiences
                        ],
                    )
                    self._invalidate_audience()
            if isinstance(result, CustomAudienceCatalogVM):
                self.custom_catalog = result
                choices = {row.local_id: row for row in self.custom_choices if row.available}
                selected = [
                    choices.get(row.local_id, replace(row, available=False))
                    if result.terms_accepted
                    else replace(row, available=False)
                    for row in self.form.custom_audiences
                ]
                if selected != self.form.custom_audiences:
                    self.form = replace(self.form, custom_audiences=selected)
                    self._invalidate_audience()
                self.custom_confirmed = False
            elif isinstance(result, CustomAudienceVM):
                self.custom_catalog = replace(
                    self.custom_catalog,
                    audiences=[
                        row
                        for row in self.custom_catalog.audiences
                        if row.local_id != result.local_id
                    ]
                    + [result],
                )
                self.custom_confirmed = False
                self.custom_notice = (
                    "Tu público está listo. Elígelo para usarlo en esta promoción."
                    if result.available
                    else (
                        result.notice + " "
                        if result.notice
                        else "Meta todavía prepara este público. "
                    )
                    + "Consulta su estado antes de elegirlo."
                )

    def _invalidate_enhancements(self) -> None:
        self._enhancements_operation = str(uuid4())
        self.enhancements_working = False
        self.enhancements_notice = ""

    async def _enhancements_current(
        self, context: tuple[str, str, str], piece: str, source: str, brand: str, operation: str
    ) -> bool:
        return (
            context == await self._session()
            and piece == self._piece_id
            and source == self.form.source_id
            and brand == self.selected_source.brand_id
            and operation == self._enhancements_operation
        )

    @rx.event(background=True)
    async def recheck_enhancements(self) -> None:
        async with self:
            context = await self._session()
            if self.busy or self.loading or self.enhancements_working:
                return
            if context != self._loaded_context or not all(tenant_uuid(value) for value in context):
                return
            piece, source, brand = (
                self._piece_id,
                self.form.source_id,
                self.selected_source.brand_id,
            )
            if not all(tenant_uuid(value) for value in (piece, source, brand)):
                return
            self._invalidate_review()
            self._enhancements_operation = operation = str(uuid4())
            self.enhancements_working = True
            self.enhancements_notice = ""
        try:
            with acting_login(UUID(context[1])):
                policy = await asyncio.to_thread(
                    recheck_enhancement_permissions,
                    UUID(context[0]),
                    UUID(piece),
                    UUID(source),
                    UUID(brand),
                )
        except Exception as exc:
            logger.warning("promotion permissions refresh failed: %s", type(exc).__name__)
            async with self:
                if await self._enhancements_current(context, piece, source, brand, operation):
                    self.form = replace(self.form, enhancements=BrandEnhancementsVM())
                    self.sources = [
                        replace(row, enhancements=BrandEnhancementsVM())
                        if row.brand_id == brand
                        else row
                        for row in self.sources
                    ]
                    self.enhancements_notice = (
                        "No pudimos consultar los permisos. Vuelve a intentarlo antes de preparar."
                    )
        else:
            async with self:
                if await self._enhancements_current(context, piece, source, brand, operation):
                    self.form = replace(self.form, enhancements=policy)
                    self.sources = [
                        replace(row, enhancements=policy) if row.brand_id == brand else row
                        for row in self.sources
                    ]
                    self.enhancements_notice = (
                        "Permisos actualizados. Revisa el resumen "
                        "antes de preparar otra vista previa."
                    )
        finally:
            async with self:
                if await self._enhancements_current(context, piece, source, brand, operation):
                    self.enhancements_working = False

    def _invalidate_destinations(self) -> None:
        self._destination_operation = str(uuid4())
        self.destinations_working = False
        self.destinations_notice = ""

    async def _destination_current(
        self,
        context: tuple[str, str, str],
        piece: str,
        source: str,
        connection: str,
        operation: str,
    ) -> bool:
        return (
            context == await self._session()
            and self._piece_id == piece
            and self.form.source_id == source
            and self.selected_source.connection_id == connection
            and self._destination_operation == operation
        )

    @rx.event(background=True)
    async def recheck_destinations(self) -> None:
        async with self:
            context = await self._session()
            source = self.selected_source
            if self.busy or self.loading or self.destinations_working:
                return
            if context != self._loaded_context or not all(tenant_uuid(value) for value in context):
                self.destinations_notice = NO_SESSION
                return
            piece, source_id, connection = self._piece_id, source.id, source.connection_id
            if not all(tenant_uuid(value) for value in (piece, source_id, connection)):
                return
            self._destination_operation = operation = str(uuid4())
            self.destinations_working = True
            self.destinations_notice = ""
        try:
            with acting_login(UUID(context[1])):
                options = await asyncio.to_thread(
                    recheck_messaging_destinations,
                    UUID(context[0]),
                    UUID(piece),
                    UUID(source_id),
                    UUID(connection),
                )
        except Exception as exc:
            logger.warning("promotion destinations read failed: %s", type(exc).__name__)
            async with self:
                if await self._destination_current(
                    context, piece, source_id, connection, operation
                ):
                    self.destinations_notice = (
                        str(exc)
                        if isinstance(exc, WizardUnavailable)
                        else "No pudimos comprobar los destinos. Vuelve a intentarlo."
                    )
        else:
            async with self:
                if await self._destination_current(
                    context, piece, source_id, connection, operation
                ):
                    self.sources = [
                        replace(row, messaging_destinations=options)
                        if row.id == source_id and row.connection_id == connection
                        else row
                        for row in self.sources
                    ]
                    self.destinations_notice = "Comprobación terminada. Revisa cada destino."
        finally:
            async with self:
                if await self._destination_current(
                    context, piece, source_id, connection, operation
                ):
                    self.destinations_working = False

    @rx.var
    def audience_places_label(self) -> str:
        return placements_label(self.form.placement_mode, self.form.placements)

    @rx.var
    def audience_location_label(self) -> str:
        return " · ".join(
            value
            for value in (
                self.form.city_name,
                self.form.location_region,
                self.form.location_country,
            )
            if value
        )

    @rx.var
    def audience_interests_label(self) -> str:
        if self.form.housing:
            return "No se eligen intereses para vivienda"
        return ", ".join(row.label for row in self.form.interests) or "Sin intereses elegidos"

    @rx.var
    def audience_people_label(self) -> str:
        if self.form.housing:
            return "Todas las edades y géneros permitidos por Meta para vivienda"
        upper = "65 o más" if self.form.age_max == "65" else self.form.age_max
        return f"{self.form.age_min} a {upper} años · " + GENDER_LABELS.get(
            self.form.gender, "Todas las personas"
        )

    def _invalidate_audience(self) -> None:
        self._audience_revision = str(uuid4())
        self.audience_reach = AudienceReachVM(
            label="La estimación debe actualizarse con tu elección."
        )
        self.reach_loading = False
        self._reach_operation = str(uuid4())
        self.audience_notice = ""
        self.audience_error = ""
        self._invalidate_review()

    def _audience_scope(self, context: tuple[str, str, str]) -> dict[str, UUID]:
        if context != self._loaded_context or not all(tenant_uuid(value) for value in context):
            raise ValueError("missing authenticated audience context")
        source = next((row for row in self.sources if row.id == self.form.source_id), None)
        if source is None or not source.ad_account_id:
            raise AudienceUnavailable(
                "Elige una cuenta para anuncios en Tus redes y vuelve a intentarlo."
            )
        return audience_scope(context[0], self._piece_id, source.id, source.ad_account_id)

    @rx.event
    def audience_edit(self, name: str, value: str) -> rx.event.EventSpec | None:
        if self.busy:
            return None
        if name == "place_query":
            self.place_query = value
            self.place_results = []
            self.form = replace(
                self.form, city_name="", location_key="", location_country="", location_region=""
            )
        elif name == "interest_query":
            self.interest_query = value
            self.interest_results = []
            self._audience_search = str(uuid4())
            return None
        elif name == "location_kind" and value in {"city", "region", "country"}:
            self.form = replace(
                self.form, location_kind=value, location_key="", city_name="", radius_km=""
            )
            self.place_results = []
        elif name == "gender" and value in GENDER_LABELS and not self.form.housing:
            self.form = replace(self.form, gender=value)
        elif name == "placement_mode" and value in {"automatic", "manual"}:
            self.form = replace(self.form, placement_mode=value, placements=[])
        else:
            return None
        self._invalidate_audience()
        return PromotionState.refresh_reach()

    @rx.event
    def choose_place(self, key: str) -> rx.event.EventSpec | None:
        place = next((row for row in self.place_results if row.key == key), None)
        if self.busy or place is None:
            return None
        self.form = replace(
            self.form,
            city_name=place.label,
            location_key=place.key,
            location_kind=place.kind,
            location_country=place.country,
            location_region=place.region,
            radius_km="",
        )
        self.place_query = place.label
        self.place_results = []
        self._invalidate_audience()
        return PromotionState.refresh_reach()

    @rx.event
    def choose_interest(self, interest_id: str) -> rx.event.EventSpec | None:
        row = next((item for item in self.interest_results if item.id == interest_id), None)
        if (
            self.busy
            or self.form.housing
            or row is None
            or row.id in {item.id for item in self.form.interests}
        ):
            return None
        self.form = replace(self.form, interests=[*self.form.interests, row])
        self.interest_results = []
        self.interest_query = ""
        self._invalidate_audience()
        return PromotionState.refresh_reach()

    @rx.event
    def remove_interest(self, interest_id: str) -> rx.event.EventSpec | None:
        if self.busy:
            return None
        self.form = replace(
            self.form, interests=[row for row in self.form.interests if row.id != interest_id]
        )
        self._invalidate_audience()
        return PromotionState.refresh_reach()

    @rx.event
    def placement(self, key: str, checked: bool) -> rx.event.EventSpec | None:
        if self.busy or key not in PLACEMENT_LABELS or self.form.placement_mode != "manual":
            return None
        selected = set(self.form.placements)
        selected.add(key) if checked else selected.discard(key)
        self.form = replace(self.form, placements=sorted(selected))
        self._invalidate_audience()
        return PromotionState.refresh_reach()

    @rx.event(background=True)
    async def search_places(self) -> None:
        await self._search_audience("places")

    @rx.event(background=True)
    async def search_interests(self) -> None:
        await self._search_audience("interests")

    @rx.event(background=True)
    async def suggest_interests(self) -> None:
        await self._search_audience("suggestions")

    async def _search_audience(self, kind: str) -> None:
        async with self:
            if self.busy or (kind != "places" and self.form.housing):
                return
            context = await self._session()
            revision = self._audience_revision
            self._audience_search = request = str(uuid4())
            form = self.form
            query = self.place_query if kind == "places" else self.interest_query
            self.audience_working = (
                "Consultando lugares…" if kind == "places" else "Consultando intereses…"
            )
            self.audience_error = ""
        try:
            scope = self._audience_scope(context)
            with acting_login(UUID(context[1])):
                rows = (
                    await asyncio.to_thread(find_places, scope, query, form.location_kind)
                    if kind == "places"
                    else await asyncio.to_thread(suggest_interests, scope, form)
                    if kind == "suggestions"
                    else await asyncio.to_thread(find_interests, scope, query)
                )
        except Exception as exc:
            logger.warning("audience search failed: %s", type(exc).__name__)
            async with self:
                if (
                    context == await self._session()
                    and request == self._audience_search
                    and revision == self._audience_revision
                ):
                    self.audience_error = (
                        str(exc)
                        if isinstance(exc, AudienceUnavailable)
                        else "No pudimos consultar las opciones de Meta. Vuelve a intentarlo."
                    )
        else:
            async with self:
                if (
                    context == await self._session()
                    and request == self._audience_search
                    and revision == self._audience_revision
                ):
                    if kind == "places":
                        self.place_results = rows
                    else:
                        self.interest_results = rows
                    if not rows:
                        self.audience_notice = "No encontramos resultados. Prueba con otro nombre."
        finally:
            async with self:
                if context == await self._session() and request == self._audience_search:
                    self.audience_working = ""

    @rx.event(background=True)
    async def refresh_reach(self) -> None:
        async with self:
            context = await self._session()
            revision = self._audience_revision
            if self.busy or not self.form.location_key or step_problem(self.form, 3):
                return
            form = self.form
            self.reach_loading = True
            self._reach_operation = operation = str(uuid4())
        try:
            scope = self._audience_scope(context)
            with acting_login(UUID(context[1])):
                estimate = await asyncio.to_thread(read_reach, scope, form)
        except Exception as exc:
            logger.warning("audience estimate failed: %s", type(exc).__name__)
            estimate = AudienceReachVM(
                label="No pudimos consultar la estimación. Vuelve a intentarlo."
            )
        async with self:
            if (
                context == await self._session()
                and revision == self._audience_revision
                and operation == self._reach_operation
            ):
                self.audience_reach = estimate
                self.reach_loading = False

    @rx.event(background=True)
    async def restore_audience(self) -> None:
        await self._persist_audience(save=False)

    @rx.event(background=True)
    async def save_audience(self) -> None:
        await self._persist_audience(save=True)

    async def _persist_audience(self, *, save: bool) -> None:
        async with self:
            context = await self._session()
            if self.busy or (save and step_problem(self.form, 3)):
                if save:
                    self.audience_error = step_problem(self.form, 3)
                return
            revision = self._audience_revision
            form, version = self.form, self._audience_version
            self.audience_error = ""
            self.audience_working = (
                "Guardando tu público…" if save else "Buscando tu público guardado…"
            )
            self.busy = True
        try:
            scope = self._audience_scope(context)
            with acting_login(UUID(context[1])):
                result = (
                    await asyncio.to_thread(store_audience, scope, form, version)
                    if save
                    else await asyncio.to_thread(read_saved_audience, scope)
                )
        except Exception as exc:
            logger.warning("audience persistence failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and revision == self._audience_revision:
                    self.audience_error = (
                        str(exc)
                        if isinstance(exc, AudienceUnavailable)
                        else "No pudimos guardar o recuperar el público. Vuelve a intentarlo."
                    )
        else:
            async with self:
                if context == await self._session() and revision == self._audience_revision:
                    if save:
                        self._audience_version = result
                        self.audience_notice = (
                            "Público guardado en Qualify. Esto no crea ni activa un anuncio."
                        )
                    elif result:
                        changes, self._audience_version = result
                        self.form = replace(self.form, **changes)
                        self.place_query = self.form.city_name
                        self._invalidate_audience()
                        revision = self._audience_revision
                        self.audience_notice = (
                            "Recuperamos tu público guardado. "
                            "Revisa la elección antes de continuar."
                        )
                    else:
                        self.audience_notice = (
                            "Todavía no guardaste un público para esta publicación. "
                            "Elígelo y toca Guardar público para después."
                        )
        finally:
            async with self:
                if context == await self._session() and revision == self._audience_revision:
                    self.busy = False
                    self.audience_working = ""
        async with self:
            refresh = (
                not save
                and context == await self._session()
                and revision == self._audience_revision
            )
        if refresh:
            await PromotionState.refresh_reach.fn(self)

    @rx.var
    def title(self) -> str:
        if self.preparation_blocked:
            return "Revisa tu cuenta antes de promocionar"
        if self.reviewed:
            if self.form.story:
                return STORY_REVIEW_TITLE
            return "Revisa tu anuncio antes de autorizarlo"
        if (
            self.step <= 1
            and any(row.media_kind for row in self.sources)
            and step_keys(self.form)[0] == "source"
        ):
            return UNPUBLISHED_SOURCE_TITLE
        return step_title(self.form, self.step)

    @rx.var
    def step_total(self) -> int:
        return step_count(self.form)

    @rx.var
    def display_total(self) -> int:
        return step_counter(self.form, self._offered(), self.step, self.reviewed)[1]

    @rx.var
    def display_step(self) -> int:
        return step_counter(self.form, self._offered(), self.step, self.reviewed)[0]

    def _offered(self) -> PromotionDraftVM:
        if not self.sources:
            return self.form
        return replace(
            PromotionDraftVM(), **_unpublished_defaults(self.sources[0], len(self.sources) == 1)
        )

    def _media(self, rows: list[AdMediaVM], asset_id: str) -> AdMediaVM:
        return next((row for row in rows if row.id == asset_id), AdMediaVM(id=""))

    @rx.var
    def chosen_feed(self) -> AdMediaVM:
        return self._media(self.selected_source.feed_media, self.form.feed_asset_id)

    @rx.var
    def chosen_vertical(self) -> AdMediaVM:
        return self._media(self.selected_source.vertical_media, self.form.vertical_asset_id)

    @rx.var
    def chosen_feed_cover(self) -> AdMediaVM:
        return self._media(self.selected_source.feed_covers, self.form.feed_cover_id)

    @rx.var
    def chosen_vertical_cover(self) -> AdMediaVM:
        return self._media(self.selected_source.vertical_covers, self.form.vertical_cover_id)

    @rx.event
    def toggle_covers(self) -> None:
        if not self.busy:
            self.covers_open = not self.covers_open

    @rx.var
    def zone_label(self) -> str:
        return zone_label(self.timezone_name)

    @rx.var
    def step_key(self) -> str:
        keys = step_keys(self.form)
        return keys[min(max(self.step, 1), len(keys)) - 1]

    @rx.var
    def is_unpublished(self) -> bool:
        return self.form.media_kind != ""

    @rx.var
    def country_label(self) -> str:
        return COUNTRY_LABELS.get(self.form.country, "Por elegir")

    @rx.var
    def selected_source(self) -> PromotionSourceVM:
        return next(
            (row for row in self.sources if row.id == self.form.source_id),
            PromotionSourceVM(id="", account_label="", caption=""),
        )

    @rx.var
    def execution_reason(self) -> str:
        if self.selected_source.unavailable_reason:
            return self.selected_source.unavailable_reason
        if self.form.source_id and not self.form.enhancements.loaded:
            return "Vuelve a consultar los permisos de esta marca antes de preparar el anuncio."
        return ""

    @rx.var
    def enhancement_summary(self) -> str:
        return permission_summary(self.form.enhancements)

    @rx.var
    def enhancement_notice(self) -> str:
        if not self.form.enhancements.loaded:
            return "Falta consultar los permisos guardados de esta marca. No se supondrán apagados."
        if any(self.form.enhancements.values.values()):
            return AVAILABILITY_NOTICE
        return "Se pedirá a Meta mantener apagados los cuatro cambios de imagen, texto y botón."

    @rx.var
    def preparation_blocked(self) -> bool:
        return self.selected_source.health.blocks_preparation

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

    @rx.var
    def paid_operation_locked(self) -> bool:
        return bool(self.result.status)

    @rx.var
    def piece_href(self) -> str:
        piece = tenant_uuid(self._piece_id)
        return f"/drafts/{piece}" if piece else "/drafts"

    @rx.var
    def promotion_status_href(self) -> str:
        reference = self.result.promotion_id or self.review.promotion_id
        promotion_id = tenant_uuid(reference)
        return f"/promotions/{promotion_id}" if promotion_id else "/promotions"

    @rx.var
    def checks_block_confirmation(self) -> bool:
        return any(check.status != "verified" for check in self.checks)

    def _invalidate_review(self) -> None:
        self.review = PromotionReviewVM()
        self.checks = []
        self.reviewed = False
        self.confirm_charge = False
        self.video_waiting = False
        self.needs_help = False
        if not getattr(self, "result", PromotionResultVM()).status:
            self.success = ""
            self._request_key = str(uuid4())

    @rx.event
    def edit(self, name: str, value: str) -> rx.event.EventSpec | None:
        if self.busy or name not in {
            "link_url",
            "radius_km",
            "age_min",
            "age_max",
            "budget",
            "start_local",
            "end_local",
            "message",
            "headline",
        }:
            return
        if getattr(self.form, name) != value:
            self.form = replace(self.form, **{name: value})
            self.error = ""
            self._invalidate_review()
            if name in {"radius_km", "age_min", "age_max"}:
                self._invalidate_audience()
                return PromotionState.refresh_reach()
        return None

    @rx.event
    def option(self, name: str, value: bool) -> rx.event.EventSpec | None:
        if self.busy or name not in {"housing", "advantage_audience"}:
            return
        self.form = replace(self.form, **{name: value})
        if name == "housing" and value:
            self.form = replace(
                self.form,
                age_min="18",
                age_max="65",
                gender="all",
                interests=[],
                radius_km="",
                custom_audiences=[
                    row for row in self.form.custom_audiences if row.kind != "lookalike"
                ],
            )
            self.interest_results = []
            if getattr(self, "custom_kind", "engagement") == "lookalike":
                self.custom_kind = "engagement"
                self.custom_seed = ""
                self.custom_confirmed = False
                self._custom_request_key = str(uuid4())
        self.error = ""
        self._invalidate_audience()
        return PromotionState.refresh_reach()

    @rx.event
    def choose_goal(self, goal: str) -> None:
        if self.busy or goal not in {"visit", "lead"} or goal == self.form.goal:
            return
        self.form = replace(self.form, goal=goal)
        self.error = ""
        self._invalidate_review()

    @rx.event
    def choose_lead_form(self, form_id: str) -> None:
        if self.busy or not any(row.id == form_id for row in self.selected_source.lead_forms):
            return
        self.form = replace(self.form, lead_form_id=form_id)
        self.error = ""
        self._invalidate_review()

    @rx.event(background=True)
    async def refresh_lead_forms(self) -> None:
        """After creating a form elsewhere: re-read this account's ready forms only,
        keeping everything else the owner already chose."""
        async with self:
            context = await self._session()
            source = self.selected_source
            if self.busy or self.loading or self.forms_working:
                return
            if context != self._loaded_context or not all(tenant_uuid(v) for v in context):
                return
            connection = tenant_uuid(source.connection_id)
            if connection is None:
                return
            self.forms_working = True
        try:
            with acting_login(UUID(context[1])):
                forms, problem = await asyncio.to_thread(
                    ready_lead_forms, UUID(context[0]), connection
                )
        finally:
            async with self:
                self.forms_working = False
        async with self:
            if context != await self._session() or self.form.source_id != source.id:
                return
            self.sources = [
                # A failed read keeps the forms already shown, so the choice survives.
                replace(
                    row, lead_forms=row.lead_forms if problem else forms, lead_forms_error=problem
                )
                if row.id == source.id
                else row
                for row in self.sources
            ]
            if not problem and not any(row.id == self.form.lead_form_id for row in forms):
                self.form = replace(self.form, lead_form_id=forms[0].id if forms else "")
                self._invalidate_review()

    @rx.event
    def choose_lead_cta(self, code: str) -> None:
        if self.busy or code not in LEAD_CTA_LABELS:
            return
        self.form = replace(self.form, lead_cta=code)
        self.error = ""
        self._invalidate_review()

    @rx.event
    def choose_cta(self, code: str) -> None:
        if self.busy or code not in WEBSITE_CTA_LABELS:
            return
        self.form = replace(self.form, cta_type=code)
        self.error = ""
        self._invalidate_review()

    @rx.var
    def lead_form_label(self) -> str:
        return next(
            (
                row.name
                for row in self.selected_source.lead_forms
                if row.id == self.form.lead_form_id
            ),
            "Por elegir",
        )

    @rx.var
    def button_label(self) -> str:
        if self.form.goal == "lead":
            return LEAD_CTA_LABELS.get(self.form.lead_cta, "Por elegir")
        return WEBSITE_CTA_LABELS.get(self.form.cta_type, "Por elegir")

    @rx.event
    def accept_charge(self, value: bool) -> None:
        self.confirm_charge = (
            bool(value)
            if self.has_remote_review
            and not self.busy
            and not self.success
            and not getattr(self, "result", PromotionResultVM()).status
            and not any(check.status != "verified" for check in self.checks)
            else False
        )

    @rx.event
    def choose_source(self, source_id: str) -> rx.event.EventSpec | None:
        if self.busy:
            return
        source = next((row for row in self.sources if row.id == source_id), None)
        if source is None:
            return
        self._invalidate_destinations()
        self._invalidate_enhancements()
        PromotionState._reset_custom_audiences(self)
        zone = source.timezone_name or self._tenant_timezone
        changed_zone = zone != self.timezone_name
        self.form = replace(
            PromotionDraftVM(
                budget=self.form.budget,
                start_local=self.form.start_local,
                end_local=self.form.end_local,
            ),
            source_id=source.id,
            link_url=source.default_link_url,
            cta_type=source.default_cta_type,
            lead_form_id=source.lead_forms[0].id if source.lead_forms else "",
            enhancements=source.enhancements,
            **({"start_local": "", "end_local": ""} if changed_zone else {}),
            **_unpublished_defaults(source, len(self.sources) == 1),
        )
        self.timezone_name = zone
        self.error = ""
        self._audience_version = 0
        self.place_query = ""
        self.interest_query = ""
        self.place_results = []
        self.interest_results = []
        self._invalidate_audience()
        self._invalidate_review()
        return (
            PromotionState.restore_audience()
            if source.ad_account_id
            and not source.health.blocks_preparation
            and not source.media_kind
            else None
        )

    @rx.event
    def choose_media(self, slot: str, asset_id: str) -> None:
        """One of the piece's own files for a slot; never an id outside its lists."""
        source = self.selected_source
        lists = {
            "feed_asset_id": source.feed_media,
            "vertical_asset_id": source.vertical_media,
            "feed_cover_id": source.feed_covers,
            "vertical_cover_id": source.vertical_covers,
        }
        if self.busy or slot not in lists or not any(row.id == asset_id for row in lists[slot]):
            return
        if getattr(self.form, slot) != asset_id:
            self.form = replace(self.form, **{slot: asset_id})
            self.error = ""
            # «Cambiar portada» lives in the summary: drop Meta's review but stay there.
            stay = slot.endswith("_cover_id") and self.reviewed
            self._invalidate_review()
            self.reviewed = stay

    @rx.event
    def choose_country(self, code: str) -> None:
        if self.busy or code not in COUNTRY_LABELS or code == self.form.country:
            return
        self.form = replace(self.form, country=code)
        self.error = ""
        self._invalidate_review()

    @rx.event
    def choose_another_source(self) -> None:
        if self.busy:
            return
        self._invalidate_destinations()
        self._invalidate_enhancements()
        PromotionState._reset_custom_audiences(self)
        self.form = replace(self.form, source_id="")
        self._invalidate_audience()
        self.step = 1
        self.error = ""
        self._invalidate_review()

    @rx.event
    def recheck_health(self) -> rx.event.EventSpec | None:
        if self.busy or self.loading:
            return None
        self._loaded_context = ("", "", "")
        return PromotionState.load()

    def _step_completeness(self) -> list[bool]:
        return [
            not step_problem(self.form, n, self.timezone_name)
            for n in range(1, step_count(self.form) + 1)
        ]

    @rx.event
    def read_step(self) -> rx.event.EventSpec:
        params = self.router.url.query_parameters
        last = step_count(self.form)
        target = guard_step(parse_step_param(params.get("paso"), last), self._step_completeness())
        self.direction = step_direction(self.step, target, self.direction)
        reviewed = (
            target == last
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
        if self.busy or self.loading or not self.sources or self.preparation_blocked:
            return None
        problem = step_problem(self.form, self.step, self.timezone_name)
        if problem:
            self.error = problem
            return None
        self.error = ""
        last = step_count(self.form)
        if self.step >= last:
            self.reviewed = True
            self.confirm_charge = False
            return go_to_step(
                f"/drafts/{self._piece_id}/promote", last, revision="1", **self._return_params
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
                f"/drafts/{self._piece_id}/promote",
                step_count(self.form),
                back=True,
                **self._return_params,
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
            self.entry_unpublished = False
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
                # Keep the route discoverable: a blocked account opens its explanation
                # and Meta action instead of silently removing the owner's next step.
                self.entry_available = bool(rows)
                self.entry_unpublished = any(row.media_kind for row in rows)

    @rx.event(background=True)
    async def load(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            context = await self._session()
            piece = tenant_uuid(str(getattr(self, "draft_id", "")))
            params = dict(self.router.url.query_parameters)
            # m-25026350: «Agregar un botón con enlace» from Tu semana's historia.
            story = params.get("formato") == STORY_FORMAT
            if piece is None or not all(tenant_uuid(value) for value in context):
                self.loading = False
                self.error = NO_SESSION if piece else LOAD_FAILED
                return
            if (
                self._loaded_context == context
                and self._piece_id == str(piece)
                and self.sources
                and self.sources[0].story == story
                and params.get("paso")
            ):
                self.read_step()
                return
            self.sources = []
            self.result = PromotionResultVM()
            self._invalidate_destinations()
            self._invalidate_enhancements()
            PromotionState._reset_custom_audiences(self)
            self.form = PromotionDraftVM()
            self.place_query = ""
            self.interest_query = ""
            self.place_results = []
            self.interest_results = []
            self.audience_working = ""
            self._audience_version = 0
            self._invalidate_audience()
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
                for key in ("desde", "semana", "vista", "evento", "formato")
                if params.get(key)
            }
            week = back_to_week_href(params)
            self.story_entry = story
            self.back_href = week or f"/drafts/{piece}"
            self.back_label = "Tu semana" if week else "Revisar publicación"
            event_id = tenant_uuid(str(params.get("evento", "")))
        try:
            with acting_login(UUID(context[1])):
                rows, zone = await asyncio.to_thread(
                    load_sources, UUID(context[0]), piece, event_id, True, story
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
                if rows and rows[0].media_kind and self.back_label != "Tu semana":
                    self.back_label = "Revisar pieza"  # never published: one name, «pieza»
                self.covers_open = False
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
        source = next((row for row in self.sources if row.id == self.form.source_id), None)
        if (
            source
            and source.ad_account_id
            and not source.health.blocks_preparation
            and not source.media_kind
        ):
            yield PromotionState.restore_audience()

    @rx.event(background=True)
    async def create_preview(self) -> None:
        await self._remote(confirm=False)

    @rx.event(background=True)
    async def confirm(self) -> None:
        await self._remote(confirm=True)

    async def _remote(self, *, confirm: bool) -> None:
        async with self:
            context = await self._session()
            if (
                self.busy
                or self.loading
                or self.enhancements_working
                or not self.reviewed
                or self.success
                or getattr(self, "result", PromotionResultVM()).status
                or self.preparation_blocked
                or (getattr(self, "needs_help", False) and not confirm)
            ):
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
            if confirm and any(check.status != "verified" for check in self.checks):
                self.confirm_charge = False
                self.error = "Resuelve las comprobaciones pendientes antes de autorizar el gasto."
                return
            self.busy = True
            self.error = ""
            self._operation = operation = str(uuid4())
            form, zone, review = self.form, self.timezone_name, self.review
            source = next((row for row in self.sources if row.id == form.source_id), None)
            piece, request_key = self._piece_id, self._request_key
        try:
            with acting_login(UUID(context[1])):
                if confirm and form.media_kind:
                    outcome = await asyncio.to_thread(
                        confirm_unpublished, UUID(context[0]), UUID(context[2]), review
                    )
                elif confirm:
                    outcome = await asyncio.to_thread(
                        confirm_review, UUID(context[0]), UUID(context[2]), review, True
                    )
                elif form.media_kind:
                    # A video Meta is still processing: the SAME key repeats the
                    # preparation and never uploads it again.
                    prepared = await asyncio.to_thread(
                        prepare_unpublished,
                        UUID(context[0]),
                        UUID(piece),
                        UUID(context[2]),
                        form,
                        source,
                        zone,
                        request_key,
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
                if (
                    context == await self._session()
                    and operation == self._operation
                    and form == self.form
                    and piece == self._piece_id
                    and source
                    == next((row for row in self.sources if row.id == form.source_id), None)
                ):
                    self.checks = promotion_checks(
                        getattr(exc, "diagnostics", ())
                        if isinstance(exc, WizardUnavailable)
                        else ()
                    )
                    self.confirm_charge = False
                    readable = isinstance(exc, WizardUnavailable | UnpublishedUnavailable)
                    if confirm and not readable:
                        self.result = promotion_result(None, review.promotion_id)
                    self.error = (
                        str(exc) if readable else CONFIRM_FAILED if confirm else PREVIEW_FAILED
                    )
                    outcome_kind = (
                        video_outcome(exc)
                        if isinstance(exc, UnpublishedUnavailable) and not confirm
                        else ""
                    )
                    self.video_waiting = outcome_kind == "waiting"
                    self.needs_help = outcome_kind == "help"
                    if self.video_waiting:
                        self.error = ""
        else:
            async with self:
                if (
                    context == await self._session()
                    and operation == self._operation
                    and form == self.form
                    and piece == self._piece_id
                    and source
                    == next((row for row in self.sources if row.id == form.source_id), None)
                ):
                    if confirm:
                        self.result = outcome
                        self.success = outcome.message if outcome.status == "active" else ""
                        self.confirm_charge = False
                    elif form.enhancements == self.form.enhancements:
                        self.video_waiting = False
                        self.review = prepared
                        self.checks = prepared.checks
                        self.confirm_charge = False
        finally:
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.busy = False


def _unpublished_defaults(
    source: PromotionSourceVM, single_source: bool = False
) -> dict[str, str | bool]:
    """Prefill a piece's own pair: its first 4:5 and 9:16 files and, for videos, the
    first image of each format as the cover. Everything stays visible and changeable.
    A story ad (m-25026350) uses only the 9:16 file; a single source is not a step."""
    if not source.media_kind:
        return {}

    def first(rows: list) -> str:
        return rows[0].id if rows else ""

    return {
        "media_kind": source.media_kind,
        "single_feed": len(source.feed_media) == 1,
        "single_vertical": len(source.vertical_media) == 1,
        "feed_asset_id": first(source.feed_media),
        "vertical_asset_id": first(source.vertical_media),
        "feed_cover_id": first(source.feed_covers),
        "vertical_cover_id": first(source.vertical_covers),
        "message": source.default_message,
        "headline": source.default_headline,
        "country": source.default_country,
        "story": source.story,
        "single_source": single_source and source.story,
    }
