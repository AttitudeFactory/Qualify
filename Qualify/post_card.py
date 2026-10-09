"""The POST card (QUA-118): one component for the Planificador's «Sin programar» panel
and the `/drafts` gallery, over one view-model (`planner_vm.PostOptionVM`), so the two
never drift apart. Also the small pieces both screens need around a POST — the tone
pill, the thumbnail / first video frame, the evaluator's note, the per-output chip —
and the two HTML drag-and-drop hosts the calendar uses.

A card says the POST's state the design system's way (P1: colour + line + word): a
`signal_pill` with the state word, the card's left edge in the same tone, and the
«Usado ×N» / «En calendario» badges for its history (D2). «Programado» is never printed
here — that word belongs to the calendar event.
"""

from __future__ import annotations

from typing import Any

import reflex as rx

from .planner_vm import DESTINATION_ICONS, KIND_ICONS
from .r2_media import BACKEND_BASE
from .ui import card, signal_pill, tag
from .ui import tokens as T

_TONES = ("ok", "warn", "error", "info", "neutral", "accent")
_CLAMP_2 = {
    "display": "-webkit-box",
    "-webkit-line-clamp": "2",
    "-webkit-box-orient": "vertical",
    "overflow": "hidden",
}


class DragBox(rx.el.Div):
    """A `div` that can be dragged (native HTML drag and drop — no custom JavaScript).
    The browser does the dragging; the handlers only record what is being dragged."""

    on_drag_start: rx.EventHandler[rx.event.no_args_event_spec]
    on_drag_end: rx.EventHandler[rx.event.no_args_event_spec]


class DropBox(rx.el.Div):
    """A `div` something can be dropped on. `on_drag_over` must prevent the default
    (`rx.event.prevent_default`) or the browser refuses the drop."""

    on_drag_over: rx.EventHandler[rx.event.no_args_event_spec]
    on_drag_enter: rx.EventHandler[rx.event.no_args_event_spec]
    on_drag_leave: rx.EventHandler[rx.event.no_args_event_spec]
    on_drop: rx.EventHandler[rx.event.no_args_event_spec]


