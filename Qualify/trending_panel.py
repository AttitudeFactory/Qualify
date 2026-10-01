"""The "Tendencias e inspiración" panel (QUA-113, Fase 1) — moved out of
`stories_page.py` unchanged in look and behavior, bound to `TrendingState`
(`trending_state.py`) instead of `StoriesState`, so any publish flow can show it.

Reference only: Meta's trending audio (`GET /ig_audio`, needs the active flow's
account — `TrendingState.audio_connection_id`) and QUA-107's TikTok/Instagram trending
content (ScrapeCreators, no account needed). Nothing here is ever fetched on screen
load, and nothing here ever reaches a publish call.
"""

from __future__ import annotations

import reflex as rx

from .stories_vm import TrendAudioOptionVM, TrendingVideoVM
from .trending_state import TrendingState
from .ui import card, section
from .ui import tokens as T

# ---------------------------------------------------------------------------
# Meta trending-audio reference (`GET /ig_audio`) — informational only.


def _trend_option(option: TrendAudioOptionVM) -> rx.Component:
    """One row of the compact Meta audio list — title first (primary), artist and
    duration secondary, the whole row clickable. Deliberately a plain list row, not
    a card: no border box, no thumbnail (Meta's `ig_audio` never carries cover art).

    The play button is a SIBLING of the selection button, never nested inside it —
    a `<button>` cannot contain another `<button>` per the HTML5 spec."""
    selected = TrendingState.selected_trend_audio_id == option.audio_id
    is_playing_this = (
        TrendingState.playing_audio_id == option.audio_id
    ) & TrendingState.is_audio_playing
    return rx.hstack(
        rx.box(
            rx.cond(
                option.has_preview,
                rx.button(
                    rx.cond(is_playing_this, rx.icon("pause", size=12), rx.icon("play", size=12)),
                    variant="ghost",
                    color_scheme=rx.cond(is_playing_this, "iris", "gray"),
                    size="1",
                    on_click=TrendingState.toggle_audio_preview(
                        option.audio_id, option.preview_url
                    ),
                ),
            ),
            width="1.75rem",
            flex_shrink="0",
        ),
        rx.button(
            rx.hstack(
                rx.cond(
                    selected,
                    rx.icon("circle-check", size=14, color=rx.color("iris", 9), flex_shrink="0"),
                    rx.icon("music", size=14, color=T.TEXT_FAINT, flex_shrink="0"),
                ),
                rx.vstack(
                    rx.text(option.title, size="2", weight="medium"),
                    rx.cond(
                        option.artist_or_creator != "",
                        rx.text(option.artist_or_creator, size="1", color=T.TEXT_MUTED),
                    ),
                    align_items="start",
                    spacing="0",
                ),
                rx.spacer(),
                rx.cond(
                    option.duration_label != "",
                    rx.text(option.duration_label, size="1", color=T.TEXT_FAINT, flex_shrink="0"),
                ),
                align="center",
                spacing="3",
                width="100%",
                padding_right="0.5rem",
            ),
            variant="ghost",
            color_scheme=rx.cond(selected, "iris", "gray"),
            background=rx.cond(selected, rx.color("iris", 3), "transparent"),
            border_radius="0",
            size="2",
            width="100%",
            on_click=TrendingState.select_trend_audio(option.audio_id, option.title),
        ),
        align="center",
        spacing="0",
        width="100%",
        padding_right="0.5rem",
        border_bottom=f"1px solid {rx.color('gray', 4)}",
    )


