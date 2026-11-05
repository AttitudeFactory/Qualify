"""«Comparar creadores» — `/creadores/comparar?ids=a,b[,c,d]` (Delivery 1, m-24946132;
UX `docs/ux-creadores.md` §3; rules in design §9.3).

Rules that are not negotiated (founder, 2026-11-04): 2 to 4 creators, the same window
for all (said in words on top), the best of each row marked with the word «Mejor» —
bold figure **and** a `tone_badge`, never colour alone — **no summed score and no
overall winner**, «Sin dato» never counted as 0, and the stale-data warning with its
button inside.

- Computer: a Radix table in a horizontally scrollable box, the metric names as row
  headers, one column per creator with its ✕ (only with 3 or 4).
- Phone: two creator columns per screen, every figure with its name above it, and
  visible «‹ Anteriores» / «Siguientes ›» buttons with «1–2 de 3» in words. Swiping and
  the per-creator bar chart are NOT built: both wait for the founder (UX ⚑ 3 and ⚑ 5).
"""

from __future__ import annotations

import reflex as rx

from .creators_access import CreatorsAccessState
from .creators_page import (
    TOUCH_MIN,
    action_callout,
    back_link,
    creator_avatar,
    help_popover,
    stale_badge,
)
from .creators_state import CreatorsCompareState
from .creators_vm import (
    BEST,
    COMPARE_ADD,
    COMPARE_NEXT,
    COMPARE_PREV,
    COMPARE_TITLE,
    CellVM,
    ColumnVM,
    MobileColumnVM,
    MobileItemVM,
    RowVM,
)
from .ui import (
    app_shell,
    callout,
    card,
    empty_state,
    loading_spinner,
    mono,
    page_body,
    page_header,
    skeleton_rows,
    tone_badge,
)
from .ui import tokens as T

S = CreatorsCompareState


def _best_badge() -> rx.Component:
    return tone_badge(BEST, "ok", icon="trophy")


def _value(text: rx.Var[str], best: rx.Var[bool], missing: rx.Var[bool]) -> rx.Component:
    return rx.hstack(
        rx.text(
            text,
            size="2",
            weight=rx.cond(best, "bold", "regular"),
            color=rx.cond(missing, T.TEXT_MUTED, T.TEXT_STRONG),
            class_name="q-nums",
            white_space="nowrap",
        ),
        rx.cond(best, _best_badge()),
        spacing="2",
        align="center",
        wrap="wrap",
    )


def _column_head(c: rx.Var[ColumnVM], *, wide: bool = True) -> rx.Component:
    updating = S.updating.contains(c.tracked_id)
    return rx.vstack(
        rx.hstack(
            creator_avatar(c.avatar_url, c.initials, "3"),
            rx.vstack(
                rx.link(rx.text(c.name, size="2", weight="bold"), href=c.href),
                mono(c.handle, size="1", overflow_wrap="anywhere"),
                spacing="0",
                align_items="start",
                min_width="0",
            ),
            rx.spacer(),
            rx.cond(
                c.remove_href != "",
                rx.link(
                    rx.icon_button(
                        rx.icon("x", size=T.ICON_SM),
                        variant="ghost",
                        color_scheme="gray",
                        size="2",
                        aria_label=c.remove_label,
                        min_width=TOUCH_MIN,
                        min_height=TOUCH_MIN,
                    ),
                    href=c.remove_href,
                ),
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        rx.cond(
            updating,
            rx.hstack(
                loading_spinner("sm"),
                rx.text("Actualizando…", size="1", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
        ),
        rx.cond(c.few_note != "", rx.text(c.few_note, size="1", color=T.TEXT_MUTED)),
        spacing="1",
        align_items="start",
        width="100%",
        # a table column keeps room for a name; a phone column takes half the screen
        min_width="10rem" if wide else "0",
    )


def _cell(cell: rx.Var[CellVM]) -> rx.Component:
    return rx.table.cell(
        _value(cell.text, cell.best, cell.missing),
        aria_label=cell.spoken,
        vertical_align="middle",
    )


def _row(row: rx.Var[RowVM]) -> rx.Component:
    return rx.table.row(
        rx.table.row_header_cell(
            rx.hstack(
                rx.vstack(
                    rx.text(row.label, size="2", weight="medium"),
                    rx.cond(row.hint != "", rx.text(row.hint, size="1", color=T.TEXT_MUTED)),
                    spacing="0",
                    align_items="start",
                ),
                rx.cond(row.help != "", help_popover(row.label, row.help)),
                spacing="1",
                align="center",
                justify="between",
                width="100%",
            ),
            min_width="12rem",
        ),
        rx.foreach(row.cells, _cell),
    )


def _freshness_cell(c: rx.Var[ColumnVM]) -> rx.Component:
    return rx.table.cell(
        rx.vstack(
            rx.text(c.freshness, size="2", color=T.TEXT_MUTED),
            rx.cond(c.stale, stale_badge()),
            spacing="1",
            align_items="start",
        ),
    )


def _table() -> rx.Component:
    comparison = S.comparison
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell(aria_label="Lo que comparamos"),
                    rx.foreach(
                        comparison.columns,
                        lambda c: rx.table.column_header_cell(_column_head(c)),
                    ),
                ),
            ),
            rx.table.body(
                rx.foreach(comparison.rows, _row),
                rx.table.row(
                    rx.table.row_header_cell(rx.text("Datos de", size="2", weight="medium")),
                    rx.foreach(comparison.columns, _freshness_cell),
                ),
            ),
            variant="surface",
            width="100%",
        ),
        overflow_x="auto",
        width="100%",
        display=rx.breakpoints(initial="none", md="block"),
    )


