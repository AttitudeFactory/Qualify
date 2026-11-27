"""«¿Cuánto te conviene pagar por un cliente?» (m-25091387): five questions about the
business, the result, and the one-time offer before the first «Promocionar».

The view is chosen by the address: `?paso=N` shows a step (all five, or the one a
«Cambiar» opened); no `paso` shows the result, or step 1 while nothing is saved;
`?oferta=1` (sent by `offer_gate`) shows the offer. `?volver=` is the wizard to go back to.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from urllib.parse import urlencode
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.ads.investment_profile import CURRENCY_UNSUPPORTED, InvestmentProfileUnavailable
from qualify_api.tenancy.acting import acting_login

from .auth_state import AuthState
from .creative_state import CreativeState
from .investment_profile_provider import brand_for, load_profile, save_profile, should_offer
from .investment_profile_vm import (
    LOAD_FAILED,
    NO_SESSION,
    PROFILE_ROUTE,
    REVIEW_MARGIN,
    SAVE_FAILED,
    SAVED_NOTICE,
    STEP_TITLES,
    TOTAL_STEPS,
    ProfileAnswersVM,
    ProfileVM,
    amount_echo,
    answer_rows,
    answers_from,
    cap_echo,
    card_title,
    first_problem,
    headline,
    how_computed,
    margin_options,
    meaning,
    money_copy,
    read_amount,
    safe_return,
    step_problem,
    unknown_note,
    whole_money,
    with_answer,
)
from .nav_url import scalar_param, with_query
from .tenant import tenant_uuid
from .ui import go_to_step, settle_step
from .ui.steps_vm import guard_step, parse_step_param, step_direction

logger = logging.getLogger(__name__)

STEPS = "steps"  # walking the five questions
EDIT = "edit"  # one question opened from the result's «Cambiar»


class InvestmentProfileState(rx.State):
    profile: ProfileVM = ProfileVM()
    answers: ProfileAnswersVM = ProfileAnswersVM()
    supported: bool = True
    loading: bool = True
    busy: bool = False
    error: str = ""
    reason: str = ""
    notice: str = ""
    step: int = 1
    direction: str = "next"
    mode: str = ""
    offer: bool = False
    return_to: str = ""
    _context: tuple[str, str, str] = ("", "", "")
    _brand: str = ""
    _operation: str = ""
    _offer_skipped: bool = False
    _offer_settled: tuple[str, str, str] = ("", "", "")

    # -- what the page shows -------------------------------------------------

    @rx.var
    def title(self) -> str:
        return STEP_TITLES[max(0, min(self.step - 1, TOTAL_STEPS - 1))]

    @rx.var
    def showing_steps(self) -> bool:
        return self.mode != "" or (
            not self.loading and self.supported and not self.profile.exists and not self.offer
        )

    @rx.var
    def showing_offer(self) -> bool:
        return self.offer and self.mode == "" and not self.loading and not self.profile.exists

    @rx.var
    def back_label(self) -> str:
        if self.mode == EDIT:
            return "Tu resultado"
        return "Tu anuncio" if self.return_to else "Anuncios"

    @rx.var
    def primary_label(self) -> str:
        if self.mode == EDIT:
            return "Guardar"
        return "Ver mi resultado" if self.step == TOTAL_STEPS else "Siguiente"

    @rx.var
    def ticket_echo(self) -> str:
        return amount_echo(self.answers.ticket, self.profile.currency)

    @rx.var
    def cap_echo(self) -> str:
        return cap_echo(self.answers.cap, self.profile.currency)

    @rx.var
    def margin_help(self) -> str:
        price, problem = read_amount(self.answers.ticket)
        of = "De" if problem else f"De los {whole_money(price, self.profile.currency)}"
        return (
            f"{of} lo que paga un cliente, ¿cuánto te queda después de pagar lo que cuesta "
            "hacerlo o conseguirlo?"
        )

    @rx.var
    def unknown_note(self) -> str:
        return unknown_note(self.answers.ticket, self.profile.currency)

    @rx.var
    def margin_choices(self) -> list[tuple[str, str]]:
        return margin_options(self.answers.ticket, self.profile.currency)

    @rx.var
    def money_copy(self) -> dict[str, str]:
        return money_copy(self.profile.currency)

    @rx.var
    def headline(self) -> str:
        return headline(self.profile)

    @rx.var
    def card_title(self) -> str:
        return card_title(self.profile)

    @rx.var
    def meaning(self) -> str:
        return meaning(self.profile)

    @rx.var
    def how_computed(self) -> str:
        return how_computed(self.profile)

    @rx.var
    def answer_rows(self) -> list[tuple[int, str, str]]:
        return answer_rows(self.profile) if self.profile.exists else []

    @rx.var
    def unsupported_message(self) -> str:
        return CURRENCY_UNSUPPORTED

    # -- session -------------------------------------------------------------

    async def _session(self) -> tuple[str, str, str]:
        auth = await self.get_state(AuthState)
        return auth.session_tenant_id, auth._auth_user_id, auth._session_user_id

    async def _cached_brand(self) -> str:
        creative = await self.get_state(CreativeState)
        return creative._brand_id

    def _reset(self, context: tuple[str, str, str]) -> None:
        self.profile, self.answers = ProfileVM(), ProfileAnswersVM()
        self.supported, self.mode, self.step = True, "", 1
        self.error = self.reason = self.notice = ""
        self._brand, self._context = "", context
        self._offer_skipped, self._offer_settled = False, ("", "", "")

    def _params(self) -> dict[str, str]:
        return {"volver": self.return_to} if self.return_to else {}

    # -- loading -------------------------------------------------------------

    @rx.event(background=True)
    async def load(self) -> None:
        """`/promotions/perfil` and the Anuncios list (its card). Leaves the answers
        alone while a flow is open."""
        async with self:
            context = await self._session()
            if context != self._context:
                self._reset(context)
            cached = await self._cached_brand()
            self._operation = operation = str(uuid4())
            self.loading, self.error = True, ""
        if not all(tenant_uuid(value) for value in context):
            async with self:
                if self._operation == operation:
                    self.error, self.loading = NO_SESSION, False
            return
        try:
            with acting_login(UUID(context[1])):
                brand = await asyncio.to_thread(brand_for, UUID(context[0]), cached)
                if brand is None:
                    raise InvestmentProfileUnavailable(LOAD_FAILED)
                profile, supported = await asyncio.to_thread(load_profile, UUID(context[0]), brand)
        except Exception as exc:
            logger.warning("investment profile load failed: %s", type(exc).__name__)
            async with self:
                if self._operation == operation:
                    self.error = (
                        str(exc) if isinstance(exc, InvestmentProfileUnavailable) else LOAD_FAILED
                    )
                    self.loading = False
            return
        async with self:
            if self._operation == operation and context == await self._session():
                self._brand, self.profile, self.supported = str(brand), profile, supported
                if self.mode == "":
                    self.answers = answers_from(profile)
                self.loading = False

    @rx.event
    def read_step(self) -> rx.event.EventSpec:
        """The address → the view; idempotent (on_load and «atrás» may both run it)."""
        params = self.router.url.query_parameters
        self.return_to = safe_return(scalar_param(params, "volver"))
        self.offer = scalar_param(params, "oferta") == "1"
        raw = scalar_param(params, "paso")
        if not raw:
            self.mode, self.step, self.reason = "", 1, ""
            return settle_step()
        requested = parse_step_param(raw, TOTAL_STEPS)
        target = guard_step(
            requested, [not step_problem(self.answers, n) for n in range(1, TOTAL_STEPS + 1)]
        )
        self.mode = self.mode or STEPS
        self.direction = step_direction(self.step, target, self.direction)
        if target != self.step:
            self.reason = ""
        self.step = target
        return settle_step()

    # -- the questions -------------------------------------------------------

    @rx.event
    def answer(self, name: str, value: str) -> None:
        if not self.busy:
            self.answers = with_answer(self.answers, name, value)
            self.reason = ""

    @rx.event
    def start(self) -> rx.event.EventSpec:
        """«Responder (1 minuto)» on the offer, or «Calcularlo» again."""
        self.mode, self.step, self.direction = STEPS, 1, "next"
        self.offer, self.reason, self.notice = False, "", ""
        return go_to_step(PROFILE_ROUTE, 1, **self._params())

    @rx.event
    def change(self, step: int) -> rx.event.EventSpec | None:
        """«Cambiar» on one answer: only that step, its primary saves."""
        if self.busy or not self.profile.exists or not 1 <= step <= TOTAL_STEPS:
            return None
        self.answers = answers_from(self.profile)
        self.mode, self.step, self.direction = EDIT, step, "next"
        self.reason = self.notice = self.error = ""
        return go_to_step(PROFILE_ROUTE, step, **self._params())

    @rx.event
    def next_step(self) -> rx.event.EventSpec | None:
        if self.busy or self.loading:
            return None
        self.reason = step_problem(self.answers, self.step)
        if self.reason:
            return None
        price_changed = read_amount(self.answers.ticket)[0] != self.profile.ticket
        if (
            self.mode == EDIT
            and self.step == 2
            and price_changed
            and self.answers.margin_choice in {"low", "mid", "high", "top"}
        ):
            # the range was over the old price: show what it means now before saving
            self.step, self.direction, self.notice = 3, "next", REVIEW_MARGIN
            return go_to_step(PROFILE_ROUTE, 3, **self._params())
        if self.mode == EDIT or self.step == TOTAL_STEPS:
            return InvestmentProfileState.save
        self.step, self.direction, self.notice = self.step + 1, "next", ""
        return go_to_step(PROFILE_ROUTE, self.step, **self._params())

    @rx.event
    def back_step(self) -> rx.event.EventSpec | None:
        if self.busy or self.mode == EDIT:
            return None
        self.step = max(1, self.step - 1)
        self.direction, self.reason = "back", ""
        return go_to_step(PROFILE_ROUTE, self.step, back=True, **self._params())

    @rx.event
    def leave(self) -> rx.event.EventSpec | None:
        """«‹ …» in the head: an edit goes back to the result; the questions go back to
        where the owner came from. What was written stays (N6)."""
        if self.busy:
            return None
        if self.mode == EDIT:
            self.mode, self.reason, self.notice = "", "", ""
            return rx.redirect(with_query(PROFILE_ROUTE, **self._params()), replace=True)
        # back to the wizard counts as «Ahora no»: the offer does not come back
        self._offer_skipped = self._offer_skipped or bool(self.return_to)
        return rx.redirect(self.return_to or "/promotions")

    @rx.event(background=True)
    async def save(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            context = await self._session()
            if self.busy or self.loading or context != self._context:
                return
            if not self._brand:
                self.error = LOAD_FAILED
                return
            step, reason = first_problem(self.answers)
            if step:
                self.step, self.reason, self.direction = step, reason, "back"
                yield go_to_step(PROFILE_ROUTE, step, **self._params())
                return
            snapshot, brand, edit = self.answers, self._brand, self.mode == EDIT
            self._operation = operation = str(uuid4())
            self.busy, self.error, self.notice = True, "", ""
        try:
            with acting_login(UUID(context[1])):
                saved = await asyncio.to_thread(
                    save_profile, UUID(context[0]), UUID(brand), snapshot
                )
        except Exception as exc:
            logger.warning("investment profile save failed: %s", type(exc).__name__)
            async with self:
                if self._operation == operation:
                    self.busy = False
                    self.error = (
                        str(exc) if isinstance(exc, InvestmentProfileUnavailable) else SAVE_FAILED
                    )
            return
        async with self:
            if self._operation != operation:
                return
            self.profile, self.answers = saved, answers_from(saved)
            self.mode, self.busy, self.reason = "", False, ""
            self.notice = SAVED_NOTICE if edit else ""
            target = with_query(PROFILE_ROUTE, **self._params())
        yield rx.redirect(target, replace=True)

    # -- the offer before the first «Promocionar» ----------------------------

    @rx.event
    async def offer_gate(self) -> rx.event.EventSpec | None:
        """On the wizard's route: a brand with no profile and no promotion yet is
        offered the questions once per session first. Never blocks promoting: any
        failure lets the wizard open."""
        params = self.router.url.query_parameters
        if scalar_param(params, "paso"):
            return None
        context = await self._session()
        if self._offer_skipped or self._offer_settled == context:
            return None
        if not all(tenant_uuid(value) for value in context):
            return None
        cached = await self._cached_brand()
        try:
            with acting_login(UUID(context[1])):
                brand = await asyncio.to_thread(brand_for, UUID(context[0]), cached)
                offer = brand is not None and await asyncio.to_thread(
                    should_offer, UUID(context[0]), brand
                )
        except Exception as exc:
            logger.warning("investment profile offer check failed: %s", type(exc).__name__)
            return None
        if not offer:
            self._offer_settled = context
            return None
        query = urlencode({key: scalar_param(params, key) for key in params})
        back = safe_return(self.router.url.path + (f"?{query}" if query else ""))
        return rx.redirect(with_query(PROFILE_ROUTE, oferta="1", volver=back))

    @rx.event
    def skip_offer(self) -> rx.event.EventSpec:
        """«Ahora no, seguir con el anuncio»: no more offers this session; the Anuncios
        card stays. No dismissal is stored (the first promotion ends the offer)."""
        self._offer_skipped, self.offer = True, False
        return rx.redirect(self.return_to or "/promotions")
