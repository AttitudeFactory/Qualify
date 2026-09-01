"""Mentions dashboard blocks + backwards-compatible re-exports.

The shell pieces (``sidebar``, ``session_badge``) now live in ``Qualify/ui/layout.py``
and are re-exported here so older imports keep working; new code should import from
``.ui`` directly. What remains in this module is specific to the mentions dashboard.
"""

import reflex as rx

from .state import DashboardState, MentionRow
from .ui import (
    page_header,
    platform_badge,
    sentiment_badge,
    session_badge,
    sidebar,
    stat_card,
)
from .ui import tokens as T

__all__ = [
    "filter_bar",
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
    return page_header(
        "Dashboard de menciones",
        "Menciones de marca en TikTok e Instagram Reels",
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
