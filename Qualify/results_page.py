"""Resultados — `/resultados` (m-24843003, RESULTADOS-5; `docs/ux-guia-navegacion.md` §3,
N1, N5, N8, N11, N12).

«¿Cómo me va?» in one place, instead of three screens (audit T3):

1. The header «Resultados» — the menu entry, the `h1` and the browser tab say the same (N1).
2. The tab strip — Redes · WhatsApp · Tu página web · Quién habla de ti, each with its own
   address (`?tab=`, N5). From `md` up a segmented control; on a phone a full-width select
   under the visible label «Estás viendo» (the pattern of «Por responder», m-24842990):
   four long labels do not fit 360 px and N12 allows no sideways scroll.
3. The open tab — only that one is in the tree, so only its data loads (and the mentions
   heartbeat stops when another tab opens):
   - «Redes» / «WhatsApp»: the week's figures, each a whole card linking to its list
     (N11); without the connection, what to connect (N8); a quiet week, a way out.
   - «Tu página web»: the Clarity reading screen (`clarity_page.clarity_content`).
   - «Quién habla de ti»: the mentions listing (`components`).

Only design-system primitives (`page_header`, `section`, `card(interactive=True)`,
`empty_state`, `callout`, `skeleton_card`), the segmented control and select every tabbed
screen already uses. Every target is ≥ 44 px and nothing depends on hover (N12).
"""

from __future__ import annotations

import reflex as rx

from .clarity_page import clarity_content
from .components import filter_bar, mentions_body, mentions_intro, stats_row
from .results_state import ResultsState as R
from .results_vm import (
    CONNECTIONS_URL,
    CREATE_URL,
    SUBTITLE,
    TAB_MENTIONS,
    TAB_SELECT_LABEL,
    TAB_SOCIAL,
    TAB_VMS,
    TAB_WEB,
    TAB_WHATSAPP,
    TITLE,
    WHATSAPP_MODULE_URL,
    WHATSAPP_NUMBERS_URL,
    WHATSAPP_QR_URL,
    ResultStatVM,
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
    skeleton_card,
)
from .ui import tokens as T

_TARGET = "44px"


# --- tab strip ----------------------------------------------------------------------------


def _segment(tab: TabVM) -> rx.Component:
    return rx.segmented_control.item(tab.label, value=tab.key)


def _option(tab: TabVM) -> rx.Component:
    return rx.select.item(tab.label, value=tab.key)


