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

«Lo que cobra» (m-24955847): what the owner wrote down about the creator's price — the
lowest price («Desde 150.000 pesos») and free text on how they work. It lives on the
tracked creator, so it shows (and can be changed) before the first read too. The
drawer has its own address, `?flujo=tarifa&paso=1` (N5), which Comparar links to.
Nothing is sent to the creator.
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
    FLOW_RATE,
    OPEN_INSTAGRAM,
    RATE_ADD,
    RATE_AMOUNT_LABEL,
    RATE_AMOUNT_PLACEHOLDER,
    RATE_CHANGE,
    RATE_CURRENCY_LABEL,
    RATE_CURRENCY_OPTIONS,
    RATE_DRAWER_DESCRIPTION,
    RATE_EMPTY,
    RATE_NOTES_LABEL,
    RATE_NOTES_PLACEHOLDER,
    RATE_SAVE,
    RATE_TITLE,
    REVIEW_ANOTHER,
    SHEET_COAUTHORS,
    SHEET_PAID,
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
    drawer,
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
from .ui.flow_history import flow_sync
from .ui.route_history import route_history

S = CreatorSheetState

_NOTES_ID = "q-rate-notes"
_AMOUNT_ID = "q-rate-amount"
_CURRENCY_ID = "q-rate-currency"


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
        # The (?) sits in the card's corner; the label keeps a gutter for it so a long
        # name («Vistas típicas por reel») wraps instead of running under it at 360 px.
        style={"& > * > :first-child": {"paddingRight": "2.5rem"}},
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


def _paid_section() -> rx.Component:
    """Only what Instagram marks «colaboración pagada» — the same name as Comparar's row."""
    return section(SHEET_PAID, rx.text(S.sheet.collab_sentence, size="2"))


