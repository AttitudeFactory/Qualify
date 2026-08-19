"""Reusable UI primitives on top of Radix Themes.

Every helper here encodes one design-system rule so screens do not have to remember
it. The rules, in short (full text in docs/design-system.md §5):

* **A status is colour + icon/dot + word.** ``signal_pill``/``tone_badge`` always render
  the word; colour alone is never the only carrier.
* **The badge variant encodes the category.** ``soft`` = state (tone), ``outline`` =
  identity (platform, entity), ``surface`` = tag/category. Solid is reserved for the
  one primary action of a screen (buttons), never for a badge.
* **Surfaces are flat.** A card is a border on gray-2, no shadow.
* **Empty and error states direct.** They say what happened and what to do next.
"""

from __future__ import annotations

import reflex as rx

from . import tokens as T

# ---------------------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------------------


def card(*children: rx.Component, padding: str = "1.25rem", **props) -> rx.Component:
    """The flat surface everything sits on: gray-2 fill, gray-5 hairline, card radius."""
    style = {
        "border": T.BORDER,
        "border_radius": T.RADIUS_CARD,
        "background": T.SURFACE_BG,
        "padding": padding,
        "width": "100%",
    }
    style.update(props)
    return rx.box(*children, **style)


def stat_card(
    label: str,
    value: rx.Var | str,
    tone: str = "accent",
    hint: str | rx.Var | None = None,
) -> rx.Component:
    """One figure with its label. Tone colours the figure only; the label stays muted."""
    value_var = value.to_string() if isinstance(value, rx.Var) else value
    return card(
        rx.text(label, size="2", color=T.TEXT_MUTED),
        # A text, not a heading: a figure is not a section of the document outline.
        rx.text(
            value_var,
            size="7",
            weight="bold",
            color=T.tone_color(tone, 10),
            class_name="q-nums",
            line_height="1.2",
        ),
        *([rx.text(hint, size="1", color=T.TEXT_FAINT)] if hint is not None else []),
        padding="1rem 1.25rem",
    )


def kv(label: str, value: rx.Var | str, mono: bool = False) -> rx.Component:
    """A label/value pair for detail panels. ``mono`` for identifiers, handles, keys."""
    return rx.hstack(
        rx.text(label, size="2", color=T.TEXT_MUTED, min_width="9rem"),
        rx.text(value, size="2", class_name="q-mono" if mono else ""),
        align="baseline",
        spacing="3",
        width="100%",
    )


def mono(text: rx.Var | str, size: str = "2") -> rx.Component:
    """Inline identifier text (``@handle``, ids, keys) in the mono face."""
    return rx.text(text, size=size, class_name="q-mono")


# ---------------------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------------------


def status_dot(tone: str = "neutral", size: str = "8px") -> rx.Component:
    """The signal: a solid dot in the tone's step 9. Never used without a word next to
    it — pair through ``signal_pill``."""
    return rx.box(
        width=size,
        height=size,
        min_width=size,
        border_radius="9999px",
        background=T.tone_color(tone, 9),
        aria_hidden="true",
    )


def signal_pill(label: str | rx.Var, tone: str = "neutral", size: str = "1") -> rx.Component:
    """The product's status unit: dot + word in a soft badge. Used for connection
    health, publish attempts, sentiment, sync state — anything with a lifecycle."""
    return rx.badge(
        status_dot(tone),
        label,
        variant="soft",
        size=size,
        radius="full",
        **T.tone_scheme(tone),
    )


def tone_badge(
    label: str | rx.Var, tone: str = "neutral", icon: str | None = None, size: str = "1"
) -> rx.Component:
    """A soft badge in a tone, optionally with a lucide icon. For states where a dot is
    too quiet (a card-level verdict, a table cell that must be scanned)."""
    children: list = []
    if icon:
        children.append(rx.icon(icon, size=12))
    children.append(label)
    return rx.badge(*children, variant="soft", size=size, **T.tone_scheme(tone))


