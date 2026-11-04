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
from qualify_api.ads.wizard import WizardUnavailable
from qualify_api.tenancy.acting import acting_login

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

    def _invalidate_review(self) -> None:
        self.review = PromotionReviewVM()
        self.reviewed = False
        self.confirm_charge = False
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
                self.form, age_min="18", age_max="65", gender="all", interests=[], radius_km=""
            )
            self.interest_results = []
        self.error = ""
        self._invalidate_audience()
        return PromotionState.refresh_reach()

    @rx.event
    def accept_charge(self, value: bool) -> None:
        self.confirm_charge = (
            bool(value) if self.has_remote_review and not self.busy and not self.success else False
        )

    @rx.event
    def choose_source(self, source_id: str) -> rx.event.EventSpec | None:
        if self.busy:
            return
        source = next((row for row in self.sources if row.id == source_id), None)
        if source is None:
            return
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
            **({"start_local": "", "end_local": ""} if changed_zone else {}),
        )
        self.timezone_name = zone
        self.error = ""
        self._audience_version = 0
        self.place_query = ""
        self.interest_query = ""
        self.place_results = []
        self.interest_results = []
        self._invalidate_audience()
        return (
            PromotionState.restore_audience()
            if source.ad_account_id and not source.health.blocks_preparation
            else None
        )

    @rx.event
    def choose_another_source(self) -> None:
        if self.busy:
            return
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
        if self.busy or self.loading or not self.sources or self.preparation_blocked:
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
                # Keep the route discoverable: a blocked account opens its explanation
                # and Meta action instead of silently removing the owner's next step.
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
            if (
                self._loaded_context == context
                and self._piece_id == str(piece)
                and self.sources
                and params.get("paso")
            ):
                self.read_step()
                return
            self.sources = []
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
                    load_sources, UUID(context[0]), piece, event_id, True
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
        source = next((row for row in self.sources if row.id == self.form.source_id), None)
        if source and source.ad_account_id and not source.health.blocks_preparation:
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
                or not self.reviewed
                or self.success
                or self.preparation_blocked
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
