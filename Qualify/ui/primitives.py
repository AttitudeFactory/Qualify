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

from collections.abc import Callable
from typing import Any

import reflex as rx

from . import tokens as T

# ---------------------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------------------


def card(
    *children: rx.Component,
    padding: str = "1.25rem",
    interactive: bool = False,
    **props,
) -> rx.Component:
    """The surface everything sits on — the kit's *card* material (`.q-card`,
    assets/qualify.css, "Liquid Glass: Radix skin"): a translucent relief inside the
    opaque page panel, the card radius and the resting elevation of the system, no
    backdrop blur (plan D5). ``interactive=True`` adds the hover lift — only for a card
    that actually does something when clicked, so elevation keeps meaning 'this
    responds to you' rather than being decoration. Inline ``props`` still win over the
    class (`skeleton_card` passes ``background="transparent"``)."""
    style: dict = {
        "padding": padding,
        "width": "100%",
        "class_name": "q-card q-lift" if interactive else "q-card",
    }
    if interactive:
        style["cursor"] = "pointer"
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


def mono(text: rx.Var | str, size: str = "2", **props) -> rx.Component:
    """Inline identifier text (``@handle``, ids, keys) in the mono face. ``props`` are
    layout only (e.g. ``overflow_wrap="anywhere"`` for a handle inside a narrow card)."""
    return rx.text(text, size=size, class_name="q-mono", **props)


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


def removable_pill(
    label: str | rx.Var | rx.Component,
    on_remove: Any,
    *,
    icon: str | None = None,
    leading: rx.Component | None = None,
    suggested: bool = False,
    remove_label: str = "Quitar",
    size: str = "2",
) -> rx.Component:
    """A value the operator curates — a hashtag, a banned word, an uploaded file — with
    its ✕. ``surface`` gray like a `tag` (it is a value, not a state); ``suggested=True``
    turns it ``soft`` accent for a value the product proposed and the operator has not
    typed. Never a tone: a pill that could be removed is not a verdict. ``icon`` is a
    fixed lucide icon; ``leading`` is any component (e.g. a conditional warning)."""
    children: list = []
    if icon:
        children.append(rx.icon(icon, size=12))
    if leading is not None:
        children.append(leading)
    children.append(
        rx.text(label, overflow="hidden", text_overflow="ellipsis", white_space="nowrap")
    )
    children.append(
        rx.el.button(
            rx.icon("x", size=12),
            on_click=on_remove,
            type="button",
            aria_label=remove_label,
            display="flex",
            align_items="center",
            background="transparent",
            border="none",
            padding="0",
            color="inherit",
            cursor="pointer",
            flex_shrink="0",
        )
    )
    look = {"variant": "soft"} if suggested else {"variant": "surface", "color_scheme": "gray"}
    return rx.badge(
        *children,
        size=size,
        radius="full",
        gap="1",
        align_items="center",
        max_width="100%",
        **look,
    )


