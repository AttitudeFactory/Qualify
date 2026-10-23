"""Mentions dashboard blocks + backwards-compatible re-exports.

The shell pieces (``sidebar``, ``session_badge``) now live in ``Qualify/ui/layout.py``
and are re-exported here so older imports keep working; new code should import from
``.ui`` directly. What remains in this module is specific to the mentions dashboard
(QUA-49; paginated, auto-refreshed, one meaning per column since QUA-152).

Layout (QUA-152, founder review 2026-10-13): the page header carries only the title. The
table lives in its own panel (a ``card``) whose header holds this module's refresh —
never beside the app-wide theme toggle — and whose footer holds the compact pager. The
summary cards describe the scope (account + period) and do not move with a search.

RESULTADOS-1 (m-24843000): each summary card filters the list with one tap (N11); a
negative mention says what to do and links to answer it on the network (N9, N13); every
reason is on screen, long texts open with «Ver más», and at 360 px the filters fit one
line with the rest in «Más filtros» and every target is ≥ 44 px (N12).
"""

import reflex as rx

from .mentions_paging import (
    ALL_SENTIMENTS,
    NEW_MENTIONS_BUTTON,
    ORIGIN_OPTIONS,
    PERIOD_OPTIONS,
    SENTIMENT_OPTIONS,
)
from .mentions_provider import NO_LINK
from .results_state import ResultsState
from .state import DashboardState, MentionRow
from .ui import (
    callout,
    card,
    drawer,
    empty_state,
    mono,
    platform_badge,
    sentiment_badge,
    session_badge,
    sidebar,
    signal_pill,
    skeleton_rows,
    stat_card,
    tag,
)
from .ui import tokens as T

__all__ = [
    "filter_bar",
    "mentions_body",
    "mentions_table",
    "platform_badge",
    "sentiment_badge",
    "session_badge",
    "sidebar",
    "stat_card",
    "stats_row",
    "mentions_intro",
]

# QUA-152: the refresh heartbeat (`rx.moment`'s `interval`, a browser-side setInterval —
# same mechanism as `/inbox`'s QUA-89 timer). 45 s: inside the ticket's 30–60 s window.
_REFRESH_INTERVAL_MS = 45 * 1000

# The "Mención" column has a fixed width (founder review 2026-10-13): a long mention is
# cut with an ellipsis in the row and opened in full in place with «Ver más» — no hover card
# since RESULTADOS-1: nothing on this screen depends on a mouse (N12).
_MENTION_COL_WIDTH = rx.breakpoints(initial="220px", xl="260px")

# Responsive layout (2026-10-13): the 8-column table from Radix `lg` (1280 px) up — below
# that the sidebar leaves ~700 px, measured too narrow for it. Below it (phones, tablets,
# small laptops) each mention is a card, the pager shrinks to "‹ Página n de N ›" and the
# filters fold into «Periodo» + «Más filtros» (RESULTADOS-1).
#
# The switch is a CSS class, not `rx.breakpoints` on `display` (2026-10-16). In the exported
# build the global stylesheet is linked twice (once in the prerendered head, once more by the
# hydration, AFTER emotion's style tags), so Radix's `.rt-Box { display: block }` outranked
# emotion's media rules and the table and the cards showed at once. The rules live in
# assets/qualify-listen.css, which is compiled INTO that global stylesheet after Radix's
# own rules — the `.q-wa-chats` pattern — so they win in every copy of it.
_TABLE_ONLY = "q-mentions-table-only"
_CARDS_ONLY = "q-mentions-cards-only"
# Breathing room after the mention, so its column never reads as glued to Sentimiento.
_MENTION_GUTTER = "2rem"

# Every tap target on this screen (N12): pager, filters, buttons, links.
_TARGET = "44px"

MENTIONS_INTRO = "Lo que la gente publica o comenta cuando etiqueta a tu negocio."


def _refresh_timer() -> rx.Component:
    """Hidden heartbeat: every tick re-reads the current page under the same snapshot and
    counts new mentions (`DashboardState.refresh_tick`). It unmounts — and stops — with
    the page; nothing runs server-side between ticks."""
    return rx.moment(
        interval=_REFRESH_INTERVAL_MS,
        on_change=lambda _tick: DashboardState.refresh_tick,
        display="none",
    )


