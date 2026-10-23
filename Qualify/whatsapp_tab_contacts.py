"""`/whatsapp` → Contactos tab (WA-19, QUA-218): the opt-ins (who agreed to receive this
business's WhatsApp messages), the import from the lead form, manual add and revoke.

Same hook as the other tabs: rendered only while active, inside the shell's box keyed by
the number; the root's `on_mount` loads (opt-ins are tenant-wide, so a number switch
costs no second read). The page never talks to the provider — only to the state.
"""

from __future__ import annotations

import reflex as rx

from .ui import callout, drawer, empty_state, mono, skeleton_rows, tag
from .ui import tokens as T
from .whatsapp_contacts_state import WhatsAppContactsState as S
from .whatsapp_contacts_vm import FILTERS, IMPORT_CONDITION, OptInVM
from .whatsapp_marketing_ui import (
    confirm_action,
    field,
    ghost_refresh,
    retry_button,
    section_head,
    tone_banner,
    tone_pill,
)


def _revoke_action(o: OptInVM) -> rx.Component:
    return confirm_action(
        rx.button(
            rx.icon("user-x", size=T.ICON_SM),
            "Revocar",
            loading=S.revoking_phone == o.phone,
            variant="soft",
            size="1",
            **T.tone_scheme("neutral"),
        ),
        title="Revocar consentimiento",
        description=rx.text(
            rx.text.strong(o.phone),
            " deja de recibir campañas. Solo vuelve a estar activo si da un consentimiento nuevo.",
        ),
        verb="Revocar",
        on_confirm=S.revoke_phone(o.phone),
    )


def _row(o: OptInVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.vstack(
                mono(o.phone, weight="medium"),
                rx.cond(
                    o.brand != "", rx.text(o.brand, size="1", color=T.TEXT_MUTED), rx.fragment()
                ),
                spacing="0",
                align_items="start",
            )
        ),
        rx.table.cell(tag(o.source_label)),
        rx.table.cell(rx.text(o.captured_at, size="1", color=T.TEXT_MUTED, class_name="q-nums")),
        rx.table.cell(
            rx.vstack(
                tone_pill(o.status_label, o.status_tone),
                rx.cond(
                    o.revoked_detail != "",
                    rx.text(o.revoked_detail, size="1", color=T.TEXT_MUTED),
                    rx.fragment(),
                ),
                spacing="1",
                align_items="start",
            )
        ),
        rx.table.cell(
            rx.tooltip(
                rx.text(
                    o.consent_text,
                    size="1",
                    color=T.TEXT_MUTED,
                    max_width="18rem",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                content=o.consent_text,
            )
        ),
        rx.table.cell(rx.cond(o.is_active, _revoke_action(o), rx.fragment())),
        align="center",
    )


def _table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Número"),
                    rx.table.column_header_cell("Origen"),
                    rx.table.column_header_cell("Capturado"),
                    rx.table.column_header_cell("Estado"),
                    rx.table.column_header_cell("Texto aceptado"),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(rx.foreach(S.opt_ins, _row)),
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
            S.has_opt_ins,
            _table(),
            empty_state(
                "users",
                "Aún no hay contactos con consentimiento",
                "Solo puedes enviar campañas a quien aceptó recibir mensajes de WhatsApp de "
                "tu negocio. Impórtalos del formulario de leads o agrégalos a mano.",
                # N8 (m-24842961).
                action=rx.button(
                    rx.icon("user-plus", size=16),
                    "Agregar contacto",
                    on_click=S.open_add,
                    variant="soft",
                    size="3",
                ),
            ),
        ),
        rx.cond(
            S.failed,
            retry_button("Volver a leer los contactos", S.reload),
            skeleton_rows(4, height="3rem"),
        ),
    )


def _import_action() -> rx.Component:
    return confirm_action(
        rx.button(
            rx.icon("download", size=16),
            "Importar del formulario de leads",
            loading=S.importing,
            on_click=S.prepare_import,
            variant="soft",
            size="2",
            **T.tone_scheme("neutral"),
        ),
        title="Importar del formulario de leads",
        description=rx.vstack(
            rx.text(IMPORT_CONDITION, weight="medium"),
            rx.text(
                "Cada lead con consentimiento se agrega con el texto del formulario y la "
                "fecha en que lo aceptó. Quien escribió STOP después no se reactiva.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.cond(
                S.lead_consent != "",
                rx.vstack(
                    rx.text("Texto actual del formulario", size="1", color=T.TEXT_MUTED),
                    rx.blockquote(S.lead_consent, size="2"),
                    spacing="1",
                    width="100%",
                ),
                rx.text(
                    "Tu negocio aún no tiene formulario de leads.", size="2", color=T.TEXT_MUTED
                ),
            ),
            spacing="3",
            align_items="start",
        ),
        verb="Importar",
        on_confirm=S.run_import,
        tone="accent",
    )


def _add_drawer() -> rx.Component:
    return drawer(
        rx.vstack(
            callout(
                "Meta exige que la persona haya aceptado recibir mensajes de WhatsApp de tu "
                "negocio, nombrándolo. Guarda aquí el texto exacto que aceptó.",
                "info",
            ),
            field(
                "Número de WhatsApp",
                rx.input(
                    value=S.add_phone,
                    on_change=S.set_add_phone,
                    placeholder="+57 300 1234567",
                    type="tel",
                    width="100%",
                ),
                "Con el indicativo del país.",
            ),
            field(
                "Texto que aceptó",
                rx.text_area(
                    value=S.add_consent,
                    on_change=S.set_add_consent,
                    rows="4",
                    width="100%",
                ),
                "Debe nombrar a tu negocio y decir que recibirá mensajes de WhatsApp.",
            ),
            rx.cond(S.add_error != "", callout(S.add_error, "warn"), rx.fragment()),
            spacing="4",
            width="100%",
            align_items="start",
        ),
        open=S.add_open,
        on_open_change=S.set_add_open,
        title="Agregar contacto",
        description="Un número que te dio su consentimiento fuera de Qualify.",
        footer=rx.hstack(
            rx.spacer(),
            rx.button(
                rx.icon("user-plus", size=16),
                "Agregar contacto",
                on_click=S.submit_add,
                loading=S.adding,
                size="2",
            ),
            width="100%",
        ),
        icon="user-plus",
    )


def contacts_tab() -> rx.Component:
    return rx.vstack(
        tone_banner(S.banner, S.banner_tone),
        section_head(
            "Contactos con consentimiento",
            ghost_refresh("Actualizar", S.reload, loading=S.loading),
            _import_action(),
            rx.button(
                rx.icon("user-plus", size=16), "Agregar contacto", on_click=S.open_add, size="2"
            ),
        ),
        rx.text(
            "Solo estos números pueden recibir tus campañas de marketing. Quien escribe STOP, "
            "BAJA o CANCELAR queda revocado solo.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.segmented_control.root(
            *[rx.segmented_control.item(label, value=key) for key, label in FILTERS],
            value=S.view_filter,
            on_change=S.set_filter,
            size="1",
        ),
        _list(),
        _add_drawer(),
        spacing="4",
        width="100%",
        align_items="start",
        on_mount=S.ensure_loaded,
    )
