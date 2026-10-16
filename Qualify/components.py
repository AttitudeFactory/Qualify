"""Mentions dashboard blocks + backwards-compatible re-exports.

The shell pieces (``sidebar``, ``session_badge``) now live in ``Qualify/ui/layout.py``
and are re-exported here so older imports keep working; new code should import from
``.ui`` directly. What remains in this module is specific to the mentions dashboard
(QUA-49; paginated, auto-refreshed, one meaning per column since QUA-152).

Layout (QUA-152, founder review 2026-10-13): the page header carries only the title. The
table lives in its own panel (a ``card``) whose header holds this module's refresh —
never beside the app-wide theme toggle — and whose footer holds the compact pager. The
summary cards describe the scope (account + period) and do not move with a search.
"""

import reflex as rx

from .mentions_paging import ORIGIN_OPTIONS, PERIOD_OPTIONS, SENTIMENT_OPTIONS
from .state import DashboardState, MentionRow
from .ui import (
    callout,
    card,
    empty_state,
    mono,
    page_header,
    platform_badge,
    sentiment_badge,
    session_badge,
    sidebar,
    signal_pill,
    skeleton_rows,
    stat_card,
    tag,
)
from .ui import tokens as T

__all__ = [
    "filter_bar",
    "mentions_body",
    "mentions_table",
    "platform_badge",
    "sentiment_badge",
    "session_badge",
    "sidebar",
    "stat_card",
    "stats_row",
    "topbar",
]

# QUA-152: the refresh heartbeat (`rx.moment`'s `interval`, a browser-side setInterval —
# same mechanism as `/inbox`'s QUA-89 timer). 45 s: inside the ticket's 30–60 s window.
_REFRESH_INTERVAL_MS = 45 * 1000

# The "Mención" column has a fixed width (founder review 2026-10-13): a long mention is
# cut with an ellipsis in the row and read in full in the hover card.
_MENTION_COL_WIDTH = rx.breakpoints(initial="220px", xl="260px")

# Responsive layout (2026-10-13): the 8-column table from Radix `lg` (1280 px) up — below
# that the sidebar leaves ~700 px, measured too narrow for it. Below it (phones, tablets,
# small laptops) each mention is a card and the pager shrinks to "‹ Página n de N ›". A
# hover card does not exist on touch, so the card shows the text itself.
#
# The switch is a CSS class, not `rx.breakpoints` on `display` (2026-10-16). In the exported
# build the global stylesheet is linked twice (once in the prerendered head, once more by the
# hydration, AFTER emotion's style tags), so Radix's `.rt-Box { display: block }` outranked
# emotion's media rules and the table and the cards showed at once. The rules live in
# assets/qualify-listen.css, which is compiled INTO that global stylesheet after Radix's
# own rules — the `.q-wa-chats` pattern — so they win in every copy of it.
_TABLE_ONLY = "q-mentions-table-only"
_CARDS_ONLY = "q-mentions-cards-only"
# Breathing room after the mention, so its column never reads as glued to Sentimiento.
_MENTION_GUTTER = "2rem"

_NO_LINK_NOTE = "La red social no devolvió el enlace de esta mención."


def _refresh_timer() -> rx.Component:
    """Hidden heartbeat: every tick re-reads the current page under the same snapshot and
    counts new mentions (`DashboardState.refresh_tick`). It unmounts — and stops — with
    the page; nothing runs server-side between ticks."""
    return rx.moment(
        interval=_REFRESH_INTERVAL_MS,
        on_change=lambda _tick: DashboardState.refresh_tick,
        display="none",
    )


def _muted(value: rx.Var | str, **props) -> rx.Component:
    return rx.text(value, size="2", color=T.TEXT_MUTED, **props)


def topbar() -> rx.Component:
    # Channel-neutral on purpose (founder review 2026-10-13): mentions will come from
    # several channels; the channel of each one is its own column, never the page title.
    return page_header(
        "Menciones",
        "Publicaciones y comentarios de tus redes sociales que mencionan tu cuenta.",
    )


def stats_row() -> rx.Component:
    """The summary of the scope (account + period). A search, an origin or a sentiment
    filter narrows the TABLE, never these cards. Mentions that are not (yet) a polarity
    are listed under the total, never folded into one."""
    return rx.grid(
        stat_card(
            "Total menciones",
            DashboardState.total_mentions,
            "accent",
            hint=DashboardState.states_hint,
        ),
        stat_card("Positivas", DashboardState.positive_count, "ok"),
        stat_card("Neutras", DashboardState.neutral_count, "neutral"),
        stat_card("Negativas", DashboardState.negative_count, "error"),
        columns=rx.breakpoints(initial="2", md="4"),
        spacing="3",
        width="100%",
    )


