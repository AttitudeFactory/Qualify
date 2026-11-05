"""Anuncios: recorded delivery states, dated results and explicit pause consent."""

from __future__ import annotations

import reflex as rx

from .ad_results_state import AdResultsState as S
from .ad_results_vm import AdDayVM, AdResultVM
from .ui import (
    app_shell,
    callout,
    card,
    empty_state,
    page_body,
    page_header,
    signal_pill,
    skeleton_card,
)
from .ui import tokens as T


def _fact(label: str, value: str | rx.Var[str]) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="1", color=T.TEXT_MUTED),
        rx.text(value, size="3", weight="medium", overflow_wrap="anywhere"),
        spacing="1",
        align_items="start",
        min_width="0",
        width="100%",
    )


def _ad(row: rx.Var[AdResultVM]) -> rx.Component:
    return rx.link(
        card(
            rx.vstack(
                signal_pill(row.status_label, row.tone),
                rx.cond(
                    row.stale | row.refresh_failed,
                    rx.text("Actualiza con Meta para comprobar el estado actual.", size="2"),
                ),
                rx.text(row.title, weight="medium", class_name="q-clamp-3"),
                rx.text(row.account, size="2", color=T.TEXT_MUTED, overflow_wrap="anywhere"),
                _fact("Presupuesto aprobado al crear", row.approved_budget),
                rx.text("Última consulta: " + row.checked_label, size="1", color=T.TEXT_MUTED),
                rx.cond(
                    row.rejection_reason != "",
                    rx.text(row.rejection_reason, size="2", overflow_wrap="anywhere"),
                ),
                rx.text("Ver estado y resultados →", size="2"),
                align_items="start",
                spacing="3",
                width="100%",
            ),
            interactive=True,
            width="100%",
        ),
        href="/promotions/" + row.id,
        underline="none",
        color="inherit",
        display="block",
        min_height="44px",
        width="100%",
    )


