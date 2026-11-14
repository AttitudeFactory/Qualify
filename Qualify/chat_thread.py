"""The open chat both channels draw (m-25027371, BU-A5): ONE thread for WhatsApp →
Chats and Conversaciones (Instagram).

A composition of design-system pieces (`card`, `chat_bubble`, `signal_pill`, `tag`,
`skeleton_rows`, `callout`, Radix menu and accordion), not a new component — the same
standing as `chat_row.py`. Each page hands over its channel's data; what the owner
sees is the same on both:

- the **header**: «‹ Por responder» (when the chat came from the single list), the
  person's picture or initials with the channel's glyph, the name, the channel's word
  and until when the owner can write («Puedes escribirle hasta las …» / «Quedan N min
  para responder»), the channel's state pills, and «⋯» with what is used seldom
  (Asignar, Cerrar / Reabrir, Ajustes de este canal). The header carries the channel's
  wash (`--q-chat-tint-3`), and ONLY the header: under the messages the thread is
  `--gray-a2` by default (a UX preference awaiting the founder: with or without a
  wash under the messages, both pass the contrast measured in the built screen);
- the **bubbles**: the business's on the channel's soft tint with dark text, the
  customer's on the control material; time, «Enviado» and the ticks inside the business
  bubble in `--gray-12`, «Leído» in `--accent-11`, an error in `--tomato-12`, a link in
  `--accent-12` underlined (`assets/qualify-inbox.css`, `.q-chat-*`);
- the **day separators** («Hoy», «Ayer», «12 oct»), the **status mark** (an icon with
  its word as the accessible name and tooltip), and the **empty / loading / error**
  states.

The channel's colour is data: `chat_thread_vm.thread_style(channel)` turns
`T.PLATFORM_SCALE` into the custom properties the one rule set reads.
"""

from __future__ import annotations

from typing import Any

import reflex as rx

from .chat_row import chat_avatar, instagram_glyph
from .chat_row import tone_pill as _tone_pill
from .chat_row_vm import CHANNEL_INSTAGRAM, CHANNEL_WHATSAPP, INBOX_BACK_LABEL
from .chat_thread_vm import MORE_ACTIONS_LABEL, NO_MESSAGES, channel_name, thread_style
from .ui import callout, card, chat_bubble, skeleton_rows, tag
from .ui import tokens as T

#: N12: every tap target in the thread is at least 44 px.
TAP_MIN = "2.75rem"


# ======================================================================================
# Frame
# ======================================================================================


def thread_frame(channel: str, *children: rx.Component, **props: Any) -> rx.Component:
    """The conversation's card. `.q-chat-thread` + the channel's custom properties: the
    one rule set paints both channels from them."""
    return card(
        rx.vstack(*children, spacing="3", width="100%"),
        padding="1rem",
        class_name=f"q-card q-chat-thread q-chat-thread--{channel}",
        style=thread_style(channel),
        width="100%",
        **props,
    )


def thread_body(
    *,
    error: rx.Var[str],
    on_retry: Any,
    ready: rx.Var[bool],
    content: rx.Component,
) -> rx.Component:
    """Error (the reason + «Reintentar»), loading (the skeleton of the bubbles to come),
    or the content."""
    return rx.cond(
        error != "",
        rx.vstack(
            callout(error, "error"),
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                "Reintentar",
                on_click=on_retry,
                variant="soft",
                size="2",
                min_height=TAP_MIN,
                **T.tone_scheme("neutral"),
            ),
            width="100%",
            spacing="3",
        ),
        rx.cond(ready, content, skeleton_rows(4, height="3rem")),
    )


def no_chat_open(text: str) -> rx.Component:
    """The right pane while no chat is open (desktop): a quiet hint, not an empty state."""
    return rx.center(
        rx.vstack(
            rx.box(rx.icon("message-square-text", size=22), class_name="q-conv-placeholder-glyph"),
            rx.text("Elige una conversación", size="2", weight="medium"),
            rx.text(text, size="1", color=T.TEXT_MUTED, text_align="center"),
            spacing="1",
            align="center",
            max_width="20rem",
        ),
        class_name="q-conv-placeholder",
        width="100%",
    )


# ======================================================================================
# Header
# ======================================================================================


def back_button(on_click: Any, *, label: str = INBOX_BACK_LABEL, **props: Any) -> rx.Component:
    """N7: the button names where it goes — «‹ Por responder» — never a bare arrow."""
    return rx.button(
        rx.icon("chevron-left", size=T.ICON_MD),
        label,
        on_click=on_click,
        variant="ghost",
        size="2",
        min_height="44px",
        type="button",
        **T.tone_scheme("neutral"),
        **props,
    )


