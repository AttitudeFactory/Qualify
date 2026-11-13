"""Screens of «Stickers y videos de tu marca» (m-24976895, `docs/ux-stickers-videos.md`):
the section in Tu marca with its library and the three-step «Crear para esta temporada»
drawer, the batch in «Por aprobar», and the approved library in «Aprobados»
(m-24986801). Design-system pieces only (`card`, `drawer`,
`step_progress`, `choice_card`, `tone_badge`, `signal_pill`, `callout`, `empty_state`,
`skeleton_card`). Nothing plays by itself: stickers (light animated WebP) move once in
view — with `prefers-reduced-motion` only after a tap — and videos only with their own
controls."""

from __future__ import annotations

import reflex as rx

from .product_sticker_state import ProductStickerState as P
from .product_sticker_ui import product_start_card, product_sticker_drawer, start_card
from .product_sticker_vm import SEASON_START_LINE, SEASON_START_TITLE
from .r2_media import BACKEND_BASE
from .seasonal_state import FLOW_STEPS, SeasonalState
from .seasonal_vm import (
    AI_LINE,
    ANOTHER_AI_YES,
    APPROVE_LABEL,
    APPROVE_READY_LABEL,
    APPROVED_EMPTY_TEXT,
    APPROVED_EMPTY_TITLE,
    APPROVED_PILL,
    ARCHIVE_LABEL,
    ARCHIVED_TITLE,
    BACK_LABEL,
    BATCH_FAILED,
    CANCEL_LABEL,
    CHECKING_PRICE,
    CREATE_HREF,
    CREATE_LABEL,
    CREATING_LABEL,
    DELETE_LABEL,
    DRAFTS_ROUTE,
    EMPTY_TEXT,
    EMPTY_TITLE,
    FREE_LINE,
    FREE_TITLE,
    GO_DRAFTS_LABEL,
    HEAVY_PILL,
    KIND_ALL,
    KIND_ALL_LABEL,
    KIND_EMPTY_ACTION,
    KIND_EMPTY_TITLE,
    KIND_FILTER_LABEL,
    KIND_STICKERS_LABEL,
    KIND_VIDEOS_LABEL,
    MAX_OTHER_NAME,
    MODE_AI,
    MODE_FREE,
    NEXT_LABEL,
    NO_PHOTOS_TO_SHOW,
    OTHER_KEY,
    OTHER_NAME_HINT,
    OTHER_NAME_LABEL,
    PENDING_EMPTY_TEXT,
    PENDING_EMPTY_TITLE,
    PREPARING,
    PRODUCT_SEASON_KEY,
    RESTORE_LABEL,
    RETRY_LABEL,
    SECTION_HELP,
    SECTION_TITLE,
    SEND_HINT,
    SEND_LINK_HREF,
    SEND_LINK_LABEL,
    STICKER,
    TAP_TO_SEE,
    TRY_AGAIN_LABEL,
    UPLOAD_LOGO_LABEL,
    VIDEO,
    AiPhotoVM,
    OccasionVM,
    SeasonalItemVM,
    SeasonVM,
)
from .ui import (
    callout,
    card,
    choice_card,
    drawer,
    empty_state,
    media_thumb,
    signal_pill,
    skeleton_card,
    tone_badge,
)
from .ui import tokens as T
from .ui.route_history import route_history
from .ui.steps import step_progress

S = SeasonalState
_TAP = "44px"
_OTHER_ID = "seasonal-other-name"
_OTHER_COUNT_ID = "seasonal-other-count"
_KIND_ID = "approved-kind-filter"


def fold_summary(label: str | rx.Var[str]) -> rx.Component:
    """The summary row of a folded list (`rx.el.details(class_name="q-fold")`): a chevron
    that turns when it opens (the flex row hides the browser's triangle) and the name with
    its count, ≥ 44 px (m-24986801)."""
    return rx.el.summary(
        rx.icon("chevron-right", size=T.ICON_SM, class_name="q-fold-chevron", aria_hidden="true"),
        rx.text(label, size="2", weight="medium", as_="span"),
        cursor="pointer",
        min_height=_TAP,
        display="flex",
        align_items="center",
        gap="0.35rem",
    )