def pill(label: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """`signal_pill` for a tone that is only known at runtime."""
    return rx.match(
        tone,
        *[(t, signal_pill(label, t)) for t in _TONES],
        signal_pill(label, "neutral"),
    )


def tone_edge(tone: rx.Var[str]) -> rx.Var:
    """The card's left edge in the tone's colour — the line of «colour + line + word»."""
    return rx.match(
        tone,
        ("ok", f"3px solid {rx.color('green', 9)}"),
        ("warn", f"3px solid {rx.color('amber', 9)}"),
        ("error", f"3px solid {rx.color('tomato', 9)}"),
        ("info", f"3px solid {rx.color('blue', 9)}"),
        ("accent", f"3px solid {rx.color('accent', 9)}"),
        f"3px solid {rx.color('gray', 8)}",
    )


def thumbnail(url: rx.Var[str], size: str) -> rx.Component:
    """`url` is an http(s) URL, a backend `/r2media/<token>` path (a generated piece,
    in R2 only since 2026-10-06) or a local upload-store key, resolved the way the creative
    screens do, with `rx.get_upload_url`."""
    return rx.cond(
        url != "",
        rx.image(
            src=rx.cond(
                url.startswith("http"),
                url,
                rx.cond(url.startswith("/r2media"), BACKEND_BASE + url, rx.get_upload_url(url)),
            ),
            alt="",
            width=size,
            height=size,
            min_width=size,
            object_fit="cover",
            border_radius=T.RADIUS_CONTROL,
            border=T.BORDER,
        ),
        rx.center(
            rx.icon("image", size=T.ICON_SM, color=T.TEXT_FAINT),
            width=size,
            height=size,
            min_width=size,
            background=T.SURFACE_BG_RAISED,
            border_radius=T.RADIUS_CONTROL,
            border=T.BORDER,
        ),
    )


def card_media(thumbnail_url: rx.Var[str], video_url: rx.Var[str], size: str) -> rx.Component:
    """A card's picture: the first frame of the POST's R2-only video when it has one (a
    muted, controls-less `<video>` that only loads metadata — served with HTTP Range, so
    a card reads a few MB, not the reel), otherwise the image thumbnail / placeholder."""
    return rx.cond(
        video_url != "",
        rx.el.video(
            src=BACKEND_BASE + video_url + "#t=0.1",
            muted=True,
            preload="metadata",
            plays_inline=True,
            aria_hidden="true",
            width=size,
            height=size,
            style={
                "min_width": size,
                "object_fit": "cover",
                "border_radius": T.RADIUS_CONTROL,
                "border": T.BORDER,
                "background": "black",
                "pointer_events": "none",
            },
        ),
        thumbnail(thumbnail_url, size),
    )


def readiness_note(note: rx.Var[str]) -> rx.Component:
    """The evaluator's reason, under an approved-but-not-ready POST (card, list, panel)."""
    return rx.cond(
        note != "",
        rx.hstack(
            rx.icon("triangle-alert", size=12, color=rx.color("amber", 10), flex_shrink="0"),
            rx.text(note, size="1", color=rx.color("amber", 11)),
            align="start",
            spacing="1",
        ),
    )


def output_chip(chip: rx.Var) -> rx.Component:
    """«Feed · lun 12 · 12:00 p. m. · @bianki» — one output's planning state, by tone."""
    return rx.box(
        pill(chip.word + " · " + chip.state_label, chip.tone),
        title=rx.cond(chip.note != "", chip.note, chip.label),
    )


def kind_icon(kind: rx.Var[str], size: int = 14) -> rx.Component:
    """The format's glyph — `rx.icon` needs a literal name, so a match over the kinds."""
    return rx.match(
        kind,
        *[(key, rx.icon(icon, size=size)) for key, icon in KIND_ICONS.items()],
        rx.icon("image", size=size),
    )


def kind_chip(kind: rx.Var[str], label: rx.Var[str], *, glass: bool = False) -> rx.Component:
    """«▶ Reel» in the format's colour; `glass` for a chip laid over media."""
    return rx.box(
        kind_icon(kind, 12),
        rx.text(label, as_="span"),
        class_name="q-kind-chip q-kind-" + kind + (" q-kind-chip--glass" if glass else ""),
    )


def temperature_badge(
    temperature: rx.Var[str],
    label: rx.Var[str],
    hint: rx.Var[str],
    *,
    compact: bool = False,
):
    """Cold (snowflake, ice gradient) or Hot (flame, fire gradient); nothing when the
    POST's history is unknown. `compact` keeps the glyph and drops the word (a calendar
    chip); the word stays in the tooltip and the accessible name."""
    return rx.cond(
        temperature != "",
        rx.box(
            rx.cond(
                temperature == "cold",
                rx.icon("snowflake", size=11 if compact else 12),
                rx.icon("flame", size=11 if compact else 12),
            ),
            *([] if compact else [rx.text(label, as_="span")]),
            class_name="q-temp q-temp--" + temperature + (" q-temp--mini" if compact else ""),
            title=hint,
            aria_label=hint,
        ),
    )


def media_fill(thumbnail_url: rx.Var[str], video_url: rx.Var[str], kind: rx.Var[str]):
    """A POST's picture filling its frame: the R2 video's first frame, the image, or —
    with neither — the format's own gradient and glyph."""
    return rx.cond(
        video_url != "",
        rx.el.video(
            src=BACKEND_BASE + video_url + "#t=0.1",
            muted=True,
            preload="metadata",
            plays_inline=True,
            aria_hidden="true",
            class_name="q-media-fill",
        ),
        rx.cond(
            thumbnail_url != "",
            rx.image(
                src=rx.cond(
                    thumbnail_url.startswith("http"),
                    thumbnail_url,
                    rx.get_upload_url(thumbnail_url),
                ),
                alt="",
                class_name="q-media-fill",
            ),
            rx.center(kind_icon(kind, 26), class_name="q-media-empty q-kind-" + kind),
        ),
    )


def destination_icon(destination: rx.Var[str] | str, size: int = 12) -> rx.Component:
    """The destination's glyph (`rx.icon` needs a literal name, hence the match)."""
    if isinstance(destination, str):
        return rx.icon(DESTINATION_ICONS.get(destination, "send"), size=size)
    return rx.match(
        destination,
        *[(key, rx.icon(icon, size=size)) for key, icon in DESTINATION_ICONS.items()],
        rx.icon("send", size=size),
    )


def destination_badge(
    destination: rx.Var[str], label: rx.Var[str], *, prefix: str = ""
) -> rx.Component:
    """QUA-118 v2: where an event goes out — glyph AND word («Publicación», «Reel»,
    «Historia»), in the destination's colour; never the colour alone. Nothing when the
    destination is unknown."""
    return rx.cond(
        destination != "",
        rx.box(
            destination_icon(destination),
            rx.text(prefix + label, as_="span"),
            class_name="q-dest-badge q-dest-" + destination,
        ),
    )


def campaign_badge(name: rx.Var[str], color: rx.Var[str]) -> rx.Component:
    """QUA-143: the POST's campaign — a flag AND its name, in the campaign's palette
    colour (`q-tint-*`, shared with tags). Identity, never state: a squared, bordered
    badge with a flag so it never reads as a tag pill or a status. Nothing when the POST
    is independent."""
    return rx.cond(
        name != "",
        rx.box(
            rx.icon("flag", size=11, flex_shrink="0"),
            rx.text(name, as_="span", class_name="q-campaign-name"),
            class_name="q-campaign-badge q-tint-" + color,
            title="Campaña: " + name,
        ),
    )


def color_swatches(
    selected: rx.Var[str], on_pick, choices: dict[str, str], *, label: str
) -> rx.Component:
    """QUA-143: the campaign colours — `choices` is the closed list of four (key → word),
    never a state colour. A radio group of round swatches; the chosen one is ringed.
    `on_pick(key)` returns the event to fire."""
    return rx.hstack(
        *[
            rx.el.button(
                type="button",
                role="radio",
                aria_checked=rx.cond(selected == key, "true", "false"),
                aria_label=word,
                title=word,
                on_click=on_pick(key),
                class_name=rx.cond(
                    selected == key,
                    f"q-swatch q-swatch--on q-tint-{key}",
                    f"q-swatch q-tint-{key}",
                ),
            )
            for key, word in choices.items()
        ],
        role="radiogroup",
        aria_label=label,
        spacing="2",
        align="center",
    )


def campaign_mark(name: rx.Var[str], color: rx.Var[str]) -> rx.Component:
    """QUA-143: the compact form for the one-line calendar chip and the «+N más» rows —
    a small flag tile in the campaign's colour (its name is in the hover card, the
    accessible name and the panel). Nothing when the POST is independent."""
    return rx.cond(
        name != "",
        rx.center(
            rx.icon("flag", size=9, color="white", stroke_width=2.75),
            class_name="q-campaign-mark q-tint-" + color,
            title="Campaña: " + name,
        ),
    )


def history_badges(post: rx.Var) -> rx.Component:
    """D2: «Usado ×N» for the publications already out, «En calendario» for a live
    event. Never excluding — a `recurrente` POST reads Listo + Usado ×3."""
    return rx.fragment(
        rx.cond(
            post.used_count > 0,
            rx.badge(
                rx.icon("history", size=11),
                "Usado ×" + post.used_count.to_string(),
                variant="soft",
                color_scheme=T.tone_scale("info"),
                size="1",
                radius="full",
                title="Veces publicado desde el Planificador",
            ),
        ),
        rx.cond(
            post.in_calendar,
            rx.badge(
                rx.icon("calendar-check", size=11),
                "En calendario",
                variant="outline",
                color_scheme="gray",
                size="1",
                radius="full",
                title="Tiene una publicación programada o en curso",
            ),
        ),
    )


def post_card(
    post: rx.Var,
    *,
    actions: rx.Component,
    size: str = "2.75rem",
    on_drag_start: Any = None,
    on_drag_end: Any = None,
    show_media_label: bool = False,
) -> rx.Component:
    """The POST as a card. `actions` is the row under the body (links, «Asignar»);
    with `on_drag_start` the card becomes draggable (the calendar's «Sin programar»).
    The left edge, the pill and the word all carry the gallery state (P1)."""
    body = rx.hstack(
        card_media(post.thumbnail_url, post.video_url, size),
        rx.vstack(
            rx.text(post.title, size="2", weight="medium", style=_CLAMP_2),
            rx.flex(
                pill(post.gallery_label, post.gallery_tone),
                # The gallery prints «Video · Reel 9:16» — medium and format in one tag,
                # the category word included — instead of «Reel» + «Video · Reel 9:16».
                rx.cond(
                    show_media_label & (post.media_label != ""),
                    tag(post.media_label),
                    tag(post.category_label),
                ),
                # QUA-118 v2: Cold (evergreen, proven) / Hot (new) — `planner_vm.temperature`.
                temperature_badge(post.temperature, post.temperature_label, post.temperature_hint),
                history_badges(post),
                wrap="wrap",
                gap="0.3rem",
                align="center",
            ),
            # MP-11: one chip per template output with its planning state; the
            # package stays one card and is taken apart when assigning.
            rx.cond(
                post.has_outputs,
                rx.flex(rx.foreach(post.outputs, output_chip), wrap="wrap", gap="0.25rem"),
            ),
            readiness_note(post.readiness_note),
            spacing="1",
            min_width="0",
            flex="1",
        ),
        spacing="2",
        align="start",
        width="100%",
    )
    inner = card(
        body,
        rx.box(actions, width="100%", margin_top="0.5rem"),
        padding="0.6rem 0.6rem 0.6rem 0.75rem",
        border_left=tone_edge(post.gallery_tone),
    )
    if on_drag_start is None:
        return inner
    return DragBox.create(
        inner,
        draggable=True,
        on_drag_start=on_drag_start,
        on_drag_end=on_drag_end,
        class_name="q-post-drag",
        title="Arrastra al calendario, o pulsa «Asignar»",
        width="100%",
    )
