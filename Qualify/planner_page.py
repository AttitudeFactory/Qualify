"""`/planner` — Planificador (QUA-108): the editorial calendar.

Two views of the same week, switched from the header (see `planner_vm.py` for the
reasoning): **Calendario** — seven day columns on a real hour axis — and **Lista** —
events grouped by day. A "Sin programar" panel (toggled from the toolbar, closed by
default so the calendar gets the full width) holds the POSTs waiting to be planned.
Short dialogs cover assign / reschedule / detail / cancel. On a phone the list is always
used: a seven-column hour grid does not fit a phone width.

What the screen deliberately does not have: a publish button. Planning is not
publishing — `/publish` publishes now, QUA-111 will execute planned events.

Built only from the design system (`ui/`): `app_shell` + `page_header` + `page_body`,
states by tone through `signal_pill`, identity through `platform_badge`, colours through
`T.*`, so light and dark mode need no rules of their own.
"""

from __future__ import annotations

import reflex as rx
from qualify_api.planner.recurrence import SERIES_CAP

from .planner_state import SCROLL_ID, PlannerState
from .planner_vm import (
    ASSIGN_STEPS,
    AUTO_PUBLISH_ACTIVE,
    AUTO_PUBLISH_NO_CONNECTION,
    EXPIRED_NOTE,
    REPEAT_BY_COUNT,
    REPEAT_BY_UNTIL,
    STEP_ACCOUNTS,
    STEP_POST,
    STEP_PREVIEW,
    STEP_WHEN,
    TAG_COLORS,
    VIEW_CALENDAR,
    VIEW_LIST,
)
from .r2_media import BACKEND_BASE
from .ui import (
    app_shell,
    callout,
    card,
    drawer,
    page_body,
    page_header,
    platform_badge,
    signal_pill,
    stepper,
    tag,
)
from .ui import tokens as T

_TONES = ("ok", "warn", "error", "info", "neutral", "accent")
_GRID_COLUMNS = "4.5rem repeat(7, minmax(0, 1fr))"
# Lucide ships no brand logos, so each platform gets a generic glyph in its identity
# colour (T.PLATFORM_SCALE); the list view and the detail spell the name out.
_PLATFORM_ICON = {"instagram": "camera", "facebook": "users", "tiktok": "music-2"}
_CLAMP_2 = {
    "display": "-webkit-box",
    "-webkit-line-clamp": "2",
    "-webkit-box-orient": "vertical",
    "overflow": "hidden",
}
_ONE_LINE = {"overflow": "hidden", "text_overflow": "ellipsis", "white_space": "nowrap"}


def _pill(label: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """`signal_pill` for a tone that is only known at runtime."""
    return rx.match(
        tone,
        *[(t, signal_pill(label, t)) for t in _TONES],
        signal_pill(label, "neutral"),
    )


def _platform_icon(platform: rx.Var[str]) -> rx.Component:
    return rx.match(
        platform,
        *[
            (key, rx.icon(icon, size=T.ICON_SM, color=rx.color(T.platform_scale(key), 9)))
            for key, icon in _PLATFORM_ICON.items()
        ],
        rx.icon("globe", size=T.ICON_SM, color=T.TEXT_MUTED),
    )


def _card_media(thumbnail_url: rx.Var[str], video_url: rx.Var[str], size: str) -> rx.Component:
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
        _thumbnail(thumbnail_url, size),
    )


def _thumbnail(url: rx.Var[str], size: str) -> rx.Component:
    """`url` is an http(s) URL or a local upload-store key (`PostSummary.thumbnail_url`);
    a key is resolved the way the creative screens do, with `rx.get_upload_url`."""
    return rx.cond(
        url != "",
        rx.image(
            src=rx.cond(url.startswith("http"), url, rx.get_upload_url(url)),
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


def _tag_badge(tag, *, solid: bool = False, closable: bool = False) -> rx.Component:
    """A planning tag in its palette colour (identity, like a platform: never a state).
    `closable` adds a trailing × so it reads as removable."""
    content = [tag.name, rx.icon("x", size=11)] if closable else [tag.name]
    return rx.match(
        tag.color,
        *[
            (
                c,
                rx.badge(
                    *content,
                    color_scheme=c,
                    variant="solid" if solid else "soft",
                    radius="full",
                    size="1",
                ),
            )
            for c in TAG_COLORS
        ],
        rx.badge(tag.name, color_scheme="gray", variant="soft", radius="full", size="1"),
    )


def _tag_badge_plain(tag) -> rx.Component:
    """One-parameter form for `rx.foreach`, which counts the render function's params."""
    return _tag_badge(tag)


def _tag_dot(tag) -> rx.Component:
    return rx.match(
        tag.color,
        *[
            (
                c,
                rx.box(
                    width="7px",
                    height="7px",
                    border_radius="999px",
                    background=rx.color(c, 9),
                    title=tag.name,
                ),
            )
            for c in TAG_COLORS
        ],
        rx.box(width="7px", height="7px", border_radius="999px", background=rx.color("gray", 9)),
    )


def _accent_edge(event) -> rx.Var:
    return rx.cond(
        event.overdue,
        f"3px solid {rx.color('amber', 9)}",
        f"3px solid {rx.color('accent', 8)}",
    )


# ---------------------------------------------------------------------------
# Event actions (⋯ menu) — shared by both views


def _card_menu(event) -> rx.Component:
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.icon_button(
                rx.icon("ellipsis", size=T.ICON_SM),
                size="1",
                variant="ghost",
                color_scheme="gray",
                aria_label="Acciones del evento",
            ),
        ),
        rx.dropdown_menu.content(
            rx.dropdown_menu.item("Ver detalle", on_click=PlannerState.open_detail(event.event_id)),
            rx.cond(
                event.detail_href != "",
                rx.dropdown_menu.item("Ver POST", on_click=rx.redirect(event.detail_href)),
            ),
            rx.cond(
                event.can_modify,
                rx.fragment(
                    rx.dropdown_menu.item(
                        "Reprogramar", on_click=PlannerState.open_reschedule(event.event_id)
                    ),
                    rx.dropdown_menu.separator(),
                    rx.dropdown_menu.item(
                        "Cancelar publicación",
                        color_scheme="red",
                        on_click=PlannerState.ask_cancel(event.event_id),
                    ),
                ),
            ),
            size="1",
        ),
    )


# ---------------------------------------------------------------------------
# Calendario — hour axis × seven days, compact


def _chip_edge(event) -> rx.Var:
    """The chip's left edge carries the state at a glance: accent approved, amber pending
    or overdue, tomato rejected, gray cancelled/unknown."""
    return rx.cond(
        event.muted,
        rx.color("gray", 8),
        rx.cond(
            event.overdue,
            rx.color("amber", 9),
            rx.match(
                event.approval_tone,
                ("ok", rx.color("accent", 9)),
                ("warn", rx.color("amber", 9)),
                ("error", rx.color("tomato", 9)),
                rx.color("gray", 8),
            ),
        ),
    )


