"""Four small decisions, a review, then a separate authorization of advertising spend."""

from __future__ import annotations

import reflex as rx

from .ad_health_ui import health_details
from .promotion_audience_ui import promotion_audience
from .promotion_state import PromotionState as S
from .promotion_vm import EMPTY_SOURCES, MessagingDestinationVM, PromotionCheckVM
from .ui import (
    app_shell,
    callout,
    card,
    choice_card,
    page_body,
    page_header,
    signal_pill,
    skeleton_card,
    step_foot,
    step_frame,
    step_head,
    step_sync,
)
from .ui import tokens as T


def _field(label: str, name: str, value: rx.Var[str], **props: object) -> rx.Component:
    field_id = "promotion-" + name
    return rx.vstack(
        rx.el.label(label, html_for=field_id, font_weight="500"),
        rx.input(
            id=field_id,
            value=value,
            on_change=lambda text: S.edit(name, text),
            disabled=S.busy,
            size="3",
            min_height="44px",
            width="100%",
            **props,
        ),
        spacing="2",
        width="100%",
    )


def _check_result(check: PromotionCheckVM) -> rx.Component:
    return rx.vstack(
        rx.flex(
            rx.text(check.label, size="2", weight="medium"),
            rx.match(
                check.status,
                ("verified", signal_pill("Comprobado", "ok")),
                ("blocked", signal_pill("Requiere cambios", "warn")),
                signal_pill("Por comprobar", "warn"),
            ),
            gap="2",
            align="center",
            wrap="wrap",
            width="100%",
        ),
        rx.text(check.detail, size="2", color=T.TEXT_MUTED, overflow_wrap="anywhere"),
        spacing="1",
        width="100%",
    )


