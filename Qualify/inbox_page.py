"""Inbox content screen (Fase 1 Parte 4-B, B2 UI slice) — Reels from the last 2 weeks,
with a switch to turn monitoring on/off per Reel.

Built on the `ui` shell (`app_shell` / `page_header` / `page_body`); badges and callouts
follow the design-system tones (docs/design-system.md). Adds the `/inbox` route only.

Material (Liquid Glass migration, lote D — docs/plan-migracion-liquid-glass.md §4):
every block — a Reel row, a comment, a reply draft, the sync strip — is `ui.card`, the
card role of plan D5 (translucent relief, no backdrop blur); the three recipes no
primitive covers (the 72px thumbnail, the row skeleton, the outgoing reply bubble) live
in `assets/qualify-inbox.css` on the control tokens. Buttons follow §5.5: the connected
screen has no solid button — the per-row switch is its primary action — so sync,
analyse and generate are `soft`, and the draft's accept/discard carry their tone through
`T.tone_scheme`, never a raw Radix hue.

No rich media preview beyond a thumbnail + caption snippet on the Reels list — the goal
there is to make the monitoring decision visible and actionable, not to redesign the
screen.

`_sync_section()` (2026-08-15, promoted to permanent architecture 2026-08-19 — QUA-89)
renders the comment-sync controls: a manual "Sincronizar comentarios" button plus a
hidden `rx.moment` heartbeat that calls the SAME `InboxState.sync_comments` every 5
minutes while this screen is mounted. See `inbox_state.py`'s module docstring for why one
handler backing both triggers is what gives them a single shared loading state and
re-entrancy guard for free. The polling timer is deliberately a client-side interval
(`_polling_timer()` below), not a server-side background loop — see its docstring for why
that is what makes cleanup on navigation/tab-close unconditional rather than something
that has to be cancelled.

`_comments_section()` (QUA-92, restructured QUA-93) adds the comment/thread view this
file's docstring used to say was out of scope: synced comments with their persisted
sentiment (QUA-21), stacked below the Reels list inside the same `page_body` — not a new
route, not a tabs pattern (no precedent for `rx.tabs` anywhere in this app). It never
syncs on its own (`InboxState.sync_comments`/QUA-89 is unchanged).

**QUA-93 replaced the flat comment list with two levels, still inside this one
`section()`, still no new route:** a global sentiment widget + a page of Reel
summary-cards (`_reel_summaries_list`) at the top level, and one Reel's comments
(`_reel_detail_view`, paginated/filtered/searched) behind a "Ver comentarios" click —
toggled by `InboxState.is_showing_reel_detail`, the same `rx.cond`-swap idiom every other
section of this screen already uses, not a second routing mechanism. `_comment_card`
itself is UNCHANGED from QUA-92 — it moved one level down (the detail view), not
redesigned. Opción A for the Reel reference (founder decision, 2026-08-24, reapplied
per-Reel in QUA-93): a Reel still inside the Reels-monitoring list's 2-week window shows
its real thumbnail/caption/permalink (cross-referenced from `CandidateMediaVM`, ZERO
extra Meta calls — see `inbox_provider.reel_summaries_page`'s docstring); an older
monitored Reel falls back to `external_thread_id` only, same as QUA-92's original scope.

`_analyze_now_button()` (QUA-92) makes QUA-21's existing manual trigger visible on
screen: it calls `InboxState.analyze_sentiment`, which runs the same seam the
`POST /api/sentiment/analyze` route wraps (`inbox_provider.analyze_sentiment_now` —
never a second analysis engine). Same
"button + `rx.cond` loading label" shape `_sync_now_button()` already establishes, kept
as its own control rather than merged into `_sync_now_button()`: syncing and analyzing
are two independent actions with two independent guards (`is_syncing`/`is_analyzing`),
and QUA-92's own requirement is that neither ever triggers the other. It stays the ONE
button for both levels — `InboxState._refresh_after_write` decides what it refreshes.
"""

from __future__ import annotations

import reflex as rx

from .inbox_state import FILTER_ALL, FILTER_COMMERCIAL, InboxState
from .inbox_vm import (
    MONITORING_ACTIVE,
    MONITORING_EXPIRED,
    MONITORING_PENDING,
    CandidateMediaVM,
    CommentVM,
    IntentChipVM,
    ReelSummaryVM,
)
from .publishing_vm import ConnectionOptionVM
from .replies_provider import DraftVM
from .replies_state import RepliesState
from .ui import (
    app_shell,
    callout,
    card,
    chat_bubble,
    empty_state,
    loading_spinner,
    media_thumb,
    mono,
    page_body,
    page_header,
    section,
    sentiment_badge,
    skeleton_rows,
    stat_card,
    tone_badge,
)
from .ui import tokens as T


def _connection_item(conn: ConnectionOptionVM) -> rx.Component:
    return rx.select.item(conn.external_username, value=conn.id)


def _connection_selector() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(placeholder="Elige una cuenta de Instagram", width="260px"),
        rx.select.content(
            rx.foreach(InboxState.connections, _connection_item),
        ),
        value=InboxState.selected_connection_id,
        on_change=InboxState.select_connection,
        size="2",
    )


