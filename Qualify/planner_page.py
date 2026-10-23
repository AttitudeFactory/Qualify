"""`/planner` — Planificador (QUA-108): the editorial calendar.

Two views of the same week, switched from the header (see `planner_vm.py` for the
reasoning): **Calendario** — seven day columns on a real hour axis — and **Lista** —
events grouped by day. A "Sin programar" panel (toggled from the toolbar, closed by
default so the calendar gets the full width) holds the POSTs waiting to be planned.
Planning, rescheduling and an event's detail open as side panels (`planner_drawer`) —
never a modal. On a phone the list is always
used: a seven-column hour grid does not fit a phone width.

What the screen deliberately does not have: a publish button. Planning is not
publishing — `/publish` publishes now, QUA-111 will execute planned events.

Built only from the design system (`ui/`): `app_shell` + `page_header` + `page_body`,
states by tone through `signal_pill`, identity through `platform_badge`, colours through
`T.*`, so light and dark mode need no rules of their own. The calendar's skin — the week
as one card, hairlines, today, the chips and their state edge — is the `q-cal-*` family in
`assets/qualify-planner.css` (plan D13: the weekly hour grid is kept, only its material
moved to the Liquid Glass card).
"""

from __future__ import annotations

import reflex as rx

from .planner_drawer import (
    assign_drawer,
    channel_mark,
    event_panel,
    tag_badge_plain,
    tag_dot,
)
from .planner_state import REFRESH_SECONDS, SCROLL_ID, PlannerState
from .planner_vm import VIEW_CALENDAR, VIEW_LIST
from .post_card import (
    DropBox,
    campaign_badge,
    campaign_mark,
    card_media,
    destination_badge,
    destination_icon,
    pill,
    post_card,
    readiness_note,
    temperature_badge,
)
from .ui import (
    app_shell,
    callout,
    card,
    page_body,
    page_header,
    platform_badge,
    skeleton_rows,
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
    """The chip's left edge carries the state at a glance: grass published, tomato
    failed; for what is still planned, accent approved, amber pending or overdue,
    tomato rejected, gray cancelled/unknown. Computed from the state alone, as one
    `.q-cal-chip--*` class per state (`assets/qualify-planner.css`), so the colour is
    the sheet's, not the page's."""
    return rx.match(
        event.status_label,
        ("Publicado", "q-cal-chip--published"),
        ("Fallido", "q-cal-chip--failed"),
        rx.cond(
            event.muted,
            "q-cal-chip--idle",
            rx.cond(
                event.overdue,
                "q-cal-chip--overdue",
                rx.match(
                    event.approval_tone,
                    ("ok", "q-cal-chip--approved"),
                    ("warn", "q-cal-chip--pending"),
                    ("error", "q-cal-chip--rejected"),
                    "q-cal-chip--idle",
                ),
            ),
        ),
    )


def _chip_detail(event) -> rx.Component:
    """Everything about the event, on hover — the chip stays one line so every hour of
    the grid keeps the same height, and nothing is lost: title, caption, when, channel,
    destination, temperature, its states, tags and what may keep it from going out."""
    return rx.vstack(
        rx.hstack(
            card_media(event.thumbnail_url, event.video_url, "3.25rem"),
            rx.vstack(
                rx.text(event.title, size="2", weight="bold", style=_CLAMP_2),
                rx.text(
                    event.date_label + " · " + event.time_label,
                    size="1",
                    color=T.TEXT_MUTED,
                    class_name="q-nums",
                ),
                spacing="1",
                min_width="0",
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        rx.cond(
            event.caption_excerpt != "",
            rx.text(event.caption_excerpt, size="1", color=T.TEXT_MUTED, style=_CLAMP_2),
        ),
        rx.flex(
            rx.hstack(
                channel_mark(event.platform),
                rx.text(event.account_label, size="1", weight="medium"),
                align="center",
                spacing="1",
            ),
            destination_badge(event.destination, event.destination_label),
            temperature_badge(event.temperature, event.temperature_label, event.temperature_hint),
            wrap="wrap",
            gap="0.4rem",
            align="center",
        ),
        rx.flex(
            pill(event.approval_label, event.approval_tone),
            pill(event.status_label, event.status_tone),
            wrap="wrap",
            gap="0.3rem",
        ),
        campaign_badge(event.campaign_name, event.campaign_color),
        rx.cond(
            event.tags.length() > 0,
            rx.flex(rx.foreach(event.tags, tag_badge_plain), wrap="wrap", gap="0.25rem"),
        ),
        readiness_note(event.readiness_note),
        rx.text("Clic para ver y gestionar", size="1", color=T.TEXT_FAINT),
        spacing="2",
        width="17rem",
    )


def _calendar_chip(event) -> rx.Component:
    """A one-line event chip: picture, time, channel, destination and Cold/Hot by glyph
    and colour. One line, so five fit in an hour of the grid; the full
    detail opens on hover (`_chip_detail`) and the event's panel on click. A Hot POST
    glows like embers, a Cold one is frosted (`q-chip-temp--*`)."""
    chip = rx.box(
        # The picture lives in the hover card: a seventh of the screen fits the time
        # and three glyphs, not a thumbnail too. The time gives way first (ellipsis);
        # the glyphs never shrink.
        rx.box(
            rx.text(event.time_label, size="1", weight="bold", class_name="q-nums q-chip-time"),
            # The event's state by glyph (the word is in the hover card and the name):
            # ✓ published, ✕ failed, ⚠ pending / expired / not ready.
            rx.match(
                event.status_label,
                (
                    "Publicado",
                    rx.icon("circle-check", size=12, color=T.tone_color("ok", 10), flex_shrink="0"),
                ),
                (
                    "Fallido",
                    rx.icon("circle-x", size=12, color=T.tone_color("error", 10), flex_shrink="0"),
                ),
                rx.cond(
                    event.overdue | (event.readiness_note != ""),
                    rx.icon(
                        "triangle-alert", size=11, color=T.tone_color("warn", 10), flex_shrink="0"
                    ),
                ),
            ),
            rx.box(class_name="q-chip-gap"),
            # QUA-143: the campaign's flag, before the channel — identity, not state.
            campaign_mark(event.campaign_name, event.campaign_color),
            channel_mark(event.platform),
            rx.cond(
                event.destination != "",
                rx.center(
                    destination_icon(event.destination, 10),
                    class_name="q-dest-dot q-dest-dot--sm q-dest-" + event.destination,
                    title=event.destination_label,
                ),
            ),
            temperature_badge(
                event.temperature, event.temperature_label, event.temperature_hint, compact=True
            ),
            class_name="q-chip-line",
        ),
        # stop_propagation: the cell behind the chip opens "Nueva publicación" on click.
        on_click=PlannerState.open_detail(event.event_id).stop_propagation,
        cursor="pointer",
        role="button",
        # The accessible name says everything the glyphs say: title, channel,
        # destination, temperature and the event's state word (QUA-118).
        aria_label=event.time_label
        + " · "
        + event.title
        + " · "
        + event.account_label
        + rx.cond(event.campaign_name != "", " · Campaña " + event.campaign_name, "")
        + rx.cond(event.destination_label != "", " · " + event.destination_label, "")
        + rx.cond(event.temperature_label != "", " · " + event.temperature_label, "")
        + rx.cond(event.output_label != "", " · " + event.output_label, "")
        + " · "
        + event.status_label
        + rx.cond(event.approval_label != event.status_label, " · " + event.approval_label, ""),
        # The chip is a control on the calendar card (`.q-cal-chip`): its material, its
        # state edge and its muted look all come from the sheet.
        class_name="q-cal-chip "
        + _chip_edge(event).to(str)
        + rx.cond(event.muted, " q-cal-chip--muted", "")
        + " q-lift q-chip-temp q-chip-temp--"
        + event.temperature,
    )
    return rx.hover_card.root(
        rx.hover_card.trigger(rx.box(chip, class_name="q-chip-trigger")),
        rx.hover_card.content(_chip_detail(event), side="right", align="start", size="1"),
        open_delay=250,
        close_delay=80,
    )


def _status_glyph(event) -> rx.Component:
    """The event's state as a small icon: ✓ published, ✕ failed, ⏱ otherwise."""
    return rx.match(
        event.status_label,
        ("Publicado", rx.icon("circle-check", size=13, color=T.tone_color("ok", 10))),
        ("Fallido", rx.icon("circle-x", size=13, color=T.tone_color("error", 10))),
        rx.icon("clock", size=13, color=T.TEXT_MUTED),
    )


def _hour_list_row(event) -> rx.Component:
    """One compact row of the hour's full list: time, then the POST's title over
    account · destination, then status/channel/destination glyphs. A click opens the
    event's side panel."""
    return rx.el.button(
        rx.text(event.time_label, size="1", weight="bold", class_name="q-nums q-hour-list-time"),
        rx.box(
            rx.text(event.title, size="1", weight="medium", class_name="q-hour-list-title"),
            rx.text(
                event.account_label + " · " + event.destination_label,
                size="1",
                color=T.TEXT_MUTED,
                class_name="q-hour-list-title q-hour-list-sub",
            ),
            min_width="0",
        ),
        rx.hstack(
            campaign_mark(event.campaign_name, event.campaign_color),
            channel_mark(event.platform),
            rx.cond(
                event.destination != "",
                rx.center(
                    destination_icon(event.destination, 10),
                    class_name="q-dest-dot q-dest-dot--sm q-dest-" + event.destination,
                ),
            ),
            rx.box(_status_glyph(event), title=event.status_label, display="flex"),
            align="center",
            spacing="1",
        ),
        type="button",
        title=event.status_label,
        class_name="q-hour-list-row",
        on_click=PlannerState.open_detail(event.event_id).stop_propagation,
    )


def _more_pill(cell) -> rx.Component:
    """«+N más»: from the sixth event of an hour on. Opens, right beside it, exactly
    the N events that did not fit — title, account, destination and state — and each
    row opens the event's panel."""
    # Reflex wraps the trigger's child in a Flex that IS the trigger, so a stop on the
    # button itself kept the list from ever opening. The stop lives out here instead:
    # the trigger handles the click first, then the slot under it never sees it (it
    # would open «Nueva publicación»).
    return rx.box(
        rx.popover.root(
            rx.popover.trigger(
                rx.button(
                    rx.icon("layers", size=12),
                    "+" + cell.more_count.to_string() + " más",
                    type="button",
                    variant="soft",
                    size="1",
                    class_name="q-cell-more",
                    title="Ver las publicaciones que no caben en la celda",
                ),
            ),
            rx.popover.content(
                rx.vstack(
                    rx.hstack(
                        rx.text(
                            "+" + cell.more_count.to_string() + " más",
                            size="2",
                            weight="bold",
                            color=T.tone_color("accent", 11),
                        ),
                        rx.spacer(),
                        rx.text(cell.heading, size="1", color=T.TEXT_MUTED),
                        align="center",
                        width="100%",
                    ),
                    rx.box(
                        rx.foreach(cell.more, _hour_list_row),
                        class_name="q-hour-list",
                    ),
                    spacing="2",
                    width="19rem",
                    max_width="calc(100vw - 2rem)",
                ),
                # Right beside the pill, pointing at it: «these are the +N». Radix flips it
                # to the left on the last days of the week, where the right has no room.
                side="right",
                align="center",
                side_offset=6,
                size="1",
            ),
        ),
        on_click=rx.event.stop_propagation,
        width="100%",
    )


def _day_header(day) -> rx.Component:
    """A day's head, sticky over its column: name and number, today in the accent with
    its underline, a past day muted (`.q-cal-day*`, `assets/qualify-planner.css`)."""
    return rx.center(
        rx.hstack(
            rx.text(
                day.weekday,
                size="2",
                weight=rx.cond(day.is_today, "bold", "regular"),
                class_name="q-cal-day-name",
            ),
            rx.text(day.day_number, size="2", weight="bold", class_name="q-nums q-cal-day-num"),
            spacing="2",
            align="center",
        ),
        class_name=rx.cond(
            day.is_today,
            "q-cal-head q-cal-day q-cal-day--today",
            rx.cond(day.is_past, "q-cal-head q-cal-day q-cal-day--past", "q-cal-head q-cal-day"),
        ),
    )


def _hour_cell(cell) -> rx.Component:
    """A clickable slot: a click on its empty area opens "Nueva publicación" for this
    day and hour. A not-past slot shows a "+" on hover (`q-planner-slot*` in
    `assets/qualify-planner.css`) so it reads as "you can add here": in the corner when
    the slot is empty, under the chips when it has posts. Past days get neither."""
    slot = rx.vstack(
        rx.cond(
            ~cell.is_past & (cell.cards.length() == 0),
            rx.el.span(rx.icon("plus", size=T.ICON_SM), class_name="q-planner-slot-plus"),
        ),
        rx.foreach(cell.visible, _calendar_chip),
        rx.cond(cell.more_count > 0, _more_pill(cell)),
        # One chip leaves room under it: the "+" shows there on hover, never over a chip.
        rx.cond(
            ~cell.is_past & (cell.cards.length() == 1),
            rx.el.span(
                rx.icon("plus", size=12),
                class_name="q-planner-slot-plus q-planner-slot-plus--below",
            ),
        ),
        on_click=PlannerState.open_assign_for_slot(cell.day_iso, cell.hour),
        title=rx.cond(cell.is_past, "", "Nueva publicación a esta hora"),
        cursor=rx.cond(cell.is_past, "default", "pointer"),
        class_name=rx.cond(
            cell.is_today,
            "q-planner-slot q-cal-cell q-cal-cell--today",
            "q-planner-slot q-cal-cell",
        ),
        position="relative",
        spacing="1",
        padding="0.25rem",
        # An hour is at least this tall; one with more posts grows to show up to five
        # chips (`CELL_VISIBLE`) and, past that, «+N más». The whole row grows with its
        # fullest cell (grid rows stretch), so the seven days stay aligned.
        min_height="4.25rem",
        height="100%",  # fills its row when a neighbour cell made it taller
        width="100%",
        min_width="0",
    )
    # QUA-118 drag & drop: a «Sin programar» card dropped here opens the drawer
    # prefilled with this day and hour. `on_drag_over` must prevent the default or the
    # browser never fires the drop; a past day is not a target.
    return DropBox.create(
        slot,
        on_drag_over=rx.event.prevent_default,
        on_drop=PlannerState.drop_on_slot(cell.day_iso, cell.hour).prevent_default,
        class_name=rx.cond(
            PlannerState.dragging & ~cell.is_past,
            "q-drop-target q-drop-target--active",
            "q-drop-target",
        ),
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
            white_space="nowrap",
            class_name="q-cal-hour",
        ),
        rx.foreach(row.cells, _hour_cell),
    )


def _calendar() -> rx.Component:
    """The week as one card (`.q-cal`): the sticky day row on top, the hour axis on the
    left, seven columns of slots. Material and hairlines are the sheet's."""
    return rx.box(
        rx.grid(
            rx.box(class_name="q-cal-head"),
            rx.foreach(PlannerState.days, _day_header),
            rx.foreach(PlannerState.rows, _hour_row),
            # Radix's own `columns` prop, not a css `grid_template_columns`: Radix's base
            # `.rt-Grid { grid-template-columns: minmax(0, 1fr) }` can win the cascade over
            # an emotion class of equal specificity, collapsing the week to one column.
            columns=_GRID_COLUMNS,
            width="100%",
        ),
        class_name="q-cal",
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
                card_media(event.thumbnail_url, event.video_url, "3.5rem"),
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
                        destination_badge(event.destination, event.destination_label),
                        temperature_badge(
                            event.temperature, event.temperature_label, event.temperature_hint
                        ),
                        tag(event.category_label),
                        rx.cond(event.output_label != "", tag(event.output_label)),
                        campaign_badge(event.campaign_name, event.campaign_color),
                        rx.foreach(event.tags, tag_badge_plain),
                        align="center",
                        spacing="2",
                        wrap="wrap",
                    ),
                    readiness_note(event.readiness_note),
                    spacing="1",
                    min_width="0",
                    flex="1",
                ),
                rx.flex(
                    pill(event.approval_label, event.approval_tone),
                    pill(event.status_label, event.status_tone),
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
            opacity=rx.cond(event.muted, "0.55", "1"),
            align="center",
            spacing="2",
            flex="1",
            min_width="0",
            # The card material with the state on its left edge (amber when overdue).
            class_name=rx.cond(
                event.overdue, "q-plist-card q-plist-card--overdue q-lift", "q-plist-card q-lift"
            ),
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
                    color=rx.cond(day.is_today, T.tone_color("accent", 11), T.TEXT_STRONG),
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
    """A «Sin programar» card: the shared `post_card`, draggable onto a calendar cell
    (QUA-118); «Asignar» stays as the click path for keyboard and touch."""
    return post_card(
        post,
        actions=rx.hstack(
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
        ),
        on_drag_start=PlannerState.start_drag(post.post_id),
        on_drag_end=PlannerState.end_drag,
    )


def _unscheduled_panel() -> rx.Component:
    """The POSTs waiting to be planned, as a `card` beside the week (sticky on a wide
    screen, stacked under it on a narrow one)."""
    body = rx.vstack(
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
        width="100%",
        align_items="start",
    )
    return card(
        body,
        padding="0.9rem",
        width=rx.breakpoints(initial="100%", lg="20rem"),
        min_width=rx.breakpoints(initial="0", lg="20rem"),
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
    """One tag in the filter: the row toggles it; the trash turns the row itself into
    «¿Eliminar?» — the confirmation lives where the click was, no dialog."""
    selected = PlannerState.tag_filter.contains(tag.id)
    row = rx.hstack(
        rx.checkbox(checked=selected, size="1", pointer_events="none"),
        tag_dot(tag),
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
        _hover={"background": T.SURFACE_BG_RAISED},
    )
    confirm = rx.vstack(
        rx.text(
            "¿Eliminar «" + tag.name + "»? Se quita de todas las publicaciones.",
            size="1",
        ),
        rx.hstack(
            rx.button(
                "Volver",
                size="1",
                variant="soft",
                color_scheme="gray",
                on_click=PlannerState.cancel_delete_tag,
            ),
            rx.button(
                "Eliminar", size="1", color_scheme="red", on_click=PlannerState.confirm_delete_tag
            ),
            spacing="2",
        ),
        spacing="2",
        width="100%",
        padding="0.5rem",
        border_radius=T.RADIUS_CONTROL,
        background=T.tone_color("error", 3),
    )
    return rx.cond(PlannerState.delete_tag_id == tag.id, confirm, row)


def _tags_filter() -> rx.Component:
    empty = rx.vstack(
        rx.center(
            rx.icon("tag", size=T.ICON_MD, color=T.tone_color("accent", 11)),
            width="2.75rem",
            height="2.75rem",
            border_radius="999px",
            background=T.tone_color("accent", 3),
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
            background=rx.cond(selected, T.SURFACE_BG_RAISED, "transparent"),
            _hover={"background": T.SURFACE_BG_RAISED},
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


# ---------------------------------------------------------------------------
# Page


def _views() -> rx.Component:
    """Calendario on desktop when chosen; Lista when chosen, and always on a phone. The
    responsive switch lives on plain divs (`q-planner-desktop` / `q-planner-mobile` in
    `assets/qualify-planner.css`), not on Radix boxes, whose base `display` can outrank
    it."""
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
        skeleton_rows(1, height="2.5rem"),
        skeleton_rows(1, height="24rem", radius=T.RADIUS_CARD),
        spacing="2",
        width="100%",
    )


def planner_index() -> rx.Component:
    return app_shell(
        page_header(
            "Tu semana",
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
        assign_drawer(),
        event_panel(),
        # The page's clock: a quiet re-read of the week every REFRESH_SECONDS, so what
        # the worker published (or failed) shows without a manual reload. Client-side,
        # so it stops when the page is left.
        rx.moment(
            interval=REFRESH_SECONDS * 1000,
            on_change=PlannerState.refresh_week,
            display="none",
        ),
    )
