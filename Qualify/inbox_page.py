"""Comentarios screen (`/inbox`). Since m-24842989 the body follows the owner's job:
(1) «Respuestas listas para aprobar», (2) «Comentarios por publicación», (3) the search
strip and, folded behind «Más opciones», which publications to review — the per-Reel
monitoring switches this screen started as (Fase 1 Parte 4-B, B2 UI slice).

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
renders the comment-sync controls: a manual «Buscar comentarios nuevos» button plus a
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
    UNSURE_INTENT_NOTE,
    CandidateMediaVM,
    CommentVM,
    IntentChipVM,
    ReelSummaryVM,
)
from .next_steps_vm import (
    ALL_CLEAR_BODY,
    ALL_CLEAR_TITLE,
    CREATE_LABEL,
    CREATE_ROUTE,
    DISMISS_LABEL,
    NEXT_PENDING_LABEL,
)
from .publishing_vm import ConnectionOptionVM
from .replies_state import RepliesState
from .replies_vm import (
    COMMERCIAL_BADGE,
    PUBLICATION_ALT_FALLBACK,
    REVIEW_BADGE,
    REVIEW_CONFIRM_LABEL,
    SOURCES_EMPTY,
    SOURCES_PRICE_NOTE,
    SOURCES_TITLE,
    DraftVM,
    SourceProductVM,
)
from .ui import (
    app_shell,
    callout,
    card,
    chat_bubble,
    empty_state,
    loading_spinner,
    media_thumb,
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
        rx.select.trigger(
            placeholder="Elige una cuenta de Instagram",
            width="100%",
            max_width="260px",
            class_name="q-inbox-tap",
        ),
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
            tone_badge("Buscando comentarios", "ok", icon="eye"),
            tone_badge("No buscamos comentarios", "neutral", icon="eye-off"),
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
                    rx.cond(candidate.caption != "", candidate.caption, "Sin texto"),
                    size="2",
                    weight="medium",
                    max_width="100%",
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
                    wrap="wrap",
                ),
                spacing="1",
                align_items="start",
                flex="1",
                min_width="0",
            ),
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
        "Conecta tu Instagram para ver tus comentarios",
        "Conecta tu cuenta en «Tus redes» y dale permiso para leer comentarios: "
        "aquí verás lo que te comentan y la respuesta lista para aprobar.",
        action=rx.link(
            rx.button(rx.icon("link", size=16), "Ir a Tus redes", size="3"),
            href="/connections",
        ),
    )


def _empty_candidates_state() -> rx.Component:
    return empty_state(
        "film",
        "Sin Reels ni publicaciones en las últimas 2 semanas",
        "Esta cuenta no subió Reels ni publicaciones a tu perfil en los últimos 14 días.",
        # N8 (m-24842961): comments come from publishing.
        action=rx.link(
            rx.button(rx.icon("wand-sparkles", size=16), CREATE_LABEL, size="3"),
            href=CREATE_ROUTE,
        ),
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


def _review_choice_section() -> rx.Component:
    """«Qué publicaciones revisar» — the per-Reel monitoring switches. Configuration,
    not the job the owner came for, so it lives last and folded (m-24842989)."""
    return section(
        "Qué publicaciones revisar",
        rx.cond(InboxState.action_error != "", _action_error(), rx.fragment()),
        rx.cond(InboxState.load_error != "", _load_error(), _candidates_body()),
        description=(
            "Elige de qué publicaciones de las últimas 2 semanas quieres que busquemos comentarios."
        ),
    )


def _more_options() -> rx.Component:
    """m-24842989 (qualify-ux §6, N6): the advanced settings behind «Más opciones» —
    same folded `rx.accordion` the Clarity screen uses for its configuration. Closed by
    default: the switches only appear when the owner opens it."""
    return rx.accordion.root(
        rx.accordion.item(
            header="Más opciones: qué publicaciones revisar",
            content=_review_choice_section(),
            value="more",
        ),
        collapsible=True,
        type="single",
        variant="ghost",
        width="100%",
        class_name="q-inbox-more",
    )


def _connected_body() -> rx.Component:
    """m-24842989: the order follows the owner's job, not the setup — (1) the replies
    ready to approve, (2) the comments by publication, (3) the search strip and, folded,
    which publications to review. The sync strip stays mounted outside the accordion so
    its 5-minute heartbeat keeps running while «Más opciones» is closed."""
    return rx.vstack(
        _replies_section(),
        _comments_section(),
        _sync_section(),
        _more_options(),
        spacing="5",
        width="100%",
        align_items="start",
        class_name="q-inbox-main",
    )


def _body() -> rx.Component:
    return page_body(
        rx.cond(
            InboxState.connections_error != "",
            _connections_error(),
            rx.cond(
                InboxState.is_loading_connections,
                _card_skeleton(),
                rx.cond(
                    ~InboxState.has_connections,
                    _no_connections_state(),
                    _connected_body(),
                ),
            ),
        ),
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
    warning tone and suffixed «revísalo»; the card explains it once, under the chips
    (`_comment_intent`)."""
    return rx.cond(
        chip.reliable,
        rx.cond(chip.commercial, tone_badge(chip.label, "info"), tone_badge(chip.label, "neutral")),
        tone_badge(chip.label + " · revísalo", "warn"),
    )