def _trend_audio_section() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.button(
                rx.icon("sparkles", size=14),
                "Sugerir audio en tendencia",
                variant="soft",
                size="2",
                loading=TrendingState.is_loading_trend,
                disabled=TrendingState.audio_connection_id == "",
                on_click=TrendingState.suggest_audio,
            ),
            rx.cond(
                TrendingState.selected_trend_audio_id != "",
                rx.badge(
                    TrendingState.selected_trend_audio_title,
                    rx.icon("x", size=12, on_click=TrendingState.clear_trend_audio),
                    variant="soft",
                    color_scheme="iris",
                    size="2",
                ),
            ),
            align="center",
            spacing="2",
            wrap="wrap",
        ),
        rx.hstack(
            rx.input(
                rx.input.slot(rx.icon("search", size=14)),
                placeholder="Buscar audio por nombre o artista…",
                value=TrendingState.audio_search_query,
                on_change=TrendingState.set_audio_search_query,
                disabled=TrendingState.audio_connection_id == "",
                size="2",
                width="100%",
            ),
            rx.button(
                "Buscar",
                variant="soft",
                size="2",
                loading=TrendingState.is_loading_trend,
                disabled=TrendingState.audio_connection_id == "",
                on_click=TrendingState.search_audio,
            ),
            align="center",
            spacing="2",
            width="100%",
        ),
        rx.text(
            "Solo una referencia para ti — no se adjunta a la publicación.",
            size="1",
            color=T.TEXT_FAINT,
        ),
        rx.cond(
            TrendingState.trend_expanded & (TrendingState.trend_options.length() > 0),
            rx.vstack(
                rx.hstack(
                    rx.text("Resultados", size="1", weight="medium", color=T.TEXT_MUTED),
                    rx.spacer(),
                    rx.button(
                        rx.icon("x", size=12),
                        "Ocultar",
                        variant="soft",
                        color_scheme="gray",
                        size="1",
                        on_click=TrendingState.close_trend_audio,
                    ),
                    align="center",
                    width="100%",
                    padding_bottom="0.25rem",
                ),
                rx.foreach(TrendingState.trend_options, _trend_option),
                spacing="0",
                width="100%",
            ),
        ),
        width="100%",
        spacing="2",
        align_items="start",
    )


# ---------------------------------------------------------------------------
# QUA-107: ScrapeCreators trending discovery — TikTok + Instagram, reference only.
# Independent of the connection selector above: these buttons are never disabled by
# `audio_connection_id`, unlike `_trend_audio_section`'s Meta-backed suggestion.


def _trending_thumbnail(candidate: TrendingVideoVM) -> rx.Component:
    return rx.cond(
        candidate.has_thumbnail,
        rx.image(
            src=candidate.thumbnail_url,
            width="56px",
            height="56px",
            object_fit="cover",
            border_radius="0.5rem",
            flex_shrink="0",
        ),
        rx.center(
            rx.icon("film", size=20, color=T.TEXT_FAINT),
            width="56px",
            height="56px",
            border_radius="0.5rem",
            background=T.SURFACE_BG_RAISED,
            flex_shrink="0",
        ),
    )


