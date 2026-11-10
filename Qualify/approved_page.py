"""«Aprobados» (`/aprobados`, m-24986801, docs/ux-aprobados-y-menus.md §3): what the owner
already approved, ready to go out — publications (Le falta algo first, then the most
recently approved) and the season's stickers and videos, one «Tipo» filter each.

Views only: the publications come from `GalleryState` (the same read as «Por aprobar», no
second one), the stickers and videos from `SeasonalState`. Every card is «Por aprobar»'s
own (`creative_pages._gallery_card`, `seasonal_ui`); nothing new is drawn here.
"""

from __future__ import annotations

import reflex as rx

from .creative_pages import _gallery_card, _gallery_reject_dialog, list_panel, list_tabs
from .gallery_state import GalleryState
from .planner_vm import GALLERY_FILTER_ALL, VIEW_POSTS, VIEW_STICKERS
from .seasonal_state import SeasonalState
from .seasonal_ui import approved_section
from .ui import app_shell, callout, empty_state, page_body, page_header, skeleton_rows
from .ui import tokens as T

KIND_LABEL = "Tipo"
ALL_KINDS = "Todos los tipos"
EMPTY_TITLE = "Todavía no apruebas ninguna publicación"
EMPTY_TEXT = "Cuando apruebes una, aparece aquí lista para elegir día y hora."
EMPTY_ACTION = "Ver lo que espera tu aprobación"
FILTER_EMPTY_TITLE = "Nada de ese tipo todavía"
FILTER_EMPTY_ACTION = "Ver todos"
RETRY = "Reintentar"

_KIND_ID = "approved-posts-kind"
_TAP = "44px"


def _kind_filter() -> rx.Component:
    """«Tipo» with its label in sight: the creation types that exist and have something
    approved (never an invented category). An old `?estado=listo|usado` shows as a chip
    that can be taken off."""
    return rx.flex(
        rx.el.label(
            rx.text(KIND_LABEL, size="2", weight="medium", as_="span"),
            html_for=_KIND_ID,
        ),
        rx.select.root(
            rx.select.trigger(id=_KIND_ID, min_height=_TAP, min_width="12rem"),
            rx.select.content(
                rx.select.item(ALL_KINDS, value=GALLERY_FILTER_ALL),
                rx.foreach(
                    GalleryState.approved_kind_options,
                    lambda option: rx.select.item(option.label, value=option.value),
                ),
            ),
            value=GalleryState.approved_kind_filter,
            on_change=GalleryState.set_approved_kind_filter,
            size="2",
        ),
        rx.cond(
            GalleryState.approved_state_label != "",
            rx.button(
                GalleryState.approved_state_label,
                rx.icon("x", size=14),
                size="1",
                variant="soft",
                radius="full",
                on_click=GalleryState.clear_approved_filters,
                aria_label="Quitar el filtro " + GalleryState.approved_state_label,
                class_name="q-gfilter",
            ),
        ),
        gap="0.5rem",
        align="center",
        wrap="wrap",
    )


def _empty() -> rx.Component:
    return rx.cond(
        GalleryState.approved_is_filtered,
        empty_state(
            "filter",
            FILTER_EMPTY_TITLE,
            "",
            action=rx.button(
                FILTER_EMPTY_ACTION,
                variant="soft",
                size="2",
                on_click=GalleryState.clear_approved_filters,
            ),
        ),
        empty_state(
            "list-checks",
            EMPTY_TITLE,
            EMPTY_TEXT,
            action=rx.link(rx.button(EMPTY_ACTION, size="3"), href="/drafts"),
        ),
    )


def _approved_card(post) -> rx.Component:
    return _gallery_card(post, approved=True)


def _posts() -> rx.Component:
    return list_panel(
        VIEW_POSTS,
        rx.cond(
            GalleryState.error != "",
            rx.vstack(
                callout(GalleryState.error, "error"),
                rx.button(
                    rx.icon("refresh-cw", size=15),
                    RETRY,
                    variant="soft",
                    size="2",
                    min_height=_TAP,
                    on_click=GalleryState.reload,
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            GalleryState.approved_count > 0,
            _kind_filter(),
        ),
        rx.cond(
            GalleryState.loading,
            rx.box(
                *[skeleton_rows(1, height="7rem", radius=T.RADIUS_CARD) for _ in range(6)],
                class_name="q-gallery",
            ),
            rx.cond(
                GalleryState.error != "",
                rx.fragment(),
                rx.cond(
                    GalleryState.approved_visible_count > 0,
                    rx.vstack(
                        rx.text(GalleryState.approved_count_line, size="1", color=T.TEXT_MUTED),
                        rx.box(
                            rx.foreach(GalleryState.approved_visible, _approved_card),
                            class_name="q-gallery q-gallery--cards",
                        ),
                        spacing="2",
                        width="100%",
                        align_items="start",
                    ),
                    _empty(),
                ),
            ),
        ),
    )


def approved_index() -> rx.Component:
    return app_shell(
        page_header(
            "Aprobados", "Lo que ya aprobaste, listo para programar o mandar por WhatsApp."
        ),
        page_body(
            list_tabs(GalleryState.approved_tab_label, SeasonalState.approved_tab_label),
            _posts(),
            list_panel(VIEW_STICKERS, approved_section()),
            _gallery_reject_dialog(),
        ),
    )
