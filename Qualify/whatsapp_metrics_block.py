"""The metrics block of `/whatsapp` → Conexión (WA-17, QUA-216 · WA-21, QUA-220).

A KPI row of stat tiles (our own tables) and one small chart plus a cost table (read
from Meta). Per the dataviz rules: headline numbers are tiles, not charts; the one chart
is the "emphasis" form — sent as a gray track, delivered as the accent fill inside it,
one scale, a legend, the exact values on hover; status tones are not reused as series
colours. The block loads on its own `on_mount` (the Conexión tab is keyed by the number).
"""

from __future__ import annotations

import reflex as rx

from .ui import callout, card, skeleton_rows, stat_card, tag
from .ui import tokens as T
from .whatsapp_marketing_ui import ghost_refresh, tone_banner
from .whatsapp_metrics_state import WhatsAppMetricsState as S
from .whatsapp_metrics_vm import PERIODS, BarVM, CostLineVM, EntryVM

_CHART_HEIGHT = "7.5rem"
# Gray 7, not lower: the sent track must stay visible on the dark card (dataviz: the
# de-emphasis gray is still a mark, not the background).
_SENT_COLOR = T.tone_color("neutral", 7)
_DELIVERED_COLOR = T.tone_color("accent", 9)


def _entry(e: EntryVM) -> rx.Component:
    return tag(e.label + " · " + e.count)


def _kpis() -> rx.Component:
    m = S.metrics
    return rx.vstack(
        rx.grid(
            stat_card("Conversaciones nuevas", m.threads_opened, tone="accent"),
            stat_card(
                "Pedidos confirmados", m.orders_confirmed, tone="neutral", hint=m.orders_total
            ),
            stat_card("Traspasos a persona", m.handoffs, tone="neutral", hint=m.awaiting_human),
            stat_card(
                "Primera respuesta humana",
                m.median_first_response,
                tone="neutral",
                hint="Mediana · p90 " + m.p90_first_response,
            ),
            stat_card("Mensajes recibidos", m.messages_in, tone="neutral"),
            stat_card(
                "Mensajes enviados", m.messages_out, tone="neutral", hint=m.messages_out_detail
            ),
            columns=rx.breakpoints(initial="2", md="3"),
            spacing="3",
            width="100%",
        ),
        rx.cond(
            m.entry_counts.length() > 0,
            rx.vstack(
                rx.text("Por dónde llegaron", size="1", color=T.TEXT_MUTED),
                rx.flex(rx.foreach(m.entry_counts, _entry), gap="2", wrap="wrap"),
                spacing="1",
                align_items="start",
            ),
            rx.fragment(),
        ),
        rx.cond(m.qr_note != "", rx.text(m.qr_note, size="1", color=T.TEXT_FAINT), rx.fragment()),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _bar(b: BarVM) -> rx.Component:
    return rx.vstack(
        rx.tooltip(
            rx.box(
                rx.box(
                    position="absolute",
                    bottom="0",
                    left="0",
                    width="100%",
                    height=b.delivered_pct,
                    background=_DELIVERED_COLOR,
                    border_radius="4px 4px 0 0",
                ),
                position="relative",
                width="100%",
                height=b.sent_pct,
                min_height="2px",
                background=_SENT_COLOR,
                border_radius="4px 4px 0 0",
            ),
            content=b.tooltip,
        ),
        flex="1",
        min_width="4px",
        max_width="2.5rem",
        height=_CHART_HEIGHT,
        justify="end",
        spacing="0",
        aria_label=b.tooltip,
        role="img",
    )


def _axis_label(b: BarVM) -> rx.Component:
    return rx.box(
        rx.cond(
            b.show_label,
            rx.text(b.label, size="1", color=T.TEXT_FAINT, white_space="nowrap"),
            rx.fragment(),
        ),
        flex="1",
        min_width="4px",
        max_width="2.5rem",
        overflow="visible",
    )


def _swatch(color: rx.Var, label: str) -> rx.Component:
    return rx.hstack(
        rx.box(width="10px", height="10px", border_radius="3px", background=color),
        rx.text(label, size="1", color=T.TEXT_MUTED),
        spacing="1",
        align="center",
    )


def _cost_row(c: CostLineVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(c.category, size="2")),
        rx.table.cell(rx.text(c.volume, size="2", class_name="q-nums", text_align="right")),
        rx.table.cell(rx.text(c.billable, size="2", class_name="q-nums", text_align="right")),
        rx.table.cell(rx.text(c.cost, size="2", class_name="q-nums", text_align="right")),
    )


