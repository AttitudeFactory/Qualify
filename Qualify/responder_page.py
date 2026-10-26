"""«Por responder» (`/responder`, m-24842990, ATENDER-1): one place with everyone who
waits for the owner's answer (founder decision 3, 2026-10-23).

Layout (docs/design-system.md §9.1): `app_shell(page_header(...), page_body(...))`.

1. **Who is waiting** — four rows (Instagram messages, people who want to buy, comments
   with a reply ready, WhatsApp chats), each a figure + «Ver» to its list already
   filtered (N11). With nobody waiting, one empty state with the next step: create the
   next publication (N8). Loading is a skeleton; a failed count says so with «Reintentar».
2. **The tabs** Mensajes · Quieren comprar · Comentarios · WhatsApp · Interesados, each at
   `?tab=` (N5). From the `md` breakpoint up a segmented control; on a phone a select —
   five segments do not fit 360 px and N12 allows no sideways scroll for tabs.
3. **The open tab's list** — only that tab is in the tree, so only its state loads. Each
   list is the existing screen's own content (`conversations_page.messages_tab`,
   `followups_page.followups_panel`, `inbox_page.comments_tab`, `leads_page.leads_tab`);
   WhatsApp chats stay in the WhatsApp module (merging the inboxes is out of scope), so
   that tab links to `/whatsapp?tab=chats`.

Data: `ResponderState` (`responder_state.py`) over `responder_provider` → VMs from
`responder_vm.py`. The page imports neither the provider nor any backend module.
"""

from __future__ import annotations

import reflex as rx

from .conversations_page import messages_tab
from .followups_page import followups_panel
from .inbox_page import comments_tab
from .leads_page import leads_tab
from .responder_state import ResponderState
from .responder_vm import (
    ALL_CLEAR_ACTION,
    ALL_CLEAR_BODY,
    ALL_CLEAR_HREF,
    ALL_CLEAR_TITLE,
    TAB_BUYERS,
    TAB_COMMENTS,
    TAB_LEADS,
    TAB_MESSAGES,
    TAB_SELECT_LABEL,
    TAB_WHATSAPP,
    WHATSAPP_CHATS_HREF,
    WHATSAPP_TAB_ACTION,
    WHATSAPP_TAB_TITLE,
    CountRowVM,
    TabVM,
)
from .ui import (
    app_shell,
    callout,
    card,
    empty_state,
    page_body,
    page_header,
    section,
    skeleton_rows,
    tone_badge,
)
from .ui import tokens as T
from .ui.route_history import route_history

R = ResponderState

#: N12: every target a thumb hits is at least 44 px tall.
_TARGET = "44px"


# ======================================================================================
# Who is waiting
# ======================================================================================


def _count_row(row: CountRowVM) -> rx.Component:
    """The whole row opens its list (N11: the figure itself is the way in); «Ver ›» is
    only the visual hint, not a second link."""
    return rx.link(
        card(
            rx.flex(
                rx.hstack(
                    rx.icon(row.icon, size=T.ICON_MD, color=T.TEXT_MUTED, flex_shrink="0"),
                    rx.vstack(
                        rx.text(
                            row.label, size="2", weight="medium", color=T.tone_color("neutral", 12)
                        ),
                        rx.cond(
                            row.tone == "warn",
                            tone_badge(row.count_label, "warn", icon="bell"),
                            tone_badge(row.count_label, "ok", icon="check"),
                        ),
                        spacing="1",
                        align_items="start",
                    ),
                    spacing="3",
                    align="center",
                    flex="1",
                    min_width="0",
                ),
                rx.hstack(
                    rx.text(row.action_label, size="2", weight="medium"),
                    rx.icon("chevron-right", size=T.ICON_SM),
                    spacing="1",
                    align="center",
                    color=T.tone_color("accent", 11),
                    flex_shrink="0",
                ),
                direction="row",
                gap="3",
                align="center",
                justify="between",
                width="100%",
                min_height=_TARGET,
            ),
            padding="0.875rem 1rem",
            interactive=True,
        ),
        href=row.href,
        aria_label=row.label + ": " + row.count_label,
        underline="none",
        display="block",
        width="100%",
    )


def _all_clear() -> rx.Component:
    return card(
        empty_state(
            "circle-check",
            ALL_CLEAR_TITLE,
            ALL_CLEAR_BODY,
            action=rx.link(
                rx.button(
                    rx.icon("wand-sparkles", size=T.ICON_SM),
                    ALL_CLEAR_ACTION,
                    size="3",
                    min_height=_TARGET,
                ),
                href=ALL_CLEAR_HREF,
            ),
        ),
    )