def _button(label, on_click, *, icon: str | None = None, solid: bool = False, **props):
    kids = [rx.icon(icon, size=T.ICON_SM)] if icon else []
    return rx.button(
        *kids,
        label,
        on_click=on_click,
        variant="solid" if solid else "soft",
        size="2",
        min_height=_TAP,
        **({} if solid else T.tone_scheme("neutral")),
        **props,
    )


# ======================================================================================
# Tu marca › «Stickers y videos de tu marca»
# ======================================================================================


def _season_row(season: SeasonVM) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.text(season.label, size="2", weight="medium"),
            rx.text(season.counts_label, size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
            flex="1",
            min_width="0",
        ),
        rx.cond(
            season.archived,
            _button(RESTORE_LABEL, S.restore(season.key), icon="rotate-ccw"),
            # m-25017912: product stickers do not end with a season — never archived
            rx.cond(
                season.key != PRODUCT_SEASON_KEY,
                rx.button(
                    ARCHIVE_LABEL,
                    on_click=S.archive(season.key),
                    variant="ghost",
                    size="2",
                    min_height=_TAP,
                    **T.tone_scheme("neutral"),
                ),
            ),
        ),
        width="100%",
        align="center",
        spacing="3",
        padding_y="0.25rem",
    )


def _start_cards() -> rx.Component:
    """Two ways to start, each with its benefit and its price (UX doc §1): the free season
    first, then the owner's product (m-25017912). One column on a phone."""
    return rx.grid(
        # with nothing yet, the empty state above already offers the season's button
        rx.cond(
            ~S.is_empty,
            start_card(
                SEASON_START_TITLE,
                SEASON_START_LINE,
                "",
                _button(CREATE_LABEL, S.open_flow, icon="plus", solid=True),
                icon="calendar-heart",
            ),
        ),
        product_start_card(),
        columns=rx.breakpoints(initial="1", sm="2"),
        spacing="2",
        width="100%",
    )


