"""`/whatsapp` → Campañas tab (WA-20, QUA-219): the number's marketing campaigns, the
«Nueva campaña» wizard (plantilla → variables → audiencia → ritmo → revisar) and the
campaign detail (summary, sends, «Cancelar campaña»).

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
    tag,
)
from .ui import tokens as T
from .whatsapp_campaigns_state import WhatsAppCampaignsState as S
from .whatsapp_campaigns_vm import (
    MAX_PER_MINUTE,
    PAYMENT_FAILED,
    PAYMENT_NOTICE,
    RATE_CARD_NOTICE,
    SENDER_NOTICE,
    STEP_AUDIENCE,
    STEP_PACING,
    STEP_REVIEW,
    STEP_TEMPLATE,
    STEP_VARIABLES,
    STEPS,
    CampaignRowVM,
    EstimateVM,
    OptionVM,
    SendVM,
    VariableFieldVM,
)
from .whatsapp_contacts_vm import SOURCES
from .whatsapp_marketing_ui import (
    confirm_action,
    field,
    ghost_refresh,
    retry_button,
    section_head,
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
                "Ver",
                rx.icon("chevron-right", size=T.ICON_SM),
                on_click=S.open_detail(c.campaign_id),
                variant="ghost",
                size="1",
                **T.tone_scheme("neutral"),
            )
        ),
        align="center",
    )


def _num_header(label: str) -> rx.Component:
    return rx.table.column_header_cell(label, text_align="right")


def _campaigns_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Campaña"),
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
            _campaigns_table(),
            empty_state(
                "megaphone",
                "Aún no hay campañas en este número",
                "Una campaña envía una plantilla aprobada a tus contactos con opt-in, al "
                "ritmo que elijas, y te muestra cuántos la recibieron y leyeron.",
                action=rx.button(
                    rx.icon("plus", size=16), "Nueva campaña", on_click=S.open_wizard, size="3"
                ),
            ),
        ),
        rx.cond(
            S.failed,
            retry_button("Volver a leer las campañas", S.reload),
            skeleton_rows(3, height="3.5rem"),
        ),
    )


# ======================================================================================
# Shared: the estimate
# ======================================================================================


def _estimate_block(e: EstimateVM) -> rx.Component:
    return rx.vstack(
        rx.cond(
            e.placeholder,
            callout(
                rx.vstack(
                    rx.text(RATE_CARD_NOTICE, weight="bold"),
                    rx.text(
                        "Las tarifas de Meta por país aún no están cargadas en Qualify; el "
                        "valor de abajo es un orden de magnitud, no lo que Meta cobrará.",
                        size="1",
                    ),
                    mono(e.rate_card_status, size="1"),
                    spacing="1",
                    align_items="start",
                ),
                "warn",
                icon="circle-alert",
            ),
            rx.fragment(),
        ),
        rx.grid(
            stat_card("Destinatarios", e.recipients, tone="neutral"),
            stat_card(
                "Costo estimado",
                e.cost_label,
                tone="neutral",
                hint="Meta cobra por mensaje entregado, según el país y la categoría.",
            ),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="3",
            width="100%",
        ),
        rx.cond(e.unpriced != "", rx.text(e.unpriced, size="1", color=T.TEXT_MUTED), rx.fragment()),
        spacing="3",
        width="100%",
        align_items="start",
    )


# ======================================================================================
# Wizard steps
# ======================================================================================


def _template_choice(t: TemplateVM) -> rx.Component:
    selected = S.w_template_id == t.template_id
    return choice_card(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    mono(t.name, weight="medium"),
                    tag(t.category_label),
                    rx.text(t.language_label, size="1", color=T.TEXT_MUTED),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(
                    t.body_text,
                    size="1",
                    color=T.TEXT_MUTED,
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                    max_width="32rem",
                ),
                rx.cond(
                    ~t.sendable,
                    rx.text(
                        rx.cond(
                            t.wizard_block != "",
                            t.wizard_block,
                            "Aún no está aprobada por Meta.",
                        ),
                        size="1",
                        color=T.TEXT_FAINT,
                    ),
                    rx.fragment(),
                ),
                spacing="1",
                align_items="start",
                min_width="0",
            ),
            rx.spacer(),
            tone_pill(t.status_label, t.status_tone),
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
    )


def _step_template() -> rx.Component:
    return rx.vstack(
        field(
            "Nombre de la campaña",
            rx.input(
                value=S.w_name,
                on_change=S.set_w_name,
                placeholder="Ej.: Promo de octubre",
                max_length=120,
                width="100%",
            ),
            "Solo lo ve tu equipo.",
        ),
        field(
            "Plantilla",
            rx.cond(
                S.templates_loading,
                skeleton_rows(3, height="3.5rem"),
                rx.cond(
                    S.has_sendable_templates,
                    rx.vstack(
                        rx.foreach(S.templates, _template_choice),
                        spacing="2",
                        width="100%",
                        role="radiogroup",
                        aria_label="Plantilla",
                    ),
                    callout(
                        "Este número aún no tiene plantillas aprobadas. Crea una en «Plantillas» "
                        "y espera la aprobación de Meta (puede tardar hasta 24 h).",
                        "info",
                    ),
                ),
            ),
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _variable_input(v: VariableFieldVM) -> rx.Component:
    return field(
        v.label,
        rx.input(
            value=v.value,
            on_change=lambda value: S.set_value(v.id, value),
            placeholder=rx.cond(v.example != "", "Ej.: " + v.example, ""),
            width="100%",
        ),
    )


def _step_variables() -> rx.Component:
    return rx.vstack(
        rx.cond(
            S.variable_inputs.length() > 0,
            rx.vstack(
                rx.text(
                    "El mismo valor va a todos los destinatarios de la campaña.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.foreach(S.variable_inputs, _variable_input),
                spacing="3",
                width="100%",
                align_items="start",
            ),
            callout("Esta plantilla no tiene variables: no hay nada que completar.", "info"),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _brand_item(o: OptionVM) -> rx.Component:
    return rx.select.item(o.label, value=o.value)


def _source_check(key: str, label: str) -> rx.Component:
    return rx.checkbox(
        label,
        checked=S.w_sources.contains(key),
        on_change=lambda _checked: S.toggle_source(key),
        size="2",
    )


def _step_audience() -> rx.Component:
    return rx.vstack(
        rx.text(
            "Solo contactos con opt-in activo. Deja un filtro vacío para no filtrar por él.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        field(
            "Marca",
            rx.select.root(
                rx.select.trigger(width="100%"),
                rx.select.content(rx.foreach(S.brand_options, _brand_item)),
                value=S.w_brand,
                on_change=S.set_brand,
            ),
        ),
        field(
            "Origen del consentimiento",
            rx.flex(
                *[_source_check(key, label) for key, label in SOURCES],
                gap="4",
                wrap="wrap",
            ),
            "Sin marcar ninguno, entran todos los orígenes.",
        ),
        rx.grid(
            field(
                "Capturado desde",
                rx.input(type="date", value=S.w_from, on_change=S.set_w_from, width="100%"),
            ),
            field(
                "Capturado hasta",
                rx.input(type="date", value=S.w_to, on_change=S.set_w_to, width="100%"),
            ),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="3",
            width="100%",
        ),
        field(
            "Prefijos de país",
            rx.input(
                value=S.w_prefixes,
                on_change=S.set_w_prefixes,
                placeholder="+57, +52",
                width="100%",
            ),
            "Separados por comas. Vacío = todos los países.",
        ),
        card(
            rx.hstack(
                rx.cond(S.counting, loading_spinner("sm"), rx.icon("users", size=T.ICON_MD)),
                rx.text(
                    rx.cond(S.counting, "Contando contactos…", S.audience_label),
                    size="2",
                    weight="medium",
                ),
                align="center",
                spacing="2",
            ),
            padding="0.75rem 1rem",
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _step_pacing() -> rx.Component:
    return rx.vstack(
        field(
            "Mensajes por minuto",
            rx.input(
                value=S.w_rate,
                on_change=S.set_w_rate,
                type="number",
                min="1",
                max=str(MAX_PER_MINUTE),
                width="10rem",
            ),
            "Un ritmo bajo cuida la calidad del número: si muchos lo bloquean o lo reportan, "
            "Meta baja su límite de envíos.",
        ),
        rx.cond(S.pacing_label != "", rx.text(S.pacing_label, size="2"), rx.fragment()),
        callout(
            "Meta además limita cuántas plantillas de marketing recibe cada persona: si "
            "alguien ya recibió muchas, el envío se omite (código 131049) y no se reintenta "
            "antes de 24 h.",
            "info",
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _step_review() -> rx.Component:
    t = S.selected_template
    return rx.vstack(
        card(
            rx.vstack(
                kv("Campaña", S.w_name),
                kv("Plantilla", t.option_label),
                kv("Destinatarios", S.audience_label),
                kv("Ritmo", S.rate_text),
                spacing="2",
                width="100%",
            ),
            padding="1rem 1.25rem",
        ),
        _estimate_block(S.w_estimate),
        callout(PAYMENT_NOTICE, "info", icon="credit-card"),
        rx.text(
            "Guardada como borrador. «Lanzar» encola los envíos; cerrar este panel la deja en "
            "la lista para lanzarla después.",
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
        rx.hstack(
            rx.cond(
                (S.step > STEP_TEMPLATE) & (S.step < STEP_REVIEW),
                rx.button(
                    rx.icon("chevron-left", size=16),
                    "Atrás",
                    on_click=S.back,
                    variant="soft",
                    size="2",
                    **T.tone_scheme("neutral"),
                ),
                rx.fragment(),
            ),
            rx.text(
                rx.cond(S.step < STEP_REVIEW, S.step_problem, ""),
                size="1",
                color=T.TEXT_MUTED,
                flex="1",
            ),
            rx.cond(
                S.step == STEP_REVIEW,
                rx.button(
                    rx.icon("send", size=16),
                    "Lanzar",
                    on_click=S.launch_campaign(S.w_campaign_id),
                    loading=S.launching,
                    size="2",
                ),
                rx.button(
                    rx.cond(S.step == STEP_PACING, "Guardar y revisar", "Siguiente"),
                    rx.icon("chevron-right", size=16),
                    on_click=S.next_step,
                    loading=S.w_busy,
                    disabled=S.step_problem != "",
                    size="2",
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
            stepper(
                list(STEPS),
                current=S.step,
                completed=S.completed_steps,
                on_select=S.go_to_step,
            ),
            rx.match(
                S.step,
                (STEP_TEMPLATE, _step_template()),
                (STEP_VARIABLES, _step_variables()),
                (STEP_AUDIENCE, _step_audience()),
                (STEP_PACING, _step_pacing()),
                (STEP_REVIEW, _step_review()),
                _step_template(),
            ),
            spacing="5",
            width="100%",
            align_items="start",
        ),
        open=S.wizard_open,
        on_open_change=S.set_wizard_open,
        title="Nueva campaña",
        description="Una plantilla aprobada, a tus contactos con opt-in, al ritmo que elijas.",
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
            stat_card("En cola", row.queued, tone="info"),
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
                rx.heading("Antes de lanzar", size="3", as_="h3"),
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
            rx.box(
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
            ),
            rx.fragment(),
        ),
        spacing="4",
        width="100%",
        align_items="start",
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
                    "Cancelar campaña",
                    loading=S.cancelling,
                    variant="soft",
                    size="2",
                    **T.tone_scheme("error"),
                ),
                title="Cancelar campaña",
                description="Los envíos que aún no salieron se retiran; los que ya salieron "
                "no se pueden deshacer. Una campaña cancelada no se puede reanudar.",
                verb="Cancelar campaña",
                dismiss="Seguir con la campaña",
                on_confirm=S.cancel_campaign,
            ),
            rx.fragment(),
        ),
        rx.cond(
            d.can_launch,
            rx.button(
                rx.icon("send", size=16),
                "Lanzar",
                on_click=S.launch_campaign(S.detail_id),
                loading=S.launching,
                size="2",
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
        title=rx.cond(S.detail.row.name != "", S.detail.row.name, "Campaña"),
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
            "Campañas",
            ghost_refresh("Actualizar", S.reload),
            rx.button(rx.icon("plus", size=16), "Nueva campaña", on_click=S.open_wizard, size="2"),
        ),
        rx.text(
            "Envía una plantilla aprobada a tus contactos con opt-in. Los costos son "
            "estimados; Meta cobra por mensaje entregado.",
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