def _counts() -> rx.Component:
    return rx.cond(
        R.counts_error != "",
        rx.vstack(
            callout(R.counts_error, "error"),
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                "Reintentar",
                on_click=R.load_counts,
                loading=R.counts_loading,
                variant="soft",
                size="3",
                min_height=_TARGET,
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        rx.cond(
            R.show_counts_skeleton,
            skeleton_rows(4, height="4.5rem"),
            rx.cond(
                R.is_all_clear,
                _all_clear(),
                rx.vstack(rx.foreach(R.rows, _count_row), spacing="2", width="100%"),
            ),
        ),
    )


# ======================================================================================
# Tabs
# ======================================================================================


def _segment(tab: TabVM) -> rx.Component:
    return rx.segmented_control.item(tab.label, value=tab.key)


def _option(tab: TabVM) -> rx.Component:
    return rx.select.item(tab.label, value=tab.key)


def _tab_strip() -> rx.Component:
    """Each label carries its figure («Quieren comprar · 1») so what waits in another
    list shows without opening it."""
    return rx.box(
        # md and up: the segmented control every tabbed screen of the app uses.
        rx.box(
            rx.segmented_control.root(
                rx.foreach(R.tabs, _segment),
                value=R.active_tab,
                on_change=R.select_tab,
                size="3",
                aria_label="Qué ver",
            ),
            display=["none", "none", "block"],
        ),
        # Phones: one select, full width — five segments would need a sideways scroll.
        # A visible label says it is the way to the other lists, not a form field.
        rx.vstack(
            rx.text(
                TAB_SELECT_LABEL,
                size="2",
                color=T.TEXT_MUTED,
                as_="label",
            ),
            rx.select.root(
                rx.select.trigger(width="100%", min_height=_TARGET, aria_label="Qué ver"),
                rx.select.content(rx.foreach(R.tabs, _option)),
                value=R.active_tab,
                on_change=R.select_tab,
                size="3",
            ),
            spacing="1",
            display=["flex", "flex", "none"],
            width="100%",
        ),
        width="100%",
    )


def _whatsapp_tab() -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.icon("message-circle", size=T.ICON_MD, color=T.TEXT_MUTED),
                rx.heading(WHATSAPP_TAB_TITLE, size="4", as_="h2"),
                spacing="2",
                align="center",
            ),
            rx.text(R.whatsapp_text, size="2", color=T.TEXT_MUTED),
            rx.link(
                rx.button(
                    WHATSAPP_TAB_ACTION,
                    rx.icon("chevron-right", size=T.ICON_SM),
                    size="3",
                    min_height=_TARGET,
                ),
                href=WHATSAPP_CHATS_HREF,
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
    )


def _tab_body() -> rx.Component:
    """Only the open tab is in the tree, so only its list loads and polls."""
    return rx.box(
        rx.match(
            R.active_tab,
            (TAB_MESSAGES, messages_tab()),
            (TAB_BUYERS, followups_panel()),
            (TAB_COMMENTS, comments_tab()),
            (TAB_WHATSAPP, _whatsapp_tab()),
            (TAB_LEADS, leads_tab()),
            messages_tab(),
        ),
        width="100%",
    )


# ======================================================================================
# Page
# ======================================================================================


def responder_header() -> rx.Component:
    return page_header(
        "Por responder",
        "Las personas que te escribieron o comentaron y todavía esperan tu respuesta.",
    )


def _who_is_waiting() -> rx.Component:
    """On a phone, «Quién te espera» shows only on the way in (`/responder` with no
    `?tab=`): after a «Ver» the owner lands on the list, not on the figures again. The
    figures still travel in the tab labels. From md up it always shows."""
    return rx.cond(
        R.has_tab_param,
        rx.box(section("Quién te espera", _counts()), display=["none", "none", "block"]),
        section("Quién te espera", _counts()),
    )


def responder_index() -> rx.Component:
    return app_shell(
        route_history(ResponderState.enter_history, on_leave=ResponderState.leave_page_flows),
        responder_header(),
        page_body(
            _who_is_waiting(),
            rx.vstack(_tab_strip(), _tab_body(), spacing="4", width="100%"),
        ),
    )


def legacy_redirect() -> rx.Component:
    """The body of `/inbox`, `/conversations` and `/leads`: nothing — their `on_load`
    redirects to the tab (`ResponderState.redirect_legacy`)."""
    return rx.fragment()