def _muted(value: rx.Var | str, **props) -> rx.Component:
    return rx.text(value, size="2", color=T.TEXT_MUTED, **props)


def mentions_intro() -> rx.Component:
    """What the tab is about, under Resultados' tab strip (m-24843003). Channel-neutral on
    purpose (founder review 2026-10-13): mentions will come from several channels; the
    channel of each one is its own column, never the title."""
    return _muted(MENTIONS_INTRO)


def _sentiment_card(
    label: str,
    value: rx.Var,
    tone: str,
    pick: str,
    hint: rx.Var | None = None,
) -> rx.Component:
    """One summary figure that is also the way to the list it counts (N11, RESULTADOS-1):
    a tap shows only those mentions, a second tap shows all again. The line under the
    figure says so on screen — a touch screen has no hover to hint it. The card sits in a
    native button, so Enter and Space work from the keyboard, the app's focus ring shows,
    and `aria-pressed` tells a screen reader which one is on."""
    active = DashboardState.sentiment_filter == pick
    surface = card(
        rx.text(label, size="2", color=T.TEXT_MUTED),
        # A text, not a heading: a figure is not a section of the document outline.
        rx.text(
            value.to_string(),
            size="7",
            weight="bold",
            color=T.tone_color(tone, 10),
            class_name="q-nums",
            line_height="1.2",
        ),
        *([rx.text(hint, size="1", color=T.TEXT_FAINT)] if hint is not None else []),
        rx.text(
            rx.cond(active, "Viendo solo estas", "Ver solo estas")
            if pick != ALL_SENTIMENTS
            else rx.cond(active, "Viendo todas", "Ver todas"),
            size="1",
            weight="medium",
            color=rx.cond(active, T.tone_color(tone, 11), T.TEXT_MUTED),
        ),
        interactive=True,
        padding="1rem 1.25rem",
        min_height=_TARGET,
        height="100%",
        text_align="left",
        border=rx.cond(active, f"1px solid {T.tone_color(tone, 8)}", None),
    )
    return rx.el.button(
        surface,
        type="button",
        on_click=DashboardState.pick_sentiment(pick),
        # No aria-label: the visible text («Negativas 2 Ver solo estas») names the button,
        # figure included, and `aria-pressed` says which one is on (UX review).
        aria_pressed=active,
        # Only the reset a native button needs; the look is the card's.
        background="transparent",
        border="none",
        padding="0",
        margin="0",
        font="inherit",
        color="inherit",
        cursor="pointer",
        display="block",
        width="100%",
        border_radius="var(--radius-4)",
    )


def stats_row() -> rx.Component:
    """The summary of the scope (account + period). A search, an origin or a sentiment
    filter narrows the LIST, never these figures. Each card filters the list by its
    sentiment with one tap (RESULTADOS-1); the total shows all again. Mentions that are
    not (yet) a polarity are listed under the total, never folded into one."""
    return rx.grid(
        _sentiment_card(
            "Total menciones",
            DashboardState.total_mentions,
            "accent",
            ALL_SENTIMENTS,
            hint=DashboardState.states_hint,
        ),
        _sentiment_card("Positivas", DashboardState.positive_count, "ok", "Positiva"),
        _sentiment_card("Neutras", DashboardState.neutral_count, "neutral", "Neutra"),
        _sentiment_card("Negativas", DashboardState.negative_count, "error", "Negativa"),
        columns=rx.breakpoints(initial="2", md="4"),
        spacing="3",
        width="100%",
    )


def _filter_select(
    label: str,
    items: list[str] | rx.Var,
    value: rx.Var,
    on_change: rx.EventHandler,
    *,
    in_panel: bool = False,
    **props,
) -> rx.Component:
    """A select with its label on screen and a ≥ 44 px trigger (N12). Inside the phone's
    panel the menu opens as a popper, so the drawer never clips it."""
    options = (
        [rx.foreach(items, lambda item: rx.select.item(item, value=item))]
        if isinstance(items, rx.Var)
        else [rx.select.item(item, value=item) for item in items]
    )
    content_props = {"position": "popper"} if in_panel else {}
    return rx.vstack(
        rx.text(label, size="1", color=T.TEXT_MUTED, weight="medium"),
        rx.select.root(
            rx.select.trigger(min_height=_TARGET, width="100%", aria_label=label),
            rx.select.content(*options, **content_props),
            value=value,
            on_change=on_change,
            size="3",
        ),
        spacing="1",
        **props,
    )


