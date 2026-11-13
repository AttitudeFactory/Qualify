"""Anuncios: recorded delivery states, dated results and explicit pause consent."""

from __future__ import annotations

import reflex as rx
from qualify_api.ads.status_webhook import SUBSCRIBE_OFFER

from .ad_results_state import AdResultsState as S
from .ad_results_vm import URGENT_PAUSE, AdDayVM, AdResultVM, AlertAccountVM
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


def _alert_account(row: rx.Var[AlertAccountVM]) -> rx.Component:
    return rx.cond(
        S.alerts_on.contains(row.id),
        signal_pill(
            rx.cond(
                S.alert_accounts.length() > 1, "Avisos activados: " + row.name, "Avisos activados"
            ),
            "ok",
            size="2",
        ),
        rx.button(
            rx.cond(
                S.alert_accounts.length() > 1, "Activar avisos de " + row.name, "Activar avisos"
            ),
            on_click=S.ask_alerts(row.id),
            disabled=S.alerts_busy,
            loading=S.alerts_busy & (S.alert_target.id == row.id),
            variant="outline",
            min_height="44px",
            width=rx.breakpoints(initial="100%", sm="auto"),
        ),
    )


def _alerts() -> rx.Component:
    return rx.cond(
        S.alert_accounts.length() > 0,
        card(
            rx.vstack(
                rx.heading("Avisos de Meta", size="3", as_="h2"),
                rx.text(SUBSCRIBE_OFFER, size="2"),
                rx.cond(S.alerts_notice != "", callout(S.alerts_notice, "ok")),
                rx.cond(S.alerts_error != "", callout(S.alerts_error, "error")),
                rx.foreach(S.alert_accounts, _alert_account),
                rx.alert_dialog.root(
                    rx.alert_dialog.content(
                        rx.alert_dialog.title("¿Activar los avisos de Meta?"),
                        rx.alert_dialog.description(
                            "Meta nos avisará cuando revise o detenga un anuncio de la cuenta "
                            + S.alert_target.name
                            + ". No cambia tus anuncios ni tu presupuesto."
                        ),
                        rx.flex(
                            rx.alert_dialog.cancel(
                                rx.button("Ahora no", variant="outline", min_height="44px"),
                            ),
                            rx.button(
                                "Activar avisos",
                                on_click=S.confirm_alerts,
                                disabled=S.alerts_busy,
                                loading=S.alerts_busy,
                                min_height="44px",
                            ),
                            direction=rx.breakpoints(initial="column", sm="row"),
                            gap="3",
                            margin_top="16px",
                        ),
                        max_width="480px",
                    ),
                    open=S.alert_target.id != "",
                    on_open_change=S.dismiss_alerts,
                ),
                spacing="3",
                align_items="start",
                width="100%",
            ),
            width="100%",
        ),
    )


