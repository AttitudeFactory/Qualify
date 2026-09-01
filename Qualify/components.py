"""Mentions dashboard blocks + backwards-compatible re-exports.

The shell pieces (``sidebar``, ``session_badge``) now live in ``Qualify/ui/layout.py``
and are re-exported here so older imports keep working; new code should import from
``.ui`` directly. What remains in this module is specific to the mentions dashboard.
"""

import reflex as rx

from .state import DashboardState, MentionRow
from .ui import (
    callout,
    empty_state,
    page_header,
    platform_badge,
    sentiment_badge,
    session_badge,
    sidebar,
    skeleton_rows,
    stat_card,
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


def topbar() -> rx.Component:
    # QUA-97 audit (2026-09-01): the previous subtitle ("Menciones de marca en TikTok e
    # Instagram Reels") was leftover copy from the pre-QUA-97 synthetic/seed dashboard,
    # which modeled multi-brand competitive listening including TikTok. It overstated
    # real coverage on two axes at once — TikTok mentions are structurally unavailable
    # (fase0-zernio-mercado.md §4.1), and even on Instagram this covers only caption and
    # comment @mentions, not Stories/tags. Say exactly what v1 covers, nothing more.
    return page_header(
        "Dashboard de menciones",
        "Instagram — menciones en captions y comentarios de la cuenta conectada "
        "(no incluye Stories, etiquetados, Facebook, Threads ni TikTok)",
    )


def stats_row() -> rx.Component:
    return rx.grid(
        stat_card("Total menciones", DashboardState.total_mentions, "accent"),
        stat_card("Positivas", DashboardState.positive_count, "ok"),
        stat_card("Neutras", DashboardState.neutral_count, "neutral"),
        stat_card("Negativas", DashboardState.negative_count, "error"),
        columns=rx.breakpoints(initial="2", md="4"),
        spacing="3",
        width="100%",
    )


def filter_bar() -> rx.Component:
    return rx.hstack(
        rx.select(
            DashboardState.brand_options,
            value=DashboardState.brand_filter,
            on_change=DashboardState.set_brand_filter,
            size="2",
        ),
        rx.select(
            DashboardState.platform_options,
            value=DashboardState.platform_filter,
            on_change=DashboardState.set_platform_filter,
            size="2",
        ),
        rx.select(
            ["Todos", "POS", "NEU", "NEG"],
            value=DashboardState.sentiment_filter,
            on_change=DashboardState.set_sentiment_filter,
            size="2",
        ),
        rx.input(
            rx.input.slot(rx.icon("search", size=T.ICON_SM)),
            placeholder="Buscar por caption o creador",
            value=DashboardState.search_query,
            on_change=DashboardState.set_search_query,
            size="2",
            width="260px",
        ),
        spacing="3",
        wrap="wrap",
        width="100%",
    )


def mention_row(mention: MentionRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(mention.posted_at, white_space="nowrap", class_name="q-nums"),
        rx.table.cell(platform_badge(mention.platform)),
        rx.table.cell(mention.brand),
        rx.table.cell(rx.text(mention.creator_handle, size="2", class_name="q-mono")),
        rx.table.cell(
            mention.caption,
            max_width="360px",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        rx.table.cell(sentiment_badge(mention.sentiment)),
        rx.table.cell(mention.views, text_align="right", class_name="q-nums"),
        rx.table.cell(mention.likes, text_align="right", class_name="q-nums"),
    )


def mentions_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Fecha"),
                    rx.table.column_header_cell("Plataforma"),
                    rx.table.column_header_cell("Marca"),
                    rx.table.column_header_cell("Creador"),
                    rx.table.column_header_cell("Caption"),
                    rx.table.column_header_cell("Sentimiento"),
                    rx.table.column_header_cell("Vistas", text_align="right"),
                    rx.table.column_header_cell("Likes", text_align="right"),
                )
            ),
            rx.table.body(
                rx.foreach(DashboardState.filtered_mentions, mention_row),
            ),
            variant="surface",
            width="100%",
        ),
        overflow_x="auto",
        width="100%",
    )


def _mentions_load_error() -> rx.Component:
    return callout(DashboardState.mentions_error, "error")


def _mentions_empty_state() -> rx.Component:
    return empty_state(
        "at-sign",
        "Aún no hay menciones",
        "En cuanto alguien mencione a tu cuenta de Instagram conectada en un caption o "
        "un comentario, aparecerá acá.",
    )


def mentions_body() -> rx.Component:
    """Loading → error → empty → table, same `rx.cond` composition `inbox_page.py`
    establishes for its own screen (`is_loading` / `*_error` / `show_empty_state`,
    never silently overlapping). Distinct from `mentions_table()` (kept as the raw table
    for whatever still renders it directly) so this module has exactly one place that
    decides what the user sees before any real mention has ever arrived — which, until
    Meta Business Verification unblocks Advanced Access, is the state production is in
    today (QUA-97 §B)."""
    return rx.cond(
        DashboardState.is_loading_mentions,
        skeleton_rows(rows=4, height="2.75rem"),
        rx.cond(
            DashboardState.mentions_error != "",
            _mentions_load_error(),
            rx.cond(
                DashboardState.show_empty_state,
                _mentions_empty_state(),
                mentions_table(),
            ),
        ),
    )