def _mobile_item(item: rx.Var[MobileItemVM]) -> rx.Component:
    # Same structure and one-line value in every column, so the rows line up across the
    # pair and the eye compares sideways (UX §3.2).
    return rx.vstack(
        rx.text(item.label, size="1", color=T.TEXT_MUTED, line_clamp=2, min_height="2.5em"),
        _value(item.text, item.best, item.missing),
        spacing="1",
        align_items="start",
        width="100%",
        min_height="4.5rem",
    )


def _mobile_column(m: rx.Var[MobileColumnVM]) -> rx.Component:
    c = m.column
    return card(
        rx.vstack(
            _column_head(c, wide=False),
            rx.divider(),
            rx.foreach(m.figures, _mobile_item),
            rx.text(c.freshness, size="1", color=T.TEXT_MUTED),
            rx.cond(c.stale, stale_badge()),
            spacing="2",
            align_items="start",
            width="100%",
        ),
        padding="0.75rem",
        min_width="0",
    )


def _mobile() -> rx.Component:
    return rx.vstack(
        rx.grid(
            rx.foreach(S.visible, _mobile_column),
            columns="2",
            spacing="2",
            width="100%",
        ),
        rx.cond(
            S.page_count > 1,
            rx.hstack(
                rx.button(
                    rx.icon("chevron-left", size=T.ICON_MD),
                    COMPARE_PREV,
                    variant="soft",
                    size="3",
                    min_height=TOUCH_MIN,
                    disabled=~S.has_prev,
                    on_click=S.prev_page,
                ),
                rx.text(S.counter, size="2", color=T.TEXT_MUTED, aria_live="polite"),
                rx.button(
                    COMPARE_NEXT,
                    rx.icon("chevron-right", size=T.ICON_MD),
                    variant="soft",
                    size="3",
                    min_height=TOUCH_MIN,
                    disabled=~S.has_next,
                    on_click=S.next_page,
                ),
                justify="between",
                align="center",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
        display=rx.breakpoints(initial="flex", md="none"),
    )


def _warnings() -> rx.Component:
    comparison = S.comparison
    return rx.fragment(
        rx.cond(
            comparison.stale_message != "",
            action_callout(
                comparison.stale_message,
                rx.button(
                    rx.icon("refresh-cw", size=T.ICON_SM),
                    comparison.stale_button,
                    variant="soft",
                    size="3",
                    min_height=TOUCH_MIN,
                    loading=S.is_updating,
                    on_click=S.update_stale,
                ),
            ),
        ),
        rx.cond(S.update_message != "", callout(S.update_message, "error")),
        rx.cond(comparison.short_window != "", callout(comparison.short_window, "info")),
    )


def _comparison_view() -> rx.Component:
    comparison = S.comparison
    return rx.vstack(
        rx.text(comparison.intro, size="2", color=T.TEXT_MUTED),
        _warnings(),
        _table(),
        _mobile(),
        rx.cond(
            comparison.add_href != "",
            rx.link(
                rx.button(
                    rx.icon("plus", size=T.ICON_SM),
                    COMPARE_ADD,
                    variant="outline",
                    size="3",
                    min_height=TOUCH_MIN,
                ),
                href=comparison.add_href,
            ),
        ),
        spacing="4",
        width="100%",
    )


def _loading() -> rx.Component:
    return rx.box(skeleton_rows(6, height="3rem"), width="100%", aria_busy="true")


def creators_compare_index() -> rx.Component:
    off = CreatorsAccessState.access == "off"
    return app_shell(
        page_header(COMPARE_TITLE, None, kicker=back_link()),
        page_body(
            rx.cond(
                off,
                empty_state(
                    "users",
                    "Esto viene pronto",
                    "Estamos preparando esta parte para que encuentres creadores de tu "
                    "ciudad. Mientras tanto, prepara tu próxima publicación.",
                    action=rx.link(rx.button("Crear publicación", size="3"), href="/create"),
                ),
                rx.cond(
                    S.loading,
                    _loading(),
                    rx.cond(
                        S.load_error != "",
                        callout(S.load_error, "error"),
                        rx.cond(S.has_comparison, _comparison_view(), _loading()),
                    ),
                ),
            ),
        ),
    )
