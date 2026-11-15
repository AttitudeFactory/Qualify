"""The one reply box both chats draw (m-25027374, BU-A7): WhatsApp → Chats and
Conversaciones (Instagram).

A composition of design-system pieces (`orbit_menu`, Radix button / text area,
`callout`), not a new component — the same standing as `chat_thread.py`. Each page keeps
its own state and hands over its channel's events; the box is the same on both:

    [what rides with the reply: a suggestion, an attachment, the buttons being written…]
    [tools, icon AND name: Botones · Mensajes guardados · ❤ · Sugerir respuesta]
    [«+»] [the text, growing with what is written]                         [«Enviar»]
    [one line: what happens when you send, or what to fix]

- What a channel cannot send is not drawn (`reply_box_vm.draws`); the view never asks
  a channel name, only the box's flags.
- «Enviar» is the box's only solid button; everything else is soft or ghost (P3).
- Every control is at least 44 px (N12), with an accessible name.
- The keyboard is as before: Enter writes a new line, «Enviar» sends (nothing sends on
  a key, so a slip of the thumb never sends half a message).
- On a phone the tools row is one line that scrolls sideways instead of wrapping, so
  the box keeps to two short rows (`assets/qualify-inbox.css`, `.q-reply-*`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import reflex as rx

from .chat_thread import TAP_MIN
from .reply_box_vm import (
    FIELD_LABEL,
    FIELD_PLACEHOLDER,
    PLUS_LABEL,
    SEND_LABEL,
    ReplyBoxVM,
    plus_rows,
)
from .ui import OrbitItem, orbit_menu
from .ui import tokens as T


def reply_tool(
    icon: str,
    label: str | rx.Var[str],
    *,
    pressed: rx.Var[bool] | None = None,
    tone: str = "neutral",
    **props: Any,
) -> rx.Component:
    """A tool of the box: its icon AND its name, soft, never the solid action. `pressed`
    for a tool that switches something on in the box (Botones)."""
    extra: dict[str, Any] = {}
    if pressed is not None:
        extra["aria_pressed"] = rx.cond(pressed, "true", "false")
    return rx.button(
        rx.icon(icon, size=T.ICON_SM, aria_hidden="true"),
        label,
        variant="soft",
        size="2",
        type="button",
        min_height=TAP_MIN,
        class_name="q-reply-tool",
        **extra,
        **T.tone_scheme(tone),
        **props,
    )


def reply_icon_tool(icon: str, label: str, *, tone: str = "neutral", **props: Any) -> rx.Component:
    """A tool whose glyph IS its name (the ❤): 44 px, named for the screen reader and
    the tooltip."""
    return rx.tooltip(
        rx.icon_button(
            rx.icon(icon, size=T.ICON_MD, aria_hidden="true"),
            variant="soft",
            size="3",
            type="button",
            aria_label=label,
            min_width=TAP_MIN,
            min_height=TAP_MIN,
            class_name="q-reply-tool",
            **T.tone_scheme(tone),
            **props,
        ),
        content=label,
    )


def reply_field(
    value: rx.Var[str],
    on_change: Any,
    *,
    disabled: rx.Var[bool],
    placeholder: str | rx.Var[str] = FIELD_PLACEHOLDER,
    field_id: str,
) -> rx.Component:
    """The text, one line that grows with what is written (`field-sizing: content`;
    a browser without it keeps two lines and a scroll). Enter is a new line."""
    return rx.text_area(
        value=value,
        on_change=on_change,
        placeholder=placeholder,
        disabled=disabled,
        rows="1",
        resize="none",
        aria_label=FIELD_LABEL,
        id=field_id,
        class_name="q-reply-field",
        width="100%",
    )


def send_button(on_click: Any, *, loading: rx.Var[bool], disabled: rx.Var[bool]) -> rx.Component:
    """«Enviar»: the box's one solid button."""
    return rx.button(
        rx.icon("send", size=T.ICON_SM, aria_hidden="true"),
        SEND_LABEL,
        on_click=on_click,
        loading=loading,
        disabled=disabled,
        size="3",
        type="button",
        min_height=TAP_MIN,
        class_name="q-reply-send",
    )


def plus_menu(
    box: ReplyBoxVM, on_select: Callable[[str], Any], *, disabled: rx.Var[bool]
) -> rx.Component:
    """The «+» with the rows this channel can send (`reply_box_vm.plus_rows`); each one
    opens a flow and never sends. Fewer than two rows: no «+» at all."""
    rows = plus_rows(box)
    if len(rows) < 2:
        return rx.fragment()
    return orbit_menu(
        PLUS_LABEL,
        [OrbitItem(key=r.key, icon=r.icon, text=r.text, on_select=on_select(r.key)) for r in rows],
        disabled=disabled,
    )


def reply_box_shell(box: ReplyBoxVM, *children: rx.Component) -> rx.Component:
    """The box's place when there is nothing to type (a closed window): the same frame,
    holding only what the owner can do or read there."""
    return rx.vstack(
        *children,
        spacing="2",
        width="100%",
        padding_top="0.5rem",
        class_name=f"q-wa-composer q-reply-box q-reply-box--{box.channel}",
    )


def reply_box(
    box: ReplyBoxVM,
    *,
    field: rx.Component,
    send: rx.Component,
    plus: rx.Component,
    above: tuple[rx.Component, ...] = (),
    tools: tuple[rx.Component, ...] = (),
    note: rx.Component | None = None,
) -> rx.Component:
    """The box, in its rows (module docstring). `q-wa-composer` stays: the thread's rules
    (the line above it, the iPhone's home bar) read it on both channels."""
    return rx.vstack(
        *above,
        *(
            [
                rx.flex(
                    *tools,
                    gap="0.5rem",
                    align="center",
                    class_name="q-reply-tools",
                    role="toolbar",
                    aria_label="Herramientas de la respuesta",
                )
            ]
            if tools
            else []
        ),
        rx.hstack(
            plus,
            rx.box(field, flex="1", min_width="0"),
            send,
            align="end",
            # U4: a tight gap, so the text gets the width at 360 px
            spacing="1",
            width="100%",
            class_name="q-reply-row",
        ),
        *([note] if note is not None else []),
        spacing="2",
        width="100%",
        padding_top="0.5rem",
        class_name=f"q-wa-composer q-reply-box q-reply-box--{box.channel}",
    )