def _analytics() -> rx.Component:
    a = S.analytics
    return rx.vstack(
        rx.hstack(
            rx.text("Mensajes enviados y entregados por día", size="2", weight="medium"),
            rx.spacer(),
            _swatch(_SENT_COLOR, "Enviados"),
            _swatch(_DELIVERED_COLOR, "Entregados"),
            width="100%",
            align="center",
            spacing="3",
            wrap="wrap",
        ),
        rx.cond(
            a.has_traffic,
            rx.vstack(
                rx.hstack(
                    rx.foreach(a.bars, _bar),
                    spacing="1",
                    align="end",
                    justify="between",
                    width="100%",
                    border_bottom=T.BORDER,
                ),
                rx.hstack(
                    rx.foreach(a.bars, _axis_label),
                    spacing="1",
                    justify="between",
                    width="100%",
                ),
                spacing="1",
                width="100%",
            ),
            rx.text(
                "Meta no registra mensajes enviados desde este número en el periodo.",
                size="2",
                color=T.TEXT_MUTED,
            ),
        ),
        rx.text(
            a.sent_total
            + " enviados · "
            + a.delivered_total
            + " entregados · tasa de entrega "
            + a.delivery_rate,
            size="1",
            color=T.TEXT_MUTED,
            class_name="q-nums",
        ),
        rx.cond(
            a.cost_available,
            rx.vstack(
                rx.text("Costo por categoría (aproximado, según Meta)", size="2", weight="medium"),
                rx.box(
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("Categoría"),
                                rx.table.column_header_cell("Entregados", text_align="right"),
                                rx.table.column_header_cell("Cobrables", text_align="right"),
                                rx.table.column_header_cell("Costo", text_align="right"),
                            )
                        ),
                        rx.table.body(rx.foreach(a.costs, _cost_row)),
                        variant="surface",
                        size="1",
                        width="100%",
                    ),
                    overflow_x="auto",
                    width="100%",
                ),
                rx.text(
                    "Total: " + a.cost_total, size="1", color=T.TEXT_MUTED, class_name="q-nums"
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.text(
                "Meta no informa costos para esta cuenta en el periodo (o se factura a través "
                "de un proveedor).",
                size="1",
                color=T.TEXT_FAINT,
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def metrics_block() -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.heading("Actividad del número", size="3", as_="h2"),
                rx.spacer(),
                rx.segmented_control.root(
                    *[rx.segmented_control.item(label, value=key) for key, label in PERIODS],
                    value=S.period,
                    on_change=S.set_period,
                    size="1",
                ),
                ghost_refresh("Actualizar", S.reload),
                width="100%",
                align="center",
                spacing="2",
                wrap="wrap",
            ),
            rx.cond(
                S.metrics_error != "",
                callout(S.metrics_error, "error"),
                rx.cond(S.metrics_ready, _kpis(), skeleton_rows(2, height="5.5rem")),
            ),
            rx.divider(),
            rx.cond(
                S.analytics_ready,
                _analytics(),
                rx.cond(
                    S.analytics_notice != "",
                    tone_banner(S.analytics_notice, S.analytics_notice_tone),
                    skeleton_rows(1, height="9rem"),
                ),
            ),
            spacing="4",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
        on_mount=S.ensure_loaded,
    )