def filter_bar() -> rx.Component:
    return rx.hstack(
        rx.cond(
            DashboardState.show_account_filter,
            rx.select(
                DashboardState.account_options,
                value=DashboardState.account_filter,
                on_change=DashboardState.set_account_filter,
                size="2",
            ),
        ),
        rx.select(
            list(PERIOD_OPTIONS),
            value=DashboardState.period_filter,
            on_change=DashboardState.set_period_filter,
            size="2",
        ),
        rx.select(
            list(ORIGIN_OPTIONS),
            value=DashboardState.origin_filter,
            on_change=DashboardState.set_origin_filter,
            size="2",
        ),
        rx.select(
            list(SENTIMENT_OPTIONS),
            value=DashboardState.sentiment_filter,
            on_change=DashboardState.set_sentiment_filter,
            size="2",
        ),
        _refresh_button(),
        spacing="2",
        wrap="wrap",
        align="center",
        width="100%",
    )


# --- the table panel ---------------------------------------------------------------------


def _refresh_button() -> rx.Component:
    """This module's refresh: one icon, at the end of its own filter row — never beside
    the app-wide theme toggle (founder review 2026-10-13)."""
    return rx.tooltip(
        rx.icon_button(
            rx.icon("refresh-cw", size=T.ICON_SM),
            size="2",
            variant="soft",
            loading=DashboardState.is_refreshing,
            on_click=DashboardState.refresh_now,
            aria_label="Actualizar menciones",
        ),
        content="Actualizar menciones",
    )


def _panel_header() -> rx.Component:
    return rx.heading("Menciones recibidas", size="3", as_="h2")


def mention_sentiment_badge(mention: MentionRow) -> rx.Component:
    """Positiva / Neutra / Negativa / Pendiente are sentiments. A mention with no text, or
    one the model could not read, has NONE: it reads "Sin análisis" in plain muted text,
    outside the sentiment vocabulary, with the reason on hover (founder review)."""
    return rx.match(
        mention.sentiment_state,
        ("POS", signal_pill("Positiva", "ok")),
        ("NEU", signal_pill("Neutra", "neutral")),
        ("NEG", signal_pill("Negativa", "error")),
        ("PENDING", signal_pill("Pendiente", "info")),
        (
            "NO_TEXT",
            rx.tooltip(
                _muted("Sin análisis", cursor="help", white_space="nowrap"),
                content="La mención no tiene texto que analizar.",
            ),
        ),
        (
            "ERROR",
            rx.tooltip(
                _muted("Sin análisis", cursor="help", white_space="nowrap"),
                content="No se pudo analizar el sentimiento de esta mención.",
            ),
        ),
        _muted("—"),
    )


def _date_cell(mention: MentionRow) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.text(mention.day, size="2", class_name="q-nums", white_space="nowrap"),
            rx.cond(
                mention.time != "",
                rx.text(mention.time, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            ),
            spacing="0",
        ),
        spacing="2",
        align="center",
    )


def _link_cell(mention: MentionRow) -> rx.Component:
    return rx.cond(
        mention.permalink != "",
        rx.link(
            rx.hstack(
                rx.text("Ver", size="2", weight="medium"),
                rx.icon("arrow-up-right", size=T.ICON_SM),
                spacing="1",
                align="center",
            ),
            href=mention.permalink,
            is_external=True,
            aria_label="Ver la mención en su red social",
            white_space="nowrap",
            underline="hover",
        ),
        rx.tooltip(_muted("—", cursor="help"), content=_NO_LINK_NOTE),
    )


def _author_cell(mention: MentionRow) -> rx.Component:
    return rx.cond(
        mention.author_note == "",
        mono(mention.author),
        rx.tooltip(
            _muted(mention.author, white_space="nowrap", cursor="help"),
            content=mention.author_note,
        ),
    )


