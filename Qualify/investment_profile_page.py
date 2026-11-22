"""«¿Cuánto te conviene pagar por un cliente?» (m-25091387): five guided questions, the
result with a «Cambiar» per answer, and the offer before the first «Promocionar».
Design: `.claude/ux-perfil-inversion-2026-11-22.md`."""

from __future__ import annotations

import reflex as rx

from .investment_profile_state import EDIT
from .investment_profile_state import InvestmentProfileState as S
from .investment_profile_vm import MARGIN_EXACT, MARGIN_UNKNOWN, OBJECTIVES, PROFILE_ROUTE
from .ui import (
    app_shell,
    callout,
    card,
    choice_card,
    page_body,
    page_header,
    skeleton_card,
    stat_card,
    step_foot,
    step_frame,
    step_head,
    step_sync,
    tone_badge,
)
from .ui import tokens as T


def _muted(text: str | rx.Var) -> rx.Component:
    return rx.text(text, color=T.TEXT_MUTED)


def _option(
    title: str | rx.Var, detail: str, selected: rx.Var[bool], on_select: object
) -> rx.Component:
    return choice_card(
        rx.vstack(
            rx.text(title, weight="medium"),
            rx.text(detail, size="2", color=T.TEXT_MUTED) if detail else rx.fragment(),
            spacing="1",
            align="start",
            width="100%",
        ),
        selected=selected,
        on_select=on_select,
        disabled=S.busy,
        min_height="44px",
        width="100%",
        text_align="left",
    )


def _field(
    label: str, name: str, value: rx.Var[str], placeholder: str, echo: rx.Var[str] | None = None
) -> rx.Component:
    field_id = "perfil-" + name
    return rx.vstack(
        rx.el.label(label, html_for=field_id, font_weight="500"),
        rx.input(
            id=field_id,
            value=value,
            on_change=lambda text: S.answer(name, text),
            placeholder=placeholder,
            input_mode="numeric",
            max_length=40,
            disabled=S.busy,
            size="3",
            min_height="44px",
            width="100%",
        ),
        *([rx.cond(echo != "", rx.text(echo, weight="medium"))] if echo is not None else []),
        spacing="2",
        width="100%",
    )


