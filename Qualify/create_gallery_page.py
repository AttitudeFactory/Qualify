"""«Crear publicación» with the photos and videos chosen in Galería (CM-7, m-24955928).

One short screen, one decision: what the owner chose is already decided (in order, with
«Cambiar»), so only the sound (when a business video has it) and, optionally, what to
say remain before «Crear publicación». Design system only (`page_header` with the way
back to «Galería» — N7, `page_body`, `section`, `callout`, `media_thumb`, `tone_badge`,
Radix's switch and text area as the generator uses them). Phone first: three tiles a
row at 360 px, 44 px targets.
"""

from __future__ import annotations

import reflex as rx

from .create_gallery_state import CreateGalleryState
from .create_gallery_vm import (
    BACK_LABEL,
    CHANGE,
    CREATE,
    NOT_ENOUGH_MEDIA_TEXT,
    SOUND_LABEL,
    TITLE,
    TOPIC_HINT,
    TOPIC_LABEL,
    ChosenVM,
)
from .post_card import viewable_src
from .ui import (
    callout,
    card,
    loading_spinner,
    media_thumb,
    page_body,
    page_header,
    section,
    skeleton_rows,
    tone_badge,
)
from .ui import tokens as T

__all__ = ["create_gallery_view"]

S = CreateGalleryState
_TOUCH_MIN = "44px"
_THUMB_H = "6.5rem"
_CHOSEN = "Lo que elegiste"


def _picture(t: rx.Var[ChosenVM]) -> rx.Component:
    return rx.cond(
        t.thumb != "",
        media_thumb(viewable_src(t.thumb), size=None, width="100%", height=_THUMB_H),
        rx.cond(
            t.video != "",
            rx.box(
                rx.el.video(
                    src=viewable_src(t.video) + "#t=0.1",
                    preload="metadata",
                    muted=True,
                    plays_inline=True,
                    aria_hidden="true",
                    width="100%",
                    height="100%",
                ),
                class_name="q-catalog-video",
                height=_THUMB_H,
                width="100%",
            ),
            media_thumb(
                "",
                has=rx.Var.create(False),
                size=None,
                width="100%",
                height=_THUMB_H,
                icon=rx.cond(t.media_type == "video", "film", "image"),
            ),
        ),
    )


def _tile(t: rx.Var[ChosenVM]) -> rx.Component:
    return rx.box(
        _picture(t),
        rx.center(
            rx.text(t.order, size="2", weight="bold"),
            position="absolute",
            top="0.35rem",
            left="0.35rem",
            min_width="1.75rem",
            height="1.75rem",
            padding_x="0.35rem",
            border_radius="999px",
            background=T.tone_color("accent", 9),
            color="var(--accent-contrast)",
            class_name="q-nums",
            aria_hidden="true",
        ),
        rx.cond(
            t.duration != "",
            rx.box(
                tone_badge(t.duration, "neutral", icon="film"),
                position="absolute",
                bottom="0.35rem",
                right="0.35rem",
                class_name="q-nums",
                aria_hidden="true",
            ),
        ),
        position="relative",
        role="listitem",
        aria_label=t.label,
        key=t.key,
        min_width="0",
    )


def _chosen() -> rx.Component:
    return section(
        _CHOSEN,
        rx.box(
            rx.foreach(S.tiles, _tile),
            display="grid",
            grid_template_columns="repeat(auto-fill, minmax(6.25rem, 1fr))",
            gap="0.5rem",
            width="100%",
            role="list",
            aria_label=_CHOSEN,
        ),
        rx.button(
            rx.icon("pencil", size=T.ICON_SM),
            CHANGE,
            variant="soft",
            color_scheme=T.tone_scale("neutral"),
            size="3",
            type="button",
            min_height=_TOUCH_MIN,
            width=rx.breakpoints(initial="100%", sm="auto"),
            on_click=S.change,
            aria_label="Cambiar lo que elegiste",
        ),
        description=S.kind,
    )


def _sound() -> rx.Component:
    """D6: off at first; the line under it says what that means."""
    return rx.cond(
        S.offers_sound,
        card(
            rx.vstack(
                rx.el.label(
                    rx.hstack(
                        rx.switch(
                            checked=S.use_audio,
                            on_change=S.set_use_audio,
                            size="3",
                        ),
                        rx.text(SOUND_LABEL, size="3", weight="medium"),
                        align="center",
                        spacing="3",
                        min_height=_TOUCH_MIN,
                    ),
                ),
                rx.text(S.sound_text, size="2", color=T.TEXT_MUTED, role="status"),
                spacing="1",
                width="100%",
            ),
            padding="0.75rem 1rem",
            width="100%",
        ),
    )


def _topic() -> rx.Component:
    return rx.vstack(
        rx.el.label(TOPIC_LABEL, html_for="create-gallery-topic", class_name="rt-Text rt-r-size-2"),
        rx.text_area(
            id="create-gallery-topic",
            value=S.topic,
            on_change=S.set_topic,
            rows="3",
            max_length=280,
            width="100%",
            size="3",
        ),
        rx.text(TOPIC_HINT, size="1", color=T.TEXT_MUTED),
        spacing="1",
        width="100%",
    )


def _create_button() -> rx.Component:
    return rx.button(
        rx.cond(S.creating, loading_spinner("sm"), rx.icon("sparkles", size=T.ICON_SM)),
        CREATE,
        size="3",
        type="button",
        min_height=_TOUCH_MIN,
        width=rx.breakpoints(initial="100%", sm="auto"),
        disabled=S.creating | ~S.has_media,
        on_click=S.create,
    )


def _body() -> rx.Component:
    return rx.vstack(
        rx.cond(S.error != "", callout(S.error, "error")),
        rx.cond(S.dropped_text != "", callout(S.dropped_text, "warn")),
        rx.cond(
            S.has_media,
            rx.vstack(_chosen(), _sound(), _topic(), _create_button(), spacing="5", width="100%"),
            rx.cond(
                S.error == "",
                rx.vstack(
                    callout(NOT_ENOUGH_MEDIA_TEXT, "info"),
                    rx.button(
                        CHANGE,
                        variant="soft",
                        size="3",
                        type="button",
                        min_height=_TOUCH_MIN,
                        on_click=S.change,
                    ),
                    spacing="3",
                    align_items="start",
                ),
            ),
        ),
        spacing="4",
        width="100%",
        max_width="40rem",
    )


def create_gallery_view() -> rx.Component:
    return rx.fragment(
        page_header(
            TITLE,
            None,
            kicker=rx.link(
                rx.button(
                    rx.icon("chevron-left", size=T.ICON_SM),
                    BACK_LABEL,
                    variant="ghost",
                    color_scheme=T.tone_scale("neutral"),
                    size="3",
                    min_height=_TOUCH_MIN,
                ),
                href="/catalog",
            ),
        ),
        page_body(
            rx.cond(
                S.loading | ~S.loaded,
                rx.box(skeleton_rows(4), width="100%", aria_busy="true"),
                _body(),
            ),
        ),
    )
