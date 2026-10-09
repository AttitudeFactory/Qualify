"""A real carousel for a piece's slides (§ request 2026-10-08): one slide in view,
arrows to move, dots and a «2 / 5» counter — the way Instagram will show it — instead
of the slides stacked one under the other. Shared by the generator's result and the
draft screen; each screen keeps its own way of drawing one file (`render_item`), so
the slide keeps its frame and its download bar.

Plain Reflex state events, no script of its own: every slide stays mounted and only the
active one is displayed, so moving never reloads an image. Swiping on a phone is not
wired (arrows and dots work there too)."""

from __future__ import annotations

from collections.abc import Callable

import reflex as rx

from .ui import tokens as T

#: The carousel moves to the next slide by itself every this many ms (§ request
#: 2026-10-08: "un pequeño delay para que cambien solas"), back to the first after the
#: last; the arrows and dots still work.
AUTOPLAY_MS = 4000


def _arrow(icon: str, label: str, side: str, on_click: rx.event.EventSpec) -> rx.Component:
    return rx.icon_button(
        rx.icon(icon, size=18),
        on_click=on_click,
        aria_label=label,
        title=label,
        variant="solid",
        color_scheme="gray",
        radius="full",
        size="2",
        position="absolute",
        top="40%",
        transform="translateY(-50%)",
        z_index="2",
        opacity="0.85",
        box_shadow="0 2px 8px rgba(0, 0, 0, 0.35)",
        **{side: "0.6rem"},
    )


def media_carousel(
    items: rx.Var,
    index: rx.Var[int],
    *,
    on_prev: rx.event.EventSpec,
    on_next: rx.event.EventSpec,
    on_pick: Callable[[rx.Var[int]], rx.event.EventSpec],
    on_tick: Callable[[], rx.event.EventSpec],
    render_item: Callable[[rx.Var], rx.Component],
) -> rx.Component:
    """`items` (a list of `MediaVM`) as a carousel on slide `index`. `on_pick(i)` jumps
    to slide `i` (the dots); `on_prev` / `on_next` step one (the arrows, hidden at the
    ends); `on_tick()` moves on by itself every `AUTOPLAY_MS`, wrapping around."""
    total = items.length()
    return rx.vstack(
        # a client-side heartbeat (react-moment's own setInterval), mounted only while
        # the carousel is — the same pattern as /inbox's sync timer
        rx.moment(interval=AUTOPLAY_MS, on_change=lambda _tick: on_tick(), display="none"),
        rx.box(
            rx.foreach(
                items,
                lambda item, i: rx.box(
                    render_item(item),
                    display=rx.cond(i == index, "block", "none"),
                    width="100%",
                ),
            ),
            rx.cond(index > 0, _arrow("chevron-left", "Diapositiva anterior", "left", on_prev)),
            rx.cond(
                index < total - 1,
                _arrow("chevron-right", "Diapositiva siguiente", "right", on_next),
            ),
            position="relative",
            width="100%",
        ),
        rx.hstack(
            rx.hstack(
                rx.foreach(
                    items,
                    lambda _item, i: rx.box(
                        on_click=on_pick(i),
                        role="button",
                        aria_label=rx.Var.create("Ir a la diapositiva ") + (i + 1).to_string(),
                        cursor="pointer",
                        width=rx.cond(i == index, "1.1rem", "0.5rem"),
                        height="0.5rem",
                        border_radius="999px",
                        background=rx.cond(
                            i == index, T.tone_color("accent", 9), T.tone_color("neutral", 6)
                        ),
                        transition=f"width {T.DUR_FAST} {T.EASE}",
                    ),
                ),
                spacing="1",
                align="center",
            ),
            rx.text(
                index + 1,
                " / ",
                total,
                size="1",
                color=T.TEXT_MUTED,
                class_name="q-nums",
            ),
            justify="between",
            align="center",
            width="100%",
        ),
        spacing="2",
        width="100%",
        class_name="q-carousel",
    )