def _coauthors_section() -> rx.Component:
    """Accounts it published WITH: brands, but also news outlets and friends — so not
    «marcas» (review 2026-11-04)."""
    sheet = S.sheet
    return rx.cond(
        sheet.coauthor_sentence != "",
        section(
            SHEET_COAUTHORS,
            rx.text(sheet.coauthor_sentence, size="2"),
            _tags(sheet.collaborators),
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


# --- «Lo que cobra» -------------------------------------------------------------------


def _rate_section() -> rx.Component:
    """«Desde 150.000 pesos» first, then how they work (line breaks kept), then when it
    was written. Empty: one sentence and the button — never «0»."""
    rate = S.rate
    return section(
        RATE_TITLE,
        rx.cond(
            rate.has_rate,
            rx.vstack(
                rx.cond(
                    rate.from_text != "",
                    rx.text(rate.from_text, size="5", weight="bold", class_name="q-nums"),
                ),
                rx.cond(
                    rate.notes != "",
                    rx.text(rate.notes, size="2", white_space="pre-line", overflow_wrap="anywhere"),
                ),
                rx.cond(rate.updated != "", rx.text(rate.updated, size="1", color=T.TEXT_MUTED)),
                spacing="2",
                align_items="start",
                width="100%",
            ),
            rx.text(RATE_EMPTY, size="2", color=T.TEXT_MUTED),
        ),
        rx.button(
            rx.cond(
                rate.has_rate, rx.icon("pencil", size=T.ICON_SM), rx.icon("plus", size=T.ICON_SM)
            ),
            rx.cond(rate.has_rate, RATE_CHANGE, RATE_ADD),
            variant="soft",
            size="3",
            min_height=TOUCH_MIN,
            on_click=S.open_rate,
        ),
    )


def _field_label(text: str, field_id: str) -> rx.Component:
    """A visible label tied to its field (`rx.text(as_="label")` drops `htmlFor`)."""
    return rx.el.label(rx.text(text, as_="span", size="2", weight="medium"), html_for=field_id)


def _field_error(message: rx.Var[str], error_id: str) -> rx.Component:
    """The refusal next to its field, read aloud when it appears."""
    return rx.cond(
        message != "",
        rx.text(
            message,
            id=error_id,
            size="2",
            color=T.tone_color("error", 11),
            role="alert",
        ),
    )


def _rate_form() -> rx.Component:
    """The price first (the one thing Comparar uses), with its currency beside it; how
    the creator works is optional and comes after."""
    return rx.vstack(
        rx.vstack(
            _field_label(RATE_AMOUNT_LABEL, _AMOUNT_ID),
            rx.flex(
                rx.input(
                    id=_AMOUNT_ID,
                    value=S.rate_amount_input,
                    on_change=S.set_rate_amount,
                    placeholder=RATE_AMOUNT_PLACEHOLDER,
                    input_mode="decimal",
                    size="3",
                    min_height=TOUCH_MIN,
                    flex="1 1 9rem",
                    min_width="0",
                    custom_attrs={
                        "enterKeyHint": "done",
                        "autoComplete": "off",
                        "aria-describedby": "q-rate-amount-error",
                    },
                ),
                rx.select.root(
                    rx.select.trigger(
                        id=_CURRENCY_ID,
                        aria_label=RATE_CURRENCY_LABEL,
                        min_height=TOUCH_MIN,
                        width="100%",
                    ),
                    rx.select.content(
                        *[rx.select.item(name, value=code) for code, name in RATE_CURRENCY_OPTIONS]
                    ),
                    value=S.rate_currency_input,
                    on_change=S.set_rate_currency,
                    size="3",
                ),
                gap="0.5rem",
                width="100%",
                align="center",
                wrap="wrap",
            ),
            _field_error(S.rate_amount_error, "q-rate-amount-error"),
            spacing="1",
            width="100%",
        ),
        rx.vstack(
            _field_label(RATE_NOTES_LABEL, _NOTES_ID),
            rx.text_area(
                id=_NOTES_ID,
                value=S.rate_notes_input,
                on_change=S.set_rate_notes,
                placeholder=RATE_NOTES_PLACEHOLDER,
                rows="5",
                size="3",
                width="100%",
                custom_attrs={"aria-describedby": "q-rate-notes-count q-rate-notes-error"},
            ),
            rx.text(
                S.rate_counter,
                id="q-rate-notes-count",
                size="1",
                color=rx.cond(S.rate_notes_over, T.tone_color("error", 11), T.TEXT_MUTED),
                align="right",
                width="100%",
            ),
            _field_error(S.rate_notes_error, "q-rate-notes-error"),
            spacing="1",
            width="100%",
        ),
        rx.cond(S.rate_error != "", callout(S.rate_error, "error")),
        spacing="4",
        width="100%",
    )


def _rate_footer() -> rx.Component:
    return rx.hstack(
        rx.button(
            CANCEL,
            variant="soft",
            color_scheme="gray",
            size="3",
            min_height=TOUCH_MIN,
            on_click=S.close_rate,
        ),
        rx.button(
            RATE_SAVE,
            size="3",
            min_height=TOUCH_MIN,
            loading=S.rate_saving,
            on_click=S.save_rate,
        ),
        justify="end",
        spacing="3",
        width="100%",
    )


def _rate_drawer() -> rx.Component:
    return drawer(
        rx.vstack(
            flow_sync(FLOW_RATE, 1, ready=S.rate_ready),
            rx.form(
                _rate_form(),
                on_submit=lambda _data: S.save_rate,
                reset_on_submit=False,
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        open=S.rate_open,
        on_open_change=S.set_rate_open,
        title=RATE_TITLE,
        description=RATE_DRAWER_DESCRIPTION,
        footer=_rate_footer(),
        icon="wallet",
    )


def _sheet_view() -> rx.Component:
    return rx.vstack(
        _identity(),
        _messages(),
        _figures(),
        _rate_section(),
        rx.grid(
            _top_section(),
            _standout_section(),
            _works_section(),
            _paid_section(),
            _coauthors_section(),
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
        _rate_section(),
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
            rx.fragment(
                rx.cond(S.has_read, _sheet_view(), _not_read_yet()),
                _rate_drawer(),
            ),
        ),
    )


def creator_sheet_index() -> rx.Component:
    off = CreatorsAccessState.access == "off"
    return app_shell(
        route_history(S.enter_history, ack=S.history_ack, on_leave=S.leave_sheet),
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
