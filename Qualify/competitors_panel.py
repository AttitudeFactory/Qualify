"""«Tus competidores» — RF-05's panel (m-25119465), moved by m-25142823 from the reels bar
to «Negocios parecidos al tuyo» (`brand_kit_editor._referentes_section`, Deivid
2026-11-27): the reels bar's «Competidores» switches the side of the reels now.

The owner sees their competitors (the accounts marked «Compite contigo» on the board of the
same section), marks more or takes one off (through the board's own events, so the board
saves the label), ticks up to 6 for the Monday run, and asks «Ver sus reels ahora» for
any other — the read Deivid signed (RF-05): it only QUEUES, the reels-worker pays inside
the business's daily cap. Nothing else here calls a vendor or the model.

The logic stays where it was, in `DiscoverReelsState` (its rows, `toggle_weekly`,
`read_competitor`, `refresh_competitors`), so the reels screen and this section share one
state; this section adds only its own free read of the rows (`load_competitors`) and the
browser clock that follows a manual read while the section is on screen. The pieces are
the system's: a `surface` button that opens the `drawer` — from the bottom on a phone, from
the right on a wider window — with the same 44 px option rows as the reels filters.
"""

from __future__ import annotations

import reflex as rx
from qualify_api.referentes.competitors import STATE_READING

from . import reels_competitors_vm, reels_filters_vm
from .creative_wizard_pages import BrandConnectState
from .discover_reels import (
    _CHIP_PAD,
    _ELLIPSIS,
    _TARGET,
    PHONE_MEDIA,
    DiscoverReelsState,
    _option_row,
    _ticker,
)
from .ui import callout, drawer, loading_spinner, signal_pill
from .ui import tokens as T

#: The section's opener: the drawer gives the focus back to it when it closes.
COMPETITORS_OPENER_ID = "competitors-panel"
RIVALS_FOCUS_SCRIPT = (
    "window.setTimeout(function () {"
    f" var b = document.getElementById('{COMPETITORS_OPENER_ID}');"
    " if (b && b.offsetParent !== null) { b.focus(); }"
    "}, 0);"
)


def _read_state(row: rx.Var[dict[str, str]]) -> rx.Component:
    """Under a row, today's «Ver sus reels ahora»: reading, done, a limit or a failure, in
    the tone of each (`reels_competitors_vm.STATE_TONES`)."""
    message = row["message"].to(str)
    return rx.match(
        row["tone"],
        ("info", callout(message, "info")),
        ("ok", callout(message, "ok")),
        ("warn", callout(message, "warn")),
        ("error", callout(message, "error")),
        rx.fragment(),
    )


def _competitor_row(row: rx.Var[dict[str, str]]) -> rx.Component:
    """One competitor: a 44 px checkbox row («leemos cada lunes») and, outside the 6,
    «Ver sus reels ahora». The button drops under the name on a phone."""
    S = DiscoverReelsState
    key = row["key"].to(str)
    weekly = row["weekly"].to(str) != ""
    busy = S.competitor_busy == key
    read_now = rx.button(
        rx.cond(busy, loading_spinner("sm"), rx.icon("play", size=14, aria_hidden="true")),
        reels_competitors_vm.READ_NOW,
        variant="soft",
        size="2",
        min_height="44px",
        on_click=S.read_competitor(key),
        disabled=(S.competitor_busy != "") | (row["state"].to(str) == STATE_READING),
        aria_busy=rx.cond(busy, "true", "false"),
        aria_label=reels_competitors_vm.READ_NOW + ": " + row["label"].to(str),
    )
    # back to the board's «sin clasificar» (the board saves it: set/clear label)
    remove = rx.button(
        rx.icon("x", size=14, aria_hidden="true"),
        reels_competitors_vm.REMOVE_LABEL,
        variant="ghost",
        color_scheme="gray",
        size="2",
        min_height="44px",
        margin="0",
        on_click=BrandConnectState.unmark_account(key),
        disabled=S.competitor_busy != "",
        aria_label=reels_competitors_vm.REMOVE_LABEL + ": " + row["label"].to(str),
    )
    return rx.vstack(
        rx.flex(
            rx.box(
                _option_row(
                    row["label"].to(str),
                    weekly,
                    S.toggle_weekly(key),
                    role="checkbox",
                    detail=row["detail"].to(str),
                ),
                flex="1 1 14rem",
                min_width="0",
            ),
            rx.cond(weekly, rx.fragment(), read_now),
            remove,
            wrap="wrap",
            align="center",
            spacing="2",
            width="100%",
        ),
        _read_state(row),
        spacing="1",
        width="100%",
        role="listitem",
    )