def _calendar_chip(event) -> rx.Component:
    """A compact event chip: platform + time on one line, the title under it. The rest
    (approval wording, caption, actions) lives in the detail dialog, one click away."""
    return rx.box(
        rx.hstack(
            _card_media(event.thumbnail_url, event.video_url, "1.6rem"),
            rx.vstack(
                rx.hstack(
                    _platform_icon(event.platform),
                    rx.text(event.time_label, size="1", weight="bold", class_name="q-nums"),
                    # MP-11: the output's word — the same POST appears up to three times.
                    rx.cond(event.output_label != "", tag(event.output_label)),
                    rx.cond(
                        event.overdue | (event.readiness_note != ""),
                        rx.icon("triangle-alert", size=12, color=rx.color("amber", 10)),
                    ),
                    rx.spacer(),
                    align="center",
                    spacing="1",
                    width="100%",
                ),
                rx.text(event.title, size="1", color=T.TEXT_MUTED, style=_ONE_LINE, width="100%"),
                rx.cond(
                    event.tags.length() > 0,
                    rx.hstack(rx.foreach(event.tags, _tag_dot), spacing="1", padding_top="2px"),
                ),
                spacing="0",
                min_width="0",
                flex="1",
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        # stop_propagation: the cell behind the chip opens "Nueva publicación" on click.
        on_click=PlannerState.open_detail(event.event_id).stop_propagation,
        cursor="pointer",
        role="button",
        aria_label=event.time_label
        + " · "
        + event.title
        + rx.cond(event.output_label != "", " · " + event.output_label, "")
        + " · "
        + event.approval_label,
        title=event.title
        + rx.cond(event.output_label != "", " · " + event.output_label, "")
        + " — "
        + event.approval_label
        + " · "
        + event.status_label
        + rx.cond(event.readiness_note != "", " · " + event.readiness_note, ""),
        padding="0.3rem 0.4rem",
        border=T.BORDER,
        border_left="3px solid",
        border_left_color=_chip_edge(event),
        border_radius=T.RADIUS_CONTROL,
        background=T.SURFACE_BG,
        background_color=rx.cond(event.muted, rx.color("gray", 2), T.SURFACE_BG),
        color=rx.cond(event.muted, T.TEXT_MUTED, "inherit"),
        text_decoration=rx.cond(event.muted, "line-through", "none"),
        width="100%",
        class_name="q-lift",
    )


def _day_header(day) -> rx.Component:
    return rx.center(
        rx.hstack(
            rx.text(
                day.weekday,
                size="2",
                color=rx.cond(day.is_today, rx.color("accent", 11), T.TEXT_MUTED),
                weight=rx.cond(day.is_today, "bold", "regular"),
            ),
            rx.text(
                day.day_number,
                size="2",
                weight="bold",
                class_name="q-nums",
                color=rx.cond(
                    day.is_today,
                    rx.color("accent", 11),
                    rx.cond(day.is_past, T.TEXT_MUTED, T.TEXT_STRONG),
                ),
            ),
            spacing="2",
            align="center",
        ),
        padding="0.6rem 0.25rem",
        border_left=T.BORDER,
        border_bottom=rx.cond(day.is_today, f"2px solid {rx.color('accent', 9)}", T.BORDER),
        background=T.SURFACE_BG,
        position="sticky",
        top="0",
        z_index="2",
    )


_HAIRLINE = f"1px solid {rx.color('gray', 4)}"


def _hour_cell(cell) -> rx.Component:
    """A clickable slot: a click on its empty area opens "Nueva publicación" for this
    day and hour. A not-past slot shows a "+" on hover (`q-planner-slot*` in
    `assets/qualify.css`) so it reads as "you can add here": in the corner when the slot
    is empty, under the chips when it has posts. Past days get neither."""
    return rx.vstack(
        rx.cond(
            ~cell.is_past & (cell.cards.length() == 0),
            rx.el.span(rx.icon("plus", size=T.ICON_SM), class_name="q-planner-slot-plus"),
        ),
        rx.foreach(cell.cards, _calendar_chip),
        # A slot that already has posts gets its "+" under the last chip instead of in
        # the corner, so it never covers a chip. Its space is always reserved, so the
        # row does not jump when it fades in.
        rx.cond(
            ~cell.is_past & (cell.cards.length() > 0),
            rx.el.span(
                rx.icon("plus", size=12),
                class_name="q-planner-slot-plus q-planner-slot-plus--below",
            ),
        ),
        on_click=PlannerState.open_assign_for_slot(cell.day_iso, cell.hour),
        title=rx.cond(cell.is_past, "", "Nueva publicación a esta hora"),
        cursor=rx.cond(cell.is_past, "default", "pointer"),
        class_name="q-planner-slot",
        position="relative",
        spacing="1",
        padding="0.25rem",
        min_height="2.75rem",
        border_top=_HAIRLINE,
        border_left=_HAIRLINE,
        background=rx.cond(cell.is_today, rx.color("accent", 2), "transparent"),
        width="100%",
        min_width="0",
    )


def _hour_row(row) -> rx.Component:
    return rx.fragment(
        rx.box(
            rx.text(row.label, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            id="q-hour-" + row.key.to_string(),
            padding="0.25rem 0.5rem 0 0",
            text_align="right",
            border_top=_HAIRLINE,
            white_space="nowrap",
        ),
        rx.foreach(row.cells, _hour_cell),
    )


def _calendar() -> rx.Component:
    return rx.box(
        rx.grid(
            rx.box(
                border_bottom=T.BORDER,
                background=T.SURFACE_BG,
                position="sticky",
                top="0",
                z_index="2",
            ),
            rx.foreach(PlannerState.days, _day_header),
            rx.foreach(PlannerState.rows, _hour_row),
            # Radix's own `columns` prop, not a css `grid_template_columns`: Radix's base
            # `.rt-Grid { grid-template-columns: minmax(0, 1fr) }` can win the cascade over
            # an emotion class of equal specificity, collapsing the week to one column.
            columns=_GRID_COLUMNS,
            width="100%",
        ),
        border=T.BORDER,
        border_radius=T.RADIUS_CARD,
        background=T.SURFACE_BG,
        # The grid scrolls inside its own box (the sticky day headers stick to it), so
        # the whole week fits the screen the way a calendar does, not a tall page.
        id=SCROLL_ID,
        max_height="calc(100vh - 15.5rem)",
        min_height="22rem",
        overflow_y="auto",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Lista — grouped by day


def _readiness_note(note) -> rx.Component:
    """The evaluator's reason, under an approved-but-not-ready POST (card, list, panel)."""
    return rx.cond(
        note != "",
        rx.hstack(
            rx.icon("triangle-alert", size=12, color=rx.color("amber", 10), flex_shrink="0"),
            rx.text(note, size="1", color=rx.color("amber", 11)),
            spacing="1",
            align="center",
        ),
    )


def _list_item(event) -> rx.Component:
    return rx.hstack(
        rx.text(
            event.time_label,
            size="4",
            weight="medium",
            class_name="q-nums q-plist-time",
            min_width="4.5rem",
            padding_top="0.9rem",
        ),
        rx.hstack(
            rx.hstack(
                _card_media(event.thumbnail_url, event.video_url, "3.5rem"),
                rx.vstack(
                    rx.text(event.title, size="3", weight="bold", style=_ONE_LINE, width="100%"),
                    rx.cond(
                        event.caption_excerpt != "",
                        rx.text(
                            event.caption_excerpt,
                            size="2",
                            color=T.TEXT_MUTED,
                            style=_ONE_LINE,
                            width="100%",
                        ),
                    ),
                    rx.hstack(
                        platform_badge(event.platform),
                        rx.text(event.account_label, size="1", color=T.TEXT_MUTED),
                        tag(event.category_label),
                        rx.cond(event.output_label != "", tag(event.output_label)),
                        rx.foreach(event.tags, _tag_badge_plain),
                        align="center",
                        spacing="2",
                        wrap="wrap",
                    ),
                    _readiness_note(event.readiness_note),
                    spacing="1",
                    min_width="0",
                    flex="1",
                ),
                rx.flex(
                    _pill(event.approval_label, event.approval_tone),
                    _pill(event.status_label, event.status_tone),
                    direction="column",
                    align="end",
                    gap="0.3rem",
                    class_name="q-plist-pills",
                ),
                on_click=PlannerState.open_detail(event.event_id),
                cursor="pointer",
                role="button",
                aria_label=event.title,
                spacing="3",
                align="center",
                flex="1",
                min_width="0",
                class_name="q-plist-body",
            ),
            _card_menu(event),
            padding="0.75rem 0.9rem",
            border=T.BORDER,
            border_left=_accent_edge(event),
            border_radius=T.RADIUS_CARD,
            background=T.SURFACE_BG,
            box_shadow=T.ELEV_ISLAND,
            opacity=rx.cond(event.muted, "0.55", "1"),
            align="center",
            spacing="2",
            flex="1",
            min_width="0",
            class_name="q-lift",
        ),
        align="start",
        spacing="3",
        width="100%",
        class_name="q-plist-item",
    )


def _list_day(day) -> rx.Component:
    return rx.cond(
        day.count > 0,
        rx.vstack(
            rx.hstack(
                rx.heading(
                    day.title,
                    size="4",
                    as_="h2",
                    color=rx.cond(day.is_today, rx.color("accent", 11), T.TEXT_STRONG),
                ),
                rx.spacer(),
                rx.cond(
                    ~day.is_past,
                    rx.button(
                        rx.icon("plus", size=T.ICON_SM),
                        "Asignar",
                        size="1",
                        variant="ghost",
                        on_click=PlannerState.open_assign_for_day(day.iso),
                    ),
                ),
                align="center",
                width="100%",
            ),
            rx.foreach(day.cards, _list_item),
            spacing="2",
            width="100%",
            padding_bottom="0.75rem",
        ),
    )


def _list() -> rx.Component:
    return rx.vstack(
        rx.cond(
            PlannerState.total_events == 0,
            rx.center(
                rx.vstack(
                    rx.icon("calendar-days", size=T.ICON_LG, color=T.TEXT_FAINT),
                    rx.heading("Nada planificado esta semana", size="4", as_="h2"),
                    rx.text(
                        "Asigna un POST a un día, una hora y una cuenta.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    align="center",
                    spacing="2",
                ),
                padding="3rem 1rem",
                width="100%",
            ),
        ),
        rx.foreach(PlannerState.days, _list_day),
        spacing="3",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Sin programar


def _post_option(post) -> rx.Component:
    return card(
        rx.hstack(
            _thumbnail(post.thumbnail_url, "2.75rem"),
            rx.vstack(
                rx.text(post.title, size="2", weight="medium", style=_CLAMP_2),
                rx.flex(
                    tag(post.category_label),
                    _pill(post.approval_label, post.approval_tone),
                    wrap="wrap",
                    gap="0.25rem",
                ),
                # MP-11: one chip per template output with its planning state; the
                # package stays one card and is taken apart when assigning.
                rx.cond(
                    post.has_outputs,
                    rx.flex(
                        rx.foreach(post.outputs, _output_chip),
                        wrap="wrap",
                        gap="0.25rem",
                    ),
                ),
                _readiness_note(post.readiness_note),
                spacing="1",
                min_width="0",
                flex="1",
            ),
            spacing="2",
            align="start",
            width="100%",
        ),
        rx.hstack(
            rx.cond(
                post.detail_href != "",
                rx.link(rx.text("Ver POST", size="1"), href=post.detail_href),
            ),
            rx.spacer(),
            rx.button(
                rx.icon("calendar-plus", size=T.ICON_SM),
                "Asignar",
                size="1",
                variant="soft",
                on_click=PlannerState.open_assign_for_post(post.post_id),
                disabled=~PlannerState.has_connections,
            ),
            width="100%",
            align="center",
            margin_top="0.5rem",
        ),
        padding="0.6rem",
    )


def _unscheduled_panel() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading("Sin programar", size="3", as_="h2"),
            rx.badge(
                PlannerState.unscheduled_count,
                variant="soft",
                color_scheme="gray",
                radius="full",
                class_name="q-nums",
            ),
            rx.spacer(),
            rx.icon_button(
                rx.icon("x", size=T.ICON_SM),
                size="1",
                variant="ghost",
                color_scheme="gray",
                aria_label="Cerrar panel",
                on_click=PlannerState.toggle_unscheduled,
            ),
            align="center",
            spacing="2",
            width="100%",
        ),
        rx.text(
            "POSTs listos para planificar. Asígnalos a un día, una hora y una cuenta.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.cond(
            PlannerState.unscheduled_count > 0,
            rx.vstack(
                rx.foreach(PlannerState.unscheduled, _post_option),
                spacing="2",
                width="100%",
            ),
            rx.vstack(
                rx.text("No hay POSTs pendientes de planificar.", size="2", color=T.TEXT_MUTED),
                rx.link(rx.button("Crear pieza", size="1", variant="soft"), href="/create"),
                spacing="2",
                padding="1rem 0",
            ),
        ),
        spacing="2",
        width=rx.breakpoints(initial="100%", lg="20rem"),
        min_width=rx.breakpoints(initial="0", lg="20rem"),
        padding="0.9rem",
        border=T.BORDER,
        border_radius=T.RADIUS_CARD,
        background=T.CARD_BG,
        align_items="start",
        position=rx.breakpoints(initial="static", lg="sticky"),
        top="0",
    )


# ---------------------------------------------------------------------------
# Header + toolbar


def _view_toggle() -> rx.Component:
    # Plain div for the responsive switch: Radix's base classes can outrank an emotion
    # `display` set on its own components (see `_calendar`).
    return rx.el.div(
        rx.segmented_control.root(
            rx.segmented_control.item(
                rx.hstack(rx.icon("list", size=T.ICON_SM), "Lista", spacing="1", align="center"),
                value=VIEW_LIST,
            ),
            rx.segmented_control.item(
                rx.hstack(
                    rx.icon("calendar-days", size=T.ICON_SM),
                    "Calendario",
                    spacing="1",
                    align="center",
                ),
                value=VIEW_CALENDAR,
            ),
            value=PlannerState.view_mode,
            on_change=PlannerState.set_view_mode,
        ),
        class_name="q-planner-desktop",
    )


def _assign_button() -> rx.Component:
    return rx.button(
        rx.icon("plus", size=T.ICON_MD),
        "Nueva publicación",
        on_click=PlannerState.open_assign_blank,
        disabled=~PlannerState.has_connections,
    )


def _connection_filter() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(placeholder="Todas las cuentas", variant="ghost"),
        rx.select.content(
            rx.select.item("Todas las cuentas", value="all"),
            rx.foreach(
                PlannerState.connections,
                lambda c: rx.select.item(c.label, value=c.id),
            ),
        ),
        value=PlannerState.connection_filter,
        on_change=PlannerState.set_connection_filter,
    )


def _toolbar() -> rx.Component:
    return rx.flex(
        rx.hstack(
            rx.icon_button(
                rx.icon("chevron-left", size=T.ICON_MD),
                variant="ghost",
                color_scheme="gray",
                aria_label="Semana anterior",
                on_click=PlannerState.previous_week,
            ),
            rx.icon_button(
                rx.icon("chevron-right", size=T.ICON_MD),
                variant="ghost",
                color_scheme="gray",
                aria_label="Semana siguiente",
                on_click=PlannerState.next_week,
            ),
            rx.vstack(
                rx.heading(PlannerState.month_label, size="4", as_="h2"),
                rx.text(PlannerState.week_label, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                spacing="0",
            ),
            rx.button(
                "Hoy",
                size="1",
                variant=rx.cond(PlannerState.is_current_week, "soft", "outline"),
                color_scheme="gray",
                on_click=PlannerState.go_to_today,
            ),
            align="center",
            spacing="2",
        ),
        rx.spacer(),
        rx.hstack(
            rx.button(
                rx.icon("inbox", size=T.ICON_SM),
                "Sin programar",
                rx.badge(
                    PlannerState.unscheduled_count,
                    variant=rx.cond(PlannerState.unscheduled_count > 0, "solid", "soft"),
                    radius="full",
                    size="1",
                    class_name="q-nums",
                ),
                variant=rx.cond(PlannerState.show_unscheduled, "soft", "ghost"),
                color_scheme="gray",
                on_click=PlannerState.toggle_unscheduled,
            ),
            _connection_filter(),
            _tags_filter(),
            _timezone_picker(),
            align="center",
            spacing="3",
            wrap="wrap",
        ),
        align="center",
        gap="0.75rem",
        wrap="wrap",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Toolbar popovers: Etiquetas (filter) and zona horaria


def _search_box(value: rx.Var[str], on_change, placeholder: str) -> rx.Component:
    return rx.input(
        rx.input.slot(rx.icon("search", size=T.ICON_SM)),
        value=value,
        on_change=on_change,
        placeholder=placeholder,
        width="100%",
        auto_focus=True,
    )


def _tag_filter_row(tag) -> rx.Component:
    selected = PlannerState.tag_filter.contains(tag.id)
    return rx.hstack(
        rx.checkbox(checked=selected, size="1", pointer_events="none"),
        _tag_dot(tag),
        rx.text(tag.name, size="2", style=_ONE_LINE),
        rx.spacer(),
        rx.icon_button(
            rx.icon("trash-2", size=T.ICON_SM),
            size="1",
            variant="ghost",
            color_scheme="gray",
            aria_label="Eliminar etiqueta",
            title="Eliminar etiqueta",
            # stop_propagation: the row itself toggles the filter.
            on_click=PlannerState.ask_delete_tag(tag.id, tag.name).stop_propagation,
        ),
        on_click=PlannerState.toggle_tag_filter(tag.id),
        cursor="pointer",
        align="center",
        spacing="2",
        width="100%",
        padding="0.35rem 0.5rem",
        border_radius=T.RADIUS_CONTROL,
        _hover={"background": rx.color("gray", 3)},
    )


def _tags_filter() -> rx.Component:
    empty = rx.vstack(
        rx.center(
            rx.icon("tag", size=T.ICON_MD, color=rx.color("accent", 11)),
            width="2.75rem",
            height="2.75rem",
            border_radius="999px",
            background=rx.color("accent", 3),
        ),
        rx.text("Sin etiquetas", size="2", weight="bold"),
        rx.text(
            "Usa etiquetas para organizar tu planificación: escribe un nombre arriba para "
            "crear la primera.",
            size="1",
            color=T.TEXT_MUTED,
            text_align="center",
        ),
        align="center",
        spacing="2",
        padding="1rem 0.5rem",
    )
    return rx.popover.root(
        rx.popover.trigger(
            rx.button(
                rx.icon("tag", size=T.ICON_SM),
                "Etiquetas",
                rx.cond(
                    PlannerState.tag_filter_count > 0,
                    rx.badge(
                        PlannerState.tag_filter_count,
                        variant="solid",
                        radius="full",
                        size="1",
                        class_name="q-nums",
                    ),
                ),
                rx.icon("chevron-down", size=T.ICON_SM),
                variant=rx.cond(PlannerState.tag_filter_count > 0, "soft", "ghost"),
                color_scheme="gray",
            ),
        ),
        rx.popover.content(
            rx.vstack(
                _search_box(PlannerState.tag_query, PlannerState.set_tag_query, "Buscar etiquetas"),
                rx.cond(
                    PlannerState.can_create_tag,
                    rx.button(
                        rx.icon("plus", size=T.ICON_SM),
                        "Crear etiqueta «" + PlannerState.tag_query + "»",
                        variant="ghost",
                        size="2",
                        width="100%",
                        justify="start",
                        on_click=PlannerState.create_tag_from_filter,
                    ),
                ),
                rx.cond(
                    PlannerState.tags.length() == 0,
                    rx.cond(PlannerState.can_create_tag, rx.fragment(), empty),
                    rx.vstack(
                        rx.foreach(PlannerState.tag_results, _tag_filter_row),
                        spacing="0",
                        width="100%",
                        max_height="15rem",
                        overflow_y="auto",
                    ),
                ),
                rx.divider(),
                rx.hstack(
                    rx.button(
                        "Borrar selección",
                        variant="ghost",
                        color_scheme="gray",
                        size="1",
                        disabled=PlannerState.tag_filter_count == 0,
                        on_click=PlannerState.clear_tag_filter,
                    ),
                    rx.spacer(),
                    rx.text(
                        "Filtra las publicaciones con cualquiera de las marcadas.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    align="center",
                    width="100%",
                ),
                spacing="2",
                width="18rem",
            ),
            side="bottom",
            align="end",
        ),
    )


def _tz_row(option) -> rx.Component:
    selected = option.value == PlannerState.tz_name
    return rx.popover.close(
        rx.hstack(
            rx.box(
                rx.cond(selected, rx.icon("check", size=T.ICON_SM)),
                width="1rem",
            ),
            rx.text(
                option.city + rx.cond(option.country != "", ", " + option.country, ""),
                size="2",
                weight=rx.cond(selected, "bold", "regular"),
                style=_ONE_LINE,
            ),
            rx.text("(" + option.offset_label + ")", size="1", color=T.TEXT_MUTED, flex_shrink="0"),
            on_click=PlannerState.choose_tz(option.value),
            cursor="pointer",
            align="center",
            spacing="2",
            width="100%",
            padding="0.35rem 0.5rem",
            border_radius=T.RADIUS_CONTROL,
            background=rx.cond(selected, rx.color("gray", 3), "transparent"),
            _hover={"background": rx.color("gray", 3)},
        ),
    )


def _timezone_picker() -> rx.Component:
    return rx.popover.root(
        rx.popover.trigger(
            rx.button(
                rx.icon("globe", size=T.ICON_SM),
                PlannerState.tz_city_label,
                rx.icon("chevron-down", size=T.ICON_SM),
                variant="ghost",
                color_scheme="gray",
                title=PlannerState.tz_name,
            ),
        ),
        rx.popover.content(
            rx.vstack(
                _search_box(
                    PlannerState.tz_query,
                    PlannerState.set_tz_query,
                    "Buscar ciudad, país o zona horaria",
                ),
                rx.text("Sugerencias", size="1", color=T.TEXT_MUTED, weight="medium"),
                rx.foreach(PlannerState.tz_suggestions, _tz_row),
                rx.divider(),
                rx.text("Todas las zonas horarias", size="1", color=T.TEXT_MUTED, weight="medium"),
                rx.vstack(
                    rx.foreach(PlannerState.tz_results, _tz_row),
                    spacing="0",
                    width="100%",
                    max_height="16rem",
                    overflow_y="auto",
                ),
                rx.text(
                    "Cambia la zona en que ves y planificas la semana. La zona del negocio "
                    "no se modifica.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                width="20rem",
            ),
            side="bottom",
            align="end",
        ),
    )


def _form_tag_toggle(tag) -> rx.Component:
    selected = PlannerState.form_tag_ids.contains(tag.id)
    return rx.box(
        rx.cond(selected, _tag_badge(tag, solid=True, closable=True), _tag_badge(tag)),
        on_click=PlannerState.toggle_form_tag(tag.id),
        cursor="pointer",
        opacity=rx.cond(selected, "1", "0.7"),
    )


def _suggested_tag(suggestion) -> rx.Component:
    """A recommended tag not created yet: one click creates it and selects it."""
    return rx.match(
        suggestion.color,
        *[
            (
                c,
                rx.badge(
                    rx.icon("plus", size=12),
                    suggestion.name,
                    color_scheme=c,
                    variant="outline",
                    radius="full",
                    size="1",
                    cursor="pointer",
                    title=suggestion.hint,
                    on_click=PlannerState.add_suggested_tag(suggestion.name, suggestion.color),
                ),
            )
            for c in TAG_COLORS
        ],
        rx.fragment(),
    )


def _form_tags() -> rx.Component:
    return rx.vstack(
        rx.cond(
            PlannerState.tags.length() > 0,
            rx.flex(
                rx.foreach(PlannerState.tags, _form_tag_toggle),
                wrap="wrap",
                gap="0.35rem",
            ),
            rx.text("Aún no hay etiquetas. Son opcionales.", size="1", color=T.TEXT_MUTED),
        ),
        rx.cond(
            PlannerState.tag_suggestions.length() > 0,
            rx.vstack(
                rx.text("Sugeridas", size="1", color=T.TEXT_MUTED, weight="medium"),
                rx.flex(
                    rx.foreach(PlannerState.tag_suggestions, _suggested_tag),
                    wrap="wrap",
                    gap="0.35rem",
                ),
                spacing="1",
                width="100%",
            ),
        ),
        rx.hstack(
            rx.input(
                value=PlannerState.form_tag_query,
                on_change=PlannerState.set_form_tag_query,
                placeholder="Nueva etiqueta (p. ej. Campaña octubre)",
                size="1",
                flex="1",
                max_length=40,
            ),
            rx.button(
                rx.icon("plus", size=T.ICON_SM),
                "Crear",
                size="1",
                variant="soft",
                disabled=~PlannerState.form_can_create_tag,
                on_click=PlannerState.create_tag_in_form,
            ),
            width="100%",
            align="center",
        ),
        spacing="2",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Dialogs


def _field(label: str, control: rx.Component) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        spacing="1",
        width="100%",
    )


def _meridiem_option(label: str, value: str) -> rx.Component:
    selected = PlannerState.form_meridiem == value
    return rx.box(
        rx.text(label, size="1", weight=rx.cond(selected, "bold", "regular")),
        on_click=PlannerState.set_form_meridiem(value),
        role="button",
        aria_pressed=selected,
        cursor="pointer",
        text_align="center",
        padding="0 0.55rem",
        line_height="1rem",
        border_radius="calc(var(--q-radius-control) - 2px)",
        background=rx.cond(selected, rx.color("accent", 9), "transparent"),
        color=rx.cond(selected, "white", T.TEXT_MUTED),
        _hover={"background": rx.cond(selected, rx.color("accent", 10), rx.color("gray", 4))},
    )


def _meridiem_toggle() -> rx.Component:
    """a. m. over p. m.: one compact control the height of the selects beside it."""
    return rx.flex(
        _meridiem_option("a. m.", "am"),
        _meridiem_option("p. m.", "pm"),
        direction="column",
        gap="1px",
        padding="2px",
        border=T.BORDER,
        border_radius=T.RADIUS_CONTROL,
        background=T.SURFACE_BG,
        aria_label="a. m. o p. m.",
    )


def _time_picker() -> rx.Component:
    """Hour, minute and a. m./p. m. with the app's own controls. The native
    `<input type="time">` popup is drawn by the browser and cannot be styled."""
    return rx.hstack(
        rx.select.root(
            rx.select.trigger(aria_label="Hora", min_width="3.6rem"),
            rx.select.content(*[rx.select.item(str(h), value=str(h)) for h in range(1, 13)]),
            value=PlannerState.form_hour12,
            on_change=PlannerState.set_form_hour12,
        ),
        rx.text(":", weight="bold", color=T.TEXT_MUTED),
        rx.select.root(
            rx.select.trigger(aria_label="Minutos", min_width="3.6rem"),
            rx.select.content(
                rx.foreach(PlannerState.minute_options, lambda m: rx.select.item(m, value=m))
            ),
            value=PlannerState.form_minute,
            on_change=PlannerState.set_form_minute,
        ),
        _meridiem_toggle(),
        align="center",
        spacing="1",
        wrap="wrap",
    )


def _output_control() -> rx.Component:
    """«Salida» (MP-11): which template output this event publishes. One POST, up to
    three events — Reel 9:16, Feed 4:5, Historia 9:16. Shown only for a POST with outputs;
    a reschedule shows the output as text (a move never changes it)."""
    return rx.cond(
        PlannerState.form_is_reschedule,
        rx.text(PlannerState.form_output_label, size="2"),
        rx.vstack(
            rx.segmented_control.root(
                rx.foreach(
                    PlannerState.form_outputs,
                    lambda o: rx.segmented_control.item(o.label, value=o.port),
                ),
                value=PlannerState.form_output_port,
                on_change=PlannerState.set_form_output_port,
                width="100%",
            ),
            rx.text(
                "Cada salida se programa por separado: puedes asignar el mismo POST tres "
                "veces, una por salida.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            spacing="1",
            width="100%",
        ),
    )


def _output_chip(chip) -> rx.Component:
    """«Feed · lun 12 · 12:00 p. m. · @bianki» — one output's planning state, by tone."""
    return rx.box(
        _pill(chip.word + " · " + chip.state_label, chip.tone),
        title=rx.cond(chip.note != "", chip.note, chip.label),
    )


def _step_hint(text: str) -> rx.Component:
    return rx.text(text, size="1", color=T.TEXT_MUTED)


def _step_post() -> rx.Component:
    """Step 1 · Post. D1: a POST that is not approved and publishable is refused right
    here, with the evaluator's exact reason, and the flow does not go on."""
    return rx.vstack(
        rx.cond(
            PlannerState.form_is_reschedule,
            _field("POST", rx.text(PlannerState.form_post_title, size="2", weight="medium")),
            _field(
                "POST",
                rx.select.root(
                    rx.select.trigger(placeholder="Elige un POST", width="100%"),
                    rx.select.content(
                        rx.foreach(
                            PlannerState.schedulable,
                            lambda p: rx.select.item(
                                p.title + " · " + p.approval_short, value=p.post_id
                            ),
                        )
                    ),
                    value=PlannerState.form_post_id,
                    on_change=PlannerState.set_form_post_id,
                ),
            ),
        ),
        rx.cond(
            PlannerState.form_has_outputs | (PlannerState.form_output_label != ""),
            _field("Salida", _output_control()),
        ),
        rx.cond(
            PlannerState.form_post_blocked != "",
            callout("No se puede programar: " + PlannerState.form_post_blocked, "error"),
        ),
        rx.cond(
            (PlannerState.form_post_blocked == "")
            & (PlannerState.form_post_id != "")
            & ~PlannerState.form_is_reschedule,
            callout("Listo para programar.", "ok"),
        ),
        _step_hint(
            "Solo entra al calendario un POST listo para publicar: aprobado, con su texto "
            "aprobado y su media disponible."
        ),
        spacing="3",
        width="100%",
    )


def _series_summary() -> rx.Component:
    """What the recurrence controls add up to: «Semanal · 4 veces · del 12 oct al 2
    nov» and the dates, or the exact reason the series cannot be built."""
    s = PlannerState.form_series
    return rx.cond(
        s.error != "",
        callout(s.error, "error"),
        rx.vstack(
            rx.text(s.summary, size="2", weight="medium"),
            rx.flex(rx.foreach(s.dates, lambda d: tag(d)), wrap="wrap", gap="0.25rem"),
            spacing="1",
            width="100%",
        ),
    )


def _repeat_controls() -> rx.Component:
    """QUA-118 A2/A4: weekly, same weekday and time, by count OR by end date, at most
    SERIES_CAP occurrences. Hidden on a reschedule (a move is one event)."""
    return rx.vstack(
        rx.hstack(
            rx.switch(
                checked=PlannerState.form_repeat,
                on_change=PlannerState.set_form_repeat,
                aria_label="Repetir cada semana",
            ),
            rx.vstack(
                rx.text("Repetir cada semana", size="2", weight="medium"),
                rx.text("Mismo día de la semana y misma hora.", size="1", color=T.TEXT_MUTED),
                spacing="0",
            ),
            align="center",
            spacing="3",
        ),
        rx.cond(
            PlannerState.form_repeat,
            rx.vstack(
                rx.segmented_control.root(
                    rx.segmented_control.item("Número de veces", value=REPEAT_BY_COUNT),
                    rx.segmented_control.item("Hasta una fecha", value=REPEAT_BY_UNTIL),
                    value=PlannerState.form_repeat_mode,
                    on_change=PlannerState.set_form_repeat_mode,
                    size="1",
                ),
                rx.cond(
                    PlannerState.form_repeat_mode == REPEAT_BY_UNTIL,
                    _field(
                        "Fecha de fin (incluida)",
                        rx.input(
                            type="date",
                            value=PlannerState.form_repeat_until,
                            on_change=PlannerState.set_form_repeat_until,
                            min=PlannerState.form_date,
                            width="100%",
                        ),
                    ),
                    _field(
                        f"Número de veces (máximo {SERIES_CAP})",
                        rx.input(
                            type="number",
                            min="1",
                            max=str(SERIES_CAP),
                            value=PlannerState.form_repeat_count,
                            on_change=PlannerState.set_form_repeat_count,
                            width="8rem",
                        ),
                    ),
                ),
                _series_summary(),
                spacing="3",
                width="100%",
                padding_left="0.25rem",
            ),
        ),
        spacing="3",
        width="100%",
    )


def _step_when() -> rx.Component:
    """Step 2 · Fecha y hora: one publication, or a weekly series."""
    return rx.vstack(
        rx.grid(
            _field(
                "Fecha",
                rx.input(
                    type="date",
                    value=PlannerState.form_date,
                    on_change=PlannerState.set_form_date,
                    min=PlannerState.today_iso,
                    width="100%",
                ),
            ),
            _field("Hora", _time_picker()),
            columns="1",
            spacing="3",
            width="100%",
        ),
        _step_hint("Zona horaria: " + PlannerState.tz_name),
        rx.cond(~PlannerState.form_is_reschedule, rx.fragment(rx.divider(), _repeat_controls())),
        spacing="3",
        width="100%",
    )


def _account_row(c) -> rx.Component:
    """One account to publish to. A compatible one toggles; an incompatible one is
    listed disabled with the reason (QUA-118 AC 6) and can never be chosen."""
    checked = PlannerState.form_connection_ids.contains(c.id)
    return rx.box(
        rx.hstack(
            rx.checkbox(
                checked=checked,
                disabled=~c.compatible,
                aria_label=c.label,
                style={"pointer_events": "none"},
            ),
            platform_badge(c.platform),
            rx.text(c.label, size="2", weight="medium"),
            rx.spacer(),
            rx.cond(~c.compatible, signal_pill("No compatible", "warn")),
            align="center",
            spacing="2",
            width="100%",
        ),
        rx.cond(
            c.note != "",
            rx.text(c.note, size="1", color=T.TEXT_MUTED, padding_left="1.9rem"),
        ),
        on_click=PlannerState.toggle_form_connection(c.id),
        role="checkbox",
        aria_checked=checked,
        aria_disabled=~c.compatible,
        cursor=rx.cond(c.compatible, "pointer", "not-allowed"),
        opacity=rx.cond(c.compatible, "1", "0.6"),
        padding="0.6rem 0.75rem",
        border=T.BORDER,
        border_radius=T.RADIUS_CONTROL,
        background=rx.cond(checked, rx.color("accent", 2), T.SURFACE_BG),
        border_color=rx.cond(checked, rx.color("accent", 7), rx.color("gray", 5)),
        width="100%",
    )


def _step_accounts() -> rx.Component:
    """Step 3 · Cuentas: one event per chosen account (AC 5). A reschedule moves one
    event, so there exactly one account is chosen."""
    return rx.vstack(
        rx.cond(
            PlannerState.connections.length() > 0,
            rx.vstack(
                rx.foreach(PlannerState.connections, _account_row), spacing="2", width="100%"
            ),
            callout(
                "No hay cuentas activas. Conecta o reactiva una en Conexiones para poder "
                "planificar.",
                "warn",
            ),
        ),
        rx.cond(
            PlannerState.form_is_reschedule,
            _step_hint("Una publicación se mueve a una sola cuenta."),
            _step_hint(
                "Cada cuenta recibe su propia publicación, independiente de las demás: "
                "cancelar una no afecta a las otras."
            ),
        ),
        spacing="3",
        width="100%",
    )


def _frame(frame) -> rx.Component:
    """A static mock of what one account will show (AC 7): the POST's media in the
    channel's shape. Never a Meta rendering — a frame, not a promise."""
    media = rx.cond(
        frame.video_url != "",
        rx.el.video(
            src=BACKEND_BASE + frame.video_url + "#t=0.1",
            muted=True,
            preload="metadata",
            plays_inline=True,
            controls=True,
            width="100%",
            height="100%",
            style={"object_fit": "cover", "display": "block"},
        ),
        rx.cond(
            frame.thumbnail_url != "",
            rx.image(
                src=rx.cond(
                    frame.thumbnail_url.startswith("http"),
                    frame.thumbnail_url,
                    rx.get_upload_url(frame.thumbnail_url),
                ),
                alt="",
                width="100%",
                height="100%",
                object_fit="cover",
                display="block",
            ),
            rx.center(rx.icon("image", size=T.ICON_MD, color=T.TEXT_FAINT), height="100%"),
        ),
    )
    return rx.vstack(
        rx.hstack(
            platform_badge(frame.platform),
            rx.text(frame.account_label, size="1", weight="medium", style=_ONE_LINE),
            align="center",
            spacing="1",
            max_width="100%",
        ),
        rx.box(
            media,
            width="7.5rem",
            style={"aspect_ratio": frame.aspect},
            background="black",
            border_radius=T.RADIUS_CONTROL,
            border=T.BORDER,
            overflow="hidden",
        ),
        tag(frame.kind_label),
        spacing="1",
        align="center",
    )


def _summary_row(label: str, value) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2", color=T.TEXT_MUTED, min_width="6.5rem"),
        rx.box(value, flex="1", min_width="0"),
        align="start",
        width="100%",
    )


def _plan_label(text: str) -> rx.Component:
    """The summary card's row label: small caps, muted — the mock-up's «CUÁNDO»."""
    return rx.text(
        text,
        size="1",
        weight="bold",
        color=T.TEXT_MUTED,
        letter_spacing="0.06em",
        text_transform="uppercase",
        flex_shrink="0",
    )


def _plan_row(label: str, value: rx.Component) -> rx.Component:
    return rx.hstack(
        _plan_label(label),
        rx.spacer(),
        rx.box(value, min_width="0", display="flex", justify_content="flex-end"),
        align="start",
        width="100%",
        spacing="3",
    )


def _plan_card() -> rx.Component:
    """What «Programar» will do, as a card: the POST and its media, when (and how
    often), on which accounts, in which zone. The same facts the service will act on."""
    s = PlannerState.form_series
    return rx.box(
        rx.vstack(
            _plan_row(
                "POST",
                rx.vstack(
                    rx.text(
                        PlannerState.form_post_title_or_chosen,
                        size="2",
                        weight="bold",
                        text_align="right",
                    ),
                    rx.hstack(
                        rx.icon("film", size=12, color=T.TEXT_MUTED),
                        rx.text(PlannerState.form_media_label, size="1", color=T.TEXT_MUTED),
                        align="center",
                        spacing="1",
                    ),
                    rx.cond(
                        PlannerState.form_output_label != "",
                        rx.text(
                            "Salida: " + PlannerState.form_output_label,
                            size="1",
                            color=T.TEXT_MUTED,
                        ),
                    ),
                    spacing="1",
                    align="end",
                ),
            ),
            rx.divider(),
            _plan_row("Cuándo", signal_pill(PlannerState.form_when_label, "accent", size="2")),
            _plan_row(
                "Repetición",
                rx.cond(
                    s.enabled,
                    rx.vstack(
                        rx.text(s.summary, size="2", text_align="right"),
                        rx.flex(
                            rx.foreach(s.dates, lambda d: tag(d)),
                            wrap="wrap",
                            gap="0.3rem",
                            justify="end",
                        ),
                        spacing="2",
                        align="end",
                    ),
                    rx.text("Una sola vez", size="2"),
                ),
            ),
            rx.divider(),
            _plan_row(
                "Cuentas",
                rx.flex(
                    rx.foreach(
                        PlannerState.form_selected_accounts,
                        lambda c: rx.hstack(
                            platform_badge(c.platform),
                            rx.text(c.label, size="2", weight="medium"),
                            align="center",
                            spacing="2",
                        ),
                    ),
                    wrap="wrap",
                    gap="0.6rem",
                    justify="end",
                ),
            ),
            _plan_row(
                "Zona horaria",
                rx.hstack(
                    rx.icon("globe", size=12, color=T.TEXT_MUTED),
                    rx.text(PlannerState.tz_name, size="2"),
                    align="center",
                    spacing="1",
                ),
            ),
            spacing="3",
            width="100%",
        ),
        padding="1rem 1.1rem",
        border=T.BORDER,
        border_radius=T.RADIUS_CARD,
        background=T.CARD_BG,
        width="100%",
    )


def _phone(frame) -> rx.Component:
    """A phone-shaped frame with the POST's media in the channel's shape: the format's
    word on top, a play glyph over a video, the account under. A mock, never Meta."""
    media = rx.cond(
        frame.video_url != "",
        rx.el.video(
            src=BACKEND_BASE + frame.video_url + "#t=0.1",
            muted=True,
            preload="metadata",
            plays_inline=True,
            aria_hidden="true",
            width="100%",
            height="100%",
            style={"object_fit": "cover", "display": "block", "pointer_events": "none"},
        ),
        rx.cond(
            frame.thumbnail_url != "",
            rx.image(
                src=rx.cond(
                    frame.thumbnail_url.startswith("http"),
                    frame.thumbnail_url,
                    rx.get_upload_url(frame.thumbnail_url),
                ),
                alt="",
                width="100%",
                height="100%",
                object_fit="cover",
                display="block",
            ),
            rx.center(rx.icon("image", size=T.ICON_MD, color=T.TEXT_FAINT), height="100%"),
        ),
    )
    overlay_text = {"color": "white", "text_shadow": "0 1px 2px rgba(0,0,0,.6)"}
    return rx.box(
        rx.box(media, position="absolute", inset="0"),
        rx.text(
            frame.kind_label,
            size="1",
            weight="bold",
            position="absolute",
            top="0.45rem",
            left="0.55rem",
            style=overlay_text,
        ),
        rx.cond(
            frame.video_url != "",
            rx.center(
                rx.center(
                    rx.icon("play", size=14, color="white", fill="white"),
                    width="2.1rem",
                    height="2.1rem",
                    border_radius="999px",
                    background="rgba(0,0,0,.55)",
                    border="1px solid rgba(255,255,255,.35)",
                ),
                position="absolute",
                inset="0",
                pointer_events="none",
            ),
        ),
        rx.text(
            frame.account_label,
            size="1",
            weight="medium",
            position="absolute",
            bottom="0.45rem",
            left="0.55rem",
            right="0.55rem",
            style={**overlay_text, **_ONE_LINE},
        ),
        width="6.75rem",
        style={"aspect_ratio": frame.aspect},
        position="relative",
        flex_shrink="0",
        border_radius="0.9rem",
        overflow="hidden",
        background="black",
        border=f"2px solid {rx.color('gray', 7)}",
        box_shadow=T.ELEV_ISLAND,
    )


def _frame_block(frame) -> rx.Component:
    """One account's preview: the phone frame and, beside it, what will be published
    there, in words that stay true (format, medium, account — nothing we do not know)."""
    return rx.hstack(
        _phone(frame),
        rx.vstack(
            rx.hstack(
                rx.box(
                    width="8px",
                    height="8px",
                    border_radius="999px",
                    background=T.tone_color("ok", 9),
                ),
                rx.text(frame.kind_label + " listo para publicar", size="2", weight="bold"),
                align="center",
                spacing="2",
            ),
            rx.text(
                "Se publicará en "
                + frame.account_label
                + " como "
                + frame.kind_label
                + " · "
                + frame.media_label
                + " en formato "
                + frame.ratio_label
                + ".",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.hstack(
                platform_badge(frame.platform),
                tag(frame.kind_label),
                spacing="1",
                align="center",
            ),
            spacing="2",
            min_width="0",
            flex="1",
        ),
        spacing="3",
        align="center",
        width="100%",
        padding="0.75rem",
        background=T.SURFACE_BG_RAISED,
        border=T.BORDER,
        border_radius=T.RADIUS_CARD,
    )


def _preview_card() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.icon("smartphone", size=14, color=T.tone_color("accent", 10)),
            _plan_label("Vista previa en móvil"),
            rx.spacer(),
            rx.text(PlannerState.form_media_label, size="1", color=T.TEXT_MUTED),
            align="center",
            width="100%",
            spacing="2",
        ),
        rx.vstack(
            rx.foreach(PlannerState.form_frames, _frame_block),
            spacing="2",
            width="100%",
            margin_top="0.75rem",
        ),
        rx.text(
            "Vista previa orientativa: el formato de cada cuenta con la media actual del POST.",
            size="1",
            color=T.TEXT_FAINT,
            margin_top="0.5rem",
        ),
        padding="1rem 1.1rem",
        border=T.BORDER,
        border_radius=T.RADIUS_CARD,
        background=T.CARD_BG,
        width="100%",
    )


def _tags_block() -> rx.Component:
    count = PlannerState.form_tag_ids.length()
    return rx.vstack(
        rx.hstack(
            rx.text("Etiquetas (opcional)", size="2", weight="medium"),
            rx.spacer(),
            rx.cond(
                count > 0,
                rx.text(
                    rx.cond(count == 1, "1 seleccionada", count.to_string() + " seleccionadas"),
                    size="1",
                    color=T.TEXT_MUTED,
                ),
            ),
            align="center",
            width="100%",
        ),
        _form_tags(),
        spacing="2",
        width="100%",
    )


def _step_preview() -> rx.Component:
    """Step 4 · Vista previa — and the confirmation: the count of events to create, the
    plan card, one frame per account, the optional tags, and the service's answer right
    here if it refuses (nothing is created then — the plan is atomic)."""
    n = PlannerState.form_event_count
    s = PlannerState.form_series
    return rx.vstack(
        callout(
            rx.cond(
                PlannerState.form_is_reschedule,
                "Se moverá esta publicación a la nueva fecha y cuenta.",
                rx.cond(
                    n == 1,
                    "Se creará 1 publicación programada.",
                    "Se crearán "
                    + n.to_string()
                    + " publicaciones programadas, independientes entre sí"
                    + rx.cond(s.enabled, ", mediante la regla de repetición.", "."),
                ),
            ),
            "info",
        ),
        _plan_card(),
        _preview_card(),
        _tags_block(),
        rx.cond(
            PlannerState.form_post_note != "",
            callout(
                "Quedará programado, pero no se publicará hasta que esté listo: "
                + PlannerState.form_post_note,
                "warn",
            ),
        ),
        rx.cond(PlannerState.form_error != "", callout(PlannerState.form_error, "error")),
        spacing="4",
        width="100%",
    )


def _drawer_footer() -> rx.Component:
    return rx.hstack(
        rx.button(
            "Cancelar",
            variant="ghost",
            color_scheme="gray",
            on_click=PlannerState.close_form,
        ),
        rx.spacer(),
        rx.cond(
            PlannerState.form_step > STEP_POST,
            rx.button(
                rx.icon("chevron-left", size=T.ICON_SM),
                "Atrás",
                variant="soft",
                color_scheme="gray",
                on_click=PlannerState.prev_step,
            ),
        ),
        rx.cond(
            PlannerState.form_is_last_step,
            rx.button(
                PlannerState.form_submit_label,
                loading=PlannerState.saving,
                on_click=PlannerState.submit_form,
            ),
            rx.button(
                "Siguiente",
                rx.icon("chevron-right", size=T.ICON_SM),
                disabled=~PlannerState.form_can_advance,
                title=PlannerState.form_step_error,
                on_click=PlannerState.next_step,
            ),
        ),
        align="center",
        spacing="2",
        width="100%",
    )


def _assign_drawer() -> rx.Component:
    """The assign / reschedule flow (QUA-118 AC 4): a right-edge drawer with a stepper
    — Post → Fecha y hora → Cuentas → Vista previa (where «Programar» lives). A step
    must be valid to leave it; a completed step is one click away to fix; the last
    step is where the service's answer lands."""
    return drawer(
        stepper(
            list(ASSIGN_STEPS),
            current=PlannerState.form_step,
            completed=PlannerState.form_steps_done,
            on_select=PlannerState.go_to_step,
        ),
        rx.box(
            rx.match(
                PlannerState.form_step,
                (STEP_POST, _step_post()),
                (STEP_WHEN, _step_when()),
                (STEP_ACCOUNTS, _step_accounts()),
                (STEP_PREVIEW, _step_preview()),
                _step_post(),
            ),
            margin_top="1.25rem",
            width="100%",
        ),
        rx.cond(
            PlannerState.form_step_hint != "",
            rx.text(
                PlannerState.form_step_hint,
                size="1",
                color=rx.color("amber", 11),
                margin_top="0.75rem",
            ),
        ),
        open=PlannerState.form_open,
        on_open_change=PlannerState.set_form_open,
        title=rx.hstack(
            rx.text(PlannerState.form_title, size="5", weight="bold"),
            rx.badge(
                PlannerState.form_step_badge,
                variant="soft",
                radius="full",
                size="1",
            ),
            align="center",
            spacing="2",
        ),
        description=rx.cond(
            PlannerState.form_is_reschedule,
            "Mueve la publicación a otra fecha, hora o cuenta.",
            "Elige el POST, cuándo sale y en qué cuentas. Nada se publica hasta su hora.",
        ),
        footer=_drawer_footer(),
        width="34rem",
    )


def _detail_tag(tag) -> rx.Component:
    """A tag on the open event: click to take it off (saved right away)."""
    return rx.box(
        _tag_badge(tag, closable=True),
        on_click=PlannerState.remove_detail_tag(tag.id),
        cursor="pointer",
        title="Quitar etiqueta",
    )


def _detail_add_tag() -> rx.Component:
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(rx.icon("plus", size=12), "Etiqueta", size="1", variant="ghost"),
        ),
        rx.dropdown_menu.content(
            rx.cond(
                PlannerState.detail_available_tags.length() > 0,
                rx.foreach(
                    PlannerState.detail_available_tags,
                    lambda t: rx.dropdown_menu.item(
                        rx.hstack(_tag_dot(t), rx.text(t.name), align="center", spacing="2"),
                        on_click=PlannerState.add_detail_tag(t.id),
                    ),
                ),
                rx.dropdown_menu.item(
                    "No hay más etiquetas. Créalas desde «Etiquetas» o al programar.",
                    disabled=True,
                ),
            ),
            size="1",
        ),
    )


def _detail_row(label: str, value: rx.Var[str]) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2", color=T.TEXT_MUTED, min_width="6.5rem"),
        rx.text(value, size="2"),
        align="start",
        width="100%",
    )


def _detail_dialog() -> rx.Component:
    d = PlannerState.detail
    body = rx.vstack(
        rx.hstack(
            # A POST whose video lives only in R2 shows the video itself (its first frame,
            # playable) through the backend's short-lived `/r2media/<token>`; anything
            # else keeps the image thumbnail / placeholder.
            rx.cond(
                d.video_url != "",
                rx.video(
                    src=BACKEND_BASE + d.video_url,
                    controls=True,
                    muted=True,
                    preload="metadata",
                    width="6rem",
                    min_width="6rem",
                    height="auto",
                    style={
                        "aspect_ratio": "9 / 16",
                        "background": "black",
                        "border_radius": "0.375rem",
                    },
                ),
                _thumbnail(d.thumbnail_url, "4.5rem"),
            ),
            rx.vstack(
                rx.text(d.title, size="3", weight="bold"),
                rx.flex(
                    tag(d.category_label),
                    _pill(d.approval_label, d.approval_tone),
                    _pill(d.status_label, d.status_tone),
                    wrap="wrap",
                    gap="0.25rem",
                ),
                spacing="2",
                min_width="0",
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        rx.cond(d.caption_excerpt != "", rx.text(d.caption_excerpt, size="2", color=T.TEXT_MUTED)),
        rx.divider(),
        _detail_row("Cuándo", d.when_label),
        rx.hstack(
            rx.text("Cuenta", size="2", color=T.TEXT_MUTED, min_width="6.5rem"),
            platform_badge(d.platform),
            rx.text(d.account_label, size="2"),
            align="center",
            width="100%",
        ),
        rx.cond(d.content_type_label != "", _detail_row("Contenido", d.content_type_label)),
        rx.cond(d.output_label != "", _detail_row("Salida", d.output_label)),
        # `revision` is the event's reschedule counter (it keys the publish attempt, so a
        # moved event can never collide with the old one) — internal. Shown to people only
        # once it means something: how many times the publication was moved.
        rx.cond(
            d.revision > 1,
            _detail_row(
                "Reprogramado",
                rx.cond(d.revision == 2, "1 vez", (d.revision - 1).to_string() + " veces"),
            ),
        ),
        rx.hstack(
            rx.text("Etiquetas", size="2", color=T.TEXT_MUTED, min_width="6.5rem"),
            rx.flex(
                rx.foreach(d.tags, _detail_tag),
                _detail_add_tag(),
                wrap="wrap",
                gap="0.35rem",
                align="center",
            ),
            align="center",
            width="100%",
        ),
        rx.cond(
            # QUA-115: an expired event will NOT publish when it is ready — only a
            # reschedule brings it back, so the expiry note replaces the readiness one.
            d.expired,
            callout(EXPIRED_NOTE, "warn"),
            rx.cond(
                d.publish_note != "",
                callout(
                    "No se publicará hasta completarlo: "
                    + d.publish_note
                    + " El evento sigue programado y se publica en el siguiente minuto en que "
                    "esté listo.",
                    "warn",
                ),
            ),
        ),
        rx.match(
            PlannerState.auto_publish,
            (
                AUTO_PUBLISH_ACTIVE,
                rx.text(
                    "Publicación automática activa: un evento aprobado se publica a su "
                    "hora (se revisa cada minuto).",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
            ),
            (
                AUTO_PUBLISH_NO_CONNECTION,
                callout(
                    "No hay una cuenta conectada y activa para publicar. Conéctala en "
                    "Conexiones: los eventos se publicarán en cuanto lo esté.",
                    "warn",
                ),
            ),
            callout(
                "El servicio de publicación automática no está disponible en este "
                "momento: los eventos no se publicarán a su hora.",
                "warn",
            ),
        ),
        rx.hstack(
            rx.cond(
                d.detail_href != "",
                rx.link(
                    rx.button("Ver POST", variant="soft", color_scheme="gray"),
                    href=d.detail_href,
                ),
            ),
            rx.spacer(),
            # A REJECTED POST: nothing to move or cancel — only take it off the calendar.
            rx.cond(
                d.can_remove_rejected,
                rx.button(
                    rx.icon("trash-2", size=T.ICON_SM),
                    "Quitar del calendario",
                    variant="soft",
                    color_scheme="red",
                    on_click=PlannerState.ask_remove_rejected,
                ),
            ),
            # A POST still in review can be rejected from here (the creative FSM decides).
            rx.cond(
                d.can_reject_post,
                rx.button(
                    rx.icon("thumbs-down", size=T.ICON_SM),
                    "Rechazar POST",
                    variant="soft",
                    color_scheme="red",
                    on_click=PlannerState.reject_post_from_detail,
                ),
            ),
            rx.cond(
                d.can_modify,
                rx.hstack(
                    rx.button(
                        "Cancelar publicación",
                        variant="soft",
                        color_scheme="red",
                        on_click=PlannerState.ask_cancel_from_detail,
                    ),
                    rx.button("Reprogramar", on_click=PlannerState.reschedule_from_detail),
                    spacing="2",
                ),
            ),
            width="100%",
            align="center",
            wrap="wrap",
            gap="2",
        ),
        spacing="3",
        width="100%",
    )
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Publicación planificada"),
            rx.cond(
                PlannerState.detail_loading,
                rx.center(rx.spinner(), padding="2rem"),
                rx.cond(
                    PlannerState.detail_error != "",
                    callout(PlannerState.detail_error, "error"),
                    body,
                ),
            ),
            max_width="32rem",
        ),
        open=PlannerState.detail_open,
        on_open_change=PlannerState.set_detail_open,
    )


def _remove_rejected_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Quitar POST rechazado del calendario"),
            rx.alert_dialog.description(
                "Se cancelan y se quitan del calendario las publicaciones de este POST que "
                "todavía no salieron. Lo ya publicado se conserva. El POST rechazado no se "
                "borra: puedes regenerarlo y volver a programarlo.",
                size="2",
            ),
            rx.hstack(
                rx.alert_dialog.cancel(
                    rx.button("Volver", variant="soft", color_scheme="gray"),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        "Quitar del calendario",
                        color_scheme="red",
                        on_click=PlannerState.confirm_remove_rejected,
                    ),
                ),
                justify="end",
                spacing="2",
                margin_top="1rem",
            ),
        ),
        open=PlannerState.remove_rejected_open,
        on_open_change=PlannerState.set_remove_rejected_open,
    )


def _delete_tag_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Eliminar etiqueta"),
            rx.alert_dialog.description(
                "Se eliminará «" + PlannerState.delete_tag_name + "» y se quitará de todas "
                "las publicaciones que la tengan. Las publicaciones no se modifican.",
                size="2",
            ),
            rx.hstack(
                rx.alert_dialog.cancel(
                    rx.button("Volver", variant="soft", color_scheme="gray"),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        "Eliminar etiqueta",
                        color_scheme="red",
                        on_click=PlannerState.confirm_delete_tag,
                    ),
                ),
                justify="end",
                spacing="2",
                margin_top="1rem",
            ),
        ),
        open=PlannerState.delete_tag_open,
        on_open_change=PlannerState.set_delete_tag_open,
    )