def _account_select(*, in_panel: bool = False, **props) -> rx.Component:
    return rx.cond(
        DashboardState.show_account_filter,
        _filter_select(
            "Cuenta",
            DashboardState.account_options,
            DashboardState.account_filter,
            DashboardState.set_account_filter,
            in_panel=in_panel,
            **props,
        ),
    )


def _period_select(**props) -> rx.Component:
    return _filter_select(
        "Periodo",
        list(PERIOD_OPTIONS),
        DashboardState.period_filter,
        DashboardState.set_period_filter,
        **props,
    )


def _origin_select(*, in_panel: bool = False, **props) -> rx.Component:
    return _filter_select(
        "Origen",
        list(ORIGIN_OPTIONS),
        DashboardState.origin_filter,
        DashboardState.set_origin_filter,
        in_panel=in_panel,
        **props,
    )


def _sentiment_select(*, in_panel: bool = False, **props) -> rx.Component:
    return _filter_select(
        "Sentimiento",
        list(SENTIMENT_OPTIONS),
        DashboardState.sentiment_filter,
        DashboardState.set_sentiment_filter,
        in_panel=in_panel,
        **props,
    )


def _more_filters_panel() -> rx.Component:
    """The phone's «Más filtros»: account, origin and sentiment, each with its label. Every
    change applies at once (the list behind updates); «Listo» closes the panel."""
    return drawer(
        rx.vstack(
            _account_select(in_panel=True, width="100%"),
            _origin_select(in_panel=True, width="100%"),
            _sentiment_select(in_panel=True, width="100%"),
            spacing="4",
            width="100%",
        ),
        open=DashboardState.filters_open,
        on_open_change=DashboardState.set_filters_open,
        title="Más filtros",
        description="Los cambios se aplican a la lista al momento.",
        footer=rx.hstack(
            rx.button(
                "Quitar filtros",
                variant="soft",
                color_scheme=T.tone_scale("neutral"),
                size="3",
                min_height=_TARGET,
                on_click=DashboardState.clear_more_filters,
            ),
            rx.spacer(),
            rx.button(
                "Listo",
                size="3",
                min_height=_TARGET,
                on_click=DashboardState.set_filters_open(False),
            ),
            width="100%",
            align="center",
        ),
        icon="sliders-horizontal",
    )


def filter_bar() -> rx.Component:
    """Wide screens: every filter in one row, each with its label. Below 1280 px (the same
    switch as table ↔ cards): only «Periodo» and «Más filtros», one line at 360 px (N12);
    the button counts the filters in use behind it."""
    return rx.box(
        rx.box(
            rx.hstack(
                _account_select(min_width="12rem"),
                _period_select(min_width="12rem"),
                _origin_select(min_width="12rem"),
                _sentiment_select(min_width="12rem"),
                spacing="3",
                wrap="wrap",
                align="end",
                width="100%",
            ),
            class_name=_TABLE_ONLY,
        ),
        rx.box(
            rx.hstack(
                _period_select(flex="1", min_width="0"),
                rx.button(
                    rx.icon("sliders-horizontal", size=T.ICON_SM),
                    DashboardState.more_filters_label,
                    variant="soft",
                    size="3",
                    min_height=_TARGET,
                    on_click=DashboardState.set_filters_open(True),
                ),
                spacing="2",
                align="end",
                width="100%",
            ),
            class_name=_CARDS_ONLY,
        ),
        _more_filters_panel(),
        width="100%",
    )


# --- the table panel ---------------------------------------------------------------------


