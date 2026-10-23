"""«Preguntas iniciales» (Instagram Ice Breakers, m-24789472, phase 2 UI): a drawer opened
from Conversaciones' header for the selected account — the place where the taps of
these questions arrive, so the person sets them up where they will answer them.

Same pattern as «Administrar plantillas» (`conversations_page.templates_manager`): the
`ui.drawer` primitive, rows as cards with icon tools («Subir», «Bajar», «Quitar»), and
confirmations IN PLACE (a second dialog over the drawer would trap focus twice). States
are tones through `signal_pill` / `tone_badge` / `callout`; content loading is a
skeleton, work in progress is the button's own `loading`. The page reads
`IceBreakersState` only.
"""

from __future__ import annotations

import reflex as rx

from .ice_breakers_state import IceBreakersState
from .ice_breakers_vm import (
    ANSWER_NOTE,
    EXPLANATION,
    MAX_QUESTION_CHARS,
    UNAVAILABLE_NOTE,
    QuestionRowVM,
)
from .ui import callout, card, drawer, signal_pill, skeleton_rows, tone_badge
from .ui import tokens as T

S = IceBreakersState
_TONES = ("ok", "warn", "error", "info", "neutral")


def open_button(connection_id: rx.Var[str]) -> rx.Component:
    """The door, for Conversaciones' header: «Preguntas iniciales» of `connection_id`."""
    return rx.button(
        rx.icon("message-circle-question", size=T.ICON_SM),
        "Preguntas iniciales",
        on_click=S.open_panel(connection_id),
        variant="soft",
        size="2",
        type="button",
        **T.tone_scheme("neutral"),
    )


def _status_pill() -> rx.Component:
    return rx.match(
        S.status.tone,
        *[(t, signal_pill(S.status.label, t, size="2")) for t in _TONES[:-1]],
        signal_pill(S.status.label, "neutral", size="2"),
    )


def _status() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            _status_pill(),
            rx.cond(
                S.status.verified,
                tone_badge("Comprobado en Instagram", "ok", icon="badge-check", size="2"),
                rx.fragment(),
            ),
            spacing="2",
            align="center",
            flex_wrap="wrap",
        ),
        rx.cond(
            S.status.detail != "",
            rx.text(S.status.detail, size="1", color=T.TEXT_MUTED),
            rx.fragment(),
        ),
        spacing="1",
        width="100%",
    )


def _explanation() -> rx.Component:
    return rx.hstack(
        rx.icon("smartphone", size=T.ICON_MD, color=T.TEXT_MUTED, flex_shrink="0"),
        rx.vstack(
            rx.text(EXPLANATION, size="2"),
            rx.text(ANSWER_NOTE, size="2", color=T.TEXT_MUTED),
            spacing="1",
            min_width="0",
        ),
        spacing="3",
        align="start",
        width="100%",
    )


def _unavailable() -> rx.Component:
    return rx.cond(
        S.available,
        rx.fragment(),
        callout(
            rx.vstack(
                rx.text(UNAVAILABLE_NOTE, size="2"),
                rx.cond(
                    S.availability_label != "",
                    tone_badge(S.availability_label, "warn", icon="circle-help"),
                    rx.fragment(),
                ),
                rx.cond(
                    S.unavailable_reason != "",
                    rx.text(S.unavailable_reason, size="1", color=T.TEXT_MUTED),
                    rx.fragment(),
                ),
                spacing="2",
                width="100%",
            ),
            "info",
        ),
    )


def _tool(icon: str, label: str, **props) -> rx.Component:
    return rx.tooltip(
        rx.icon_button(
            rx.icon(icon, size=T.ICON_SM),
            variant="ghost",
            size="2",
            type="button",
            aria_label=label,
            **T.tone_scheme("neutral"),
            **props,
        ),
        content=label,
    )


def _row(row: QuestionRowVM, index: rx.Var[int]) -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.text("Pregunta ", index + 1, size="2", weight="medium"),
                rx.spacer(),
                rx.text(row.counter, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                width="100%",
                align="center",
            ),
            rx.input(
                value=row.question,
                on_change=lambda value: S.set_question(index, value),
                placeholder="Ej.: ¿Hacen envíos a domicilio?",
                max_length=MAX_QUESTION_CHARS,
                disabled=S.busy,
                width="100%",
                size="3",
                aria_label="Texto de la pregunta",
            ),
            rx.cond(
                row.error != "",
                rx.text(row.error, size="1", color=T.tone_color("error", 11), role="alert"),
                rx.fragment(),
            ),
            rx.hstack(
                _tool(
                    "arrow-up",
                    "Subir",
                    on_click=S.move_question(index, -1),
                    disabled=row.is_first | S.busy,
                ),
                _tool(
                    "arrow-down",
                    "Bajar",
                    on_click=S.move_question(index, 1),
                    disabled=row.is_last | S.busy,
                ),
                rx.spacer(),
                rx.button(
                    rx.icon("trash-2", size=T.ICON_SM),
                    "Quitar",
                    on_click=S.remove_question(index),
                    disabled=S.busy,
                    variant="ghost",
                    size="2",
                    type="button",
                    **T.tone_scheme("neutral"),
                ),
                width="100%",
                align="center",
                spacing="1",
            ),
            spacing="2",
            width="100%",
        ),
        padding="0.75rem",
        key=row.key,
    )


