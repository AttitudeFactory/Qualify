"""«¿Quieres un video más largo? Armar mi video por partes» (ADR 44 entry B, m-24921079):
the card under step 2 of a Clip, and the note «Orden del clip» shows over empty parts.

Mounted by `content_generator`: `parts_start_card()` at the end of `_clip_references_view`
while no plan is on screen, `parts_empty_notice()` at the top of `_clip_parts_block`
(empty parts). Design system only
(`card`, `callout`, `progress_panel`); one column, so it reads the same at 375 px.
"""

from __future__ import annotations

import reflex as rx
from qualify_api.creative.parts_ai import STORY_MAX

from . import parts_start_vm as vm
from .audience_view import audience_question
from .creative_state import CreativeState
from .parts_start_state import PartsStartState
from .ui import callout, card, progress_panel
from .ui import tokens as T

_STORY_ID = "parts-start-story"
_HINT_ID = "parts-start-hint"
#: Every button here is a touch target (design-system §4.5).
_TOUCH = "44px"


def _typed_story() -> rx.Var[str]:
    """What the field holds right now, read in the browser at the tap."""
    return rx.Var(
        f"(document.getElementById('{_STORY_ID}')?.value ?? '')",
        _var_type=str,
    )


def _closed() -> rx.Component:
    """The invitation: the question, the benefit, and the one button that opens it."""
    return rx.vstack(
        rx.text(vm.CARD_TITLE, size="3", weight="medium", as_="p"),
        rx.text(
            rx.cond(CreativeState.selected_product_id != "", vm.CARD_HELP, vm.CARD_HELP_NO_PRODUCT),
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.button(
            rx.icon("film", size=T.ICON_SM),
            vm.CARD_ACTION,
            on_click=PartsStartState.open_card,
            variant="soft",
            size="3",
            min_height=_TOUCH,
            width=["100%", "auto"],
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _manual_button() -> rx.Component:
    return rx.button(
        vm.MANUAL_LABEL,
        on_click=PartsStartState.choose_manual,
        variant="soft",
        size="3",
        min_height=_TOUCH,
        width=["100%", "auto"],
    )


def _question() -> rx.Component:
    """The one question, prefilled, and the two ways on (§3a)."""
    return rx.vstack(
        rx.el.label(
            vm.QUESTION,
            html_for=_STORY_ID,
            font_weight="500",
        ),
        rx.text_area(
            value=PartsStartState.story,
            on_change=PartsStartState.set_story,
            # the debounced value is flushed when the field loses focus as well
            on_blur=PartsStartState.set_story,
            max_length=STORY_MAX,
            id=_STORY_ID,
            aria_describedby=_HINT_ID,
            rows="3",
            size="3",
            width="100%",
            resize="vertical",
        ),
        rx.text(vm.QUESTION_HINT, id=_HINT_ID, size="1", color=T.TEXT_MUTED),
        # m-25026509: the same answer as step 3's, before «Proponerme las partes»
        rx.box(audience_question("parts-audience"), width="100%", padding_top="0.5rem"),
        rx.cond(PartsStartState.error != "", callout(PartsStartState.error, "warn")),
        rx.flex(
            rx.button(
                vm.PROPOSE_LABEL,
                # always active: an empty sentence answers with what to write (UX review)
                # the field's text goes WITH the tap: `on_change` is debounced, and a tap
                # right after typing would otherwise propose the previous sentence
                on_click=PartsStartState.propose(_typed_story()),
                size="3",
                min_height=_TOUCH,
                width=["100%", "auto"],
            ),
            # «Prefiero armarlas yo»: hidden until UI-4's sheet (`MANUAL_PARTS_ENABLED`)
            *([_manual_button()] if vm.MANUAL_PARTS_ENABLED else []),
            rx.button(
                vm.CLOSE_LABEL,
                on_click=PartsStartState.close_card,
                variant="ghost",
                color_scheme="gray",
                size="3",
                min_height=_TOUCH,
                width=["100%", "auto"],
            ),
            direction=rx.breakpoints(initial="column", sm="row"),
            gap="0.75rem",
            align=rx.breakpoints(initial="stretch", sm="center"),
            wrap="wrap",
            width="100%",
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _proposing() -> rx.Component:
    """«Armando tu propuesta»: a single call that reports no progress, so the bar creeps
    and the stage above it advances by time (`parts_start_vm.STAGE_SECONDS`)."""
    return progress_panel(
        vm.PROGRESS_TITLE,
        steps=PartsStartState.steps,
        creep_seconds=vm.PROGRESS_CREEP_SECONDS,
    )


def parts_start_card() -> rx.Component:
    """The card itself: closed, open with its question, or waiting for the proposal —
    of THIS piece (`CreativeState.parts_piece`)."""
    # a card left by an earlier piece (its sentence, error or wait) shows as new
    fresh = PartsStartState.piece == CreativeState.parts_piece
    return card(
        rx.cond(
            fresh & PartsStartState.proposing,
            _proposing(),
            rx.cond(fresh & PartsStartState.open, _question(), _closed()),
        ),
        padding="1rem",
        role="region",
        aria_label=vm.CARD_ACTION,
    )


def parts_empty_notice() -> rx.Component:
    """Over «Prefiero armarlas yo»'s empty parts: the fact and what to do (§4)."""
    return rx.vstack(
        rx.text(vm.EMPTY_TITLE, size="3", weight="medium"),
        rx.text(vm.EMPTY_BODY, size="2", color=T.TEXT_MUTED),
        spacing="1",
        align_items="start",
        width="100%",
        role="status",
    )