def _thumbnail(candidate: CandidateMediaVM) -> rx.Component:
    """The Reel's 72px picture, or — when the API returned none — the same frame filled
    with the control material (`ui.media_thumb`). Decorative:
    the caption next to it is the Reel's name, so the image carries no alt text."""
    return media_thumb(candidate.thumbnail_url, size="72px", icon="film")


def _monitoring_switch(candidate: CandidateMediaVM) -> rx.Component:
    """Per-row control: just the switch and its status label. Whether THIS row is
    mid-toggle is decided one level up, by `_candidate_card` — see its docstring for why
    the loading state lives there now (the whole card skeletons, not just this control).
    """
    return rx.vstack(
        rx.switch(
            checked=candidate.is_monitored,
            on_change=lambda checked: InboxState.toggle_monitored(
                candidate.external_media_id, checked
            ),
            size="2",
        ),
        rx.cond(
            candidate.is_monitored,
            tone_badge("Monitoreado", "ok", icon="eye"),
            tone_badge("No monitoreado", "neutral", icon="eye-off"),
        ),
        spacing="1",
        align="center",
    )


def _candidate_card_content(candidate: CandidateMediaVM) -> rx.Component:
    """One Reel or feed post row on the card material (`ui.card`): picture, caption, its
    format label (QUA-146) and meta, the monitoring switch on the right."""
    return card(
        rx.hstack(
            _thumbnail(candidate),
            rx.vstack(
                rx.text(
                    rx.cond(candidate.caption != "", candidate.caption, "Sin caption"),
                    size="2",
                    weight="medium",
                    max_width="380px",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.hstack(
                    # QUA-146: Reel / Foto / Video / Carrusel / Publicación.
                    rx.cond(
                        candidate.format_label != "",
                        tone_badge(candidate.format_label, "neutral"),
                        rx.fragment(),
                    ),
                    rx.icon("clock", size=13, color=T.TEXT_FAINT),
                    rx.text(candidate.posted_at, size="1", color=T.TEXT_MUTED),
                    rx.cond(
                        candidate.permalink != "",
                        rx.link(
                            "Ver en Instagram",
                            href=candidate.permalink,
                            target="_blank",
                            size="1",
                        ),
                        rx.fragment(),
                    ),
                    spacing="2",
                    align="center",
                ),
                spacing="1",
                align_items="start",
            ),
            rx.spacer(),
            _monitoring_switch(candidate),
            spacing="3",
            align="center",
            width="100%",
        ),
        padding="1rem 1.25rem",
        # Full width of the body: every row's switch/actions line up on one right edge
        # instead of each card hugging its own caption.
        width="100%",
    )


def _candidate_card(candidate: CandidateMediaVM) -> rx.Component:
    """One Reel's card, or — while THIS row's toggle is in flight — the SAME shimmering
    `_card_skeleton()` the initial-load state uses, in this card's place only.

    Gated on `toggling_media_ids.contains(candidate.external_media_id)` — the per-row
    set `InboxState.toggle_monitored` already maintains. `rx.foreach(InboxState.
    candidates, _candidate_card)` in `_candidates_body()` is untouched: every OTHER card
    keeps rendering `_candidate_card_content` normally, because their own id is never in
    `toggling_media_ids`. This is deliberately NOT `is_loading_candidates` (that flag
    stays reserved for the initial load / a connection switch, where there is nothing
    valid to show yet at all — see `_load_candidates`'s `show_loading` param) — a single
    row toggling must never blank or skeleton any OTHER row, and never has to since this
    condition is local to `candidate.external_media_id`.
    """
    return rx.cond(
        InboxState.toggling_media_ids.contains(candidate.external_media_id),
        _card_skeleton(),
        _candidate_card_content(candidate),
    )


def _card_skeleton() -> rx.Component:
    """Content-loading placeholder shaped like a Reel row: the card's frame, empty
    (`.q-inbox-skeleton`), with the picture and two lines shimmering inside."""
    return card(
        rx.hstack(
            skeleton_rows(1, height="72px", width="72px"),
            rx.vstack(
                skeleton_rows(1, height="1.25rem", width="220px"),
                skeleton_rows(1, height="1rem", width="140px"),
                spacing="2",
                align_items="start",
            ),
            spacing="3",
            align="center",
        ),
        padding="1rem 1.25rem",
        # Full width of the body: every row's switch/actions line up on one right edge
        # instead of each card hugging its own caption.
        width="100%",
        class_name="q-card q-inbox-skeleton",
        aria_busy="true",
    )


def _no_connections_state() -> rx.Component:
    return empty_state(
        "link-2-off",
        "No hay cuentas listas para monitorear",
        "Conecta una cuenta con el permiso de comentarios en "
        "Conexiones para elegir qué contenido monitorear.",
        action=rx.link(
            rx.button(rx.icon("link", size=16), "Ir a Conexiones", size="3"),
            href="/connections",
        ),
    )


def _empty_candidates_state() -> rx.Component:
    return empty_state(
        "film",
        "Sin Reels ni publicaciones en las últimas 2 semanas",
        "Esta cuenta no publicó Reels ni publicaciones en el feed en los últimos 14 días.",
    )


def _connections_error() -> rx.Component:
    return callout(InboxState.connections_error, "error")


def _load_error() -> rx.Component:
    return callout(InboxState.load_error, "error")


def _action_error() -> rx.Component:
    """Error from a toggle action, shown ABOVE the list rather than replacing it: the
    Reels on screen are still valid, one toggle failed."""
    return callout(InboxState.action_error, "warn")


def _candidates_body() -> rx.Component:
    return rx.cond(
        InboxState.is_loading_candidates,
        rx.vstack(_card_skeleton(), _card_skeleton(), spacing="3", width="100%"),
        rx.cond(
            InboxState.show_empty_state,
            _empty_candidates_state(),
            rx.vstack(
                rx.foreach(InboxState.candidates, _candidate_card),
                spacing="3",
                width="100%",
            ),
        ),
    )


def _body() -> rx.Component:
    return page_body(
        # Inside the body (not between header and body): it shares the body's width cap
        # and gutter, so it lines up with the cards below instead of running edge to edge.
        rx.cond(InboxState.has_connections, _sync_section(), rx.fragment()),
        rx.cond(InboxState.action_error != "", _action_error(), rx.fragment()),
        rx.cond(
            InboxState.connections_error != "",
            _connections_error(),
            rx.cond(
                InboxState.is_loading_connections,
                _card_skeleton(),
                rx.cond(
                    ~InboxState.has_connections,
                    _no_connections_state(),
                    rx.cond(
                        InboxState.load_error != "",
                        _load_error(),
                        _candidates_body(),
                    ),
                ),
            ),
        ),
        rx.cond(InboxState.has_connections, _comments_section(), rx.fragment()),
        rx.cond(InboxState.has_connections, _replies_section(), rx.fragment()),
    )


# ------------------------------------------------------------------------------------
# Comments section (QUA-92, restructured QUA-93) — read-only view of synced comments +
# their persisted sentiment (QUA-21), grouped by Reel. Stacked below the Reels list in
# the SAME page_body, not a separate route or a tabs pattern (no precedent for tabs in
# this app) — see the module docstring for why. Every sub-section owns its own §6.1
# lifecycle, independent of every other: the Reels-monitoring list above, the global
# summary widget, the Reel summary-card list, and the Reel detail view all have their
# own `*_error`/`is_loading_*`/`show_empty_*` triplet that never cross-talks.
# ------------------------------------------------------------------------------------


def _intent_chip(chip: IntentChipVM) -> rx.Component:
    """One intent class (m-24789644, B3). A class the golden-set measurement does not
    back is still shown — hiding it would hide the comment's best guess — but in the
    warning tone and suffixed «no fiable», with the reason on hover."""
    return rx.cond(
        chip.reliable,
        rx.cond(chip.commercial, tone_badge(chip.label, "info"), tone_badge(chip.label, "neutral")),
        rx.tooltip(
            tone_badge(chip.label + " · no fiable", "warn"),
            content=(
                "Esta clase todavía no alcanza la precisión mínima medida; "
                "revísala antes de actuar."
            ),
        ),
    )


def _comment_intent(comment: CommentVM) -> rx.Component:
    return rx.cond(
        comment.intent_analyzed,
        rx.hstack(
            rx.icon("target", size=13, color=T.TEXT_FAINT),
            rx.foreach(comment.intent_chips, _intent_chip),
            spacing="2",
            align="center",
            wrap="wrap",
        ),
        rx.hstack(
            rx.icon("target", size=13, color=T.TEXT_FAINT),
            rx.text("Intención sin analizar", size="1", color=T.TEXT_MUTED),
            spacing="2",
            align="center",
        ),
    )


def _comment_card(comment: CommentVM) -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.text(
                    rx.cond(
                        comment.author_username != "", comment.author_username, "Autor desconocido"
                    ),
                    size="2",
                    weight="medium",
                ),
                rx.spacer(),
                sentiment_badge(comment.sentiment_label),
                rx.cond(
                    comment.score_display != "",
                    mono(comment.score_display, size="1"),
                    rx.fragment(),
                ),
                align="center",
                spacing="2",
                width="100%",
            ),
            rx.text(
                rx.cond(comment.text != "", comment.text, "Sin texto"),
                size="2",
            ),
            _comment_intent(comment),
            rx.hstack(
                rx.icon("clock", size=13, color=T.TEXT_FAINT),
                rx.text(comment.posted_at, size="1", color=T.TEXT_MUTED),
                rx.icon("film", size=13, color=T.TEXT_FAINT),
                mono(comment.external_thread_id, size="1"),
                spacing="2",
                align="center",
            ),
            spacing="2",
            align_items="start",
            width="100%",
        ),
        padding="1rem 1.25rem",
        # Full width of the body: every row's switch/actions line up on one right edge
        # instead of each card hugging its own caption.
        width="100%",
    )