def pill_editor(
    items: rx.Var[list[str]],
    *,
    draft: rx.Var[str],
    on_draft_change: Any,
    on_add: Any,
    on_remove: Callable[[rx.Var[int]], Any],
    placeholder: str,
    add_label: str = "Agregar",
    empty_hint: str = "",
    show_items: bool = True,
) -> rx.Component:
    """A list the operator builds one value at a time: the values as `removable_pill`s,
    and an input that adds one on Enter, on "+" or on leaving it (so a typed value is
    never lost by clicking elsewhere). ``on_remove`` gets the pill's index.
    ``show_items=False`` leaves only the input, for a flow that lists and edits the
    values on a later screen (the Brand Kit's ¿Todo correcto?)."""
    pills = rx.flex(
        rx.foreach(items, lambda item, index: removable_pill(item, on_remove(index))),
        wrap="wrap",
        gap="2",
        width="100%",
    )
    listed = rx.cond(
        items.length() > 0,
        pills,
        rx.text(empty_hint, size="1", color=T.TEXT_FAINT) if empty_hint else rx.fragment(),
    )
    return rx.vstack(
        listed if show_items else rx.fragment(),
        rx.form(
            rx.hstack(
                rx.input(
                    value=draft,
                    on_change=on_draft_change,
                    on_blur=on_add,
                    placeholder=placeholder,
                    width="100%",
                    size="2",
                ),
                rx.icon_button(
                    rx.icon("plus", size=T.ICON_SM),
                    type="submit",
                    variant="soft",
                    color_scheme="gray",
                    size="2",
                    aria_label=add_label,
                ),
                spacing="2",
                width="100%",
            ),
            on_submit=on_add,
            reset_on_submit=False,
            width="100%",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def sentiment_badge(sentiment: rx.Var[str]) -> rx.Component:
    """Sentiment is a state: positive=ok, negative=error, anything else neutral.

    Matches two vocabularies that coexist in the product: the Mentions dashboard's own
    ``"positive"``/``"negative"`` values, and the QUA-21/QUA-92 pipeline's ``POS``/
    ``NEG``/``NEU`` — the literal values ``comment_sentiment_results.label``'s CHECK
    constraint allows. ``""`` matches explicitly to "Sin analizar": the QUA-92 state for
    a comment with no ``comment_sentiment_results`` row yet under the current model
    version, which must never render as NEU (docs/design-system.md §6.1/§7.2 — a comment
    pending analysis and one classified neutral are different facts)."""
    return rx.match(
        sentiment,
        ("positive", signal_pill("Positiva", "ok")),
        ("negative", signal_pill("Negativa", "error")),
        ("POS", signal_pill("Positiva", "ok")),
        ("NEG", signal_pill("Negativa", "error")),
        ("NEU", signal_pill("Neutra", "neutral")),
        ("", signal_pill("Sin analizar", "neutral")),
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


# ---------------------------------------------------------------------------------------
# Waiting. Two primitives, one rule (founder, 2026-10-08, docs/design-system.md §5.4):
#
#   * **skeleton = content loading.** Something is being READ and will appear in this
#     place: a list, a detail, a catalogue, a calendar. The placeholder has the shape of
#     what is coming. ALWAYS a skeleton — never a spinner — and always through
#     `skeleton_card`/`skeleton_rows`, never `rx.skeleton` from a page.
#   * **spinner = work in progress.** Something is being DONE: scraping, generating,
#     syncing, publishing, uploading, cloning a voice. A spinner next to the sentence
#     that says what is happening. ALWAYS `loading_spinner`, never `rx.spinner`.
#
# `Qualify/test_design_system_guard.py` fails the build on either `rx.spinner(` or
# `rx.skeleton(` outside this package.
# ---------------------------------------------------------------------------------------


def skeleton_card(lines: int = 3) -> rx.Component:
    """Content-loading placeholder shaped like ``card``: a title line and as many body
    lines as the content will have. The shimmer is the kit's (`.rt-Skeleton` skin in
    `assets/qualify.css`)."""
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


def skeleton_rows(
    rows: int = 3, height: str = "2.5rem", width: str = "100%", radius: str | None = None
) -> rx.Component:
    """Content-loading placeholder for a table, a list, a grid of tiles, a media
    block: ``rows`` blocks of ``height`` × ``width``. ``radius`` defaults to the control
    radius; pass ``T.RADIUS_CARD`` for a card-sized block, ``"9999px"`` for an avatar.
    One row with a height is how a page draws a single big block (a preview, a calendar)."""
    return rx.vstack(
        *[
            rx.skeleton(
                rx.box(height=height, width=width, border_radius=radius or T.RADIUS_CONTROL)
            )
            for _ in range(rows)
        ],
        spacing="2",
        width=width,
        aria_busy="true",
    )


#: `loading_spinner`'s one real variant — size. There is no light/dark variant to
#: pick: the ring (`.q-spinner` in `assets/qualify.css`) is the kit's — a quiet track
#: in the gray scale and the accent on top. size -> (diameter, ring track).
_SPINNER_SIZES: dict[str, tuple[str, str]] = {
    "sm": ("1.25rem", "2px"),  # inline, next to the sentence that says what is happening
    "md": ("2.25rem", "3px"),  # a standalone wait (default)
    "lg": ("3.5rem", "4px"),  # a full-panel wait — e.g. the Brand Kit wizard's own
}


def loading_spinner(size: str = "md") -> rx.Component:
    """Work in progress — scraping, generating, syncing, publishing. The kit's ring
    (`.q-spinner`), never Radix's own `rx.spinner`, and never for content that is merely
    loading (that is a skeleton, see the rule above). Inside a button's busy state too:
    `rx.cond(busy, loading_spinner("sm"), rx.icon(...))` keeps the icon slot."""
    diameter, track = _SPINNER_SIZES.get(size, _SPINNER_SIZES["md"])
    return rx.box(
        class_name="q-spinner",
        width=diameter,
        height=diameter,
        min_width=diameter,
        min_height=diameter,
        style={"--q-spinner-track": track},
        role="status",
        aria_label="Cargando",
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


def progress_step_row(row: rx.Var[dict[str, str]]) -> rx.Component:
    """One stage of a `progress_panel` (`{"title", "status"}`, status `done`, `running`
    or `pending`) as the comment over its bar: only the running stage shows, and it
    fades in each time the stage changes (§ request 2026-10-02: the comments go above
    the bar, with no spinning circle next to them)."""
    return rx.cond(
        row["status"] == "running",
        rx.text(
            row["title"],
            size="2",
            weight="medium",
            color=T.TEXT_STRONG,
            text_align="center",
            class_name="q-progress-comment",
        ),
    )


def progress_panel(
    title: str | rx.Var,
    detail: str | rx.Var = "",
    *,
    value: rx.Var[int] | int | None = None,
    steps: rx.Var[list[dict[str, str]]] | None = None,
    creep_seconds: int = 30,
) -> rx.Component:
    """A blocking wait with a progress bar (§ request 2026-10-01): voice analysis,
    referentes search, hashtag suggestions. With a `value` (0-100) the bar shows real
    progress; without one — a single call that reports none — it creeps towards ~90%
    over `creep_seconds` and the screen goes away when the work ends. A light sweep
    over the bar says it is alive either way (`assets/qualify.css`, "Progress panel").
    `steps` are the stages: the running one is the comment right above the bar
    (`progress_step_row`). The panel fades in when the view switches to it, and it is
    the Brand Kit's one loader (§ request 2026-10-02)."""
    if value is None:
        fill = rx.box(
            class_name="q-progress-fill q-progress-creep",
            style={"--q-creep": f"{creep_seconds}s"},
        )
        percent = rx.fragment()
    else:
        width = (value.to_string() + "%") if isinstance(value, rx.Var) else f"{value}%"
        fill = rx.box(class_name="q-progress-fill", width=width)
        percent = rx.text(value, "%", size="1", color=T.TEXT_MUTED, class_name="q-nums")
    return rx.vstack(
        rx.text(title, size="3", weight="medium", text_align="center"),
        *([rx.text(detail, size="2", color=T.TEXT_MUTED, text_align="center")] if detail else []),
        *(
            # min height = one line, so the bar does not jump between two stages
            [
                rx.box(
                    rx.foreach(steps, progress_step_row), min_height="1.25rem", padding_top="0.5rem"
                )
            ]
            if steps is not None
            else []
        ),
        rx.box(
            fill,
            class_name="q-progress-track",
            role="progressbar",
            aria_label=title if isinstance(title, str) else "Progreso",
            width="100%",
            max_width="26rem",
        ),
        percent,
        spacing="3",
        align="center",
        width="100%",
        padding="2.5rem 0",
        class_name="q-progress-panel",
    )


# ---------------------------------------------------------------------------------------
# Overlays and multi-step flows (QUA-118)
# ---------------------------------------------------------------------------------------


def drawer(
    *children: rx.Component,
    open: rx.Var[bool] | bool,
    on_open_change: Any,
    title: str | rx.Var | rx.Component,
    description: str | rx.Var | None = None,
    footer: rx.Component | None = None,
    width: str = "32rem",
    icon: str | None = None,
) -> rx.Component:
    """A panel that slides in from the right edge and stays there while the operator
    works through something longer than a dialog — the Planificador's assign flow.
    Built on Radix's dialog, so Esc, the backdrop click, the focus trap and the ARIA
    wiring come for free; ``.q-drawer`` (assets/qualify.css) only moves the content to
    the edge: fixed width on a desktop, the full viewport on a phone. The body scrolls;
    ``title`` and ``footer`` stay put. One drawer at a time, never nested. ``icon`` puts
    an accent glyph before the title and sets it as a header (with ``.q-drawer-*``)."""
    body = rx.box(
        *children,
        class_name="q-drawer-body",
        flex="1",
        min_height="0",
        overflow_y="auto",
        width="100%",
    )
    head = rx.vstack(
        rx.hstack(
            rx.dialog.title(
                rx.hstack(
                    rx.box(rx.icon(icon, size=18), class_name="q-drawer-glyph"),
                    rx.text(title, class_name="q-drawer-title-text"),
                    class_name="q-drawer-title",
                    spacing="0",
                )
                if icon is not None
                else title,
                margin="0",
                size="5",
                as_child=icon is not None or not isinstance(title, (str, rx.Var)),
            ),
            rx.spacer(),
            rx.dialog.close(
                rx.icon_button(
                    rx.icon("x", size=T.ICON_MD),
                    variant="ghost",
                    color_scheme="gray",
                    size="2",
                    aria_label="Cerrar",
                ),
            ),
            align="center",
            width="100%",
        ),
        *(
            [rx.dialog.description(description, size="2", color=T.TEXT_MUTED, margin="0")]
            if description is not None
            else []
        ),
        spacing="1",
        width="100%",
        class_name="q-drawer-head",
    )
    parts: list[rx.Component] = [head, body]
    if footer is not None:
        parts.append(rx.box(footer, class_name="q-drawer-foot", width="100%"))
    return rx.dialog.root(
        rx.dialog.content(
            rx.flex(*parts, direction="column", height="100%", width="100%", gap="0"),
            class_name="q-drawer",
            style={"--q-drawer-w": width},
        ),
        open=open,
        on_open_change=on_open_change,
    )


def stepper(
    labels: list[str],
    *,
    current: rx.Var[int] | int,
    completed: rx.Var[list[bool]],
    on_select: Callable[[int], Any] | None = None,
    icons: list[str] | None = None,
) -> rx.Component:
    """The steps of a flow, in order: a filled check for a step already completed, the
    number for the rest — or, with ``icons``, one glyph per step instead of a number
    (the Planificador's drawer: steps read by picture and word) — the current one
    highlighted. When ``on_select`` is given, a
    step is clickable once completed (back to fix something) or once the step before it
    is — the last step is never "completed" (confirming is the act), yet it must be a
    click away again after going back. A step further ahead never is, so nothing can be
    confirmed with a step missing. Numbers are a fallback, not the point: the label is
    what reads. Static labels, dynamic state."""
    items: list[rx.Component] = []
    for index, label in enumerate(labels):
        is_current = current == index
        is_done = completed[index]
        reachable = is_done | is_current
        if index:
            reachable = reachable | completed[index - 1]
        base = "q-step-dot q-step-dot--icon" if icons else "q-step-dot"
        dot = rx.box(
            rx.cond(
                is_done,
                rx.icon("check", size=12, stroke_width=3),
                rx.icon(icons[index], size=15)
                if icons
                else rx.text(str(index + 1), size="1", weight="bold", line_height="1"),
            ),
            class_name=rx.cond(
                is_done,
                f"{base} q-step-dot--done",
                rx.cond(is_current, f"{base} q-step-dot--current", base),
            ),
            aria_hidden="true",
        )
        text = rx.text(
            label,
            size="1",
            weight=rx.cond(is_current, "bold", "medium"),
            color=rx.cond(is_current | is_done, T.TEXT_STRONG, T.TEXT_MUTED),
            class_name="q-step-label",
        )
        step = rx.el.button(
            dot,
            text,
            type="button",
            title=label,
            class_name=rx.cond(is_current, "q-step q-step--current", "q-step"),
            aria_current=rx.cond(is_current, "step", "false"),
            disabled=~reachable if on_select is not None else True,
            on_click=on_select(index) if on_select is not None else None,
        )
        if index:
            items.append(
                rx.box(
                    class_name=rx.cond(
                        is_done | is_current, "q-step-line q-step-line--on", "q-step-line"
                    ),
                    aria_hidden="true",
                )
            )
        items.append(step)
    return rx.box(
        *items,
        class_name="q-stepper",
        role="list",
        aria_label="Pasos",
        width="100%",
    )