def ad_results_index() -> rx.Component:
    return app_shell(
        page_header("Anuncios", "Revisa el estado de tus promociones y en qué se fue tu dinero."),
        page_body(
            rx.cond(S.error != "", callout(S.error, "error")),
            rx.cond(
                S.loading,
                skeleton_card(4),
                rx.cond(
                    S.ads.length() > 0,
                    rx.vstack(rx.foreach(S.ads, _ad), spacing="4", width="100%"),
                    rx.cond(
                        S.error != "",
                        rx.button(
                            "Volver a consultar",
                            on_click=S.load_list,
                            min_height="44px",
                            variant="outline",
                        ),
                        empty_state(
                            "megaphone",
                            "Todavía no tienes anuncios aquí",
                            "Cuando prepares una promoción desde una publicación de Instagram, "
                            "podrás consultar aquí su estado y sus resultados.",
                            action=rx.link(
                                "Ver tus publicaciones",
                                href="/drafts",
                                min_height="44px",
                                display="inline-flex",
                                align_items="center",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def _daily(row: rx.Var[AdDayVM]) -> rx.Component:
    return card(
        rx.vstack(
            rx.heading(row.label, size="4", as_="h3"),
            rx.grid(
                _fact("Gasto", row.spend),
                _fact("Clics", row.clicks),
                _fact("Personas que lo vieron", row.reach),
                _fact("Veces que se mostró", row.impressions),
                columns=rx.breakpoints(initial="1", sm="2"),
                spacing="4",
                width="100%",
            ),
            rx.el.details(
                rx.el.summary("Ver costos y proporción de clics", min_height="44px"),
                rx.vstack(
                    _fact("Clics por cada 100 veces que se mostró", row.ctr),
                    _fact("Costo por clic", row.cpc),
                    _fact("Costo por mil veces que se mostró", row.cpm),
                    align_items="start",
                    spacing="3",
                    width="100%",
                ),
                width="100%",
            ),
            spacing="4",
            align_items="start",
            width="100%",
        ),
        width="100%",
    )


def _pause_confirmation() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("¿Pausar este anuncio?"),
            rx.alert_dialog.description(
                "Pediremos a Meta que deje de mostrarlo. La pausa no borra el gasto ya "
                "realizado y puede tardar en reflejarse."
            ),
            rx.text(S.detail.promotion.title, size="2", class_name="q-clamp-3"),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button("Seguir viendo resultados", variant="outline", min_height="44px"),
                    on_click=S.dismiss_pause(False),
                ),
                rx.button(
                    "Confirmar pausa",
                    on_click=S.confirm_pause,
                    disabled=S.busy,
                    min_height="44px",
                ),
                direction=rx.breakpoints(initial="column", sm="row"),
                gap="3",
                margin_top="16px",
            ),
            max_width="480px",
        ),
        open=S.pause_open,
        on_open_change=S.dismiss_pause,
    )


def _management() -> rx.Component:
    return card(
        rx.vstack(
            rx.heading("Controla este anuncio", size="4", as_="h2"),
            rx.button(
                "Pausar anuncio",
                on_click=S.ask_pause,
                variant="outline",
                disabled=S.busy | ~S.detail.promotion.can_pause,
                min_height="44px",
                width=rx.breakpoints(initial="100%", sm="auto"),
            ),
            rx.cond(
                ~S.detail.promotion.can_pause,
                rx.text(
                    "La pausa estará disponible cuando podamos comprobar un anuncio "
                    "que siga mostrándose en esta cuenta.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
            ),
            rx.flex(
                rx.button("Reanudar", disabled=True, variant="outline", min_height="44px"),
                rx.button(
                    "Cambiar presupuesto", disabled=True, variant="outline", min_height="44px"
                ),
                rx.button(
                    "Cambiar fecha de fin", disabled=True, variant="outline", min_height="44px"
                ),
                direction=rx.breakpoints(initial="column", sm="row"),
                wrap="wrap",
                gap="3",
                width="100%",
            ),
            callout(
                rx.cond(
                    S.detail.promotion.management_reason != "",
                    S.detail.promotion.management_reason,
                    "Reanudar y cambiar el presupuesto o el final todavía no está habilitado "
                    "desde Qualify. Revisa estos cambios en el Administrador de anuncios de Meta.",
                ),
                "info",
            ),
            rx.text(
                "Por ahora, haz esos cambios en el Administrador de anuncios de Meta.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        width="100%",
    )


def _detail() -> rx.Component:
    return rx.vstack(
        card(
            rx.vstack(
                signal_pill(S.detail.promotion.status_label, S.detail.promotion.tone),
                rx.cond(
                    S.detail.promotion.stale | S.detail.promotion.refresh_failed,
                    callout(
                        "Este es el último estado guardado. "
                        "Actualiza con Meta para comprobar si cambió.",
                        "warn",
                    ),
                ),
                rx.heading(S.detail.promotion.title, size="4", as_="h2", overflow_wrap="anywhere"),
                _fact("Cuenta para anuncios", S.detail.promotion.account),
                _fact("Presupuesto aprobado al crear", S.detail.promotion.approved_budget),
                rx.text(
                    "El presupuesto aprobado es el original; no confirma cambios hechos en Meta.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                _fact("Final aprobado al crear", S.detail.promotion.end_label),
                _fact("Última consulta del estado", S.detail.promotion.checked_label),
                rx.cond(
                    S.detail.promotion.rejection_reason != "",
                    callout(S.detail.promotion.rejection_reason, "error"),
                ),
                rx.button(
                    "Actualizar con Meta",
                    on_click=S.refresh,
                    disabled=S.busy,
                    loading=S.busy,
                    min_height="44px",
                    size="3",
                ),
                rx.text(
                    "Consulta el estado y los resultados. "
                    "No activa anuncios ni cambia su presupuesto.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="3",
                align_items="start",
                width="100%",
            ),
            width="100%",
        ),
        rx.heading("Resultados por día", size="5", as_="h2"),
        rx.text("Última consulta de resultados: " + S.detail.updated_label, size="2"),
        rx.cond(
            S.detail.promotion.timezone_name != "",
            rx.text(
                "Fechas según la cuenta de Meta: " + S.detail.promotion.timezone_name,
                size="2",
                color=T.TEXT_MUTED,
            ),
            callout("La zona horaria de esta cuenta está por comprobar.", "warn"),
        ),
        rx.cond(S.detail.notice != "", callout(S.detail.notice, "info")),
        rx.cond(
            S.detail.insights_stale | S.detail.insights_refresh_failed,
            callout(
                "Estos resultados están pendientes de actualizar. "
                "La fecha de consulta indica cuándo se guardaron.",
                "warn",
            ),
        ),
        rx.cond(
            S.detail.days.length() > 0,
            rx.vstack(rx.foreach(S.detail.days, _daily), spacing="4", width="100%"),
            callout(
                "Todavía no hay resultados diarios disponibles. Actualiza con Meta. "
                "La falta de datos no significa que el gasto sea cero.",
                "info",
            ),
        ),
        _management(),
        _pause_confirmation(),
        spacing="4",
        align_items="start",
        width="100%",
    )


def ad_result_detail_index() -> rx.Component:
    return app_shell(
        page_header("Anuncios", "Estado y resultados de esta promoción."),
        page_body(
            rx.link(
                "← Volver a Anuncios",
                href="/promotions",
                min_height="44px",
                display="inline-flex",
                align_items="center",
            ),
            rx.cond(S.error != "", callout(S.error, "error")),
            rx.cond(S.notice != "", callout(S.notice, "ok")),
            rx.cond(
                S.loading,
                skeleton_card(5),
                rx.cond(
                    S.detail.promotion.id != "",
                    _detail(),
                    rx.button(
                        "Volver a consultar",
                        on_click=S.load_detail,
                        min_height="44px",
                        variant="outline",
                    ),
                ),
            ),
        ),
    )
