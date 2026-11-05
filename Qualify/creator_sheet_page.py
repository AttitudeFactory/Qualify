"""The creator's sheet — `/creadores/[creator_id]` (Delivery 1, m-24946129; UX
`docs/ux-creadores.md` §2.3).

What matters first and in words; the detail below. One column on a phone; on a computer
the four figures in a row and the lists in two columns. Every figure is a `stat_card`
whose `hint` is always visible (a phone has no hover) plus a «¿Cómo lo contamos?»
popover opened with a tap. «Sin dato» where Instagram gives nothing — never 0.

«Actualizar» (`soft`) is the one paid call of the screen and runs in the background:
the old sheet stays on screen while it reads (§6.1). With stale data (backend
`STALE_DAYS`) a `warn` callout above the figures carries the same button (§6.3).
«Quitar de tu lista» asks first (`rx.alert_dialog`) and lands on the list with
«Quitaste a @x de tu lista.» on top (N3).
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
    toned_callout,
)
from .creators_state import CreatorSheetState
from .creators_vm import (
    ARCHIVE,
    ARCHIVE_CONFIRM,
    CANCEL,
    COMPARE_WITH_OTHER,
    OPEN_INSTAGRAM,
    REVIEW_ANOTHER,
    SHEET_COLLABS,
    SHEET_STANDOUT,
    SHEET_TOP,
    SHEET_WORKS,
    YOUNG_REEL,
    ReelVM,
    StatVM,
    TagVM,
)
from .ui import (
    app_shell,
    callout,
    card,
    empty_state,
    loading_spinner,
    media_thumb,
    mono,
    page_body,
    page_header,
    section,
    skeleton_card,
    skeleton_rows,
    stat_card,
    tag,
)
from .ui import tokens as T

S = CreatorSheetState


def _stat(s: rx.Var[StatVM]) -> rx.Component:
    return rx.box(
        rx.cond(
            s.missing,
            stat_card(s.label, s.value, tone="neutral", hint=s.hint),
            stat_card(s.label, s.value, hint=s.hint),
        ),
        rx.box(help_popover(s.label, s.help), position="absolute", top="0.25rem", right="0.25rem"),
        position="relative",
        width="100%",
    )


def _reel_row(r: rx.Var[ReelVM]) -> rx.Component:
    """A reel: the figure and the date, and the way out to Instagram (N9: says it
    leaves Qualify). No picture: the read carries none we may keep."""
    return rx.link(
        rx.hstack(
            media_thumb("", size="48px", icon="clapperboard", icon_size=20),
            rx.vstack(
                rx.hstack(
                    rx.text(
                        rx.cond(r.lift != "", r.lift + " · " + r.views, r.views),
                        size="2",
                        weight="medium",
                        class_name="q-nums",
                    ),
                    rx.text("· " + r.when, size="2", color=T.TEXT_MUTED),
                    spacing="1",
                    wrap="wrap",
                ),
                rx.hstack(
                    rx.text(OPEN_INSTAGRAM, size="1", color=T.TEXT_MUTED),
                    rx.icon("external-link", size=T.ICON_SM, color=T.TEXT_MUTED),
                    rx.cond(r.young, tag(YOUNG_REEL)),
                    spacing="1",
                    align="center",
                    wrap="wrap",
                ),
                spacing="1",
                align_items="start",
                min_width="0",
            ),
            spacing="3",
            align="center",
            width="100%",
            min_height=TOUCH_MIN,
        ),
        href=r.url,
        is_external=True,
        aria_label=r.label,
        underline="none",
        color="inherit",
        width="100%",
    )


def _tags(items: rx.Var[list[TagVM]]) -> rx.Component:
    return rx.flex(rx.foreach(items, lambda t: tag(t.label, size="2")), gap="0.5rem", wrap="wrap")


def _identity() -> rx.Component:
    sheet = S.sheet
    return rx.vstack(
        rx.hstack(
            creator_avatar(sheet.avatar_url, sheet.initials, "5"),
            rx.vstack(
                rx.hstack(
                    mono(sheet.handle, overflow_wrap="anywhere"),
                    rx.text("·", color=T.TEXT_MUTED),
                    rx.link(
                        OPEN_INSTAGRAM,
                        rx.icon("external-link", size=T.ICON_SM),
                        href=sheet.profile_url,
                        is_external=True,
                        size="2",
                        display="inline-flex",
                        align_items="center",
                        gap="0.25rem",
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.hstack(
                    rx.cond(sheet.stale, stale_badge()),
                    rx.cond(
                        S.refreshing,
                        rx.hstack(
                            loading_spinner("sm"),
                            rx.text("Actualizando…", size="2", color=T.TEXT_MUTED),
                            spacing="2",
                            align="center",
                        ),
                        rx.text(sheet.freshness, size="2", color=T.TEXT_MUTED),
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                spacing="1",
                align_items="start",
                min_width="0",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def _update_button() -> rx.Component:
    return rx.button(
        rx.icon("refresh-cw", size=T.ICON_SM),
        S.update_label,
        variant="soft",
        size="3",
        min_height=TOUCH_MIN,
        loading=S.refreshing,
        on_click=S.refresh,
    )


def _messages() -> rx.Component:
    sheet = S.sheet
    return rx.fragment(
        rx.cond(
            S.refresh_message != "",
            toned_callout(S.refresh_message, S.refresh_tone),
        ),
        rx.cond(
            S.refresh_done & ~S.refreshing,
            callout("Listo: los datos son de hoy.", "ok"),
        ),
        rx.cond(
            sheet.status_message != "",
            toned_callout(sheet.status_message, sheet.status_tone),
        ),
        rx.cond(
            sheet.stale & ~S.refreshing,
            action_callout(sheet.stale_message, _update_button()),
        ),
        rx.cond(sheet.no_reels != "", callout(sheet.no_reels, "warn")),
        rx.cond(sheet.few_reels != "", callout(sheet.few_reels, "info")),
    )


def _figures() -> rx.Component:
    sheet = S.sheet
    return rx.vstack(
        rx.grid(
            rx.foreach(sheet.stats, _stat),
            columns=rx.breakpoints(initial="2", lg="4"),
            spacing="3",
            width="100%",
        ),
        rx.cond(sheet.cadence != "", rx.text(sheet.cadence, size="3")),
        spacing="3",
        width="100%",
    )


def _top_section() -> rx.Component:
    sheet = S.sheet
    return section(
        SHEET_TOP,
        rx.cond(
            sheet.top_reels.length() > 0,
            rx.vstack(rx.foreach(sheet.top_reels, _reel_row), spacing="2", width="100%"),
            rx.text("Todavía no hay reels con vistas para mostrar.", size="2"),
        ),
    )


def _standout_section() -> rx.Component:
    sheet = S.sheet
    return section(
        SHEET_STANDOUT,
        rx.text(sheet.standout_sentence, size="2"),
        rx.vstack(rx.foreach(sheet.standout_reels, _reel_row), spacing="2", width="100%"),
        rx.cond(
            sheet.standout_more.length() > 0,
            rx.accordion.root(
                rx.accordion.item(
                    header="Ver los demás",
                    content=rx.vstack(
                        rx.foreach(sheet.standout_more, _reel_row), spacing="2", width="100%"
                    ),
                    value="more",
                ),
                collapsible=True,
                type="single",
                variant="ghost",
                width="100%",
            ),
        ),
    )


def _works_section() -> rx.Component:
    sheet = S.sheet
    return section(
        SHEET_WORKS,
        rx.cond(
            sheet.duration_sentence != "",
            rx.text(sheet.duration_sentence, size="2"),
            rx.text(
                "Todavía no hay reels suficientes para saber qué duración le va mejor.", size="2"
            ),
        ),
        rx.cond(
            sheet.audios.length() > 0,
            rx.vstack(
                rx.text("Audios que más usa:", size="2", weight="medium"),
                _tags(sheet.audios),
                spacing="2",
                width="100%",
            ),
        ),
    )


def _collabs_section() -> rx.Component:
    sheet = S.sheet
    return section(
        SHEET_COLLABS,
        rx.text(sheet.collab_sentence, size="2"),
        rx.cond(
            sheet.coauthor_sentence != "",
            rx.vstack(
                rx.text(sheet.coauthor_sentence, size="2"),
                _tags(sheet.collaborators),
                spacing="2",
                width="100%",
            ),
        ),
    )


def _foot() -> rx.Component:
    sheet = S.sheet
    return rx.vstack(
        rx.cond(sheet.trust != "", rx.text(sheet.trust, size="1", color=T.TEXT_MUTED)),
        rx.cond(sheet.hidden_note != "", rx.text(sheet.hidden_note, size="1", color=T.TEXT_MUTED)),
        rx.cond(
            S.primary_compare,
            rx.link(
                rx.button(COMPARE_WITH_OTHER, size="3", min_height=TOUCH_MIN, width="100%"),
                href=S.compare_href,
                width="100%",
                max_width="26rem",
            ),
            rx.link(
                rx.button(REVIEW_ANOTHER, size="3", min_height=TOUCH_MIN, width="100%"),
                href="/creadores?flujo=agregar&paso=1",
                width="100%",
                max_width="26rem",
            ),
        ),
        rx.button(
            ARCHIVE,
            variant="ghost",
            color_scheme="gray",
            size="3",
            min_height=TOUCH_MIN,
            on_click=S.ask_archive,
        ),
        spacing="3",
        width="100%",
    )


def _archive_dialog() -> rx.Component:
    big = {"size": "3", "min_height": TOUCH_MIN}
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(ARCHIVE),
            rx.alert_dialog.description(
                rx.text.strong(S.handle),
                " deja de aparecer en tu lista. Puedes volver a revisarlo cuando quieras.",
                size="2",
            ),
            rx.cond(S.archive_error != "", callout(S.archive_error, "error", margin_top="1rem")),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button(CANCEL, variant="soft", color_scheme="gray", **big),
                ),
                rx.button(
                    ARCHIVE_CONFIRM,
                    loading=S.archiving,
                    on_click=S.confirm_archive,
                    **big,
                    **T.tone_scheme("error"),
                ),
                justify="end",
                gap="0.75rem",
                margin_top="1.25rem",
                wrap="wrap",
            ),
            max_width="28rem",
        ),
        open=S.archive_open,
        on_open_change=S.set_archive_open,
    )


def _sheet_view() -> rx.Component:
    return rx.vstack(
        _identity(),
        _messages(),
        _figures(),
        rx.grid(
            _top_section(),
            _standout_section(),
            _works_section(),
            _collabs_section(),
            columns=rx.breakpoints(initial="1", lg="2"),
            spacing="5",
            width="100%",
        ),
        _foot(),
        _archive_dialog(),
        spacing="5",
        width="100%",
    )


def _not_read_yet() -> rx.Component:
    """In the list but never read: the sheet has nothing to show yet."""
    return rx.vstack(
        rx.cond(
            S.refresh_message != "",
            toned_callout(S.refresh_message, S.refresh_tone),
        ),
        empty_state(
            "user-search",
            "Todavía no tenemos sus números",
            "Revísalo ahora y en unos segundos ves cuántas personas ven sus reels.",
            action=rx.button(
                rx.cond(S.refreshing, "Revisando…", "Revisar ahora"),
                size="3",
                min_height=TOUCH_MIN,
                loading=S.refreshing,
                on_click=S.refresh,
            ),
        ),
        _foot(),
        _archive_dialog(),
        spacing="4",
        width="100%",
    )


def _loading() -> rx.Component:
    return rx.vstack(
        skeleton_rows(1, height="4rem"),
        rx.grid(
            skeleton_card(2),
            skeleton_card(2),
            skeleton_card(2),
            skeleton_card(2),
            columns=rx.breakpoints(initial="2", lg="4"),
            spacing="3",
            width="100%",
        ),
        skeleton_rows(3),
        spacing="4",
        width="100%",
        aria_busy="true",
    )


def _module_body() -> rx.Component:
    return rx.cond(
        S.loading,
        _loading(),
        rx.cond(
            S.load_error != "",
            card(
                rx.vstack(
                    callout(S.load_error, "error"),
                    rx.link(
                        rx.button("Ir a tus creadores", size="3", min_height=TOUCH_MIN),
                        href="/creadores",
                    ),
                    spacing="3",
                ),
            ),
            rx.cond(S.has_read, _sheet_view(), _not_read_yet()),
        ),
    )


def creator_sheet_index() -> rx.Component:
    off = CreatorsAccessState.access == "off"
    return app_shell(
        page_header(
            rx.cond(off, "Creadores", S.title),
            None,
            rx.cond(S.has_read & ~off, _update_button()),
            # N7: the way back is on top in every state, loaded or not.
            kicker=back_link(),
        ),
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
                _module_body(),
            ),
        ),
    )