def _channel_glyph(channel: str) -> rx.Component:
    if channel == CHANNEL_WHATSAPP:
        return rx.icon("message-circle", size=12, stroke_width=2.6, aria_hidden="true")
    if channel == CHANNEL_INSTAGRAM:
        return instagram_glyph()
    return rx.fragment()


def window_text(text: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """Until when the owner can write. Said in words; the `warn` tone (under an hour)
    adds the clock icon and the warn colour, never colour alone."""
    return rx.cond(
        text != "",
        rx.hstack(
            rx.cond(
                tone == "warn",
                rx.icon("clock-alert", size=T.ICON_SM, aria_hidden="true"),
                rx.icon("clock", size=T.ICON_SM, aria_hidden="true"),
            ),
            rx.text(text, size="1"),
            spacing="1",
            align="center",
            class_name=rx.cond(
                tone == "warn", "q-chat-window q-chat-window--warn", "q-chat-window"
            ),
        ),
        rx.fragment(),
    )


def more_menu(*items: rx.Component) -> rx.Component:
    """«⋯»: what is used seldom. A 44 px icon button with its name for the keyboard and
    the screen reader; Radix's menu brings arrows, Esc and the focus return."""
    return rx.menu.root(
        rx.menu.trigger(
            rx.icon_button(
                rx.icon("ellipsis", size=T.ICON_MD),
                variant="ghost",
                size="3",
                type="button",
                aria_label=MORE_ACTIONS_LABEL,
                title=MORE_ACTIONS_LABEL,
                min_width=TAP_MIN,
                min_height=TAP_MIN,
                class_name="q-chat-more",
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.menu.content(*items, align="end", class_name="q-chat-menu"),
        modal=False,
    )


def menu_item(label: rx.Var[str] | str, icon: str | rx.Component, **props: Any) -> rx.Component:
    """One «⋯» entry, at least 44 px tall (N12)."""
    glyph = rx.icon(icon, size=T.ICON_SM) if isinstance(icon, str) else icon
    return rx.menu.item(
        rx.hstack(glyph, rx.text(label), spacing="2", align="center"),
        min_height=TAP_MIN,
        **props,
    )


def thread_header(
    *,
    channel: str,
    title: rx.Var[str],
    initials: rx.Var[str],
    avatar_url: rx.Var[str],
    subtitle: rx.Component | None = None,
    window: rx.Component | None = None,
    pills: tuple[rx.Component, ...] = (),
    is_closed: rx.Var[bool] | None = None,
    back: rx.Component | None = None,
    actions: rx.Component | None = None,
    menu: rx.Component | None = None,
) -> rx.Component:
    """Back · avatar + name (+ subtitle) · «⋯» on top; then the channel's word, the
    window line, the state pills and «Cerrado» on one wrapping line (at 360 px they
    drop under the name instead of overlapping it); then the channel's own actions."""
    meta_line = rx.hstack(
        rx.hstack(
            _channel_glyph(channel),
            rx.text(channel_name(channel), size="1", weight="medium"),
            spacing="1",
            align="center",
            class_name="q-chat-channel-word",
        ),
        # The pills first: at 360 px the most urgent («Pago por revisar») stays on the
        # first line (m-24955648); the window line wraps after them.
        *pills,
        *([window] if window is not None else []),
        *([rx.cond(is_closed, tag("Cerrado"), rx.fragment())] if is_closed is not None else []),
        spacing="2",
        flex_wrap="wrap",
        align="center",
        width="100%",
    )
    return rx.vstack(
        *([back] if back is not None else []),
        rx.hstack(
            chat_avatar(initials, avatar_url, channel, large=True),
            rx.vstack(
                rx.heading(title, size="4", as_="h2", class_name="q-wa-ellipsis", width="100%"),
                *([subtitle] if subtitle is not None else []),
                spacing="0",
                min_width="0",
                flex="1",
            ),
            *([menu] if menu is not None else []),
            width="100%",
            align="center",
            spacing="3",
        ),
        meta_line,
        *([actions] if actions is not None else []),
        spacing="2",
        width="100%",
        class_name="q-chat-head",
    )


def state_pill(label: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """A state pill whose tone is data; nothing when there is no label."""
    return rx.cond(label != "", _tone_pill(label, tone), rx.fragment())


# ======================================================================================
# Messages
# ======================================================================================


def status_mark(tick: rx.Var[str], label: rx.Var[str]) -> rx.Component:
    """The business message's state, as an icon with its word (`aria-label` + tooltip):
    clock «Por enviar», ✓ «Enviado», ✓✓ «Entregado», ✓✓ in the accent «Leído», the alert
    «No entregado». The colour lives in the sheet (`.q-chat-tick--*`), never inline, so
    the measured tokens apply inside the tinted bubble."""
    icon = rx.match(
        tick,
        ("sent", rx.icon("check", size=T.ICON_SM)),
        ("delivered", rx.icon("check-check", size=T.ICON_SM)),
        ("read", rx.icon("check-check", size=T.ICON_SM)),
        ("queued", rx.icon("clock", size=T.ICON_SM)),
        ("failed", rx.icon("circle-alert", size=T.ICON_SM)),
        rx.fragment(),
    )
    return rx.cond(
        tick != "",
        rx.box(
            icon,
            title=label,
            aria_label=label,
            role="img",
            display="inline-flex",
            align_items="center",
            class_name="q-chat-tick q-chat-tick--" + tick,
        ),
        rx.fragment(),
    )


def bubble_meta(
    *,
    time_label: rx.Var[str],
    tick: rx.Var[str],
    tick_label: rx.Var[str],
    error_label: rx.Var[str],
    leading: rx.Component | None = None,
) -> rx.Component:
    """Time + status mark under the text (inside the bubble), and the error in words."""
    return rx.vstack(
        rx.hstack(
            *([leading] if leading is not None else []),
            rx.text(time_label, size="1", class_name="q-nums q-chat-time"),
            status_mark(tick, tick_label),
            spacing="1",
            align="center",
            justify="end",
            width="100%",
        ),
        rx.cond(
            error_label != "",
            rx.text(error_label, size="1", class_name="q-chat-error"),
            rx.fragment(),
        ),
        spacing="1",
        width="100%",
        padding_top="0.35rem",
    )


def day_separator(label: rx.Var[str]) -> rx.Component:
    """«Hoy» / «Ayer» / «12 oct» on the first message of each day."""
    return rx.cond(
        label != "",
        rx.center(
            rx.box(rx.text(label, size="1"), class_name="q-conv-day"),
            width="100%",
            role="separator",
            aria_label=label,
        ),
        rx.fragment(),
    )


def message_row(
    *,
    outbound: rx.Var[bool],
    body: rx.Component,
    meta: rx.Component,
    before: tuple[rx.Component, ...] = (),
    has_before: rx.Var[bool] | None = None,
    bare: rx.Var[bool] | None = None,
) -> rx.Component:
    """One message: the business's on the right in the channel's tint, the customer's on
    the left (with its context lines — an ad, a story, a tap — above). `bare` drops the
    bubble's fill (a sticker heart). The entrance plays once per message: the caller
    keys the row by message id."""
    out_class = "q-wa-msg q-wa-msg--out q-chat-msg q-chat-msg--out"
    in_class = "q-wa-msg q-wa-msg--in q-chat-msg q-chat-msg--in"
    return rx.cond(
        outbound,
        rx.box(
            chat_bubble(body, direction="out", meta=meta),
            class_name=(
                rx.cond(bare, out_class + " q-chat-msg--bare", out_class)
                if bare is not None
                else out_class
            ),
        ),
        rx.box(
            *before,
            chat_bubble(body, direction="in", meta=meta),
            class_name=(
                rx.cond(has_before, in_class + " q-chat-msg--context", in_class)
                if has_before is not None
                else in_class
            ),
        ),
    )


def thread_scroll(top: rx.Component, messages: rx.Var[list], render: Any) -> rx.Component:
    """The messages, oldest first, anchored at the newest (`column-reverse`, no JS);
    `top` is the channel's line above them («Cargar anteriores» / «Se muestran…»)."""
    return rx.box(
        rx.vstack(
            top,
            rx.cond(
                messages.length() > 0,
                rx.foreach(messages, render),
                rx.text(
                    NO_MESSAGES,
                    size="2",
                    color=T.TEXT_MUTED,
                    text_align="center",
                    width="100%",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        class_name="q-wa-scroll q-wa-scroll--messages q-chat-scroll",
        width="100%",
        role="log",
        aria_label="Mensajes",
    )


# ======================================================================================
# The order strip (WhatsApp)
# ======================================================================================


def order_strip(label: rx.Var[str], content: rx.Component) -> rx.Component:
    """«Pedido · 3 productos · COP 45.000 · Pago por revisar», folded; one tap opens the
    order card of today, unchanged (UX §4 point 9). Radix's accordion: a real button
    with `aria-expanded`, Enter and Space."""
    return rx.accordion.root(
        rx.accordion.item(
            header=rx.hstack(
                rx.icon("shopping-bag", size=T.ICON_MD, aria_hidden="true"),
                rx.text(label, size="2", weight="medium", text_align="left"),
                spacing="2",
                align="center",
            ),
            content=content,
            value="order",
        ),
        collapsible=True,
        type="single",
        variant="ghost",
        width="100%",
        class_name="q-chat-order",
    )