# --- Global sentiment summary widget (QUA-93) ---------------------------------------


def _global_summary_stats() -> rx.Component:
    return rx.cond(
        InboxState.global_summary,
        rx.grid(
            stat_card("Total", InboxState.global_summary.total, "accent"),
            stat_card("Positivos", InboxState.global_summary.positive, "ok"),
            stat_card("Neutros", InboxState.global_summary.neutral, "neutral"),
            stat_card("Negativos", InboxState.global_summary.negative, "error"),
            stat_card("Sin analizar", InboxState.global_summary.not_analyzed, "neutral"),
            columns=rx.breakpoints(initial="2", md="5"),
            spacing="3",
            width="100%",
        ),
        rx.fragment(),
    )


def _global_summary_skeleton() -> rx.Component:
    return rx.grid(
        *[skeleton_rows(1, height="5.5rem", radius=T.RADIUS_CARD) for _ in range(5)],
        columns=rx.breakpoints(initial="2", md="5"),
        spacing="3",
        width="100%",
    )


def _global_summary_error_block() -> rx.Component:
    return callout(InboxState.global_summary_error, "error")


def _global_summary_widget() -> rx.Component:
    # Explicit label (bug reported 2026-08-25): with nothing distinguishing this from
    # the per-Reel chips further down, a single monitored Reel makes the two numbers
    # look identical and it read as ambiguous which one this was. This widget is always
    # the connection-wide total, across every Reel with synced comments — never one
    # Reel's count.
    #
    # Copy corrected (QUA-94): this used to say "todos los Reels monitoreados", which
    # was already inaccurate — `global_sentiment_summary` (see its docstring) counts
    # every comment in the connection, including Reels no longer monitored. Renamed to
    # describe what the query actually computes rather than change the query to match
    # the old label; see the docstring for why a monitored/historical split is a
    # fast-follow, not done here.
    return rx.vstack(
        rx.text(
            "Resumen general — todos los comentarios sincronizados",
            size="2",
            weight="medium",
            color=T.TEXT_MUTED,
        ),
        rx.cond(
            InboxState.global_summary_error != "",
            _global_summary_error_block(),
            rx.cond(
                InboxState.is_loading_global_summary,
                _global_summary_skeleton(),
                _global_summary_stats(),
            ),
        ),
        spacing="3",
        width="100%",
    )


