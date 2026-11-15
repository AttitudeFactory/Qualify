"""«Ajustes de chats» (m-25017861, decision D1): what the owner prepares once, apart from
the messages. One screen, three cards, no tabs (mockup part F): «Para todos tus chats»,
«WhatsApp», «Instagram». Every row opens the screen that already exists; an Instagram
account's «Preguntas iniciales» open in their drawer right here.

Routes: `/chats/ajustes` and `/chats/ajustes/instagram` (the same hub, with an account's
«Preguntas iniciales» open — the Instagram chat's «Ajustes de este canal»). The WhatsApp
menu has its own page, `/chats/ajustes/whatsapp` (`whatsapp_page.whatsapp_settings_index`).

Design system only: `page_header` / `page_body` / `section` / `card`, rows of Radix
links and ghost buttons with the 44 px target, loading as a skeleton, failure as a
`callout` with the next step. The page reads `ChatSettingsState` (and opens the drawer
of `IceBreakersState`).
"""

from __future__ import annotations

import reflex as rx

from .chat_settings_state import ChatSettingsState
from .chat_settings_vm import (
    ALL_CHATS_ROWS,
    ALL_CHATS_TITLE,
    BACK_TO_CHATS,
    CHAT_SETTINGS_SUBTITLE,
    CHATS_HREF,
    CONNECTIONS_ACTION,
    CONNECTIONS_HREF,
    CONNECTIONS_NOTE,
    INSTAGRAM_TITLE,
    NO_INSTAGRAM,
    NO_INSTAGRAM_ACTION,
    NO_WHATSAPP,
    NO_WHATSAPP_ACTION,
    NO_WHATSAPP_HREF,
    RETRY,
    WHATSAPP_ROWS,
    WHATSAPP_TITLE,
    InstagramRowVM,
    SettingRowVM,
)
from .ice_breakers_panel import ice_breakers_panel
from .ice_breakers_state import IceBreakersState
from .ui import app_shell, callout, card, page_body, page_header, section, skeleton_rows
from .ui import tokens as T

S = ChatSettingsState

#: The phone's touch target (N12); the rows are the page's only controls.
_ROW_MIN = "56px"


def _row_body(icon: str, title: str | rx.Var, detail: str | rx.Var) -> rx.Component:
    return rx.hstack(
        rx.icon(icon, size=T.ICON_MD, color=T.TEXT_MUTED, flex_shrink="0"),
        rx.vstack(
            rx.text(title, size="3", weight="medium", color=T.TEXT_STRONG),
            rx.text(detail, size="2", weight="regular", color=T.TEXT_MUTED, text_align="left"),
            spacing="0",
            align_items="start",
            min_width="0",
            flex="1",
        ),
        rx.icon("chevron-right", size=T.ICON_SM, color=T.TEXT_MUTED, flex_shrink="0"),
        spacing="3",
        align="center",
        width="100%",
    )


def _link_row(row: SettingRowVM) -> rx.Component:
    """A row that opens the screen where the thing is set up (a real link: it can be
    opened in a new tab and the screen reader says «enlace»)."""
    return rx.link(
        _row_body(row.icon, row.title, row.detail),
        href=row.href,
        underline="none",
        display="flex",
        align_items="center",
        min_height=_ROW_MIN,
        padding_y="0.5rem",
        width="100%",
        custom_attrs={"data-setting": row.key},
    )


def _rows(*rows: rx.Component) -> rx.Component:
    return card(
        rx.vstack(*rows, spacing="1", width="100%"),
        padding="0.5rem 1rem",
        width="100%",
    )


def _instagram_row(row: InstagramRowVM) -> rx.Component:
    """«Preguntas iniciales» of one account: opens their drawer on this page."""
    return rx.button(
        _row_body("message-circle-question", row.title, row.detail),
        on_click=IceBreakersState.open_panel(row.connection_id),
        variant="ghost",
        width="100%",
        height="auto",
        min_height=_ROW_MIN,
        # the ghost button's negative margin would pull it out of line with the links
        margin="0",
        padding_x="0",
        padding_y="0.5rem",
        justify_content="start",
        type="button",
        **T.tone_scheme("neutral"),
    )


def _plain_line(text: str, action: str, href: str) -> rx.Component:
    """No account of a channel: what is missing and the one link that fixes it (N8)."""
    return rx.vstack(
        rx.text(text, size="2", color=T.TEXT_MUTED),
        rx.link(action, href=href, size="2", weight="medium"),
        spacing="1",
        padding_y="0.75rem",
        width="100%",
    )


def _whatsapp_card() -> rx.Component:
    return section(
        WHATSAPP_TITLE,
        rx.cond(
            S.has_whatsapp,
            _rows(*[_link_row(row) for row in WHATSAPP_ROWS]),
            _rows(_plain_line(NO_WHATSAPP, NO_WHATSAPP_ACTION, NO_WHATSAPP_HREF)),
        ),
    )


def _instagram_card() -> rx.Component:
    return section(
        INSTAGRAM_TITLE,
        rx.cond(
            S.has_instagram,
            _rows(rx.foreach(S.instagram, _instagram_row)),
            _rows(_plain_line(NO_INSTAGRAM, NO_INSTAGRAM_ACTION, CONNECTIONS_HREF)),
        ),
    )


def _channels() -> rx.Component:
    """The two channel cards: a skeleton while loading, the error with its retry."""
    return rx.cond(
        S.load_error != "",
        rx.vstack(
            callout(S.load_error, "error"),
            rx.button(
                RETRY,
                on_click=ChatSettingsState.load,
                variant="soft",
                size="2",
                min_height="44px",
                type="button",
            ),
            spacing="3",
            width="100%",
        ),
        rx.cond(
            S.loaded,
            rx.vstack(_whatsapp_card(), _instagram_card(), spacing="5", width="100%"),
            skeleton_rows(4, height="3.5rem"),
        ),
    )


def _back_to_chats() -> rx.Component:
    """N7: the way back to the chats, the place this one hangs from."""
    return rx.link(
        rx.hstack(
            rx.icon("chevron-left", size=T.ICON_SM),
            rx.text(BACK_TO_CHATS, size="2"),
            spacing="1",
            align="center",
        ),
        href=CHATS_HREF,
        underline="none",
        color=T.TEXT_MUTED,
    )


def chat_settings_index() -> rx.Component:
    """`/chats/ajustes` and `/chats/ajustes/instagram`."""
    return app_shell(
        # The menu's own word (N1); `test_nav_one_name` reads it here, as a literal.
        page_header("Ajustes de chats", CHAT_SETTINGS_SUBTITLE, kicker=_back_to_chats()),
        page_body(
            rx.vstack(
                section(ALL_CHATS_TITLE, _rows(*[_link_row(row) for row in ALL_CHATS_ROWS])),
                _channels(),
                rx.text(
                    CONNECTIONS_NOTE + " ",
                    rx.link(CONNECTIONS_ACTION, href=CONNECTIONS_HREF),
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="5",
                width="100%",
                max_width="720px",
            ),
            ice_breakers_panel(),
        ),
    )


__all__ = ["chat_settings_index"]