def _questions() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text("Tus preguntas", size="3", weight="bold"),
            rx.cond(S.at_limit, tone_badge(S.counter, "warn"), tone_badge(S.counter, "neutral")),
            rx.spacer(),
            rx.button(
                rx.icon("plus", size=T.ICON_SM),
                "Agregar pregunta",
                on_click=S.add_question,
                disabled=S.at_limit | S.busy,
                variant="soft",
                size="2",
                type="button",
            ),
            width="100%",
            align="center",
            spacing="2",
            flex_wrap="wrap",
        ),
        rx.cond(
            S.rows.length() == 0,
            rx.text(
                "No tienes preguntas. Agrega al menos una para publicarla.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.vstack(rx.foreach(S.rows, _row), spacing="2", width="100%"),
        ),
        rx.cond(S.form_error != "", callout(S.form_error, "error"), rx.fragment()),
        rx.cond(
            S.dirty,
            rx.hstack(
                rx.text("Tienes cambios sin guardar.", size="1", color=T.TEXT_MUTED),
                rx.button(
                    rx.icon("undo-2", size=T.ICON_SM),
                    "Deshacer cambios",
                    on_click=S.discard_changes,
                    disabled=S.busy,
                    variant="ghost",
                    size="1",
                    type="button",
                    **T.tone_scheme("neutral"),
                ),
                spacing="2",
                align="center",
                flex_wrap="wrap",
            ),
            rx.fragment(),
        ),
        rx.button(
            rx.icon("list-restart", size=T.ICON_SM),
            "Restaurar las preguntas por defecto",
            on_click=S.ask_confirm("restore"),
            disabled=~S.can_restore,
            variant="ghost",
            size="2",
            type="button",
            **T.tone_scheme("neutral"),
        ),
        spacing="3",
        width="100%",
    )


def _body() -> rx.Component:
    return rx.vstack(
        _explanation(),
        rx.cond(
            S.load_error != "",
            rx.vstack(
                callout(S.load_error, "error"),
                rx.button(
                    rx.icon("refresh-cw", size=T.ICON_SM),
                    "Reintentar",
                    on_click=S.load,
                    variant="soft",
                    size="2",
                    type="button",
                    **T.tone_scheme("neutral"),
                ),
                spacing="2",
                width="100%",
            ),
            rx.cond(
                S.ready,
                rx.vstack(
                    _status(),
                    _unavailable(),
                    rx.cond(
                        S.remote_error != "",
                        callout(S.remote_error, "error"),
                        rx.fragment(),
                    ),
                    _questions(),
                    spacing="4",
                    width="100%",
                ),
                skeleton_rows(4, height="5.5rem", radius=T.RADIUS_CARD),
            ),
        ),
        spacing="4",
        width="100%",
    )


def _confirm_block() -> rx.Component:
    yes_label = rx.match(
        S.confirming,
        ("publish", "Sí, publicar"),
        ("remove", "Sí, quitar"),
        "Sí, restaurar",
    )
    return rx.vstack(
        rx.text(S.confirm_message, size="2", weight="medium"),
        rx.hstack(
            rx.button(
                "Cancelar",
                on_click=S.cancel_confirm,
                variant="soft",
                size="2",
                type="button",
                **T.tone_scheme("neutral"),
            ),
            rx.cond(
                S.confirming == "remove",
                rx.button(
                    yes_label,
                    on_click=S.confirm,
                    size="2",
                    type="button",
                    **T.tone_scheme("error"),
                ),
                rx.button(yes_label, on_click=S.confirm, size="2", type="button"),
            ),
            spacing="2",
            justify="end",
            width="100%",
            flex_wrap="wrap",
        ),
        spacing="2",
        width="100%",
    )


def _actions() -> rx.Component:
    return rx.vstack(
        rx.flex(
            rx.button(
                rx.icon("check", size=T.ICON_SM),
                "Guardar",
                on_click=S.save,
                loading=S.working == "save",
                disabled=~S.dirty | (S.busy & (S.working != "save")) | ~S.ready,
                variant="soft",
                size="2",
                type="button",
            ),
            rx.button(
                rx.icon("send", size=T.ICON_SM),
                "Publicar en Instagram",
                on_click=S.ask_confirm("publish"),
                loading=S.working == "publish",
                disabled=~S.can_publish,
                size="2",
                type="button",
            ),
            gap="0.5rem",
            wrap="wrap",
            justify="end",
            width="100%",
        ),
        rx.flex(
            rx.button(
                rx.icon("scan-search", size=T.ICON_SM),
                "Comprobar en Instagram",
                on_click=S.check_remote,
                loading=S.working == "check",
                disabled=(S.busy & (S.working != "check")) | ~S.ready,
                variant="ghost",
                size="2",
                type="button",
                **T.tone_scheme("neutral"),
            ),
            rx.button(
                rx.icon("circle-x", size=T.ICON_SM),
                "Quitar de Instagram",
                on_click=S.ask_confirm("remove"),
                loading=S.working == "remove",
                disabled=~S.can_remove,
                variant="ghost",
                size="2",
                type="button",
                **T.tone_scheme("error"),
            ),
            gap="0.5rem",
            wrap="wrap",
            justify="end",
            width="100%",
        ),
        rx.cond(
            S.ready & ~S.available,
            rx.text(
                "Publicar y quitar todavía no están disponibles.",
                size="1",
                color=T.TEXT_MUTED,
                text_align="right",
                width="100%",
            ),
            rx.fragment(),
        ),
        spacing="2",
        width="100%",
    )


def ice_breakers_panel() -> rx.Component:
    """The drawer. Mount once per page (it is a dialog)."""
    return drawer(
        _body(),
        open=S.panel_open,
        on_open_change=S.set_panel_open,
        title=S.panel_title,
        icon="message-circle-question",
        description="Preguntas listas para que te escriban con un toque.",
        footer=rx.cond(S.confirming != "", _confirm_block(), _actions()),
    )


__all__ = ["ice_breakers_panel", "open_button"]