# --- Reel summary-card list (QUA-93 — the level QUA-92's flat list used to be) -------


def _reel_thumbnail(reel: ReelSummaryVM) -> rx.Component:
    """Same shape as `_thumbnail(candidate)` above, over `ReelSummaryVM`'s own
    thumbnail_url — opción A enrichment, `""` for a Reel outside the 2-week window."""
    return media_thumb(reel.thumbnail_url, size="72px", icon="film")


def _reel_monitoring_badge(reel: ReelSummaryVM) -> rx.Component:
    """QUA-94 + QUA-149: the Reel's EFFECTIVE monitoring state, as the backend applies it
    (`ReelSummaryVM.monitoring_state`, computed from the shared 14-day rule — never from
    `is_monitored` alone):

    - "Monitoreado" — synced, inside its 14-day window;
    - "Monitoreado · fecha por verificar" — synced, but its publication date was not
      read yet (a Reel monitored before QUA-149), so expiry cannot be judged yet;
    - "No monitoreado · vencido" — its window ended: no longer synced, history kept;
    - "No monitoreado" — turned off (by the user, or because it was deleted on Instagram).

    Same `tone_badge` family as `_reel_sentiment_chips`. Decoration only — never hides the
    card or anything inside it."""
    return rx.match(
        reel.monitoring_state,
        (MONITORING_ACTIVE, tone_badge("Monitoreado", "ok", icon="eye")),
        (
            MONITORING_PENDING,
            tone_badge("Monitoreado · fecha por verificar", "info", icon="clock"),
        ),
        (
            MONITORING_EXPIRED,
            tone_badge("No monitoreado · vencido", "warn", icon="calendar-x"),
        ),
        tone_badge("No monitoreado", "neutral", icon="eye-off"),
    )


def _reel_sentiment_chips(reel: ReelSummaryVM) -> rx.Component:
    return rx.hstack(
        tone_badge("Positivos " + reel.positive.to_string(), "ok"),
        tone_badge("Neutros " + reel.neutral.to_string(), "neutral"),
        tone_badge("Negativos " + reel.negative.to_string(), "error"),
        tone_badge("Sin analizar " + reel.not_analyzed.to_string(), "neutral"),
        spacing="2",
        wrap="wrap",
    )


def _format_badge(reel: ReelSummaryVM) -> rx.Component:
    """m-24789644 (B2): what the commented media is — Reel / Foto / Video / Carrusel /
    Publicación / Historia — same badge the candidate rows use (QUA-146)."""
    return rx.cond(reel.format_label != "", tone_badge(reel.format_label, "neutral"), rx.fragment())


