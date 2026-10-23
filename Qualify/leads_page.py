"""«Clientes interesados» (/leads, and the «Interesados» tab of «Por responder») — the
people who left their details on this tenant's form and accepted being contacted.

m-24842992: one card per person (no table, so nothing scrolls sideways at 360 px), with
«Escribirle por WhatsApp ↗» (≥ 44 px) that opens the owner's own WhatsApp, and the state
«Pendiente» / «Ya le escribiste» as words. The empty state gives the form's real link with
«Copiar enlace» when the business has one (N8). Copy lives in `leads_vm`.
"""

from __future__ import annotations

import reflex as rx

from .leads_provider import LeadVM
from .leads_state import LeadsState
from .leads_vm import (
    CONTACTED_LABEL,
    CONTACTED_TONE,
    COPY_LINK_LABEL,
    EMPTY_NO_LINK,
    EMPTY_TITLE,
    EMPTY_WITH_LINK,
    EXTRA_LABEL,
    HOW_IT_WORKS,
    INTRO,
    LINK_COPIED,
    MARK_PENDING_LABEL,
    PENDING_LABEL,
    PENDING_TONE,
    WRITE_LABEL,
)
from .ui import (
    app_shell,
    callout,
    card,
    empty_state,
    mono,
    page_body,
    page_header,
    signal_pill,
    skeleton_rows,
    tag,
)
from .ui import tokens as T

#: N12: every tap target on this screen is at least this tall.
_TARGET = "44px"


def _topbar() -> rx.Component:
    return page_header(
        "Clientes interesados",
        INTRO,
        # The count badge of docs/design-system.md §5.3: soft, neutral — a figure
        # about the page, never a state.
        badge=rx.badge(
            LeadsState.lead_count.to_string(),
            variant="soft",
            size="2",
            **T.tone_scheme("neutral"),
        ),
    )


def _status(lead: LeadVM) -> rx.Component:
    return rx.cond(
        lead.contacted,
        signal_pill(CONTACTED_LABEL, CONTACTED_TONE, size="2"),
        signal_pill(PENDING_LABEL, PENDING_TONE, size="2"),
    )


def _lead_card(lead: LeadVM) -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.text(lead.full_name, weight="medium", size="3"),
                _status(lead),
                justify="between",
                align="center",
                width="100%",
                wrap="wrap",
                spacing="2",
            ),
            rx.cond(
                lead.interest != "",
                rx.hstack(
                    rx.text("Le interesa:", size="2", color=T.TEXT_MUTED),
                    tag(lead.interest, size="2"),
                    align="center",
                    spacing="2",
                    wrap="wrap",
                ),
            ),
            rx.cond(
                lead.extra_summary != "",
                rx.text(EXTRA_LABEL + " " + lead.extra_summary, size="2", color=T.TEXT_MUTED),
            ),
            rx.text(lead.registered_at, size="1", color=T.TEXT_MUTED),
            # One tappable element only: a link that looks like a button (as_child), so a
            # keyboard or screen reader stops once and mobile browsers see one tap.
            rx.button(
                # A plain <a>, not rx.link: Radix Link would paint its own text colour
                # over the solid button.
                rx.el.a(
                    rx.icon("message-circle", size=16),
                    WRITE_LABEL,
                    href=lead.wa_href,
                    target="_blank",
                    rel="noopener noreferrer",
                ),
                as_child=True,
                size="3",
                width="100%",
                min_height=_TARGET,
                on_click=LeadsState.mark_contacted(lead.id),
                aria_label="Escribirle a " + lead.full_name + " por WhatsApp (se abre WhatsApp)",
            ),
            rx.cond(
                lead.contacted,
                rx.hstack(
                    rx.text(lead.contacted_note, size="1", color=T.TEXT_MUTED),
                    rx.button(
                        MARK_PENDING_LABEL,
                        variant="ghost",
                        size="2",
                        min_height=_TARGET,
                        on_click=LeadsState.mark_pending(lead.id),
                    ),
                    justify="between",
                    align="center",
                    width="100%",
                    wrap="wrap",
                    spacing="2",
                ),
            ),
            spacing="2",
            width="100%",
            align="start",
        ),
        padding="1rem",
        width="100%",
    )


def _leads_list() -> rx.Component:
    return rx.vstack(
        rx.text(HOW_IT_WORKS, size="2", color=T.TEXT_MUTED),
        rx.text(LeadsState.pending_summary, size="3", weight="medium"),
        rx.cond(LeadsState.mark_error != "", callout(LeadsState.mark_error, "error")),
        # One column on phones; two side by side from tablet up. Never a table (N12).
        rx.grid(
            rx.foreach(LeadsState.leads, _lead_card),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="3",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def _form_link_action() -> rx.Component:
    return rx.vstack(
        mono(LeadsState.form_link, size="2", overflow_wrap="anywhere", text_align="center"),
        rx.button(
            rx.icon("copy", size=16),
            COPY_LINK_LABEL,
            size="3",
            min_height=_TARGET,
            on_click=[rx.set_clipboard(LeadsState.form_link), rx.toast.success(LINK_COPIED)],
        ),
        spacing="2",
        align="center",
        width="100%",
        max_width="440px",
    )


def _empty_state() -> rx.Component:
    return rx.cond(
        LeadsState.has_form_link,
        empty_state("user-plus", EMPTY_TITLE, EMPTY_WITH_LINK, action=_form_link_action()),
        empty_state("user-plus", EMPTY_TITLE, EMPTY_NO_LINK),
    )


def _body() -> rx.Component:
    return rx.cond(
        LeadsState.load_error != "",
        callout(LeadsState.load_error, "error"),
        rx.cond(
            LeadsState.is_loading,
            skeleton_rows(3),
            rx.cond(LeadsState.show_empty_state, _empty_state(), _leads_list()),
        ),
    )


def leads_tab() -> rx.Component:
    """m-24842990: the «Interesados» tab of «Por responder» — the same list, with the
    page's description as the tab's opening line."""
    return rx.vstack(
        rx.text(INTRO, size="2", color=T.TEXT_MUTED),
        _body(),
        spacing="3",
        width="100%",
    )


def leads_index() -> rx.Component:
    return app_shell(_topbar(), page_body(_body()))
