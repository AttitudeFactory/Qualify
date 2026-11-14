"""The chat row both lists draw (m-25017844, BU-A2) — WhatsApp → Chats and Conversaciones.

A composition of design-system pieces (Radix avatar, `media_thumb`'s person icon,
`signal_pill`, `tag`, the card material with its lift), not a new component: the view
model (`chat_row_vm.ChatRowVM`) has already chosen the one pill, taken the initials and
worded the accessible name; this only draws.

Anatomy: picture or initial with the channel's glyph on its corner · the breathing dot
while the customer waits · name (bold while waiting), who attends it (with a team) and
time on one line · preview with its media icon · the one pill. A closed chat (in a
list that mixes open and closed) has its name and preview in the muted token, and
«cerrado» in its accessible name.
Channel identity = glyph + the platform scale (`T.PLATFORM_SCALE`, painted by
`.q-chat-channel--{channel}` in `assets/qualify-inbox.css`). The dot and the pulse of a
fresh row stop under `prefers-reduced-motion` (the same sheet).

Keyboard: the row is `role="button"` with `tabindex=0`; Enter and Space on the row itself
call the element's own `click()` — the same `on_click` event, no global listener, no
extra state handler — and Space does not scroll the page.
"""

from __future__ import annotations

import reflex as rx
from reflex.vars.base import Var

from .chat_row_vm import CHANNEL_INSTAGRAM, CHANNEL_WHATSAPP, ChatRowVM
from .ui import media_thumb, signal_pill, tag
from .ui import tokens as T

_TONES = ("ok", "warn", "error", "info", "neutral")
#: N12: the row is one tap target of at least 44 px.
_TAP_MIN = "2.75rem"
#: The Radix avatar size "4" (40 px), for the person icon in the same frame.
_AVATAR_SIZE = "2.5rem"

#: Enter / Space activate the focused row like a native button (only when the row itself
#: has focus, so a key pressed inside a future control in the row is left alone).
ROW_KEY_HANDLER: Var = Var(
    _js_expr=(
        "((e) => { if (e.target === e.currentTarget && !e.repeat && "
        "(e.key === 'Enter' || e.key === ' ')) "
        "{ e.preventDefault(); e.currentTarget.click(); } })"
    )
)