def brand_section() -> rx.Component:
    """The section in Tu marca: the library by season (the coming one first), the
    archived ones folded, and «Crear para esta temporada»."""
    return card(
        rx.vstack(
            rx.hstack(
                rx.center(
                    rx.icon("sticker", size=T.ICON_MD, aria_hidden="true"),
                    width="2.5rem",
                    height="2.5rem",
                    min_width="2.5rem",
                    border_radius=T.RADIUS_CONTROL,
                    **T.tone_scheme("info"),
                ),
                rx.vstack(
                    rx.heading(SECTION_TITLE, size="3", as_="h2"),
                    rx.text(SECTION_HELP, size="2", color=T.TEXT_MUTED),
                    spacing="1",
                    align_items="start",
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            rx.cond(
                S.loading,
                skeleton_card(2),
                rx.cond(
                    S.error != "",
                    rx.vstack(
                        callout(S.error, "error"),
                        _button(RETRY_LABEL, S.load, icon="refresh-cw"),
                        spacing="2",
                        width="100%",
                    ),
                    rx.cond(
                        S.is_empty,
                        empty_state(
                            "sticker",
                            EMPTY_TITLE,
                            EMPTY_TEXT,
                            _button(CREATE_LABEL, S.open_flow, icon="plus", solid=True),
                        ),
                        rx.vstack(
                            rx.cond(
                                S.month_spend != "",
                                rx.text(S.month_spend, size="2", color=T.TEXT_MUTED),
                            ),
                            rx.foreach(S.shelf, _season_row),
                            rx.cond(
                                S.archived.length() > 0,
                                rx.el.details(
                                    fold_summary(ARCHIVED_TITLE),
                                    rx.vstack(rx.foreach(S.archived, _season_row), width="100%"),
                                    width="100%",
                                    class_name="q-fold",
                                ),
                            ),
                            spacing="2",
                            width="100%",
                            align_items="start",
                        ),
                    ),
                ),
            ),
            rx.cond(S.action_error != "", callout(S.action_error, "error")),
            _start_cards(),
            create_drawer(),
            product_sticker_drawer(),
            # «Tu producto en sticker» follows the address (`?crear=producto`, each step's
            # `?flujo=sticker-producto&paso=N`) on mount, reload and «atrás»/«adelante»
            route_history(P.enter_history, ack=P.history_ack),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        on_mount=[S.load, S.open_from_query, P.load_start],
        on_unmount=[S.stop_poll, P.stop_poll],
    )


# ======================================================================================
# «Crear para esta temporada» — three steps in a drawer
# ======================================================================================


def _occasion_card(occasion: OccasionVM) -> rx.Component:
    return choice_card(
        rx.vstack(
            rx.text(occasion.label, size="3", weight="medium"),
            rx.cond(occasion.line != "", rx.text(occasion.line, size="2", color=T.TEXT_MUTED)),
            spacing="0",
            align_items="start",
        ),
        selected=S.occasion_key == occasion.key,
        on_select=S.choose_occasion(occasion.key),
        padding="0.75rem 1rem",
        width="100%",
        min_height=_TAP,
    )


def _step_occasion() -> rx.Component:
    return rx.vstack(
        rx.vstack(
            rx.foreach(S.occasions, _occasion_card), spacing="2", width="100%", role="radiogroup"
        ),
        rx.cond(
            S.occasion_key == OTHER_KEY,
            rx.vstack(
                rx.hstack(
                    rx.el.label(
                        rx.text(OTHER_NAME_LABEL, size="2", weight="medium"), html_for=_OTHER_ID
                    ),
                    rx.spacer(),
                    rx.text(
                        S.other_count,
                        size="1",
                        color=T.TEXT_MUTED,
                        id=_OTHER_COUNT_ID,
                        class_name="q-nums",
                    ),
                    width="100%",
                ),
                rx.input(
                    id=_OTHER_ID,
                    value=S.other_name,
                    on_change=S.set_other_name,
                    max_length=MAX_OTHER_NAME,
                    placeholder=OTHER_NAME_HINT,
                    size="3",
                    width="100%",
                    custom_attrs={"aria-describedby": _OTHER_COUNT_ID},
                ),
                spacing="1",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
    )


def _mode_card(mode: str, title, line: str, *, disabled=False) -> rx.Component:
    return choice_card(
        rx.vstack(
            rx.text(title, size="3", weight="medium"),
            rx.text(line, size="2", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
        ),
        selected=S.mode == mode,
        on_select=S.choose_mode(mode),
        disabled=disabled,
        padding="0.75rem 1rem",
        width="100%",
        min_height=_TAP,
    )


def _step_how() -> rx.Component:
    return rx.vstack(
        _mode_card(MODE_FREE, FREE_TITLE, FREE_LINE),
        # offered only with the backend's quote; why not, in its words, otherwise
        # off by configuration: no card; no photo to animate: disabled with the reason
        rx.cond(
            ~S.ai_hidden,
            rx.vstack(
                _mode_card(MODE_AI, S.ai_title, AI_LINE, disabled=~S.ai_ready),
                rx.cond(
                    S.ai_quoting,
                    rx.text(CHECKING_PRICE, size="1", color=T.TEXT_MUTED),
                    rx.cond(
                        S.ai_unavailable != "",
                        rx.text(S.ai_unavailable, size="1", color=T.TEXT_MUTED),
                    ),
                ),
                spacing="2",
                width="100%",
            ),
        ),
        spacing="2",
        width="100%",
        role="radiogroup",
    )


def _ai_photo(photo: AiPhotoVM) -> rx.Component:
    return rx.vstack(
        media_thumb(
            rx.cond(photo.src != "", BACKEND_BASE + photo.src, ""),
            size=None,
            width="100%",
            height="6.5rem",
            alt=photo.title,
            icon="image",
        ),
        rx.text(photo.title, size="1", weight="medium", text_align="left"),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _step_photos() -> rx.Component:
    """m-24976893: WHAT the IA will animate, before paying — read-only in the beta (the
    backend picks the newest approved photo pieces), with the quote's total."""
    return rx.vstack(
        rx.text(S.ai_photos_line, size="2", color=T.TEXT_MUTED),
        rx.cond(
            S.ai_photos.length() > 0,
            rx.grid(
                rx.foreach(S.ai_photos, _ai_photo),
                columns="3",
                spacing="2",
                width="100%",
            ),
            callout(NO_PHOTOS_TO_SHOW, "warn"),
        ),
        rx.text(S.ai_total_line, size="3", weight="bold"),
        rx.text(S.review_line, size="2", color=T.TEXT_MUTED),
        spacing="3",
        width="100%",
    )


def _step_review() -> rx.Component:
    return rx.cond(
        S.mode == MODE_AI,
        _step_photos(),
        rx.vstack(
            rx.text(S.review_line, size="3"),
            spacing="3",
            width="100%",
        ),
    )


def _flow_footer() -> rx.Component:
    return rx.vstack(
        rx.cond(S.flow_error != "", callout(S.flow_error, "warn")),
        rx.cond(
            S.flow_missing,
            rx.flex(
                _button(UPLOAD_LOGO_LABEL, S.upload_logo, icon="image-plus"),
                rx.button(
                    rx.link(
                        rx.icon("images", size=T.ICON_SM),
                        GO_DRAFTS_LABEL,
                        href=DRAFTS_ROUTE,
                        underline="none",
                    ),
                    as_child=True,
                    variant="soft",
                    size="2",
                    min_height=_TAP,
                    **T.tone_scheme("neutral"),
                ),
                gap="2",
                wrap="wrap",
            ),
        ),
        rx.hstack(
            _button(BACK_LABEL, S.flow_back, icon="chevron-left", disabled=S.creating),
            rx.spacer(),
            rx.cond(
                S.flow_step < FLOW_STEPS,
                _button(NEXT_LABEL, S.flow_next, solid=True, disabled=~S.flow_can_next),
                rx.cond(
                    S.mode == MODE_AI,
                    # «Crear 3 videos · unos US$0,15»: no icon, one line at 375 px
                    _button(
                        rx.cond(S.creating, CREATING_LABEL, S.create_label),
                        S.create,
                        solid=True,
                        disabled=S.creating,
                        aria_busy=rx.cond(S.creating, "true", "false"),
                        white_space="nowrap",
                    ),
                    _button(
                        rx.cond(S.creating, CREATING_LABEL, S.create_label),
                        S.create,
                        icon="plus",
                        solid=True,
                        disabled=S.creating,
                        aria_busy=rx.cond(S.creating, "true", "false"),
                    ),
                ),
            ),
            width="100%",
            align="center",
            spacing="2",
        ),
        spacing="2",
        width="100%",
    )


def create_drawer() -> rx.Component:
    return drawer(
        rx.match(
            S.flow_step,
            (1, _step_occasion()),
            (2, _step_how()),
            _step_review(),
        ),
        open=S.flow_open,
        on_open_change=S.set_flow_open,
        title=S.flow_title,
        step=step_progress(S.flow_step, FLOW_STEPS),
        footer=_flow_footer(),
        icon="sticker",
    )


# ======================================================================================
# «Por aprobar» — one card per sticker or video
# ======================================================================================


def _preview(item: SeasonalItemVM) -> rx.Component:
    """Square preview: «Preparando…», the failure, a sticker (moves once in view; with
    reduced motion only after «Toca para ver»), or a video with its own controls — never
    `autoplay`."""
    src = BACKEND_BASE + item.src
    shown = S.shown_ids.contains(item.id)
    return rx.box(
        rx.cond(
            item.preparing,
            rx.center(
                rx.vstack(
                    rx.icon("loader", size=T.ICON_MD, aria_hidden="true"),
                    rx.text(PREPARING, size="1", color=T.TEXT_MUTED),
                    align="center",
                    spacing="1",
                ),
                width="100%",
                height="100%",
            ),
            rx.cond(
                item.failed,
                rx.center(
                    rx.icon("image-off", size=T.ICON_MD, color=T.TEXT_FAINT, aria_hidden="true"),
                    width="100%",
                    height="100%",
                ),
                rx.cond(
                    item.is_video,
                    rx.el.video(
                        src=src,
                        controls=True,
                        muted=True,
                        preload="none",
                        plays_inline=True,
                        width="100%",
                        height="100%",
                        aria_label=item.alt,
                        class_name="q-seasonal-video",
                    ),
                    rx.fragment(
                        rx.image(
                            src=src,
                            alt=item.alt,
                            loading="lazy",
                            width="100%",
                            height="100%",
                            class_name=rx.cond(
                                shown, "q-seasonal-anim is-shown", "q-seasonal-anim"
                            ),
                        ),
                        rx.cond(
                            ~shown,
                            rx.button(
                                rx.icon("play", size=T.ICON_SM),
                                TAP_TO_SEE,
                                on_click=S.show(item.id),
                                variant="soft",
                                size="1",
                                class_name="q-seasonal-tap",
                                **T.tone_scheme("neutral"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        class_name="q-seasonal-preview",
        position="relative",
        width="100%",
        aspect_ratio="1 / 1",
        border_radius=T.RADIUS_CONTROL,
        overflow="hidden",
        background=T.tone_color("neutral", 3),
    )


def _delete_action(item: SeasonalItemVM, busy: rx.Var[bool]) -> rx.Component:
    """«Eliminar» (m-25016851) on every sticker and video, asked first in an alert dialog
    with the same verb on the title and the button (docs/design-system.md §6.2)."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("trash-2", size=T.ICON_SM),
                DELETE_LABEL,
                variant="ghost",
                size="2",
                min_height=_TAP,
                disabled=busy,
                aria_label=DELETE_LABEL + " " + item.alt,
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title(item.delete_title),
            rx.alert_dialog.description(item.delete_text, size="2"),
            rx.flex(
                rx.alert_dialog.cancel(_button(CANCEL_LABEL, rx.noop())),
                rx.alert_dialog.action(
                    rx.button(
                        DELETE_LABEL,
                        on_click=S.delete(item.id),
                        variant="solid",
                        size="2",
                        min_height=_TAP,
                        **T.tone_scheme("error"),
                    ),
                ),
                gap="2",
                justify="end",
                margin_top="1rem",
                wrap="wrap",
            ),
            max_width="26rem",
        ),
    )


def _item_card(item: SeasonalItemVM) -> rx.Component:
    busy = S.busy_ids.contains(item.id)
    return card(
        rx.vstack(
            _preview(item),
            rx.flex(
                tone_badge(item.kind_label, "info"),
                rx.cond(item.heavy, signal_pill(HEAVY_PILL, "warn")),
                rx.cond(item.approved, signal_pill(APPROVED_PILL, "ok")),
                wrap="wrap",
                gap="1",
            ),
            rx.cond(item.caption != "", rx.text(item.caption, size="2", weight="medium")),
            rx.text(
                rx.cond(item.size_label != "", item.size_label + " · ", "") + item.season_label,
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.cond(item.fail_text != "", rx.text(item.fail_text, size="1")),
            rx.cond(
                item.ready,
                rx.flex(
                    _button(APPROVE_LABEL, S.approve(item.id), solid=True, disabled=busy, flex="1"),
                    # an IA piece offers «Pedir otro» only while «Con IA» has a price
                    rx.cond(
                        ~item.paid | (S.ai_redo_cost != ""),
                        _button(item.another_label, S.another(item.id), disabled=busy, flex="1"),
                    ),
                    gap="2",
                    width="100%",
                ),
                rx.cond(
                    item.failed & (~item.paid | (S.ai_redo_cost != "")),
                    _button(
                        item.another_label, S.another(item.id), icon="refresh-cw", disabled=busy
                    ),
                ),
            ),
            rx.cond(
                S.confirm_another == item.id,
                rx.vstack(
                    callout(S.another_question, "warn"),
                    rx.flex(
                        _button(ANOTHER_AI_YES, S.another(item.id), solid=True),
                        _button(CANCEL_LABEL, S.cancel_confirm),
                        gap="2",
                        wrap="wrap",
                    ),
                    spacing="2",
                    width="100%",
                ),
            ),
            # a «Con IA» video being made cannot be deleted yet: its paid task is running
            rx.cond(~(item.paid & item.preparing), _delete_action(item, busy)),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        padding="0.6rem",
    )


def _group(season: SeasonVM) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(season.pending_progress_label, size="3", weight="bold"),
            width="100%",
        ),
        rx.progress(
            value=season.pending_progress,
            max=100,
            width="100%",
            aria_label=season.pending_progress_label,
        ),
        rx.cond(
            season.all_failed,
            rx.vstack(
                callout(BATCH_FAILED, "error"),
                _button(TRY_AGAIN_LABEL, S.load, icon="refresh-cw"),
                spacing="2",
                width="100%",
            ),
        ),
        rx.grid(
            rx.foreach(season.pending_pieces, _item_card),
            # one column on a phone: the two buttons fit side by side at 44 px
            columns=rx.breakpoints(initial="1", xs="2", sm="3", lg="4"),
            spacing="2",
            width="100%",
        ),
        rx.cond(
            season.ready_count > 1,
            _button(
                APPROVE_READY_LABEL + " (" + season.ready_count.to_string() + ")",
                S.ask_approve_ready(season.key),
                icon="check-check",
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _approve_ready_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(APPROVE_READY_LABEL),
            rx.alert_dialog.description(S.confirm_question),
            rx.flex(
                rx.alert_dialog.cancel(_button(CANCEL_LABEL, S.cancel_confirm)),
                rx.alert_dialog.action(
                    _button(APPROVE_LABEL, S.approve_ready, solid=True),
                ),
                gap="2",
                justify="end",
                margin_top="1rem",
                wrap="wrap",
            ),
        ),
        open=S.confirm_season != "",
    )


def drafts_section() -> rx.Component:
    """«Por aprobar» › Stickers y videos: per season, only the pieces still waiting for
    the owner (being prepared, ready, failed — m-24986801); an approved one leaves the
    grid for «Aprobados». Loading, error and empty in this tab's own words."""
    return rx.vstack(
        rx.cond(S.action_error != "", callout(S.action_error, "error")),
        rx.cond(
            S.loading,
            skeleton_card(2),
            rx.cond(
                S.error != "",
                _load_error(),
                rx.cond(
                    S.to_review.length() > 0,
                    rx.vstack(
                        # m-24976893: the month's IA spend, next to what is waiting
                        rx.cond(
                            S.month_spend != "",
                            rx.text(S.month_spend, size="2", color=T.TEXT_MUTED),
                        ),
                        rx.foreach(S.to_review, _group),
                        spacing="4",
                        width="100%",
                    ),
                    rx.cond(
                        S.loaded,
                        empty_state(
                            "sticker",
                            PENDING_EMPTY_TITLE,
                            PENDING_EMPTY_TEXT,
                            _create_link(),
                        ),
                    ),
                ),
            ),
        ),
        _approve_ready_dialog(),
        spacing="4",
        width="100%",
        on_mount=S.load,
        on_unmount=S.stop_poll,
    )


def _load_error() -> rx.Component:
    return rx.vstack(
        callout(S.error, "error"),
        _button(RETRY_LABEL, S.load, icon="refresh-cw"),
        spacing="2",
        width="100%",
    )


def _create_link() -> rx.Component:
    """«Crear para esta temporada»: opens the flow in Tu marca (`?crear=temporada`)."""
    return rx.button(
        rx.link(
            rx.icon("plus", size=T.ICON_SM),
            CREATE_LABEL,
            href=CREATE_HREF,
            underline="none",
        ),
        as_child=True,
        size="2",
        min_height=_TAP,
    )


# ======================================================================================
# «Aprobados» › Stickers y videos (m-24986801, docs/ux-aprobados-y-menus.md §3)
# ======================================================================================


def _kind_filter() -> rx.Component:
    """«Tipo»: Todos · Stickers · Videos, with its label in sight (`&tipo=`)."""
    return rx.flex(
        rx.el.label(
            rx.text(KIND_FILTER_LABEL, size="2", weight="medium", as_="span"),
            html_for=_KIND_ID,
        ),
        rx.select.root(
            rx.select.trigger(id=_KIND_ID, min_height=_TAP, min_width="10rem"),
            rx.select.content(
                rx.select.item(KIND_ALL_LABEL, value=KIND_ALL),
                rx.select.item(KIND_STICKERS_LABEL, value=STICKER),
                rx.select.item(KIND_VIDEOS_LABEL, value=VIDEO),
            ),
            value=S.kind_filter,
            on_change=S.set_kind_filter,
            size="2",
        ),
        gap="0.5rem",
        align="center",
        wrap="wrap",
    )


def _approved_group(season: SeasonVM) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(
                season.label + " · " + season.counts_label,
                size="3",
                weight="bold",
                flex="1",
                min_width="0",
            ),
            rx.cond(
                season.key != PRODUCT_SEASON_KEY,
                rx.button(
                    ARCHIVE_LABEL,
                    on_click=S.archive_from_approved(season.key),
                    variant="ghost",
                    size="2",
                    min_height=_TAP,
                    **T.tone_scheme("neutral"),
                ),
            ),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.grid(
            rx.foreach(season.approved_pieces, _item_card),
            columns=rx.breakpoints(initial="2", sm="3", lg="4"),
            spacing="2",
            width="100%",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _send_hint() -> rx.Component:
    """Where the approved ones are used: inside a WhatsApp chat (spec §3)."""
    return rx.flex(
        rx.text(SEND_HINT, size="2", color=T.TEXT_MUTED),
        rx.link(SEND_LINK_LABEL, href=SEND_LINK_HREF, size="2", weight="medium"),
        gap="0.25rem 0.5rem",
        wrap="wrap",
        align="center",
    )


def _archived_fold() -> rx.Component:
    return rx.cond(
        S.archived.length() > 0,
        rx.el.details(
            fold_summary(S.archived_title),
            rx.vstack(rx.foreach(S.archived, _season_row), width="100%"),
            width="100%",
            class_name="q-fold",
        ),
    )


def approved_section() -> rx.Component:
    """«Aprobados» › Stickers y videos: by season (the coming one first), filtered by
    kind, each season with «Archivar»; archived ones folded with «Volver a usar»."""
    return rx.vstack(
        rx.cond(S.action_error != "", callout(S.action_error, "error")),
        rx.cond(
            S.loading,
            skeleton_card(2),
            rx.cond(
                S.error != "",
                _load_error(),
                rx.cond(
                    S.approved_count > 0,
                    rx.vstack(
                        _kind_filter(),
                        rx.cond(
                            S.approved_library.length() > 0,
                            rx.vstack(
                                rx.foreach(S.approved_library, _approved_group),
                                _send_hint(),
                                spacing="4",
                                width="100%",
                            ),
                            empty_state(
                                "filter",
                                KIND_EMPTY_TITLE,
                                "",
                                _button(KIND_EMPTY_ACTION, S.set_kind_filter(KIND_ALL)),
                            ),
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    rx.cond(
                        S.loaded,
                        empty_state(
                            "sticker",
                            APPROVED_EMPTY_TITLE,
                            APPROVED_EMPTY_TEXT,
                            _create_link(),
                        ),
                    ),
                ),
            ),
        ),
        _archived_fold(),
        spacing="4",
        width="100%",
        on_mount=S.load,
        on_unmount=S.stop_poll,
    )
