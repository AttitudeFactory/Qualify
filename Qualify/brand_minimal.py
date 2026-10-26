"""/brand — «Tu marca» in five steps (m-24848529, MARCA-4).

The founder's decision 6 (2026-10-23): the mandatory Brand Kit is five named steps —
① Tus redes (with «No tengo redes») ② Tu negocio y rubro ③ Tu logo ④ Tus colores
⑤ Cómo hablas — and finishing them unlocks the app (`brand_finish.save_brand_kit`
marks the kit finished and sets `AuthState.brand_kit_complete`). Typography, banned
words, the recorded voice and the referentes are «Mejora tu marca (opcional)»: they
live in the Brand Kit editor (/brand/kit) and in the old flows, still routable.

This page replaces the old «¿Tienes redes sociales?» fork. Every control is the old
wizards' own renderer on the same `CreativeState` / `BrandWizardState` /
`BrandConnectState` fields, so a draft started in either old flow is read back as it was
(`BrandWizardState.load_saved_assets`, `BrandConnectState.load_saved_details`), and the
step it resumes on is mapped by name (`brand_minimal_vm.step_from_progress`). Only the
cursor and the one example phrase are this module's (`BrandMinimalState`).

Architect review (2026-10-23): Tus redes first; `persist_brand_kit(adopt_voice=True)`
after step 5 (what `save_brand_kit` does); progress by step name; no ADR.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import reflex as rx
from qualify_api.creative.brand_prefill_review import PrefillReview, owner_started, review_of
from sqlalchemy.exc import SQLAlchemyError

from . import brand_answers_vm as answers_vm
from . import brand_documents
from . import brand_minimal_vm as vm
from . import brand_proposal_vm as proposal_vm
from .auth_state import AuthState, brand_tenant_id
from .brand_answers import BrandAnswersState, answers_body, answers_header
from .brand_proposal import BrandProposalState, approved_notice, proposal_review, read_notice
from .creative_state import CreativeState
from .creative_wizard_pages import (  # the wizards' own controls, shared on purpose
    _BRANDBOARD_COLUMN_MAX,
    _CONTROL_RADIUS,
    _FINISH_DRAFT_LABEL,
    _FINISH_LABEL,
    _LOGO_VERSION_ACCEPT,
    _PALETTE_VERSION_ORDER,
    COUNTRY_OPTIONS,
    HAS_LOGO_PROFILE,
    LOGO_SOURCE_PROFILE,
    BrandConnectState,
    BrandWizardState,
    _asset_src,
    _brand_extras,
    _brand_ready_card,
    _change_email_button,
    _choice_card,
    _connect_loading,
    _connect_step_account,
    _connect_step_profile,
    _explain_finish_failure,
    _finish_navigation,
    _labeled_area,
    _labeled_input,
    _loading_view,
    _logo_step_complete,
    _logo_versions,
    _profile_avatar,
    _progress_trigger,
    _remove_button,
    _select_field,
    _step_body,
    _step_logo,
    _step_palette,
    _tone_sliders,
    _wizard_shell,
    exit_label,
    leave_flow,
    step_param,
)
from .tenant import tenant_uuid
from .ui import (
    callout,
    card,
    dropzone,
    page_body,
    page_header,
    step_foot,
    step_frame,
    step_head,
    step_sync,
)
from .ui import tokens as T
from .ui.steps_vm import DIR_NEXT, NEXT_LABEL, guard_step, parse_step_param, step_direction

logger = logging.getLogger(__name__)

#: Where a finished kit goes from /brand: the editor, as before (m-24848529 keeps it).
_EDITOR_ROUTE = "/brand/kit"

#: Tu logo's answers (value, title, blurb) — one screen: answering opens the upload or
#: the three questions right below, without a «siguiente paso».
_LOGO_ANSWERS: tuple[tuple[str, str, str], ...] = (
    ("si", "Sí, ya tengo logo", "Súbelo aquí y lo usamos tal cual."),
    ("no", "Todavía no tengo", "Cuéntanos en tres preguntas cómo te lo imaginas."),
)
_LOGO_FROM_PROFILE = (
    HAS_LOGO_PROFILE,
    "Usar mi foto de perfil",
    "Tomamos tu logo y tus colores de la foto de tu cuenta.",
)

#: Cómo hablas' one example (the ticket's exact question): it fills `do_examples`, so
#: the kit can be read for its voice (`readiness`: at least one example).
_PHRASE_LABEL = "¿Cómo le dirías a un cliente que llegó el combo nuevo?"
_PHRASE_PLACEHOLDER = "Ej.: ¡Llegó el combo nuevo! Pásate hoy y pruébalo."

#: Tu logo on «Sí» (UX review): ONE upload. It fills the version the palette reads
#: first (`_PALETTE_VERSION_ORDER`); the four versions and «Otros elementos» wait
#: behind «Tengo otras versiones de mi logo (opcional)».
_MAIN_LOGO_VERSION = _PALETTE_VERSION_ORDER[0]
_MAIN_LOGO_UPLOAD_ID = "brand_minimal_logo"

#: Countries Tu negocio y rubro can name (`account_country`).
_KNOWN_COUNTRIES = frozenset(code for code, _name in COUNTRY_OPTIONS)


class BrandMinimalState(rx.State):
    """The five steps' cursor (a step NAME, `brand_minimal_vm.STEP_NAMES`) and the one
    example phrase. Every kit field stays where it was (`CreativeState`), with the logo
    files in `BrandWizardState` and the social account and rubro in `BrandConnectState`."""

    step: str = vm.FIRST_STEP
    #: Cómo hablas' phrase, mirrored into `CreativeState.kit_do_examples` on every change.
    phrase: str = ""
    #: `enter` finished deciding the step: until then the page shows its loading card,
    #: so an owner coming back never sees Tus redes flash before their own step.
    entered: bool = False
    #: Tu logo: the four versions and «Otros elementos» are open (behind a soft button).
    more_logo_versions: bool = False
    #: Tu negocio y rubro: país and ciudad are open (behind «Más opciones»).
    show_place: bool = False
    #: The account's country (a session only), put back when a read profile is forgotten.
    account_country: str = ""
    #: `data-dir` of the step frame's body (PASOS-4): the side the next step comes from.
    direction: str = DIR_NEXT
    #: `enter` decided the step on THIS visit: only then may `step_sync` write the
    #: address (cleared when the frame unmounts, `leave_frame`).
    synced: bool = False
    _entry_hydrated: bool = False
    #: Why the owner is here when another page sent them (`?desde=`, N1): «Para usar
    #: Por responder, primero termina tu marca…». Cleared on the first step change.
    gate_notice: str = ""

    @rx.var
    def step_number(self) -> int:
        """0-based position."""
        return vm.step_index(self.step)

    @rx.var
    def n(self) -> int:
        """«Paso N de 5» and `?paso=N`: the 1-based position (every step is visible)."""
        return vm.step_index(self.step) + 1

    @rx.var
    def is_last(self) -> bool:
        return self.step == vm.LAST_STEP

    async def _live_facts(self) -> vm.KitFacts:
        """What the session holds now, as `KitFacts` (the browser's «atrás» decides on
        it, not on the database)."""
        connect = await self.get_state(BrandConnectState)
        wizard = await self.get_state(BrandWizardState)
        creative = await self.get_state(CreativeState)
        return vm.KitFacts(
            socials_answered=bool(connect.profile_username) or connect.started_without_socials,
            rubro=connect.rubro_text,
            positioning=creative.kit_positioning,
            audience=creative.kit_audience,
            has_logo_answer=vm.logo_answered(
                wizard.has_logo,
                has_files=bool(wizard.logo_versions or wizard.brand_extras),
                brief=wizard.logo_brief_1,
                from_profile=HAS_LOGO_PROFILE,
            ),
            palette=creative.kit_palette,
            example=self.phrase,
        )

    def _go(self, name: str) -> None:
        if name != self.step:
            self.gate_notice = ""
        self.direction = step_direction(
            vm.step_index(self.step) + 1, vm.step_index(name) + 1, self.direction
        )
        self.step = name

    @rx.event
    def leave_frame(self) -> None:
        """The frame unmounted: the next visit's first render must not write this
        visit's step into the address (`step_sync`)."""
        self.synced = False

    @rx.event
    async def pop_step(self) -> None:
        """The browser's «atrás»/«adelante» (`step_frame(on_pop=...)`): the step in
        `?paso=`, never past the first step still unanswered (`steps_vm.guard_step`).
        Idempotent: `enter` may answer the same «atrás» too."""
        raw = step_param(self)
        if raw is None or not self.entered:
            return
        requested = parse_step_param(raw, vm.TOTAL_STEPS)
        target = guard_step(requested, vm.step_completes(await self._live_facts()))
        self._go(vm.STEP_NAMES[target - 1])

    @rx.event(background=True)
    async def persist_progress(self) -> None:
        """Fired on every step change (`_progress_trigger`): the half-written kit and the
        step's NAME go to the database (`brand_finish.save_progress`)."""
        from .brand_finish import MINIMAL_FLOW, save_progress

        await save_progress(self, MINIMAL_FLOW)

    @rx.event(background=True)
    async def enter(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """On page load: a finished kit goes to the editor; a draft (of this flow, or of
        either old one) opens on the step that holds its data, never past the first gap
        (`brand_minimal_vm.resume_step`); nothing saved opens on Tus redes. Read from the
        database itself, so it does not depend on the order the page's loads land in."""
        async with self:
            self.synced = False
            # the browser's «atrás» inside the flow (`?paso=` already there) keeps the
            # step on screen while the entry is read: no «Cargando» flash per step
            if not (self.entered and step_param(self) is not None):
                self.entered = False
            auth = await self.get_state(AuthState)
            tenant = brand_tenant_id(auth)
            in_session = auth.session_tenant_id != ""
        tenant_id = tenant_uuid(tenant) if tenant else None
        entry: _Entry | None = None
        account_country = ""
        if tenant_id is not None:
            try:
                entry = await asyncio.to_thread(_read_entry, tenant_id)
                if in_session:
                    account_country = await asyncio.to_thread(_read_account_country, tenant_id)
            except SQLAlchemyError as exc:
                logger.warning("brand minimal: entry unreadable: %s", type(exc).__name__)
        if entry is not None and entry.finished:
            async with self:
                self.entered = True
            yield rx.redirect(_EDITOR_ROUTE)
            return
        async with self:
            # m-24852199: a proposal from the Alta, or why there is none
            (await self.get_state(BrandProposalState)).show(
                entry.review if entry is not None else PrefillReview()
            )
            self.account_country = vm.account_country("", account_country, _KNOWN_COUNTRIES)
            self.more_logo_versions = False
            self.show_place = False
            raw = step_param(self)
            label = entry_label(self.router.url.query_parameters.get(vm.GATE_PARAM, ""))
            facts = entry.facts if entry is not None else vm.KitFacts()
            self.gate_notice = vm.gate_notice(label, len(vm.missing_steps(facts))) if label else ""
            if entry is not None and not self._entry_hydrated:
                self.phrase = entry.facts.example
                connect = await self.get_state(BrandConnectState)
                progress = entry.progress
                if progress.get("started_without_socials"):
                    connect.started_without_socials = True
                if progress.get("profile_pic_is_real"):
                    connect.profile_pic_is_real = True
                if progress.get("logo_from_profile"):
                    connect.logo_from_profile = True
                    wizard = await self.get_state(BrandWizardState)
                    if not wizard.has_logo:
                        wizard.has_logo = HAS_LOGO_PROFILE
                self._entry_hydrated = True
            if entry is None:
                self.step = vm.FIRST_STEP
            elif raw is not None:
                requested = parse_step_param(raw, vm.TOTAL_STEPS)
                self.step = vm.STEP_NAMES[guard_step(requested, vm.step_completes(entry.facts)) - 1]
            else:
                self.step = vm.resume_step(entry.saved_step, entry.facts)
            connect = await self.get_state(BrandConnectState)
            connect.country_code = vm.account_country(
                connect.country_code, self.account_country, _KNOWN_COUNTRIES
            )
            proposal = await self.get_state(BrandProposalState)
            if proposal.approved:  # «Listo…» stands on the step the approval opened
                proposal.approved_step = self.step
            # m-24854331 (OL2-6): an approval that left rubro, logo and colours filled
            # opens «Te faltan 3 cosas que solo tú sabes» instead of the five steps
            answers = await self.get_state(BrandAnswersState)
            if entry is not None and entry.answers_path:
                creative = await self.get_state(CreativeState)
                answers.open(
                    active=True,
                    answers=answers_vm.Answers(
                        entry.facts.positioning or creative.kit_positioning,
                        entry.facts.audience or creative.kit_audience,
                        self.phrase,
                    ),
                    hints=entry.hints,
                    drafts=entry.drafts,
                    has_tags=entry.has_tags,
                )
            else:
                answers.open(
                    active=False, answers=answers_vm.Answers(), hints={}, drafts={}, has_tags=False
                )
            self.entered = True
            self.synced = True
        yield None

    # -- moving ------------------------------------------------------------------

    @rx.event
    async def next_step(self) -> rx.event.EventSpec | None:
        """Continuar. Leaving Tu negocio y rubro (re)starts the search for businesses like
        the owner's in the background when its answers changed — it is read later, in
        «Mejora tu marca», never waited for here."""
        leaving = self.step
        self._go(vm.next_step(self.step))
        (await self.get_state(BrandProposalState)).approved = False
        if leaving == vm.STEP_BUSINESS:
            connect = await self.get_state(BrandConnectState)
            if connect.rubro_text.strip() and connect._answers() != connect.discovery_answers:
                return BrandConnectState.run_discovery
        return None

    @rx.event
    def prev_step(self) -> None:
        """Atrás: the step before, with everything written kept (it lives in the states)."""
        self._go(vm.previous_step(self.step))

    @rx.event
    def primary(self) -> rx.event.EventSpec:
        """The frame's primary button: «Siguiente», or «Terminar mi marca» on the last
        step (`finish`, label and behaviour as before)."""
        if self.step == vm.LAST_STEP:
            return BrandMinimalState.finish
        return BrandMinimalState.next_step

    @rx.event
    async def skip_socials(self) -> None:
        """«No tengo redes»: straight to Tu negocio y rubro, with nothing prefilled — a
        profile read before is forgotten, with what it had filled in (rubro, place and
        the colours of its picture)."""
        connect = await self.get_state(BrandConnectState)
        if connect.profile_username:
            await self._forget_profile(connect)
        connect.started_without_socials = True
        self._go(vm.STEP_BUSINESS)
        (await self.get_state(BrandProposalState)).approved = False

    @rx.event
    async def not_my_profile(self) -> None:
        """«No es mi cuenta»: back to the user field to write another one."""
        connect = await self.get_state(BrandConnectState)
        await self._forget_profile(connect)

    async def _forget_profile(self, connect: BrandConnectState) -> None:
        wizard = await self.get_state(BrandWizardState)
        if wizard.has_logo == HAS_LOGO_PROFILE:
            wizard.has_logo = ""
        if wizard.logo_source == LOGO_SOURCE_PROFILE:
            await wizard.retire_logo_colours()
        connect.profile_username = ""
        connect.profile_fullname = ""
        connect.profile_bio = ""
        connect.profile_category = ""
        connect.profile_followers = ""
        connect.profile_followers_count = 0
        connect.profile_pic = ""
        connect.forget_kept_picture()
        connect.profile_pic_is_real = False
        connect.logo_from_profile = False
        connect.sector = ""
        # the profile's country goes; the account's own (chosen at signup) comes back
        connect.country_code = self.account_country
        connect.city = ""
        connect.error = ""

    # -- Tu logo -------------------------------------------------------------------

    @rx.event
    async def answer_logo(self, value: str) -> None:
        """Tu logo's question. Unlike the old flows it does not move on: the upload or
        the three questions open right below it, on the same step. «Usar mi foto de
        perfil» puts the picture's colours in Tus colores."""
        connect = await self.get_state(BrandConnectState)
        wizard = await self.get_state(BrandWizardState)
        if value == HAS_LOGO_PROFILE:
            if not connect.profile_pic_is_real:
                return
            wizard.has_logo = value
            connect.logo_from_profile = True
            await connect._apply_profile_picture_colours(wizard)
            return
        if value not in {key for key, _t, _b in _LOGO_ANSWERS}:
            return
        wizard.has_logo = value
        connect.logo_from_profile = False
        if wizard.logo_source == LOGO_SOURCE_PROFILE:
            await wizard.retire_logo_colours()

    @rx.event
    def show_more_logo_versions(self) -> None:
        """«Tengo otras versiones de mi logo (opcional)»: the four versions and «Otros
        elementos», as in the editor."""
        self.more_logo_versions = True

    @rx.event
    def open_place(self) -> None:
        """«Más opciones: país y ciudad», or «Cambiar» next to a read profile's place."""
        self.show_place = True

    @rx.event
    async def change_logo_answer(self) -> None:
        """«Cambiar mi respuesta»: the question again — files and answers stay staged."""
        wizard = await self.get_state(BrandWizardState)
        wizard.has_logo = ""

    # -- Cómo hablas --------------------------------------------------------------------

    @rx.event
    async def set_phrase(self, value: str) -> None:
        creative = await self.get_state(CreativeState)
        creative.kit_do_examples = vm.with_example_phrase(
            creative.kit_do_examples, self.phrase, value
        )
        self.phrase = value

    # -- leaving ------------------------------------------------------------------------

    @rx.event(background=True)
    async def save_for_later(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Seguir después» (N6, N2): what is written is saved now; an account goes to
        Inicio, a guest is told how to come back (`creative_wizard_pages.leave_flow`)."""
        from .brand_finish import MINIMAL_FLOW

        async for event in leave_flow(self, MINIMAL_FLOW, later=True):
            yield event

    @rx.event(background=True)
    async def leave(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """The head's «‹ Inicio» (or «‹ Tu correo» for a guest), on every step: save,
        then go (`leave_flow`)."""
        from .brand_finish import MINIMAL_FLOW

        async for event in leave_flow(self, MINIMAL_FLOW, later=False):
            yield event

    @rx.event(background=True)
    async def finish(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Terminar mi marca» on Cómo hablas: save everything with the voice adopted
        (`save_brand_kit` → `persist_brand_kit(adopt_voice=True)`), which marks the kit
        finished and unlocks the app; then «Tu marca está lista» for an account, or the
        signup for a draft. The tone was set on this step, so the editor no longer opens
        on «Voz y tono» and /create no longer flags it."""
        from .brand_finish import MINIMAL_FLOW, save_brand_kit

        async with self:
            (await self.get_state(BrandConnectState)).voice_configured = True
        if not await save_brand_kit(self, MINIMAL_FLOW):
            await _explain_finish_failure(self)
            return
        async with self:
            self.step = vm.FIRST_STEP
            self.direction = DIR_NEXT
            self.phrase = ""
            self.more_logo_versions = False
            self.show_place = False
            navigation = await _finish_navigation(self)
        yield brand_documents.BrandDocumentState.reset_documents
        if navigation is not None:
            yield navigation


class _Entry:
    """What `enter` reads from the database (off the event loop)."""

    def __init__(
        self,
        finished: bool,
        saved_step: str | None,
        facts: vm.KitFacts,
        progress: dict[str, Any],
        review: PrefillReview | None = None,
        *,
        answers_path: bool = False,
        hints: dict[str, str] | None = None,
        drafts: dict[str, str] | None = None,
        has_tags: bool = False,
    ) -> None:
        self.finished = finished
        self.saved_step = saved_step
        self.facts = facts
        self.progress = progress
        #: The Alta's proposal (m-24852199): pending, or why the account was not read.
        self.review = review or PrefillReview()
        #: m-24854331: «Te faltan 3 cosas…» instead of the five steps, with the rubro's
        #: examples, the B1 drafts and whether the approval brought tags.
        self.answers_path = answers_path
        self.hints = hints or {}
        self.drafts = drafts or {}
        self.has_tags = has_tags


def _read_account_country(tenant_id: UUID) -> str:
    """The country the owner chose at signup (m-24842967), or "" when unreadable."""
    from .settings_provider import read_locale

    locale = read_locale(tenant_id)
    return locale.country if locale is not None else ""


def entry_label(slug: object) -> str:
    """The menu entry (its name, N1) whose page sent the owner here (`?desde=`), or ""
    for anything that is not a page of the menu."""
    from .ui.layout import NAV_ITEMS
    from .ui.nav_vm import ROUTE_ALIASES

    if isinstance(slug, list | tuple):
        slug = slug[0] if slug else ""
    path = "/" + str(slug or "").strip().strip("/")
    if path == "/":
        return ""
    best = ("", 0)
    for label, _icon, route, enabled in NAV_ITEMS:
        if not enabled or route == "/":
            continue
        for prefix in (route, *ROUTE_ALIASES.get(route, ())):
            if (path == prefix or path.startswith(f"{prefix}/")) and len(prefix) > best[1]:
                best = (label, len(prefix))
    return best[0]


def read_brand_facts(tenant_id: UUID) -> vm.KitFacts:
    """What the saved kit holds (Inicio's «Termina tu marca: te faltan …»)."""
    entry = _read_entry(tenant_id)
    return entry.facts if entry is not None else vm.KitFacts()


def _read_entry(tenant_id: UUID) -> _Entry | None:
    """The brand's kit, answers and brandboard → where /brand opens. None without a
    brand (nothing to resume)."""
    from qualify_api.creative.brand_kit_store import BrandKitStore

    from .creative_provider import default_brand_id, load_kit_form

    brand_id = default_brand_id(tenant_id)
    if brand_id is None:
        return None
    form = load_kit_form(tenant_id, brand_id)
    store = BrandKitStore()
    details = store.load_details(tenant_id=tenant_id, brand_id=brand_id)
    progress = vm.progress_of(details.connect)
    if vm.kit_finished(form is not None, progress):
        return _Entry(True, None, vm.KitFacts(), progress)
    kinds = [asset.kind for asset in store.list_assets(tenant_id=tenant_id, brand_id=brand_id)]
    facts = vm.facts_from_saved(
        positioning=form.positioning if form else "",
        audience=form.audience if form else "",
        palette=form.palette_rgb if form else "",
        do_examples=form.do_examples if form else "",
        connect=details.connect,
        profile=details.profile,
        logo_brief=details.logo_brief,
        file_kinds=kinds,
        progress=progress,
    )
    started = owner_started(  # m-24852199: a proposal never goes over the owner's own
        details.connect,
        details.profile,
        details.logo_brief,
        kit_answers=(
            [form.positioning, form.audience, form.palette_rgb, form.do_examples] if form else []
        ),
        has_files=bool(kinds),
    )
    review = review_of(details.connect, has_kit=form is not None, started=started)
    connect = details.connect or {}
    answers_path = answers_vm.applies(
        state=answers_vm.prefill_state(connect),
        rubro=facts.rubro,
        has_logo=facts.has_logo_answer,
        palette=facts.palette,
    )
    return _Entry(
        False,
        vm.step_from_progress(progress),
        facts,
        progress,
        review,
        answers_path=answers_path,
        hints=answers_vm.example_hints(
            answers_vm.example_set(
                sector=str(connect.get("sector") or ""),
                rubro=str(connect.get("rubro_text") or ""),
            )
        )
        if answers_path
        else {},
        drafts=answers_vm.drafts_from(connect) if answers_path else {},
        has_tags=bool(connect.get("hashtags")),
    )


# ---------------------------------------------------------------------------------------
# The page


def _heading_for(index: int) -> rx.Var[str]:
    return rx.match(
        BrandMinimalState.step,
        *((name, (title, subtitle)[index]) for name, title, subtitle in vm.STEPS),
        (vm.STEPS[0][1], vm.STEPS[0][2])[index],
    )


def _wide_button(label: str, icon: str, on_click: Any, *, variant: str = "soft") -> rx.Component:
    """A secondary choice inside a step: the column's width, at least 44 px tall (N12)."""
    return rx.button(
        rx.icon(icon, size=T.ICON_SM),
        label,
        type="button",
        variant=variant,
        color_scheme="gray",
        size="3",
        radius=_CONTROL_RADIUS,
        width="100%",
        min_height="44px",
        on_click=on_click,
    )


def _step_socials() -> rx.Component:
    """① Tus redes: the user and the network (reading it prefills the rest), the profile
    read to confirm, or «No tengo redes». While the profile is read, the footer stays:
    «Seguir después» is always there (no wait without a control)."""
    return rx.cond(
        BrandConnectState.analyzing,
        _connect_loading(),
        rx.cond(
            BrandConnectState.profile_username != "",
            rx.vstack(
                _connect_step_profile(),
                rx.text(f"¿Es tu cuenta? Toca «{NEXT_LABEL}».", size="2", color=T.TEXT_MUTED),
                _wide_button("No es mi cuenta", "rotate-ccw", BrandMinimalState.not_my_profile),
                spacing="3",
                width="100%",
                align="center",
            ),
            rx.vstack(
                _connect_step_account(),
                rx.text(vm.PUBLIC_READ_NOTE, size="2", color=T.TEXT_MUTED, text_align="center"),
                rx.text("¿Todavía no tienes redes?", size="2", color=T.TEXT_MUTED),
                _wide_button("No tengo redes", "arrow-right", BrandMinimalState.skip_socials),
                spacing="3",
                width="100%",
                align="center",
            ),
        ),
    )


def _step_business() -> rx.Component:
    """② Tu negocio y rubro: the rubro (what the search for similar businesses starts
    from), Posicionamiento and Audiencia — what the kit needs to be read for its voice.
    País and ciudad are optional; a read profile prefills them."""
    return _step_body(
        _labeled_input(
            "¿A qué se dedica tu negocio?",
            BrandConnectState.rubro_text,
            BrandConnectState.set_rubro_text,
            "Ej.: Shawarmas y ensaladas",
        ),
        _labeled_area(
            "¿Qué te hace distinto?",
            CreativeState.kit_positioning,
            CreativeState.set_kit_positioning,
            "Ej.: Shawarma hecho al momento, con salsas de la casa y porciones grandes.",
        ),
        _labeled_area(
            "¿Quién te compra?",
            CreativeState.kit_audience,
            CreativeState.set_kit_audience,
            "Ej.: Estudiantes y oficinistas de la zona que almuerzan rápido.",
        ),
        _place(),
        icon="store",
    )


def _place_fields() -> rx.Component:
    return rx.grid(
        _select_field(
            "País (opcional)",
            BrandConnectState.country_code,
            BrandConnectState.set_country_code,
            COUNTRY_OPTIONS,
            "Elige tu país",
        ),
        _labeled_input(
            "Ciudad (opcional)",
            BrandConnectState.city,
            BrandConnectState.set_city,
            "Ej.: San Cristóbal",
        ),
        # one column on a phone (N12), two from the small breakpoint up
        columns=rx.breakpoints(initial="1", sm="2"),
        spacing="3",
        width="100%",
    )


def _place_summary() -> rx.Component:
    """«San Cristóbal, Venezuela · Cambiar»: the place a read profile brought."""
    country_name = rx.match(BrandConnectState.country_code, *COUNTRY_OPTIONS, "")
    return rx.hstack(
        rx.icon("map-pin", size=T.ICON_SM, color=T.TEXT_MUTED),
        rx.text(
            BrandConnectState.city,
            rx.cond(country_name != "", rx.fragment(", ", country_name)),
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.button(
            "Cambiar",
            type="button",
            variant="ghost",
            size="3",
            radius=_CONTROL_RADIUS,
            min_height="44px",
            on_click=BrandMinimalState.open_place,
        ),
        align="center",
        spacing="2",
        width="100%",
        flex_wrap="wrap",
    )


def _place() -> rx.Component:
    """País and ciudad (N6: three questions on the step, the rest optional): the fields
    once opened; a read profile's place as one line; otherwise a soft button. The
    account's country is already chosen (`BrandMinimalState.enter`)."""
    return rx.cond(
        BrandMinimalState.show_place,
        _place_fields(),
        rx.cond(
            BrandConnectState.city != "",
            _place_summary(),
            _wide_button(
                "Más opciones: país y ciudad",
                "map-pin",
                BrandMinimalState.open_place,
                variant="ghost",
            ),
        ),
    )


def _logo_question() -> rx.Component:
    return _step_body(
        *(
            _choice_card(title, blurb, False, BrandMinimalState.answer_logo(value))
            for value, title, blurb in _LOGO_ANSWERS
        ),
        rx.cond(
            BrandConnectState.profile_pic_is_real,
            _choice_card(
                _LOGO_FROM_PROFILE[1],
                _LOGO_FROM_PROFILE[2],
                False,
                BrandMinimalState.answer_logo(_LOGO_FROM_PROFILE[0]),
            ),
        ),
        icon="image",
    )


def _logo_from_profile() -> rx.Component:
    return _step_body(
        _profile_avatar("5.5rem", 28),
        rx.text("Usamos tu foto de perfil como logo.", size="3", text_align="center"),
    )


def _main_logo_upload() -> rx.Component:
    """«Sube tu logo»: one dropzone, saved as the version the palette reads first."""
    staged = BrandWizardState.logo_versions.contains(_MAIN_LOGO_VERSION)
    return rx.vstack(
        dropzone(
            rx.vstack(
                rx.cond(
                    staged,
                    rx.image(
                        src=_asset_src(BrandWizardState.logo_versions[_MAIN_LOGO_VERSION].to(str)),
                        alt="Tu logo",
                        height="5.5rem",
                        width="100%",
                        object_fit="contain",
                    ),
                    rx.icon("image-plus", size=28, color=T.TEXT_MUTED),
                ),
                rx.text(
                    rx.cond(staged, "Toca para cambiarlo", "Sube tu logo"),
                    size="3",
                    weight="medium",
                ),
                rx.text(
                    "Una foto o imagen de tu logo. Con una basta.",
                    size="2",
                    color=T.TEXT_MUTED,
                    text_align="center",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            upload_id=_MAIN_LOGO_UPLOAD_ID,
            accept=_LOGO_VERSION_ACCEPT,
            max_files=1,
            on_drop=BrandWizardState.handle_logo_version_upload(
                rx.upload_files(upload_id=_MAIN_LOGO_UPLOAD_ID), _MAIN_LOGO_VERSION
            ),
            width="100%",
        ),
        rx.cond(
            staged,
            rx.hstack(
                rx.text("Quitar este logo", size="2", color=T.TEXT_MUTED),
                _remove_button(
                    "Quitar tu logo", BrandWizardState.clear_logo_version(_MAIN_LOGO_VERSION)
                ),
                align="center",
                spacing="1",
            ),
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def _logo_upload_minimal() -> rx.Component:
    """Tu logo on «Sí, ya tengo logo»: one upload, and the versions only if asked for."""
    return rx.vstack(
        rx.cond(
            BrandWizardState.logo_error != "",
            callout(BrandWizardState.logo_error, "error"),
        ),
        rx.cond(
            BrandMinimalState.more_logo_versions,
            rx.vstack(_logo_versions(), _brand_extras(), spacing="4", width="100%"),
            rx.vstack(
                _main_logo_upload(),
                _wide_button(
                    "Tengo otras versiones de mi logo (opcional)",
                    "chevron-right",
                    BrandMinimalState.show_more_logo_versions,
                    variant="ghost",
                ),
                spacing="3",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


def _step_logo_answered() -> rx.Component:
    return rx.vstack(
        rx.cond(
            BrandWizardState.has_logo == HAS_LOGO_PROFILE,
            _logo_from_profile(),
            rx.cond(
                BrandWizardState.has_logo == "si",
                _logo_upload_minimal(),
                _step_logo(BrandMinimalState.next_step),
            ),
        ),
        _wide_button(
            "Cambiar mi respuesta",
            "rotate-ccw",
            BrandMinimalState.change_logo_answer,
            variant="ghost",
        ),
        spacing="4",
        width="100%",
        align="center",
    )


def _step_logo_view() -> rx.Component:
    """③ Tu logo: the question and its answer on one step."""
    return rx.cond(BrandWizardState.has_logo == "", _logo_question(), _step_logo_answered())


def _step_voice() -> rx.Component:
    """⑤ Cómo hablas: the tone and one phrase the owner would say. The rest is
    «Mejora tu marca (opcional)», named here so the owner knows it is not lost."""
    return _step_body(
        *_tone_sliders(),
        _labeled_input(
            _PHRASE_LABEL,
            BrandMinimalState.phrase,
            BrandMinimalState.set_phrase,
            _PHRASE_PLACEHOLDER,
        ),
        rx.text(
            rx.text.strong("Mejora tu marca (opcional). "),
            "Tu tipografía, las palabras que nunca usas, tu voz grabada y los negocios "
            "parecidos al tuyo los sumas cuando quieras desde Tu marca.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        icon="message-circle",
    )


def _steps() -> rx.Component:
    return rx.fragment(
        _progress_trigger(BrandMinimalState),
        rx.match(
            BrandMinimalState.step,
            (vm.STEP_SOCIALS, _step_socials()),
            (vm.STEP_BUSINESS, _step_business()),
            (vm.STEP_LOGO, _step_logo_view()),
            (vm.STEP_COLOURS, _step_palette()),
            (vm.STEP_VOICE, _step_voice()),
            _step_socials(),
        ),
    )


def _can_continue() -> rx.Var[bool]:
    """What Continuar needs on each step (`brand_minimal_vm.step_complete`, as Vars)."""
    return rx.match(
        BrandMinimalState.step,
        (
            vm.STEP_SOCIALS,
            (BrandConnectState.profile_username != "") & ~BrandConnectState.analyzing,
        ),
        (
            vm.STEP_BUSINESS,
            (BrandConnectState.rubro_text != "")
            & (CreativeState.kit_positioning != "")
            & (CreativeState.kit_audience != ""),
        ),
        (
            vm.STEP_LOGO,
            rx.cond(
                BrandWizardState.has_logo == HAS_LOGO_PROFILE,
                True,
                (BrandWizardState.has_logo != "") & _logo_step_complete(),
            ),
        ),
        (vm.STEP_COLOURS, CreativeState.kit_palette != ""),
        (vm.STEP_VOICE, BrandMinimalState.phrase != ""),
        False,
    )


def _reason() -> rx.Var[str]:
    """While «Siguiente» (or «Terminar mi marca») is off, what the step still needs —
    read next to the button (§5.8), so an off button never reads as «se trabó»."""
    return rx.cond(
        ~_can_continue(),
        rx.match(BrandMinimalState.step, *vm.MISSING_HINTS.items(), ""),
        "",
    )


def _primary_label() -> rx.Var[str]:
    """«Siguiente», and on Cómo hablas the finish (`_finish_button`'s label: an account
    finishes its brand, a draft finishes it and creates the account)."""
    return rx.cond(
        BrandMinimalState.is_last,
        rx.cond(AuthState.session_tenant_id != "", _FINISH_LABEL, _FINISH_DRAFT_LABEL),
        NEXT_LABEL,
    )


def _foot() -> rx.Component:
    """Atrás · Seguir después · Siguiente (the step frame's foot, PASOS-4). Tus redes
    has no primary until a profile is read: its network buttons and «No tengo redes» are
    its ways forward."""
    common: dict[str, Any] = {
        "step": BrandMinimalState.n,
        "on_back": BrandMinimalState.prev_step,
        "on_later": BrandMinimalState.save_for_later,
    }
    return rx.cond(
        (BrandMinimalState.step == vm.STEP_SOCIALS) & (BrandConnectState.profile_username == ""),
        step_foot(None, on_primary=None, **common),
        step_foot(
            _primary_label(),
            on_primary=BrandMinimalState.primary,
            primary_disabled=~_can_continue(),
            primary_loading=BrandMinimalState.is_last & CreativeState.kit_saving,
            reason=_reason(),
            **common,
        ),
    )


def _column_width() -> rx.Var[str]:
    return rx.cond(
        (BrandMinimalState.step == vm.STEP_LOGO)
        & (BrandWizardState.has_logo == "si")
        & BrandMinimalState.more_logo_versions,
        _BRANDBOARD_COLUMN_MAX,
        "34rem",
    )


def _head(title: str | rx.Var[str]) -> rx.Component:
    """«‹ Inicio» (a guest: «‹ Tu correo») on every step — the way out saves first
    (`BrandMinimalState.leave`) — «Paso N de 5» and the step's name as the h1."""
    return step_head(
        title,
        step=BrandMinimalState.n,
        total=vm.TOTAL_STEPS,
        back_label=exit_label(),
        on_exit=BrandMinimalState.leave,
    )


def _notices() -> rx.Component:
    return rx.vstack(
        rx.cond(
            BrandMinimalState.gate_notice != "",
            callout(BrandMinimalState.gate_notice, "info"),
        ),
        rx.cond(
            CreativeState.kit_error != "",
            callout(CreativeState.kit_error, "error"),
        ),
        approved_notice(BrandMinimalState.step),
        read_notice(BrandMinimalState.step == vm.FIRST_STEP),
        spacing="3",
        width="100%",
        max_width="34rem",
        align_self="center",
        align_items="center",
    )


def _step_card() -> rx.Component:
    return card(
        rx.vstack(
            _steps(),
            # a guest's other way out on the first step, as before: another email
            rx.cond(BrandMinimalState.step == vm.FIRST_STEP, _change_email_button()),
            width="100%",
            max_width=_column_width(),
            align_self="center",
            align_items="center",
            spacing="4",
        ),
        padding=rx.breakpoints(initial="1rem", sm="1.75rem"),
        width="100%",
        # a flex column, so the step's column centres in the card
        display="flex",
        flex_direction="column",
    )


def _loading_card() -> rx.Component:
    return card(
        _loading_view("Cargando tu marca"),
        padding="1.75rem",
        width="100%",
        display="flex",
        align_items="center",
        justify_content="center",
    )


def _frame(loading: rx.Var[bool]) -> rx.Component:
    """The five steps in the step frame (PASOS-4, m-24852243; §4.5): the head with the
    way out on every step, the step in the body that scrolls, the foot fixed. While the
    kit loads the head stays (the way out is never missing) and the foot waits. The
    address (`?paso=N`) and the settle (top + focus) follow every step change
    (`step_sync`), only once `enter` has decided the step."""
    return step_frame(
        _notices(),
        rx.cond(
            loading,
            _loading_card(),
            rx.fragment(
                rx.cond(
                    BrandMinimalState.synced,
                    step_sync(BrandMinimalState.n, BrandMinimalState.direction),
                ),
                rx.text(_heading_for(1), size="3", color=T.TEXT_MUTED, width="100%"),
                _step_card(),
            ),
        ),
        head=_head(rx.cond(loading, "Tu marca", _heading_for(0))),
        foot=rx.cond(loading, rx.fragment(), _foot()),
        step=BrandMinimalState.n,
        direction=BrandMinimalState.direction,
        on_pop=BrandMinimalState.pop_step,
        on_leave=BrandMinimalState.leave_frame,
    )


def brand_minimal_index() -> rx.Component:
    """«Tu marca» in five steps, in the step frame. Three other faces keep the page's
    usual header: «Tu marca está lista» after the finish, the Alta's proposal to review
    (m-24852199) and «Te faltan 3 cosas» (m-24854331) — none of them is one of the
    five steps."""
    loading = ~BrandMinimalState.synced | ~BrandMinimalState.entered | CreativeState.kit_loading
    # m-24852199: a pending proposal is reviewed before any step is shown (no step is
    # mounted meanwhile, so the save-as-you-go writes nothing until the owner decides)
    reviewing = BrandProposalState.pending & ~loading
    # m-24854331: after «Aprobar», the three questions only the owner can answer
    answering = BrandAnswersState.active & ~loading & ~BrandProposalState.pending
    ready = BrandWizardState.brand_ready & (CreativeState.kit_error == "")
    return _wizard_shell(
        rx.cond(
            ready,
            rx.fragment(page_header("Tu marca", title_size="8"), page_body(_brand_ready_card())),
            rx.cond(
                answering,
                rx.fragment(answers_header(), answers_body()),
                rx.cond(
                    reviewing,
                    rx.fragment(
                        page_header(proposal_vm.REVIEW_TITLE, title_size="8"),
                        page_body(
                            rx.vstack(_notices(), proposal_review(), spacing="4", width="100%")
                        ),
                    ),
                    _frame(loading),
                ),
            ),
        ),
    )
