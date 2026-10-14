"""Leads screen — the people this tenant has converted through its capture funnel.

Read-only for now: capture happens on the public form, analysis grows here later
(sources, interests, RFM). Reuses the scaffold's sidebar; the active tenant
comes from the login session (QUA-66).
"""

from __future__ import annotations

import reflex as rx

from .leads_provider import LeadVM
from .leads_state import LeadsState
from .ui import app_shell, callout, empty_state, page_body, page_header, skeleton_rows, tag
from .ui import tokens as T


def _topbar() -> rx.Component:
    return page_header(
        "Leads",
        "Personas captadas por tu funnel, con su consentimiento registrado",
        # The count badge of docs/design-system.md §5.3: soft, neutral — a figure
        # about the page, never a state.
        badge=rx.badge(
            LeadsState.lead_count.to_string() + " leads",
            variant="soft",
            size="2",
            **T.tone_scheme("neutral"),
        ),
    )


def _lead_row(lead: LeadVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(lead.full_name, weight="medium")),
        rx.table.cell(rx.link(lead.whatsapp_phone, href=lead.wa_href, target="_blank")),
        rx.table.cell(
            rx.cond(
                lead.interest != "",
                tag(lead.interest),
                rx.text("—", color=T.TEXT_FAINT),
            )
        ),
        rx.table.cell(
            rx.cond(
                lead.source != "",
                rx.text(lead.source, size="2"),
                rx.text("—", color=T.TEXT_FAINT),
            )
        ),
        rx.table.cell(rx.text(lead.extra_summary, size="1", color=T.TEXT_MUTED)),
        rx.table.cell(rx.text(lead.registered_at, size="1", color=T.TEXT_MUTED)),
    )


def _leads_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Nombre"),
                    rx.table.column_header_cell("WhatsApp"),
                    rx.table.column_header_cell("Interés"),
                    rx.table.column_header_cell("Fuente"),
                    rx.table.column_header_cell("Datos extra"),
                    rx.table.column_header_cell("Registro"),
                ),
            ),
            rx.table.body(rx.foreach(LeadsState.leads, _lead_row)),
            width="100%",
            variant="surface",
        ),
        overflow_x="auto",
        width="100%",
    )


def _empty_state() -> rx.Component:
    return empty_state(
        "user-plus",
        "Todavía no hay leads",
        "Comparte el formulario de captura de este negocio: cada registro "
        "con consentimiento aparecerá aquí.",
    )


def _body() -> rx.Component:
    return rx.cond(
        LeadsState.load_error != "",
        callout(LeadsState.load_error, "error"),
        rx.cond(
            LeadsState.is_loading,
            skeleton_rows(3),
            rx.cond(LeadsState.show_empty_state, _empty_state(), _leads_table()),
        ),
    )


def leads_index() -> rx.Component:
    return app_shell(_topbar(), page_body(_body()))