def _song_detail_panel() -> rx.Component:
    """Renders `TrendingState.song_detail` — only mounted once it is non-`None` (see
    `_trending_video_card`'s guard), so no field here needs its own None-check
    besides `user_count`/`recommend_status`, which the vendor may omit."""
    detail = TrendingState.song_detail
    is_playing_this = (
        TrendingState.playing_audio_id == detail.audio_id
    ) & TrendingState.is_audio_playing
    return rx.vstack(
        rx.text(detail.display_label, size="2", weight="medium"),
        rx.cond(
            detail.has_preview,
            rx.hstack(
                rx.button(
                    rx.cond(is_playing_this, rx.icon("pause", size=12), rx.icon("play", size=12)),
                    variant="soft",
                    color_scheme=rx.cond(is_playing_this, "iris", "gray"),
                    size="1",
                    on_click=TrendingState.toggle_audio_preview(
                        detail.audio_id, detail.preview_url
                    ),
                ),
                rx.text("Escuchar preview", size="1", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
        ),
        rx.cond(
            detail.has_user_count,
            rx.hstack(
                rx.icon("users", size=12, color=T.TEXT_FAINT),
                rx.text(detail.user_count, " videos la usan", size="1", color=T.TEXT_MUTED),
                spacing="1",
            ),
        ),
        rx.cond(
            detail.has_recommend_status,
            rx.hstack(
                rx.icon("flame", size=12, color=T.TEXT_FAINT),
                rx.text(
                    "Puntaje de tendencia del vendor: ",
                    detail.recommend_status,
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                spacing="1",
            ),
        ),
        rx.hstack(
            rx.button(
                "Usar esta canción",
                size="1",
                variant="soft",
                color_scheme="iris",
                on_click=TrendingState.select_trend_audio(detail.audio_id, detail.title),
            ),
            rx.button(
                rx.icon("search", size=12),
                "Buscar en Meta",
                size="1",
                variant="soft",
                color_scheme="gray",
                disabled=TrendingState.audio_connection_id == "",
                loading=TrendingState.is_loading_trend,
                on_click=TrendingState.search_song_on_meta(detail.title),
            ),
            spacing="2",
            wrap="wrap",
        ),
        spacing="2",
        padding="0.5rem",
        background=T.SURFACE_BG_RAISED,
        border_radius="0.5rem",
        align_items="start",
        width="100%",
    )


def _trending_video_card(candidate: TrendingVideoVM) -> rx.Component:
    is_expanded = TrendingState.expanded_song_id == candidate.music_id
    return rx.box(
        rx.hstack(
            _trending_thumbnail(candidate),
            rx.vstack(
                rx.text(
                    rx.cond(candidate.caption != "", candidate.caption, "(sin descripción)"),
                    size="2",
                    weight="medium",
                    max_width="360px",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.text(candidate.author_label, size="1", color=T.TEXT_MUTED),
                rx.hstack(
                    rx.text("♥ ", candidate.likes_label, size="1", color=T.TEXT_FAINT),
                    rx.text("💬 ", candidate.comments_label, size="1", color=T.TEXT_FAINT),
                    rx.cond(
                        candidate.plays_label != "",
                        rx.text("▶ ", candidate.plays_label, size="1", color=T.TEXT_FAINT),
                    ),
                    spacing="3",
                ),
                rx.cond(
                    candidate.permalink != "",
                    rx.link("Ver original", href=candidate.permalink, target="_blank", size="1"),
                ),
                align_items="start",
                spacing="1",
            ),
            align_items="start",
            spacing="3",
            width="100%",
        ),
        rx.box(
            rx.cond(
                candidate.has_music,
                rx.vstack(
                    rx.button(
                        "Ver detalle de la canción",
                        variant="ghost",
                        size="1",
                        loading=is_expanded & TrendingState.is_loading_song_detail,
                        on_click=TrendingState.expand_song(
                            candidate.music_id, candidate.music_title
                        ),
                    ),
                    rx.cond(
                        is_expanded,
                        rx.cond(TrendingState.song_detail, _song_detail_panel()),
                    ),
                    spacing="1",
                    width="100%",
                ),
            ),
            min_height="2.25rem",
            margin_top="0.5rem",
            width="100%",
        ),
        padding="0.75rem",
        border=f"1px solid {rx.color('gray', 5)}",
        border_radius=T.RADIUS_CARD,
        width="100%",
    )


def _trending_platform_section(
    *,
    label: str,
    icon: str,
    items: rx.Var[list[TrendingVideoVM]],
    expanded: rx.Var[bool],
    is_loading: rx.Var[bool],
    on_toggle: rx.event.EventHandler,
    on_refresh: rx.event.EventHandler,
) -> rx.Component:
    """One platform's trending block, full width — stacked with its sibling below
    (never a side-by-side column) precisely because a TikTok card can expand a song
    detail panel inline and an Instagram one never does (Reels carry no music), so
    two columns of these next to each other drift out of alignment the moment one
    expands. Stacking removes the "must match height" problem structurally instead
    of bounding it with a fixed/scrollable height.

    The main button drives fetch AND collapse/expand (follow-up: "cómo cierro
    esto") — `on_toggle` never re-fetches once `items` is already cached, only the
    very first click per platform does. The separate refresh icon (follow-up: "cómo
    actualizo") ALWAYS re-fetches, bypassing that cache — it only appears once there
    is something to refresh."""
    return rx.vstack(
        rx.hstack(
            rx.button(
                rx.icon(icon, size=14),
                label,
                rx.cond(
                    items.length() > 0,
                    rx.icon(rx.cond(expanded, "chevron-up", "chevron-down"), size=14),
                    rx.fragment(),
                ),
                variant="soft",
                size="2",
                loading=is_loading,
                on_click=on_toggle,
            ),
            rx.cond(
                items.length() > 0,
                rx.icon_button(
                    rx.icon("refresh-cw", size=14),
                    variant="ghost",
                    color_scheme="gray",
                    size="2",
                    loading=is_loading,
                    title="Actualizar con contenido nuevo",
                    on_click=on_refresh,
                ),
                rx.fragment(),
            ),
            align="center",
            spacing="2",
        ),
        rx.cond(
            expanded & (items.length() > 0),
            rx.vstack(rx.foreach(items, _trending_video_card), spacing="2", width="100%"),
        ),
        width="100%",
        spacing="2",
        align_items="start",
    )


def _trending_discovery_section() -> rx.Component:
    """QUA-107: TikTok + Instagram trending, shown for reference only. Explicit,
    operator-triggered per platform — never fetched on screen load."""
    return rx.vstack(
        rx.text(
            "Contenido y audios en tendencia, de forma general — no representa "
            "exclusivamente una región ni tu país. Solo referencia visual: nada se "
            "descarga ni se adjunta automáticamente a la Story.",
            size="1",
            color=T.TEXT_FAINT,
        ),
        _trending_platform_section(
            label="Tendencia en TikTok",
            icon="music",
            items=TrendingState.tiktok_trending,
            expanded=TrendingState.tiktok_trending_expanded,
            is_loading=TrendingState.is_loading_tiktok_trending,
            on_toggle=TrendingState.toggle_tiktok_trending,
            on_refresh=TrendingState.discover_tiktok_trending,
        ),
        rx.divider(),
        _trending_platform_section(
            label="Tendencia en Instagram",
            icon="film",
            items=TrendingState.instagram_trending,
            expanded=TrendingState.instagram_trending_expanded,
            is_loading=TrendingState.is_loading_instagram_trending,
            on_toggle=TrendingState.toggle_instagram_trending,
            on_refresh=TrendingState.discover_instagram_trending,
        ),
        width="100%",
        spacing="3",
    )


def _audio_preview_player() -> rx.Component:
    """The ONE shared player behind every play/pause button on this screen (Meta's
    audio list and the TikTok song-detail panel) — driven entirely by
    `playing_audio_url`/`is_audio_playing`, so only one preview is ever sounding at
    a time."""
    return rx.box(
        rx.audio(
            src=TrendingState.playing_audio_url,
            playing=TrendingState.is_audio_playing,
            controls=False,
            on_ended=TrendingState.audio_preview_stopped,
            on_error=TrendingState.audio_preview_stopped,
        ),
        display="none",
    )


def trending_card() -> rx.Component:
    return card(
        rx.vstack(
            _audio_preview_player(),
            rx.hstack(
                rx.icon("sparkles", size=T.ICON_MD, color=T.tone_color("info", 9)),
                rx.heading("Tendencias e inspiración", size="3", as_="h2"),
                spacing="2",
                align="center",
            ),
            rx.divider(),
            section("Audio en tendencia (Meta)", _trend_audio_section()),
            rx.divider(),
            section("Contenido en tendencia", _trending_discovery_section()),
            spacing="4",
            align_items="stretch",
            width="100%",
        ),
        padding="1.5rem",
    )