def ad_results_index() -> rx.Component:
    return app_shell(
        page_header("Anuncios", "Revisa el estado de tus promociones y en qué se fue tu dinero."),
        page_body(
            card(
                rx.vstack(
                    rx.link(
                        "Formularios para clientes interesados",
                        href="/promotions/forms",
                        weight="medium",
                        min_height="44px",
                        display="inline-flex",
                        align_items="center",
                    ),
                    rx.text(
                        "Las preguntas que llenan quienes quieren cotizar o que los contactes.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                width="100%",
            ),
            rx.cond(S.error != "", callout(S.error, "error")),
            rx.cond(S.loading, rx.fragment(), _alerts()),
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


def _edit_primary_action(review_ready: bool | rx.Var[bool]) -> rx.Component:
    return rx.cond(
        review_ready,
        rx.button(
            rx.cond(S.edit_action == "budget_down", "Guardar presupuesto", "Confirmar cambio"),
            on_click=S.confirm_change,
            disabled=~S.can_confirm_edit,
            min_height="44px",
        ),
        rx.button(
            "Comprobar cambio",
            on_click=S.prepare_change,
            disabled=S.busy | S.change_pending,
            min_height="44px",
        ),
    )


def _edit_confirmation() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(S.edit_title),
            rx.dialog.description(
                "Primero comprobaremos los valores con Meta. Solo cambiaremos el anuncio "
                "después de tu confirmación."
            ),
            rx.vstack(
                rx.cond(S.error != "", callout(S.error, "error")),
                rx.cond(S.edit_warning != "", callout(S.edit_warning, "warn")),
                rx.cond(S.change_pending, callout(URGENT_PAUSE, "warn")),
                rx.cond(
                    S.edit_action == "budget",
                    rx.vstack(
                        rx.text(
                            "Nuevo presupuesto total en pesos colombianos",
                            as_="label",
                            html_for="ad-edit-budget",
                        ),
                        rx.input(
                            id="ad-edit-budget",
                            value=S.edit_budget_total,
                            on_change=S.set_edit_budget_total,
                            input_mode="numeric",
                            disabled=S.change_pending,
                            min_height="44px",
                            width="100%",
                        ),
                        rx.text(
                            "Escribe pesos completos, sin puntos ni comas. "
                            "El nuevo total debe ser mayor al actual.",
                            size="2",
                        ),
                        width="100%",
                        align_items="start",
                    ),
                ),
                rx.cond(
                    S.edit_action == "budget_down",
                    rx.vstack(
                        rx.text(
                            "Nuevo presupuesto total en pesos colombianos",
                            as_="label",
                            html_for="ad-edit-budget-down",
                        ),
                        rx.input(
                            id="ad-edit-budget-down",
                            value=S.edit_budget_total,
                            on_change=S.set_edit_budget_total,
                            input_mode="numeric",
                            disabled=S.change_pending,
                            aria_describedby="ad-edit-floor",
                            min_height="44px",
                            width="100%",
                        ),
                        rx.text(
                            rx.cond(
                                S.floor_loading,
                                "Consultando con Meta cuánto puedes bajarlo…",
                                S.floor_label,
                            ),
                            id="ad-edit-floor",
                            size="2",
                            weight="medium",
                        ),
                        rx.text(
                            "Escribe pesos completos, sin puntos ni comas. "
                            "Es el total para todo el anuncio, no por día.",
                            size="2",
                        ),
                        width="100%",
                        align_items="start",
                    ),
                ),
                rx.cond(
                    S.edit_action == "end_time",
                    rx.vstack(
                        rx.text("Nueva fecha y hora de final", as_="label", html_for="ad-edit-end"),
                        rx.input(
                            id="ad-edit-end",
                            type="datetime-local",
                            value=S.edit_end_local,
                            on_change=S.set_edit_end_local,
                            disabled=S.change_pending,
                            min_height="44px",
                            width="100%",
                        ),
                        rx.text("Zona horaria: " + S.detail.promotion.timezone_name, size="2"),
                        width="100%",
                        align_items="start",
                    ),
                ),
                rx.cond(
                    S.edit_action == "resume",
                    rx.text(
                        "Al reanudar, Meta podrá volver a mostrar el anuncio y gastar "
                        "dentro del presupuesto aprobado.",
                        size="2",
                    ),
                ),
                rx.cond(
                    S.edit_review.ready,
                    card(
                        rx.vstack(
                            rx.text(S.edit_review.summary, weight="medium"),
                            rx.cond(
                                S.edit_review.budget_changed,
                                rx.vstack(
                                    _fact("Presupuesto total actual", S.edit_review.current_budget),
                                    _fact(
                                        "Presupuesto total después del cambio",
                                        S.edit_review.new_budget,
                                    ),
                                    spacing="3",
                                    width="100%",
                                ),
                            ),
                            rx.cond(
                                S.edit_review.end_changed,
                                rx.vstack(
                                    _fact("Final actual", S.edit_review.current_end),
                                    _fact("Final después del cambio", S.edit_review.new_end),
                                    spacing="3",
                                    width="100%",
                                ),
                            ),
                            rx.checkbox(
                                "Confirmo este cambio y el gasto que puede permitir en Meta.",
                                checked=S.edit_consent,
                                on_change=S.set_edit_consent,
                                disabled=S.busy | S.change_pending,
                                min_height="44px",
                            ),
                            width="100%",
                            align_items="start",
                            spacing="3",
                        ),
                        width="100%",
                    ),
                ),
                rx.flex(
                    rx.button(
                        "Volver a resultados",
                        variant="outline",
                        on_click=S.dismiss_edit(False),
                        disabled=S.busy,
                        min_height="44px",
                    ),
                    _edit_primary_action(S.edit_review.ready),
                    direction=rx.breakpoints(initial="column", sm="row"),
                    gap="3",
                    width="100%",
                ),
                spacing="4",
                width="100%",
                align_items="start",
                margin_top="16px",
            ),
            max_width="600px",
        ),
        open=S.edit_open,
        on_open_change=S.dismiss_edit,
    )


def _management() -> rx.Component:
    return card(
        rx.vstack(
            rx.heading("Controla este anuncio", size="4", as_="h2"),
            rx.cond(
                S.change_pending
                | S.detail.promotion.operation_pending
                | S.detail.promotion.stale
                | S.detail.promotion.refresh_failed,
                callout(URGENT_PAUSE, "warn"),
            ),
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
                rx.button(
                    "Reanudar",
                    on_click=S.open_edit("resume"),
                    disabled=S.busy | ~S.detail.promotion.can_resume | S.change_pending,
                    variant="outline",
                    min_height="44px",
                ),
                rx.button(
                    "Aumentar presupuesto",
                    on_click=S.open_edit("budget"),
                    disabled=S.busy | ~S.detail.promotion.can_manage | S.change_pending,
                    variant="outline",
                    min_height="44px",
                ),
                rx.button(
                    "Bajar presupuesto",
                    on_click=S.open_edit("budget_down"),
                    disabled=S.busy | ~S.detail.promotion.can_manage | S.change_pending,
                    variant="outline",
                    min_height="44px",
                ),
                rx.button(
                    "Cambiar fecha de fin",
                    on_click=S.open_edit("end_time"),
                    disabled=S.busy | ~S.detail.promotion.can_manage | S.change_pending,
                    variant="outline",
                    min_height="44px",
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
                    "Cada cambio requiere comprobar los valores actuales y tu confirmación. "
                    "Si hay un cambio pendiente, actualiza con Meta antes de continuar.",
                ),
                "info",
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        width="100%",
    )


def _detail_facts() -> rx.Component:
    return rx.vstack(
        _fact("Cuenta para anuncios", S.detail.promotion.account),
        _fact("Presupuesto total actual comprobado", S.detail.promotion.current_budget),
        _fact("Final actual comprobado", S.detail.promotion.current_end_label),
        _fact("Presupuesto aprobado al crear", S.detail.promotion.approved_budget),
        rx.text(
            "El presupuesto aprobado es el original; no confirma cambios hechos en Meta.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        _fact("Final aprobado al crear", S.detail.promotion.end_label),
        _fact("Última consulta del estado", S.detail.promotion.checked_label),
        spacing="3",
        align_items="start",
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
                rx.cond(
                    S.detail.promotion.rejection_reason != "",
                    callout(S.detail.promotion.rejection_reason, "error"),
                ),
                rx.cond(
                    S.detail.promotion.rejected,
                    rx.vstack(
                        rx.text(
                            "Este anuncio no se puede volver a enviar. Cambia la imagen o el "
                            "texto de la publicación y prepara una promoción nueva.",
                            size="2",
                        ),
                        rx.link(
                            rx.button("Cambiar imagen o texto", min_height="44px", size="3"),
                            href=S.detail.promotion.fix_href,
                        ),
                        rx.el.details(
                            rx.el.summary("Más detalles", min_height="44px"),
                            _detail_facts(),
                            width="100%",
                        ),
                        spacing="3",
                        align_items="start",
                        width="100%",
                    ),
                    _detail_facts(),
                ),
                rx.button(
                    "Actualizar con Meta",
                    on_click=S.refresh,
                    disabled=S.busy,
                    loading=S.busy,
                    variant=rx.cond(S.detail.promotion.rejected, "outline", "solid"),
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
        card(
            rx.vstack(
                _fact("Conversaciones vinculadas en Qualify", S.detail.observed_conversations),
                rx.text(
                    "Recuento acumulado de conversaciones con un mensaje vinculado a este anuncio. "
                    "No equivale a ventas ni al recuento de Meta.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
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
        _edit_confirmation(),
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
            rx.cond(S.edit_warning != "", callout(S.edit_warning, "warn")),
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