def _objective() -> rx.Component:
    return rx.vstack(
        _muted("Elige lo que más le sirve a tu negocio. Puedes cambiarlo en cada anuncio."),
        rx.vstack(
            *[
                _option(title, detail, S.answers.objective == key, S.answer("objective", key))
                for key, title, detail in OBJECTIVES
            ],
            role="radiogroup",
            aria_label="Qué quieres que haga la gente",
            spacing="3",
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


def _ticket() -> rx.Component:
    return rx.vstack(
        _muted(
            "Piensa en una compra normal, no en la más grande. Si vendes cosas de precios "
            "muy distintos, usa el promedio."
        ),
        _field(
            "Lo que paga en una compra, en pesos",
            "ticket",
            S.answers.ticket,
            "Ejemplo: 20.000",
            S.ticket_echo,
        ),
        rx.text(
            "Por ejemplo: un combo de comida, $20.000 · un paquete de viaje, $1.500.000 · "
            "una asesoría, $150.000.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        spacing="4",
        width="100%",
    )


def _margin() -> rx.Component:
    return rx.vstack(
        _muted(S.margin_help),
        rx.text(
            "Por ejemplo: vendes un combo en $20.000. Los ingredientes y el empaque te "
            "cuestan $8.000. Te quedan $12.000.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.vstack(
            rx.foreach(
                S.margin_choices,
                lambda row: choice_card(
                    rx.text(row[1], weight="medium"),
                    selected=S.answers.margin_choice == row[0],
                    on_select=S.answer("margin_choice", row[0]),
                    disabled=S.busy,
                    min_height="44px",
                    width="100%",
                    text_align="left",
                ),
            ),
            role="radiogroup",
            aria_label="Cuánto te queda de cada venta",
            spacing="3",
            width="100%",
        ),
        rx.cond(
            S.answers.margin_choice == MARGIN_EXACT,
            _field(
                "Me quedan, en pesos", "margin_exact", S.answers.margin_exact, "Ejemplo: 12.000"
            ),
        ),
        rx.cond(S.answers.margin_choice == MARGIN_UNKNOWN, callout(S.unknown_note, "info")),
        spacing="4",
        width="100%",
    )


def _clients() -> rx.Component:
    return rx.vstack(
        _muted(
            "Sin que te falte tiempo para atenderlos bien. Así no pagas por clientes que "
            "no vas a poder atender."
        ),
        _field("Clientes nuevos por semana", "clients", S.answers.clients, "Ejemplo: 15"),
        spacing="4",
        width="100%",
    )


def _cap() -> rx.Component:
    return rx.vstack(
        _muted("Es tu tope. Ningún anuncio se crea sin que tú lo apruebes."),
        _field("Tope al mes, en pesos", "cap", S.answers.cap, "Ejemplo: 200.000", S.cap_echo),
        spacing="4",
        width="100%",
    )


def _steps() -> rx.Component:
    foot = rx.cond(
        S.mode == EDIT,
        step_foot(
            S.primary_label,
            step=S.step,
            on_primary=S.next_step,
            primary_busy=S.busy,
            reason=S.reason,
        ),
        step_foot(
            S.primary_label,
            step=S.step,
            on_primary=S.next_step,
            on_back=S.back_step,
            primary_busy=S.busy,
            reason=S.reason,
        ),
    )
    return step_frame(
        step_sync(S.step, S.direction),
        rx.cond(S.error != "", callout(S.error, "error")),
        rx.cond(S.notice != "", callout(S.notice, "info")),
        rx.match(
            S.step,
            (1, _objective()),
            (2, _ticket()),
            (3, _margin()),
            (4, _clients()),
            _cap(),
        ),
        head=step_head(
            S.title,
            step=S.step,
            total=5,
            back_label=S.back_label,
            on_exit=S.leave,
            show_progress=S.mode != EDIT,
        ),
        foot=foot,
        step=S.step,
        direction=S.direction,
        on_pop=S.read_step,
    )


def _answer_row(row: rx.Var[tuple[int, str, str]]) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.text(row[1], size="2", color=T.TEXT_MUTED),
            rx.text(row[2], weight="medium", overflow_wrap="anywhere"),
            spacing="0",
            align_items="start",
            flex="1",
            min_width="0",
        ),
        rx.button(
            "Cambiar",
            on_click=S.change(row[0]),
            variant="ghost",
            min_height="44px",
            disabled=S.busy,
            aria_label="Cambiar " + row[1].to(str).lower(),
        ),
        align="center",
        justify="between",
        spacing="3",
        width="100%",
    )


def _next() -> rx.Component:
    return rx.cond(
        S.return_to != "",
        rx.link(rx.button("Seguir con tu anuncio", size="3", min_height="44px"), href=S.return_to),
        rx.vstack(
            rx.link(
                rx.button("Promocionar una publicación", size="3", min_height="44px"),
                href="/drafts",
            ),
            rx.link(
                "Volver a Anuncios",
                href="/promotions",
                min_height="44px",
                display="inline-flex",
                align_items="center",
            ),
            spacing="2",
            align_items="start",
        ),
    )


def _result() -> rx.Component:
    return rx.fragment(
        page_header("Anuncios", "Lo que te conviene pagar por cada cliente nuevo."),
        page_body(
            rx.cond(S.notice != "", callout(S.notice, "ok")),
            rx.cond(S.error != "", callout(S.error, "error")),
            rx.box(stat_card("Por cada cliente nuevo", S.headline), width="100%"),
            rx.cond(
                S.profile.estimated,
                rx.vstack(
                    tone_badge("Aproximado", "warn"),
                    _muted("Cuando sepas cuánto te queda, toca Cambiar en «Lo que te queda»."),
                    spacing="1",
                    align_items="start",
                ),
            ),
            rx.text(S.meaning),
            _muted(S.how_computed),
            _muted(
                "No es lo que va a costar un anuncio: es tu límite para saber si te conviene. "
                "Contamos solo la primera compra; si tus clientes vuelven, cada uno vale más."
            ),
            card(
                rx.vstack(
                    rx.heading("Tus respuestas", size="3", as_="h2"),
                    rx.foreach(S.answer_rows, _answer_row),
                    spacing="2",
                    width="100%",
                ),
                width="100%",
            ),
            _next(),
        ),
    )


def _offer() -> rx.Component:
    return rx.fragment(
        page_header("Antes de tu primer anuncio"),
        page_body(
            rx.text(
                "Con 5 preguntas sobre tu negocio te decimos cuánto te conviene pagar por "
                "cada cliente. Así sabes si un anuncio te deja ganancia."
            ),
            rx.button("Responder (1 minuto)", on_click=S.start, size="3", min_height="44px"),
            rx.button(
                "Ahora no, seguir con el anuncio",
                on_click=S.skip_offer,
                variant="outline",
                size="3",
                min_height="44px",
            ),
        ),
    )


def _waiting() -> rx.Component:
    return rx.fragment(
        page_header("Anuncios", "Lo que te conviene pagar por cada cliente nuevo."),
        page_body(
            rx.cond(
                S.loading,
                skeleton_card(4),
                rx.cond(
                    S.error != "",
                    rx.vstack(
                        callout(S.error, "error"),
                        rx.button(
                            "Volver a consultar",
                            on_click=S.load,
                            variant="outline",
                            min_height="44px",
                        ),
                        spacing="3",
                        align_items="start",
                        width="100%",
                    ),
                    rx.vstack(
                        callout(S.unsupported_message, "info"),
                        rx.link(
                            "Volver a Anuncios",
                            href="/promotions",
                            min_height="44px",
                            display="inline-flex",
                            align_items="center",
                        ),
                        spacing="3",
                        align_items="start",
                        width="100%",
                    ),
                ),
            ),
        ),
    )


def investment_profile_index() -> rx.Component:
    return app_shell(
        rx.cond(
            S.showing_steps,
            _steps(),
            rx.cond(
                S.showing_offer,
                _offer(),
                rx.cond(S.profile.exists & ~S.loading, _result(), _waiting()),
            ),
        )
    )


def investment_profile_card() -> rx.Component:
    """The Anuncios list's entry: the question until answered, then the number."""
    return rx.cond(
        S.loading | ~S.supported,
        rx.fragment(),
        card(
            rx.vstack(
                rx.text(
                    rx.cond(
                        S.profile.exists,
                        S.card_title,
                        "¿Cuánto te conviene pagar por un cliente?",
                    ),
                    weight="medium",
                ),
                rx.text(
                    rx.cond(
                        S.profile.exists,
                        "Con lo que nos contaste de tu negocio.",
                        "Responde 5 preguntas y te lo calculamos. Toma un minuto.",
                    ),
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.link(
                    rx.cond(S.profile.exists, "Ver o cambiar", "Calcularlo"),
                    href=PROFILE_ROUTE,
                    min_height="44px",
                    display="inline-flex",
                    align_items="center",
                ),
                spacing="1",
                align_items="start",
                width="100%",
            ),
            width="100%",
        ),
    )