def _refresh_button() -> rx.Component:
    """This module's refresh, with its word on screen (nothing only in a tooltip, N12), in
    the panel's own header — never beside the app-wide theme toggle (founder review
    2026-10-13)."""
    return rx.button(
        rx.icon("refresh-cw", size=T.ICON_SM),
        "Actualizar",
        size="3",
        variant="soft",
        min_height=_TARGET,
        loading=DashboardState.is_refreshing,
        on_click=DashboardState.refresh_now,
        aria_label="Actualizar menciones",
    )


def _panel_header() -> rx.Component:
    return rx.hstack(
        rx.heading("Menciones recibidas", size="3", as_="h2"),
        rx.spacer(),
        _refresh_button(),
        align="center",
        width="100%",
    )


def mention_sentiment_badge(mention: MentionRow) -> rx.Component:
    """Positiva / Neutra / Negativa / Pendiente are sentiments. A mention with no text, or
    one the model could not read, has NONE: it shows its reason in plain muted text —
    «Sin texto para leer», «No pudimos leerla» — outside the sentiment vocabulary and on
    screen, never only on hover (founder review; RESULTADOS-1, N12)."""
    return rx.match(
        mention.sentiment_state,
        ("POS", signal_pill("Positiva", "ok")),
        ("NEU", signal_pill("Neutra", "neutral")),
        ("NEG", signal_pill("Negativa", "error")),
        ("PENDING", signal_pill("Pendiente", "info")),
        _muted(rx.cond(mention.sentiment_note != "", mention.sentiment_note, "—")),
    )


def _date_cell(mention: MentionRow) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.text(mention.day, size="2", class_name="q-nums", white_space="nowrap"),
            rx.cond(
                mention.time != "",
                rx.text(mention.time, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            ),
            spacing="0",
        ),
        spacing="2",
        align="center",
    )


def _link_label(mention: MentionRow) -> rx.Component:
    """Destination + ↗ (N9): «Ver en Instagram ↗», or «Ver y responder en Instagram ↗» on a
    negative mention."""
    return rx.hstack(
        rx.text(mention.link_label, size="2", weight="medium"),
        rx.icon("arrow-up-right", size=T.ICON_SM, aria_hidden="true"),
        spacing="1",
        align="center",
    )


def _link_cell(mention: MentionRow) -> rx.Component:
    """The way out to the network, or «Sin enlace» on screen when it gave none."""
    return rx.cond(
        mention.permalink != "",
        rx.link(
            _link_label(mention),
            href=mention.permalink,
            is_external=True,
            aria_label=mention.link_label + " (se abre en otra pestaña)",
            white_space="nowrap",
            underline="hover",
            display="inline-flex",
            align_items="center",
            min_height=_TARGET,
        ),
        _muted(NO_LINK, white_space="nowrap"),
    )


def _reply_block(mention: MentionRow) -> rx.Component:
    """On a negative mention: what to do and the button to do it, together — in the table
    as on the card (UX review) — the owner answers on the network; Qualify never answers by
    itself (N13). No link: the advice stays, the reason («Sin enlace») replaces the button."""
    hint = rx.text(mention.reply_hint, size="2", weight="medium", color=T.tone_color("error", 11))
    return rx.cond(
        mention.reply_hint != "",
        rx.vstack(
            hint,
            rx.cond(
                mention.permalink != "",
                rx.button(
                    rx.link(
                        _link_label(mention),
                        href=mention.permalink,
                        is_external=True,
                        aria_label=mention.link_label + " (se abre en otra pestaña)",
                        underline="none",
                    ),
                    as_child=True,
                    size="3",
                    variant="soft",
                    min_height=_TARGET,
                    **T.tone_scheme("error"),
                ),
                _muted(NO_LINK),
            ),
            spacing="2",
            align_items="start",
            width="100%",
        ),
    )


def _author_cell(mention: MentionRow) -> rx.Component:
    """The author, and on screen why it is missing when the network did not give it."""
    return rx.cond(
        mention.author_note == "",
        mono(mention.author),
        rx.vstack(
            _muted(mention.author, white_space="nowrap"),
            rx.text(mention.author_note, size="1", color=T.TEXT_FAINT, max_width="14rem"),
            spacing="0",
            align_items="start",
        ),
    )