def _checks() -> rx.Component:
    return rx.cond(
        S.checks.length() > 0,
        card(
            rx.vstack(
                rx.heading("Comprobaciones de Meta", size="3", as_="h2"),
                rx.text(
                    "Estos resultados corresponden a tu elección actual. "
                    "Si la cambias, volveremos a comprobarla.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.foreach(S.checks, _check_result),
                rx.cond(
                    S.reviewed
                    & S.has_remote_review
                    & S.checks_block_confirmation
                    & ~S.paid_operation_locked,
                    rx.button(
                        "Volver a comprobar esta promoción",
                        on_click=S.create_preview,
                        disabled=S.busy | (S.success != ""),
                        min_height="44px",
                        variant="outline",
                    ),
                ),
                spacing="3",
                width="100%",
            ),
            width="100%",
        ),
    )


def _source_choice(source: rx.Var) -> rx.Component:
    return choice_card(
        rx.vstack(
            rx.text(source.account_label, weight="medium", overflow_wrap="anywhere"),
            rx.text(source.caption, size="2", class_name="q-clamp-3", color=T.TEXT_MUTED),
            rx.text("Publicada: " + source.published_label, size="1", color=T.TEXT_MUTED),
            rx.cond(
                source.account_name != "",
                rx.text(
                    "Cuenta para anuncios: " + source.account_name, size="1", color=T.TEXT_MUTED
                ),
            ),
            rx.cond(
                source.currency != "",
                rx.text("Moneda de la cuenta: " + source.currency, size="1", color=T.TEXT_MUTED),
            ),
            rx.cond(
                source.health.blocks_preparation,
                rx.text(source.health.reason, size="2", color=T.TEXT_MUTED),
            ),
            spacing="2",
            align="start",
            width="100%",
        ),
        selected=S.form.source_id == source.id,
        on_select=S.choose_source(source.id),
        disabled=S.busy,
        min_height="44px",
        width="100%",
        text_align="left",
    )


def _publication() -> rx.Component:
    return rx.vstack(
        signal_pill("Visitas a tu web", "info"),
        rx.text(
            "Mostrarás una publicación que ya salió en Instagram "
            "para llevar más personas a tu página.",
            color=T.TEXT_MUTED,
        ),
        rx.text("Elige la publicación y la cuenta correctas antes de continuar.", size="2"),
        rx.vstack(
            rx.foreach(S.sources, _source_choice),
            role="radiogroup",
            aria_label="Publicación de Instagram",
            spacing="3",
            width="100%",
        ),
        rx.cond(
            S.selected_source.account_name != "",
            rx.vstack(
                health_details(S.selected_source.health),
                rx.link(
                    "Revisar cuenta en Tus redes",
                    href="/connections",
                    min_height="44px",
                    display="inline-flex",
                    align_items="center",
                ),
                spacing="2",
                align_items="start",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


def _messaging_destination(option: MessagingDestinationVM) -> rx.Component:
    return rx.vstack(
        rx.text(option.label, weight="medium"),
        rx.text(option.notice, size="2", color=T.TEXT_MUTED, overflow_wrap="anywhere"),
        spacing="1",
        align_items="start",
        width="100%",
    )


def _destination() -> rx.Component:
    return card(
        rx.vstack(
            _field(
                "Página que abrirá el anuncio",
                "link_url",
                S.form.link_url,
                placeholder="https://tu-negocio.com",
                type="url",
            ),
            rx.text("Botón del anuncio: Más información", weight="medium"),
            rx.text(
                "Revisa que el enlace lleve a lo que ofreces en esta publicación.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.cond(
                S.selected_source.messaging_destinations.length() > 0,
                rx.vstack(
                    rx.text("Anuncios que abren un chat", weight="medium"),
                    rx.text(
                        "Estos destinos todavía no se pueden elegir aquí. "
                        "Revisa qué falta para usar los chats de tu negocio.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    rx.foreach(S.selected_source.messaging_destinations, _messaging_destination),
                    rx.button(
                        "Volver a comprobar destinos",
                        on_click=S.recheck_destinations,
                        disabled=S.busy | S.loading | S.destinations_working,
                        loading=S.destinations_working,
                        variant="outline",
                        min_height="44px",
                    ),
                    rx.cond(
                        S.destinations_notice != "",
                        rx.text(S.destinations_notice, size="2", color=T.TEXT_MUTED),
                    ),
                    spacing="3",
                    align_items="start",
                    width="100%",
                ),
                rx.fragment(),
            ),
            spacing="4",
            width="100%",
        ),
        width="100%",
    )


def _budget() -> rx.Component:
    return card(
        rx.vstack(
            _field(
                "Presupuesto total en pesos colombianos",
                "budget",
                S.form.budget,
                placeholder="Ejemplo: 25000",
                input_mode="numeric",
            ),
            rx.text(
                "En pesos enteros, para todo el período, no por día.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            _field("Inicio", "start_local", S.form.start_local, type="datetime-local"),
            _field("Final", "end_local", S.form.end_local, type="datetime-local"),
            rx.cond(
                S.timezone_name != "",
                rx.text(
                    "Zona horaria usada para estas fechas: " + S.timezone_name,
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                callout("Revisa la zona horaria de tu negocio antes de continuar.", "warn"),
            ),
            callout(
                "Meta debe comprobar el importe y las fechas antes de crear el anuncio.",
                "info",
            ),
            spacing="4",
            width="100%",
        ),
        width="100%",
    )


def _fact(label: str, value: rx.Var[str]) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="1", color=T.TEXT_MUTED),
        rx.text(value, size="2", overflow_wrap="anywhere"),
        spacing="1",
        width="100%",
    )


def _review() -> rx.Component:
    return rx.vstack(
        card(
            rx.vstack(
                _fact("Publicación", S.selected_source.caption),
                _fact("Instagram", S.selected_source.account_label),
                _fact(
                    "Cuenta para anuncios",
                    rx.cond(
                        S.selected_source.account_name != "",
                        S.selected_source.account_name,
                        "Pendiente de elegir en Tus redes",
                    ),
                ),
                _fact("Botón", rx.Var.create("Más información")),
                _fact("Página de destino", S.form.link_url),
                _fact("Lugar de las personas", S.audience_location_label),
                _fact(
                    "Distancia",
                    rx.cond(
                        S.form.radius_km != "",
                        S.form.radius_km + " km (pendiente de comprobar)",
                        "El lugar elegido",
                    ),
                ),
                _fact("Personas", S.audience_people_label),
                _fact("Intereses", S.audience_interests_label),
                _fact("Dónde aparece", S.audience_places_label),
                _fact(
                    "Ampliación del público",
                    rx.cond(
                        S.form.advantage_audience,
                        "Solicitada, pendiente de comprobar con Meta",
                        "No solicitada",
                    ),
                ),
                _fact(
                    "Anuncio de vivienda",
                    rx.cond(S.form.housing, "Sí, requiere comprobaciones adicionales", "No"),
                ),
                _fact("Presupuesto para todo el período", S.budget_label),
                _fact("Inicio", S.start_label),
                _fact("Final", S.end_label),
                _fact("Zona horaria", S.timezone_name),
                _fact("Cambios permitidos a Meta", S.enhancement_summary),
                rx.text(S.enhancement_notice, size="2", color=T.TEXT_MUTED),
                rx.text(
                    "Estos permisos se guardan en Tu marca "
                    "y no reemplazan la revisión del anuncio.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.button(
                    "Volver a consultar permisos",
                    on_click=S.recheck_enhancements,
                    disabled=S.busy | S.loading | S.enhancements_working,
                    loading=S.enhancements_working,
                    min_height="44px",
                    variant="outline",
                ),
                rx.cond(
                    S.enhancements_notice != "",
                    rx.text(S.enhancements_notice, size="2", color=T.TEXT_MUTED),
                ),
                spacing="3",
                width="100%",
            ),
            width="100%",
        ),
        rx.cond(
            S.execution_reason != "",
            rx.vstack(
                callout(S.execution_reason, "warn"),
                rx.link(
                    "Revisar cuenta para anuncios en Tus redes",
                    href="/connections",
                    min_height="44px",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            S.has_remote_review,
            rx.vstack(
                rx.cond(
                    ~S.paid_operation_locked,
                    signal_pill("Anuncio en pausa", "info"),
                    rx.cond(
                        S.result.status == "active",
                        signal_pill("Activación solicitada a Meta", "info"),
                        signal_pill("Activación por comprobar", "warn"),
                    ),
                ),
                rx.el.iframe(
                    src=S.review.preview_url,
                    title="Vista previa de tu anuncio en Meta",
                    sandbox="",
                    referrer_policy="no-referrer",
                    width="100%",
                    height="420px",
                    loading="lazy",
                ),
                rx.text(S.review.charge_notice, weight="medium"),
                rx.text(
                    "Revisión válida hasta: " + S.review.expires_label, size="2", color=T.TEXT_MUTED
                ),
                rx.text(
                    "Si vence, vuelve a la publicación y prepara otra promoción.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.checkbox(
                    "Revisé el anuncio y autorizo el presupuesto total indicado.",
                    checked=S.confirm_charge,
                    on_change=S.accept_charge,
                    disabled=(S.busy | S.paid_operation_locked | S.checks_block_confirmation),
                    min_height="44px",
                ),
                spacing="3",
                width="100%",
            ),
            callout(
                "Este es el resumen de tu elección. No activa anuncios. Antes de autorizar "
                "el gasto debes revisar una vista previa válida de Meta.",
                "info",
            ),
        ),
        spacing="4",
        width="100%",
    )


def _blocked_preparation() -> rx.Component:
    return rx.vstack(
        page_header("Antes de promocionar"),
        page_body(
            card(
                rx.vstack(
                    rx.heading("Revisa la cuenta publicitaria", size="4", as_="h2"),
                    health_details(S.selected_source.health),
                    rx.text(
                        "Resuelve este estado en Meta y vuelve a consultar "
                        "antes de preparar el anuncio.",
                        color=T.TEXT_MUTED,
                    ),
                    rx.button(
                        "Volver a comprobar",
                        on_click=S.recheck_health,
                        disabled=S.loading | S.busy,
                        min_height="44px",
                        size="3",
                    ),
                    rx.cond(
                        S.sources.length() > 1,
                        rx.button(
                            "Elegir otra publicación",
                            on_click=S.choose_another_source,
                            variant="outline",
                            min_height="44px",
                        ),
                    ),
                    rx.link(
                        rx.cond(
                            S.back_label == "Tu semana", "Volver a Tu semana", "Ver publicación"
                        ),
                        href=S.back_href,
                        min_height="44px",
                        display="inline-flex",
                        align_items="center",
                    ),
                    spacing="4",
                    align_items="start",
                    width="100%",
                ),
                width="100%",
            ),
        ),
        spacing="0",
        width="100%",
    )


def promotion_index() -> rx.Component:
    body = rx.cond(
        S.loading,
        skeleton_card(4),
        rx.cond(
            S.sources.length() == 0,
            rx.cond(
                S.error != "",
                rx.button(
                    "Volver a consultar", on_click=S.load, variant="outline", min_height="44px"
                ),
                callout(EMPTY_SOURCES, "info"),
            ),
            rx.cond(
                S.reviewed,
                _review(),
                rx.match(
                    S.step,
                    (1, _publication()),
                    (2, _destination()),
                    (3, promotion_audience()),
                    _budget(),
                ),
            ),
        ),
    )
    foot = rx.cond(
        S.reviewed,
        rx.cond(
            S.has_remote_review,
            step_foot(
                S.charge_button,
                step=S.step,
                on_primary=S.confirm,
                on_back=S.back_step,
                primary_disabled=(
                    ~S.confirm_charge
                    | S.busy
                    | S.paid_operation_locked
                    | S.checks_block_confirmation
                ),
                primary_loading=S.busy,
            ),
            step_foot(
                "Crear en pausa y ver anuncio",
                step=S.step,
                on_primary=S.create_preview,
                on_back=S.back_step,
                primary_disabled=S.busy | S.paid_operation_locked | (S.execution_reason != ""),
                primary_loading=S.busy,
                reason=S.execution_reason,
            ),
        ),
        step_foot(
            rx.cond(S.step == 4, "Revisar resumen", "Siguiente"),
            step=S.step,
            on_primary=S.next_step,
            on_back=S.back_step,
            primary_disabled=S.loading | S.busy | (S.sources.length() == 0),
        ),
    )
    return app_shell(
        rx.cond(
            S.preparation_blocked,
            _blocked_preparation(),
            step_frame(
                step_sync(S.step, S.direction),
                rx.cond(S.error != "", callout(S.error, "error")),
                rx.cond(S.success != "", callout(S.success, "ok")),
                rx.cond(
                    S.paid_operation_locked & (S.result.status != "active"),
                    callout(S.result.message, "warn"),
                ),
                rx.cond(
                    S.paid_operation_locked | ((S.error != "") & S.has_remote_review),
                    rx.link(
                        "Ver estado del anuncio",
                        href=S.promotion_status_href,
                        min_height="44px",
                    ),
                ),
                _checks(),
                rx.cond(
                    (S.execution_reason != "") & ~S.reviewed,
                    callout(S.execution_reason, "info"),
                ),
                rx.cond(
                    (S.selected_source.currency != "") & (S.selected_source.currency != "COP"),
                    callout(
                        "Este asistente prepara presupuestos en pesos colombianos. "
                        "Revisa la moneda de la cuenta elegida.",
                        "warn",
                    ),
                ),
                body,
                head=step_head(
                    S.title, step=S.step, total=4, back_label=S.back_label, back_href=S.back_href
                ),
                foot=rx.cond(
                    S.paid_operation_locked,
                    rx.link(
                        rx.button(
                            rx.cond(
                                S.back_label == "Tu semana", "Volver a Tu semana", "Ver publicación"
                            ),
                            min_height="44px",
                            size="3",
                        ),
                        href=S.back_href,
                    ),
                    foot,
                ),
                step=S.step,
                direction=S.direction,
                on_pop=S.read_step,
            ),
        ),
    )
