"""«Tu local en el mapa» under «Dirección» in Tu número › Perfil (m-24945889 §3): two
ways to put the point without typing numbers, then «Ver en el mapa» / «Quitar del
mapa». No map is drawn on the screen (that would be a new provider)."""

from __future__ import annotations

import reflex as rx

from .ui import callout, skeleton_rows, tone_badge
from .ui import tokens as T
from .whatsapp_location_state import WhatsAppLocationState
from .whatsapp_location_vm import (
    BACK_TO_CHAT,
    GEO_EXPLAIN,
    GEO_WAITING,
    LINK_HELP,
    LINK_LABEL,
    LINK_PLACEHOLDER,
    LINK_READING,
    LINK_SAVE,
    MAP_HELP,
    MAP_TITLE,
    NOT_ON_MAP,
    REMOVE,
    SAVED,
    USE_MY_LOCATION,
    VIEW_ON_MAP,
)

L = WhatsAppLocationState
_TAP = "44px"
_LINK_ID = "wa-map-link"
_LINK_HELP_ID = "wa-map-link-help"


def back_to_chat_link() -> rx.Component:
    """«‹ Volver al chat» when the owner came from «Cómo llegar» (one link, styled as a
    button: screen readers hear it once)."""
    return rx.fragment(
        rx.box(display="none", on_mount=L.read_return),
        rx.cond(
            L.return_to != "",
            rx.button(
                rx.link(
                    rx.icon("chevron-left", size=T.ICON_SM),
                    BACK_TO_CHAT,
                    href=L.return_to,
                    underline="none",
                ),
                as_child=True,
                variant="ghost",
                size="2",
                min_height=_TAP,
                **T.tone_scheme("neutral"),
            ),
        ),
    )


def _on_map() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            tone_badge(SAVED, "ok", icon="map-pin"),
            wrap="wrap",
        ),
        rx.text(L.point_label, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
        rx.flex(
            rx.link(
                rx.button(
                    rx.icon("map", size=T.ICON_SM),
                    VIEW_ON_MAP,
                    variant="soft",
                    size="2",
                    min_height=_TAP,
                    **T.tone_scheme("neutral"),
                ),
                href=L.map_href,
                is_external=True,
            ),
            rx.button(
                rx.icon("trash-2", size=T.ICON_SM),
                REMOVE,
                on_click=L.remove,
                disabled=L.busy,
                variant="ghost",
                size="2",
                min_height=_TAP,
                **T.tone_scheme("neutral"),
            ),
            gap="2",
            wrap="wrap",
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _ways_in() -> rx.Component:
    return rx.vstack(
        rx.text(NOT_ON_MAP, size="2", color=T.TEXT_MUTED),
        rx.button(
            rx.icon("locate-fixed", size=T.ICON_SM),
            rx.cond(L.locating, GEO_WAITING, USE_MY_LOCATION),
            on_click=L.use_my_location,
            disabled=L.busy | L.locating,
            variant="soft",
            size="2",
            min_height=_TAP,
        ),
        rx.text(GEO_EXPLAIN, size="1", color=T.TEXT_MUTED),
        rx.el.label(
            rx.text(LINK_LABEL, size="2", weight="medium"), html_for=_LINK_ID, margin_top="0.5rem"
        ),
        rx.flex(
            rx.input(
                id=_LINK_ID,
                value=L.link_text,
                on_change=L.set_link_text,
                placeholder=LINK_PLACEHOLDER,
                type="url",
                inputmode="url",
                size="2",
                flex="1 1 14rem",
                custom_attrs={"aria-describedby": _LINK_HELP_ID},
            ),
            rx.button(
                rx.cond(L.reading, LINK_READING, LINK_SAVE),
                on_click=L.save_link,
                disabled=L.busy | L.reading | (L.link_text == ""),
                aria_busy=rx.cond(L.reading | L.busy, "true", "false"),
                size="2",
                min_height=_TAP,
            ),
            gap="2",
            wrap="wrap",
            width="100%",
        ),
        rx.text(LINK_HELP, size="1", color=T.TEXT_MUTED, id=_LINK_HELP_ID),
        spacing="2",
        align_items="start",
        width="100%",
    )


def map_point_block() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.icon("map-pin", size=T.ICON_MD, aria_hidden="true"),
            rx.heading(MAP_TITLE, size="3", as_="h3"),
            spacing="2",
            align="center",
        ),
        rx.text(MAP_HELP, size="2", color=T.TEXT_MUTED),
        rx.cond(
            L.loading,
            skeleton_rows(rows=2, height="2.5rem"),
            rx.cond(
                L.load_error != "",
                callout(L.load_error, "error"),
                rx.cond(L.has_point, _on_map(), _ways_in()),
            ),
        ),
        rx.cond(L.error != "", callout(L.error, "warn")),
        spacing="2",
        align_items="start",
        width="100%",
        on_mount=L.ensure_loaded,
    )