def _reel_summary_card(reel: ReelSummaryVM) -> rx.Component:
    return card(
        rx.hstack(
            _reel_thumbnail(reel),
            rx.vstack(
                rx.text(
                    rx.cond(reel.caption != "", reel.caption, "Sin caption"),
                    size="2",
                    weight="medium",
                    max_width="380px",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.hstack(
                    _format_badge(reel),
                    _reel_monitoring_badge(reel),
                    rx.icon("clock", size=13, color=T.TEXT_FAINT),
                    rx.text(reel.last_message_at, size="1", color=T.TEXT_MUTED),
                    rx.icon("film", size=13, color=T.TEXT_FAINT),
                    mono(reel.external_thread_id, size="1"),
                    rx.text(reel.total.to_string() + " comentarios", size="1", color=T.TEXT_MUTED),
                    rx.cond(
                        reel.permalink != "",
                        rx.link("Ver en Instagram", href=reel.permalink, target="_blank", size="1"),
                        rx.fragment(),
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                _reel_sentiment_chips(reel),
                spacing="2",
                align_items="start",
            ),
            rx.spacer(),
            rx.button(
                "Ver comentarios",
                on_click=lambda: InboxState.select_reel(reel.thread_id),
                size="2",
                variant="surface",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        padding="1rem 1.25rem",
        # Full width of the body: every row's switch/actions line up on one right edge
        # instead of each card hugging its own caption.
        width="100%",
    )


def _reel_summaries_empty_state() -> rx.Component:
    return empty_state(
        "message-circle",
        "Aún no hay comentarios sincronizados",
        "Sincroniza comentarios arriba para ver aquí qué publicaciones tienen comentarios, con "
        "su sentimiento cuando esté analizado.",
    )


def _reel_summaries_error_block() -> rx.Component:
    return callout(InboxState.reel_summaries_error, "error")


def _load_more_reels_button() -> rx.Component:
    return rx.cond(
        InboxState.has_more_reels,
        rx.center(
            rx.button(
                rx.cond(
                    InboxState.is_loading_more_reels,
                    loading_spinner("sm"),
                    rx.text("Cargar más publicaciones"),
                ),
                on_click=InboxState.load_more_reels,
                disabled=InboxState.is_loading_more_reels,
                variant="surface",
                size="2",
            ),
            width="100%",
            padding_top="0.5rem",
        ),
        rx.fragment(),
    )


def _reel_summaries_list() -> rx.Component:
    return rx.cond(
        InboxState.reel_summaries_error != "",
        _reel_summaries_error_block(),
        rx.cond(
            InboxState.is_loading_reel_summaries,
            rx.vstack(_card_skeleton(), _card_skeleton(), spacing="3", width="100%"),
            rx.cond(
                InboxState.show_empty_reel_summaries,
                _reel_summaries_empty_state(),
                rx.vstack(
                    rx.foreach(InboxState.reel_summaries, _reel_summary_card),
                    _load_more_reels_button(),
                    spacing="3",
                    width="100%",
                ),
            ),
        ),
    )


# --- Reel detail view (QUA-93) — one Reel's comments, filtered, searched, paginated --


def _reel_detail_header() -> rx.Component:
    reel = InboxState.selected_reel_summary
    return rx.vstack(
        rx.button(
            rx.icon("arrow-left", size=16),
            "Volver",
            on_click=InboxState.back_to_reel_list,
            variant="ghost",
            size="2",
        ),
        rx.cond(
            reel,
            rx.hstack(
                _reel_thumbnail(reel),
                rx.vstack(
                    rx.text(
                        rx.cond(reel.caption != "", reel.caption, "Sin caption"),
                        size="3",
                        weight="medium",
                    ),
                    rx.hstack(
                        _format_badge(reel),
                        _reel_monitoring_badge(reel),
                        mono(reel.external_thread_id, size="1"),
                        spacing="2",
                        align="center",
                    ),
                    _reel_sentiment_chips(reel),
                    spacing="1",
                    align_items="start",
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            rx.fragment(),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


# QUA-93: filter values match `qualify_api.sentiment.repository`'s own constants
# (`"POS"`/`"NEG"`/`"NEU"`/`"PENDING"`) exactly — same "no translation table" convention
# `CommentVM.sentiment_label` already follows for `sentiment_badge`. `FILTER_ALL` is the
# one value the backend never sees (`inbox_provider.thread_comments_page` maps it to
# "no filter").
_SENTIMENT_FILTER_OPTIONS = [
    (FILTER_ALL, "Todos"),
    ("POS", "Positivos"),
    ("NEU", "Neutros"),
    ("NEG", "Negativos"),
    ("PENDING", "Sin analizar"),
]


def _sentiment_filter_item(value: str, label: str) -> rx.Component:
    return rx.select.item(label, value=value)


def _sentiment_filter_select() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(width="180px"),
        rx.select.content(
            *[_sentiment_filter_item(value, label) for value, label in _SENTIMENT_FILTER_OPTIONS]
        ),
        value=InboxState.sentiment_filter,
        on_change=InboxState.set_sentiment_filter,
        size="2",
    )


# m-24789644: «Requiere atención comercial» = the comments whose intent signal under the
# current version is commercial. Same "ALL means no filter" convention as above.
_INTENT_FILTER_OPTIONS = [
    (FILTER_ALL, "Toda intención"),
    (FILTER_COMMERCIAL, "Requiere atención comercial"),
]


def _intent_filter_select() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(width="240px"),
        rx.select.content(
            *[_sentiment_filter_item(value, label) for value, label in _INTENT_FILTER_OPTIONS]
        ),
        value=InboxState.intent_filter,
        on_change=InboxState.set_intent_filter,
        size="2",
    )


def _comment_search_input() -> rx.Component:
    return rx.input(
        rx.input.slot(rx.icon("search", size=T.ICON_SM)),
        placeholder="Buscar en los comentarios...",
        value=InboxState.search_query,
        on_change=InboxState.set_search_query,
        size="2",
        width="260px",
    )


def _thread_comments_empty_state() -> rx.Component:
    return empty_state(
        "message-circle",
        "Sin comentarios para este filtro",
        "Prueba con otro filtro de sentimiento o de intención, o borra la búsqueda.",
    )


def _thread_comments_error_block() -> rx.Component:
    return callout(InboxState.thread_comments_error, "error")


def _load_more_thread_comments_button() -> rx.Component:
    return rx.cond(
        InboxState.has_more_thread_comments,
        rx.center(
            rx.button(
                rx.cond(
                    InboxState.is_loading_more_thread_comments,
                    loading_spinner("sm"),
                    rx.text("Cargar más comentarios"),
                ),
                on_click=InboxState.load_more_thread_comments,
                disabled=InboxState.is_loading_more_thread_comments,
                variant="surface",
                size="2",
            ),
            width="100%",
            padding_top="0.5rem",
        ),
        rx.fragment(),
    )


def _thread_comments_list() -> rx.Component:
    return rx.cond(
        InboxState.thread_comments_error != "",
        _thread_comments_error_block(),
        rx.cond(
            InboxState.is_loading_thread_comments,
            rx.vstack(_card_skeleton(), _card_skeleton(), spacing="3", width="100%"),
            rx.cond(
                InboxState.show_empty_thread_comments,
                _thread_comments_empty_state(),
                rx.vstack(
                    rx.foreach(InboxState.thread_comments, _comment_card),
                    _load_more_thread_comments_button(),
                    spacing="3",
                    width="100%",
                ),
            ),
        ),
    )


def _reel_detail_view() -> rx.Component:
    return rx.vstack(
        _reel_detail_header(),
        rx.hstack(
            _sentiment_filter_select(),
            _intent_filter_select(),
            _comment_search_input(),
            spacing="3",
            align="center",
            width="100%",
            wrap="wrap",
        ),
        _thread_comments_list(),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _analyze_now_button() -> rx.Component:
    """The visible trigger for QUA-21's existing manual analysis pass — see the module
    docstring for why this stays a control of its own rather than merging into
    `_sync_now_button()`."""
    return rx.button(
        rx.cond(
            InboxState.is_analyzing,
            loading_spinner("sm"),
            rx.icon("sparkles", size=16),
        ),
        rx.cond(InboxState.is_analyzing, "Analizando...", "Analizar sentimiento"),
        on_click=InboxState.analyze_sentiment,
        disabled=~InboxState.can_analyze,
        size="2",
        variant="soft",
    )


def _analyze_intent_button() -> rx.Component:
    """m-24789644: the manual trigger of the commercial-intent pass — its own control
    for the same reason `_analyze_now_button` is not merged into the sync button."""
    return rx.button(
        rx.cond(
            InboxState.is_analyzing_intent,
            loading_spinner("sm"),
            rx.icon("target", size=16),
        ),
        rx.cond(InboxState.is_analyzing_intent, "Clasificando...", "Analizar intención"),
        on_click=InboxState.analyze_intent,
        disabled=~InboxState.can_analyze_intent,
        size="2",
        variant="soft",
    )


def _analyze_intent_error_block() -> rx.Component:
    return rx.cond(
        InboxState.analyze_intent_error != "",
        callout(InboxState.analyze_intent_error, "error"),
        rx.fragment(),
    )


def _analyze_error_block() -> rx.Component:
    # The success side (`analyze_result`) has no render block here on purpose — it is a
    # transient `rx.toast.success`, dispatched by `InboxState.analyze_sentiment` itself
    # (see that handler's docstring), not a persistent callout. Only the error stays a
    # persistent `callout`, per docs/design-system.md §5.4.
    return rx.cond(
        InboxState.analyze_error != "",
        callout(InboxState.analyze_error, "error"),
        rx.fragment(),
    )


def _comments_section() -> rx.Component:
    return section(
        "Comentarios",
        _analyze_error_block(),
        _analyze_intent_error_block(),
        rx.cond(~InboxState.is_showing_reel_detail, _global_summary_widget(), rx.fragment()),
        rx.cond(InboxState.is_showing_reel_detail, _reel_detail_view(), _reel_summaries_list()),
        description=(
            "Comentarios sincronizados, agrupados por Reel o publicación, con el sentimiento "
            "y la intención comercial ya analizados cuando existen. Cada uno se monitorea "
            "14 días desde que se "
            "publicó; al vencer deja de sincronizarse, pero su caption y sus comentarios "
            'se conservan, marcado como "No monitoreado · vencido".'
        ),
        actions=[_analyze_now_button(), _analyze_intent_button()],
    )


def _sync_now_button() -> rx.Component:
    return rx.button(
        rx.cond(
            InboxState.is_syncing,
            loading_spinner("sm"),
            rx.icon("refresh-cw", size=16),
        ),
        rx.cond(InboxState.is_syncing, "Sincronizando...", "Sincronizar comentarios"),
        on_click=InboxState.sync_comments("manual"),
        disabled=~InboxState.can_sync,
        size="2",
        variant="soft",
    )


def _sync_error_block() -> rx.Component:
    # Same "success is a toast, error is a persistent callout" split as
    # `_analyze_error_block` above — see that function's comment.
    return rx.cond(
        InboxState.sync_error != "",
        callout(InboxState.sync_error, "error"),
        rx.fragment(),
    )


# QUA-89: automatic comment-sync cadence while `/inbox` is open, in milliseconds
# (`rx.moment`'s `interval` prop). 5 minutes — see the ticket's acceptance criteria.
_POLL_INTERVAL_MS = 5 * 60 * 1000


def _polling_timer() -> rx.Component:
    """The automatic half of QUA-89 — a client-side heartbeat, not a server loop.

    `rx.moment`'s `interval` prop is `react-moment`'s own `setInterval`, running entirely
    in the browser; this app never starts or stops it server-side. React unmounts this
    component — stopping the interval with it — the instant this tree leaves the DOM:
    navigating off `/inbox` internally, or `has_connections` going false, same as every
    other component behind `_sync_section()`'s `rx.cond` gate in `inbox_index()`. On a
    tab close/hard refresh the whole JS runtime is torn down anyway, so there is nothing
    left running either way — no persistent task is ever created server-side for this to
    leak, only the same bounded, self-terminating `sync_comments()` pass the button
    already makes (see `inbox_state.py`'s module docstring).

    `on_change` calls the exact same `InboxState.sync_comments` `_sync_now_button` calls —
    not a copy, not a variant — so a tick and a click share one `is_syncing` guard and one
    loading/result/error state by construction, never two independent ones to keep in
    sync. Rendered hidden: only the tick's side effect matters, never the clock face.
    """
    return rx.moment(
        interval=_POLL_INTERVAL_MS,
        on_change=lambda _tick: InboxState.sync_comments("poll"),
        display="none",
    )


def _sync_section() -> rx.Component:
    """Comment-sync controls (QUA-89): automatic polling every 5 minutes while this
    screen is open, plus a manual trigger for an immediate pass — see `_polling_timer`'s
    docstring for why both are safe to run side by side. A `ui.card`, first block of the
    page body (QUA-146: it used to sit between header and body and ran edge to edge)."""
    return card(
        rx.vstack(
            rx.hstack(
                rx.text(
                    "Los comentarios se sincronizan automáticamente cada 5 minutos "
                    "mientras estás en esta pantalla.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.spacer(),
                _sync_now_button(),
                _polling_timer(),
                spacing="2",
                align="center",
                width="100%",
            ),
            _sync_error_block(),
            spacing="2",
            width="100%",
        ),
        padding="0.75rem 1rem",
        # Inside `page_body` now (QUA-146): the body already gives the gutter and the gap,
        # so no own margin — full width puts it on the same edges as the cards below.
        width="100%",
    )


# ------------------------------------------------------------------------------------
# Assisted reply drafts (QUA-22, comments tranche only) — a separate `RepliesState`,
# see that module's docstring for why. DM drafts do not exist anywhere below this
# line; QUA-20/QUA-69 stay blocked and untouched.
# ------------------------------------------------------------------------------------


def _generate_drafts_button() -> rx.Component:
    return rx.button(
        rx.cond(
            RepliesState.is_generating,
            loading_spinner("sm"),
            rx.icon("sparkles", size=16),
        ),
        rx.cond(RepliesState.is_generating, "Generando...", "Generar borradores"),
        on_click=RepliesState.generate_drafts,
        disabled=RepliesState.is_generating,
        size="2",
        variant="soft",
    )


def _refresh_drafts_button() -> rx.Component:
    """A secondary page control next to "Generar borradores": an icon button on the glass
    control material (`soft`, gray — §5.5), same height as its neighbour, instead of a
    bare `ghost` text link that read as a different kind of thing. Icon-only, so it
    carries `aria_label` and a tooltip with the same words."""
    return rx.tooltip(
        rx.icon_button(
            rx.cond(
                RepliesState.is_loading,
                loading_spinner("sm"),
                rx.icon("refresh-cw", size=16),
            ),
            on_click=RepliesState.load_pending_drafts,
            disabled=RepliesState.is_loading,
            size="2",
            variant="soft",
            color_scheme="gray",
            aria_label="Actualizar borradores",
        ),
        content="Actualizar borradores",
    )


def _replies_generate_error_block() -> rx.Component:
    return rx.cond(
        RepliesState.generate_error != "",
        callout(RepliesState.generate_error, "error"),
        rx.fragment(),
    )


def _replies_action_error_block() -> rx.Component:
    return rx.cond(
        RepliesState.action_error != "",
        callout(RepliesState.action_error, "error"),
        rx.fragment(),
    )


def _replies_load_error_block() -> rx.Component:
    return rx.cond(
        RepliesState.load_error != "",
        callout(RepliesState.load_error, "error"),
        rx.fragment(),
    )


def _replies_empty_state() -> rx.Component:
    return empty_state(
        "message-square-text",
        "Sin borradores pendientes",
        'Haz clic en "Generar borradores" para redactar respuestas a los comentarios '
        "positivos que todavía no tienen una.",
    )


def _draft_view_mode(draft: DraftVM) -> rx.Component:
    """Read-only: the generated text plus the two actions that decide it in one click
    — see `replies_state.py`'s module docstring for why accept/edit and send are
    folded together in this v1."""
    is_busy = RepliesState.busy_draft_id == draft.id
    return rx.vstack(
        chat_bubble(rx.text(draft.generated_text, size="2"), direction="out"),
        rx.hstack(
            rx.button(
                rx.cond(is_busy, loading_spinner("sm"), rx.icon("check", size=14)),
                "Aceptar y enviar",
                on_click=RepliesState.accept_and_send(draft.id),
                disabled=is_busy,
                size="1",
                variant="soft",
                **T.tone_scheme("ok"),
            ),
            rx.button(
                rx.icon("pencil", size=14),
                "Editar",
                on_click=RepliesState.start_edit(draft.id, draft.generated_text),
                disabled=is_busy,
                size="1",
                variant="surface",
            ),
            rx.button(
                rx.icon("x", size=14),
                "Descartar",
                on_click=RepliesState.discard_draft(draft.id),
                disabled=is_busy,
                size="1",
                variant="ghost",
                **T.tone_scheme("error"),
            ),
            spacing="2",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _draft_edit_mode(draft: DraftVM) -> rx.Component:
    is_busy = RepliesState.busy_draft_id == draft.id
    return rx.vstack(
        rx.text_area(
            value=RepliesState.edit_text,
            on_change=RepliesState.set_edit_text,
            width="100%",
            rows="3",
        ),
        rx.hstack(
            rx.button(
                rx.cond(is_busy, loading_spinner("sm"), rx.icon("send", size=14)),
                "Guardar y enviar",
                on_click=RepliesState.save_and_send(draft.id),
                disabled=is_busy,
                size="1",
                variant="soft",
                **T.tone_scheme("ok"),
            ),
            rx.button(
                "Cancelar",
                on_click=RepliesState.cancel_edit,
                disabled=is_busy,
                size="1",
                variant="ghost",
            ),
            spacing="2",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _draft_card(draft: DraftVM) -> rx.Component:
    is_editing = RepliesState.editing_draft_id == draft.id
    return card(
        rx.vstack(
            rx.hstack(
                sentiment_badge(draft.sentiment_label),
                mono(draft.source_id, size="1"),
                rx.spacer(),
                rx.text(draft.created_at, size="1", color=T.TEXT_MUTED),
                align="center",
                spacing="2",
                width="100%",
            ),
            rx.text(
                rx.cond(draft.comment_text != "", draft.comment_text, "Sin texto"),
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.box(
                rx.icon("corner-down-right", size=13, color=T.TEXT_FAINT),
                display="inline-block",
                padding_left="0.25rem",
            ),
            rx.cond(is_editing, _draft_edit_mode(draft), _draft_view_mode(draft)),
            spacing="2",
            align_items="start",
        )
    )


def _replies_list() -> rx.Component:
    return rx.cond(
        RepliesState.is_loading,
        rx.vstack(_card_skeleton(), spacing="3", width="100%"),
        rx.cond(
            RepliesState.has_pending_drafts,
            rx.vstack(rx.foreach(RepliesState.drafts, _draft_card), spacing="3", width="100%"),
            _replies_empty_state(),
        ),
    )


def _replies_section() -> rx.Component:
    return section(
        "Borradores asistidos",
        _replies_load_error_block(),
        _replies_generate_error_block(),
        _replies_action_error_block(),
        _replies_list(),
        description=(
            "Respuestas ya redactadas para comentarios positivos en contenido propio. "
            "Nada se envía sin que lo apruebes o edites primero — el borrador nunca "
            "se publica por su cuenta."
        ),
        actions=[_refresh_drafts_button(), _generate_drafts_button()],
    )


def inbox_topbar() -> rx.Component:
    return page_header(
        "Interacciones",
        "Comentarios de tus Reels y publicaciones de las últimas 2 semanas — elige cuáles "
        "monitorear",
        rx.cond(InboxState.has_connections, _connection_selector(), rx.fragment()),
    )


def inbox_index() -> rx.Component:
    return app_shell(
        inbox_topbar(),
        _body(),
    )
