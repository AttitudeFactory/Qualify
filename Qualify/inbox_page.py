"""Inbox content screen (Fase 1 Parte 4-B, B2 UI slice) — Reels from the last 2 weeks,
with a switch to turn monitoring on/off per Reel.

Same visual language as `connections_page.py`/`publishing_page.py`: badges/callouts from
the shared color-scheme convention, the shared sidebar/topbar shape. Adds the `/inbox`
route only; does not touch `connections_page.py` or `publishing_page.py`.

Deliberately minimal for this slice: no comment/thread view, no "sync now" button (see
`inbox_provider.py`'s module docstring — `sync_comments` is not wired here), no rich
media preview beyond a thumbnail + caption snippet. The goal is to make the monitoring
decision visible and actionable, not to redesign the screen.
"""

from __future__ import annotations

import reflex as rx

from .components import sidebar
from .inbox_state import InboxState
from .inbox_vm import CandidateMediaVM
from .publishing_vm import ConnectionOptionVM


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
            rx.icon("film", size=26, color=rx.color("gray", 8)),
            width="72px",
            height="72px",
            border_radius="0.5rem",
            background=rx.color("gray", 3),
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
            color=rx.cond(candidate.is_monitored, rx.color("grass", 10), rx.color("gray", 9)),
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
                    rx.icon("clock", size=13, color=rx.color("gray", 9)),
                    rx.text(candidate.posted_at, size="1", color=rx.color("gray", 10)),
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
        border=f"1px solid {rx.color('gray', 5)}",
        border_radius="0.75rem",
        background=rx.color("gray", 2),
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
            rx.skeleton(rx.box(width="72px", height="72px", border_radius="0.5rem")),
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
        border=f"1px solid {rx.color('gray', 5)}",
        border_radius="0.75rem",
        width="100%",
    )


def _no_connections_state() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon("link-2-off", size=40, color=rx.color("gray", 8)),
            rx.heading("No hay cuentas de Instagram listas para monitorear", size="5"),
            rx.text(
                "Conecta una cuenta de Instagram con el permiso de comentarios en "
                "Conexiones para elegir qué contenido monitorear.",
                size="2",
                color=rx.color("gray", 10),
                text_align="center",
                max_width="420px",
            ),
            rx.link(
                rx.button(rx.icon("link", size=16), "Ir a Conexiones", size="3"),
                href="/connections",
            ),
            spacing="3",
            align="center",
        ),
        padding="4rem 2rem",
        width="100%",
    )


def _empty_candidates_state() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon("film", size=40, color=rx.color("gray", 8)),
            rx.heading("Sin Reels en las últimas 2 semanas", size="5"),
            rx.text(
                "Esta cuenta no publicó Reels en los últimos 14 días.",
                size="2",
                color=rx.color("gray", 10),
                text_align="center",
            ),
            spacing="3",
            align="center",
        ),
        padding="4rem 2rem",
        width="100%",
    )


def _connections_error() -> rx.Component:
    return rx.box(
        rx.callout(
            InboxState.connections_error,
            icon="triangle-alert",
            color_scheme="tomato",
            width="100%",
        ),
        padding="0 2rem 2rem 2rem",
        width="100%",
    )


def _load_error() -> rx.Component:
    return rx.box(
        rx.callout(
            InboxState.load_error, icon="triangle-alert", color_scheme="tomato", width="100%"
        ),
        padding="0 2rem 2rem 2rem",
        width="100%",
    )


def _action_error() -> rx.Component:
    """Error from a toggle action, shown ABOVE the list rather than replacing it: the
    Reels on screen are still valid, one toggle failed."""
    return rx.box(
        rx.callout(
            InboxState.action_error, icon="triangle-alert", color_scheme="amber", width="100%"
        ),
        padding="0 2rem 1rem 2rem",
        width="100%",
    )


def _candidates_body() -> rx.Component:
    return rx.cond(
        InboxState.is_loading_candidates,
        rx.vstack(
            _card_skeleton(),
            _card_skeleton(),
            spacing="3",
            width="100%",
            padding="0 2rem 2rem 2rem",
        ),
        rx.cond(
            InboxState.show_empty_state,
            _empty_candidates_state(),
            rx.vstack(
                rx.foreach(InboxState.candidates, _candidate_card),
                spacing="3",
                width="100%",
                padding="0 2rem 2rem 2rem",
            ),
        ),
    )


def _body() -> rx.Component:
    return rx.vstack(
        rx.cond(InboxState.action_error != "", _action_error(), rx.fragment()),
        rx.cond(
            InboxState.connections_error != "",
            _connections_error(),
            rx.cond(
                InboxState.is_loading_connections,
                rx.box(_card_skeleton(), padding="0 2rem 2rem 2rem", width="100%"),
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
        width="100%",
        spacing="0",
    )


def inbox_topbar() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.heading("Contenido de Instagram", size="6"),
            rx.text(
                "Reels de las últimas 2 semanas — elige cuáles monitorear",
                size="2",
                color=rx.color("gray", 10),
            ),
            spacing="0",
            align_items="start",
        ),
        rx.spacer(),
        rx.cond(InboxState.has_connections, _connection_selector(), rx.fragment()),
        rx.color_mode.button(),
        width="100%",
        padding="1.5rem 2rem 1rem 2rem",
        align="center",
    )


def inbox_index() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.vstack(
            inbox_topbar(),
            _body(),
            width="100%",
            spacing="4",
            align_items="start",
        ),
        width="100%",
        spacing="0",
        align_items="start",
    )
