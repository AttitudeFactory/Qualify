"""`/whatsapp` → Campañas tab (WA-20, QUA-219): the number's promotions, the «Enviar una
promoción» wizard in three steps (m-24842996: mensaje → a quién → revisar) and the
promotion's detail (summary, sends, «Ver respuestas en Chats», «Cancelar»).

Same hook as the other tabs: rendered only while active, inside the shell's box keyed by
the number; the root's `on_mount` loads. The page never talks to the provider.
"""

from __future__ import annotations

import reflex as rx

from .ui import (
    callout,
    card,
    choice_card,
    choice_card_check,
    drawer,
    empty_state,
    kv,
    loading_spinner,
    mono,
    skeleton_card,
    skeleton_rows,
    stat_card,
    stepper,
)
from .ui import tokens as T
from .ui.flow_history import flow_sync
from .ui.steps import step_progress
from .whatsapp_campaigns_state import WhatsAppCampaignsState as S
from .whatsapp_campaigns_vm import (
    PACE_OPTIONS,
    PAYMENT_FAILED,
    PAYMENT_NOTICE,
    PER_USER_LIMIT_NOTICE,
    RATE_CARD_NOTICE,
    SCOPE_ALL,
    SCOPE_SINCE,
    SEE_REPLIES,
    SENDER_NOTICE,
    STEP_AUDIENCE,
    STEP_MESSAGE,
    STEP_REVIEW,
    STEPS,
    CampaignRowVM,
    EstimateVM,
    OptionVM,
    SendVM,
    VariableFieldVM,
)
from .whatsapp_chats_vm import CREATE_APPROVED_LABEL
from .whatsapp_contacts_vm import SOURCES
from .whatsapp_marketing_ui import (
    card_line,
    confirm_action,
    field,
    ghost_refresh,
    retry_button,
    section_head,
    table_or_cards,
    tone_banner,
    tone_pill,
)
from .whatsapp_templates_vm import TemplateVM

_NUM = {"class_name": "q-nums", "text_align": "right"}

# ======================================================================================
# The list
# ======================================================================================


def _num_cell(value: rx.Var[str]) -> rx.Component:
    return rx.table.cell(rx.text(value, size="2", **_NUM))


def _campaign_row(c: CampaignRowVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.vstack(
                rx.text(c.name, size="2", weight="medium"),
                mono(c.template_label, size="1", color=T.TEXT_MUTED),
                spacing="0",
                align_items="start",
            )
        ),
        rx.table.cell(tone_pill(c.status_label, c.status_tone)),
        _num_cell(c.sent),
        _num_cell(c.delivered),
        _num_cell(c.read),
        _num_cell(c.failed),
        _num_cell(c.skipped),
        rx.table.cell(rx.text(c.cost_label, size="2", **_NUM)),
        rx.table.cell(rx.text(c.created_at, size="1", color=T.TEXT_MUTED, class_name="q-nums")),
        rx.table.cell(
            rx.button(
                "Ver resultados",
                rx.icon("chevron-right", size=T.ICON_SM),
                on_click=S.open_detail(c.campaign_id),
                custom_attrs={"aria-label": "Ver resultados de " + c.name},
                variant="ghost",
                size="1",
                **T.tone_scheme("neutral"),
            )
        ),
        align="center",
    )


def _num_header(label: str) -> rx.Component:
    return rx.table.column_header_cell(label, text_align="right")