def _more_toggle(mention: MentionRow) -> rx.Component:
    """«Ver más» / «Ver menos» under a long text — the whole mention opens in place, on a
    phone as on a laptop (no hover needed)."""
    expanded = DashboardState.expanded_ids.contains(mention.id)
    return rx.cond(
        mention.text_is_long,
        rx.button(
            rx.cond(expanded, "Ver menos", "Ver más"),
            variant="ghost",
            size="2",
            min_height=_TARGET,
            padding_x="0",
            on_click=DashboardState.toggle_expanded(mention.id),
            aria_expanded=expanded,
        ),
    )


def _text_cell(mention: MentionRow) -> rx.Component:
    """Three lines in the row, the same cut as the card, so `LONG_TEXT_CHARS` holds in both
    views and «Ver más» shows whenever text is hidden (UX review); it opens the whole
    mention in place. On a negative mention, what to do and the button follow the text."""
    expanded = DashboardState.expanded_ids.contains(mention.id)
    return rx.vstack(
        rx.text(
            mention.text,
            size="2",
            color=rx.cond(mention.text_unavailable, T.TEXT_MUTED, "inherit"),
            width=_MENTION_COL_WIDTH,
            max_width=_MENTION_COL_WIDTH,
            white_space="pre-wrap",
            class_name=rx.cond(expanded, "", "q-clamp-3"),
            line_height="1.55",
        ),
        _more_toggle(mention),
        _reply_block(mention),
        spacing="1",
        align_items="start",
    )


def _likes_cell(mention: MentionRow) -> rx.Component:
    """A number, or its reason on screen («Ocultos», «Sin dato») — never a made-up 0."""
    return rx.cond(
        mention.likes_short == "",
        rx.text(mention.likes, size="2", class_name="q-nums"),
        _muted(mention.likes_short, white_space="nowrap"),
    )


def mention_row(mention: MentionRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(_date_cell(mention)),
        rx.table.cell(platform_badge(mention.platform)),
        rx.table.cell(tag(mention.kind_label)),
        # A negative mention carries «Ver y responder en …» next to its advice, in the
        # «Mención» cell (UX review): the owner looks for the button by the text.
        rx.table.cell(rx.cond(mention.reply_hint == "", _link_cell(mention))),
        rx.table.cell(_author_cell(mention)),
        rx.table.cell(_text_cell(mention), padding_right=_MENTION_GUTTER),
        rx.table.cell(mention_sentiment_badge(mention)),
        rx.table.cell(_likes_cell(mention), text_align="right"),
        align="center",
    )


def mention_card(mention: MentionRow) -> rx.Component:
    """One mention below 1280 px: who/when/where on top, the text (three lines, «Ver más»
    for the rest), what to do when it is negative, then likes and the link — the same
    fields as a table row, nothing hidden behind a hover."""
    expanded = DashboardState.expanded_ids.contains(mention.id)
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.hstack(
                    rx.text(mention.date, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                    platform_badge(mention.platform),
                    tag(mention.kind_label),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.spacer(),
                mention_sentiment_badge(mention),
                width="100%",
                align="start",
                spacing="2",
            ),
            _author_cell(mention),
            rx.text(
                mention.text,
                size="2",
                color=rx.cond(mention.text_unavailable, T.TEXT_MUTED, "inherit"),
                white_space="pre-wrap",
                class_name=rx.cond(expanded, "", "q-clamp-3"),
            ),
            _more_toggle(mention),
            _reply_block(mention),
            rx.hstack(
                rx.hstack(
                    rx.icon("heart", size=T.ICON_SM, color=T.TEXT_MUTED, aria_hidden="true"),
                    rx.text("Me gusta:", size="2", color=T.TEXT_MUTED),
                    _likes_cell(mention),
                    spacing="1",
                    align="center",
                ),
                rx.spacer(),
                # A negative mention already carries its button above.
                rx.cond(mention.reply_hint == "", _link_cell(mention)),
                width="100%",
                align="center",
            ),
            spacing="2",
            width="100%",
        ),
        padding="0.875rem 0.25rem",
        border_bottom=T.BORDER,
        width="100%",
    )