def _tab_strip() -> rx.Component:
    return rx.box(
        rx.box(
            rx.segmented_control.root(
                *[_segment(tab) for tab in TAB_VMS],
                value=R.active_tab,
                on_change=R.select_tab,
                size="3",
                aria_label="Qué resultados ver",
            ),
            display=["none", "none", "block"],
        ),
        rx.vstack(
            rx.text(TAB_SELECT_LABEL, size="2", weight="medium", color=T.TEXT_MUTED),
            rx.select.root(
                rx.select.trigger(
                    width="100%", min_height=_TARGET, aria_label="Qué resultados ver"
                ),
                rx.select.content(*[_option(tab) for tab in TAB_VMS]),
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


# --- figures ------------------------------------------------------------------------------


def _card_link(href: rx.Var[str] | str, *children: rx.Component) -> rx.Component:
    """A whole card that is a real link (keyboard and «atrás» work as with any link).
    No `aria_label`: the visible text — figure included — already names the link."""
    return rx.link(
        card(*children, interactive=True, min_height=_TARGET),
        href=href,
        underline="none",
        width="100%",
        display="block",
        color="inherit",
    )


def _stat(stat: rx.Var[ResultStatVM]) -> rx.Component:
    # Same anatomy as Inicio's «Así te fue» figures: the number in the accent, the words
    # in text tokens, and the chevron saying it opens something.
    return _card_link(
        stat.href,
        rx.hstack(
            rx.text(stat.label, size="2", color=T.TEXT_MUTED, flex="1"),
            rx.icon("chevron-right", size=T.ICON_MD, color=T.TEXT_MUTED),
            align="center",
            width="100%",
        ),
        rx.text(
            stat.value.to_string(),
            size="7",
            weight="bold",
            color=T.tone_color("accent", 10),
            class_name="q-nums",
            line_height="1.2",
        ),
        rx.text(stat.hint, size="1", color=T.TEXT_MUTED),
    )


def _stats_grid(stats: rx.Var[list[ResultStatVM]], md_columns: str) -> rx.Component:
    return rx.grid(
        rx.foreach(stats, _stat),
        columns=rx.breakpoints(initial="1", sm="2", md=md_columns),
        spacing="3",
        width="100%",
    )


def _full_width_button(label: str, icon: str, href: str) -> rx.Component:
    return rx.link(
        rx.button(
            rx.icon(icon, size=T.ICON_MD),
            label,
            size="3",
            width="100%",
            min_height=_TARGET,
        ),
        href=href,
        underline="none",
        width="100%",
        max_width="20rem",
    )


def _figures_loading() -> rx.Component:
    return rx.vstack(skeleton_card(2), skeleton_card(2), spacing="3", width="100%")


def _figures_error() -> rx.Component:
    return rx.vstack(
        callout(R.error, "error"),
        rx.cond(
            R.session_lost,
            _full_width_button("Iniciar sesión", "log-in", "/login"),
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_MD),
                "Reintentar",
                on_click=R.load,
                variant="soft",
                size="3",
                min_height=_TARGET,
            ),
        ),
        spacing="3",
        align_items="start",
        width="100%",
    )


def _figures(body: rx.Component) -> rx.Component:
    return rx.cond(
        R.loading,
        _figures_loading(),
        rx.cond(R.error != "", _figures_error(), body),
    )


def _social_tab() -> rx.Component:
    return section(
        "Tus redes esta semana",
        _figures(
            rx.cond(
                R.social_needs_connection,
                card(
                    empty_state(
                        "link",
                        "Conecta tu Instagram para ver esto",
                        "Aquí verás quién te escribió, quién comentó, qué publicaste y quién "
                        "habló de ti.",
                        action=_full_width_button("Conectar mi Instagram", "link", CONNECTIONS_URL),
                    ),
                ),
                rx.cond(
                    R.social_quiet,
                    card(
                        empty_state(
                            "message-circle",
                            "Esta semana todavía no hay movimiento",
                            "Una publicación nueva ayuda a que te escriban y comenten.",
                            action=_full_width_button(
                                "Crear publicación", "wand-sparkles", CREATE_URL
                            ),
                        ),
                    ),
                    _stats_grid(R.social, "4"),
                ),
            ),
        ),
        description="Los últimos 7 días en Instagram",
    )


def _whatsapp_tab() -> rx.Component:
    return section(
        "Tu WhatsApp esta semana",
        _figures(
            rx.cond(
                R.whatsapp_needs_connection,
                card(
                    empty_state(
                        "message-circle",
                        "Tu número de WhatsApp todavía no está conectado",
                        "El equipo de Qualify conecta el número de tu negocio. Cuando esté, "
                        "aquí verás cuántas personas te escribieron.",
                        action=_full_width_button(
                            "Ver tu WhatsApp", "message-circle", WHATSAPP_MODULE_URL
                        ),
                    ),
                ),
                rx.cond(
                    R.whatsapp_quiet,
                    card(
                        empty_state(
                            "message-circle",
                            "Esta semana nadie te escribió por WhatsApp",
                            "Comparte tu código QR para que te escriban más fácil.",
                            action=_full_width_button(
                                "Ver tus códigos QR", "qr-code", WHATSAPP_QR_URL
                            ),
                        ),
                    ),
                    rx.vstack(
                        _stats_grid(R.whatsapp, "2"),
                        rx.link(
                            "Ver más detalles en WhatsApp",
                            href=WHATSAPP_NUMBERS_URL,
                            size="2",
                            min_height=_TARGET,
                            display="inline-flex",
                            align_items="center",
                        ),
                        spacing="2",
                        width="100%",
                    ),
                ),
            ),
        ),
        description="Los últimos 7 días",
    )


def _web_tab() -> rx.Component:
    return clarity_content()


def _mentions_tab() -> rx.Component:
    return rx.vstack(
        mentions_intro(),
        stats_row(),
        filter_bar(),
        mentions_body(),
        spacing="4",
        width="100%",
    )


def _tab_body() -> rx.Component:
    """Only the open tab is in the tree, so only its data loads (and polls)."""
    return rx.box(
        rx.match(
            R.active_tab,
            (TAB_SOCIAL, _social_tab()),
            (TAB_WHATSAPP, _whatsapp_tab()),
            (TAB_WEB, _web_tab()),
            (TAB_MENTIONS, _mentions_tab()),
            _social_tab(),
        ),
        width="100%",
    )


def results_index() -> rx.Component:
    return app_shell(
        # The literal title: `test_nav_one_name` checks menu, header and tab say the same.
        page_header("Resultados", SUBTITLE),
        page_body(_tab_strip(), _tab_body()),
    )


__all__ = ["TITLE", "results_index"]