def _campaign_card(c: CampaignRowVM) -> rx.Component:
    """Phone (m-24842998): «Promo de octubre · Enviada · 120 la leyeron de 128 · ≈ USD
    3,00» and «Ver» — the table's essentials, nothing sliding sideways."""
    return card(
        rx.vstack(
            rx.text(c.name, size="3", weight="medium"),
            card_line(
                tone_pill(c.status_label, c.status_tone),
                rx.cond(
                    c.reach_label != "",
                    rx.text(c.reach_label, size="2", class_name="q-nums"),
                    rx.fragment(),
                ),
                rx.cond(
                    c.cost_label != "—",
                    rx.text("≈ " + c.cost_label, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
                    rx.fragment(),
                ),
            ),
            rx.button(
                "Ver resultados",
                rx.icon("chevron-right", size=T.ICON_SM),
                on_click=S.open_detail(c.campaign_id),
                custom_attrs={"aria-label": "Ver resultados de " + c.name},
                variant="soft",
                size="2",
                width="100%",
                **_TAP,
                **T.tone_scheme("neutral"),
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        padding="1rem",
    )


def _campaigns_list() -> rx.Component:
    return table_or_cards(
        _campaigns_table(),
        rx.vstack(rx.foreach(S.campaigns, _campaign_card), spacing="3", width="100%"),
    )


def _campaigns_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Promoción"),
                    rx.table.column_header_cell("Estado"),
                    _num_header("Enviados"),
                    _num_header("Entregados"),
                    _num_header("Leídos"),
                    _num_header("Fallidos"),
                    _num_header("Omitidos"),
                    _num_header("Costo estimado"),
                    rx.table.column_header_cell("Creada"),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(rx.foreach(S.campaigns, _campaign_row)),
            variant="surface",
            width="100%",
        ),
        overflow_x="auto",
        width="100%",
    )


def _list() -> rx.Component:
    return rx.cond(
        S.ready,
        rx.cond(
            S.has_campaigns,
            _campaigns_list(),
            empty_state(
                "megaphone",
                "Aún no enviaste promociones desde este número",
                "Envía un mensaje aprobado a los clientes que aceptaron recibir tus "
                "promociones y mira cuántos lo recibieron y leyeron.",
                action=rx.button(
                    rx.icon("plus", size=16),
                    "Enviar una promoción",
                    on_click=S.open_wizard,
                    size="3",
                    **_TAP,
                ),
            ),
        ),
        rx.cond(
            S.failed,
            retry_button("Volver a leer las promociones", S.reload),
            skeleton_rows(3, height="3.5rem"),
        ),
    )


# ======================================================================================
# Shared: the estimate
# ======================================================================================

# N12: every target of the wizard is at least 44 px tall on a phone.
_TAP = {"min_height": "44px"}


def _estimate_block(e: EstimateVM, duration: rx.Var[str] | None = None) -> rx.Component:
    """How many, how long (when given) and about how much — the review's three facts."""
    return rx.vstack(
        rx.cond(
            e.placeholder,
            callout(
                rx.vstack(
                    rx.text(RATE_CARD_NOTICE, weight="bold"),
                    rx.text(
                        "Las tarifas de Meta por país aún no están cargadas en Qualify; el "
                        "valor de abajo es una idea del costo, no lo que Meta cobrará.",
                        size="1",
                    ),
                    spacing="1",
                    align_items="start",
                ),
                "warn",
                icon="circle-alert",
            ),
            rx.fragment(),
        ),
        rx.grid(
            stat_card("Personas", e.recipients, tone="neutral"),
            *([stat_card("Tarda", duration, tone="neutral")] if duration is not None else []),
            stat_card(
                "Costo aproximado",
                e.cost_label,
                tone="neutral",
                hint="Meta cobra por mensaje entregado, según el país.",
            ),
            columns=rx.breakpoints(initial="1", sm="3" if duration is not None else "2"),
            spacing="3",
            width="100%",
        ),
        rx.cond(e.unpriced != "", rx.text(e.unpriced, size="1", color=T.TEXT_MUTED), rx.fragment()),
        spacing="3",
        width="100%",
        align_items="start",
    )


# ======================================================================================
# Wizard steps (m-24842996: Mensaje → A quién → Revisar)
# ======================================================================================


def _template_choice(t: TemplateVM) -> rx.Component:
    """One approved message: what the client will read first, its name second."""
    selected = S.w_template_id == t.template_id
    return choice_card(
        rx.hstack(
            rx.vstack(
                rx.text(
                    t.body_preview,
                    size="2",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    style={
                        "display": "-webkit-box",
                        "-webkit-line-clamp": "3",
                        "-webkit-box-orient": "vertical",
                    },
                ),
                rx.hstack(
                    rx.text(t.display_name, size="1", color=T.TEXT_MUTED),
                    rx.text(t.language_label, size="1", color=T.TEXT_FAINT),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.cond(
                    ~t.sendable,
                    rx.text(
                        rx.cond(
                            t.wizard_block != "",
                            t.wizard_block,
                            "Aún no está aprobado por WhatsApp.",
                        ),
                        size="1",
                        color=T.TEXT_FAINT,
                    ),
                    rx.fragment(),
                ),
                spacing="1",
                align_items="start",
                min_width="0",
                flex="1",
            ),
            rx.cond(selected, choice_card_check(), rx.fragment()),
            align="start",
            width="100%",
            spacing="2",
        ),
        selected=selected,
        on_select=S.select_template(t.template_id),
        disabled=~t.sendable,
        padding="0.75rem 1rem",
        width="100%",
        text_align="left",
        **_TAP,
    )


def _variable_input(v: VariableFieldVM) -> rx.Component:
    return field(
        v.label,
        rx.input(
            value=v.value,
            on_change=lambda value: S.set_value(v.id, value),
            placeholder=rx.cond(v.example != "", "Ej.: " + v.example, ""),
            width="100%",
            size="3",
        ),
    )


def _step_message() -> rx.Component:
    """① ¿Qué mensaje envías? — an approved message, its blanks, an optional name."""
    return rx.vstack(
        rx.heading("¿Qué mensaje envías?", size="4", as_="h3"),
        rx.cond(
            S.templates_loading,
            skeleton_rows(3, height="3.5rem"),
            rx.cond(
                S.has_sendable_templates,
                rx.vstack(
                    rx.text(
                        "Para una promoción, WhatsApp solo deja enviar mensajes que ya aprobó.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    rx.vstack(
                        rx.foreach(S.templates, _template_choice),
                        spacing="2",
                        width="100%",
                        role="radiogroup",
                        aria_label="Mensaje aprobado",
                    ),
                    spacing="2",
                    width="100%",
                    align_items="start",
                ),
                rx.vstack(
                    callout(
                        "Aún no tienes mensajes aprobados en este número. Crea uno en "
                        "«Mensajes aprobados» y espera la aprobación de WhatsApp (puede "
                        "tardar hasta 24 horas).",
                        "info",
                    ),
                    rx.button(
                        rx.icon("plus", size=16),
                        CREATE_APPROVED_LABEL,
                        on_click=S.create_approved_message,
                        variant="soft",
                        size="3",
                        min_height="44px",
                        width=rx.breakpoints(initial="100%", sm="auto"),
                    ),
                    spacing="2",
                    width="100%",
                    align_items="start",
                ),
            ),
        ),
        rx.cond(
            S.variable_inputs.length() > 0,
            rx.vstack(
                rx.text("Completa el mensaje", size="2", weight="medium"),
                rx.text(
                    "Lo que escribas aquí le llega igual a todas las personas.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                rx.foreach(S.variable_inputs, _variable_input),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
        rx.cond(
            S.w_template_id != "",
            field(
                "Nombre para reconocerla (opcional)",
                rx.input(
                    value=S.w_name,
                    on_change=S.set_w_name,
                    placeholder="Ej.: Promo de octubre",
                    max_length=120,
                    width="100%",
                    size="3",
                ),
                "Solo lo ves tú. Si lo dejas vacío, la llamamos con la fecha de hoy.",
            ),
            rx.fragment(),
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _scope_choice(value: str, title: rx.Var[str] | str) -> rx.Component:
    selected = S.w_scope == value
    return choice_card(
        rx.hstack(
            rx.text(title, size="2", weight="medium", flex="1"),
            rx.cond(selected, choice_card_check(), rx.fragment()),
            align="center",
            width="100%",
            spacing="2",
        ),
        selected=selected,
        on_select=S.set_scope(value),
        padding="0.75rem 1rem",
        width="100%",
        text_align="left",
        **_TAP,
    )


def _brand_item(o: OptionVM) -> rx.Component:
    return rx.select.item(o.label, value=o.value)


def _source_check(key: str, label: str) -> rx.Component:
    return rx.checkbox(
        label,
        checked=S.w_sources.contains(key),
        on_change=lambda _checked: S.toggle_source(key),
        size="3",
        min_height="44px",
    )


def _more_filters() -> rx.Component:
    """«Más filtros»: brand, where they joined from, until when, country prefixes."""
    return rx.vstack(
        field(
            "Marca",
            rx.select.root(
                rx.select.trigger(width="100%"),
                rx.select.content(rx.foreach(S.brand_options, _brand_item)),
                value=S.w_brand,
                on_change=S.set_brand,
                size="3",
            ),
        ),
        field(
            "Cómo se sumaron",
            rx.flex(
                *[_source_check(key, label) for key, label in SOURCES],
                direction="column",
                gap="1",
            ),
            "Sin marcar ninguno, entran todos.",
        ),
        field(
            "Se sumaron hasta",
            rx.input(type="date", value=S.w_to, on_change=S.set_w_to, width="100%", size="3"),
        ),
        field(
            "Solo números de estos países",
            rx.input(
                value=S.w_prefixes,
                on_change=S.set_w_prefixes,
                placeholder="+57, +58",
                width="100%",
                size="3",
            ),
            "Escribe el prefijo de cada país (como +57), separados por comas. Vacío = todos.",
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _pace_choice(value: str, label: str) -> rx.Component:
    selected = S.w_pace == value
    return choice_card(
        rx.hstack(
            rx.text(label, size="2", flex="1"),
            rx.cond(selected, choice_card_check(), rx.fragment()),
            align="center",
            width="100%",
            spacing="2",
        ),
        selected=selected,
        on_select=S.set_w_pace(value),
        padding="0.6rem 1rem",
        width="100%",
        text_align="left",
        **_TAP,
    )


def _more_options() -> rx.Component:
    """«Más opciones»: how fast it goes out — a choice, 30 per minute by default."""
    return rx.vstack(
        rx.text(
            "Enviar de a poco cuida tu número: si muchos lo bloquean o lo reportan, WhatsApp "
            "baja cuántos mensajes puedes enviar.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.vstack(
            *[_pace_choice(key, label) for key, label in PACE_OPTIONS],
            spacing="2",
            width="100%",
            role="radiogroup",
            aria_label="Qué tan rápido se envía",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _fold(title: rx.Var[str] | str, value: str, content: rx.Component) -> rx.Component:
    return rx.accordion.root(
        rx.accordion.item(
            header=title,
            content=content,
            value=value,
            # N12: the fold's header is a thumb-sized target at 360 px.
            style={"& button": {"min_height": "44px", "width": "100%"}},
        ),
        collapsible=True,
        variant="ghost",
        width="100%",
    )


def _step_audience() -> rx.Component:
    """② ¿A quién? — everyone who accepted by default; the rest folded away."""
    return rx.vstack(
        rx.heading("¿A quién se la envías?", size="4", as_="h3"),
        rx.text(
            "Solo le llega a quien aceptó recibir tus promociones.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.vstack(
            _scope_choice(SCOPE_ALL, S.everyone_text),
            _scope_choice(SCOPE_SINCE, "Solo a los que se sumaron desde…"),
            spacing="2",
            width="100%",
            role="radiogroup",
            aria_label="A quién",
        ),
        rx.cond(
            S.w_scope == SCOPE_SINCE,
            field(
                "Se sumaron desde",
                rx.input(
                    type="date", value=S.w_from, on_change=S.set_w_from, width="100%", size="3"
                ),
            ),
            rx.fragment(),
        ),
        _fold(
            rx.cond(S.has_more_filters, "Más filtros (en uso)", "Más filtros"),
            "filters",
            _more_filters(),
        ),
        _fold("Más opciones", "options", _more_options()),
        card(
            rx.hstack(
                rx.cond(S.counting, loading_spinner("sm"), rx.icon("users", size=T.ICON_MD)),
                rx.text(
                    rx.cond(S.counting, "Contando personas…", S.audience_label),
                    size="2",
                    weight="medium",
                ),
                align="center",
                spacing="2",
            ),
            padding="0.75rem 1rem",
            width="100%",
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _step_review() -> rx.Component:
    """③ Revisa y envía — how many, how long, about how much. Nothing leaves before
    «Enviar ahora» (N13)."""
    t = S.selected_template
    return rx.vstack(
        rx.heading("Revisa y envía", size="4", as_="h3"),
        card(
            rx.vstack(
                rx.text("El mensaje", size="1", color=T.TEXT_MUTED),
                rx.text(t.body_text, size="2", white_space="pre-wrap"),
                rx.divider(),
                kv("A quién", S.audience_label),
                kv("Nombre", S.review_name),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            padding="1rem 1.25rem",
            width="100%",
        ),
        _estimate_block(S.w_estimate, S.review_duration),
        rx.text(S.pace_text, size="2"),
        callout(PER_USER_LIMIT_NOTICE, "info"),
        callout(PAYMENT_NOTICE, "info", icon="credit-card"),
        rx.text(
            "Nada se envía hasta que toques «Enviar ahora». Si cierras este panel, la "
            "promoción queda guardada en la lista sin enviar.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _wizard_footer() -> rx.Component:
    return rx.vstack(
        rx.cond(S.w_error != "", tone_banner(S.w_error, S.w_error_tone), rx.fragment()),
        rx.cond(
            (S.step < STEP_REVIEW) & (S.step_problem != ""),
            rx.text(S.step_problem, size="1", color=T.TEXT_MUTED),
            rx.fragment(),
        ),
        rx.hstack(
            rx.cond(
                S.step > STEP_MESSAGE,
                rx.button(
                    rx.icon("chevron-left", size=16),
                    "Atrás",
                    on_click=S.back,
                    variant="soft",
                    size="3",
                    disabled=S.launching | S.w_busy,
                    **_TAP,
                    **T.tone_scheme("neutral"),
                ),
                rx.fragment(),
            ),
            rx.spacer(),
            rx.cond(
                S.step == STEP_REVIEW,
                rx.button(
                    rx.icon("send", size=16),
                    "Enviar ahora",
                    on_click=S.launch_campaign(S.w_campaign_id),
                    loading=S.launching,
                    size="3",
                    **_TAP,
                ),
                rx.button(
                    rx.cond(S.step == STEP_AUDIENCE, "Revisar", "Siguiente"),
                    rx.icon("chevron-right", size=16),
                    on_click=S.next_step,
                    loading=S.w_busy,
                    disabled=S.step_problem != "",
                    size="3",
                    **_TAP,
                ),
            ),
            align="center",
            spacing="3",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def campaign_wizard() -> rx.Component:
    return drawer(
        rx.vstack(
            flow_sync("promocion", S.step + 1, ready=S.flow_ready & ~S.templates_loading),
            rx.box(
                stepper(
                    list(STEPS),
                    current=S.step,
                    completed=S.completed_steps,
                    on_select=S.go_to_step,
                ),
                display=rx.breakpoints(initial="none", sm="block"),
            ),
            rx.match(
                S.step,
                (STEP_MESSAGE, _step_message()),
                (STEP_AUDIENCE, _step_audience()),
                (STEP_REVIEW, _step_review()),
                _step_message(),
            ),
            spacing="4",
            width="100%",
            align_items="start",
        ),
        open=S.wizard_open,
        on_open_change=S.set_wizard_open,
        title="Enviar una promoción",
        step=rx.vstack(
            step_progress(S.step + 1, len(STEPS)),
            rx.text(rx.match(S.step, *enumerate(STEPS), STEPS[0]), size="2", weight="medium"),
            spacing="1",
            width="100%",
        ),
        description=(
            "Elige el mensaje, a quién se lo envías y revisa. Nada sale hasta que toques "
            "«Enviar ahora»."
        ),
        footer=_wizard_footer(),
        width="40rem",
        icon="megaphone",
    )


# ======================================================================================
# Detail
# ======================================================================================


def _send_row(s: SendVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(mono(s.phone, size="2")),
        rx.table.cell(tone_pill(s.status_label, s.status_tone)),
        rx.table.cell(
            rx.vstack(
                rx.text(s.note, size="1"),
                rx.cond(
                    s.retry_after != "",
                    rx.text(s.retry_after, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                    rx.fragment(),
                ),
                spacing="0",
                align_items="start",
            )
        ),
        rx.table.cell(rx.text(s.cost_label, size="1", white_space="nowrap", **_NUM)),
        align="center",
    )


def _detail_body() -> rx.Component:
    d = S.detail
    row = d.row
    return rx.vstack(
        tone_banner(S.detail_banner, S.detail_banner_tone),
        # N3: the next step after «Enviar ahora» is a solid button, right under the notice.
        rx.cond(
            S.detail_launched,
            rx.button(
                rx.icon("message-circle", size=16),
                SEE_REPLIES,
                on_click=S.see_replies,
                size="3",
                width=rx.breakpoints(initial="100%", sm="auto"),
                **_TAP,
            ),
            rx.fragment(),
        ),
        rx.hstack(
            tone_pill(row.status_label, row.status_tone),
            mono(row.template_label, size="1", color=T.TEXT_MUTED),
            rx.text("Creada " + row.created_at, size="1", color=T.TEXT_MUTED),
            spacing="3",
            align="center",
            wrap="wrap",
        ),
        rx.cond(
            d.payment_failed, callout(PAYMENT_FAILED, "error", icon="credit-card"), rx.fragment()
        ),
        rx.cond(d.retry_after_24h != "", callout(d.retry_after_24h, "warn"), rx.fragment()),
        rx.grid(
            stat_card("Enviados", row.sent, tone="neutral"),
            stat_card("Entregados", row.delivered, tone="ok"),
            stat_card("Leídos", row.read, tone="ok"),
            stat_card("Por enviar", row.queued, tone="info"),
            stat_card("Fallidos", row.failed, tone="error"),
            stat_card("Omitidos", row.skipped, tone="warn"),
            columns=rx.breakpoints(initial="2", sm="3"),
            spacing="3",
            width="100%",
        ),
        kv("Costo estimado", row.cost_label),
        kv("Ritmo", d.rate_label),
        rx.cond(
            S.detail_has_estimate,
            rx.vstack(
                rx.heading("Antes de enviar", size="3", as_="h3"),
                _estimate_block(S.detail_estimate),
                callout(PAYMENT_NOTICE, "info", icon="credit-card"),
                spacing="3",
                width="100%",
                align_items="start",
            ),
            rx.text(SENDER_NOTICE, size="1", color=T.TEXT_MUTED),
        ),
        rx.cond(
            S.detail_sends.length() > 0,
            table_or_cards(
                _sends_table(),
                rx.vstack(rx.foreach(S.detail_sends, _send_card), spacing="2", width="100%"),
            ),
            rx.fragment(),
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _send_card(s: SendVM) -> rx.Component:
    """Phone: one send per card — number, state, the note and the cost."""
    return card(
        rx.vstack(
            card_line(mono(s.phone, size="2"), tone_pill(s.status_label, s.status_tone)),
            rx.cond(s.note != "", rx.text(s.note, size="1"), rx.fragment()),
            rx.cond(
                s.retry_after != "",
                rx.text(s.retry_after, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                rx.fragment(),
            ),
            rx.text(s.cost_label, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            spacing="1",
            width="100%",
            align_items="start",
        ),
        padding="0.75rem 1rem",
    )


def _sends_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Número"),
                    rx.table.column_header_cell("Estado"),
                    rx.table.column_header_cell("Nota"),
                    rx.table.column_header_cell("Costo", text_align="right"),
                )
            ),
            rx.table.body(rx.foreach(S.detail_sends, _send_row)),
            variant="surface",
            width="100%",
        ),
        overflow_x="auto",
        width="100%",
    )


def _detail_footer() -> rx.Component:
    d = S.detail
    return rx.hstack(
        ghost_refresh("Actualizar", S.refresh_detail, loading=S.detail_loading),
        rx.spacer(),
        rx.cond(
            d.can_cancel,
            confirm_action(
                rx.button(
                    rx.icon("circle-stop", size=16),
                    "Detener promoción",
                    loading=S.cancelling,
                    variant="soft",
                    size="3",
                    **_TAP,
                    **T.tone_scheme("error"),
                ),
                title="¿Detener la promoción?",
                description="Los envíos que aún no salieron se retiran; los que ya salieron "
                "no se pueden deshacer. Una promoción detenida no se puede reanudar.",
                verb="Sí, detenerla",
                dismiss=rx.cond(
                    d.row.status == "running", "Seguir enviando", "Seguir con la promoción"
                ),
                on_confirm=S.cancel_campaign,
            ),
            rx.fragment(),
        ),
        rx.cond(
            d.can_launch,
            rx.button(
                rx.icon("send", size=16),
                "Enviar ahora",
                on_click=S.launch_campaign(S.detail_id),
                loading=S.launching,
                size="3",
                **_TAP,
            ),
            rx.fragment(),
        ),
        width="100%",
        align="center",
        spacing="3",
        wrap="wrap",
    )


def campaign_detail() -> rx.Component:
    return drawer(
        rx.cond(
            S.detail.row.campaign_id != "",
            _detail_body(),
            rx.cond(
                S.detail_banner != "",
                tone_banner(S.detail_banner, S.detail_banner_tone),
                skeleton_card(6),
            ),
        ),
        open=S.detail_open,
        on_open_change=S.set_detail_open,
        title=rx.cond(S.detail.row.name != "", S.detail.row.name, "Promoción"),
        footer=_detail_footer(),
        width="44rem",
        icon="megaphone",
    )


# ======================================================================================
# The tab
# ======================================================================================


def campaigns_tab() -> rx.Component:
    return rx.vstack(
        tone_banner(S.banner, S.banner_tone),
        section_head(
            "Promociones enviadas",
            ghost_refresh("Actualizar", S.reload),
            rx.button(
                rx.icon("plus", size=16),
                "Enviar una promoción",
                on_click=S.open_wizard,
                size="3",
                **_TAP,
            ),
        ),
        rx.text(
            "Envía un mensaje aprobado a los clientes que aceptaron recibir tus promociones. "
            "Los costos son aproximados; Meta cobra por mensaje entregado.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        _list(),
        campaign_wizard(),
        campaign_detail(),
        spacing="4",
        width="100%",
        align_items="start",
        on_mount=S.ensure_loaded,
    )
