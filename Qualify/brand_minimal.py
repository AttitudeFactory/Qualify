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
from sqlalchemy.exc import SQLAlchemyError

from . import brand_documents
from . import brand_minimal_vm as vm
from .auth_state import AuthState, brand_tenant_id
from .creative_state import CreativeState
from .creative_wizard_pages import (  # the wizards' own controls, shared on purpose
    _BRANDBOARD_COLUMN_MAX,
    _CONTROL_RADIUS,
    _FINISH_DRAFT_LABEL,
    _FINISH_LABEL,
    COUNTRY_OPTIONS,
    HAS_LOGO_PROFILE,
    LOGO_SOURCE_PROFILE,
    BrandConnectState,
    BrandWizardState,
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
    _or_ready,
    _profile_avatar,
    _progress_trigger,
    _select_field,
    _step_body,
    _step_counter,
    _step_logo,
    _step_palette,
    _tone_sliders,
    _wizard_shell,
)
from .tenant import tenant_uuid
from .ui import callout, card, page_body, page_header
from .ui import tokens as T

logger = logging.getLogger(__name__)

#: Where a finished kit goes from /brand: the editor, as before (m-24848529 keeps it).
_EDITOR_ROUTE = "/brand/kit"

#: «Seguir después» (N6): what it says once the progress is saved.
_SAVED_FOR_LATER = "Guardamos lo que llevas. Cuando vuelvas, sigues en este mismo paso."
_SAVE_LATER_FAILED = "No pudimos guardar lo que llevas. Revisa tu conexión e inténtalo de nuevo."

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

    @rx.var
    def step_number(self) -> int:
        """0-based position, for «Paso N de 5»."""
        return vm.step_index(self.step)

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
            self.entered = False
            auth = await self.get_state(AuthState)
            tenant = brand_tenant_id(auth)
        tenant_id = tenant_uuid(tenant) if tenant else None
        entry: _Entry | None = None
        if tenant_id is not None:
            try:
                entry = await asyncio.to_thread(_read_entry, tenant_id)
            except SQLAlchemyError as exc:
                logger.warning("brand minimal: entry unreadable: %s", type(exc).__name__)
        if entry is not None and entry.finished:
            async with self:
                self.entered = True
            yield rx.redirect(_EDITOR_ROUTE)
            return
        async with self:
            if entry is None:
                self.step = vm.FIRST_STEP
            else:
                self.step = vm.resume_step(entry.saved_step, entry.facts)
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
            self.entered = True
        yield None

    # -- moving ------------------------------------------------------------------

    @rx.event
    async def next_step(self) -> rx.event.EventSpec | None:
        """Continuar. Leaving Tu negocio y rubro (re)starts the search for businesses like
        the owner's in the background when its answers changed — it is read later, in
        «Mejora tu marca», never waited for here."""
        leaving = self.step
        self.step = vm.next_step(self.step)
        if leaving == vm.STEP_BUSINESS:
            connect = await self.get_state(BrandConnectState)
            if connect.rubro_text.strip() and connect._answers() != connect.discovery_answers:
                return BrandConnectState.run_discovery
        return None

    @rx.event
    def prev_step(self) -> None:
        """Atrás: the step before, with everything written kept (it lives in the states)."""
        self.step = vm.previous_step(self.step)

    @rx.event
    async def skip_socials(self) -> None:
        """«No tengo redes»: straight to Tu negocio y rubro, with nothing prefilled — a
        profile read before is forgotten, with what it had filled in (rubro, place and
        the colours of its picture)."""
        connect = await self.get_state(BrandConnectState)
        if connect.profile_username:
            await self._forget_profile(connect)
        connect.started_without_socials = True
        self.step = vm.STEP_BUSINESS

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
        connect.profile_pic_is_real = False
        connect.logo_from_profile = False
        connect.sector = ""
        connect.country_code = ""
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
        """«Seguir después» (N6): what is written is saved now, and the owner is told
        they will come back to this same step."""
        from .brand_finish import MINIMAL_FLOW, save_progress

        try:
            await save_progress(self, MINIMAL_FLOW)
        except Exception as exc:  # noqa: BLE001 — a toast, never a crash
            logger.warning("brand minimal: save for later failed: %s", type(exc).__name__)
            yield brand_documents.notify(_SAVE_LATER_FAILED, "error")
            return
        yield brand_documents.notify(_SAVED_FOR_LATER, "ok")

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
            self.phrase = ""
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
    ) -> None:
        self.finished = finished
        self.saved_step = saved_step
        self.facts = facts
        self.progress = progress


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
    return _Entry(False, vm.step_from_progress(progress), facts, progress)


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
                rx.text("¿Es tu cuenta? Toca «Continuar».", size="2", color=T.TEXT_MUTED),
                _wide_button("No es mi cuenta", "rotate-ccw", BrandMinimalState.not_my_profile),
                spacing="3",
                width="100%",
                align="center",
            ),
            rx.vstack(
                _connect_step_account(),
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
        rx.grid(
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
        ),
        icon="store",
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


def _step_logo_answered() -> rx.Component:
    return rx.vstack(
        rx.cond(
            BrandWizardState.has_logo == HAS_LOGO_PROFILE,
            _logo_from_profile(),
            _step_logo(BrandMinimalState.next_step),
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


def _control(label: str, on_click: Any, **props: Any) -> rx.Component:
    """A footer button at least 44 px tall (N12)."""
    return rx.button(
        label,
        size="3",
        radius=_CONTROL_RADIUS,
        min_height="44px",
        on_click=on_click,
        **props,
    )


def _finish() -> rx.Component:
    return rx.button(
        rx.cond(AuthState.session_tenant_id != "", _FINISH_LABEL, _FINISH_DRAFT_LABEL),
        rx.icon("check", size=T.ICON_SM),
        size="3",
        radius=_CONTROL_RADIUS,
        min_height="44px",
        on_click=BrandMinimalState.finish,
        loading=CreativeState.kit_saving,
        disabled=~_can_continue(),
    )


def _controls() -> rx.Component:
    """Atrás · Seguir después · Continuar on every step (N6). The first step has nothing
    behind it: a guest gets «Usar otro correo» there. Tus redes has no Continuar until a
    profile is read (its network buttons and «No tengo redes» are its ways forward)."""
    back = rx.cond(
        BrandMinimalState.step == vm.FIRST_STEP,
        _change_email_button(),
        rx.button(
            rx.icon("chevron-left", size=T.ICON_SM),
            "Atrás",
            variant="ghost",
            size="3",
            radius=_CONTROL_RADIUS,
            min_height="44px",
            on_click=BrandMinimalState.prev_step,
        ),
    )
    later = _control(
        "Seguir después",
        BrandMinimalState.save_for_later,
        variant="ghost",
        color_scheme="gray",
    )
    forward = rx.cond(
        BrandMinimalState.step == vm.LAST_STEP,
        _finish(),
        rx.cond(
            (BrandMinimalState.step == vm.STEP_SOCIALS)
            & (BrandConnectState.profile_username == ""),
            rx.fragment(),
            rx.button(
                "Continuar",
                rx.icon("chevron-right", size=T.ICON_SM),
                size="3",
                radius=_CONTROL_RADIUS,
                min_height="44px",
                on_click=BrandMinimalState.next_step,
                disabled=~_can_continue(),
            ),
        ),
    )
    return rx.hstack(
        back,
        rx.spacer(),
        later,
        forward,
        width="100%",
        align="center",
        spacing="2",
        flex_wrap="wrap",
    )


def _column_width() -> rx.Var[str]:
    return rx.cond(
        (BrandMinimalState.step == vm.STEP_LOGO) & (BrandWizardState.has_logo == "si"),
        _BRANDBOARD_COLUMN_MAX,
        "34rem",
    )


def brand_minimal_index() -> rx.Component:
    """Same frame as the old wizards (`brand_manual_index`): `page_header` with «Paso N
    de 5» outside `page_body`, one card with the step in a centred column and the
    controls along its bottom."""
    loading = ~BrandMinimalState.entered | CreativeState.kit_loading
    return _wizard_shell(
        *_or_ready(
            page_header(
                _heading_for(0),
                _heading_for(1),
                kicker=_step_counter(BrandMinimalState.step_number, vm.TOTAL_STEPS),
                title_size="8",
            ),
            page_body(
                rx.vstack(
                    rx.vstack(
                        rx.cond(
                            CreativeState.kit_error != "",
                            callout(CreativeState.kit_error, "error"),
                        ),
                        spacing="3",
                        width="100%",
                        max_width="34rem",
                        align_self="center",
                        align_items="center",
                    ),
                    rx.cond(
                        loading,
                        card(
                            _loading_view("Cargando tu marca"),
                            padding="1.75rem",
                            width="100%",
                            flex="1",
                            display="flex",
                            align_items="center",
                            justify_content="center",
                        ),
                        card(
                            rx.vstack(
                                _steps(),
                                width="100%",
                                max_width=_column_width(),
                                align_self="center",
                                align_items="center",
                                flex="1",
                                justify_content="center",
                            ),
                            _controls(),
                            padding=rx.breakpoints(initial="1rem", sm="1.75rem"),
                            width="100%",
                            flex="1",
                            display="flex",
                            flex_direction="column",
                            justify_content="space-between",
                            gap="1.5rem",
                            key=BrandMinimalState.step,
                        ),
                    ),
                    spacing="4",
                    width="100%",
                    flex="1",
                    min_height="0",
                ),
            ),
        ),
    )