def mentions_cards() -> rx.Component:
    # The responsive class lives on a plain box: a Radix Flex (`vstack`) owns its own
    # `display` and would fight the rule.
    return rx.box(
        rx.vstack(
            rx.foreach(DashboardState.mentions, mention_card),
            spacing="0",
            width="100%",
        ),
        width="100%",
        class_name=_CARDS_ONLY,
    )


def mentions_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Fecha"),
                    rx.table.column_header_cell("Canal"),
                    rx.table.column_header_cell("Origen"),
                    rx.table.column_header_cell("Enlace"),
                    rx.table.column_header_cell("Autor"),
                    rx.table.column_header_cell(
                        "Mención", min_width=_MENTION_COL_WIDTH, padding_right=_MENTION_GUTTER
                    ),
                    rx.table.column_header_cell("Sentimiento"),
                    rx.table.column_header_cell("Me gusta", text_align="right"),
                )
            ),
            rx.table.body(
                rx.foreach(DashboardState.mentions, mention_row),
            ),
            variant="ghost",
            width="100%",
        ),
        overflow_x="auto",
        width="100%",
        class_name=_TABLE_ONLY,
    )


def _page_button(item: rx.Var[str]) -> rx.Component:
    is_current = item == DashboardState.page.to_string()
    return rx.button(
        item,
        size="3",
        radius="full",
        variant=rx.cond(is_current, "solid", "ghost"),
        color_scheme=T.tone_scale("neutral"),
        high_contrast=True,
        min_width=_TARGET,
        min_height=_TARGET,
        padding_x="0.5rem",
        class_name="q-nums",
        on_click=DashboardState.go_to_page(item),
        aria_label="Página " + item,
    )


def _arrow(
    icon: str, label: str, disabled: rx.Var[bool], on_click: rx.EventHandler
) -> rx.Component:
    return rx.icon_button(
        rx.icon(icon, size=T.ICON_SM),
        size="3",
        variant="ghost",
        min_width=_TARGET,
        min_height=_TARGET,
        color_scheme=T.tone_scale("neutral"),
        disabled=disabled,
        on_click=on_click,
        aria_label=label,
    )


def pager() -> rx.Component:
    """Compact pager (founder's reference, 2026-10-13): the page count on the left; on the
    right the arrows and up to ten page numbers, the current one filled. With the cards the
    numbers give way to "‹ Página n de N ›" (below 1280 px)."""
    prev = _arrow(
        "chevron-left", "Página anterior", ~DashboardState.has_prev, DashboardState.prev_page
    )
    nxt = _arrow(
        "chevron-right", "Página siguiente", ~DashboardState.has_next, DashboardState.next_page
    )
    return rx.box(
        rx.box(
            rx.hstack(
                rx.text(DashboardState.pages_label, size="1", color=T.TEXT_MUTED),
                rx.spacer(),
                rx.hstack(
                    prev,
                    rx.foreach(DashboardState.page_items, _page_button),
                    nxt,
                    spacing="1",
                    align="center",
                ),
                width="100%",
                align="center",
            ),
            class_name=_TABLE_ONLY,
        ),
        rx.box(
            rx.hstack(
                _arrow(
                    "chevron-left",
                    "Página anterior",
                    ~DashboardState.has_prev,
                    DashboardState.prev_page,
                ),
                rx.text(
                    "Página ",
                    DashboardState.page.to_string(),
                    " de ",
                    DashboardState.total_pages.to_string(),
                    size="2",
                    color=T.TEXT_MUTED,
                    class_name="q-nums",
                ),
                _arrow(
                    "chevron-right",
                    "Página siguiente",
                    ~DashboardState.has_next,
                    DashboardState.next_page,
                ),
                justify="center",
                align="center",
                spacing="3",
                width="100%",
            ),
            class_name=_CARDS_ONLY,
        ),
        width="100%",
    )


# --- refresh outcomes and states -------------------------------------------------------


