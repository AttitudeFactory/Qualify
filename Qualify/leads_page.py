"""Leads screen — the people this tenant has converted through its capture funnel.

Read-only for now: capture happens on the public form, analysis grows here later
(sources, interests, RFM). Reuses the scaffold's sidebar and the dev tenant selector
pattern from the connections page.
"""

from __future__ import annotations

import reflex as rx

from .components import sidebar
from .leads_provider import LeadVM
from .leads_state import LeadsState
from .tenant import TenantChoice


def _tenant_item(tenant: TenantChoice) -> rx.Component:
    return rx.select.item(tenant.label, value=tenant.id)


def _dev_tenant_selector() -> rx.Component:
    return rx.hstack(
        rx.badge("DEV", color_scheme="orange", variant="solid", size="1"),
        rx.text("Sesión como:", size="2", color=rx.color("gray", 10)),
        rx.select.root(
            rx.select.trigger(placeholder="Elige un tenant"),
            rx.select.content(rx.foreach(LeadsState.tenant_options, _tenant_item)),
            value=LeadsState.session_tenant_id,
            on_change=LeadsState.switch_tenant,
            size="2",
        ),
        spacing="2",
        align="center",
        padding="0.5rem 0.75rem",
        border=f"1px dashed {rx.color('orange', 7)}",
        border_radius="0.5rem",
        background=rx.color("orange", 2),
    )


def _topbar() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.heading("Leads", size="6"),
            rx.text(
                "Personas captadas por tu funnel, con su consentimiento registrado",
                size="2",
                color=rx.color("gray", 10),
            ),
            spacing="0",
            align_items="start",
        ),
        rx.spacer(),
        rx.badge(
            LeadsState.lead_count.to_string() + " leads",
            variant="soft",
            color_scheme="grass",
            size="2",
        ),
        _dev_tenant_selector(),
        rx.color_mode.button(),
        width="100%",
        padding="1.5rem 2rem 1rem 2rem",
        align="center",
        spacing="3",
    )


def _lead_row(lead: LeadVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(lead.full_name, weight="medium")),
        rx.table.cell(rx.link(lead.whatsapp_phone, href=lead.wa_href, target="_blank")),
        rx.table.cell(
            rx.cond(
                lead.interest != "",
                rx.badge(lead.interest, variant="soft", color_scheme="violet", size="1"),
                rx.text("—", color=rx.color("gray", 8)),
            )
        ),
        rx.table.cell(
            rx.cond(
                lead.source != "",
                rx.text(lead.source, size="2"),
                rx.text("—", color=rx.color("gray", 8)),
            )
        ),
        rx.table.cell(rx.text(lead.extra_summary, size="1", color=rx.color("gray", 10))),
        rx.table.cell(rx.text(lead.registered_at, size="1", color=rx.color("gray", 10))),
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
        padding="0 2rem 2rem 2rem",
        width="100%",
    )


def _empty_state() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon("user-plus", size=40, color=rx.color("gray", 8)),
            rx.heading("Todavía no hay leads", size="5"),
            rx.text(
                "Comparte el formulario de captura de este negocio: cada registro "
                "con consentimiento aparecerá aquí.",
                size="2",
                color=rx.color("gray", 10),
                text_align="center",
                max_width="420px",
            ),
            spacing="3",
            align="center",
        ),
        padding="4rem 2rem",
        width="100%",
    )


def _load_error() -> rx.Component:
    return rx.box(
        rx.callout(
            LeadsState.load_error,
            icon="triangle-alert",
            color_scheme="tomato",
            width="100%",
        ),
        padding="0 2rem 2rem 2rem",
        width="100%",
    )


def _body() -> rx.Component:
    return rx.cond(
        LeadsState.load_error != "",
        _load_error(),
        rx.cond(
            LeadsState.is_loading,
            rx.box(
                rx.vstack(
                    rx.skeleton(rx.box(height="2.5rem", width="100%")),
                    rx.skeleton(rx.box(height="2.5rem", width="100%")),
                    rx.skeleton(rx.box(height="2.5rem", width="100%")),
                    spacing="3",
                    width="100%",
                ),
                padding="0 2rem 2rem 2rem",
                width="100%",
            ),
            rx.cond(LeadsState.show_empty_state, _empty_state(), _leads_table()),
        ),
    )


def leads_index() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.vstack(
            _topbar(),
            _body(),
            width="100%",
            spacing="4",
            align_items="start",
        ),
        width="100%",
        spacing="0",
        align_items="start",
    )
