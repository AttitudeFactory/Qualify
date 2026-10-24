"""Inicio — `/` (m-24842962, NAV-4; `docs/ux-guia-navegacion.md` N2, N8, N11, N12).

The owner opens the app and sees, in this order:

1. «Hoy tienes» — up to three tappable cards with what waits for them, each opening the
   list already filtered (N11).
2. «Para tu primera publicación» — the checklist with its progress, while a step is
   missing (N2); a finished step stays with ✓ «Listo» and is not a link.
3. «Todo al día» — when nothing waits and nothing is missing, with «Crear publicación»
   (N8: Inicio is never empty).
4. «Así te fue esta semana» — three figures of the last 7 days, each opening its detail;
   with nothing to count and no Instagram, it says what to connect; connected but a
   quiet week, it suggests a new publication (N8).

Only design-system primitives (`page_header`, `section`, `card(interactive=True)`,
`empty_state`, `callout`, `skeleton_card`). One column on a phone; every target is a
whole card or a full-width button of at least 44 px (N12). Nothing depends on hover.
"""

from __future__ import annotations

import reflex as rx

from .home_state import HomeState
from .home_vm import CONNECTIONS_URL, CREATE_URL, FirstStepVM, TodayCardVM, WeekStatVM
from .ui import (
    app_shell,
    callout,
    card,
    empty_state,
    page_body,
    page_header,
    section,
    skeleton_card,
    tone_badge,
)
from .ui import tokens as T

TITLE = "Inicio"
SUBTITLE = "Lo que te toca hoy y cómo te fue esta semana"

_MIN_TARGET = "44px"


def _card_link(href: rx.Var[str] | str, *children: rx.Component) -> rx.Component:
    """A whole card that is a real link (keyboard and «atrás» work as with any link).

    No `aria_label`: the visible text — figure included — already names the link."""
    return rx.link(
        card(*children, interactive=True, min_height=_MIN_TARGET),
        href=href,
        underline="none",
        width="100%",
        display="block",
        color="inherit",
    )


def _today_card(item: rx.Var[TodayCardVM]) -> rx.Component:
    return _card_link(
        item.href,
        rx.hstack(
            rx.icon(item.icon, size=T.ICON_MD, color=T.tone_color("accent", 10)),
            rx.text(item.label, size="3", weight="medium", flex="1"),
            rx.icon("chevron-right", size=T.ICON_MD, color=T.TEXT_MUTED),
            align="center",
            spacing="3",
            width="100%",
        ),
    )


def _today() -> rx.Component:
    return rx.cond(
        HomeState.has_today,
        section(
            "Hoy tienes",
            rx.grid(
                rx.foreach(HomeState.today, _today_card),
                columns=rx.breakpoints(initial="1", md="3"),
                spacing="3",
                width="100%",
            ),
        ),
    )


def _pending_step(step: rx.Var[FirstStepVM]) -> rx.Component:
    return _card_link(
        step.href,
        rx.hstack(
            rx.icon("circle", size=T.ICON_MD, color=T.TEXT_MUTED),
            rx.text(step.label, size="3", flex="1"),
            rx.icon(step.icon, size=T.ICON_MD, color=T.tone_color("accent", 10)),
            align="center",
            spacing="3",
            width="100%",
        ),
    )


def _done_step(step: rx.Var[FirstStepVM]) -> rx.Component:
    # Done: not a link any more; the ✓ and the word «Listo» say it (not the icon alone).
    return card(
        rx.hstack(
            rx.icon("circle-check", size=T.ICON_MD, color=T.tone_color("ok", 10)),
            rx.text(step.label, size="3", flex="1", color=T.TEXT_MUTED),
            tone_badge("Listo", "ok"),
            align="center",
            spacing="3",
            width="100%",
        ),
        min_height=_MIN_TARGET,
    )


def _first_step(step: rx.Var[FirstStepVM]) -> rx.Component:
    return rx.cond(step.done, _done_step(step), _pending_step(step))


def _first_steps() -> rx.Component:
    return rx.cond(
        HomeState.first_steps_pending,
        section(
            "Para tu primera publicación",
            rx.vstack(
                rx.foreach(HomeState.first_steps, _first_step),
                spacing="2",
                width="100%",
            ),
            description=HomeState.first_steps_progress,
        ),
    )


def _full_width_button(label: str, icon: str, href: str) -> rx.Component:
    return rx.link(
        rx.button(
            rx.icon(icon, size=T.ICON_MD),
            label,
            size="3",
            width="100%",
            min_height=_MIN_TARGET,
        ),
        href=href,
        underline="none",
        width="100%",
        max_width="20rem",
    )


def _all_clear() -> rx.Component:
    return rx.cond(
        HomeState.all_clear,
        card(
            empty_state(
                "circle-check",
                "Todo al día",
                "¿Preparamos la próxima publicación?",
                action=_full_width_button("Crear publicación", "wand-sparkles", CREATE_URL),
            ),
        ),
    )


def _week_stat(stat: rx.Var[WeekStatVM]) -> rx.Component:
    # The figure in the accent, the words in text tokens (same anatomy as `stat_card`).
    return _card_link(
        stat.href,
        rx.text(stat.label, size="2", color=T.TEXT_MUTED),
        rx.text(
            stat.value.to_string(),
            size="7",
            weight="bold",
            color=T.tone_color("accent", 10),
            class_name="q-nums",
            line_height="1.2",
        ),
        rx.text(stat.hint, size="1", color=T.TEXT_MUTED),
    )


def _week() -> rx.Component:
    return section(
        "Así te fue esta semana",
        rx.cond(
            HomeState.week_needs_connection,
            card(
                empty_state(
                    "link",
                    "Conecta tu Instagram para ver esto",
                    "Aquí verás cuántas personas te escribieron, comentaron y hablaron de ti.",
                    action=_full_width_button("Conectar mi Instagram", "link", CONNECTIONS_URL),
                ),
            ),
            rx.cond(
                HomeState.week_quiet,
                card(
                    empty_state(
                        "message-circle",
                        "Esta semana todavía nadie te escribió",
                        "Una publicación nueva ayuda a que te escriban.",
                        action=_full_width_button("Crear publicación", "wand-sparkles", CREATE_URL),
                    ),
                ),
                rx.grid(
                    rx.foreach(HomeState.week, _week_stat),
                    columns=rx.breakpoints(initial="1", sm="3"),
                    spacing="3",
                    width="100%",
                ),
            ),
        ),
        description="Los últimos 7 días",
    )


def _loading() -> rx.Component:
    return rx.vstack(
        skeleton_card(2),
        skeleton_card(2),
        spacing="3",
        width="100%",
    )


def _error() -> rx.Component:
    return rx.vstack(
        callout(HomeState.error, "error"),
        rx.cond(
            HomeState.session_lost,
            _full_width_button("Iniciar sesión", "log-in", "/login"),
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_MD),
                "Reintentar",
                on_click=HomeState.load,
                variant="soft",
                size="3",
                min_height=_MIN_TARGET,
            ),
        ),
        spacing="3",
        align_items="start",
        width="100%",
    )


def home_index() -> rx.Component:
    return app_shell(
        page_header("Inicio", SUBTITLE),
        page_body(
            rx.cond(
                HomeState.loading,
                _loading(),
                rx.cond(
                    HomeState.error != "",
                    _error(),
                    rx.vstack(
                        _today(),
                        _first_steps(),
                        _all_clear(),
                        _week(),
                        spacing="6",
                        width="100%",
                    ),
                ),
            ),
        ),
    )


__all__ = ["SUBTITLE", "TITLE", "home_index"]
