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

«Lo que cobra» (m-24955847) adds «Cobra desde» and «Te cuesta cada mil vistas» (their
badge says «Más bajo», set by the server within one currency) and «Cómo trabaja» (free
text, three lines, the rest behind a «Ver más» tap). A missing price reads «Sin anotar»
with «Anotar lo que cobra» to the creator's sheet; prices in different currencies get a
quiet sentence, never a conversion.
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
    LOWEST,
    RATE_ADD,
    SEE_MORE,
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


def _lowest_badge() -> rx.Component:
    """«Más bajo» on a price: the same word-and-bold rule as «Mejor», never colour alone."""
    return tone_badge(LOWEST, "ok", icon="arrow-down")


def _value(
    text: rx.Var[str],
    best: rx.Var[bool],
    missing: rx.Var[bool],
    kind: rx.Var[str] | str = "metric",
) -> rx.Component:
    return rx.hstack(
        rx.text(
            text,
            size="2",
            weight=rx.cond(best, "bold", "regular"),
            color=rx.cond(missing, T.TEXT_MUTED, T.TEXT_STRONG),
            class_name="q-nums",
            white_space="nowrap",
        ),
        rx.cond(best, rx.cond(kind == "money", _lowest_badge(), _best_badge())),
        spacing="2",
        align="center",
        wrap="wrap",
    )


def _add_rate_link(href: rx.Var[str]) -> rx.Component:
    """«Anotar lo que cobra»: to the creator's sheet with the drawer open (N5)."""
    # A text link (not a button) so it wraps inside a half-screen phone column; the
    # height keeps the thumb target.
    return rx.link(
        rx.icon("plus", size=T.ICON_SM, flex_shrink="0"),
        RATE_ADD,
        href=href,
        size="2",
        display="inline-flex",
        align_items="center",
        gap="0.25rem",
        min_height=TOUCH_MIN,
    )


def _notes_value(text: rx.Var[str], missing: rx.Var[bool], long: rx.Var[bool]) -> rx.Component:
    """Free text in three lines (its own line breaks kept); the whole text behind «Ver
    más», opened with a tap (a phone has no hover)."""
    return rx.vstack(
        rx.text(
            text,
            size="2",
            color=rx.cond(missing, T.TEXT_MUTED, T.TEXT_STRONG),
            white_space="pre-line",
            overflow_wrap="anywhere",
            line_clamp=3,
        ),
        rx.cond(
            long,
            rx.popover.root(
                rx.popover.trigger(
                    rx.button(SEE_MORE, variant="ghost", size="2", min_height=TOUCH_MIN),
                ),
                rx.popover.content(
                    rx.text(text, size="2", white_space="pre-line", overflow_wrap="anywhere"),
                    max_width="22rem",
                    max_height="60vh",
                    overflow_y="auto",
                ),
            ),
        ),
        spacing="1",
        align_items="start",
        width="100%",
        max_width="16rem",
    )


def _cell_value(
    text: rx.Var[str],
    best: rx.Var[bool],
    missing: rx.Var[bool],
    kind: rx.Var[str],
    long: rx.Var[bool],
    add_href: rx.Var[str],
) -> rx.Component:
    return rx.cond(
        kind == "notes",
        _notes_value(text, missing, long),
        rx.vstack(
            _value(text, best, missing, kind),
            rx.cond(add_href != "", _add_rate_link(add_href)),
            spacing="1",
            align_items="start",
        ),
    )


def _column_head(c: rx.Var[ColumnVM], *, wide: bool = True) -> rx.Component:
    updating = S.updating.contains(c.tracked_id)
    return rx.vstack(
        rx.hstack(
            creator_avatar(c.avatar_url, c.initials, "3"),
            rx.vstack(
                rx.link(rx.text(c.name, size="2", weight="bold"), href=c.href),
                # breaks after «.» or «_» when it must, never mid-word
                mono(c.handle_wrap, size="1", overflow_wrap="break-word"),
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
        rx.cond(c.measured != "", rx.text(c.measured, size="1", color=T.TEXT_MUTED)),
        rx.cond(c.few_note != "", tone_badge(c.few_note, "warn", icon="info")),
        spacing="1",
        align_items="start",
        width="100%",
        # a table column keeps room for a name; a phone column takes half the screen
        min_width="10rem" if wide else "0",
    )


def _cell(cell: rx.Var[CellVM]) -> rx.Component:
    return rx.table.cell(
        _cell_value(cell.text, cell.best, cell.missing, cell.kind, cell.long, cell.add_href),
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
            rx.text(c.freshness_short, size="2", color=T.TEXT_MUTED),
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
                        # the kit's table skin shouts headers in capitals; a name does not
                        lambda c: rx.table.column_header_cell(
                            _column_head(c), text_transform="none", letter_spacing="normal"
                        ),
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
        _cell_value(item.text, item.best, item.missing, item.kind, item.long, item.add_href),
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
        rx.cond(
            comparison.mixed_note != "",
            rx.text(comparison.mixed_note, size="2", color=T.TEXT_MUTED, role="note"),
        ),
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