def _cancel_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Cancelar publicación"),
            rx.alert_dialog.description(
                "La publicación sale del calendario y no se publicará en esta fecha. "
                "El POST vuelve a «Sin programar» y su contenido no se modifica.",
                size="2",
            ),
            rx.hstack(
                rx.alert_dialog.cancel(
                    rx.button("Volver", variant="soft", color_scheme="gray"),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        "Cancelar publicación",
                        color_scheme="red",
                        on_click=PlannerState.confirm_cancel,
                    ),
                ),
                justify="end",
                spacing="2",
                margin_top="1rem",
            ),
        ),
        open=PlannerState.cancel_open,
        on_open_change=PlannerState.set_cancel_open,
    )


# ---------------------------------------------------------------------------
# Page


def _views() -> rx.Component:
    """Calendario on desktop when chosen; Lista when chosen, and always on a phone. The
    responsive switch lives on plain divs (`q-planner-desktop` / `q-planner-mobile` in
    `assets/qualify.css`), not on Radix boxes, whose base `display` can outrank it."""
    return rx.box(
        rx.cond(
            PlannerState.is_list_view,
            _list(),
            rx.fragment(
                rx.el.div(_calendar(), class_name="q-planner-desktop"),
                rx.el.div(_list(), class_name="q-planner-mobile"),
            ),
        ),
        flex="1",
        min_width="0",
        width="100%",
    )