def tone_pill(label: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """`signal_pill` for a tone that is data (the VM ships it): matched at build time."""
    return rx.match(
        tone,
        *[(t, signal_pill(label, t)) for t in _TONES[:-1]],
        signal_pill(label, "neutral"),
    )


def instagram_glyph(color: str | None = None) -> rx.Component:
    """Instagram's mark, inline (Lucide carries no brand icons): a rounded square, the
    lens and the flash dot, in the current colour (or `color`)."""
    extra = {"color": color} if color else {}
    return rx.el.svg(
        rx.el.svg.rect(x="2", y="2", width="20", height="20", rx="5", ry="5"),
        rx.el.svg.circle(cx="12", cy="12", r="4"),
        rx.el.svg.circle(cx="17.5", cy="6.5", r="1.2", fill="currentColor"),
        view_box="0 0 24 24",
        width="10",
        height="10",
        fill="none",
        stroke="currentColor",
        stroke_width="2.2",
        stroke_linecap="round",
        stroke_linejoin="round",
        aria_hidden="true",
        **extra,
    )


def _channel_mark(channel: rx.Var[str]) -> rx.Component:
    """The glyph on the avatar's corner, on the channel's own scale (WhatsApp's is the
    `message-circle` the menu already uses for it)."""
    return rx.match(
        channel,
        (
            CHANNEL_WHATSAPP,
            rx.box(
                rx.icon("message-circle", size=10, stroke_width=2.6, aria_hidden="true"),
                class_name="q-conv-channel q-chat-channel--whatsapp",
            ),
        ),
        (
            CHANNEL_INSTAGRAM,
            rx.box(instagram_glyph(), class_name="q-conv-channel q-chat-channel--instagram"),
        ),
        rx.fragment(),
    )


def _person_icon() -> rx.Component:
    """The person icon in the avatar's frame (`media_thumb` with no picture)."""
    return media_thumb("", size=_AVATAR_SIZE, round=True, icon="user-round", icon_size=18)


def _picture(row: ChatRowVM, fallback: rx.Var[str] | str) -> rx.Component:
    """The Radix avatar: the picture, and `fallback` when it fails (an expired URL)."""
    return rx.avatar(
        src=row.avatar_url,
        fallback=fallback,
        radius="full",
        size="4",
        custom_attrs={"referrerpolicy": "no-referrer"},
    )


def _avatar(row: ChatRowVM) -> rx.Component:
    """The picture, else the initials, else (no letter to show) the person icon. With a
    picture but no letters, the Radix avatar sits over the icon with an empty, clear
    fallback (`.q-chat-avatar__over`): a picture that fails to load reveals the icon,
    never a broken image."""
    return rx.box(
        rx.cond(
            row.initials != "",
            _picture(row, row.initials),
            rx.cond(
                row.avatar_url != "",
                rx.box(
                    _person_icon(),
                    rx.box(_picture(row, ""), class_name="q-chat-avatar__over"),
                    position="relative",
                ),
                _person_icon(),
            ),
        ),
        _channel_mark(row.channel),
        rx.cond(row.waiting, rx.box(class_name="q-conv-unread"), rx.fragment()),
        class_name="q-conv-avatar-wrap q-conv-avatar-wrap--md q-chat-avatar",
        aria_hidden="true",
        position="relative",
        flex_shrink="0",
    )


def _pill(row: ChatRowVM) -> rx.Component:
    return rx.cond(row.pill_label != "", tone_pill(row.pill_label, row.pill_tone), rx.fragment())


def _agent_chip(row: ChatRowVM) -> rx.Component:
    return rx.cond(
        row.agent_initials != "",
        rx.tooltip(
            tag(row.agent_initials),
            content=rx.cond(row.agent_name != "", row.agent_name, "Asignado"),
        ),
        rx.fragment(),
    )


def chat_row(row: ChatRowVM, *, is_open: rx.Var[bool], on_open: rx.event.EventSpec) -> rx.Component:
    """One chat in a list. `is_open` marks the chat on screen; `on_open` opens it (by
    click, tap, Enter or Space)."""
    return rx.box(
        rx.hstack(
            _avatar(row),
            rx.vstack(
                rx.hstack(
                    rx.text(
                        row.title,
                        size="3",
                        weight=rx.cond(row.waiting, "bold", "medium"),
                        color=rx.cond(row.closed, T.TEXT_MUTED, T.TEXT_STRONG),
                        class_name="q-wa-ellipsis",
                        flex="1",
                        min_width="0",
                    ),
                    # m-25017859: who attends it sits on the name line, so a WhatsApp row
                    # with a team is as tall as an Instagram row (no line of its own).
                    _agent_chip(row),
                    rx.text(
                        row.time_label,
                        size="1",
                        color=T.TEXT_MUTED,
                        white_space="nowrap",
                        class_name="q-nums",
                    ),
                    width="100%",
                    align="center",
                    spacing="2",
                ),
                rx.hstack(
                    rx.cond(
                        row.preview_icon != "",
                        rx.icon(row.preview_icon, size=T.ICON_SM, color=T.TEXT_MUTED),
                        rx.fragment(),
                    ),
                    rx.text(
                        row.preview,
                        size="2",
                        color=rx.cond(row.waiting & ~row.closed, T.TEXT_STRONG, T.TEXT_MUTED),
                        class_name="q-wa-ellipsis",
                        flex="1",
                        min_width="0",
                    ),
                    width="100%",
                    align="center",
                    spacing="1",
                ),
                # ONE line of labels at most, and only for the pill the VM picked: the
                # same third line on both channels.
                rx.cond(
                    row.pill_label != "",
                    rx.hstack(_pill(row), width="100%", align="center", spacing="1"),
                    rx.fragment(),
                ),
                spacing="1",
                width="100%",
                min_width="0",
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        on_click=on_open,
        class_name=rx.cond(
            is_open,
            rx.cond(
                row.fresh,
                "q-card q-lift q-wa-row q-conv-row q-wa-row--active q-conv-row--fresh",
                "q-card q-lift q-wa-row q-conv-row q-wa-row--active",
            ),
            rx.cond(
                row.fresh,
                "q-card q-lift q-wa-row q-conv-row q-conv-row--fresh",
                "q-card q-lift q-wa-row q-conv-row",
            ),
        ),
        role="button",
        tab_index=0,
        aria_label=row.aria_label,
        custom_attrs={
            "aria-current": rx.cond(is_open, "true", "false"),
            "onKeyDown": ROW_KEY_HANDLER,
        },
        cursor="pointer",
        min_height=_TAP_MIN,
        width="100%",
    )
