"""«Te faltan 3 cosas que solo tú sabes» → three one-question screens → «Tu marca está
lista» (m-24854331, OL2-6 of the epic m-24852192, docs/epica-prellenado-brand-kit-alta.md
§7.8; UX: docs/ux-esto-es-lo-que-vimos.md §2, mockup frames 2, 3 and 6).

After «Aprobar» (`brand_proposal.BrandProposalState.approve`), `BrandMinimalState.enter`
re-reads the kit; when the approval left the rubro, the logo and the colours filled
(`brand_answers_vm.applies`), it opens this path (`BrandAnswersState.open`) instead of
«Paso 2 de 5». Every other owner keeps the five steps unchanged.

No new storage, and no field of its own: each answer is the kit's own field in the
wizard's states — «¿Qué te hace distinto?» → `CreativeState.kit_positioning`, «¿Quién te
compra?» → `kit_audience`, the third → `BrandMinimalState.phrase` (the first line of
`do_examples`) plus the optional tone sliders. Saving as you go and finishing are the
five steps' own (`brand_finish.save_progress` / `save_brand_kit` with `MINIMAL_FLOW`), so
the gate and the editor see exactly what they saw before.

B1 drafts (OL2-3, off until OL2-4): read from `prefill.proposal.borradores`; a draft is
shown as a card and reaches the kit only through «Sí, así es» — or, after «Corregir»,
as the text the owner leaves in the field."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import reflex as rx

from . import brand_answers_vm as vm
from . import brand_documents
from . import brand_minimal_vm as minimal_vm
from .brand_proposal import BrandProposalState
from .creative_state import CreativeState
from .creative_wizard_pages import (
    _CONTROL_RADIUS,
    _FINISH_DRAFT_LABEL,
    _FINISH_LABEL,
    BrandConnectState,
    _explain_finish_failure,
    _finish_route,
    _profile_avatar,
    _progress_trigger,
    _tone_sliders,
)
from .ui import callout, card, page_body, page_header
from .ui import tokens as T

logger = logging.getLogger(__name__)

#: The two ways out of «Tu marca está lista»; the route arrives from the client.
_READY_ROUTES = frozenset({vm.CREATE_ROUTE, vm.BRAND_ROUTE})


class BrandAnswersState(rx.State):
    """The path's cursor (a screen name, `brand_answers_vm.SCREENS`), the rubro's
    examples and the B1 drafts. The answers themselves stay in the wizard's states."""

    #: This owner is on the path (set by `BrandMinimalState.enter`).
    active: bool = False
    step: str = vm.SCREEN_MISSING
    #: «Por ejemplo: «…»» per question (T22–T25), by the kit's rubro.
    hints: dict[str, str] = {}
    #: B1 drafts by question key ("" none) — the tenant's own proposal, shown to its owner.
    drafts: dict[str, str] = {}
    #: «Tus etiquetas (hecho)» only when the approval brought tags.
    has_tags: bool = False
    #: Which of the three questions hold an answer — refreshed whenever the checklist
    #: can come on screen (entry, «Atrás» from the first question, «Lo hago después»).
    answered: list[bool] = [False, False, False]
    #: «Corregir» on a draft: the field opens with the draft, in `correction` until the
    #: owner moves on (only then it becomes their answer).
    correcting: bool = False
    correction: str = ""
    #: «Ajustar el tono (opcional)» was opened on the third question.
    show_tone: bool = False

    @rx.var
    def counter_text(self) -> str:
        """T17 — «{n} de 3»."""
        return vm.counter(self.step)

    @rx.var
    def missing_title(self) -> str:
        """T16 / T16b / T16c: «Te faltan {n}…» counts down (founder, 2026-10-26)."""
        return vm.missing_title(sum(1 for done in self.answered if not done))

    @rx.var
    def current_hint(self) -> str:
        return self.hints.get(self.step, "")

    @rx.var
    def current_draft(self) -> str:
        return self.drafts.get(self.step, "")

    @rx.var
    def progress_value(self) -> int:
        """The bar under «{n} de 3» (decorative: the counter says it)."""
        if self.step not in vm.QUESTION_KEYS:
            return 0
        return round((vm.QUESTION_KEYS.index(self.step) + 1) * 100 / vm.TOTAL_QUESTIONS)

    def open(
        self,
        *,
        active: bool,
        answers: vm.Answers,
        hints: dict[str, str],
        drafts: dict[str, str],
        has_tags: bool,
    ) -> None:
        """What `BrandMinimalState.enter` read (caller holds the lock): the checklist
        right after «Aprobar»; a returning owner on the first question still empty."""
        self.active = active
        self.step = vm.resume_screen(answers) if active else vm.SCREEN_MISSING
        self.hints = dict(hints) if active else {}
        self.drafts = dict(drafts) if active else {}
        self.has_tags = has_tags and active
        self.answered = list(answers.answered())
        self._clear_screen()

    def _clear_screen(self) -> None:
        self.correcting = False
        self.correction = ""
        self.show_tone = False

    # -- the answers (in the wizard's own states) ------------------------------------------

    async def _write(self, key: str, value: str) -> None:
        """`value` as the owner's answer to `key` (caller holds the lock)."""
        from .brand_minimal import BrandMinimalState

        creative = await self.get_state(CreativeState)
        if key == vm.Q_DISTINCT:
            creative.kit_positioning = value
        elif key == vm.Q_BUYERS:
            creative.kit_audience = value
        elif key == vm.Q_PHRASE:
            minimal = await self.get_state(BrandMinimalState)
            creative.kit_do_examples = minimal_vm.with_example_phrase(
                creative.kit_do_examples, minimal.phrase, value
            )
            minimal.phrase = value

    async def _refresh_answered(self) -> None:
        """`answered` from the wizard's states (caller holds the lock)."""
        from .brand_minimal import BrandMinimalState

        creative = await self.get_state(CreativeState)
        minimal = await self.get_state(BrandMinimalState)
        answers = vm.Answers(creative.kit_positioning, creative.kit_audience, minimal.phrase)
        self.answered = list(answers.answered())

    async def _commit_correction(self) -> None:
        """After «Corregir», what the owner left in the field is their answer."""
        if self.correcting and self.step in vm.QUESTION_KEYS and self.correction.strip():
            await self._write(self.step, self.correction)
        self._clear_screen()

    # -- moving --------------------------------------------------------------------------

    @rx.event
    async def answer_now(self) -> None:
        """«Responder ahora»: the first question still empty."""
        from .brand_minimal import BrandMinimalState

        creative = await self.get_state(CreativeState)
        minimal = await self.get_state(BrandMinimalState)
        answers = vm.Answers(creative.kit_positioning, creative.kit_audience, minimal.phrase)
        self._clear_screen()
        self.step = vm.first_unanswered(answers) or vm.QUESTION_KEYS[-1]

    @rx.event
    async def next_step(self) -> None:
        """Continuar."""
        await self._commit_correction()
        self.step = vm.next_screen(self.step)

    @rx.event
    async def prev_step(self) -> None:
        """Atrás: the screen before, with everything written kept."""
        await self._commit_correction()
        self.step = vm.previous_screen(self.step)
        await self._refresh_answered()

    @rx.event
    async def confirm_draft(self) -> None:
        """«Sí, así es»: the draft becomes the owner's answer — only now does it reach
        the kit (and what generation reads). On the first two questions, the next one."""
        draft = self.drafts.get(self.step, "")
        if self.step not in vm.QUESTION_KEYS or not draft:
            return
        await self._write(self.step, draft)
        self._clear_screen()
        if self.step != vm.QUESTION_KEYS[-1]:
            self.step = vm.next_screen(self.step)

    @rx.event
    def correct_draft(self) -> None:
        """«Corregir»: the field, with the draft in it to change."""
        if self.step not in vm.QUESTION_KEYS:
            return
        self.correction = self.drafts.get(self.step, "")
        self.correcting = True

    @rx.event
    def set_correction(self, value: str) -> None:
        self.correction = value

    @rx.event
    def open_tone(self) -> None:
        self.show_tone = True

    # -- saving --------------------------------------------------------------------------

    @rx.event(background=True)
    async def persist_progress(self) -> None:
        """Every screen change (`_progress_trigger`): the half-written kit is saved, as
        in the five steps (same flow key, so the gate and the editor read it alike)."""
        from .brand_finish import MINIMAL_FLOW, save_progress

        await save_progress(self, MINIMAL_FLOW)

    @rx.event(background=True)
    async def save_for_later(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Lo hago después»: what is written is saved, T28 says so, and the owner is
        taken to the start — the checklist (every page sends an unfinished kit back to
        /brand, and /brand opens on the first question still empty)."""
        from .brand_finish import MINIMAL_FLOW, save_progress

        async with self:
            await self._commit_correction()
        try:
            await save_progress(self, MINIMAL_FLOW)
        except Exception as exc:  # noqa: BLE001 — a toast, never a crash
            logger.warning("brand answers: save for later failed: %s", type(exc).__name__)
            yield brand_documents.notify(vm.SAVE_LATER_FAILED, "error")
            return
        async with self:
            self.step = vm.SCREEN_MISSING
            await self._refresh_answered()
        yield brand_documents.notify(vm.SAVED_FOR_LATER, "ok")

    @rx.event(background=True)
    async def finish(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Terminar mi marca»: the five steps' own finish (`save_brand_kit` →
        `persist_brand_kit(adopt_voice=True)`), which marks the kit finished and unlocks
        the app; then «Tu marca está lista» (or, for a pre-login draft, the signup)."""
        from .brand_finish import MINIMAL_FLOW, save_brand_kit
        from .brand_minimal import BrandMinimalState

        async with self:
            await self._commit_correction()
            (await self.get_state(BrandConnectState)).voice_configured = True
        if not await save_brand_kit(self, MINIMAL_FLOW):
            await _explain_finish_failure(self)
            return
        async with self:
            minimal = await self.get_state(BrandMinimalState)
            minimal.step = minimal_vm.FIRST_STEP
            minimal.phrase = ""
            (await self.get_state(BrandProposalState)).approved = False
            route = await _finish_route(self)
            self.step = vm.SCREEN_READY
        yield brand_documents.BrandDocumentState.reset_documents
        if route is not None:
            yield rx.redirect(route)

    @rx.event
    def leave(self, route: str) -> rx.event.EventSpec:
        """«Crear mi primera publicación» / «Ver mi identidad de marca» — only to one of
        the screen's own routes."""
        self.active = False
        self.step = vm.SCREEN_MISSING
        self._clear_screen()
        return rx.redirect(route if route in _READY_ROUTES else vm.BRAND_ROUTE)


# ---------------------------------------------------------------------------------------
# The views


def _answer_of(key: str) -> rx.Var[str]:
    from .brand_minimal import BrandMinimalState

    return {
        vm.Q_DISTINCT: CreativeState.kit_positioning,
        vm.Q_BUYERS: CreativeState.kit_audience,
        vm.Q_PHRASE: BrandMinimalState.phrase,
    }[key]


def _setter_of(key: str) -> Any:
    from .brand_minimal import BrandMinimalState

    return {
        vm.Q_DISTINCT: CreativeState.set_kit_positioning,
        vm.Q_BUYERS: CreativeState.set_kit_audience,
        vm.Q_PHRASE: BrandMinimalState.set_phrase,
    }[key]


def _current_answer() -> rx.Var[str]:
    return rx.match(
        BrandAnswersState.step,
        *((key, _answer_of(key)) for key in vm.QUESTION_KEYS),
        "",
    )


def _draft_shown() -> rx.Var[bool]:
    """The draft card stands over an empty answer until «Sí, así es» or «Corregir»."""
    return (
        (BrandAnswersState.current_draft != "")
        & (_current_answer() == "")
        & ~BrandAnswersState.correcting
    )


def _can_continue() -> rx.Var[bool]:
    return rx.cond(
        BrandAnswersState.correcting,
        BrandAnswersState.correction != "",
        _current_answer() != "",
    )


def _button(label: str, on_click: Any, **props: Any) -> rx.Component:
    """At least 44 px tall (N12)."""
    return rx.button(
        label,
        type="button",
        size="3",
        radius=_CONTROL_RADIUS,
        min_height="44px",
        on_click=on_click,
        **props,
    )


#: The main action takes the whole width on a phone (the thumb's reach), its own from sm.
_PRIMARY_WIDTH = rx.breakpoints(initial="100%", sm="auto")


# -- the checklist (mockup frame 2) --------------------------------------------------------


def _mark(done: rx.Var[bool] | bool, number: int | None) -> rx.Component:
    """The stepper's own dot (`ui.stepper`'s classes): a check when done, else the
    question's number."""
    inner = rx.icon("check", size=12, stroke_width=3)
    if number is None:
        return rx.box(inner, class_name="q-step-dot q-step-dot--done", aria_hidden="true")
    return rx.box(
        rx.cond(done, inner, rx.text(str(number), size="1", weight="bold", line_height="1")),
        class_name=rx.cond(done, "q-step-dot q-step-dot--done", "q-step-dot"),
        aria_hidden="true",
    )


def _row(label: str, done: rx.Var[bool] | bool, number: int | None = None) -> rx.Component:
    """One line of T18: «✓ Tu cuenta (hecho)», or «1 Qué te hace distinto»."""
    mark_done = rx.text(" ", vm.DONE_MARK, as_="span", color=T.TEXT_MUTED, size="2")
    return rx.hstack(
        _mark(done, number),
        rx.text(
            label,
            rx.cond(done, mark_done, rx.fragment()) if number is not None else mark_done,
            size="3",
            weight=rx.cond(done, "regular", "medium") if number is not None else "regular",
        ),
        role="listitem",
        spacing="3",
        align="center",
        width="100%",
        min_height="2rem",
    )


def _checklist() -> rx.Component:
    rows: list[rx.Component] = []
    for label in vm.DONE_ITEMS:
        row = _row(label, True)
        rows.append(rx.cond(BrandAnswersState.has_tags, row) if label == vm.TAGS_ITEM else row)
    for number, (key, _question, item) in enumerate(vm.QUESTIONS, start=1):
        rows.append(_row(item, _answer_of(key) != "", number))
    return rx.vstack(*rows, role="list", spacing="2", width="100%", align_items="start")


def _missing_view() -> rx.Component:
    return card(
        rx.vstack(
            _checklist(),
            rx.vstack(
                _button(vm.ANSWER_NOW_LABEL, BrandAnswersState.answer_now, width="100%"),
                _button(
                    vm.LATER_LABEL,
                    BrandAnswersState.save_for_later,
                    variant="ghost",
                    color_scheme="gray",
                    width="100%",
                ),
                spacing="2",
                width="100%",
                padding_top="0.5rem",
            ),
            spacing="4",
            width="100%",
            max_width="34rem",
            align_self="center",
        ),
        padding=rx.breakpoints(initial="1rem", sm="1.75rem"),
        width="100%",
        display="flex",
        flex_direction="column",
        align_items="center",
    )


# -- one question (mockup frame 3) -------------------------------------------------------


def _field(key: str, question: str) -> rx.Component:
    """The question's field and its help text — the rubro's example (never the answer)
    or, after «Corregir», the draft's own line. The question is the page's h1; the field
    is named after it for a screen reader."""
    area = rx.cond(
        BrandAnswersState.correcting,
        rx.text_area(
            value=BrandAnswersState.correction,
            on_change=BrandAnswersState.set_correction,
            aria_label=question,
            width="100%",
            rows="4",
            size="3",
            radius=_CONTROL_RADIUS,
        ),
        rx.text_area(
            value=_answer_of(key),
            on_change=_setter_of(key),
            aria_label=question,
            width="100%",
            rows="4",
            size="3",
            radius=_CONTROL_RADIUS,
        ),
    )
    hint = rx.cond(BrandAnswersState.correcting, vm.DRAFT_HINT, BrandAnswersState.current_hint)
    return rx.vstack(
        area,
        rx.text(hint, size="2", color=T.TEXT_MUTED, width="100%"),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _draft_card() -> rx.Component:
    """B1: the draft, where it came from, «Sí, así es» · «Corregir» (T20)."""
    return rx.vstack(
        rx.blockquote(BrandAnswersState.current_draft, size="3", width="100%"),
        rx.text(vm.DRAFT_HINT, size="2", color=T.TEXT_MUTED, width="100%"),
        _button(vm.DRAFT_CONFIRM_LABEL, BrandAnswersState.confirm_draft, width="100%"),
        _button(
            vm.DRAFT_CORRECT_LABEL,
            BrandAnswersState.correct_draft,
            variant="soft",
            width="100%",
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _tone() -> rx.Component:
    """T21: the four sliders, behind a soft button — optional."""
    return rx.cond(
        BrandAnswersState.show_tone,
        rx.vstack(*_tone_sliders(), spacing="4", width="100%"),
        _button(
            vm.TONE_LABEL,
            BrandAnswersState.open_tone,
            variant="ghost",
            color_scheme="gray",
            width="100%",
        ),
    )


def _question(key: str, question: str) -> rx.Component:
    body: list[rx.Component] = [rx.cond(_draft_shown(), _draft_card(), _field(key, question))]
    if key == vm.Q_PHRASE:
        body.append(_tone())
    return rx.vstack(*body, spacing="4", width="100%", class_name="q-settle")


def _finish_button() -> rx.Component:
    from .auth_state import AuthState

    return rx.button(
        rx.cond(AuthState.session_tenant_id != "", _FINISH_LABEL, _FINISH_DRAFT_LABEL),
        rx.icon("check", size=T.ICON_SM),
        type="button",
        size="3",
        radius=_CONTROL_RADIUS,
        min_height="44px",
        on_click=BrandAnswersState.finish,
        loading=CreativeState.kit_saving,
        disabled=~_can_continue(),
        width=_PRIMARY_WIDTH,
    )


def _controls() -> rx.Component:
    """Atrás · Lo hago después · Continuar (on the last one, «Terminar mi marca»). With
    a draft card on screen its «Sí, así es» is the way forward, so no Continuar."""
    forward = rx.cond(
        _draft_shown(),
        rx.fragment(),
        rx.cond(
            BrandAnswersState.step == vm.QUESTION_KEYS[-1],
            _finish_button(),
            rx.button(
                vm.CONTINUE_LABEL,
                rx.icon("chevron-right", size=T.ICON_SM),
                type="button",
                size="3",
                radius=_CONTROL_RADIUS,
                min_height="44px",
                on_click=BrandAnswersState.next_step,
                disabled=~_can_continue(),
                width=_PRIMARY_WIDTH,
            ),
        ),
    )
    back = rx.button(
        rx.icon("chevron-left", size=T.ICON_SM),
        vm.BACK_LABEL,
        type="button",
        variant="ghost",
        size="3",
        radius=_CONTROL_RADIUS,
        min_height="44px",
        on_click=BrandAnswersState.prev_step,
    )
    later = _button(
        vm.LATER_LABEL, BrandAnswersState.save_for_later, variant="ghost", color_scheme="gray"
    )
    return rx.vstack(
        # T27: a button that is off without a reason reads as «se trabó»
        rx.cond(
            ~_draft_shown() & ~_can_continue(),
            rx.text(vm.EMPTY_ANSWER_HINT, size="2", color=T.TEXT_MUTED, width="100%"),
        ),
        rx.flex(
            rx.hstack(
                back, rx.spacer(), later, align="center", spacing="2", width="100%", flex="1"
            ),
            forward,
            direction=rx.breakpoints(initial="column-reverse", sm="row"),
            align=rx.breakpoints(initial="stretch", sm="center"),
            gap="0.5rem",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def _question_view() -> rx.Component:
    return card(
        rx.vstack(
            rx.match(
                BrandAnswersState.step,
                *((key, _question(key, question)) for key, question, _item in vm.QUESTIONS),
                rx.fragment(),
            ),
            width="100%",
            max_width="34rem",
            align_self="center",
            flex="1",
        ),
        _controls(),
        padding=rx.breakpoints(initial="1rem", sm="1.75rem"),
        width="100%",
        display="flex",
        flex_direction="column",
        justify_content="space-between",
        gap="1.5rem",
        key=BrandAnswersState.step,
    )


# -- «Tu marca está lista» (mockup frame 6) ----------------------------------------------


def _colour_dot(colour: rx.Var[str]) -> rx.Component:
    return rx.box(
        width="2rem",
        height="2rem",
        border_radius="9999px",
        background=colour,
        border=T.BORDER,
        aria_hidden="true",
    )


def _summary() -> rx.Component:
    """The owner's brand at a glance: picture, name, rubro and place, colours. No check
    over the picture (UX review 2026-10-25: it repeats the title)."""
    name = rx.cond(
        BrandConnectState.profile_fullname != "",
        BrandConnectState.profile_fullname,
        "@" + BrandConnectState.profile_username,
    )
    return rx.vstack(
        rx.hstack(
            _profile_avatar("3.5rem", 22),
            rx.vstack(
                rx.heading(name, size="4", as_="h2", overflow_wrap="anywhere"),
                rx.text(
                    BrandConnectState.rubro_text,
                    rx.cond(
                        BrandConnectState.city != "",
                        rx.fragment(" · ", BrandConnectState.city),
                    ),
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="0",
                align_items="start",
                min_width="0",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        rx.cond(
            CreativeState.kit_palette != "",
            rx.hstack(
                rx.foreach(CreativeState.kit_palette.split(","), _colour_dot),
                spacing="2",
                flex_wrap="wrap",
                role="group",
                aria_label="Tus colores",
            ),
        ),
        spacing="3",
        width="100%",
    )


def _ready_view() -> rx.Component:
    return card(
        rx.vstack(
            _summary(),
            rx.text(vm.READY_BODY, size="3"),
            rx.vstack(
                _button(
                    vm.READY_CREATE_LABEL,
                    BrandAnswersState.leave(vm.CREATE_ROUTE),
                    width="100%",
                ),
                _button(
                    vm.READY_BRAND_LABEL,
                    BrandAnswersState.leave(vm.BRAND_ROUTE),
                    variant="soft",
                    width="100%",
                ),
                spacing="2",
                width="100%",
                padding_top="0.5rem",
            ),
            spacing="4",
            width="100%",
            max_width="34rem",
            align_self="center",
        ),
        padding=rx.breakpoints(initial="1rem", sm="1.75rem"),
        width="100%",
        display="flex",
        flex_direction="column",
        align_items="center",
    )


# -- the page's header and body on this path -------------------------------------------


def _counter() -> rx.Component:
    """T17 above the question (the wizard's eyebrow treatment), with a quiet bar."""
    return rx.vstack(
        rx.text(
            BrandAnswersState.counter_text,
            size="1",
            weight="bold",
            color=T.TEXT_MUTED,
            letter_spacing="0.08em",
            text_transform="uppercase",
        ),
        rx.progress(
            value=BrandAnswersState.progress_value, size="1", width="8rem", aria_hidden="true"
        ),
        spacing="2",
    )


def answers_header() -> rx.Component:
    """`page_header` for the screen on show: the checklist's title, the question with
    «{n} de 3», or «Tu marca está lista»."""
    in_question = BrandAnswersState.counter_text != ""
    title = rx.match(
        BrandAnswersState.step,
        (vm.SCREEN_MISSING, BrandAnswersState.missing_title),
        *((key, question) for key, question, _item in vm.QUESTIONS),
        (vm.SCREEN_READY, vm.READY_TITLE),
        vm.MISSING_TITLE,
    )
    return rx.cond(
        in_question,
        page_header(title, kicker=_counter(), title_size="8"),
        page_header(title, title_size="8"),
    )


def answers_body() -> rx.Component:
    """`page_body` for the screen on show, with the save-as-you-go hook."""
    return page_body(
        rx.vstack(
            _progress_trigger(BrandAnswersState),
            rx.vstack(
                rx.cond(
                    CreativeState.kit_error != "",
                    callout(CreativeState.kit_error, "error"),
                ),
                # PB-5's literal notice, on top of the checklist right after «Aprobar»
                rx.cond(
                    BrandProposalState.approved & (BrandAnswersState.step == vm.SCREEN_MISSING),
                    callout(vm.APPROVED_NOTICE, "ok"),
                ),
                spacing="3",
                width="100%",
                max_width="34rem",
                align_self="center",
            ),
            rx.match(
                BrandAnswersState.step,
                (vm.SCREEN_MISSING, _missing_view()),
                (vm.SCREEN_READY, _ready_view()),
                _question_view(),
            ),
            spacing="4",
            width="100%",
            flex="1",
            min_height="0",
        ),
    )