def notices() -> rx.Component:
    """The refresh outcomes. None of them changes the rows on screen by itself. On page 1
    a new mention simply appears in the list (QUA-152). On a later page, whose snapshot
    keeps the rows still, «Llegaron menciones nuevas.» + «Verlas» takes the person to
    page 1 (founder's text, 2026-10-23); it wins over the generic list change."""
    return rx.vstack(
        rx.cond(
            DashboardState.new_mentions_notice != "",
            rx.hstack(
                callout(DashboardState.new_mentions_notice, "info", flex="1"),
                rx.button(
                    NEW_MENTIONS_BUTTON,
                    size="3",
                    variant="soft",
                    min_height=_TARGET,
                    on_click=DashboardState.go_to_page("1"),
                ),
                align="center",
                spacing="3",
                width="100%",
                wrap="wrap",
            ),
        ),
        rx.cond(
            DashboardState.list_changed & (DashboardState.new_mentions_notice == ""),
            rx.hstack(
                callout("La lista cambió mientras la mirabas.", "info", flex="1"),
                rx.button(
                    "Ver la lista al día",
                    size="3",
                    variant="soft",
                    min_height=_TARGET,
                    on_click=DashboardState.go_to_page("1"),
                ),
                align="center",
                spacing="3",
                width="100%",
            ),
        ),
        rx.cond(
            DashboardState.refresh_error != "",
            callout(DashboardState.refresh_error, "warn"),
        ),
        rx.cond(
            DashboardState.refresh_notice != "",
            callout(DashboardState.refresh_notice, "warn"),
        ),
        spacing="2",
        width="100%",
    )


def _mentions_load_error() -> rx.Component:
    return callout(DashboardState.mentions_error, "error")


def _mentions_empty_state() -> rx.Component:
    return rx.cond(
        DashboardState.is_windowed,
        empty_state(
            "at-sign",
            "No hay menciones en este periodo",
            "Cuando alguien mencione tu cuenta en una publicación o un "
            "comentario, aparecerá aquí. Para ver menciones anteriores, elige un periodo "
            "más amplio.",
        ),
        # N8 (m-24843003): without Instagram the way out is connecting it; with it, a new
        # publication is what invites people to tag the business.
        rx.cond(
            ResultsState.instagram_connected,
            empty_state(
                "at-sign",
                "Aún no hay menciones",
                "Cuando alguien te etiquete en una publicación o un comentario, aparecerá "
                "aquí. Una publicación nueva invita a que te etiqueten.",
                action=rx.link(
                    rx.button("Crear publicación", size="3", min_height=_TARGET),
                    href="/create",
                ),
            ),
            empty_state(
                "at-sign",
                "Aún no hay menciones",
                "Conecta tu Instagram para ver quién te menciona.",
                action=rx.link(
                    rx.button("Conectar mi Instagram", size="3", min_height=_TARGET),
                    href="/connections",
                ),
            ),
        ),
    )


def _no_results_state() -> rx.Component:
    return empty_state(
        "search-x",
        "Ninguna mención coincide con estos filtros",
        "Cambia o quita algún filtro para ver más menciones.",
    )


def mentions_body() -> rx.Component:
    """Notices above a single panel: its header (title + refresh), then loading → error →
    empty → no results → table + pager, never overlapping. The skeleton shows only when
    the screen opens; filtering, paging and refreshing keep the rows on screen."""
    return rx.vstack(
        _refresh_timer(),
        notices(),
        card(
            rx.vstack(
                _panel_header(),
                rx.cond(
                    DashboardState.is_loading_mentions,
                    skeleton_rows(rows=4, height="2.75rem"),
                    rx.cond(
                        DashboardState.mentions_error != "",
                        _mentions_load_error(),
                        rx.cond(
                            DashboardState.show_empty_state,
                            _mentions_empty_state(),
                            rx.cond(
                                DashboardState.show_no_results,
                                _no_results_state(),
                                rx.vstack(
                                    mentions_table(),
                                    mentions_cards(),
                                    # No separator: the last row (or card) already draws
                                    # the one line above the pager.
                                    pager(),
                                    spacing="3",
                                    width="100%",
                                ),
                            ),
                        ),
                    ),
                ),
                spacing="3",
                width="100%",
            ),
            padding="1rem 1.25rem",
        ),
        spacing="3",
        width="100%",
    )