def platform_badge(platform: rx.Var[str] | str) -> rx.Component:
    """Identity badge for a social platform — always ``outline`` so it can never be
    mistaken for a state. Static strings resolve at build time; Vars via ``rx.match``."""
    if isinstance(platform, str):
        return rx.badge(
            T.PLATFORM_LABEL.get(platform, platform),
            variant="outline",
            color_scheme=T.platform_scale(platform),
            size="1",
        )
    return rx.match(
        platform,
        *[
            (
                key,
                rx.badge(
                    T.PLATFORM_LABEL[key],
                    variant="outline",
                    color_scheme=T.PLATFORM_SCALE[key],
                    size="1",
                ),
            )
            for key in T.PLATFORM_SCALE
        ],
        rx.badge(platform, variant="outline", color_scheme="gray", size="1"),
    )


def tag(label: str | rx.Var, size: str = "1") -> rx.Component:
    """A category / free label (interest, source, topic). ``surface`` gray, so it reads
    as metadata rather than as a state or an identity."""
    return rx.badge(label, variant="surface", color_scheme="gray", size=size)


def sentiment_badge(sentiment: rx.Var[str]) -> rx.Component:
    """Sentiment is a state: positive=ok, negative=error, anything else neutral."""
    return rx.match(
        sentiment,
        ("positive", signal_pill("Positiva", "ok")),
        ("negative", signal_pill("Negativa", "error")),
        signal_pill("Neutra", "neutral"),
    )


# ---------------------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------------------


def callout(
    message: str | rx.Var,
    tone: str = "info",
    icon: str | None = None,
    **props,
) -> rx.Component:
    """Inline, persistent feedback tied to a place on the page (a load error above a
    list, a warning about a limit). Not for transient confirmations — use ``rx.toast``."""
    default_icon = {
        "error": "triangle-alert",
        "warn": "triangle-alert",
        "ok": "check",
        "info": "info",
        "neutral": "info",
        "accent": "info",
    }[tone if tone in T.TONE_SCALE else "info"]
    return rx.callout(
        message,
        icon=icon or default_icon,
        variant="surface",
        width="100%",
        role="alert" if tone == "error" else "status",
        **T.tone_scheme(tone),
        **props,
    )


def empty_state(
    icon: str,
    title: str,
    description: str,
    action: rx.Component | None = None,
) -> rx.Component:
    """Centred invitation to act: what is missing, why, and (optionally) the one button
    that fixes it. Copy rule: title = the fact ("Aún no…"), body = the next step."""
    return rx.center(
        rx.vstack(
            rx.icon(icon, size=T.ICON_LG, color=T.TEXT_FAINT),
            rx.heading(title, size="5", as_="h2"),
            rx.text(
                description,
                size="2",
                color=T.TEXT_MUTED,
                text_align="center",
                max_width="440px",
            ),
            *([action] if action is not None else []),
            spacing="3",
            align="center",
        ),
        padding=T.PAD_EMPTY,
        width="100%",
    )


def skeleton_card(lines: int = 3) -> rx.Component:
    """Loading placeholder shaped like ``card``. Use as many as rows you expect."""
    widths = ["40%", "60%", "100%", "80%", "50%"]
    return card(
        rx.vstack(
            *[
                rx.skeleton(rx.box(height="1rem" if i else "1.5rem", width=widths[i % 5]))
                for i in range(lines)
            ],
            spacing="3",
            width="100%",
        ),
        background="transparent",
        aria_busy="true",
    )


def skeleton_rows(rows: int = 3, height: str = "2.5rem") -> rx.Component:
    """Loading placeholder for a table or list."""
    return rx.vstack(
        *[rx.skeleton(rx.box(height=height, width="100%")) for _ in range(rows)],
        spacing="2",
        width="100%",
        aria_busy="true",
    )


def demo_notice(message: str | rx.Var) -> rx.Component:
    """The "this is a demo / not live" band. Dashed border so it cannot be confused
    with real content or with an error."""
    return rx.box(
        rx.hstack(
            rx.icon("flask-conical", size=T.ICON_MD, color=T.tone_color("warn", 11)),
            rx.text(message, size="2"),
            align="center",
            spacing="2",
        ),
        padding="0.75rem 1rem",
        border=f"1px dashed {T.tone_color('warn', 7)}",
        border_radius=T.RADIUS_CONTROL,
        background=T.tone_color("warn", 2),
        width="100%",
    )