def _comment_intent(comment: CommentVM) -> rx.Component:
    return rx.cond(
        comment.intent_analyzed,
        rx.vstack(
            rx.hstack(
                rx.icon("target", size=13, color=T.TEXT_FAINT),
                rx.foreach(comment.intent_chips, _intent_chip),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            rx.cond(
                comment.intent_unsure,
                rx.text(UNSURE_INTENT_NOTE, size="1", color=T.TEXT_MUTED),
            ),
            spacing="1",
            align_items="start",
        ),
        rx.hstack(
            rx.icon("target", size=13, color=T.TEXT_FAINT),
            rx.text("Aún no sabemos si quiere comprar", size="1", color=T.TEXT_MUTED),
            spacing="2",
            align="center",
        ),
    )


def _reply_by_dm_button(comment: CommentVM) -> rx.Component:
    """m-24789646: continue this comment in private — opens its query in Conversaciones
    with a draft; nothing is sent from here."""
    return rx.button(
        rx.icon("send", size=T.ICON_SM),
        "Escribirle en privado",
        variant="soft",
        size="2",
        loading=InboxState.replying_dm_id == comment.message_id,
        disabled=InboxState.replying_dm_id != "",
        on_click=InboxState.reply_by_dm(comment.message_id),
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
                # m-24842988: the model's score is an internal number — not shown.
                sentiment_badge(comment.sentiment_label),
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
                rx.spacer(),
                _reply_by_dm_button(comment),
                spacing="2",
                align="center",
                width="100%",
                wrap="wrap",
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
            stat_card("Sin revisar", InboxState.global_summary.not_analyzed, "neutral"),
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
            "Resumen de tus comentarios",
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

    - «Buscando comentarios» — synced, inside its 14-day window;
    - «Buscando comentarios · fecha por confirmar» — synced, but its publication date
      was not read yet (a Reel monitored before QUA-149), so expiry cannot be judged yet;
    - «Ya no buscamos comentarios» — its window ended: no longer synced, history kept;
    - «No buscamos comentarios» — turned off (by the user, or deleted on Instagram).

    Same `tone_badge` family as `_reel_sentiment_chips`. Decoration only — never hides the
    card or anything inside it."""
    return rx.match(
        reel.monitoring_state,
        (MONITORING_ACTIVE, tone_badge("Buscando comentarios", "ok", icon="eye")),
        (
            MONITORING_PENDING,
            tone_badge("Buscando comentarios · fecha por confirmar", "info", icon="clock"),
        ),
        (
            MONITORING_EXPIRED,
            tone_badge("Ya no buscamos comentarios", "warn", icon="calendar-x"),
        ),
        tone_badge("No buscamos comentarios", "neutral", icon="eye-off"),
    )


def _reel_sentiment_chips(reel: ReelSummaryVM) -> rx.Component:
    return rx.hstack(
        tone_badge("Positivos " + reel.positive.to_string(), "ok"),
        tone_badge("Neutros " + reel.neutral.to_string(), "neutral"),
        tone_badge("Negativos " + reel.negative.to_string(), "error"),
        tone_badge("Sin revisar " + reel.not_analyzed.to_string(), "neutral"),
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
                    rx.cond(reel.caption != "", reel.caption, "Sin texto"),
                    size="2",
                    weight="medium",
                    max_width="100%",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.hstack(
                    _format_badge(reel),
                    _reel_monitoring_badge(reel),
                    rx.icon("clock", size=13, color=T.TEXT_FAINT),
                    rx.text(reel.last_message_at, size="1", color=T.TEXT_MUTED),
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
                flex="1 1 12rem",
                min_width="0",
            ),
            rx.button(
                "Ver comentarios",
                on_click=lambda: InboxState.select_reel(reel.thread_id),
                size="2",
                variant="surface",
            ),
            spacing="3",
            align="center",
            width="100%",
            wrap="wrap",
        ),
        padding="1rem 1.25rem",
        # Full width of the body: every row's switch/actions line up on one right edge
        # instead of each card hugging its own caption.
        width="100%",
    )


def _reel_summaries_empty_state() -> rx.Component:
    return empty_state(
        "message-circle",
        "Todavía no tienes comentarios",
        "Cuando te comenten, aparecerán aquí agrupados por publicación.",
        action=_sync_now_button(),
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


def _missing_post_notice() -> rx.Component:
    return rx.cond(
        InboxState.missing_post_notice != "",
        callout(InboxState.missing_post_notice, "info"),
        rx.fragment(),
    )


def _reel_summaries_list() -> rx.Component:
    return rx.vstack(_missing_post_notice(), _reel_summaries_list_body(), spacing="3", width="100%")


def _reel_summaries_list_body() -> rx.Component:
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
            rx.icon("chevron-left", size=16),
            "Comentarios",
            on_click=InboxState.back_to_reel_list,
            variant="ghost",
            size="2",
            min_height="44px",
        ),
        rx.cond(
            reel,
            rx.hstack(
                _reel_thumbnail(reel),
                rx.vstack(
                    rx.text(
                        rx.cond(reel.caption != "", reel.caption, "Sin texto"),
                        size="3",
                        weight="medium",
                    ),
                    rx.hstack(
                        _format_badge(reel),
                        _reel_monitoring_badge(reel),
                        spacing="2",
                        align="center",
                        wrap="wrap",
                    ),
                    _reel_sentiment_chips(reel),
                    spacing="1",
                    align_items="start",
                    min_width="0",
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
    (FILTER_ALL, "Todos los tonos"),
    ("POS", "Positivos"),
    ("NEU", "Neutros"),
    ("NEG", "Negativos"),
    ("PENDING", "Sin revisar"),
]


def _sentiment_filter_item(value: str, label: str) -> rx.Component:
    return rx.select.item(label, value=value)


def _sentiment_filter_select() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(
            width="100%",
            max_width="180px",
            class_name="q-inbox-tap",
            aria_label="Filtrar por tono",
        ),
        rx.select.content(
            *[_sentiment_filter_item(value, label) for value, label in _SENTIMENT_FILTER_OPTIONS]
        ),
        value=InboxState.sentiment_filter,
        on_change=InboxState.set_sentiment_filter,
        size="2",
    )


# m-24789644: «Quieren comprar» = the comments whose intent signal under the current
# version is commercial. Same "ALL means no filter" convention as above.
_INTENT_FILTER_OPTIONS = [
    (FILTER_ALL, "Todos los comentarios"),
    (FILTER_COMMERCIAL, "Quieren comprar"),
]


def _intent_filter_select() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(
            width="100%",
            max_width="240px",
            class_name="q-inbox-tap",
            aria_label="Filtrar por interés en comprar",
        ),
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
        width="100%",
        max_width="320px",
        class_name="q-inbox-tap",
    )


def _thread_comments_empty_state() -> rx.Component:
    return empty_state(
        "message-circle",
        "Sin comentarios para este filtro",
        "Prueba con otro filtro o borra la búsqueda.",
        action=rx.button(
            "Quitar filtros",
            on_click=InboxState.clear_thread_filters,
            variant="soft",
            size="3",
            class_name="q-inbox-tap",
        ),
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


def _prioritize_button() -> rx.Component:
    """m-24842988: ONE «Ordenar por prioridad» — the sentiment pass (QUA-21) and the
    commercial-intent pass (m-24789644) chained on one click. Each stays its own
    background handler with its own guard, error and toast; still separate from
    `_sync_now_button()` (see the module docstring)."""
    return rx.button(
        rx.cond(
            InboxState.is_prioritizing,
            loading_spinner("sm"),
            rx.icon("list-ordered", size=16),
        ),
        rx.cond(InboxState.is_prioritizing, "Ordenando...", "Ordenar por prioridad"),
        on_click=[InboxState.analyze_sentiment, InboxState.analyze_intent],
        disabled=~InboxState.can_prioritize,
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
    # m-24842989: second block, under the replies ready to approve. Its actions sit in
    # a wrapping row of their own, not in the title row, so they never squeeze the
    # title at 360 px (N12).
    return section(
        "Comentarios por publicación",
        rx.hstack(
            _prioritize_button(),
            spacing="2",
            wrap="wrap",
        ),
        _analyze_error_block(),
        _analyze_intent_error_block(),
        rx.cond(~InboxState.is_showing_reel_detail, _global_summary_widget(), rx.fragment()),
        rx.cond(InboxState.is_showing_reel_detail, _reel_detail_view(), _reel_summaries_list()),
        description=(
            "Tus comentarios agrupados por publicación. Revisamos cada publicación durante "
            "2 semanas desde que la subes; después dejamos de buscar comentarios nuevos, "
            "pero los que ya tienes se quedan aquí."
        ),
    )


def _sync_now_button() -> rx.Component:
    return rx.button(
        rx.cond(
            InboxState.is_syncing,
            loading_spinner("sm"),
            rx.icon("refresh-cw", size=16),
        ),
        rx.cond(InboxState.is_syncing, "Buscando...", "Buscar comentarios nuevos"),
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
                    "Buscamos comentarios nuevos cada 5 minutos mientras tienes esta "
                    "pantalla abierta.",
                    size="2",
                    color=T.TEXT_MUTED,
                    flex="1 1 14rem",
                ),
                _sync_now_button(),
                _polling_timer(),
                spacing="2",
                align="center",
                width="100%",
                wrap="wrap",
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
        rx.cond(RepliesState.is_generating, "Preparando...", "Preparar respuestas"),
        on_click=RepliesState.generate_drafts,
        disabled=RepliesState.is_generating,
        size="2",
        variant="soft",
    )


def _refresh_drafts_button() -> rx.Component:
    """A secondary page control next to «Preparar respuestas»: an icon button on the glass
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
            aria_label="Actualizar respuestas",
        ),
        content="Actualizar respuestas",
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


_REPLIES_LIST_ID = "q-replies-list"


def _replies_sent_block() -> rx.Component:
    """m-24842961 (N3): a reply that went out ends in a confirmation that stays, with the
    next job — the next reply while people wait, else «¡Al día!» and the next publication
    — plus a soft «Entendido» that only closes it. Never only a toast."""
    next_button = rx.cond(
        RepliesState.has_pending_drafts,
        rx.button(
            NEXT_PENDING_LABEL,
            on_click=[RepliesState.dismiss_sent_notice, rx.scroll_to(_REPLIES_LIST_ID)],
            size="3",
            class_name="q-inbox-tap",
        ),
        rx.link(
            rx.button(
                rx.icon("wand-sparkles", size=16), CREATE_LABEL, size="3", class_name="q-inbox-tap"
            ),
            href=CREATE_ROUTE,
        ),
    )
    return rx.cond(
        RepliesState.sent_notice != "",
        card(
            rx.vstack(
                rx.hstack(
                    rx.icon("circle-check", size=T.ICON_MD, color=T.tone_color("ok", 11)),
                    rx.vstack(
                        rx.text(RepliesState.sent_notice, size="2", weight="medium"),
                        rx.cond(
                            RepliesState.has_pending_drafts,
                            rx.fragment(),
                            rx.text(
                                ALL_CLEAR_TITLE + " " + ALL_CLEAR_BODY,
                                size="2",
                                color=T.TEXT_MUTED,
                            ),
                        ),
                        spacing="0",
                        align_items="start",
                    ),
                    spacing="3",
                    align="start",
                ),
                rx.flex(
                    next_button,
                    rx.button(
                        DISMISS_LABEL,
                        on_click=RepliesState.dismiss_sent_notice,
                        variant="soft",
                        size="3",
                        class_name="q-inbox-tap",
                        **T.tone_scheme("neutral"),
                    ),
                    wrap="wrap",
                    gap="0.5rem",
                ),
                spacing="3",
                width="100%",
            ),
            padding="0.875rem 1rem",
            role="status",
        ),
    )


def _replies_load_error_block() -> rx.Component:
    return rx.cond(
        RepliesState.load_error != "",
        callout(RepliesState.load_error, "error"),
        rx.fragment(),
    )


def _replies_empty_state() -> rx.Component:
    # N8: an empty state always has a way out — here, preparing the replies.
    return empty_state(
        "message-square-text",
        "No hay respuestas por aprobar",
        "Cuando te comenten, prepara aquí las respuestas y apruébalas una por una.",
        action=_generate_drafts_button(),
    )


# -- Fase B (m-24789645): what the draft stands on, and why it needs a closer look ----------


def _source_row(product: SourceProductVM) -> rx.Component:
    """One catalog product the draft was given: its name and when it was last updated.
    Never its price — a public reply does not state one (D1)."""
    return rx.hstack(
        rx.icon("dot", size=14, color=T.TEXT_FAINT),
        rx.text(product.name, size="1", weight="medium"),
        rx.cond(
            product.updated_label != "",
            rx.text(product.updated_label, size="1", color=T.TEXT_FAINT),
            rx.fragment(),
        ),
        spacing="1",
        align="center",
        wrap="wrap",
    )


def _draft_sources(draft: DraftVM) -> rx.Component:
    """«Datos del catálogo usados»: the first few products in the open, the rest folded
    so a long catalog does not push the draft off a phone screen."""
    return rx.vstack(
        rx.hstack(
            rx.icon("package", size=13, color=T.TEXT_FAINT),
            rx.text(SOURCES_TITLE, size="1", weight="medium", color=T.TEXT_MUTED),
            spacing="2",
            align="center",
        ),
        rx.cond(
            draft.sources_count > 0,
            rx.vstack(rx.foreach(draft.sources_head, _source_row), spacing="0"),
            rx.text(SOURCES_EMPTY, size="1", color=T.TEXT_MUTED),
        ),
        rx.cond(
            draft.sources_rest.length() > 0,
            rx.accordion.root(
                rx.accordion.item(
                    header=rx.text(draft.sources_more_label, size="1"),
                    content=rx.vstack(rx.foreach(draft.sources_rest, _source_row), spacing="0"),
                    value="more",
                ),
                collapsible=True,
                variant="ghost",
                width="100%",
            ),
            rx.fragment(),
        ),
        rx.text(SOURCES_PRICE_NOTE, size="1", color=T.TEXT_FAINT),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _review_reason_row(reason: str) -> rx.Component:
    return rx.hstack(
        rx.icon("triangle-alert", size=13, color=T.tone_color("warn", 11), flex_shrink="0"),
        rx.text(reason, size="1"),
        spacing="2",
        align="start",
    )


def _review_note_row(note: str) -> rx.Component:
    """A soft note (a class the classifier is not sure about): a hint, not an alarm —
    neutral icon, faint text, no badge, no gate."""
    return rx.hstack(
        rx.icon("info", size=12, color=T.TEXT_FAINT, flex_shrink="0"),
        rx.text(note, size="1", color=T.TEXT_MUTED),
        spacing="2",
        align="start",
    )


def _draft_review_notes(draft: DraftVM) -> rx.Component:
    """Why this draft needs review (one plain sentence per blocking reason, warn tone),
    then the soft notes in a quieter style."""
    return rx.fragment(
        _draft_blocking_reasons(draft),
        rx.cond(
            draft.review_notes.length() > 0,
            rx.vstack(
                rx.foreach(draft.review_notes, _review_note_row),
                spacing="1",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
    )


def _draft_blocking_reasons(draft: DraftVM) -> rx.Component:
    return rx.cond(
        draft.needs_review,
        rx.vstack(
            rx.foreach(draft.review_reasons, _review_reason_row),
            rx.cond(
                draft.unsupported_claims != "",
                rx.text(draft.unsupported_claims, size="1", color=T.TEXT_MUTED),
                rx.fragment(),
            ),
            spacing="1",
            width="100%",
            align_items="start",
        ),
        rx.fragment(),
    )


def _review_confirm(draft: DraftVM) -> rx.Component:
    """The explicit «Revisé el borrador» a draft that needs review asks for before it
    can be sent. The state checks it again on the click (`send_block_reason`)."""
    return rx.cond(
        draft.needs_review,
        rx.checkbox(
            REVIEW_CONFIRM_LABEL,
            checked=RepliesState.reviewed_draft_ids.contains(draft.id),
            on_change=lambda checked: RepliesState.set_reviewed(draft.id, checked),
            size="2",
        ),
        rx.fragment(),
    )


def _send_locked(draft: DraftVM) -> rx.Var:
    """True while a draft that needs review has not been ticked as reviewed."""
    return draft.needs_review & ~RepliesState.reviewed_draft_ids.contains(draft.id)


def _draft_intents(draft: DraftVM) -> rx.Component:
    return rx.cond(
        draft.intent_chips.length() > 0,
        rx.hstack(
            rx.icon("target", size=13, color=T.TEXT_FAINT),
            rx.foreach(draft.intent_chips, _intent_chip),
            spacing="2",
            align="center",
            wrap="wrap",
        ),
        rx.fragment(),
    )


def _approve_label(draft: DraftVM) -> rx.Var:
    """N13: the button says who gets the answer — «Aprobar y responder a @ana» — and
    falls back to «Aprobar y responder» when the channel did not give the author."""
    return rx.cond(
        draft.author_username != "",
        "Aprobar y responder a @" + draft.author_username,
        "Aprobar y responder",
    )


def _draft_view_mode(draft: DraftVM) -> rx.Component:
    """Read-only: the prepared text plus the actions that decide it in one tap — see
    `replies_state.py`'s module docstring for why approve and send are folded together
    in this v1. N13: nothing is answered until the owner presses «Aprobar y responder».
    Main actions at `size="3"`, and the row wraps, so each one stays a ≥ 44 px target
    at 360 px (N12, `.q-inbox-main` in qualify-inbox.css)."""
    is_busy = RepliesState.busy_draft_id == draft.id
    is_regenerating = RepliesState.regenerating_draft_id == draft.id
    return rx.vstack(
        chat_bubble(rx.text(draft.generated_text, size="2"), direction="out"),
        _draft_review_notes(draft),
        _review_confirm(draft),
        # The main action alone and full width (a thumb target on a phone), the other
        # three under it; «Descartar» last and quiet, away from «Regenerar».
        rx.button(
            rx.cond(
                is_busy & ~is_regenerating,
                loading_spinner("sm"),
                rx.icon("check", size=16),
            ),
            _approve_label(draft),
            on_click=RepliesState.accept_and_send(draft.id),
            disabled=is_busy | _send_locked(draft),
            size="3",
            variant="soft",
            width="100%",
            **T.tone_scheme("ok"),
        ),
        rx.hstack(
            rx.button(
                rx.icon("pencil", size=16),
                "Editar",
                on_click=RepliesState.start_edit(draft.id, draft.generated_text),
                disabled=is_busy,
                size="3",
                variant="surface",
            ),
            rx.button(
                rx.cond(is_regenerating, loading_spinner("sm"), rx.icon("sparkles", size=16)),
                rx.cond(is_regenerating, "Regenerando...", "Regenerar"),
                on_click=RepliesState.regenerate(draft.id),
                disabled=is_busy,
                size="3",
                variant="surface",
            ),
            rx.spacer(),
            rx.button(
                rx.icon("x", size=16),
                "Descartar",
                on_click=RepliesState.discard_draft(draft.id),
                disabled=is_busy,
                size="3",
                variant="ghost",
                **T.tone_scheme("error"),
            ),
            spacing="2",
            wrap="wrap",
            width="100%",
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
            aria_label="Tu respuesta",
        ),
        _draft_review_notes(draft),
        _review_confirm(draft),
        rx.hstack(
            rx.button(
                rx.cond(is_busy, loading_spinner("sm"), rx.icon("check", size=16)),
                _approve_label(draft),
                on_click=RepliesState.save_and_send(draft.id),
                disabled=is_busy | _send_locked(draft),
                size="3",
                variant="soft",
                **T.tone_scheme("ok"),
            ),
            rx.button(
                "Cancelar",
                on_click=RepliesState.cancel_edit,
                disabled=is_busy,
                size="3",
                variant="ghost",
            ),
            spacing="2",
            wrap="wrap",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _draft_publication_thumb(draft: DraftVM) -> rx.Component:
    """The publication the comment was left on (m-24842989) — small, next to who wrote
    it. Its picture comes from the candidates the screen already loaded; without one the
    frame shows the generic icon. Not decorative here: it is the only thing on the card
    that names the publication, so its alt is the caption (else «Publicación»)."""
    return media_thumb(draft.media_thumbnail_url, size="48px", icon="image", alt=draft.media_alt)


def _draft_card(draft: DraftVM) -> rx.Component:
    """One reply waiting for approval: who commented and on which publication, the
    comment, then the prepared reply. No internal id on screen (m5 hallazgo 5). A
    commercial draft (m-24789645) adds «Quiere comprar», «Requiere revisión» and its
    reasons, the intent chips, and the catalog data the draft was given."""
    is_editing = RepliesState.editing_draft_id == draft.id
    return card(
        rx.vstack(
            rx.hstack(
                rx.cond(
                    draft.is_commercial,
                    tone_badge(COMMERCIAL_BADGE, "info", icon="shopping-bag"),
                    sentiment_badge(draft.sentiment_label),
                ),
                rx.cond(
                    draft.needs_review,
                    tone_badge(REVIEW_BADGE, "warn", icon="triangle-alert"),
                    rx.fragment(),
                ),
                rx.spacer(),
                rx.text(draft.created_at, size="1", color=T.TEXT_MUTED),
                align="center",
                spacing="2",
                width="100%",
                wrap="wrap",
            ),
            rx.hstack(
                _draft_publication_thumb(draft),
                rx.vstack(
                    rx.cond(
                        draft.author_username != "",
                        rx.text(
                            "@" + draft.author_username,
                            size="2",
                            weight="medium",
                            word_break="break-word",
                        ),
                    ),
                    # Which publication, in words: its day when we know it, else its
                    # caption (the fallback alt «Publicación» says nothing).
                    rx.cond(
                        draft.media_day != "",
                        rx.text(
                            "En tu publicación del " + draft.media_day,
                            size="1",
                            color=T.TEXT_MUTED,
                        ),
                    ),
                    rx.cond(
                        (draft.media_day == "") & (draft.media_alt != PUBLICATION_ALT_FALLBACK),
                        rx.text(
                            "En tu publicación «" + draft.media_alt + "»",
                            size="1",
                            color=T.TEXT_MUTED,
                            max_width="100%",
                            overflow="hidden",
                            text_overflow="ellipsis",
                            white_space="nowrap",
                        ),
                    ),
                    rx.text(
                        rx.cond(draft.comment_text != "", draft.comment_text, "Sin texto"),
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    align_items="start",
                    min_width="0",
                ),
                spacing="3",
                align="start",
                width="100%",
            ),
            _draft_intents(draft),
            rx.box(
                rx.icon("corner-down-right", size=13, color=T.TEXT_FAINT),
                display="inline-block",
                padding_left="0.25rem",
            ),
            rx.cond(is_editing, _draft_edit_mode(draft), _draft_view_mode(draft)),
            rx.cond(draft.is_commercial, _draft_sources(draft), rx.fragment()),
            spacing="2",
            align_items="start",
            width="100%",
        ),
        width="100%",
    )


def _replies_list() -> rx.Component:
    return rx.cond(
        RepliesState.is_loading,
        rx.vstack(_card_skeleton(), spacing="3", width="100%"),
        rx.cond(
            RepliesState.has_pending_drafts,
            rx.vstack(
                rx.foreach(RepliesState.drafts, _draft_card),
                spacing="3",
                width="100%",
                id=_REPLIES_LIST_ID,
            ),
            # Right after the last reply the confirmation already says «¡Al día!» with
            # its button; the empty state below it would repeat it.
            rx.cond(RepliesState.sent_notice != "", rx.fragment(), _replies_empty_state()),
        ),
    )


def _replies_title() -> rx.Var:
    """«Respuestas listas para aprobar ({n})» — n is the queue on screen (m-24842989),
    shown only when there is something to approve."""
    return rx.cond(
        RepliesState.has_pending_drafts,
        f"Respuestas listas para aprobar ({RepliesState.drafts.length()})",
        "Respuestas listas para aprobar",
    )


def _replies_section() -> rx.Component:
    """m-24842989: FIRST block of the screen — the people waiting come before any
    configuration. Its actions sit in a wrapping row under the title (N12)."""
    return section(
        _replies_title(),
        # With no drafts the empty state carries the one button (no duplicate row).
        rx.cond(
            RepliesState.has_pending_drafts,
            rx.hstack(
                _refresh_drafts_button(),
                _generate_drafts_button(),
                spacing="2",
                wrap="wrap",
            ),
        ),
        _replies_load_error_block(),
        _replies_generate_error_block(),
        _replies_action_error_block(),
        _replies_sent_block(),
        _replies_list(),
        description=(
            "Respuestas listas para los comentarios que te felicitan o preguntan por tus "
            "productos. Cada una sale en Instagram, debajo del comentario y a la vista de "
            "todos, solo cuando tú la apruebas."
        ),
    )


def inbox_topbar() -> rx.Component:
    return page_header(
        "Comentarios",
        "Lo que te comentaron en tus publicaciones de las últimas 2 semanas, con la "
        "respuesta lista para que la apruebes.",
        rx.cond(InboxState.has_connections, _connection_selector(), rx.fragment()),
    )


def inbox_index() -> rx.Component:
    return app_shell(
        inbox_topbar(),
        _body(),
    )