def _loading() -> rx.Component:
    return rx.vstack(
        rx.skeleton(rx.box(height="2.5rem"), width="100%"),
        rx.skeleton(rx.box(height="24rem"), width="100%"),
        spacing="2",
        width="100%",
    )


def planner_index() -> rx.Component:
    return app_shell(
        page_header(
            "Planificador",
            "Qué se publica, cuándo y en qué cuenta.",
            _view_toggle(),
            _assign_button(),
        ),
        page_body(
            rx.cond(PlannerState.load_error != "", callout(PlannerState.load_error, "error")),
            rx.cond(
                ~PlannerState.has_connections & ~PlannerState.loading,
                callout(
                    "No hay cuentas activas. Conecta o reactiva una en Conexiones para "
                    "poder planificar.",
                    "warn",
                ),
            ),
            _toolbar(),
            rx.cond(
                PlannerState.loading & (PlannerState.rows.length() == 0),
                _loading(),
                rx.flex(
                    _views(),
                    rx.cond(PlannerState.show_unscheduled, _unscheduled_panel()),
                    direction=rx.breakpoints(initial="column-reverse", lg="row"),
                    gap="1rem",
                    width="100%",
                    align="start",
                ),
            ),
            spacing="3",
        ),
        _assign_drawer(),
        _detail_dialog(),
        _cancel_dialog(),
        _delete_tag_dialog(),
        _remove_rejected_dialog(),
    )
