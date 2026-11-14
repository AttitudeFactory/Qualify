"""Four small decisions, a review, then a separate authorization of advertising spend."""

from __future__ import annotations

import reflex as rx
from qualify_api.ads.messaging_greeting import MAX_QUESTION, MAX_WELCOME

from .ad_health_ui import health_details
from .promotion_audience_ui import promotion_audience
from .promotion_state import PromotionState as S
from .promotion_story_ui import (
    story_audience,
    story_empty,
    story_link,
    story_media,
    story_review,
)
from .promotion_unpublished_ui import (
    unpublished_country,
    unpublished_feed_video,
    unpublished_images,
    unpublished_review,
    unpublished_text,
    unpublished_vertical_video,
)
from .promotion_vm import (
    CHAT_GOAL_DETAIL,
    CHAT_GOAL_FROM_PIECE,
    CONNECTIONS_RETURN_HINT,
    EMPTY_SOURCES,
    GREETING_QUESTION_SLOTS,
    LEAD_CTA_LABELS,
    STORY_EMPTY,
    STORY_PLACEMENT,
    STORY_PREVIEW_BUTTON,
    WEBSITE_CTA_LABELS,
    LeadFormChoiceVM,
    MessagingDestinationVM,
    PromotionCheckVM,
)
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
            rx.cond(
                source.media_kind == "",
                rx.text(source.account_label, weight="medium", overflow_wrap="anywhere"),
                rx.text(
                    rx.cond(
                        source.story,
                        rx.cond(
                            source.media_kind == "videos",
                            "Con el video vertical",
                            "Con la imagen vertical",
                        ),
                        rx.cond(
                            source.media_kind == "videos",
                            "Con los dos videos",
                            "Con las dos imágenes",
                        ),
                    )
                    + " · "
                    + source.account_label,
                    weight="medium",
                    overflow_wrap="anywhere",
                ),
            ),
            rx.text(source.caption, size="2", class_name="q-clamp-3", color=T.TEXT_MUTED),
            rx.cond(
                source.media_kind == "",
                rx.text("Publicada: " + source.published_label, size="1", color=T.TEXT_MUTED),
                rx.text(
                    rx.cond(
                        source.story,
                        "Solo en historias de Instagram",
                        rx.cond(
                            source.media_kind == "videos",
                            "Dos videos de la pieza: para el perfil y vertical",
                            "Dos imágenes de la pieza: para el perfil y vertical",
                        ),
                    ),
                    size="1",
                    color=T.TEXT_MUTED,
                ),
            ),
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
            rx.cond(
                source.unavailable_reason != "",
                rx.text(source.unavailable_reason, size="2", color=T.TEXT_MUTED),
            ),
            # A chat ad never uses the piece's button, so that refusal leaves the chat goal.
            rx.cond(
                source.fix_in_piece & source.chat_goal,
                rx.text(CHAT_GOAL_FROM_PIECE, size="2", weight="medium"),
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


def _piece_link() -> rx.Component:
    return rx.link(
        "Cambiar el botón en la pieza",
        href=S.piece_href,
        min_height="44px",
        display="inline-flex",
        align_items="center",
    )


def _publication() -> rx.Component:
    return rx.vstack(
        rx.cond(
            S.sources[0].media_kind == "",
            rx.vstack(
                rx.text(
                    "Mostrarás una publicación que ya salió en Instagram a más personas.",
                    color=T.TEXT_MUTED,
                ),
                rx.text("Elige la publicación y la cuenta correctas antes de continuar.", size="2"),
                spacing="2",
                width="100%",
            ),
            rx.cond(
                S.sources[0].story,
                rx.text(STORY_PLACEMENT, color=T.TEXT_MUTED),
                rx.text(
                    "Tu pieza todavía no está publicada. Puedes anunciarla sin que aparezca "
                    "en tu perfil: se verá bien en el inicio, en historias y en reels.",
                    color=T.TEXT_MUTED,
                ),
            ),
        ),
        rx.vstack(
            rx.foreach(S.sources, _source_choice),
            role="radiogroup",
            aria_label="Publicación de Instagram",
            spacing="3",
            width="100%",
        ),
        rx.cond(S.selected_source.fix_in_piece, _piece_link()),
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
    """One chat the ad may open; an unavailable one stays visible, with its status, the
    reason and, by its `reason_code`, the way to fix it in Tus redes."""
    return rx.vstack(
        choice_card(
            rx.vstack(
                rx.hstack(
                    rx.text(option.label, weight="medium"),
                    rx.cond(option.status != "", signal_pill(option.status, "warn")),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(option.notice, size="2", color=T.TEXT_MUTED, overflow_wrap="anywhere"),
                spacing="1",
                align="start",
                width="100%",
            ),
            selected=S.form.channel == option.key,
            on_select=S.choose_channel(option.key),
            disabled=S.busy | ~option.available,
            min_height="44px",
            width="100%",
            text_align="left",
        ),
        rx.cond(
            option.action != "",
            rx.link(
                option.action + CONNECTIONS_RETURN_HINT,
                href="/connections",
                min_height="44px",
                display="inline-flex",
                align_items="center",
            ),
        ),
        rx.cond(
            # Only when the owner can fix it (an action) or we could not check it at all.
            ~option.available & ((option.action != "") | (option.reason_code == "unknown")),
            rx.button(
                rx.cond(
                    option.action != "",
                    "Ya lo conecté, comprobar de nuevo",
                    "Comprobar de nuevo",
                ),
                on_click=S.recheck_destinations,
                disabled=S.busy | S.loading | S.destinations_working,
                loading=S.destinations_working,
                variant="outline",
                min_height="44px",
            ),
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _channel() -> rx.Component:
    return rx.vstack(
        rx.vstack(
            rx.foreach(S.selected_source.messaging_destinations, _messaging_destination),
            role="radiogroup",
            aria_label="Por dónde quieres que te escriban",
            spacing="4",
            width="100%",
        ),
        rx.cond(
            S.destinations_notice != "",
            rx.text(S.destinations_notice, size="2", color=T.TEXT_MUTED),
        ),
        spacing="3",
        align_items="start",
        width="100%",
    )


def _counter(value: rx.Var[str], limit: int) -> rx.Component:
    return rx.text(value.length().to_string() + f" de {limit}", size="1", color=T.TEXT_MUTED)


def _question_field(index: int) -> rx.Component:
    field_id = f"promotion-question-{index}"
    field = rx.vstack(
        rx.el.label(
            f"Botón {index + 1}" + ("" if index == 0 else " (opcional)"),
            html_for=field_id,
            font_weight="500",
        ),
        rx.input(
            id=field_id,
            value=S.form.questions[index],
            on_change=lambda text: S.edit_question(index, text),
            max_length=MAX_QUESTION,
            disabled=S.busy,
            placeholder="Ejemplo: ¿Hacen domicilios?" if index == 0 else "",
            min_height="44px",
            width="100%",
        ),
        _counter(S.form.questions[index], MAX_QUESTION),
        spacing="1",
        width="100%",
    )
    # Box 1 always shows; the others once they have text or «Agregar» opened them.
    return field if index == 0 else rx.cond(S.questions_shown > index, field)


def _chat_bubble(text: rx.Var[str], *, mine: bool = False) -> rx.Component:
    return rx.box(
        rx.text(text, size="2", white_space="pre-wrap", overflow_wrap="anywhere"),
        background=T.tone_color("accent", 3) if mine else T.SURFACE_BG,
        border=T.BORDER,
        border_radius="14px",
        padding="8px 12px",
        max_width="85%",
        align_self="end" if mine else "start",
    )


def _greeting_preview() -> rx.Component:
    questions = S.form.questions
    return rx.vstack(
        rx.heading("Así lo ve quien toca tu anuncio", size="3", as_="h2"),
        rx.vstack(
            _chat_bubble(S.welcome_preview),
            *[
                rx.cond(
                    questions[index].strip() != "",
                    _chat_bubble(questions[index], mine=True),
                )
                for index in range(GREETING_QUESTION_SLOTS)
            ],
            spacing="2",
            width="100%",
            padding="12px",
            border_radius="16px",
            background=T.CARD_BG,
        ),
        spacing="2",
        width="100%",
        aria_label="Vista previa del chat",
    )


def _greeting() -> rx.Component:
    return rx.vstack(
        card(_greeting_preview(), width="100%"),
        card(
            rx.vstack(
                rx.el.label(
                    "Mensaje de bienvenida",
                    html_for="promotion-welcome",
                    font_weight="500",
                ),
                rx.text_area(
                    id="promotion-welcome",
                    value=S.form.welcome_text,
                    on_change=S.edit_welcome,
                    max_length=MAX_WELCOME,
                    disabled=S.busy,
                    placeholder="Ejemplo: ¡Hola! Gracias por escribirnos. ¿En qué te ayudamos?",
                    rows="3",
                    width="100%",
                    aria_invalid=rx.cond(S.welcome_error != "", "true", "false"),
                ),
                _counter(S.form.welcome_text, MAX_WELCOME),
                rx.cond(
                    S.welcome_error != "",
                    rx.text(S.welcome_error, size="2", color=T.tone_color("error", 11)),
                ),
                rx.heading("Botones para tu cliente", size="3", as_="h2"),
                rx.text(
                    "La persona toca uno y te escribe sin teclear. Pon al menos uno.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                *[_question_field(index) for index in range(GREETING_QUESTION_SLOTS)],
                rx.cond(
                    S.questions_shown < GREETING_QUESTION_SLOTS,
                    rx.button(
                        "+ Agregar otra pregunta",
                        on_click=S.add_question,
                        disabled=S.busy,
                        variant="ghost",
                        min_height="44px",
                    ),
                ),
                spacing="3",
                width="100%",
            ),
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


def _option(title: str, detail: str, selected: rx.Var[bool], on_select: object) -> rx.Component:
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


def _lead_form_choice(row: rx.Var[LeadFormChoiceVM]) -> rx.Component:
    return choice_card(
        rx.text(row.name, weight="medium", overflow_wrap="anywhere"),
        selected=S.form.lead_form_id == row.id,
        on_select=S.choose_lead_form(row.id),
        disabled=S.busy,
        min_height="44px",
        width="100%",
        text_align="left",
    )


def _lead_destination() -> rx.Component:
    forms = S.selected_source.lead_forms
    return card(
        rx.cond(
            S.selected_source.lead_forms_error != "",
            callout(S.selected_source.lead_forms_error, "warn"),
            rx.cond(
                forms.length() > 0,
                rx.vstack(
                    rx.heading("Formulario", size="3", as_="h2", id="lead-form-label"),
                    rx.text(
                        "Es lo que llenará la gente sin salir de Instagram o Facebook.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    rx.vstack(
                        rx.foreach(forms, _lead_form_choice),
                        role="radiogroup",
                        aria_labelledby="lead-form-label",
                        spacing="2",
                        width="100%",
                    ),
                    rx.heading("Texto del botón", size="3", as_="h2", id="lead-cta-label"),
                    rx.vstack(
                        *[
                            _option(
                                label,
                                "",
                                S.form.lead_cta == code,
                                S.choose_lead_cta(code),
                            )
                            for code, label in LEAD_CTA_LABELS.items()
                        ],
                        role="radiogroup",
                        aria_labelledby="lead-cta-label",
                        spacing="2",
                        width="100%",
                    ),
                    rx.link(
                        "Crear otro formulario",
                        href="/promotions/forms",
                        min_height="44px",
                        display="inline-flex",
                        align_items="center",
                    ),
                    spacing="3",
                    width="100%",
                ),
                rx.vstack(
                    rx.heading("Todavía no tienes un formulario listo", size="3", as_="h2"),
                    rx.text(
                        "Crea uno con las preguntas que quieres hacer. "
                        "Cuando Meta lo acepte, vuelve aquí para elegirlo.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    rx.link(
                        rx.button("Crear formulario", min_height="44px", size="3"),
                        href="/promotions/forms",
                    ),
                    spacing="3",
                    align_items="start",
                    width="100%",
                ),
            ),
        ),
        rx.button(
            "Ya lo creé: buscar formularios",
            on_click=S.refresh_lead_forms,
            loading=S.forms_working,
            disabled=S.busy | S.forms_working,
            variant="outline",
            min_height="44px",
            margin_top="12px",
        ),
        width="100%",
    )


def _destination() -> rx.Component:
    return rx.vstack(
        rx.vstack(
            _option(
                "Que visite tu página",
                "El anuncio abre tu página web.",
                S.form.goal == "visit",
                S.choose_goal("visit"),
            ),
            _option(
                "Que te deje sus datos para contactarla",
                "La persona llena un formulario corto y tú la contactas.",
                S.form.goal == "lead",
                S.choose_goal("lead"),
            ),
            rx.cond(
                S.selected_source.chat_goal,
                _option(
                    "Que te escriban",
                    CHAT_GOAL_DETAIL,
                    S.form.goal == "chat",
                    S.choose_goal("chat"),
                ),
            ),
            role="radiogroup",
            aria_label="Qué quieres que haga la gente",
            spacing="3",
            width="100%",
        ),
        rx.match(
            S.form.goal,
            ("lead", _lead_destination()),
            ("chat", rx.fragment()),  # the chat and its greeting are the next two steps
            _link_destination(),
        ),
        spacing="4",
        width="100%",
    )


def _link_destination() -> rx.Component:
    return card(
        rx.vstack(
            _field(
                "Página que abrirá el anuncio",
                "link_url",
                S.form.link_url,
                placeholder="https://tu-negocio.com",
                type="url",
            ),
            rx.heading("Botón del anuncio", size="3", as_="h2", id="website-cta-label"),
            rx.vstack(
                *[
                    _option(label, "", S.form.cta_type == code, S.choose_cta(code))
                    for code, label in WEBSITE_CTA_LABELS.items()
                ],
                role="radiogroup",
                aria_labelledby="website-cta-label",
                spacing="2",
                width="100%",
            ),
            rx.text(
                "Revisa que el enlace lleve a lo que ofreces en esta publicación.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            # QUALIFY_ADS_CHAT_GOAL off: the chats stay a diagnosis, never a choice.
            rx.cond(
                ~S.selected_source.chat_goal
                & (S.selected_source.messaging_destinations.length() > 0),
                rx.vstack(
                    rx.text("Anuncios que abren un chat", weight="medium"),
                    _channel(),
                    spacing="2",
                    width="100%",
                ),
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
            # The amount as the owner reads money: «$25.000 COP» (m-25026350 UX review).
            rx.cond(
                S.budget_valid,
                rx.text("Total: " + S.budget_label, size="2", weight="medium"),
            ),
            _field("Inicio", "start_local", S.form.start_local, type="datetime-local"),
            _field("Final", "end_local", S.form.end_local, type="datetime-local"),
            rx.cond(
                S.timezone_name != "",
                rx.text(
                    "Las fechas están en " + S.zone_label + ".",
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
                _fact("Botón", S.button_label),
                rx.match(
                    S.form.goal,
                    ("lead", _fact("Formulario", S.lead_form_label)),
                    (
                        "chat",
                        rx.vstack(
                            _fact("Te escriben por", S.channel_label),
                            _fact("Mensaje de bienvenida", S.form.welcome_text),
                            _fact("Botones del chat", S.greeting_buttons_label),
                            spacing="3",
                            width="100%",
                        ),
                    ),
                    _fact("Página de destino", S.form.link_url),
                ),
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
                _fact("Público de Instagram", S.custom_selection_label),
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
                _fact("Horario", S.zone_label),
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
                rx.cond(
                    S.selected_source.fix_in_piece,
                    _piece_link(),
                    rx.link(
                        "Revisar cuenta para anuncios en Tus redes",
                        href="/connections",
                        min_height="44px",
                    ),
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
                            S.back_label == "Tu semana",
                            "Volver a Tu semana",
                            rx.cond(S.is_unpublished, "Ver pieza", "Ver publicación"),
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
                callout(rx.cond(S.story_entry, STORY_EMPTY, EMPTY_SOURCES), "info"),
            ),
            rx.cond(
                S.reviewed,
                rx.cond(
                    S.form.story,
                    story_review(),
                    rx.cond(S.is_unpublished, unpublished_review(), _review()),
                ),
                rx.match(
                    S.step_key,
                    ("story_media", story_media()),
                    ("story_link", story_link()),
                    ("story_audience", story_audience()),
                    ("source", _publication()),
                    ("destination", _destination()),
                    ("channel", _channel()),
                    ("greeting", _greeting()),
                    ("audience", promotion_audience()),
                    ("images", unpublished_images()),
                    ("feed_video", unpublished_feed_video()),
                    ("vertical_video", unpublished_vertical_video()),
                    ("text", unpublished_text()),
                    ("country", unpublished_country()),
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
                rx.cond(
                    S.video_waiting,
                    "Revisar ahora",
                    rx.cond(S.form.story, STORY_PREVIEW_BUTTON, "Crear en pausa y ver anuncio"),
                ),
                step=S.step,
                on_primary=S.create_preview,
                on_back=S.back_step,
                primary_disabled=(
                    S.busy | S.paid_operation_locked | (S.execution_reason != "") | S.needs_help
                ),
                primary_loading=S.busy,
                reason=S.execution_reason,
            ),
        ),
        step_foot(
            rx.cond(S.step >= S.step_total, "Revisar resumen", "Siguiente"),
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
            rx.cond(
                S.story_entry & ~S.loading & (S.sources.length() == 0),
                story_empty(),
                _wizard(body, foot),
            ),
        ),
    )


def _wizard(body: rx.Component, foot: rx.Component) -> rx.Component:
    return step_frame(
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
            S.title,
            step=S.display_step,
            total=S.display_total,
            back_label=S.back_label,
            back_href=S.back_href,
        ),
        foot=rx.cond(
            S.paid_operation_locked,
            rx.link(
                rx.button(
                    rx.cond(
                        S.back_label == "Tu semana",
                        "Volver a Tu semana",
                        rx.cond(S.is_unpublished, "Ver pieza", "Ver publicación"),
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
    )
