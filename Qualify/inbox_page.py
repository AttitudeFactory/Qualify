"""Inbox content screen (Fase 1 Parte 4-B, B2 UI slice) — Reels from the last 2 weeks,
with a switch to turn monitoring on/off per Reel.

Built on the `ui` shell (`app_shell` / `page_header` / `page_body`); badges and callouts
follow the design-system tones (docs/design-system.md). Adds the `/inbox` route only.

Deliberately minimal for this slice: no comment/thread view, no rich media preview beyond
a thumbnail + caption snippet. The goal is to make the monitoring decision visible and
actionable, not to redesign the screen.

`_sync_section()` (2026-08-15) is a TEMPORARY manual trigger for `InboxService.
sync_comments` — see `inbox_state.py`'s module docstring for why. It exists to prove the
Meta → Postgres round trip end-to-end before any scheduler/Celery wiring exists, and is
styled with the design system's `demo_notice` shape (dashed warn border + a "TEMPORAL"
badge) specifically so it reads as scaffolding, not a shipped feature.
"""

from __future__ import annotations

import reflex as rx

from .inbox_state import InboxState
from .inbox_vm import CandidateMediaVM
from .publishing_vm import ConnectionOptionVM
from .ui import app_shell, callout, empty_state, page_body, page_header
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
    return rx.cond(
        candidate.thumbnail_url != "",
        rx.image(
            src=candidate.thumbnail_url,
            width="72px",
            height="72px",
            object_fit="cover",
            border_radius="0.5rem",
        ),
        rx.center(
            rx.icon("film", size=26, color=T.TEXT_FAINT),
            width="72px",
            height="72px",
            border_radius="0.5rem",
            background=T.SURFACE_BG_RAISED,
            flex_shrink="0",
        ),
    )


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
        rx.text(
            rx.cond(candidate.is_monitored, "Monitoreado", "No monitoreado"),
            size="1",
            color=rx.cond(candidate.is_monitored, T.tone_color("ok", 10), T.TEXT_FAINT),
        ),
        spacing="1",
        align="center",
    )


def _candidate_card_content(candidate: CandidateMediaVM) -> rx.Component:
    return rx.box(
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
        border=T.BORDER,
        border_radius=T.RADIUS_CARD,
        background=T.SURFACE_BG,
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
    return rx.box(
        rx.hstack(
            rx.skeleton(rx.box(width="72px", height="72px", border_radius=T.RADIUS_CONTROL)),
            rx.vstack(
                rx.skeleton(rx.box(height="1.25rem", width="220px")),
                rx.skeleton(rx.box(height="1rem", width="140px")),
                spacing="2",
                align_items="start",
            ),
            spacing="3",
            align="center",
        ),
        padding="1rem 1.25rem",
        border=T.BORDER,
        border_radius=T.RADIUS_CARD,
        width="100%",
        aria_busy="true",
    )


def _no_connections_state() -> rx.Component:
    return empty_state(
        "link-2-off",
        "No hay cuentas de Instagram listas para monitorear",
        "Conecta una cuenta de Instagram con el permiso de comentarios en "
        "Conexiones para elegir qué contenido monitorear.",
        action=rx.link(
            rx.button(rx.icon("link", size=16), "Ir a Conexiones", size="3"),
            href="/connections",
        ),
    )


def _empty_candidates_state() -> rx.Component:
    return empty_state(
        "film",
        "Sin Reels en las últimas 2 semanas",
        "Esta cuenta no publicó Reels en los últimos 14 días.",
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
    )


def _sync_now_button() -> rx.Component:
    return rx.button(
        rx.cond(
            InboxState.is_syncing,
            rx.spinner(size="2"),
            rx.icon("refresh-cw", size=16),
        ),
        rx.cond(InboxState.is_syncing, "Sincronizando...", "Sincronizar comentarios"),
        on_click=InboxState.sync_comments,
        disabled=~InboxState.can_sync,
        size="2",
        variant="surface",
        color_scheme="amber",
    )


def _sync_result_block() -> rx.Component:
    # `truncated` (QUA-88): the Meta call budget ran out mid-sync. Still a success —
    # whatever synced is real — so this stays the "grass" callout, just with a qualifier
    # appended, never the error callout below.
    return rx.cond(
        InboxState.sync_result,
        rx.callout(
            (
                "Reels revisados: "
                + InboxState.sync_result.media_checked.to_string()
                + " · Comentarios nuevos: "
                + InboxState.sync_result.new_comments.to_string()
                + rx.cond(
                    InboxState.sync_result.truncated,
                    " · Sincronización parcial: se alcanzó el límite de llamadas, "
                    "sincroniza de nuevo en unos minutos para completar.",
                    "",
                )
            ),
            icon="check",
            color_scheme="grass",
            width="100%",
        ),
        rx.fragment(),
    )


def _sync_error_block() -> rx.Component:
    return rx.cond(
        InboxState.sync_error != "",
        rx.callout(
            InboxState.sync_error, icon="triangle-alert", color_scheme="tomato", width="100%"
        ),
        rx.fragment(),
    )


def _sync_section() -> rx.Component:
    """TEMPORARY manual sync affordance — see this module's docstring. Deliberately
    styled with the design system's `demo_notice` shape (dashed warn border) so it visually
    reads as scaffolding rather than a shipped feature."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.badge("TEMPORAL", color_scheme="amber", variant="solid", size="1"),
                rx.text(
                    "Disparador manual de sync_comments — solo para pruebas end-to-end.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.spacer(),
                _sync_now_button(),
                spacing="2",
                align="center",
                width="100%",
            ),
            _sync_result_block(),
            _sync_error_block(),
            spacing="2",
            width="100%",
        ),
        padding="0.75rem 1rem",
        border=f"1px dashed {T.tone_color('warn', 7)}",
        border_radius=T.RADIUS_CONTROL,
        background=T.tone_color("warn", 2),
        margin=f"0 {T.PAGE_X} 1.5rem {T.PAGE_X}",
        width=f"calc(100% - 2 * {T.PAGE_X})",
    )


def inbox_topbar() -> rx.Component:
    return page_header(
        "Contenido de Instagram",
        "Reels de las últimas 2 semanas — elige cuáles monitorear",
        rx.cond(InboxState.has_connections, _connection_selector(), rx.fragment()),
    )


def inbox_index() -> rx.Component:
    return app_shell(
        inbox_topbar(),
        rx.cond(InboxState.has_connections, _sync_section(), rx.fragment()),
        _body(),
    )