def _text_cell(mention: MentionRow) -> rx.Component:
    """Truncated in the row; on hover, the whole mention in the system's glass overlay
    with an accent wash and glow (founder review 2026-10-13)."""
    return rx.hover_card.root(
        rx.hover_card.trigger(
            rx.text(
                mention.text,
                size="2",
                color=rx.cond(mention.text_unavailable, T.TEXT_MUTED, "inherit"),
                width=_MENTION_COL_WIDTH,
                max_width=_MENTION_COL_WIDTH,
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
                cursor="default",
            ),
        ),
        rx.hover_card.content(
            rx.vstack(
                rx.hstack(
                    rx.cond(
                        mention.author_note == "",
                        mono(mention.author, size="1"),
                        rx.text(mention.author, size="1", color=T.TEXT_MUTED),
                    ),
                    rx.text("·", size="1", color=T.TEXT_FAINT),
                    rx.text(mention.kind_label, size="1", color=T.TEXT_MUTED),
                    rx.text("·", size="1", color=T.TEXT_FAINT),
                    rx.text(mention.date, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                    spacing="1",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(mention.text, size="2", white_space="pre-wrap", line_height="1.55"),
                spacing="2",
                align_items="start",
            ),
            max_width="440px",
            side="top",
            align="start",
            class_name="q-mention-peek",
        ),
        open_delay=200,
        close_delay=80,
    )


def _likes_cell(mention: MentionRow) -> rx.Component:
    return rx.cond(
        mention.likes_note == "",
        rx.text(mention.likes, size="2", class_name="q-nums"),
        rx.tooltip(_muted(mention.likes, cursor="help"), content=mention.likes_note),
    )


def mention_row(mention: MentionRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(_date_cell(mention)),
        rx.table.cell(platform_badge(mention.platform)),
        rx.table.cell(tag(mention.kind_label)),
        rx.table.cell(_link_cell(mention)),
        rx.table.cell(_author_cell(mention), white_space="nowrap"),
        rx.table.cell(_text_cell(mention), padding_right=_MENTION_GUTTER),
        rx.table.cell(mention_sentiment_badge(mention)),
        rx.table.cell(_likes_cell(mention), text_align="right"),
        align="center",
    )


def mention_card(mention: MentionRow) -> rx.Component:
    """One mention below 1280 px: who/when/where on top, the text (up to three lines), then
    likes and the link — the same fields as a table row, nothing hidden behind a hover."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.hstack(
                    rx.text(mention.date, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                    platform_badge(mention.platform),
                    tag(mention.kind_label),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.spacer(),
                mention_sentiment_badge(mention),
                width="100%",
                align="start",
                spacing="2",
            ),
            _author_cell(mention),
            rx.text(
                mention.text,
                size="2",
                color=rx.cond(mention.text_unavailable, T.TEXT_MUTED, "inherit"),
                class_name="q-clamp-3",
            ),
            rx.hstack(
                rx.hstack(
                    rx.icon("heart", size=T.ICON_SM, color=T.TEXT_MUTED),
                    _likes_cell(mention),
                    spacing="1",
                    align="center",
                ),
                rx.spacer(),
                _link_cell(mention),
                width="100%",
                align="center",
            ),
            spacing="2",
            width="100%",
        ),
        padding="0.875rem 0.25rem",
        border_bottom=T.BORDER,
        width="100%",
    )


def mentions_cards() -> rx.Component:
    # The responsive class lives on a plain box: a Radix Flex (`vstack`) owns its own
    # `display` and would fight the rule.
    return rx.box(
        rx.vstack(
            rx.foreach(DashboardState.mentions, mention_card),
            spacing="0",
            width="100%",
        ),
        width="100%",
        class_name=_CARDS_ONLY,
    )


def mentions_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Fecha"),
                    rx.table.column_header_cell("Canal"),
                    rx.table.column_header_cell("Origen"),
                    rx.table.column_header_cell("Enlace"),
                    rx.table.column_header_cell("Autor"),
                    rx.table.column_header_cell(
                        "Mención", min_width=_MENTION_COL_WIDTH, padding_right=_MENTION_GUTTER
                    ),
                    rx.table.column_header_cell("Sentimiento"),
                    rx.table.column_header_cell("Likes", text_align="right"),
                )
            ),
            rx.table.body(
                rx.foreach(DashboardState.mentions, mention_row),
            ),
            variant="ghost",
            width="100%",
        ),
        overflow_x="auto",
        width="100%",
        class_name=_TABLE_ONLY,
    )


def _page_button(item: rx.Var[str]) -> rx.Component:
    is_current = item == DashboardState.page.to_string()
    return rx.button(
        item,
        size="1",
        radius="full",
        variant=rx.cond(is_current, "solid", "ghost"),
        color_scheme=T.tone_scale("neutral"),
        high_contrast=True,
        min_width="1.75rem",
        class_name="q-nums",
        on_click=DashboardState.go_to_page(item),
        aria_label="Página " + item,
    )


def _arrow(
    icon: str, label: str, disabled: rx.Var[bool], on_click: rx.EventHandler
) -> rx.Component:
    return rx.icon_button(
        rx.icon(icon, size=T.ICON_SM),
        size="1",
        variant="ghost",
        color_scheme=T.tone_scale("neutral"),
        disabled=disabled,
        on_click=on_click,
        aria_label=label,
    )


def pager() -> rx.Component:
    """Compact pager (founder's reference, 2026-10-13): the page count on the left; on the
    right the arrows and up to ten page numbers, the current one filled. With the cards the
    numbers give way to "‹ Página n de N ›" (below 1280 px)."""
    prev = _arrow(
        "chevron-left", "Página anterior", ~DashboardState.has_prev, DashboardState.prev_page
    )
    nxt = _arrow(
        "chevron-right", "Página siguiente", ~DashboardState.has_next, DashboardState.next_page
    )
    return rx.box(
        rx.box(
            rx.hstack(
                rx.text(DashboardState.pages_label, size="1", color=T.TEXT_MUTED),
                rx.spacer(),
                rx.hstack(
                    prev,
                    rx.foreach(DashboardState.page_items, _page_button),
                    nxt,
                    spacing="2",
                    align="center",
                ),
                width="100%",
                align="center",
            ),
            class_name=_TABLE_ONLY,
        ),
        rx.box(
            rx.hstack(
                _arrow(
                    "chevron-left",
                    "Página anterior",
                    ~DashboardState.has_prev,
                    DashboardState.prev_page,
                ),
                rx.text(
                    "Página ",
                    DashboardState.page.to_string(),
                    " de ",
                    DashboardState.total_pages.to_string(),
                    size="2",
                    color=T.TEXT_MUTED,
                    class_name="q-nums",
                ),
                _arrow(
                    "chevron-right",
                    "Página siguiente",
                    ~DashboardState.has_next,
                    DashboardState.next_page,
                ),
                justify="center",
                align="center",
                spacing="3",
                width="100%",
            ),
            class_name=_CARDS_ONLY,
        ),
        width="100%",
    )


# --- refresh outcomes and states -------------------------------------------------------


def notices() -> rx.Component:
    """The refresh outcomes. None of them changes the rows on screen by itself. A new
    mention has no notice here: it simply appears in the list (QUA-152) — it is not a
    message and is never announced as one."""
    return rx.vstack(
        rx.cond(
            DashboardState.list_changed,
            rx.hstack(
                callout("La lista cambió desde la última carga.", "warn", flex="1"),
                rx.button(
                    "Actualizar",
                    size="2",
                    variant="soft",
                    on_click=DashboardState.go_to_page("1"),
                ),
                align="center",
                spacing="3",
                width="100%",
            ),
        ),
        rx.cond(
            DashboardState.refresh_error != "",
            callout(DashboardState.refresh_error, "warn"),
        ),
        rx.cond(
            DashboardState.refresh_notice != "",
            callout(DashboardState.refresh_notice, "warn"),
        ),
        spacing="2",
        width="100%",
    )


def _mentions_load_error() -> rx.Component:
    return callout(DashboardState.mentions_error, "error")


def _mentions_empty_state() -> rx.Component:
    return rx.cond(
        DashboardState.is_windowed,
        empty_state(
            "at-sign",
            "No hay menciones en este periodo",
            "Cuando alguien mencione tu cuenta en una publicación o un "
            "comentario, aparecerá aquí. Para ver menciones anteriores, elige un periodo "
            "más amplio.",
        ),
        empty_state(
            "at-sign",
            "Aún no hay menciones",
            "Cuando alguien mencione tu cuenta en una publicación o un comentario, aparecerá aquí.",
        ),
    )


def _no_results_state() -> rx.Component:
    return empty_state(
        "search-x",
        "Ninguna mención coincide con estos filtros",
        "Cambia o quita algún filtro para ver más menciones.",
    )


def mentions_body() -> rx.Component:
    """Notices above a single panel: its header (title + refresh), then loading → error →
    empty → no results → table + pager, never overlapping. The skeleton shows only when
    the screen opens; filtering, paging and refreshing keep the rows on screen."""
    return rx.vstack(
        _refresh_timer(),
        notices(),
        card(
            rx.vstack(
                _panel_header(),
                rx.cond(
                    DashboardState.is_loading_mentions,
                    skeleton_rows(rows=4, height="2.75rem"),
                    rx.cond(
                        DashboardState.mentions_error != "",
                        _mentions_load_error(),
                        rx.cond(
                            DashboardState.show_empty_state,
                            _mentions_empty_state(),
                            rx.cond(
                                DashboardState.show_no_results,
                                _no_results_state(),
                                rx.vstack(
                                    mentions_table(),
                                    mentions_cards(),
                                    # No separator: the last row (or card) already draws
                                    # the one line above the pager.
                                    pager(),
                                    spacing="3",
                                    width="100%",
                                ),
                            ),
                        ),
                    ),
                ),
                spacing="3",
                width="100%",
            ),
            padding="1rem 1.25rem",
        ),
        spacing="3",
        width="100%",
    )