def _candidate_row(account: rx.Var[dict[str, str]]) -> rx.Component:
    """One account of the board that is not a competitor: «@handle» over where it is on the
    board (Sin clasificar / Te inspira / No va contigo) and «Compite contigo», which moves it
    — the board's own `move_account`, saved by the board (set label)."""
    handle = account["handle"].to(str)  # the board's card already says «@user»
    place = rx.match(
        account["bucket"].to(str),
        *((bucket, words) for bucket, words in reels_competitors_vm.BUCKET_WORDS.items()),
        "",
    )
    return rx.flex(
        rx.vstack(
            rx.text(handle, size="2", weight="medium", **_ELLIPSIS),
            rx.text(place, size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
            flex="1 1 12rem",
            min_width="0",
        ),
        rx.button(
            rx.icon("swords", size=14, aria_hidden="true"),
            reels_competitors_vm.ADD_BUTTON,
            variant="soft",
            size="2",
            min_height="44px",
            on_click=BrandConnectState.move_account(account["key"].to(str), "competencia"),
            aria_label=reels_competitors_vm.ADD_BUTTON + ": " + handle,
        ),
        wrap="wrap",
        align="center",
        gap="0.5rem",
        width="100%",
        role="listitem",
    )


def _candidates() -> rx.Component:
    """«Agregar competidores»: the board's accounts that are not competitors yet (the same
    list the board above sorts), each with «Compite contigo»."""
    board = BrandConnectState
    return rx.vstack(
        rx.text(reels_competitors_vm.ADD_TITLE, size="2", weight="medium", as_="div"),
        rx.cond(
            board.discovered_accounts.length() > board.competencia_accounts.length(),
            rx.vstack(
                rx.foreach(
                    board.discovered_accounts,
                    lambda account: rx.cond(
                        account["bucket"].to(str) != "competencia", _candidate_row(account)
                    ),
                ),
                spacing="2",
                width="100%",
                role="list",
                aria_label=reels_competitors_vm.ADD_TITLE,
            ),
            rx.text(reels_competitors_vm.NO_CANDIDATES, size="2", color=T.TEXT_MUTED),
        ),
        spacing="2",
        width="100%",
        padding_top="0.75rem",
        border_top=T.BORDER,
    )


def competitors_opener() -> rx.Component:
    """«Elegir competidores» — opens the drawer from the bottom on a phone (a window of
    `PHONE_MAX_PX` or less) and from the right on a wider one, the rows read again as it
    opens; closed, the focus goes back to it (`RIVALS_FOCUS_SCRIPT`). While a manual read
    is in flight it shows the spinner. Its words are its accessible name (WCAG 2.5.3);
    `title` says the count («Tus competidores: 3 de 6 los revisamos cada lunes»)."""
    S = DiscoverReelsState
    return rx.button(
        rx.cond(
            S.competitors_reading,
            loading_spinner("sm"),
            rx.icon("users", size=T.ICON_SM, aria_hidden="true"),
        ),
        rx.text(reels_competitors_vm.OPENER_LABEL, as_="span", min_width="0", **_ELLIPSIS),
        type="button",
        id=COMPETITORS_OPENER_ID,
        on_click=rx.call_script(PHONE_MEDIA, callback=S.open_competitors),
        variant="surface",
        size="2",
        min_height=_TARGET,
        overflow="hidden",
        title=S.competitors_label,
        flex_shrink="0",
        max_width="100%",
        aria_haspopup="dialog",
        aria_expanded=rx.cond(S.competitors_open, "true", "false"),
        **_CHIP_PAD,
    )


def _competitors_drawer(*, bottom: bool) -> rx.Component:
    """The competitors panel in the system's `drawer`: the rows (ticking saves the brand's
    labels; «Ver sus reels ahora» only queues the read, the reels-worker pays inside the
    daily cap) and «Listo». Its clock is NOT here (`competitors_section` mounts it), so
    closing the drawer never stops a read's follow-up."""
    S = DiscoverReelsState
    body = rx.vstack(
        rx.cond(S.competitor_error != "", callout(S.competitor_error, "warn")),
        rx.cond(
            S.competitor_rows.length() > 0,
            rx.vstack(
                signal_pill(S.competitors_count, "accent"),
                rx.vstack(
                    rx.foreach(S.competitor_rows, _competitor_row),
                    spacing="2",
                    width="100%",
                    role="list",
                    aria_label=reels_competitors_vm.PICKER_TITLE,
                ),
                spacing="3",
                width="100%",
            ),
            rx.text(reels_competitors_vm.SECTION_EMPTY, size="2", color=T.TEXT_MUTED),
        ),
        _candidates(),
        spacing="3",
        width="100%",
    )
    foot = rx.hstack(
        rx.spacer(),
        rx.button(
            reels_filters_vm.DONE_LABEL,
            size="3",
            min_height="44px",
            on_click=S.close_competitors,
        ),
        width="100%",
        align="center",
    )
    shown = S.competitors_bottom if bottom else ~S.competitors_bottom
    return drawer(
        body,
        open=S.competitors_open & shown,
        on_open_change=S.competitors_changed,
        title=reels_competitors_vm.PICKER_TITLE,
        description=reels_competitors_vm.PICKER_BODY,
        footer=foot,
        side="bottom" if bottom else "right",
        on_close_auto_focus=rx.call_script(RIVALS_FOCUS_SCRIPT).prevent_default,
    )


def competitors_section() -> rx.Component:
    """«Tus competidores» inside «Negocios parecidos al tuyo» (m-25142823), on top, before
    the board (Deivid, 2026-11-27): one line — its name, what it does, how many the Monday
    run reads («3 de 6 marcados») and «Elegir competidores», which opens the panel. Always
    in view: with no competitor it says how to mark them (`SECTION_EMPTY`), and the panel
    offers the board's accounts. Mounting it reads the rows (`load_competitors`, Postgres,
    free) and opens the panel when the reels' «Cambiar competidores» asked for it
    (`open_on_arrival`); while a manual read is in flight the browser clock follows it,
    here as on the reels screen."""
    S = DiscoverReelsState
    has_rows = S.competitor_rows.length() > 0
    line = rx.flex(
        rx.vstack(
            rx.text(reels_competitors_vm.PICKER_TITLE, size="2", weight="medium", as_="div"),
            rx.text(
                rx.cond(
                    has_rows, reels_competitors_vm.SECTION_BODY, reels_competitors_vm.SECTION_EMPTY
                ),
                size="2",
                color=T.TEXT_MUTED,
                as_="div",
            ),
            spacing="1",
            align_items="start",
            flex="1 1 16rem",
            min_width="0",
        ),
        rx.hstack(
            rx.cond(has_rows, signal_pill(S.competitors_count, "accent")),
            competitors_opener(),
            spacing="2",
            align="center",
            flex_shrink="0",
            max_width="100%",
        ),
        wrap="wrap",
        align="center",
        gap="0.75rem",
        width="100%",
        padding_bottom="0.75rem",
        border_bottom=T.BORDER,
    )
    return rx.box(
        line,
        _competitors_drawer(bottom=False),
        _competitors_drawer(bottom=True),
        rx.cond(S.competitors_reading, _ticker(S.refresh_competitors)),
        on_mount=[S.load_competitors, rx.call_script(PHONE_MEDIA, callback=S.open_on_arrival)],
        width="100%",
    )


__all__ = [
    "COMPETITORS_OPENER_ID",
    "RIVALS_FOCUS_SCRIPT",
    "competitors_opener",
    "competitors_section",
]
